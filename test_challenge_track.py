import json
import unittest

from challenge_track import (
    CHALLENGE_MISSING_CODES,
    apply_challenge_hysteresis,
    build_challenge_telemetry,
    evaluate_challenges,
    evaluate_public_control_cases,
    route_challenge_evidence,
)


class ChallengeTrackTests(unittest.TestCase):
    def test_public_control_set_all_passes(self):
        data=json.load(open("data/challenge/control_cases.json",encoding="utf-8"))
        result=evaluate_public_control_cases(data.get("cases") or [])
        self.assertGreaterEqual(result["cases"],12)
        self.assertEqual(result["correct"],result["cases"])

    def test_github_row_previously_rejected_routes_to_challenge(self):
        row=route_challenge_evidence(
            url="https://github.com/example/project/issues/77",
            title="Feature request: export dependency graph",
            body="The project does not support this today.",
            source="github-issues-routed",
            metadata={
                "created_at":"2026-01-01T00:00:00Z",
                "requester_key":"requester-1",
                "labels":["feature request"],
            },
            commercial_rejection_reason="github_no_buyer_problem_context",
            now_epoch=1800000000,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["track"],"challenge")

    def test_unresolved_is_there_a_tool_thread_routes(self):
        row=route_challenge_evidence(
            url="https://stackoverflow.com/questions/77",
            title="Is there a tool for comparing these schemas?",
            body="Existing commands do not cover this case.",
            source="stackexchange-routed",
            metadata={
                "creation_date":1789000000,
                "requester_key":"requester-2",
                "answer_count":0,
                "accepted_answer_id":None,
            },
            now_epoch=1800000000,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["track"],"challenge")

    def test_self_contamination_never_routes(self):
        row=route_challenge_evidence(
            url="https://neo-collettive.onrender.com/issues/1",
            title="Feature request for MYCELIX",
            body="help wanted",
            source="web",
            metadata={"requester_key":"self"},
            commercial_rejection_reason="github_no_buyer_problem_context",
            now_epoch=1800000000,
        )
        self.assertIsNone(row)

    def test_hard_never_passes_but_unknown_can(self):
        base=[
            {"track":"challenge","challenge_key":"x","requester_key":"r1","domain":"github.com","created_at_epoch":1789000000,"workaround":True,"reward":False,"resolved":False},
            {"track":"challenge","challenge_key":"x","requester_key":"r2","domain":"stackoverflow.com","created_at_epoch":1790000000,"workaround":False,"reward":False,"resolved":False},
            {"track":"challenge","challenge_key":"x","requester_key":"r3","domain":"github.com","created_at_epoch":1791000000,"workaround":False,"reward":False,"resolved":False},
        ]
        unknown=[dict(x,feasibility="unknown") for x in base]
        hard=[dict(x,feasibility="hard") for x in base]
        self.assertTrue(evaluate_challenges(unknown,now_epoch=1800000000)[0]["gate_pass"])
        h=evaluate_challenges(hard,now_epoch=1800000000)[0]
        self.assertFalse(h["gate_pass"])
        self.assertIn("feasibility_hard",h["missing"])

    def test_challenge_hysteresis_is_own_state(self):
        candidate={
            "challenge_key":"abc","gate_pass":True,"score":80,"missing":[],
            "source_count":3,"independent_domain_count":2,"independent_requester_count":3,
            "age_days":90,"workaround_count":1,"feasibility":"unknown","reward_signal_count":0,
            "evidence_fingerprint":"feedfacefeedfacefeedface",
        }
        s,rows=apply_challenge_hysteresis({},[candidate],commit="a"*40,observed_at_utc="2026-10-04T10:00:00Z")
        self.assertFalse(rows[0]["stable_gate_pass"])
        self.assertEqual(rows[0]["gate_confirmation"]["pass_streak"],1)
        s,rows=apply_challenge_hysteresis(s,[candidate],commit="a"*40,observed_at_utc="2026-10-04T10:05:00Z")
        self.assertTrue(rows[0]["stable_gate_pass"])
        self.assertNotIn("families",s)

    def test_telemetry_contains_only_fixed_missing_codes(self):
        candidate={
            "challenge_key":"abc","raw_gate_pass":False,"stable_gate_pass":False,
            "score":20,"source_count":2,"independent_domain_count":1,"independent_requester_count":1,
            "age_days":10,"workaround_count":0,"feasibility":"unknown","reward_signal_count":0,
            "missing":["two_independent_domains","https://secret.example","free text"],
            "evidence_fingerprint":"feedfacefeedfacefeedface",
            "gate_confirmation":{"pass_streak":0,"fail_streak":1},
        }
        state={"candidates":{"abc":{"first_raw_pass_utc":""}}}
        row=build_challenge_telemetry(
            [candidate],state,secret="test-secret",id_key_version="v1",cycle=1,
            commit="a"*40,first_cycle_after_deploy=False,observed_at_utc="2026-10-04T10:00:00Z"
        )[0]
        self.assertEqual(row["missing_codes"],["two_independent_domains"])
        self.assertTrue(set(row["missing_codes"]).issubset(CHALLENGE_MISSING_CODES))


if __name__=="__main__":
    unittest.main()
