"""Opt-in Groq adapter. Owned PNG bytes only; secrets are never recorded."""
import base64
import os
import time
import requests
from .schema import ProviderResponse
from .description import messages
from ..schema import StudyError


class GroqVisionBackend:
    def __init__(self,http=None):
        self.http=http or requests.Session(); self.isolated=http is None

    def complete(self,input,*,repair=None,timeout_seconds=120):
        if not all(input.config.consent.get(k) is True for k in ('external_allowed','images','hints')):
            raise StudyError('consent_required','This job has not approved uploading owned image crops and OCR/caption hints.')
        key=os.environ.get('GROQ_API_KEY')
        if not key: raise StudyError('key_missing','Set GROQ_API_KEY in the server environment; it is never stored in a pack.')
        if input.config.model_digest: raise StudyError('invalid_config','Hosted models do not expose a pinned local digest; do not invent one.')
        start=time.monotonic()
        body={'model':input.config.model,'temperature':0,'max_completion_tokens':input.config.num_predict,
              'response_format':{'type':'json_object'},'reasoning_effort':'none',
              'messages':[{'role':'user','content':[{'type':'text','text':messages(input,repair)},
                  {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(input.image).decode('ascii')}}]}]}
        try:
            response=self.http.post('https://api.groq.com/openai/v1/chat/completions',json=body,
                                    headers={'Authorization':'Bearer '+key},timeout=(5,max(1,timeout_seconds)),allow_redirects=False)
            if response.status_code==429:
                error=StudyError('rate_limited','Hosted rate limit reached. Completed figures retained; resume explicitly after the reported reset.')
                try: error.resume_at=time.time()+max(1,float(response.headers.get('retry-after','60')))
                except ValueError: error.resume_at=time.time()+60
                raise error
            if response.status_code>=300: raise StudyError('provider_failed',f'Groq returned HTTP {response.status_code}; no provider fallback was attempted.')
            data=response.json(); choice=data['choices'][0]
            if choice.get('finish_reason')=='length': raise StudyError('invalid_description','Hosted figure JSON was truncated; retry explicitly with a new configuration.')
            headers={k.lower():v for k,v in response.headers.items() if k.lower().startswith('x-ratelimit-')}
            return ProviderResponse(choice['message']['content'],'groq',data.get('model',input.config.model),'',data.get('usage',{}),time.monotonic()-start,headers)
        except StudyError: raise
        except requests.Timeout as exc: raise StudyError('provider_timeout','Hosted request timed out; remote completion is unknown. Do not automatically upload again.') from exc
        except Exception as exc: raise StudyError('provider_failed',f'Hosted vision failed ({type(exc).__name__}); no fallback or duplicate upload occurred.') from exc
