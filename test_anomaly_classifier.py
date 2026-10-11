# SPDX-License-Identifier: BUSL-1.1
import tempfile
import unittest
from pathlib import Path

import anomaly_classifier as ac


class AnomalyClassifierTests(unittest.TestCase):
    def test_mask_hides_topic_names_and_numbers(self):
        m = ac.mask("The Hubble tension at 5.0 sigma and the BICEP2 B-modes; muon g-2 anomaly persists")
        for word in ("hubble", "bicep", "g-2", "5.0", "tension", "anomaly"):
            self.assertNotIn(word, m)
        self.assertIn("persists", m)
        self.assertIn("topicterm", m)

    def test_missing_model_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ac.load(Path(d) / "absent.joblib"))
        self.assertEqual(ac.predict(None, ["x"]), [])


if __name__ == "__main__":
    unittest.main()
