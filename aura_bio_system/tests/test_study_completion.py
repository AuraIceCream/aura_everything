"""Cross-page context and explicit-request coverage regressions."""
import io
import json
from pathlib import Path
import tempfile
import unittest

from aura_bio.pipeline import AnswerPolicy, AuraBioPipeline
from aura_bio.retrieval.strategies import query_variants
from aura_bio.study.claims import parse_claims
from aura_bio.study.indexing import StudyIndexer
from aura_bio.study.reranking import StudyReranker
from aura_bio.study.routing import StudyRouter
from aura_bio.study.schema import Extraction, Locator, Unit
from aura_bio.study.searcher import StudyEvidence, StudySearcher
from aura_bio.study.storage import StudyStore
from aura_bio.study.verification import StudyVerifier
from aura_bio.study.completion import assess_completion


def hit(number, text):
    return StudyEvidence(f'{number:032x}', 'lesson', 'Lesson', None, text, None, None,
                         'pack_sparse', 1.0, pack_id='a' * 32, document_id='b' * 32)


class QuestionPartsTests(unittest.TestCase):
    def test_document_prefix_is_not_a_standalone_search_variant(self):
        parts = query_variants('In R3.pdf, what is the assignment rule?')
        self.assertNotIn('In R3.pdf', parts)
        self.assertIn('what is the assignment rule', parts)

    def test_period_in_pdf_name_is_not_a_question_boundary(self):
        from aura_bio.retrieval.strategies import question_parts
        self.assertEqual(question_parts('Does R2.pdf prove this? What evidence is missing?'),
                         ['Does R2.pdf prove this', 'What evidence is missing'])

    def test_compound_request_keeps_roman_list_and_final_bias_question(self):
        question = ('In R3.pdf, how were species assigned to Groups I, II and III, '
                    'how many species were in each group, and what bias was acknowledged?')
        parts = query_variants(question)
        self.assertEqual(parts[0], question)
        self.assertTrue(any('Groups I, II and III' in part for part in parts[1:]))
        self.assertTrue(any('what bias' in part for part in parts[1:]))
        self.assertNotIn('III', parts)
        self.assertNotIn('II', parts)

    def test_reference_pages_do_not_displace_body_evidence(self):
        class Scorer:
            def predict(self, pairs, **kwargs):
                return [.95 if 'REFERENCES' in text else .8 for _, text in pairs]
        refs = hit(1, 'REFERENCES\n1. Author (2020). Calibration review.\n2. Other (2021). Study.')
        body = hit(2, 'Calibration requires three samples.')
        ranked, _ = StudyReranker(scorer=Scorer()).rerank('How is calibration performed?', [refs, body], 1)
        self.assertEqual([h.chunk_id for h in ranked], [body.chunk_id])

    def test_explicit_bibliography_question_can_retrieve_references(self):
        class Scorer:
            def predict(self, pairs, **kwargs):
                return [.95] * len(pairs)
        refs = hit(1, 'REFERENCES\n1. Author (2020). Calibration review.')
        ranked, _ = StudyReranker(scorer=Scorer()).rerank('List the bibliography references.', [refs], 1)
        self.assertEqual(len(ranked), 1)


class CrossPageContextTests(unittest.TestCase):
    def test_already_selected_caveat_is_not_pushed_out_by_new_neighbours(self):
        from aura_bio.study.context import with_neighbours
        anchors = [hit(1, 'Groups use study frequency.'), hit(2, 'Three groups were reported.'),
                   hit(3, 'Species counts were measured.')]
        bias = hit(4, 'The disadvantage is that highly invasive species may be understudied.')
        class Searcher:
            runtime_warnings = []
            def neighbors(self, *args, **kwargs):
                return [hit(5, 'METHODS: group classification was introduced.'),
                        hit(6, 'groups and species and classification were described.')]
        chosen = with_neighbours(Searcher(),
            'How were species assigned to groups, and what bias is acknowledged?',
            anchors + [bias], max_passages=5)[:5]
        self.assertIn(bias.chunk_id, [item.chunk_id for item in chosen])

    def test_bias_continuation_is_not_crowded_out_by_generic_neighbours(self):
        from aura_bio.study.context import with_neighbours
        anchors = [hit(1, 'The groups were based on research frequency.'),
                   hit(2, 'The study reports three groups.'), hit(3, 'Counts were recorded.')]
        background = hit(4, 'groups and species and classification methods were introduced.')
        methods = hit(5, 'METHODS: the group classification used study thresholds.')
        bias = hit(6, 'The disadvantage is that highly invasive species may be understudied '
                       'in regions with a low density of ecologists.')
        class Searcher:
            runtime_warnings = []
            def neighbors(self, *args, **kwargs):
                return [background, methods, bias]
        chosen = with_neighbours(Searcher(),
            'How were species assigned to groups, and what potential bias is acknowledged?',
            anchors, max_passages=5)[:5]
        self.assertIn(bias.chunk_id, [item.chunk_id for item in chosen])
        self.assertTrue({item.chunk_id for item in anchors} <= {item.chunk_id for item in chosen})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StudyStore(Path(self.tmp.name) / 'packs')
        self.pack = self.store.create_pack('Course')
        self.doc, _ = self.store.add_document(self.pack.pack_id, 'lesson.txt', io.BytesIO(b'fixture'))
        texts = [
            'METHODS\nGroups use the study-frequency thresholds: Group I >=10, Group II 5-9 and Group III 1-4.',
            'RESULTS\nThere were 33 species in Group I, 38 in Group II and 104 in Group III. '
            'Further work should use single-cell and TCR profiling to test for the',
            'presence of expanded clonotypes that kill cancer cells. The endpoint is cancer-cell killing.',
            'REFERENCES\n1. Author (2020). Groups.\n2. Other (2021). Species.\n3. More (2022). Study.',
        ]
        units = [Unit(f'{n:032x}', self.doc.document_id, n - 1, 'body', 'Lesson', f'page-{n}',
                      text, (Locator('pdf', page=n),)) for n, text in enumerate(texts, 1)]
        self.store.publish_extraction(self.doc.document_id, Extraction(units, [], [], {}, 'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_standard_context_keeps_definitions_and_next_page_continuation(self):
        question = 'How were groups assigned and what follow-up was proposed?'
        with StudySearcher(self.store, self.pack.pack_id, question=question) as searcher:
            hits = searcher._scope_candidates(self.store.units(self.pack.pack_id, self.doc.document_id), 20)
            selected = [h for h in hits if h.locators[0].page == 2]
            chosen = searcher.finalize_evidence(question, selected, selected, max_passages=4, max_chars=14000)
            self.assertEqual({loc.page for h in chosen for loc in h.locators}, {1, 2, 3})
            self.assertTrue(any('cancer-cell killing' in h.text for h in chosen))

    def test_explicit_page_scope_does_not_expand_to_other_pages(self):
        question = 'Explain page 2'
        with StudySearcher(self.store, self.pack.pack_id, question=question) as searcher:
            hits = searcher.search(question, 5, 20)
            chosen = searcher.finalize_evidence(question, hits, hits, max_passages=4, max_chars=14000)
            self.assertEqual({loc.page for h in chosen for loc in h.locators}, {2})

    def test_empty_retrieval_does_not_fill_context_from_arbitrary_pages(self):
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            self.assertEqual(searcher.finalize_evidence('Explain ORIONX99', [], [],
                             max_passages=4, max_chars=14000), [])

    def test_neighbours_keep_original_document_and_provenance(self):
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            selected = searcher._scope_candidates(self.store.units(self.pack.pack_id, self.doc.document_id), 20)[1:2]
            chosen = searcher.finalize_evidence('Explain the group assignment and follow-up', selected, selected,
                                              max_passages=4, max_chars=14000)
            self.assertTrue(all(h.document_id == self.doc.document_id and h.provenance == 'native_text' for h in chosen))
            self.assertLessEqual(sum(len(h.text) for h in chosen), 14000)

    def test_neighbour_expansion_cannot_displace_three_primary_anchors(self):
        units = [Unit(f'{n:032x}', self.doc.document_id, n - 1, 'body', 'Lesson', f'page-{n}',
                      f'Sample mechanism evidence on page {n}.', (Locator('pdf', page=n),))
                 for n in range(1, 8)]
        self.store.publish_extraction(self.doc.document_id, Extraction(units, [], [], {}, 'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            hits = searcher._scope_candidates(units, 20)
            selected = [h for h in hits if h.locators[0].page in {2, 4, 6}]
            chosen = searcher.finalize_evidence('Explain the sample mechanism', selected, hits,
                                              max_passages=4, max_chars=14000)
            self.assertTrue({h.chunk_id for h in selected} <= {h.chunk_id for h in chosen})


class CompletionSelectionTests(unittest.TestCase):
    def test_topic_words_in_other_claims_do_not_cover_a_specific_endpoint(self):
        question = ('Does ORION T-cell activity cause resistance? What evidence is missing, '
                    'and what follow-up experiment is proposed?')
        source = hit(1, 'presence of expanded ORION T-cell clonotypes which engage in target-cell killing.')
        report = assess_completion(question, [
            'Effector-function evidence for ORION T cells is missing.',
            'The proposed experiment would use ORION single-cell and receptor profiling.'
        ], [source])
        self.assertIn('what follow-up experiment is proposed', report['possible_omissions'])

    def test_generic_objective_does_not_hide_the_specific_experimental_endpoint(self):
        source = hit(1, 'We propose single-cell profiling to investigate ORION cells. '
                        'This would reveal the presence of expanded clonotypes engaging in target-cell killing.')
        question = 'What follow-up experiment do the authors propose to investigate that role?'
        report = assess_completion(question,
            ['We propose single-cell profiling to investigate ORION cells.'], [source])
        self.assertIn(question, report['possible_omissions'])

    def test_methods_alone_do_not_cover_a_proposed_experiments_objective(self):
        source = hit(1, 'We propose single-cell profiling to test whether expanded '
                        'clonotypes engage in target-cell killing.')
        question = 'What follow-up experiment do the authors propose to investigate that role?'
        coverage = assess_completion(question,
            ['The authors propose single-cell profiling.'], [source])
        self.assertIn(question, coverage['possible_omissions'])
        complete = assess_completion(question,
            ['The proposed single-cell profiling would test whether expanded clonotypes '
             'engage in target-cell killing.'], [source])
        self.assertEqual(complete['possible_omissions'], [])

    def test_evidence_question_needs_a_conclusion_not_only_topic_overlap(self):
        question = 'Does the paper directly demonstrate that ORION cells cause resistance? What evidence is missing?'
        coverage = assess_completion(question,
            ['Missing effector-function evidence prevents assessment of ORION cells and resistance.'])
        self.assertIn('Does the paper directly demonstrate that ORION cells cause resistance',
                      coverage['possible_omissions'])
        complete = assess_completion(question, ['The causal resistance role of ORION cells remains unproven.',
                                                'Effector-function evidence is missing.'])
        self.assertEqual(complete['possible_omissions'], [])

    def test_statistical_p_value_is_not_a_classification_threshold(self):
        sources = [hit(1, 'Groups were categorized by origin (p<0.001). '
                          'Group I required TS >=10. Groups II and III used TS 5-9 and 1-4.')]
        coverage = assess_completion('How were species assigned to Groups I, II and III?',
            ['Species were assigned using TS >=10 for Group I, 5-9 for Group II and 1-4 for Group III.'], sources)
        self.assertEqual(coverage['possible_omissions'], [])

    def test_threshold_numbers_do_not_count_as_group_population_counts(self):
        question = 'How were species assigned to groups, and how many species were in each group?'
        coverage = assess_completion(question, ['Species were assigned using TS >=10, TS 5-9 and TS 1-4.'])
        self.assertIn('how many species were in each group', coverage['possible_omissions'])

    def test_classification_coverage_flags_missing_source_thresholds(self):
        question = 'How were samples assigned to Groups I, II and III?'
        sources = [hit(1, 'Samples with TS >=10 were assigned to Group I. '
                          'Groups II and III used TS ranges of 5-9 and 1-4.')]
        partial = assess_completion(question, ['Groups were based on study frequency.'], sources)
        complete = assess_completion(question, ['Group I required TS >=10; Groups II and III used 5-9 and 1-4.'], sources)
        self.assertEqual(partial['possible_omissions'], [question])
        self.assertEqual(complete['possible_omissions'], [])
        self.assertFalse(complete['completeness_verified'])

    def test_simple_semantic_paraphrase_is_not_rejected_by_coverage_heuristic(self):
        report = assess_completion('Why does this happen?', ['Insufficient oxygen restricts respiration.'])
        self.assertFalse(report['assessed'])
        self.assertEqual(report['possible_omissions'], [])

    def pipeline(self, drafts):
        class Searcher:
            def search(self, *args, **kwargs):
                return [hit(1, 'Seven samples were measured. The small sample limits conclusions. '
                               'The instrument is blue. The room is quiet. The protocol is brief.')]
        class Generator:
            last_metadata = {}
            def generate_claims(self, route, evidence, instructions=()):
                rows = drafts.pop(0)
                return parse_claims(json.dumps({'version': 1, 'claims': [
                    {'claim': text, 'cite_ids': [1]} for text in rows]}), 1)
        return AuraBioPipeline(Generator(), searcher=Searcher(), router=StudyRouter(),
            verifier=StudyVerifier(use_entailment=False), accuracy_mode='robust', draft_candidates=2,
            answer_policy=AnswerPolicy('pack_only', 'a' * 32))

    def test_more_claims_cannot_win_over_covering_both_requested_parts(self):
        pipeline = self.pipeline([
            ['Seven samples were measured.', 'The instrument is blue.', 'The room is quiet.', 'The protocol is brief.'],
            ['Seven samples were measured.', 'The small sample limits conclusions.'],
        ])
        answer = pipeline.answer('How many samples were measured, and what limitation was reported?', use_critic=False)
        self.assertIn('small sample limits', answer.text)
        self.assertNotIn('room is quiet', answer.text)
        self.assertIn('question_coverage', answer.trace.final_record['delivery'])

    def test_omitted_extra_draft_is_not_described_as_missing_requested_detail(self):
        pipeline = self.pipeline([
            ['Seven samples were measured.', 'The moon consists of cheese.'],
            ['Seven samples were measured.', 'The moon consists of cheese.'],
        ])
        answer = pipeline.answer('How many samples were measured?', use_critic=False)
        self.assertNotIn('requested details could not be confirmed', answer.text)
        self.assertIn('omitted', answer.text.lower())
