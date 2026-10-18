import json
import tempfile
import unittest
from pathlib import Path

from tools import common_autonomy as ca


class Autonomy(unittest.TestCase):
    def make(self, verdicts, cat="thanks"):
        d = tempfile.mkdtemp()
        c = Path(d) / "common"
        (c / "drafts").mkdir(parents=True)
        drafts = [{"id": f"m{i}", "category": cat} for i in range(len(verdicts))]
        (c / "drafts" / "20260101T000000Z.json").write_text(json.dumps({"drafts": drafts}))
        (c / "experience.jsonl").write_text("\n".join(json.dumps(
            {"verdict": v, "draft_file": "20260101T000000Z.json", "message_id": f"m{i}"}) for i, v in enumerate(verdicts)))
        return d

    def test_not_eligible_before_enough_cases(self):
        card = ca.scorecard(self.make(["approved"] * 5))
        self.assertFalse(card["thanks"]["eligible"])

    def test_eligible_needs_rate_and_no_recent_reject(self):
        self.assertTrue(ca.scorecard(self.make(["approved"] * 20))["thanks"]["eligible"])
        self.assertFalse(ca.scorecard(self.make(["approved"] * 19 + ["rejected"]))["thanks"]["eligible"])
        self.assertFalse(ca.scorecard(self.make(["approved"] * 17 + ["rewritten"] * 3))["thanks"]["eligible"])

    def test_eligible_is_not_enabled_without_andrea(self):
        card = ca.scorecard(self.make(["approved"] * 25))
        self.assertTrue(card["thanks"]["eligible"])
        self.assertFalse(card["thanks"]["enabled"])
        self.assertFalse(ca.would_autopost({"category": "thanks", "status": "ready", "issues": []}, card))

    def test_commitments_never(self):
        card = ca.scorecard(self.make(["approved"] * 30, cat="commitment"))
        self.assertFalse(card["commitment"]["eligible"])


if __name__ == "__main__":
    unittest.main()
