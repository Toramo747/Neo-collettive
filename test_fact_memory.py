import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
from fact_cards import drop_told, told_tokens  # noqa: E402
from fact_mind import check_sentence  # noqa: E402

LINK = "https://archive.softwareheritage.org/swh:1:cnt:6d67805d38f45454f9044f7ff0fb0023d5ae81cd"
TOLD = [{"post": "post_neo-re-x", "date": "20261022", "text": f"@skitter receipt_log.py is archived: {LINK}."}]


class FactMemoryTest(unittest.TestCase):
    def test_card_with_only_told_links_is_dropped(self):
        cards = [{"text": f"receipt_log.py is archived too: {LINK}.", "source": "post_neo-re-y"},
                 {"text": "Each entry is chained to the previous one by its hash.", "source": "post_neo-re-y"},
                 {"text": f"verify_quote: {LINK} is verbatim.", "source": "tool:verify_quote(live)"}]
        kept = [c["text"] for c in drop_told(cards, TOLD)]
        self.assertEqual(len(kept), 2)
        self.assertNotIn(cards[0]["text"], kept)

    def test_new_link_is_kept(self):
        cards = [{"text": "The log is at https://example.org/new and was archived today.", "source": "post_neo-re-y"}]
        self.assertEqual(len(drop_told(cards, TOLD)), 1)

    def test_job_text_only_on_its_job(self):
        cards = [{"text": "Please recompute the chain yourself and post one line.", "source": "post_neo-job-witness-20261023"}]
        self.assertEqual(drop_told(cards, []), [])
        self.assertEqual(len(drop_told(cards, [], on_job="post_neo-job-witness-20261023")), 1)

    def test_sentence_repeating_a_told_link_is_flagged(self):
        cards = {"F1": f"receipt_log.py is archived too: {LINK}."}
        s = {"text": f"receipt_log.py is archived too: {LINK}.", "cites": ["F1"]}
        self.assertIn("already_told", check_sentence(s, cards, "", told_tokens(TOLD)))
        self.assertNotIn("already_told", check_sentence(s, cards, ""))


if __name__ == "__main__":
    unittest.main()
