from dataclasses import replace
import io
import json
import time
import unittest
from test_figure_description import figure_input,Backend,FIELDS
from aura_bio.study.schema import StudyError


class VisualFocusTests(unittest.TestCase):
    def module(self):
        try: from aura_bio.study.visual import focus
        except ImportError: self.fail('Owned focused reading is not implemented.')
        return focus

    def test_missing_geometry_does_not_invent_crop(self):
        api=self.module(); figure=figure_input().candidate
        proposed={'panels':[{'id':'D','bbox':{'x0':0,'y0':0,'x1':.5,'y1':.5}}]}
        self.assertEqual(api.select_focus('Explain panel D',figure,proposed),())

    def test_owned_panel_and_shared_legend_are_kept_together(self):
        api=self.module(); figure=figure_input().candidate
        data={'owned_regions':[{'id':'D','bbox':{'x0':.1,'y0':.1,'x1':.4,'y1':.4},
            'source_hash':figure.checksum,'frame':figure.frame,'origin':'user_annotation',
            'context_refs':['legend']}], 'context_regions':{'legend':{'x0':.4,'y0':.1,'x1':.6,'y1':.4}}}
        regions=api.select_focus('Explain panel D',figure,data)
        self.assertEqual(len(regions),1)
        self.assertEqual(regions[0].bbox.x1,.6)
        self.assertEqual(regions[0].context_refs,('legend',))

    def test_foreign_source_geometry_is_rejected(self):
        api=self.module(); figure=figure_input().candidate
        data={'owned_regions':[{'id':'D','bbox':{'x0':0,'y0':0,'x1':.5,'y1':.5},
            'source_hash':'foreign','frame':figure.frame,'origin':'native_text','context_refs':[]}]}
        with self.assertRaises(StudyError): api.select_focus('Explain panel D',figure,data)

    def test_two_region_budget_includes_repair(self):
        api=self.module()
        from aura_bio.study.visual.description import FigureDescriber
        budget=api.FocusBudget(2,time.monotonic()+300)
        backend=Backend(['bad',json.dumps(FIELDS),json.dumps(FIELDS)])
        FigureDescriber(backend).describe(figure_input(),call_budget=budget)
        with self.assertRaises(StudyError):
            FigureDescriber(backend).describe(figure_input(),call_budget=budget)
        self.assertEqual(backend.calls,2)

    def test_shared_deadline_is_not_reset_for_next_region(self):
        api=self.module(); budget=api.FocusBudget(2,300,clock=lambda:301)
        with self.assertRaises(StudyError): budget.reserve_call()
        self.assertEqual(budget.calls,0)

    def test_cancellation_is_checked_before_each_provider_attempt(self):
        api=self.module();cancelled=[False]
        def check():
            if cancelled[0]: raise StudyError('job_cancelled','Cancelled')
        try: budget=api.FocusBudget(2,time.monotonic()+300,before_call=check)
        except TypeError: self.fail('Focused calls do not check cancellation inside a multi-region request.')
        budget.reserve_call();cancelled[0]=True
        with self.assertRaises(StudyError): budget.reserve_call()
        self.assertEqual(budget.calls,1)

    def test_timeout_is_not_reuploaded(self):
        api=self.module()
        from aura_bio.study.visual.description import FigureDescriber
        class Timeout:
            calls=0
            def complete(self,*args,**kwargs): self.calls+=1;raise StudyError('provider_timeout','Unknown')
        backend=Timeout();budget=api.FocusBudget(2,time.monotonic()+300)
        with self.assertRaises(StudyError): FigureDescriber(backend).describe(figure_input(),call_budget=budget)
        self.assertEqual(backend.calls,1)

    def test_original_render_cropped_before_downscale(self):
        api=self.module()
        from PIL import Image
        from aura_bio.study.visual.assets import crop_bytes
        from aura_bio.study.visual.schema import NormalizedBox
        image=Image.new('RGB',(3000,1000),'white');image.paste('black',(2000,0,3000,1000))
        stream=io.BytesIO();image.save(stream,format='PNG')
        raw=crop_bytes(stream.getvalue(),NormalizedBox(2/3,0,1,1),max_pixels=1000000)
        with Image.open(io.BytesIO(raw)) as crop:
            self.assertEqual(crop.size,(1000,1000))
            self.assertEqual(crop.getpixel((500,500)),(0,0,0))

    def test_rotated_region_roundtrips_through_original_transform(self):
        self.module()
        from aura_bio.study.visual.schema import SourceTransform
        transform=SourceTransform(600,800,800,600,90)
        original=(60,80,300,400)
        displayed=transform.to_display(original)
        for got,want in zip(transform.to_original(displayed),original): self.assertAlmostEqual(got,want)

    def test_native_table_row_keeps_headers_and_does_not_invent_panel_geometry(self):
        api=self.module()
        self.assertTrue(hasattr(api,'table_regions'),'Native table row geometry is not connected.')
        figure=figure_input().candidate
        class Row:
            def __init__(self,cells): self.cells=cells
        class Table:
            rows=[Row([(0,0,50,20),(50,0,100,20)]),Row([(0,20,50,40),(50,20,100,40)])]
            def extract(self): return [['Plant','Origin'],['Alternanthera','South America']]
        data=api.table_regions([Table()],(0,0,100,100),figure)
        selected=api.select_focus('Where is Alternanthera from?',figure,data)
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0].bbox.y0,0)
        self.assertEqual(selected[0].bbox.y1,.4)
        self.assertEqual(selected[0].precision,'table_row')
        self.assertEqual(api.select_focus('Explain panel D',figure,data),())
