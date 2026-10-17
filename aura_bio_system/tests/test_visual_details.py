import json
import unittest
from test_figure_description import FIELDS


def details():
    return {**FIELDS,'version':2,'panels':[{'id':'D','label':'D','bbox':None,
        'observations':[{'property':'organism','value':'Mouse','origin':'vlm'}],'uncertainties':[]}],
        'tables':[]}


class VisualDetailsTests(unittest.TestCase):
    def module(self):
        try: from aura_bio.study.visual import details as api
        except ImportError: self.fail('Versioned panel/table descriptions are not implemented.')
        return api

    def test_caption_and_pixels_disagree_without_provenance_promotion(self):
        api=self.module(); value=api.validate_details(json.dumps(details()))
        observations=api.caption_observations('Panels D-E show Naked mole-rat.',unit_id='u1')
        conflicts=api.detail_conflicts(value,observations)
        self.assertEqual(value['panels'][0]['observations'][0]['origin'],'vlm')
        self.assertEqual(observations[0]['origin'],'native_text')
        self.assertEqual(conflicts[0]['panel_id'],'D')

    def test_table_cells_keep_row_header_identity(self):
        api=self.module(); value=details()
        value['tables']=[{'id':'t1','headers':[{'id':'h1','label':'Origin'}],
            'rows':[{'id':'r1','label':'Plant A'},{'id':'r2','label':'Plant B'}],
            'cells':[{'row_id':'r1','header_id':'h1','value':'South America','status':'stated','bbox':None,'origin':'vlm'}]}]
        parsed=api.validate_details(json.dumps(value))
        self.assertEqual(parsed['tables'][0]['cells'][0]['row_id'],'r1')
        value['tables'][0]['cells'][0]['header_id']='foreign'
        with self.assertRaises(ValueError): api.validate_details(json.dumps(value))

    def test_missing_cell_is_not_zero(self):
        api=self.module(); value=details()
        value['tables']=[{'id':'t1','headers':[{'id':'h','label':'Count'}],'rows':[{'id':'r','label':'A'}],
            'cells':[{'row_id':'r','header_id':'h','value':None,'status':'missing','bbox':None,'origin':'vlm'}]}]
        self.assertIsNone(api.validate_details(json.dumps(value))['tables'][0]['cells'][0]['value'])
        value['tables'][0]['cells'][0]['value']='0'
        with self.assertRaises(ValueError): api.validate_details(json.dumps(value))

    def test_panel_conflicts_reported(self):
        api=self.module(); value=details()
        value['panels'][0]['observations'].append({'property':'organism','value':'Naked mole-rat','origin':'vlm'})
        self.assertTrue(api.detail_conflicts(api.validate_details(json.dumps(value))))

    def test_model_cannot_declare_native_support_or_trusted_geometry(self):
        api=self.module(); value=details()
        value['panels'][0]['observations'][0]['origin']='native_text'
        with self.assertRaises(ValueError): api.validate_details(json.dumps(value))

    def test_repair_cannot_add_identity_even_if_other_fields_missing(self):
        api=self.module(); prior=details(); prior.pop('axes')
        changed=details(); changed['panels'][0]['id']='Invented'
        with self.assertRaises(ValueError): api.validate_details(json.dumps(changed),repair=json.dumps(prior))

    def test_v1_description_archive_still_readable(self):
        api=self.module()
        from aura_bio.study.visual.description import validate_description
        self.assertEqual(validate_description(json.dumps(FIELDS)),FIELDS)
        from aura_bio.study.visual.schema import VisualJobConfig
        from aura_bio.study.visual.description import FigureDescriber
        from test_figure_description import Backend,figure_input
        from dataclasses import replace
        input=replace(figure_input(),config=VisualJobConfig(description_version=2))
        result=FigureDescriber(Backend([json.dumps(details())])).describe(input)
        self.assertEqual(result.fields['version'],2)

    def test_caption_mapping_needs_explicit_relation_not_proximity(self):
        api=self.module()
        self.assertEqual(api.caption_observations('Naked mole-rat. A B C. Mouse. D E.',unit_id='u1'),())

    def test_caption_subject_is_not_blindly_classified_as_an_organism(self):
        obs=self.module().caption_observations('Panels A show cell counts.',unit_id='u1')
        self.assertEqual(obs[0]['property'],'subject')

    def test_caption_offsets_are_bound_to_the_parent_text_when_available(self):
        caption='Panels D show Naked mole-rat.';source='Introductory text. '+caption
        try: obs=self.module().caption_observations(caption,unit_id='u1',source_text=source)
        except TypeError: self.fail('Caption offsets are not connected to the actual parent text.')
        self.assertEqual(source[obs[0]['start']:obs[0]['end']],'Naked mole-rat')
        self.assertEqual(obs[0]['coordinate_basis'],'source_unit')

    def test_structural_repair_cannot_rewrite_an_already_readable_observation(self):
        api=self.module();prior=details();prior.pop('axes')
        changed=details();changed['panels'][0]['observations'][0]['value']='Whale'
        with self.assertRaises(ValueError): api.validate_details(json.dumps(changed),repair=json.dumps(prior))

    def test_failed_v2_repair_retains_provider_diagnostics(self):
        self.module()
        from test_figure_description import Backend,figure_input
        from aura_bio.study.visual.schema import VisualJobConfig
        from aura_bio.study.visual.description import FigureDescriber
        from aura_bio.study.schema import StudyError
        from dataclasses import replace
        input=replace(figure_input(),config=VisualJobConfig(description_version=2))
        with self.assertRaises(StudyError) as error:
            FigureDescriber(Backend(['bad','still bad'])).describe(input)
        self.assertEqual(error.exception.code,'invalid_description')
        self.assertEqual(len(error.exception.responses),2)
