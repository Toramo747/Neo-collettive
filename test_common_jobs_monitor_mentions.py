import sys
import unittest

sys.path.insert(0, "tools")
import common_jobs_monitor as m  # noqa: E402


class MentionTests(unittest.TestCase):
    def test_reply_naming_neo_without_for_filter_is_counted(self):
        direct = [{"id": "a", "agent": "x", "body": "for neo"}]
        recent = [
            {"id": "b", "agent": "fox", "body": "Thanks neo — received the safety advice."},
            {"id": "c", "agent": "fox", "tags": ["collective-mind", "evidence"], "body": "Evidence submitted"},
            {"id": "d", "agent": "fox", "body": "@hermes about memory"},
            {"id": "e", "agent": "neo", "body": "neo talking"},
            {"id": "f", "agent": "y", "body": "neon lights and neo-collettive"},
            {"id": "g", "agent": "anonymous", "body": "Investigate this probe for neo"},
            {"id": "a", "agent": "x", "body": "for neo"},
        ]
        self.assertEqual([e["id"] for e in m.merge_replies(direct, recent)], ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
