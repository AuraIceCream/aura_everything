import unittest
from aura_bio.study.schema import Unit,Locator,StudyError
from aura_bio.study.visual.schema import RenderedAsset,SourceTransform,NormalizedBox
from aura_bio.study.visual.selection import select_figures,create_crop


def unit(n, text='prose '*400, **metadata):
    return Unit(f'{n:032x}','b'*32,n,'body','Slide','',''+text,(Locator('pdf',page=n+1),),metadata,(f'{n:032x}',))


def asset(n, checksum='diagram', size=(500,500)):
    return RenderedAsset(f'{n:032x}',*size,checksum,SourceTransform(*size,*size),unit_id=f'{n:032x}',document_id='b'*32)


class FigureSelectionTests(unittest.TestCase):
    def test_vector_figure_on_text_heavy_page_selected(self):
        candidates = select_figures([unit(1,has_drawings=True,visual_regions=[[.1,.2,.7,.8]])],[asset(1)],limit=20)
        self.assertIsNone(candidates[0].exclusion_reason)
        self.assertEqual(candidates[0].frame,'page_normalized')

    def test_repeated_logo_skipped(self):
        candidates = select_figures([unit(n) for n in range(200)],[asset(n,'logo',(50,50)) for n in range(200)],limit=20)
        self.assertEqual(len(candidates),200)
        self.assertTrue(all(c.exclusion_reason for c in candidates))

    def test_repeated_diagram_keeps_all_occurrences(self):
        candidates = select_figures([unit(n,has_drawings=True) for n in range(3)],[asset(n) for n in range(3)],limit=20)
        self.assertEqual(len({c.figure_id for c in candidates}),3)
        self.assertEqual({c.locator['page'] for c in candidates},{1,2,3})

    def test_text_only_page_not_sent(self):
        self.assertEqual(select_figures([unit(1)],[asset(1)],limit=20)[0].exclusion_reason,'text_only')

    def test_garbage_text_layer_is_eligible_for_explicit_ocr(self):
        candidate=select_figures([unit(1,text='\ufffd'*200)],[asset(1)],limit=20)[0]
        self.assertIsNone(candidate.exclusion_reason)
        self.assertEqual(candidate.reason,'ocr_required_manual_available')

    def test_garbage_text_layer_is_eligible_for_explicit_ocr(self):
        candidate=select_figures([unit(1,text='\ufffd'*200)],[asset(1)],limit=20)[0]
        self.assertIsNone(candidate.exclusion_reason)
        self.assertEqual(candidate.reason,'ocr_required_manual_available')

    def test_uncertain_region_exposes_manual_page_candidate(self):
        self.assertEqual(select_figures([unit(1,has_drawings=True)],[asset(1)],limit=20)[0].reason,'uncertain_page_manual_available')

    def test_manual_crop_validated_in_source_frame(self):
        candidate = select_figures([unit(1)],[asset(1)],limit=20)[0]
        crop = create_crop(candidate,NormalizedBox(.2,.3,.8,.9))
        self.assertIsNone(crop.exclusion_reason)
        self.assertEqual(crop.reason,'manual_crop')
        self.assertNotEqual(candidate.figure_id,crop.figure_id)
