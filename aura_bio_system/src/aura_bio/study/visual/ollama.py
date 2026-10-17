"""Fixed local Ollama vision adapter. No pulls, implicit swaps or cloud URLs."""
import base64
import json
import math
import os
import subprocess
import time
from urllib.parse import urlparse
import requests
from .schema import ProviderResponse
from .description import messages, description_schema
from ..schema import StudyError


def _windows_noncopy_utilization(fallback):
    """WDDM's aggregate NVIDIA reading can be desktop copy traffic alone.

    Keep 3D, compute, video and unknown engine work conservative. Only the
    measured copy-engine share is excluded; missing/invalid counters retain
    the NVIDIA reading. VRAM and loaded-model checks are independent.
    """
    command = ("$ErrorActionPreference='Stop'; "
               "@( (Get-Counter '\\GPU Engine(*)\\Utilization Percentage').CounterSamples | "
               "ForEach-Object { @{name=$_.InstanceName;value=$_.CookedValue} } ) | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, text=True, timeout=5,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            return fallback
        samples = json.loads(result.stdout)
        if isinstance(samples, dict):
            samples = [samples]
        if not isinstance(samples, list) or not samples:
            return fallback
        total = 0.0
        for sample in samples:
            name, value = sample['name'], float(sample['value'])
            if not isinstance(name, str) or 'engtype_' not in name.lower() or not math.isfinite(value) or value < 0:
                return fallback
            if name.lower().rsplit('engtype_', 1)[1] != 'copy':
                total += value
        return min(100.0, total)
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        return fallback


def gpu_free_mb():
    try:
        result=subprocess.run(['nvidia-smi','--query-gpu=memory.free,memory.total,utilization.gpu','--format=csv,noheader,nounits'],
                              capture_output=True,text=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        rows=[tuple(float(v.strip()) for v in line.split(',')) for line in result.stdout.splitlines()]
        if result.returncode or not rows: raise ValueError()
        free, total, utilization = rows[0]
        if os.name == 'nt' and len(rows) == 1 and utilization > 15:
            utilization = _windows_noncopy_utilization(utilization)
        return free, total, utilization
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        raise StudyError('resource_unknown','Cannot check free NVIDIA VRAM. Configure nvidia-smi before starting local vision; no inference started.') from exc


class OllamaVisionBackend:
    def __init__(self,http=None,url=None):
        self.isolated=http is None
        self.http=http or requests.Session(); self.url=(url or os.environ.get('AURA_OLLAMA_HOST') or os.environ.get('OLLAMA_HOST','http://127.0.0.1:11434')).rstrip('/')
        parsed=urlparse(self.url)
        if parsed.scheme!='http' or parsed.hostname not in {'localhost','127.0.0.1','::1'} or parsed.username or parsed.password:
            raise StudyError('invalid_config','Local vision requires a loopback Ollama URL; hosted processing uses a separate explicit provider.')

    def _request(self,method,path,**kwargs):
        try:
            response=getattr(self.http,method)(self.url+path,allow_redirects=False,**kwargs)
            if response.status_code>=300:
                data=response.json()
                code='out_of_memory' if 'memory' in str(data.get('error','')).lower() else 'provider_failed'
                raise StudyError(code,'Local vision request failed; native pack remains usable. No model/provider switch occurred.')
            return response.json()
        except StudyError: raise
        except requests.Timeout as exc: raise StudyError('provider_timeout','Local request timed out; completion is unknown. No automatic duplicate request.') from exc
        except Exception as exc: raise StudyError('provider_unavailable',f'Local vision unavailable ({type(exc).__name__}); configure the installed model explicitly.') from exc

    def preflight(self,config):
        models=self._request('get','/api/tags',timeout=5).get('models',[])
        model=next((m for m in models if m.get('name')==config.model or m.get('model')==config.model),None)
        if not model: raise StudyError('model_missing','Selected vision model is not installed. No model download was attempted.')
        identity=model.get('digest','')
        if not identity: raise StudyError('model_changed','Installed model did not report a digest.')
        if config.model_digest and identity!=config.model_digest: raise StudyError('model_changed','Installed model digest changed; start a new job.')
        info=self._request('post','/api/show',json={'model':config.model},timeout=5)
        if 'vision' not in info.get('capabilities',[]): raise StudyError('model_not_vision','Selected model does not advertise vision support.')
        loaded=self._request('get','/api/ps',timeout=5).get('models',[])
        other=[m for m in loaded if m.get('name')!=config.model and m.get('model')!=config.model]
        if other:
            managed=os.environ.get('AURA_STUDY_MANAGED_GENERATOR','aura-bio:v0')
            if not config.managed_swap or any(m.get('name')!=managed and m.get('model')!=managed for m in other):
                raise StudyError('busy_gpu','Another model is loaded. Free it yourself or explicitly approve swapping AURA’s managed generator; unrelated models are never unloaded.')
            self._request('post','/api/generate',json={'model':managed,'keep_alive':0},timeout=5)
        free,total,utilization=gpu_free_mb()
        target_loaded=any(m.get('name')==config.model or m.get('model')==config.model for m in loaded)
        # The selected model's own VRAM is already reserved when it is loaded.
        # Requiring another 384 MiB here rejects a healthy idle 4 GiB card.
        needed=max(512,model.get('size',0)/1024**2+256) if not target_loaded else 64
        if free<needed or utilization>15:
            raise StudyError('busy_gpu','Insufficient free VRAM or GPU is busy; vision deferred. No unrelated process was changed.')
        return identity

    def complete(self,input,*,repair=None,timeout_seconds=120):
        identity=self.preflight(input.config)
        start=time.monotonic()
        data=self._request('post','/api/chat',json={'model':input.config.model,'stream':False,'format':description_schema(repair,version=input.config.description_version),'think':input.config.think,'keep_alive':0,
            'messages':[{'role':'user','content':messages(input,repair),'images':[base64.b64encode(input.image).decode('ascii')]}],
            'options':{'temperature':0,'num_ctx':input.config.num_ctx,'num_predict':input.config.num_predict}},timeout=(5,max(1,timeout_seconds)))
        response=ProviderResponse(data.get('message',{}).get('content',''),'ollama',data.get('model',input.config.model),identity,
                                {'prompt_tokens':data.get('prompt_eval_count',0),'completion_tokens':data.get('eval_count',0)},time.monotonic()-start)
        if data.get('done_reason')=='length':
            error=StudyError('output_truncated','Vision output exceeded its budget; partial output retained for diagnosis, never certified or silently reuploaded.')
            error.responses=[response]
            raise error
        return response
