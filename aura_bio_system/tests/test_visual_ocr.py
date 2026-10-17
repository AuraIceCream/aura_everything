import unittest
from pathlib import Path
from aura_bio.study.schema import Unit,Locator,StudyError
from aura_bio.study.visual.schema import RenderedAsset,SourceTransform
from aura_bio.study.visual.ocr import needs_ocr,parse_tsv,ocr_unit,TesseractOcr


class VisualOcrTests(unittest.TestCase):
    def test_garbage_text_layer_triggers_ocr(self):
        self.assertTrue(needs_ocr('�'*30))
        self.assertTrue(needs_ocr('(cid:42) '*20))
        self.assertTrue(needs_ocr(''))

    def test_greek_and_gene_labels_do_not_trigger_garbage_rule(self):
        self.assertFalse(needs_ocr('BRCA1, IL6 and α-β signalling are described here.'))

    def test_tsv_boxes_and_confidence_preserved(self):
        tsv='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t73.5\t7\n'
        result = parse_tsv(tsv,SourceTransform(100,100,100,100),'eng','test')
        self.assertEqual(result.words[0]['confidence'],73.5)
        self.assertEqual(result.words[0]['bbox'],[.1,.2,.4,.3])
        parent=Unit('a'*32,'b'*32,0,'body','','','',(Locator('pdf',page=1),))
        unit=ocr_unit(parent,result)
        self.assertEqual(unit.provenance,'ocr')
        self.assertFalse(unit.provenance_details['numbers_verified'])

    def test_page_timeout_is_bounded(self):
        asset=RenderedAsset('a'*32,100,100,'hash',SourceTransform(100,100,100,100))
        with self.assertRaises(StudyError): TesseractOcr().read(asset,language='eng',timeout_seconds=1)

    def test_missing_language_or_engine_fails_visibly(self):
        asset=RenderedAsset('a'*32,100,100,'hash',SourceTransform(100,100,100,100))
        with self.assertRaises(StudyError): TesseractOcr(executable='no-such-tesseract').read(asset,language='eng',timeout_seconds=60)

    @unittest.skipUnless(Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe').exists(),'Installed Tesseract CPU smoke unavailable')
    def test_real_installed_tesseract_cpu_smoke(self):
        from aura_bio.study.visual.assets import decode_image
        from aura_bio.study.schema import Limits
        asset=decode_image(Path(__file__).resolve().parents[1]/'benchmarks/figure_fixtures/figure-01.png',Limits())
        result=TesseractOcr().read(asset,language='eng',timeout_seconds=60)
        self.assertTrue(result.words)
        self.assertIn('TEACHING',result.text.upper())
