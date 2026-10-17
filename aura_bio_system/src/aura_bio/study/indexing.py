"""Build complete immutable pack generations before atomic promotion."""
import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import asdict, replace

from .chunking import chunk_units
from .validation import contained
from .text import NORMALIZATION_VERSION, search_text


class StudyIndexer:
    def __init__(self, store):
        self.store = store

    def build(self, pack_id, *, dense_encoder=None):
        with self.store.lock:
            pack = self.store.assert_available(pack_id)
            documents = [doc for doc in self.store.documents(pack_id) if doc.active]
            source_units = {doc.document_id: self.store.units(pack_id, doc.document_id) for doc in documents}
            documents = [doc for doc in documents if source_units[doc.document_id]]
            chunks = [chunk for doc in documents for chunk in chunk_units(source_units[doc.document_id])]
            root = contained(self.store.root, pack_id, 'generations')
            root.mkdir(exist_ok=True)
            temporary = contained(root, f'{uuid.uuid4().hex}.part')
            temporary.mkdir()
            # A crash after folder publication but before pointer promotion leaves an
            # unreachable generation. Never overwrite it or collide on the next retry.
            existing = [int(path.name) for path in root.iterdir() if path.name.isdigit() and path.is_dir()]
            generation = max([pack.generation, *existing]) + 1
            target = contained(root, f'{generation:08d}')
            try:
                db = sqlite3.connect(temporary / 'search.sqlite3')
                try:
                    db.executescript('''CREATE TABLE chunks(chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL);
                        CREATE INDEX chunks_document ON chunks(document_id,ordinal);
                        CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, context, text, tokenize='porter unicode61');''')
                    titles = {doc.document_id: doc.filename for doc in documents}
                    for chunk in chunks:
                        payload = {**asdict(chunk), 'title': titles[chunk.document_id]}
                        db.execute('INSERT INTO chunks VALUES (?,?,?,?)', (chunk.chunk_id, chunk.document_id, chunk.ordinal, json.dumps(payload)))
                        db.execute('INSERT INTO chunk_fts VALUES (?,?,?)', (chunk.chunk_id, search_text(titles[chunk.document_id]), search_text(chunk.text)))
                    db.commit()
                finally:
                    db.close()
                manifest = {'schema_version': 2, 'provenance_version':1, 'pack_id': pack_id, 'generation': generation,
                            'chunks': len(chunks), 'documents': [doc.document_id for doc in documents],
                            'dense': False, 'chunk_tokenizer': 'unicode-lexical-estimate-v1',
                            'search_normalization': NORMALIZATION_VERSION, 'sparse_tokenizer': 'porter unicode61'}
                if dense_encoder is not None and chunks:
                    import faiss
                    import numpy as np
                    vectors = np.asarray(dense_encoder.encode([search_text(chunk.text) for chunk in chunks], batch_size=32), dtype='float32')
                    if vectors.ndim != 2 or len(vectors) != len(chunks) or not np.isfinite(vectors).all():
                        raise ValueError('Invalid pack embedding vectors.')
                    faiss.normalize_L2(vectors)
                    index = faiss.IndexFlatIP(vectors.shape[1])
                    index.add(vectors)
                    faiss.write_index(index, str(temporary / 'dense.faiss'))
                    (temporary / 'dense-map.json').write_text(json.dumps([c.chunk_id for c in chunks]), encoding='utf-8')
                    manifest.update(dense=True, dimension=vectors.shape[1], embedding_model=getattr(dense_encoder, 'model_name', 'custom'), normalized=True)
                (temporary / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
                os.replace(temporary, target)
                # The catalogue transaction is the only readiness/current-generation pointer.
                has_visual=any(u.asset_ids for values in source_units.values() for u in values)
                state = ('hybrid-ready' if manifest['dense'] else 'sparse-ready') if chunks else 'visual-only' if has_visual else 'empty'
                self.store.update_pack(replace(pack, generation=generation, state=state))
                for document in documents:
                    if document.state != 'failed':
                        self.store.update_document(replace(document, state=state))
                return generation
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
