import unittest

from runtime_boundary import (
    EXPECTED_PROFILE_ID,
    is_control_plane_text,
    load_runtime_profile,
    sanitize_commercial_state,
    state_profile_status,
)


class RuntimeBoundaryTests(unittest.TestCase):
    def test_canonical_profile_is_locked_to_main_production(self):
        profile=load_runtime_profile()
        self.assertEqual(profile["profile_id"],EXPECTED_PROFILE_ID)
        self.assertEqual(profile["deployment_role"],"production")
        self.assertEqual(profile["branch"],"main")
        self.assertTrue(profile["commercial_gate"]["unchanged"])
        self.assertFalse(profile["tracks"]["agent_network"]["may_write_commercial_evidence"])
        self.assertFalse(profile["tracks"]["trust_lab"]["may_write_commercial_evidence"])
        self.assertFalse(profile["tracks"]["trust_lab"]["may_change_commercial_gate"])
        self.assertTrue(profile["config_fingerprint"])

    def test_explicit_foreign_state_profile_is_rejected(self):
        status=state_profile_status({"runtime_profile":{"profile_id":"mycelix-dev"}})
        self.assertFalse(status["compatible"])
        self.assertEqual(status["status"],"profile_mismatch")

    def test_legacy_untagged_state_is_migration_compatible(self):
        status=state_profile_status({"cycles_completed":151})
        self.assertTrue(status["compatible"])
        self.assertEqual(status["status"],"legacy_untagged")

    def test_current_control_plane_false_positive_is_detected(self):
        text="Historical terminal vocabulary retained for chronology only: G4_PASS G4_AMEND manual CI rerun while exact-head CI is already in flight."
        self.assertTrue(is_control_plane_text(text))

    def test_real_devops_pain_is_not_blocked(self):
        text="Our deployments are manually repeated across environments, take hours per week, and are error-prone."
        self.assertFalse(is_control_plane_text(text))

    def test_contaminated_active_thesis_is_invalidated_not_promoted(self):
        payload={
            "active_thesis":{
                "problem_id":"spreadsheet_process:agencies:devops",
                "pain":"Historical terminal vocabulary: G4_PASS G4_AMEND and manual CI rerun.",
                "source_url":"https://example.com/issue",
            },
            "thesis_history":[],
        }
        cleaned,event=sanitize_commercial_state(payload)
        self.assertIsNone(cleaned["active_thesis"])
        self.assertEqual(cleaned["thesis_history"][-1]["status"],"REJECTED_CONTROL_PLANE_CONTAMINATION")
        self.assertEqual(event["reason"],"ci_control_plane_text_not_commercial_pain")


if __name__=="__main__":
    unittest.main()
