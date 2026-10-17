"""Explicit single-worker visual jobs. No start/upload/search inference side effect."""
import json
import threading
import time
import uuid
from dataclasses import asdict,replace
from contextlib import ExitStack
from .schema import VisualJobConfig,VisualCheckpoint,FigureInput,digest
from .storage import VisualStore
from .assets import crop_bytes
from ..schema import StudyError,Unit


class VisualJobs:
    def __init__(self,store,*,describer=None,ocr=None,indexer=None,clock=time.time):
        self.store,self.describer,self.ocr,self.indexer,self.clock=store,describer,ocr,indexer,clock
        self.run_lock=threading.Lock(); self.stopping=threading.Event(); self.thread=None

    def recover(self):
        with self.store.lock:
            for pack in self.store.worker_packs():
                if pack.state=='purge-pending': continue
                for job in self.store.jobs(pack.pack_id):
                    if job.kind=='visual' and job.state in {'queued','running'}:
                        self.store.update_job(replace(job,state='paused',error='Interrupted by server restart; resume explicitly. Completed figures retained.'))

    def start(self,pack_id,figure_ids,config):
        if len(figure_ids)!=len(set(figure_ids)) or not 1<=len(figure_ids)<=config.max_figures:
            raise StudyError('limit','Select unique figures within the configured job budget.')
        with self.store.lock:
            if self.store.inference_owner is not None:
                raise StudyError('busy_gpu','Visual/answer work is active; no preflight, upload or model unload attempted.')
            visual=VisualStore(self.store,pack_id)
            figures=[visual.figure(fid) for fid in figure_ids]
            from .description import prompt_hash_for
            expected_prompt=prompt_hash_for(config.description_version)
            if config.prompt_hash and config.prompt_hash!=expected_prompt: raise StudyError('config_changed','Prompt content changed; create a new configuration.')
            config=replace(config,prompt_hash=expected_prompt)
            if config.provider=='groq' and (not visual.permission() or not all(config.consent.get(k) is True for k in ('external_allowed','images','hints'))):
                raise StudyError('consent_required','Enable external processing for this pack and explicitly approve these crops and hints.')
            if self.describer is None and config.provider=='ollama':
                from .ollama import OllamaVisionBackend
                identity=OllamaVisionBackend().preflight(config)
                config=replace(config,model_digest=identity)
            snapshot={f.figure_id:visual.snapshot_hash(f,include_ocr=config.provider!='ocr') for f in figures}
            if config.snapshot and config.snapshot!=snapshot: raise StudyError('source_changed','Submitted figure snapshot is stale.')
            config=replace(config,snapshot=snapshot)
            job=self.store.enqueue(pack_id,kind='visual')
            with self.store.db(pack_id) as db:
                db.execute('INSERT INTO visual_jobs(job_id,config,items) VALUES (?,?,?)',(job.job_id,json.dumps(asdict(config)),json.dumps(figure_ids)))
            for f in figures: visual.upsert_checkpoint(VisualCheckpoint(job.job_id,f.figure_id,f.checksum,config.checksum,updated_at=self.clock()))
            return job

    def _publish(self,pack_id):
        if self.indexer:
            self.indexer(pack_id); return
        # Rebuild via the normal cached-CPU hybrid worker. Old generation remains live until atomic publish.
        self.store.enqueue(pack_id,kind='index')

    def _change_state(self,job_id,state):
        with self.store.lock:
            job=self.store.job(job_id)
            if job.kind!='visual': raise StudyError('invalid_id','Not a visual job.')
            if job.state in {'completed','cancelled'}: return job
            job=replace(job,state=state); self.store.update_job(job)
            if any(cp.state=='completed' for cp in VisualStore(self.store,job.pack_id).checkpoints(job_id)): self._publish(job.pack_id)
            return job

    def pause(self,job_id): return self._change_state(job_id,'paused')
    def cancel(self,job_id): return self._change_state(job_id,'cancelled')

    def resume(self,job_id,config):
        with self.store.lock:
            if self.store.inference_owner is not None:
                raise StudyError('busy_gpu','Visual/answer work is active; resume did not probe or unload a model.')
            job=self.store.job(job_id); visual=VisualStore(self.store,job.pack_id)
            raw,ids,_=visual.job_data(job_id); frozen=VisualJobConfig(**raw)
            from .description import prompt_hash_for
            if frozen.prompt_hash!=prompt_hash_for(frozen.description_version): raise StudyError('config_changed','Prompt content changed; start a new job rather than resuming.')
            if any(cp.resume_at and cp.resume_at>self.clock() for cp in visual.checkpoints(job_id)):
                raise StudyError('rate_limited','Provider reset time has not elapsed; resume is explicit and must respect its reported limit.')
            supplied=replace(config,snapshot=frozen.snapshot,model_digest=config.model_digest or frozen.model_digest,prompt_hash=config.prompt_hash or frozen.prompt_hash)
            if supplied.checksum!=frozen.checksum: raise StudyError('config_changed','Provider/model/prompt/config changed; create a new job instead.')
            if job.state not in {'paused','partial','failed'}: raise StudyError('not_ready','Only paused, partial or failed jobs can be resumed.')
            if frozen.snapshot!={fid:visual.snapshot_hash(visual.figure(fid),include_ocr=frozen.provider!='ocr') for fid in ids}: raise StudyError('source_changed','Figure context/crop/OCR changed; create a new job.')
            if frozen.provider=='ollama' and self.describer is None:
                from .ollama import OllamaVisionBackend
                if OllamaVisionBackend().preflight(frozen)!=frozen.model_digest: raise StudyError('model_changed','Installed model digest changed; create a new job.')
            job=replace(job,state='queued',error=None); self.store.update_job(job)
            return job

    def launch(self):
        if self.thread and self.thread.is_alive(): return
        self.stopping.clear()
        self.thread=threading.Thread(target=self._loop,daemon=True,name='aura-visual-worker'); self.thread.start()

    def stop(self):
        self.stopping.set()
        # Requests have their own deadline; no multihour join and no new work.
        if self.thread: self.thread.join(timeout=1)

    def _loop(self):
        while not self.stopping.is_set():
            if not self.run_once(): self.stopping.wait(.25)

    def _one(self,visual,figure,config,budget=None,call_budget=None):
        with self.store.lease(visual.pack_id,require_ready=False):
            asset=visual.rendered_asset(figure.document_id,figure.asset_id)
            parent=next(u for u in self.store.units(visual.pack_id,figure.document_id) if u.unit_id==figure.unit_id)
            image=crop_bytes(asset.content,figure.bbox,max_pixels=config.max_pixels)
        if config.provider=='ocr':
            from .ocr import TesseractOcr,ocr_unit
            from .assets import decode_bytes
            result=(self.ocr or TesseractOcr()).read(decode_bytes(image,self.store.limits),language=config.model,timeout_seconds=config.ocr_timeout_seconds)
            unit=ocr_unit(parent,result)
            return replace(unit,unit_id=digest({'ocr_unit':unit.unit_id,'figure':figure.figure_id,'crop':digest(image)})[:32],
                           provenance_details={**unit.provenance_details,'figure_id':figure.figure_id,'crop_checksum':digest(image),'config_hash':config.checksum}),0,1
        if self.describer: describer=self.describer
        elif config.provider=='ollama':
            from .description import FigureDescriber
            from .ollama import OllamaVisionBackend
            describer=FigureDescriber(OllamaVisionBackend())
        else:
            from .description import FigureDescriber
            from .groq import GroqVisionBackend
            if not visual.permission(): raise StudyError('consent_required','External permission was revoked; nothing further will be uploaded.')
            describer=FigureDescriber(GroqVisionBackend())
        hint=visual.ocr_hint(figure)
        from .selection import figure_context
        caption_hint=figure_context(parent,figure)
        identity={k:v for k,v in asdict(config).items() if k not in {'snapshot','consent','managed_swap'}}
        cache_key=digest({'image':digest(image),'ocr_hint':hint[:4000],'caption_hint':caption_hint,'config':identity,
                          **({'focused_source':asdict(figure)} if config.focus else {})})
        cached=visual.cached_description(cache_key)
        if cached:
            unit=replace(cached,unit_id=uuid.uuid4().hex,document_id=parent.document_id,ordinal=parent.ordinal,title=parent.title,
                         breadcrumb=parent.breadcrumb,locators=parent.locators,asset_ids=(figure.asset_id,),
                         provenance_details={**cached.provenance_details,'source_unit_id':parent.unit_id,'figure_id':figure.figure_id,
                                             'description_origin_revision':cached.unit_id,'context_hash':figure.context_hash,'config_hash':config.checksum})
            return unit,0,0
        focus_reads=(); focus_warnings=[]
        if config.focus:
            from .focus import owned_details,select_focus,read_focus,FocusRegion
            with self.store.lease(visual.pack_id,require_ready=False):
                geometry=owned_details(visual,figure)
            regions=select_focus(config.question,figure,geometry)
            if not regions:
                focus_warnings.append('whole_figure: no precise source-owned panel/row geometry; inspecting the original figure, not an estimated model box.')
                regions=(FocusRegion('whole-figure',figure.figure_id,figure.bbox,figure.frame,(),figure.checksum,digest(config.question)),)
            focus_reads=read_focus(regions,config.question,config,visual,describer,call_budget)
            from .schema import FigureDescription,ProviderResponse
            responses=tuple(ProviderResponse(**response) for read in focus_reads for response in read['responses'])
            described=FigureDescription(focus_reads[0]['fields'],responses,focus_reads[0]['prompt_hash'],config.checksum)
        else:
            described=describer.describe(FigureInput(figure,image,config,hint,caption_hint),timeout_seconds=config.timeout_seconds,
                                    **({'budget':budget} if config.provider=='groq' else {}),
                                    **({'call_budget':call_budget} if call_budget is not None else {}))
        text=json.dumps({'focused_descriptions':[{'region':r['region'],'description':r['fields']} for r in focus_reads],
                         'warnings':focus_warnings} if focus_reads else described.fields,ensure_ascii=False)
        usage=sum(r.usage.get('total_tokens',sum(r.usage.get(k,0) for k in ('prompt_tokens','completion_tokens'))) for r in described.responses)
        unit=Unit(uuid.uuid4().hex,parent.document_id,parent.ordinal,'figure_description',parent.title,parent.breadcrumb,text,parent.locators,
                  {'description':described.fields,'responses':[asdict(r) for r in described.responses]},(figure.asset_id,),'vlm',
                  {'source_unit_id':parent.unit_id,'figure_id':figure.figure_id,'provider':config.provider,'model':config.model,
                   'model_digest':config.model_digest,'prompt_hash':described.prompt_hash,'config_hash':described.config_hash,'crop_checksum':digest(image),
                   'ocr_hint_hash':digest(hint),'caption_hint_hash':digest(caption_hint),'context_hash':figure.context_hash,
                   'think':config.think,'figure_label':figure.figure_label,'reference_kind':figure.reference_kind,'numbers_verified':False})
        from ..attachments import question_hash
        unit=replace(unit,provenance_details={**unit.provenance_details,'description_cache_key':cache_key,'question_hash':question_hash(config.question)})
        if config.description_version==2:
            from .details import caption_observations,detail_conflicts
            native=caption_observations(figure.caption,unit_id=parent.unit_id,source_text=parent.text)
            conflicts=detail_conflicts(described.fields,native)
            unit=replace(unit,metadata={**unit.metadata,'caption_observations':native,
                         'detail_conflicts':conflicts})
            if conflicts: focus_warnings.append('Unresolved caption/pixel subject disagreement; inspect the source rather than choosing an interpretation silently.')
            if focus_reads:
                unit=replace(unit,text=json.dumps({'focused_descriptions':[{'region':r['region'],'description':r['fields']} for r in focus_reads],
                    'caption_subjects':native,'unresolved_conflicts':conflicts,'warnings':focus_warnings},ensure_ascii=False))
        if config.focus:
            unit=replace(unit,metadata={**unit.metadata,'focus_reads':focus_reads,'focus_warnings':focus_warnings},
                         provenance_details={**unit.provenance_details,'focus_regions':[r['region'] for r in focus_reads]})
        return unit,usage,len(described.responses)

    def run_once(self):
        if not self.run_lock.acquire(blocking=False): return False
        reservation=ExitStack()
        try:
            job=next((j for p in self.store.worker_packs() if p.state!='purge-pending' for j in self.store.jobs(p.pack_id) if j.kind=='visual' and j.state=='queued'),None)
            if not job: return False
            reservation.enter_context(self.store.inference(job.pack_id,'visual'))
            visual=VisualStore(self.store,job.pack_id)
            raw,ids,spent=visual.job_data(job.job_id); config=VisualJobConfig(**raw)
            self.store.update_job(replace(job,state='running'))
            from .description import HostedTokenBudget,request_reservation
            def save_usage(value):
                with self.store.lock:
                    if self.store.job(job.job_id).state!='running':
                        raise StudyError('job_cancelled','Visual job is no longer running; no further request permitted.')
                    with self.store.db(job.pack_id) as db:
                        db.execute('UPDATE visual_jobs SET usage=? WHERE job_id=?',(value,job.job_id))
            budget=HostedTokenBudget(config.token_budget,spent,save_usage) if config.provider=='groq' else None
            from .focus import FocusBudget
            def allow_focus_call():
                if self.store.job(job.job_id).state!='running':
                    raise StudyError('job_cancelled','Question-focused processing was cancelled; no further model call started.')
            focus_budget=FocusBudget(2,time.monotonic()+config.timeout_seconds,before_call=allow_focus_call) if config.focus else None
            failed=False
            for checkpoint in visual.checkpoints(job.job_id):
                if checkpoint.state=='completed': continue
                if self.stopping.is_set() or self.store.job(job.job_id).state!='running': break
                try:
                    figure=visual.figure(checkpoint.item_id)
                    if visual.snapshot_hash(figure,include_ocr=config.provider!='ocr')!=config.snapshot[figure.figure_id]: raise StudyError('source_changed','Source/crop/OCR snapshot changed; start a new job.')
                    visual.upsert_checkpoint(replace(checkpoint,state='running',updated_at=self.clock()))
                    unit,usage,attempts=self._one(visual,figure,config,budget,focus_budget)
                    with self.store.lock:
                        if self.store.job(job.job_id).state!='running': break
                        if visual.snapshot_hash(figure,include_ocr=config.provider!='ocr')!=config.snapshot[figure.figure_id]: raise StudyError('source_changed','Source changed during processing; late interpretation discarded.')
                        revision=visual.publish_revision(unit,expected_source_hash=checkpoint.source_hash)
                        visual.activate_revision(figure.figure_id,revision)
                        spent=budget.used if budget else spent+usage
                        with self.store.db(job.pack_id) as db: db.execute('UPDATE visual_jobs SET usage=? WHERE job_id=?',(spent,job.job_id))
                        visual.upsert_checkpoint(replace(checkpoint,state='completed',attempts=checkpoint.attempts+attempts,revision_id=revision,error=None,updated_at=self.clock()))
                        responses=unit.metadata.get('responses',[])
                        headers=responses[-1].get('headers',{}) if responses else {}
                        tokens_remaining=headers.get('x-ratelimit-remaining-tokens')
                        requests_remaining=headers.get('x-ratelimit-remaining-requests')
                        try:
                            throttled=(tokens_remaining is not None and float(tokens_remaining)<request_reservation(FigureInput(figure,b'',config))) or (requests_remaining is not None and float(requests_remaining)<1)
                        except (ValueError,TypeError):
                            throttled=True  # Unreadable capacity is not permission to issue another upload.
                        if config.provider=='groq' and throttled and any(cp.state!='completed' for cp in visual.checkpoints(job.job_id)):
                            import re
                            reset=headers.get('x-ratelimit-reset-tokens',headers.get('x-ratelimit-reset-requests','60s'))
                            durations=re.findall(r'(\d+(?:\.\d+)?)(ms|s|m|h)',reset)
                            delay=sum(float(n)*{'ms':.001,'s':1,'m':60,'h':3600}[u] for n,u in durations) or 60
                            visual.upsert_checkpoint(replace(checkpoint,state='completed',attempts=checkpoint.attempts+attempts,revision_id=revision,error=None,
                                                     updated_at=self.clock(),resume_at=self.clock()+delay))
                            self.store.update_job(replace(job,state='paused',error='Rate-limit headers report depleted capacity; resume explicitly after reset.'))
                            self._publish(job.pack_id); return True
                except Exception as exc:
                    code=exc.code if isinstance(exc,StudyError) else 'visual_failed'
                    detail=str(exc) if isinstance(exc,StudyError) else f'Visual processing failed ({type(exc).__name__}); native index retained.'
                    try:
                        raw_responses=tuple(asdict(r) for r in getattr(exc,'responses',()))
                        visual.upsert_checkpoint(replace(checkpoint,state='failed',attempts=checkpoint.attempts+getattr(exc,'attempts',1),error=f'{code}: {detail}',updated_at=self.clock(),resume_at=getattr(exc,'resume_at',None),responses=raw_responses))
                        failed=True
                        if code in {'rate_limited','budget_exhausted','focus_budget_exhausted','busy_gpu','out_of_memory','provider_timeout','model_changed','consent_required'}:
                            self.store.update_job(replace(job,state='paused',error=f'{code}: {detail}'))
                            if any(cp.state=='completed' for cp in visual.checkpoints(job.job_id)): self._publish(job.pack_id)
                            return True
                    except StudyError: return False  # Purged/deactivated/cancelled; no late writes.
            current=self.store.job(job.job_id)
            if current.state=='running':
                complete=all(c.state=='completed' for c in visual.checkpoints(job.job_id))
                self.store.update_job(replace(job,state='completed' if complete else 'partial',error='Some figures failed; inspect checkpoints and resume explicitly.' if failed else None))
                if any(c.state=='completed' for c in visual.checkpoints(job.job_id)): self._publish(job.pack_id)
            return True
        except StudyError:
            return False
        finally:
            reservation.close()
            self.run_lock.release()
