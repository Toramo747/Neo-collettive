import json
import tempfile
import unittest
from pathlib import Path

from tools import common_experience as ce


class Experience(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        c = Path(self.d) / "common"
        (c / "drafts").mkdir(parents=True)
        (c / "board-1.json").write_text(json.dumps({"replies_for_neo": [{"id": "m1", "agent": "hermes", "body": "@neo live?"}]}))
        (c / "drafts" / "20200101T000000Z.json").write_text(json.dumps({"drafts": [
            {"id": "m1", "agent": "hermes", "should_reply": True, "body": "@hermes We ensure everything.", "issues": []},
            {"id": "m2", "agent": "hermes", "should_reply": True, "body": "@hermes Nice.", "issues": []}]}))

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        return [json.loads(l) for l in (Path(self.d) / ce.LOG).read_text().splitlines()]

    def test_posted_pairs_draft_with_target_and_is_idempotent(self):
        reply = Path(self.d) / "r.json"
        reply.write_text(json.dumps({"reply_to": "m1", "body": "@hermes Yes, it is live since this morning."}))
        ce.posted(self.d, str(reply))
        ce.posted(self.d, str(reply))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "rewritten")
        self.assertEqual(rows[0]["source_body"], "@neo live?")
        self.assertIn("since this morning", rows[0]["target_body"])

    def test_reject_skips_drafts_already_judged_and_sweep_marks_rest(self):
        reply = Path(self.d) / "r.json"
        reply.write_text(json.dumps({"reply_to": "m1", "body": "@hermes Yes."}))
        ce.posted(self.d, str(reply))
        ce.reject(self.d, "20200101T000000Z.json", "bad run")
        self.assertEqual([r["verdict"] for r in self.rows()], ["rewritten", "rejected"])
        ce.sweep(self.d, "48")
        self.assertEqual(len(self.rows()), 2)  # nothing left unjudged


if __name__ == "__main__":
    unittest.main()
