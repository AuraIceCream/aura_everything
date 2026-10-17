import hashlib
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path
from PIL import Image
from aura_bio.study.schema import Limits, StudyError
from aura_bio.study.visual.assets import decode_image, render_pdf_page
from aura_bio.study.visual.schema import SourceTransform, NormalizedBox
from study_fixtures import pdf_fixture


class VisualAssetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_decompression_bomb_rejected(self):
        path = self.root / 'big.png'
        Image.new('RGB', (101, 101)).save(path)
        with self.assertRaises(StudyError):
            decode_image(path, Limits(max_image_pixels=10_000))

    def test_signature_mismatch_rejected(self):
        path = self.root / 'bad.png'
        path.write_bytes(b'not png')
        with self.assertRaises(StudyError): decode_image(path, Limits())

    def test_multiframe_rejected(self):
        path = self.root / 'animation.png'
        Image.new('RGB', (10, 10), 'red').save(path, save_all=True, append_images=[Image.new('RGB',(10,10),'blue')])
        with self.assertRaises(StudyError): decode_image(path, Limits())

    def test_exif_rotation_applied(self):
        path = self.root / 'rotated.jpg'
        exif = Image.Exif(); exif[274] = 6
        Image.new('RGB', (80, 40)).save(path, exif=exif)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        asset = decode_image(path, Limits())
        self.assertEqual((asset.width,asset.height), (40,80))
        self.assertEqual(asset.transform.rotation, 90)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_bbox_roundtrips_through_transform(self):
        for rotation in (0,90,180,270):
            transform = SourceTransform(800,600,600,800,rotation)
            box = (80,60,560,420)
            for actual,expected in zip(transform.to_original(transform.to_display(box)),box):
                self.assertAlmostEqual(actual,expected,delta=1)
        with self.assertRaises(StudyError): NormalizedBox(-0.1,0,1,1)

    def test_cropped_pdf_transform_roundtrip(self):
        transform=SourceTransform(800,600,300,200,90,units='points',crop_offset=(100,80),crop_width=400,crop_height=300)
        original=(120,110,420,350)
        for value,expected in zip(transform.to_original(transform.to_display(original)),original):
            self.assertAlmostEqual(value,expected,delta=1)

    def test_pdf_render_ceiling(self):
        path = self.root / 'page.pdf'; pdf_fixture(path, ('Page one',))
        asset = render_pdf_page(path, 1, Limits(render_dpi=400, max_render_pixels=20_000))
        self.assertLessEqual(asset.width*asset.height, 20_000)
        self.assertLessEqual(asset.metadata['dpi'], 200)

    def test_upload_validation_does_not_decode_pixels_in_request(self):
        from aura_bio.study.validation import validate_container
        path=self.root/'safe.png'; Image.new('RGB',(20,20)).save(path)
        with patch('PIL.ImageOps.exif_transpose',side_effect=AssertionError('Unbounded request decode')):
            validate_container(path,'png',Limits())

    def test_rotated_cropped_vector_pdf_region_matches_render(self):
        from pypdf import PdfWriter
        from pypdf.generic import NameObject,DecodedStreamObject,RectangleObject
        from aura_bio.study.schema import Document
        from aura_bio.study.extractors_pdf import extract_pdf_page
        from aura_bio.study.visual.selection import select_figures
        writer=PdfWriter(); page=writer.add_blank_page(width=400,height=300)
        stream=DecodedStreamObject(); stream.set_data(b'1 0 0 rg 100 80 100 50 re f')
        page[NameObject('/Contents')]=writer._add_object(stream)
        page.cropbox=RectangleObject((50,50,350,250)); page.rotate(90)
        path=self.root/'rotated-crop.pdf'; writer.write(path)
        # No embedded bitmap: selection must discover the rendered vector rectangle.
        doc=Document('a'*32,'b'*32,'rotated-crop.pdf','pdf','checksum',path.stat().st_size)
        unit=extract_pdf_page(path,doc,1,Limits())
        asset=replace(render_pdf_page(path,1,Limits()),unit_id=unit.unit_id,document_id=doc.document_id)
        figure=select_figures([unit],[asset])[0]
        self.assertEqual(figure.reason,'drawing_region')
        expected=asset.transform.to_display((100,170,200,220))
        # Selection margin is 0.05; the source rectangle must otherwise align.
        for actual,target in zip(figure.bbox.values(),(expected.x0-.05,expected.y0-.05,expected.x1+.05,expected.y1+.05)):
            self.assertAlmostEqual(actual,max(0,min(1,target)),delta=1/asset.width)
