import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from aura_bio.study.schema import Extraction, Locator, Unit
from aura_bio.study.storage import StudyStore
from aura_bio.study.chunking import chunk_units
from aura_bio.study.indexing import StudyIndexer
from aura_bio.study.searcher import StudySearcher


class FakeEncoder:
    model_name = 'fake-v1'
    def __init__(self):
        self.queries = []
    def encode(self, texts, **kwargs):
        self.queries.extend(texts)
        return np.asarray([[1.0, float('calibration' in text.casefold())] for text in texts], dtype='float32')


class StudyRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StudyStore(Path(self.tmp.name) / 'packs')
        self.pack = self.store.create_pack('Class')
        self.document, _ = self.store.add_document(self.pack.pack_id, 'a.txt', io.BytesIO(b'Lecture'))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def unit(self, number, text, section=''):
        return Unit(f'{number:032x}', self.document.document_id, number, 'body', 'Lesson', section,
                    text, (Locator('pptx', slide=number),))

    def publish(self, units):
        self.store.publish_extraction(self.document.document_id, Extraction(units, [], [], {'units': len(units)}, 'fixture-v1'))

    def test_short_units_merge_with_every_locator(self):
        chunks = chunk_units([self.unit(i, f'Calibration phase {i}.') for i in range(1, 6)])
        self.assertEqual(len(chunks), 1)
        self.assertEqual({loc.slide for loc in chunks[0].locators}, {1, 2, 3, 4, 5})
        self.assertEqual(len(chunks[0].unit_ids), 5)

    def test_section_and_role_boundaries_do_not_merge(self):
        units = [self.unit(1, 'A', 'one'), self.unit(2, 'B', 'two'), replace(self.unit(3, 'C', 'two'), role='notes')]
        self.assertEqual(len(chunk_units(units)), 3)

    def test_long_unit_spans_point_to_original_text(self):
        unit = self.unit(1, ' '.join(f'word{i}' for i in range(1000)))
        chunks = chunk_units([unit], target_tokens=100, overlap_tokens=10)
        self.assertGreater(len(chunks), 2)
        for chunk in chunks:
            span = chunk.spans[0]
            self.assertEqual(unit.text[span['start']:span['end']], chunk.text)

    def test_sparse_search_neighbours_and_generation_are_isolated(self):
        self.publish([self.unit(1, 'Opening context.', 'one'), self.unit(2, 'ORION calibration uses seven samples.', 'two'), self.unit(3, 'Next step seals the vessel.', 'three')])
        generation = StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            hits = searcher.search('ORION calibration', 5, 20)
            self.assertEqual(searcher.mode, 'sparse')
            self.assertEqual(hits[0].locators[0].slide, 2)
            self.assertEqual(hits[0].generation, generation)
            adjacent = searcher.neighbors(hits[:1])
            self.assertEqual({loc.slide for hit in adjacent for loc in hit.locators}, {1, 3})
            self.assertEqual(searcher.search('NoSuchWord', 5, 20), [])
        other = self.store.create_pack('Other')
        with self.assertRaises(ValueError):
            StudySearcher(self.store, other.pack_id)

    def test_dense_prefix_only_on_queries(self):
        self.publish([self.unit(1, 'ORION calibration.')])
        encoder = FakeEncoder()
        StudyIndexer(self.store).build(self.pack.pack_id, dense_encoder=encoder)
        self.assertFalse(encoder.queries[0].startswith('Represent'))
        with StudySearcher(self.store, self.pack.pack_id, dense_encoder=encoder) as searcher:
            self.assertEqual(searcher.mode, 'hybrid')
            hits = searcher.search('calibration', 5, 10)
            self.assertTrue(encoder.queries[-1].startswith('Represent this sentence'))
            self.assertEqual(hits[0].pack_id, self.pack.pack_id)

    def test_natural_absent_questions_do_not_match_grammatical_words(self):
        self.publish([self.unit(1, 'Cancer is a disease of cells in the body. A limitation is missing functional evidence.')])
        StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            for query in ('What is the capital city of France?',
                          'What is the ORION calibration deadline in the ZEGA-731 course?',
                          'is of in a to the'):
                with self.subTest(query=query):
                    self.assertEqual(searcher.search(query, 5, 20), [])

    def test_search_normalizes_scientific_terms_without_changing_cited_text(self):
        original = 'The γδT-cell population has limitations. We ﬁnd cyto-\ntoxic activity.'
        unit = self.unit(1, original)
        self.publish([unit])
        StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            for query in ('gamma delta', 'limitation', 'find', 'cytotoxic'):
                with self.subTest(query=query):
                    hits = searcher.search(query, 5, 20)
                    self.assertEqual(len(hits), 1)
                    self.assertEqual(hits[0].text, original)
                    self.assertEqual(hits[0].locators[0].slide, 1)

    def test_dense_documents_and_queries_share_normalization(self):
        self.publish([self.unit(1, 'γδT cells show cyto-\ntoxic activity.')])
        encoder = FakeEncoder()
        StudyIndexer(self.store).build(self.pack.pack_id, dense_encoder=encoder)
        self.assertIn('gamma delta', encoder.queries[0])
        self.assertIn('cytotoxic', encoder.queries[0])
        with StudySearcher(self.store, self.pack.pack_id, dense_encoder=encoder) as searcher:
            searcher.search('γδT cells', 5, 10)
            self.assertIn('gamma delta', encoder.queries[-1])

    def test_failed_build_keeps_old_generation(self):
        self.publish([self.unit(1, 'ORION calibration.')])
        first = StudyIndexer(self.store).build(self.pack.pack_id)
        class BrokenEncoder:
            def encode(self, *args, **kwargs):
                raise RuntimeError('controlled failure')
        with self.assertRaises(RuntimeError):
            StudyIndexer(self.store).build(self.pack.pack_id, dense_encoder=BrokenEncoder())
        self.assertEqual(self.store.get_pack(self.pack.pack_id).generation, first)
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            self.assertTrue(searcher.search('ORION', 5, 10))
