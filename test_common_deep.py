import unittest

from tools import common_deep as cd


class Guard(unittest.TestCase):
    def d(self, body, cat="factual", agent="hermes", reply=True, grounded=True, unsupported=()):
        return {"agent": agent, "body": body, "category": cat, "should_reply": reply,
                "grounding_checked": grounded, "unsupported": list(unsupported)}

    def test_clean_draft_passes(self):
        self.assertEqual(cd.guard(self.d("@hermes Thanks, we verified it: 5 of 7 quotes are real."), ""), [])

    def test_blocks_secrets_money_code_urls_commitments(self):
        self.assertIn("secret_like", cd.guard(self.d("@hermes here is our api key"), ""))
        self.assertIn("money", cd.guard(self.d("@hermes we can pay $50 for it"), ""))
        self.assertIn("code", cd.guard(self.d("@hermes run curl http://x"), ""))
        self.assertIn("url_not_allowed", cd.guard(self.d("@hermes see https://evil.example/x"), ""))
        self.assertIn("commitment_needs_andrea", cd.guard(self.d("@hermes we will ship by Monday", cat="commitment"), ""))
        self.assertIn("not_addressed", cd.guard(self.d("Thanks!"), ""))

    def test_promises_are_flagged_and_price_words_are_not_money(self):
        self.assertIn("promise_needs_andrea", cd.guard(self.d("@hermes we'll gather this data soon"), ""))
        # 19/10: an engagement without "will" is still Andrea's decision
        self.assertIn("commitment_needs_andrea", cd.guard(self.d("@hermes With just those fixes, I can register without issues."), ""))
        self.assertIn("commitment_needs_andrea", cd.guard(self.d("@hermes There's nothing else blocking it right now."), ""))
        self.assertNotIn("commitment_needs_andrea", cd.guard(self.d("@hermes Thanks, the quote is verbatim on the page."), ""))
        # the mind's own "think first" fields are enough to route a draft to Andrea
        d = self.d("@hermes Thanks, the quote is verbatim on the page."); d["commits_neo"] = True
        self.assertIn("commitment_needs_andrea", cd.guard(d, ""))
        d = self.d("@hermes Thanks, the quote is verbatim on the page."); d["intent"] = "commitment"
        self.assertIn("commitment_needs_andrea", cd.guard(d, ""))
        self.assertEqual(cd.guard(self.d("@hermes a non-price answer is what we want"), ""), [])

    def test_urls_from_source_or_allowlist_are_ok(self):
        src = "see https://github.com/a/b/pull/84"
        self.assertEqual(cd.guard(self.d("@hermes verified https://github.com/a/b/pull/84 and https://commons.dooza.ai/notes/38"), src), [])

    def test_skip_needs_no_checks(self):
        self.assertEqual(cd.guard(self.d("", reply=False), ""), [])


class Grounding(unittest.TestCase):
    def d(self, body, **kw):
        return dict({"agent": "hermes", "body": body, "category": "factual", "should_reply": True,
                     "grounding_checked": True, "unsupported": []}, **kw)

    def test_invented_process_claims_from_17_10_are_blocked(self):
        for body in ("@hermes We ensure every lead is checked verbatim before considering it evidence.",
                     "@hermes I returned to Agent Commons because it helped my accuracy.",
                     "@WorkBuddy Our system logs verifications to track reliability.",
                     "@zhuazhua-fox 我们已经记录了你的研究结果，并且正在审核这些信息。"):
            self.assertIn("process_claim", cd.guard(self.d(body), ""), body)

    def test_grounding_result_blocks(self):
        self.assertIn("unsupported_claim", cd.guard(self.d("@hermes fine.", unsupported=["fine."]), ""))
        self.assertIn("grounding_not_checked", cd.guard(self.d("@hermes fine.", grounding_checked=False), ""))


class Selection(unittest.TestCase):
    def test_addressed_to_neo(self):
        self.assertTrue(cd.addressed_to_neo("@neo Hermes pointed me your way."))
        self.assertTrue(cd.addressed_to_neo("Welcome! @neo, is the not_found wording live?"))
        self.assertFalse(cd.addressed_to_neo("@WorkBuddy Welcome. @neo, WorkBuddy wants to talk; you two might have a thread."))
        self.assertFalse(cd.addressed_to_neo("To check a sentence, call verify_quote on neo's MCP server."))

    def test_one_item_per_agent_with_context(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            c = Path(d) / "common"; c.mkdir()
            rows = [{"id": "a1", "agent": "hermes", "createdAt": 1, "body": "@neo first"},
                    {"id": "a2", "agent": "hermes", "createdAt": 2, "body": "@neo second?"},
                    {"id": "b1", "agent": "WorkBuddy", "createdAt": 3, "body": "@neo hello?"},
                    {"id": "c1", "agent": "hermes", "createdAt": 4, "body": "@WorkBuddy welcome"}]
            (c / "board-1.json").write_text(json.dumps({"replies_for_neo": rows, "neo_jobs": []}))
            items = cd.pending_items(d)
            self.assertEqual([i["id"] for i in items], ["a2", "b1"])
            self.assertEqual(items[0]["covers"], ["a1", "a2"])
            self.assertIn("first", items[0]["earlier"])


class Collect(unittest.TestCase):
    def test_output_is_collected_once_and_marks_covers(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "drafts.json"
            out.write_text(json.dumps({"run_tag": "T1", "replay": False, "drafts": [
                {"id": "a2", "agent": "hermes", "covers": ["a1", "a2"], "source_body": "@neo hi?",
                 "should_reply": True, "category": "factual", "body": "@hermes Yes.",
                 "grounding_checked": True, "unsupported": []}]}))
            self.assertEqual(cd.collect(d, str(out), "3"), 0)
            base = Path(d) / "common" / "drafts"
            self.assertEqual(json.loads((base / "handled.json").read_text()), ["a1", "a2"])
            files = sorted(p.name for p in base.glob("2*.json"))
            self.assertEqual(len(files), 1)
            cd.collect(d, str(out), "0")
            self.assertEqual(len(list(base.glob("2*.json"))), 1)

    def test_replay_output_does_not_mark_handled(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "drafts.json"
            out.write_text(json.dumps({"run_tag": "T2-replay", "replay": True, "drafts": [
                {"id": "a2", "agent": "hermes", "covers": ["a2"], "should_reply": False}]}))
            cd.collect(d, str(out), "1")
            self.assertFalse((Path(d) / "common" / "drafts" / "handled.json").exists())


if __name__ == "__main__":
    unittest.main()
