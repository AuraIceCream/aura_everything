"""Read-only multi-pack snapshots with bounded primary-image evidence."""
from copy import copy
from .schema import StudyError
from .searcher import StudySearcher


class CompositeStudySearcher:
    def __init__(self, store, attachment_id, context_pack_id=None, *, dense_encoder=None, question=None):
        self.store, self.pack_id = store, attachment_id
        self.question = question
        self.searchers = {}
        self.runtime_warnings = []
        if context_pack_id == attachment_id:
            raise StudyError('invalid_scope', 'Image and context must be different sources.')
        try:
            for id in (attachment_id, context_pack_id):
                if not id:
                    continue
                pack = store.assert_available(id)
                if id == context_pack_id and pack.retention != 'saved':
                    raise StudyError('invalid_scope', 'Select saved material as context.')
                try:
                    searcher = StudySearcher(store, id, dense_encoder=dense_encoder if pack.state == 'hybrid-ready' else None)
                except StudyError as exc:
                    if exc.code != 'embedding_mismatch':
                        raise
                    searcher = StudySearcher(store, id)
                    self.runtime_warnings.append(f'{id}: cached encoder mismatch; sparse retrieval used.')
                self.searchers[id] = searcher
                self.runtime_warnings.extend(f'{id}: {w}' for w in searcher.runtime_warnings)
            self.generations = {id: s.generation for id, s in self.searchers.items()}
            self.generation = self.generations[attachment_id]
            self.source_modes = {id: s.mode for id, s in self.searchers.items()}
            self.mode = next(iter(set(self.source_modes.values()))) if len(set(self.source_modes.values())) == 1 else 'mixed'
        except Exception:
            self.close()
            raise

    def search(self, query, top_k, candidate_k):
        pooled = {}
        for id, searcher in self.searchers.items():
            for rank, hit in enumerate(searcher.search(query, min(200, candidate_k), candidate_k), 1):
                if not self._eligible(hit, query):
                    continue
                item = copy(hit)
                item.rrf_score = 1 / (60 + rank)
                pooled[(id, item.chunk_id)] = item
        ranked = sorted(pooled.values(), key=lambda h: (-h.rrf_score, h.pack_id, h.chunk_id))
        return ranked[:top_k]

    def neighbors(self, hits, radius=1, limit=16):
        result = []
        for id, searcher in self.searchers.items():
            if len(result) >= limit:
                break
            result.extend(h for h in searcher.neighbors([h for h in hits if h.pack_id == id], radius, limit - len(result)) if self._eligible(h, self.question or ''))
        return result

    def finalize_evidence(self, query, selected, candidates, *, max_passages, max_chars):
        primary = [h for h in candidates if h.pack_id == self.pack_id and h.text.strip() and self._eligible(h, query)]
        if not primary:
            # The figure interpretation may have no query terms ("this arrow").
            searcher = self.searchers[self.pack_id]
            primary = []
            for row in searcher.connection.execute('SELECT chunk_id FROM chunks ORDER BY rowid'):
                h = searcher._evidence(row[0])
                if h and h.text.strip() and self._eligible(h, query):
                    primary.append(h)
                if len(primary) == 2:
                    break
        if not primary:
            raise StudyError('not_ready', 'No indexed image interpretation/transcription is available.')
        from .evidence_budget import budget_evidence
        chosen=budget_evidence([h for h in primary[:2]+list(selected) if self._eligible(h,query)],
            max_passages=max_passages,max_chars=max_chars,warnings=self.runtime_warnings,
            originals=[h for h in candidates if self._eligible(h,query)])
        if not any(h.pack_id==self.pack_id for h in chosen):
            raise StudyError('context_budget','The complete image interpretation cannot fit the answer context budget. Narrow the question; context alone cannot replace the image.')
        return chosen

    def _eligible(self, hit, query):
        if hit.pack_id != self.pack_id:
            return True
        if hit.provenance not in {'vlm', 'ocr', 'user_annotation'}:
            return False
        from .attachments import question_hash
        units = {u.unit_id: u for u in self.store.units(self.pack_id, hit.document_id)}
        if not all(id in units for id in hit.unit_ids):
            return False
        expected = question_hash(self.question if self.question is not None else query)
        return hit.provenance != 'vlm' or all(units[id].provenance_details.get('question_hash', '') in {'', expected} for id in hit.unit_ids)

    def close(self):
        for searcher in self.searchers.values():
            searcher.close()
        self.searchers.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
