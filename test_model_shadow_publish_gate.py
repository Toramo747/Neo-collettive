import unittest

from tools.model_shadow_publish_gate import publishable


class ModelShadowPublishGateTests(unittest.TestCase):
    def setUp(self):
        self.metrics = {
            "mode": "shadow",
            "batch_complete": True,
            "batch_idle": False,
            "student_available": True,
            "promotion_eligible": True,
            "student_not_worse_public": True,
            "student_not_worse_hidden": True,
            "promotion_requires_manual_approval": True,
        }
        self.student = {
            "schema_v": 1,
            "mode": "shadow",
            "trained": True,
            "weights_f32_b64": "bounded-weights",
            "artifact_sha256": "digest",
        }

    def test_publish_when_public_and_hidden_shadow_gates_pass(self):
        self.assertTrue(publishable(self.metrics, self.student))

    def test_incomplete_batch_cannot_publish(self):
        metrics = dict(self.metrics, batch_complete=False)
        self.assertFalse(publishable(metrics, self.student))

    def test_idle_replay_cannot_publish(self):
        metrics = dict(self.metrics, batch_idle=True)
        self.assertFalse(publishable(metrics, self.student))

    def test_public_regression_blocks_publish(self):
        metrics = dict(self.metrics, student_not_worse_public=False, promotion_eligible=False)
        self.assertFalse(publishable(metrics, self.student))

    def test_hidden_regression_blocks_publish(self):
        metrics = dict(self.metrics, student_not_worse_hidden=False, promotion_eligible=False)
        self.assertFalse(publishable(metrics, self.student))

    def test_missing_manual_production_gate_blocks_publish(self):
        metrics = dict(self.metrics, promotion_requires_manual_approval=False)
        self.assertFalse(publishable(metrics, self.student))

    def test_non_shadow_or_untrained_artifact_blocks_publish(self):
        student = dict(self.student, mode="production")
        self.assertFalse(publishable(self.metrics, student))
        student = dict(self.student, trained=False)
        self.assertFalse(publishable(self.metrics, student))

    def test_missing_student_artifact_blocks_publish(self):
        self.assertFalse(publishable(self.metrics, {}))


if __name__ == "__main__":
    unittest.main()
