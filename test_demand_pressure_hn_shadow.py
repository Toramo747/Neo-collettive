import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path("experiments/demand-pressure/hn_shadow.py")
spec = importlib.util.spec_from_file_location("oxibay_ipd_hn", PATH)
hn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hn)

NOW = 1_800_000_000
KEY = b"x" * 32


def hit(i, when=NOW-86400, text="I need help with my restaurant booking workflow because manual tasks waste time."):
    return {"objectID": str(i), "story_id": str(i), "created_at_i": when,
            "title": "Restaurant booking needs help", "comment_text": text,
            "author": "p" + str(i)}


class IPDHNShadowTests(unittest.TestCase):
    def test_offline_plan_has_bounded_non_overlapping_windows(self):
        p = hn.plan(NOW)
        self.assertEqual(len(p), 16)
        self.assertEqual({x["topic"] for x in p}, {x[0] for x in hn.TOPICS})
        self.assertEqual(p[0]["end"], NOW)
        self.assertEqual(p[0]["start"], p[1]["end"])
        self.assertEqual(p[1]["start"], p[2]["end"])

    def test_real_format_is_screened_and_one_thread_one_request(self):
        a = hit(1)
        b = {**hit(2), "story_id": "1"}
        result = hn.convert([a, b], key=KEY, topic="restaurant booking")
        score = hn.demand_pressure_index(result, now_epoch=NOW)
        self.assertEqual(score["unique_request_threads"], 1)
        self.assertEqual(score["verified_requester_tokens"], 0)
        self.assertEqual(score["evidence_status"], "TOO_FEW_THREADS")

    def test_vendor_marketing_and_ambiguous_are_not_demand(self):
        rows = [hit(1, text="We built our tool and we offer custom integrations."),
                hit(2, text="Our app sells bookkeeping automation services."),
                hit(3, text="Hello, I work as a developer."),
                hit(4, text="I need help with my restaurant booking workflow because it is manual.")]
        result = hn.convert(rows, key=KEY, topic="restaurant booking")
        self.assertLessEqual(len(result), 1)

    def test_provider_failure_fails_closed(self):
        p = hn.plan(NOW)
        batches = [{"ok": True, "hits": []} for _ in p]
        batches[0] = {"ok": False, "hits": []}
        result = hn.evaluate(p, batches, key=KEY, now_epoch=NOW)
        self.assertEqual(result["topics"][p[0]["topic"]]["status"], "INCONCLUSIVE_PROVIDER_FAILURE")
        self.assertFalse(result["production_state_write"])

    def test_truncated_source_cannot_claim_growth(self):
        p = hn.plan(NOW)
        batches = [{"ok": True, "hits": []} for _ in p]
        batches[0] = {"ok": True, "hits": [hit(i) for i in range(hn.HITS_PER_QUERY)]}
        result = hn.evaluate(p, batches, key=KEY, now_epoch=NOW)
        ipd = result["topics"][p[0]["topic"]]["ipd"]
        self.assertEqual(ipd["growth_status"], "SOURCE_TRUNCATED")
        self.assertEqual(ipd["components"]["growth"], 0)
        self.assertIsNone(ipd["growth_percent"])

    def test_aggregate_does_not_leak_source_objects(self):
        p = hn.plan(NOW)
        raw = hit(123, text="I need help with our manual restaurant booking. secret_phrase_xyz")
        batches = [{"ok": True, "hits": []} for _ in p]
        batches[0] = {"ok": True, "hits": [raw]}
        result = hn.evaluate(p, batches, key=KEY, now_epoch=NOW)
        serialized = json.dumps(result)
        self.assertNotIn("secret_phrase_xyz", serialized)
        self.assertNotIn("comment_text", serialized)
        self.assertNotIn("objectID", serialized)
        self.assertNotIn("actor_hmac", serialized)
        self.assertNotIn("request_id", serialized)
        self.assertNotIn("p123", serialized)
        self.assertEqual(result["verified_unique_human_buyers"], 0)

    def test_plan_mode_no_network(self):
        text = PATH.read_text()
        self.assertIn("elif not sys.argv[1:]", text)
        self.assertIn("no_deploy", text)
        self.assertNotIn("AUTOPILOT_STATE", text)
        self.assertNotIn("commercial_evidence_memory", text)
        self.assertNotIn("trigger_deploy(", text)


if __name__ == "__main__":
    unittest.main()
