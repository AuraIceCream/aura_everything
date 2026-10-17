import io
import tempfile
import unittest
from pathlib import Path
from aura_bio.study.schema import Extraction, Locator, Unit
from aura_bio.study.storage import StudyStore
from aura_bio.study.indexing import StudyIndexer


class AttachmentRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StudyStore(Path(self.tmp.name))
        self.ids = []
        for name, text, method in [('Image', 'ORION arrow connects A to B.', 'vlm'), ('Book', 'ORION calibration uses seven samples.', 'native_text')]:
            pack = self.store.create_pack(name)
            doc, _ = self.store.add_document(pack.pack_id, 'fixture.txt', io.BytesIO(text.encode()))
            # Same chunk identity across separate indexes must never merge ownership.
            unit = Unit('1' * 32, doc.document_id, 1, 'body', name, name, text, (Locator('text', start_line=1),), provenance=method)
            self.store.publish_extraction(doc.document_id, Extraction([unit], [], [], {}, 'fixture'))
            StudyIndexer(self.store).build(pack.pack_id)
            self.ids.append(pack.pack_id)

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_source_snapshots_and_citations_keep_ownership(self):
        from aura_bio.study.composite import CompositeStudySearcher
        with CompositeStudySearcher(self.store, *self.ids) as searcher:
            hits = searcher.search('ORION', 10, 20)
            self.assertEqual({h.pack_id for h in hits}, set(self.ids))
            self.assertEqual(searcher.source_modes, {id: 'sparse' for id in self.ids})
            self.assertEqual(len(searcher.generations), 2)

    def test_reserved_image_evidence_is_bounded_and_never_promoted_to_native(self):
        from aura_bio.study.composite import CompositeStudySearcher
        with CompositeStudySearcher(self.store, *self.ids) as searcher:
            candidates = searcher.search('ORION', 10, 20)
            context = [h for h in candidates if h.pack_id == self.ids[1]]
            chosen = searcher.finalize_evidence('ORION', context, candidates, max_passages=2, max_chars=100)
            self.assertEqual(chosen[0].pack_id, self.ids[0])
            self.assertEqual(chosen[0].provenance, 'vlm')
            self.assertLessEqual(sum(len(h.text) for h in chosen), 100)
            self.assertLessEqual(len(chosen), 2)

    def test_structured_image_cannot_be_truncated_or_replaced_by_context(self):
        import json
        from dataclasses import replace
        from aura_bio.study.composite import CompositeStudySearcher
        from aura_bio.study.schema import StudyError
        pack=self.ids[0];doc=self.store.documents(pack)[0]
        original=self.store.units(pack,doc.document_id)[0]
        text=json.dumps({'kind':'pathway','labels':['ORION'],'axes':[],'relations':[],
                         'summary':'A visible label.','uncertainties':['Other details are unclear.']})
        self.store.publish_extraction(doc.document_id,Extraction([
            replace(original,role='figure_description',text=text)],[],[],{},'fixture'))
        StudyIndexer(self.store).build(pack)
        with CompositeStudySearcher(self.store,*self.ids) as searcher:
            hits=searcher.search('ORION',10,20)
            with self.assertRaises(StudyError) as error:
                searcher.finalize_evidence('ORION',hits,hits,max_passages=2,max_chars=100)
            self.assertEqual(error.exception.code,'context_budget')
            self.assertTrue(any('context budget' in w for w in searcher.runtime_warnings))

    def test_query_fusion_never_merges_same_chunk_id_across_packs(self):
        from types import SimpleNamespace
        from aura_bio.retrieval.strategies import multi_query_search, deep_search, hierarchical_search
        hits = [SimpleNamespace(pack_id=p, chunk_id='same', document_id='same', rrf_score=1) for p in self.ids]
        class Search:
            def search(self, *args, **kwargs): return hits
        self.assertEqual(len(multi_query_search(Search(), 'ORION', 10, 20)), 2)
        self.assertEqual(len(deep_search(Search(), None, 'ORION', 10, 20)), 2)
        self.assertEqual(len(hierarchical_search(Search(), None, 'ORION', 1, 20,
            neighbor_fetch=lambda *args: [hits[1]])), 2)

    def test_retired_or_different_question_description_is_not_retrieved(self):
        from aura_bio.study.composite import CompositeStudySearcher
        from aura_bio.study.attachments import question_hash
        from dataclasses import replace
        pack=self.ids[0]; doc=self.store.documents(pack)[0]
        unit=self.store.units(pack,doc.document_id)[0]
        unit=replace(unit,provenance_details={'question_hash':question_hash('Old question?')})
        self.store.publish_extraction(doc.document_id,Extraction([unit],[],[],{},'fixture'))
        StudyIndexer(self.store).build(pack)
        with CompositeStudySearcher(self.store,*self.ids) as searcher:
            hits=searcher.search('ORION',10,20)
            self.assertFalse(any(h.pack_id==pack for h in hits))

    def test_real_sparse_plus_fake_dense_context_is_reported_as_mixed(self):
        import numpy as np
        from aura_bio.study.composite import CompositeStudySearcher
        class Encoder:
            model_name='fixture-encoder'
            def encode(self,texts,**kwargs):return np.array([[1.,len(text)/1000] for text in texts],dtype='float32')
        encoder=Encoder();StudyIndexer(self.store).build(self.ids[1],dense_encoder=encoder)
        with CompositeStudySearcher(self.store,*self.ids,dense_encoder=encoder) as searcher:
            self.assertEqual(searcher.mode,'mixed')
            self.assertEqual(searcher.source_modes,{self.ids[0]:'sparse',self.ids[1]:'hybrid'})
            self.assertEqual({h.pack_id for h in searcher.search('ORION',10,20)},set(self.ids))

    def test_failed_second_snapshot_closes_the_first(self):
        import sqlite3
        from unittest.mock import patch
        from aura_bio.study.searcher import StudySearcher
        from aura_bio.study.composite import CompositeStudySearcher
        from aura_bio.study.schema import StudyError
        captured=[]
        def open_snapshot(*args,**kwargs):
            searcher=StudySearcher(*args,**kwargs);captured.append(searcher);return searcher
        empty=self.store.create_pack('Empty context')
        with patch('aura_bio.study.composite.StudySearcher',side_effect=open_snapshot):
            with self.assertRaises(StudyError):CompositeStudySearcher(self.store,self.ids[0],empty.pack_id)
        with self.assertRaises(sqlite3.ProgrammingError):captured[0].connection.execute('SELECT 1')
