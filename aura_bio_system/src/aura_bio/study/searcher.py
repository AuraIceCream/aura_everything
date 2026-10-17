"""A pack-owned evidence interface; sparse search never loads an encoder."""
import json
import sqlite3
from copy import copy
from dataclasses import dataclass,field
from .provenance import source_method

from aura_bio_pipeline.retrieval import Evidence

from .schema import Locator, StudyError
from .validation import contained
from .text import NORMALIZATION_VERSION, query_terms, search_text


@dataclass
class StudyEvidence(Evidence):
    pack_id: str = ''
    unit_ids: tuple[str, ...] = ()
    locators: tuple[Locator, ...] = ()
    generation: int = 0
    provenance: str = 'native_text'
    provenance_details: dict = field(default_factory=dict)

    def as_dict(self):
        return {**super().as_dict(), 'pack_id': self.pack_id, 'unit_ids': list(self.unit_ids),
                'locators': [loc.as_dict() for loc in self.locators], 'generation': self.generation,
                'provenance':self.provenance,'provenance_details':self.provenance_details}


class StudySearcher:
    def __init__(self, store, pack_id, *, dense_encoder=None, question=None):
        self.store, self.pack_id = store, pack_id
        self.question = question
        self.figure_ids = ()
        pack = store.assert_available(pack_id)
        if pack.state not in {'sparse-ready', 'hybrid-ready'}:
            raise StudyError('not_ready', 'Study pack has no ready text index.')
        self.generation = pack.generation
        self.root = contained(store.root, pack_id, 'generations', f'{self.generation:08d}')
        self.manifest = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
        self.connection = sqlite3.connect(f'{(self.root / "search.sqlite3").as_uri()}?mode=ro', uri=True, check_same_thread=False)
        self.encoder, self.index, self.ids = dense_encoder, None, []
        self.mode = 'sparse'
        self.generations = {pack_id:self.generation}
        self.runtime_warnings = []
        if self.manifest.get('schema_version',1)<2:
            self.runtime_warnings.append('Legacy native index: readable, but rebuild to carry explicit evidence provenance.')
        if self.manifest.get('search_normalization') != NORMALIZATION_VERSION:
            self.runtime_warnings.append('Legacy text index: rebuild to enable scientific normalization and stemming.')
        if dense_encoder is not None and self.manifest['dense']:
            if getattr(dense_encoder, 'model_name', 'custom') != self.manifest['embedding_model']:
                self.close()
                raise StudyError('embedding_mismatch', 'Pack and query embedding models differ; rebuild the dense index.')
            import faiss
            self.index = faiss.read_index(str(self.root / 'dense.faiss'))
            self.ids = json.loads((self.root / 'dense-map.json').read_text(encoding='utf-8'))
            self.mode = 'hybrid'
        self.source_modes = {pack_id:self.mode}

    def bind_figures(self, ids, question):
        from .visual.storage import VisualStore
        with self.store.lock:
            visual=VisualStore(self.store,self.pack_id)
            units=visual.indexed_units(ids,question=question,connection=self.connection)
            parents={visual.figure(fid).unit_id for fid in ids}
            documents={u.document_id for u in units}
            units += [u for doc in documents for u in self.store.units(self.pack_id,doc)
                      if u.unit_id in parents and u.provenance=='native_text']
            self.figure_ids=tuple(ids)
            self.figure_units=tuple(units)  # Immutable revisions, not a live active-pointer lookup.

    def _target_scope(self, query):
        from .questions import scoped_units
        scope = scoped_units(self.store, self.pack_id, self.question or query)
        if scope == []: return []
        if self.figure_ids:
            from .visual.storage import VisualStore
            visual=VisualStore(self.store,self.pack_id)
            figures=[visual.figure(id) for id in self.figure_ids]
            units=getattr(self,'figure_units',None)
            if units is None:
                units=[u for f in figures for u in self.store.units(self.pack_id,f.document_id)
                       if u.unit_id==f.unit_id or u.provenance_details.get('figure_id') in self.figure_ids]
            selected={u.unit_id:u for u in units}
            if scope is not None:
                # Native references may bring relevant caption/procedure pages;
                # only the explicitly selected interpretations may join them.
                selected.update((u.unit_id,u) for u in scope if u.provenance=='native_text')
            scope=list(selected.values())
        return scope

    def _scope(self,query):
        from .questions import references
        target=self._target_scope(query)
        refs=references(self.question or query)
        if target and any(r.kind in {'figure','table'} for r in refs) and not any(r.kind in {'page','slide'} for r in refs):
            # A figure can refer to a procedure on another page. Retrieve that
            # context normally, but only inside the identified document(s).
            documents={u.document_id for u in target}
            return [u for doc in documents for u in self.store.units(self.pack_id,doc) if u.provenance=='native_text'] + [u for u in target if u.provenance!='native_text']
        return target

    def _reserved_targets(self,query,limit):
        from .questions import references
        if not self.figure_ids and not references(self.question or query): return []
        target=self._target_scope(query)
        if not target: return []
        from .questions import anchors,caption_anchors
        hits=self._scope_candidates(target,200)
        refs=[r for r in references(self.question or query) if r.kind in {'figure','table'}]
        wanted={(a.get('kind','figure'),a['label']) for u in target for a in anchors(u)
                if not refs or any(a.get('kind','figure')==r.kind and a['label']==r.value for r in refs)}
        def identities(hit):
            return tuple((a.get('kind','figure'),a['label']) for a in caption_anchors([{'text':s} for s in hit.text.splitlines()])
                         if (a.get('kind','figure'),a['label']) in wanted)
        hits.sort(key=lambda h:(h.provenance=='native_text',not bool(identities(h))))
        chosen,seen=[],set()
        for hit in hits:
            key=(hit.provenance,identities(hit) or hit.unit_ids)
            if key not in seen:
                chosen.append(hit);seen.add(key)
            if len(chosen)>=limit: break
        return chosen

    def _bound(self, hit, units):
        if hit is None or units is None:
            return hit
        selected = {u.unit_id:u for u in units}
        row = self.connection.execute('SELECT payload FROM chunks WHERE chunk_id=?', (hit.chunk_id,)).fetchone()
        spans = [s for s in json.loads(row[0]).get('spans', []) if s['unit_id'] in selected]
        if not spans:
            return None
        item = copy(hit)
        item.unit_ids = tuple(dict.fromkeys(s['unit_id'] for s in spans))
        item.text = '\n\n'.join(selected[s['unit_id']].text[s['start']:s['end']] for s in spans)
        item.locators = tuple(dict.fromkeys(loc for id in item.unit_ids for loc in selected[id].locators))
        item.provenance_details = {**item.provenance_details, 'spans':[
            {'unit_id':id, **selected[id].provenance_details} for id in item.unit_ids]}
        return item

    def _scope_candidates(self, units, limit):
        doc_ids = list(dict.fromkeys(u.document_id for u in units))
        result = []
        for doc_id in doc_ids:
            for row in self.connection.execute('SELECT chunk_id FROM chunks WHERE document_id=? ORDER BY ordinal',(doc_id,)):
                item = self._bound(self._evidence(row[0], channel='pack_reference'), units)
                if item and item.text.strip():
                    result.append(item)
                if len(result) >= limit:
                    return result
        return result

    def _overview(self, limit):
        """Round-robin documents and spaced chunks: bounded coverage, not a full read."""
        groups = []
        for doc in self.store.documents(self.pack_id):
            if doc.active:
                rows = [r[0] for r in self.connection.execute('SELECT chunk_id FROM chunks WHERE document_id=? ORDER BY ordinal',(doc.document_id,))]
                if rows:
                    count = min(limit,len(rows))
                    positions = [round(i*(len(rows)-1)/max(1,count-1)) for i in range(count)]
                    groups.append([rows[i] for i in positions])
        result = []
        for i in range(limit):
            for group in groups:
                if i < len(group):
                    item = self._evidence(group[i], len(result)+1, 'pack_overview')
                    if item: result.append(item)
                    if len(result) >= limit: return result
        return result

    def _evidence(self, chunk_id, rank=1, channel='pack_sparse'):
        row = self.connection.execute('SELECT payload FROM chunks WHERE chunk_id=?', (chunk_id,)).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        # Deactivated material cannot leak from a previously pinned search generation.
        if not self.store.document(self.pack_id, value['document_id']).active:
            return None
        return StudyEvidence(chunk_id, f'study:{self.pack_id}', value['title'], None, value['text'],
                             None, 'User-provided material', channel, 1 / (60 + rank),
                             document_id=value['document_id'], core_bm25_rank=rank if channel == 'pack_sparse' else None,
                             pack_id=self.pack_id, unit_ids=tuple(value['unit_ids']),
                             locators=tuple(Locator(**loc) for loc in value['locators']), generation=self.generation,
                             provenance=source_method(value.get('provenance'),'body' if value.get('provenance') is not None or self.manifest.get('schema_version',1)==1 else 'derived_unknown'),
                             provenance_details=value.get('provenance_details',{}))

    def search(self, query, top_k, candidate_k):
        self.store.assert_available(self.pack_id)
        from .questions import is_overview
        scope = self._scope(query)
        if scope == []:
            return []
        overview=scope is None and is_overview(self.question or query)
        tokens = query_terms(query)
        if not tokens:
            return self._scope_candidates(scope, min(top_k,200)) if scope else self._overview(min(top_k,200)) if overview else []
        expression = ' OR '.join(f'"{token}"' for token in tokens)
        rows = self.connection.execute('SELECT chunk_id FROM chunk_fts WHERE chunk_fts MATCH ? ORDER BY bm25(chunk_fts) LIMIT ?',
                                       (expression, min(max(1, candidate_k), 200))).fetchall()
        hits = {row[0]: self._evidence(row[0], rank) for rank, row in enumerate(rows, 1)}
        if self.index is not None:
            import faiss
            import numpy as np
            from aura_bio_pipeline.embedding import QUERY_PREFIX
            normalized = search_text(query) if self.manifest.get('search_normalization') == NORMALIZATION_VERSION else query
            vector = np.asarray(self.encoder.encode([QUERY_PREFIX + normalized]), dtype='float32')
            if vector.shape != (1, self.manifest['dimension']) or not np.isfinite(vector).all():
                raise StudyError('embedding_mismatch', 'Invalid query embedding shape/value.')
            faiss.normalize_L2(vector)
            _, ranks = self.index.search(vector, min(max(1, candidate_k), 200, len(self.ids)))
            for rank, number in enumerate(ranks[0], 1):
                if number < 0:
                    continue
                key = self.ids[int(number)]
                hit = hits.get(key)
                if hit is None:
                    hit = self._evidence(key, rank, 'pack_dense')
                    hits[key] = hit
                else:
                    hit.rrf_score += 1 / (60 + rank)
                    hit.channel = 'pack_hybrid'
                if hit is not None:
                    hit.dense_rank = rank
        ranked = sorted((self._bound(hit,scope) for hit in hits.values() if hit is not None),
                        key=lambda h: h.rrf_score if h else -1, reverse=True)
        ranked = [h for h in ranked if h is not None]
        if scope:
            known = {h.chunk_id for h in ranked}
            ranked += [h for h in self._scope_candidates(scope,min(candidate_k,200)) if h.chunk_id not in known]
            # A short generic question may not match the JSON description at
            # all. Reserve visual evidence before a long native page fills k.
            pinned = self._reserved_targets(query,min(top_k,8))
            reserved = {h.chunk_id for h in pinned}
            ranked = pinned + [h for h in ranked if h.chunk_id not in reserved]
        elif overview:
            primary=ranked[:max(1,top_k//2)]+self._overview(min(top_k,200))+ranked
            ranked=[];seen=set()
            for hit in primary:
                if hit.chunk_id not in seen:
                    ranked.append(hit);seen.add(hit.chunk_id)
        return ranked[:top_k]

    def finalize_evidence(self, query, selected, candidates, *, max_passages, max_chars):
        from .questions import is_overview, references
        from .evidence_budget import budget_evidence
        from .context import with_neighbours
        scope = self._scope(query)
        if not references(self.question or query) and not is_overview(self.question or query):
            primary = with_neighbours(self, self.question or query, selected, max_passages)
            return budget_evidence(primary,max_passages=max_passages,max_chars=max_chars,
                                   warnings=self.runtime_warnings,originals=candidates)
        if scope == []:
            return []
        if scope:
            primary=self._reserved_targets(query,max_passages)
            primary += [h for h in selected if self._bound(h,scope) is not None]
            primary += self._scope_candidates(scope,max_passages)
        else:
            primary=list(selected)[:max(1,max_passages//2)]+self._overview(max_passages)
        if not scope and self.manifest['chunks'] > max_passages:
            warning = 'Document overview uses a bounded sample, not an exhaustive reading of every page.'
            if warning not in self.runtime_warnings: self.runtime_warnings.append(warning)
        bounded=[self._bound(hit,scope) for hit in primary+list(selected)]
        bounded=with_neighbours(self,self.question or query,[h for h in bounded if h is not None],max_passages)
        originals=[self._bound(hit,scope) for hit in candidates]
        return budget_evidence(bounded,max_passages=max_passages,max_chars=max_chars,
                               warnings=self.runtime_warnings,originals=[h for h in originals if h is not None])

    def neighbors(self, hits, radius=1, limit=16):
        self.store.assert_available(self.pack_id)
        known = {hit.chunk_id for hit in hits}
        result = []
        for hit in hits:
            if getattr(hit, 'pack_id', '') != self.pack_id:
                continue
            row = self.connection.execute('SELECT ordinal,document_id FROM chunks WHERE chunk_id=?', (hit.chunk_id,)).fetchone()
            if row is None:
                continue
            for adjacent in self.connection.execute('SELECT chunk_id FROM chunks WHERE document_id=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal',
                                                     (row[1], row[0] - radius, row[0] + radius)):
                if adjacent[0] not in known:
                    known.add(adjacent[0])
                    item = self._bound(self._evidence(adjacent[0], channel='pack_neighbor'), self._scope(self.question or ''))
                    if item is not None:
                        item.rrf_score = 0.0
                        result.append(item)
                        if len(result) >= limit:
                            return result
        return result

    def close(self):
        self.connection.close()
        self.index = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
