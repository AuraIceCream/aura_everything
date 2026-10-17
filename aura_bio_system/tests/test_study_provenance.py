import unittest
from dataclasses import asdict

from aura_bio.study.schema import Unit, Locator, unit_from_dict, StudyError
from aura_bio.study.provenance import SourceMethod


class ProvenanceTests(unittest.TestCase):
    def test_four_provenance_values_roundtrip(self):
        self.assertEqual({m.value for m in SourceMethod}, {'native_text', 'ocr', 'vlm', 'user_annotation'})
        for method in SourceMethod:
            unit = Unit('a'*32, 'b'*32, 0, 'body', 'T', '', 'text', (Locator('pdf', page=1),), provenance=method.value)
            self.assertEqual(unit_from_dict(asdict(unit)).provenance, method.value)
        with self.assertRaises(ValueError):
            SourceMethod('verified_vision')

    def test_legacy_native_units_load_without_derived_promotion(self):
        data = asdict(Unit('a'*32, 'b'*32, 0, 'body', '', '', 'text', (Locator('pdf', page=1),)))
        data.pop('provenance', None)
        data.pop('provenance_details', None)
        self.assertEqual(unit_from_dict(data).provenance, 'native_text')
        data['role'] = 'figure_description'
        with self.assertRaises(StudyError):
            unit_from_dict(data)
