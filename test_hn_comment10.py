import asyncio
import unittest
from unittest import mock

import cloud_mcp


class HnComment10Tests(unittest.TestCase):
    def test_comment_mode_requests_ten_comments_and_links_each_comment(self):
        seen = {}

        async def fake_get_json(url, params):
            seen.update(params)
            return {"hits": [
                {"objectID": "101", "story_id": "9", "author": "a", "comment_text": "I need a tool", "created_at_i": 1},
                {"objectID": "102", "story_id": "9", "author": "b", "comment_text": "same here", "created_at_i": 2},
            ]}

        with mock.patch.object(cloud_mcp, "HN_RETRIEVAL_MODE", "comment10"), \
             mock.patch.object(cloud_mcp, "get_json", fake_get_json), \
             mock.patch.object(cloud_mcp, "natural_search_seed", lambda q, m: q):
            rows = asyncio.run(cloud_mcp._hn_query_search("invoice tool", 3))
        self.assertEqual(seen["tags"], "comment")
        self.assertEqual(seen["hitsPerPage"], 10)
        self.assertEqual({r["url"] for r in rows}, {"https://news.ycombinator.com/item?id=101",
                                                   "https://news.ycombinator.com/item?id=102"})

    def test_story_mode_is_the_old_behaviour(self):
        seen = {}

        async def fake_get_json(url, params):
            seen.update(params)
            return {"hits": []}

        with mock.patch.object(cloud_mcp, "HN_RETRIEVAL_MODE", "story"), \
             mock.patch.object(cloud_mcp, "get_json", fake_get_json), \
             mock.patch.object(cloud_mcp, "natural_search_seed", lambda q, m: q):
            asyncio.run(cloud_mcp._hn_query_search("invoice tool", 3))
        self.assertEqual(seen["tags"], "story")
        self.assertEqual(seen["hitsPerPage"], 3)


if __name__ == "__main__":
    unittest.main()
