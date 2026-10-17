import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aura_bio.study.visual.ollama import gpu_free_mb


@unittest.skipUnless(os.name == 'nt', 'Windows GPU-engine counters')
class GpuIdleDetectionTests(unittest.TestCase):
    def sample(self, engines, *, counter_status=0):
        results = [SimpleNamespace(returncode=0, stdout='3687, 4096, 16\n'),
                   SimpleNamespace(returncode=counter_status, stdout=json.dumps(engines))]
        with patch('aura_bio.study.visual.ollama.subprocess.run', side_effect=results):
            return gpu_free_mb()

    def test_desktop_copy_activity_is_not_compute_busy(self):
        actual = self.sample([{'name':'pid_42_phys_0_eng_3_engtype_Copy', 'value':16},
                              {'name':'pid_42_phys_0_eng_0_engtype_3D', 'value':0}])
        self.assertEqual(actual, (3687.0, 4096.0, 0.0))

    def test_compute_and_3d_work_remain_busy(self):
        actual = self.sample([{'name':'pid_42_phys_0_eng_1_engtype_Compute_0', 'value':70},
                              {'name':'pid_43_phys_0_eng_0_engtype_3D', 'value':12}])
        self.assertEqual(actual[2], 82)

    def test_counter_failure_preserves_conservative_nvidia_reading(self):
        self.assertEqual(self.sample([], counter_status=1), (3687.0, 4096.0, 16.0))

    def test_invalid_counter_values_cannot_hide_activity(self):
        self.assertEqual(self.sample([{'name':'engtype_Compute_0','value':float('nan')}])[2], 16)


if __name__ == '__main__':
    unittest.main()
