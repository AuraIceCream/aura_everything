"""Pack-owned visual metadata, immutable revisions and restart checkpoints."""
import json
import time
from dataclasses import asdict,replace
from .schema import RenderedAsset,SourceTransform,VisualCheckpoint,candidate_from_dict,digest
from .assets import decode_bytes
from .selection import select_figures,create_crop
from ..schema import StudyError,unit_from_dict,Locator
from ..validation import contained,validate_id

TABLES = '''
CREATE TABLE IF NOT EXISTS visual_figures(figure_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS visual_revisions(revision_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,figure_id TEXT NOT NULL,method TEXT NOT NULL,active INTEGER NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS visual_jobs(job_id TEXT PRIMARY KEY,config TEXT NOT NULL,items TEXT NOT NULL,usage INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS visual_checkpoints(job_id TEXT NOT NULL,item_id TEXT NOT NULL,document_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(job_id,item_id));
CREATE TABLE IF NOT EXISTS visual_pages(document_id TEXT NOT NULL,page INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(document_id,page));
CREATE TABLE IF NOT EXISTS visual_settings(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
'''


class VisualStore:
    def __init__(self,store,pack_id):
        self.store,self.pack_id=store,pack_id
        self.discovery_warnings=[]
        with store.lock:
            store.assert_available(pack_id)
            with store.db(pack_id) as db: db.executescript(TABLES)

    def _document(self,document_id):
        self.store.assert_available(self.pack_id)
        document=self.store.document(self.pack_id,document_id)
        if not document.active: raise StudyError('not_ready','Document is deactivated.')
        return document

    def figures(self,document_id):
        with self.store.lock:
            self.discovery_warnings=[]
            self._document(document_id)
            with self.store.db(self.pack_id) as db:
                units=[unit_from_dict(json.loads(r[0])) for r in db.execute('SELECT payload FROM units WHERE document_id=? ORDER BY ordinal',(document_id,))]
            assets=[]
            for unit in units:
                for aid in unit.asset_ids:
                    try: assets.append(self.rendered_asset(document_id,aid))
                    except StudyError as exc:
                        self.discovery_warnings.append(f'Asset {aid[:8]} unavailable: {exc.code}. Re-ingest or inspect the original; no image was sent.')
            candidates=select_figures(units,assets,limit=200)
            with self.store.db(self.pack_id) as db:
                for candidate in candidates:
                    db.execute('INSERT OR IGNORE INTO visual_figures VALUES (?,?,?)',(candidate.figure_id,document_id,json.dumps(asdict(candidate))))
                return [candidate_from_dict(json.loads(r[0])) for r in db.execute('SELECT payload FROM visual_figures WHERE document_id=? ORDER BY rowid',(document_id,))]

    def rendered_asset(self,document_id,asset_id):
        metadata=self.store.asset(self.pack_id,document_id,asset_id)
        content=self.store.asset_path(self.pack_id,document_id,asset_id).read_bytes()
        if digest(content)!=metadata['checksum']: raise StudyError('source_changed','Owned image checksum changed; re-ingest it.')
        image=decode_bytes(content,self.store.limits)
        coords=metadata['coordinates']
        transform=SourceTransform(**coords['transform']) if 'transform' in coords else image.transform
        return replace(image,asset_id=asset_id,unit_id=metadata['unit_id'],document_id=document_id,checksum=metadata['checksum'],
                       transform=transform,metadata=coords)

    def figure(self,figure_id):
        validate_id(figure_id)
        with self.store.db(self.pack_id) as db:
            row=db.execute('SELECT payload FROM visual_figures WHERE figure_id=?',(figure_id,)).fetchone()
        if row is None: raise StudyError('not_found','Figure not found in this pack.')
        figure=candidate_from_dict(json.loads(row[0])); self._document(figure.document_id)
        return figure

    def add_crop(self,figure_id,bbox):
        with self.store.lock:
            figure=create_crop(self.figure(figure_id),bbox)
            with self.store.db(self.pack_id) as db:
                db.execute('INSERT OR IGNORE INTO visual_figures VALUES (?,?,?)',(figure.figure_id,figure.document_id,json.dumps(asdict(figure))))
            return figure

    def publish_revision(self,unit,*,expected_source_hash):
        with self.store.lock:
            self._document(unit.document_id)
            figure=self.figure(unit.provenance_details['figure_id'])
            if figure.document_id!=unit.document_id or figure.checksum!=expected_source_hash:
                raise StudyError('source_changed','Figure source changed; create a new job.')
            if unit.provenance not in {'ocr','vlm','user_annotation'}:
                raise StudyError('invalid_provenance','A visual revision must declare its actual method.')
            # Check bytes again, so a stale in-flight result cannot publish after a source change.
            self.rendered_asset(unit.document_id,figure.asset_id)
            validate_id(unit.unit_id)
            payload=asdict(replace(unit,locators=(Locator(**figure.locator),),asset_ids=(figure.asset_id,),
                                 provenance_details={**unit.provenance_details,'revision_id':unit.unit_id,'asset_id':figure.asset_id,
                                 'bbox':asdict(figure.bbox),'frame':figure.frame}))
            with self.store.db(self.pack_id) as db:
                old=db.execute('SELECT payload FROM visual_revisions WHERE revision_id=?',(unit.unit_id,)).fetchone()
                encoded=json.dumps(payload)
                if old and old[0]!=encoded: raise StudyError('immutable_revision','Existing revisions cannot be overwritten.')
                db.execute('INSERT OR IGNORE INTO visual_revisions VALUES (?,?,?,?,0,?)',(unit.unit_id,unit.document_id,figure.figure_id,unit.provenance,encoded))
            return unit.unit_id

    def activate_revision(self,figure_id,revision_id):
        with self.store.lock:
            self.figure(figure_id); revision=self.revision(revision_id)
            if revision.provenance_details['figure_id']!=figure_id: raise StudyError('invalid_id','Revision belongs to another figure.')
            with self.store.db(self.pack_id) as db:
                if revision.provenance=='vlm' and db.execute("SELECT 1 FROM visual_revisions WHERE figure_id=? AND method='user_annotation' AND active=1",(figure_id,)).fetchone():
                    return  # Re-description must not silently undo a user edit.
                methods=('vlm','user_annotation') if revision.provenance=='user_annotation' else (revision.provenance,)
                for method in methods: db.execute('UPDATE visual_revisions SET active=0 WHERE figure_id=? AND method=?',(figure_id,method))
                db.execute('UPDATE visual_revisions SET active=1 WHERE revision_id=?',(revision_id,))

    def revision(self,revision_id):
        validate_id(revision_id)
        with self.store.db(self.pack_id) as db:
            row=db.execute('SELECT payload FROM visual_revisions WHERE revision_id=?',(revision_id,)).fetchone()
        if not row: raise StudyError('not_found','Visual revision not found.')
        unit=unit_from_dict(json.loads(row[0])); self.store.assert_available(self.pack_id)
        self.store.document(self.pack_id,unit.document_id)  # Deactivation preserves historical citation revisions.
        return unit

    def revisions(self,figure_id):
        self.figure(figure_id)
        with self.store.db(self.pack_id) as db:
            return [{**json.loads(r['payload']),'active':bool(r['active'])} for r in db.execute('SELECT payload,active FROM visual_revisions WHERE figure_id=? ORDER BY rowid',(figure_id,))]

    def active_units(self,document_id):
        with self.store.db(self.pack_id) as db:
            return [unit_from_dict(json.loads(r[0])) for r in db.execute('SELECT payload FROM visual_revisions WHERE document_id=? AND active=1 ORDER BY rowid',(document_id,))]

    def indexed_units(self,figure_ids,*,question=None,connection=None):
        """Resolve question-compatible revisions only if this generation contains them."""
        if connection is None:
            from ..searcher import StudySearcher
            with self.store.lease(self.pack_id),StudySearcher(self.store,self.pack_id) as searcher:
                return self.indexed_units(figure_ids,question=question,connection=searcher.connection)
        from ..attachments import question_hash
        with self.store.lock:
            present={id for row in connection.execute('SELECT payload FROM chunks') for id in json.loads(row[0])['unit_ids']}
            result=[]
            for fid in figure_ids:
                figure=self.figure(fid)
                units=[u for u in self.active_units(figure.document_id)
                       if u.provenance_details.get('figure_id')==fid and u.provenance in {'ocr','vlm','user_annotation'}
                       and (question is None or u.provenance_details.get('question_hash','') in {'',question_hash(question)})]
                if not units or not {u.unit_id for u in units}<=present:
                    raise StudyError('not_ready','Process and index the selected figures for this question before answering.')
                result.extend(units)
            return result

    def upsert_checkpoint(self,checkpoint):
        with self.store.lock:
            figure=self.figure(checkpoint.item_id)
            job=self.store.job(checkpoint.job_id)
            if job.pack_id!=self.pack_id: raise StudyError('invalid_id','Checkpoint belongs to another pack.')
            if job.state not in {'queued','running'}: raise StudyError('cancelled','Job is no longer running; late output discarded.')
            with self.store.db(self.pack_id) as db:
                db.execute('INSERT OR REPLACE INTO visual_checkpoints VALUES (?,?,?,?)',(checkpoint.job_id,checkpoint.item_id,figure.document_id,json.dumps(asdict(checkpoint))))

    def checkpoints(self,job_id):
        with self.store.db(self.pack_id) as db:
            return [VisualCheckpoint(**json.loads(r[0])) for r in db.execute('SELECT payload FROM visual_checkpoints WHERE job_id=? ORDER BY rowid',(job_id,))]

    def job_data(self,job_id):
        with self.store.db(self.pack_id) as db:
            row=db.execute('SELECT * FROM visual_jobs WHERE job_id=?',(job_id,)).fetchone()
        if not row: raise StudyError('not_found','Visual job snapshot not found.')
        return json.loads(row['config']),json.loads(row['items']),row['usage']

    def ocr_hint(self,figure):
        values=[u.text for u in self.active_units(figure.document_id) if u.provenance=='ocr' and u.provenance_details.get('figure_id')==figure.figure_id]
        return values[-1] if values else ''

    def snapshot_hash(self,figure,*,include_ocr=True):
        self.rendered_asset(figure.document_id,figure.asset_id)
        parent=next((u for u in self.store.units(self.pack_id,figure.document_id) if u.unit_id==figure.unit_id),None)
        if parent is None: raise StudyError('source_changed','Parent unit was replaced; discover/reselect the new figure.')
        return digest({'candidate':asdict(figure),'ocr_hint':digest(self.ocr_hint(figure) if include_ocr else ''),
                       'native_context':digest({'text':parent.text,'locators':[loc.as_dict() for loc in parent.locators],'metadata':parent.metadata}),
                       'original':self._document(figure.document_id).checksum})

    def cached_description(self,cache_key):
        with self.store.db(self.pack_id) as db:
            for row in db.execute("SELECT payload FROM visual_revisions WHERE method='vlm' ORDER BY rowid DESC LIMIT 2000"):
                unit=unit_from_dict(json.loads(row[0]))
                if unit.provenance_details.get('description_cache_key')==cache_key: return unit
        return None

    def permission(self,allowed=None):
        with self.store.lock,self.store.db(self.pack_id) as db:
            if allowed is not None: db.execute('INSERT OR REPLACE INTO visual_settings VALUES (?,?)',('external_allowed',json.dumps(bool(allowed))))
            row=db.execute('SELECT payload FROM visual_settings WHERE key=?',('external_allowed',)).fetchone()
            return bool(row and json.loads(row[0]))


def remove_document_visual(db,document_id):
    # Called inside the existing purge transaction; nothing can race late writes under store.lock.
    existing={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ('visual_figures','visual_revisions','visual_checkpoints','visual_pages'):
        if table in existing: db.execute(f'DELETE FROM {table} WHERE document_id=?',(document_id,))
    if 'visual_jobs' in existing: db.execute('DELETE FROM visual_jobs')
    if 'visual_checkpoints' in existing: db.execute('DELETE FROM visual_checkpoints')
