"""Guard document selection, not model knowledge, using authored source fixtures."""
import io
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace

from aura_bio.study.schema import Extraction, Locator, Unit, StudyError
from aura_bio.study.storage import StudyStore
from aura_bio.study.indexing import StudyIndexer
from aura_bio.study.searcher import StudySearcher
from aura_bio.study.visual.selection import select_figures
from test_figure_selection import asset, unit


def large_description():
    import json
    labels=[f'L{n:02d}'+('!?'*48) for n in range(32)]
    return json.dumps({'kind':'pathway','labels':labels,'axes':[],
        'relations':[{'from':labels[n],'to':labels[n+1],'relation':'arrow'} for n in range(24)],
        'summary':'Visible connections.','uncertainties':['Some labels are unclear.']})


class FigureTargetTests(unittest.TestCase):
    def test_maximum_live_description_is_atomic_even_with_dense_punctuation(self):
        from aura_bio.study.chunking import chunk_units
        from aura_bio.study.visual.description import validate_live_description
        text=large_description()
        validate_live_description(text)
        figure=Unit('f'*32,'d'*32,0,'figure_description','Figure','',text,
            (Locator('pdf',page=1),),{},(),'vlm',{'figure_label':'5'})
        chunks=chunk_units([figure])
        self.assertEqual(len(chunks),1)
        self.assertEqual(chunks[0].text,text)

    def test_multiple_references_and_panel_qualifiers_select_each_parent_figure(self):
        from aura_bio.study.questions import references,Reference
        self.assertEqual(references('Compare Figs. 5a and 6(b), 7'),[Reference('figure','5'),Reference('figure','6'),Reference('figure','7')])
    def test_same_numbered_table_and_figure_remain_distinct(self):
        page=unit(1,text='Fig. 5 | Pathway.\nTable 5 | Measurements.',visual_regions=[[.1,.1,.8,.3],[.1,.6,.8,.8]],
            figure_anchors=[{'kind':'figure','label':'5','caption':'Fig. 5 | Pathway.','bbox':[.1,.31,.8,.35]},
                            {'kind':'table','label':'5','caption':'Table 5 | Measurements.','bbox':[.1,.81,.8,.85]}])
        figures=select_figures([page],[asset(1)])
        self.assertEqual({f.reference_kind for f in figures},{'figure','table'})
        self.assertEqual(len({f.figure_id for f in figures}),2)
    def test_study_router_recognizes_question_families_without_a_biology_classifier(self):
        from aura_bio.study.routing import StudyRouter
        for question,task in [('Compare ORION and VEGA','comparison'),('Explain the wash procedure','process_explanation'),
                              ('Calculate the dilution','numerical'),('Summarize this document','summary'),
                              ('What total follows?','numerical'),
                              ('Make practice questions from this PDF','quiz_generation')]:
            with self.subTest(question=question):
                self.assertEqual(StudyRouter().route(question).task_type.label,task)

    def test_two_captioned_figures_do_not_become_one_whole_page_crop(self):
        page = unit(1, text='Fig. 5 | Wash procedure.\nFig. 6 | Control diagram.',
            visual_regions=[[.1,.1,.8,.35],[.1,.6,.8,.85]],
            figure_anchors=[{'label':'5','caption':'Fig. 5 | Wash procedure.', 'bbox':[.1,.36,.8,.4]},
                            {'label':'6','caption':'Fig. 6 | Control diagram.', 'bbox':[.1,.86,.8,.9]}])
        figures = select_figures([page], [asset(1)])
        self.assertEqual([f.figure_label for f in figures], ['5','6'])
        self.assertLess(figures[0].bbox.y1, .55)
        self.assertGreater(figures[1].bbox.y0, .5)

    def test_caption_context_not_arbitrary_first_four_thousand_chars(self):
        from aura_bio.study.visual.selection import figure_context
        page = unit(1, text='Unrelated introduction. ' * 250 + '\nFig. 5 | Wash with buffer ORION.')
        figure = replace(select_figures([page], [asset(1)])[0], figure_label='5', caption='Fig. 5 | Wash with buffer ORION.')
        context = figure_context(page, figure)
        self.assertIn('Wash with buffer ORION', context)
        self.assertLess(len(context), 4001)


class DocumentQuestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StudyStore(Path(self.tmp.name) / 'packs')
        self.pack = self.store.create_pack('Study material')
        self.doc, _ = self.store.add_document(self.pack.pack_id, 'lesson.txt', io.BytesIO(b'fixture'))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def publish(self, document=None):
        document = document or self.doc
        units = [Unit(f'{n:032x}', document.document_id, n-1, 'body', 'Lesson', str(n), text,
                      (Locator('pdf',page=n),), metadata) for n,text,metadata in (
            (1,'Introduction describes calibration.',{}),
            (2,'Results refer to Fig. 5 in passing.',{}),
            (3,'Fig. 5 | Wash procedure. Wash with ORION buffer then seal the vessel.',
                {'figure_anchors':[{'label':'5','caption':'Fig. 5 | Wash procedure.','bbox':[.1,.7,.9,.8]}]}),
            (4,'Conclusion: controls exclude background activity.',{}))]
        self.store.publish_extraction(document.document_id, Extraction(units, [], [], {}, 'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)

    def test_page_reference_retrieves_even_without_matching_content_words(self):
        self.publish()
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            hits = searcher.search('Explain page 3', 5, 20)
            self.assertTrue(hits)
            self.assertEqual({loc.page for hit in hits for loc in hit.locators}, {3})
            self.assertIn('ORION', hits[0].text)

    def test_page_and_figure_constraints_intersect(self):
        self.publish()
        with StudySearcher(self.store,self.pack.pack_id) as searcher:
            self.assertEqual(searcher.search('Explain Fig. 5 on page 1',5,20),[])

    def test_bounded_page_range_includes_each_requested_page(self):
        self.publish()
        with StudySearcher(self.store,self.pack.pack_id) as searcher:
            hits=searcher.search('Explain pages 2-4',5,20)
            self.assertEqual({loc.page for hit in hits for loc in hit.locators},{2,3,4})

    def test_figure_reference_prefers_caption_not_earlier_cross_reference(self):
        self.publish()
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            hits = searcher.search('Explain the procedure in Fig. 5', 5, 20)
            self.assertTrue(hits)
            self.assertEqual(hits[0].locators[0].page, 3)

    def test_overview_samples_beginning_middle_and_end(self):
        self.publish()
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            hits = searcher.search('Summarize this document for my exam', 4, 20)
            self.assertEqual({loc.page for hit in hits for loc in hit.locators}, {1,2,3,4})

    def test_overview_keeps_ranked_evidence_alongside_coverage(self):
        self.publish()
        with StudySearcher(self.store,self.pack.pack_id) as searcher:
            hits=searcher.search('Summarize this document, focusing on ORION',4,20)
            selected=sorted(hits,key=lambda h:h.locators[0].page,reverse=True)[:2]
            chosen=searcher.finalize_evidence('Summarize this document',selected,hits,max_passages=2,max_chars=14000)
            self.assertEqual(chosen[0].chunk_id,selected[0].chunk_id)
            self.assertTrue(any(h.channel=='pack_sparse' for h in hits))

    def test_figure_retains_caption_and_relevant_methods_elsewhere_in_same_document(self):
        self.publish()
        units=self.store.units(self.pack.pack_id,self.doc.document_id)
        units=[replace(u,text='ORION wash procedure: calibrate the pump first, then rinse for seven minutes.') if u.ordinal==0 else u for u in units]
        self.store.publish_extraction(self.doc.document_id,Extraction(units,[],[],{},'fixture'))
        other,_=self.store.add_document(self.pack.pack_id,'unrelated.txt',io.BytesIO(b'other'))
        self.store.publish_extraction(other.document_id,Extraction([Unit('e'*32,other.document_id,0,'body','Other','','ORION wash unrelated instructions.',(Locator('pdf',page=1),))],[],[],{},'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        question='Explain the ORION wash procedure in Fig. 5'
        with StudySearcher(self.store,self.pack.pack_id,question=question) as searcher:
            hits=searcher.search(question,6,30)
            chosen=searcher.finalize_evidence(question,hits,hits,max_passages=6,max_chars=14000)
            self.assertEqual({h.document_id for h in chosen},{self.doc.document_id})
            self.assertTrue(any('calibrate the pump' in h.text for h in chosen))
            self.assertTrue(any('Fig. 5 |' in h.text for h in chosen))

    def test_missing_locator_does_not_fall_back_to_other_content(self):
        self.publish()
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            self.assertEqual(searcher.search('Explain calibration on page 99', 5, 20), [])

    def test_merged_short_pages_are_trimmed_to_requested_page(self):
        units = [Unit(f'{n:032x}', self.doc.document_id,n,'body','Lesson','',text,(Locator('pdf',page=n),))
                 for n,text in [(1,'Secret unrelated FIRST page.'),(2,'ORION wash SECOND page.'),(3,'Unrelated THIRD page.')]]
        self.store.publish_extraction(self.doc.document_id, Extraction(units, [], [], {}, 'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store,self.pack.pack_id) as searcher:
            hits = searcher.search('Explain page 2',5,20)
            self.assertEqual(hits[0].text, 'ORION wash SECOND page.')
            self.assertEqual([loc.page for loc in hits[0].locators], [2])

    def test_requested_figure_keeps_its_current_interpretation(self):
        self.publish()
        units = self.store.units(self.pack.pack_id,self.doc.document_id)
        interpretation = Unit('f'*32,self.doc.document_id,2,'figure_description','Lesson','','Wash then seal.',
            (Locator('pdf',page=3),), {}, (), 'vlm', {'figure_label':'5','numbers_verified':False})
        self.store.publish_extraction(self.doc.document_id, Extraction([*units,interpretation],[],[],{},'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store,self.pack.pack_id) as searcher:
            hits = searcher.search('Explain Fig. 5',5,20)
            chosen = searcher.finalize_evidence('Explain Fig. 5',hits,hits,max_passages=6,max_chars=14000)
            self.assertIn('vlm', [h.provenance for h in chosen])

    def test_long_caption_page_cannot_starve_its_visual_interpretation(self):
        self.publish()
        units = self.store.units(self.pack.pack_id,self.doc.document_id)
        units = [replace(u,text=u.text+' context '*5000) if u.ordinal==2 else u for u in units]
        units.append(Unit('f'*32,self.doc.document_id,2,'figure_description','Lesson','','A points to B.',
            (Locator('pdf',page=3),),{},(),'vlm',{'figure_label':'5','numbers_verified':False}))
        self.store.publish_extraction(self.doc.document_id,Extraction(units,[],[],{},'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store,self.pack.pack_id) as searcher:
            hits=searcher.search('Explain Fig. 5',3,30)
            self.assertIn('vlm',[h.provenance for h in hits])
            chosen=searcher.finalize_evidence('Explain Fig. 5',hits,hits,max_passages=3,max_chars=14000)
            self.assertIn('vlm',[h.provenance for h in chosen])

    def test_reserved_native_passage_is_the_caption_not_the_start_of_a_long_page(self):
        self.publish()
        units=self.store.units(self.pack.pack_id,self.doc.document_id)
        units=[replace(u,text='Unrelated introduction. '*2000+'\nFig. 5 | Wash procedure. ORION wash then seal.',
                       metadata={'figure_anchors':[{'label':'5','caption':'Fig. 5 | Wash procedure. Unrelated neighbouring column.'}]})
               if u.ordinal==2 else u for u in units]
        self.store.publish_extraction(self.doc.document_id,Extraction(units,[],[],{},'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store,self.pack.pack_id) as searcher:
            hits=searcher.search('Explain Fig. 5',3,30)
            self.assertIn('Fig. 5 |',hits[0].text)

    def test_bounded_figure_description_keeps_its_structure_and_last_connection(self):
        import json
        self.publish()
        labels=[f'Step {n} with visible condition' for n in range(32)]
        fields={'kind':'pathway','labels':labels,'axes':[],
                'relations':[{'from':labels[n],'to':labels[n+1],'relation':'arrow'} for n in range(24)],
                'summary':'A visible multi-step procedure.','uncertainties':[]}
        text=json.dumps(fields)
        unit=Unit('f'*32,self.doc.document_id,2,'figure_description','Lesson','',text,
            (Locator('pdf',page=3),),{},(),'vlm',{'figure_label':'5','numbers_verified':False})
        units=self.store.units(self.pack.pack_id,self.doc.document_id)
        self.store.publish_extraction(self.doc.document_id,Extraction([*units,unit],[],[],{},'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store,self.pack.pack_id) as searcher:
            hits=searcher.search('Explain Fig. 5',6,30)
            figure_hits=[h for h in hits if h.provenance=='vlm']
            self.assertEqual(len(figure_hits),1)
            self.assertEqual(json.loads(figure_hits[0].text),fields)

    def test_multiple_large_figures_are_never_sliced_at_the_context_limit(self):
        import json
        self.publish()
        units=self.store.units(self.pack.pack_id,self.doc.document_id)
        units.append(Unit('e'*32,self.doc.document_id,4,'body','Lesson','','Fig. 6 | Other pathway.',
            (Locator('pdf',page=4),),{'figure_anchors':[{'label':'6','caption':'Fig. 6 | Other pathway.'}]}))
        text=large_description()
        for n,label in enumerate(('5','6')):
            units.append(Unit(f'{100+n:032x}',self.doc.document_id,5+n,'figure_description','Lesson','',text,
                (Locator('pdf',page=3+n),),{},(),'vlm',{'figure_label':label}))
        self.store.publish_extraction(self.doc.document_id,Extraction(units,[],[],{},'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        question='Compare Figs. 5 and 6'
        with StudySearcher(self.store,self.pack.pack_id,question=question) as searcher:
            hits=searcher.search(question,12,30)
            chosen=searcher.finalize_evidence(question,hits,hits,max_passages=12,max_chars=14000)
            figures=[h for h in chosen if h.provenance=='vlm']
            self.assertEqual(len(figures),1)
            self.assertEqual(json.loads(figures[0].text),json.loads(text))
            self.assertLessEqual(sum(len(h.text) for h in chosen),14000)
            self.assertTrue(any('omitted' in w and 'context budget' in w for w in searcher.runtime_warnings))

    def test_topical_figure_question_restores_complete_candidate_before_budgeting(self):
        from copy import copy
        self.publish()
        units=self.store.units(self.pack.pack_id,self.doc.document_id)
        text=large_description()
        units.append(Unit('f'*32,self.doc.document_id,4,'figure_description','Lesson','',text,
            (Locator('pdf',page=3),),{},(),'vlm',{}))
        self.store.publish_extraction(self.doc.document_id,Extraction(units,[],[],{},'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store,self.pack.pack_id) as searcher:
            candidates=[searcher._evidence(r[0]) for r in searcher.connection.execute('SELECT chunk_id FROM chunks')]
            original=next(h for h in candidates if h.provenance=='vlm')
            shortened=copy(original);shortened.text=original.text[:100]
            chosen=searcher.finalize_evidence('Explain visible connections',[shortened],candidates,max_passages=2,max_chars=14000)
            self.assertEqual(chosen[0].text,text)
            self.assertEqual(searcher.finalize_evidence('Explain visible connections',[shortened],candidates,max_passages=2,max_chars=100),[])


    def test_ambiguous_figure_across_documents_requires_a_choice(self):
        self.publish()
        other, _ = self.store.add_document(self.pack.pack_id, 'other.txt', io.BytesIO(b'other'))
        # Distinct generated unit IDs per document, as the real extractor produces.
        other_unit = Unit('e'*32, other.document_id, 0, 'body', 'Other', '', 'Fig. 5 | Other procedure.',
            (Locator('pdf',page=1),), {'figure_anchors':[{'label':'5','caption':'Fig. 5 | Other procedure.','bbox':[0,.8,1,.9]}]})
        self.store.publish_extraction(other.document_id, Extraction([other_unit], [], [], {}, 'fixture'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        with StudySearcher(self.store, self.pack.pack_id) as searcher:
            with self.assertRaises(StudyError) as error:
                searcher.search('Explain Fig. 5', 5, 20)
            self.assertEqual(error.exception.code, 'ambiguous_reference')


class PdfCaptionTests(unittest.TestCase):
    def test_caption_geometry_does_not_absorb_an_adjacent_column(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        from aura_bio.study.extractors_pdf import extract_pdf_page
        from aura_bio.study.schema import Document,Limits
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'columns.pdf'
            writer=PdfWriter();page=writer.add_blank_page(width=600,height=800)
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            stream=DecodedStreamObject()
            stream.set_data(b'BT /F1 9 Tf 40 300 Td (Fig. 5 | Target pathway.) Tj ET BT /F1 9 Tf 400 300 Td (Fig. 6 | Other pathway.) Tj ET')
            page[NameObject('/Contents')]=writer._add_object(stream);writer.write(path)
            result=extract_pdf_page(path,Document('a'*32,'b'*32,'columns.pdf','','pdf'),1,Limits())
        anchors=result.metadata['figure_anchors']
        self.assertEqual([a['label'] for a in anchors],['5','6'])
        self.assertEqual(anchors[0]['caption'],'Fig. 5 | Target pathway.')
        self.assertLess(anchors[0]['bbox'][2],.5)

    def test_page_extraction_keeps_caption_geometry_and_ignores_prose_mentions(self):
        from study_fixtures import pdf_fixture
        from aura_bio.study.extractors_pdf import extract_pdf_page
        from aura_bio.study.schema import Document, Limits
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'caption.pdf'
            pdf_fixture(path, ('Results mention Fig. 5.', 'Fig. 5 | ORION wash procedure.'))
            doc = Document('a'*32,'b'*32,'caption.pdf','','pdf')
            mention = extract_pdf_page(path,doc,1,Limits())
            page = extract_pdf_page(path,doc,2,Limits())
        labels = page.metadata.get('figure_anchors', [])
        self.assertEqual(mention.metadata.get('figure_anchors'), [])
        self.assertEqual([a['label'] for a in labels], ['5'])
        self.assertEqual(labels[0]['caption'], 'Fig. 5 | ORION wash procedure.')
        self.assertEqual(len(labels[0]['bbox']), 4)
