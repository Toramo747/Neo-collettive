import asyncio
import base64
import hashlib
import json
import unittest
from unittest import mock

import httpx

import github_chunk_store as gcs


class FakeGitHub:
    """Minimal Git Data API: blobs, trees (with base_tree and deletions), commits, refs."""

    def __init__(self):
        self.blobs, self.trees, self.commits = {}, {}, {}
        self.ref = None
        self.ff_rejections = 0

    def _sha(self, obj) -> str:
        return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/repos/o/r/", 1)[1]
        body = json.loads(request.content or b"{}") if request.content else {}
        if request.method == "POST" and path == "git/blobs":
            sha = self._sha(body["content"])
            self.blobs[sha] = body["content"]
            return httpx.Response(201, json={"sha": sha})
        if request.method == "POST" and path == "git/trees":
            files = dict(self.trees.get(body.get("base_tree"), {}))
            for e in body["tree"]:
                if e["sha"] is None:
                    files.pop(e["path"], None)
                else:
                    files[e["path"]] = e["sha"]
            sha = self._sha(files)
            self.trees[sha] = files
            return httpx.Response(201, json={"sha": sha})
        if request.method == "POST" and path == "git/commits":
            sha = self._sha(body)
            self.commits[sha] = body
            return httpx.Response(201, json={"sha": sha})
        if request.method == "GET" and path.startswith("git/ref/heads/"):
            return httpx.Response(200 if self.ref else 404, json={"object": {"sha": self.ref}})
        if request.method == "PATCH" and path.startswith("git/refs/heads/"):
            new = body["sha"]
            if not body.get("force") and self.commits[new]["parents"] != [self.ref]:
                self.ff_rejections += 1
                return httpx.Response(422, json={})
            self.ref = new
            return httpx.Response(200, json={})
        if request.method == "GET" and path.startswith("git/commits/"):
            c = self.commits[path.rsplit("/", 1)[1]]
            return httpx.Response(200, json={"tree": {"sha": c["tree"]}})
        if request.method == "GET" and path.startswith("git/trees/"):
            if not self.ref:
                return httpx.Response(409, json={})
            files = self.trees[self.commits[self.ref]["tree"]]
            return httpx.Response(200, json={"tree": [{"path": p, "type": "blob", "sha": s} for p, s in files.items()]})
        if request.method == "GET" and path.startswith("git/blobs/"):
            content = self.blobs[path.rsplit("/", 1)[1]]
            return httpx.Response(200, json={"content": base64.b64encode(content.encode()).decode()})
        return httpx.Response(500)

    def seed(self):
        tree = self._sha({})
        self.trees[tree] = {}
        c = {"message": "init", "tree": tree, "parents": []}
        self.ref = self._sha(c)
        self.commits[self.ref] = c


class Store(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        self.gh.seed()
        transport = httpx.MockTransport(self.gh.handler)
        real_async, real_sync = httpx.AsyncClient, httpx.Client
        self.p1 = mock.patch.object(gcs.httpx, "AsyncClient", lambda **kw: real_async(transport=transport, **kw))
        self.p2 = mock.patch.object(gcs.httpx, "Client", lambda **kw: real_sync(transport=transport, **kw))
        self.p1.start(); self.p2.start()

    def tearDown(self):
        self.p1.stop(); self.p2.stop()

    def store(self):
        return gcs.GitHubChunkStore("o/r", "t")

    def test_write_then_fresh_reader_sees_values(self):
        s = self.store()
        self.assertTrue(asyncio.run(s.put_many({"NEO_CHALLENGE_TRACK_abc_0": "zz1", "NEO_CHALLENGE_TRACK_abc_1": "zz2"})))
        fresh = self.store()
        self.assertEqual(fresh.get("NEO_CHALLENGE_TRACK_abc_1"), "zz2")
        self.assertEqual(fresh.keys(), ["NEO_CHALLENGE_TRACK_abc_0", "NEO_CHALLENGE_TRACK_abc_1"])

    def test_delete_removes_from_tree(self):
        s = self.store()
        asyncio.run(s.put_many({"NEO_EVIDENCE_g_0": "a", "NEO_EVIDENCE_g_1": "b"}))
        self.assertTrue(asyncio.run(s.delete_many(["NEO_EVIDENCE_g_0"])))
        self.assertEqual(self.store().keys(), ["NEO_EVIDENCE_g_1"])

    def test_squash_keeps_tree_and_drops_parents(self):
        s = self.store()
        asyncio.run(s.put_many({"NEO_EVIDENCE_g_0": "a"}))
        self.assertTrue(asyncio.run(s.squash()))
        self.assertEqual(self.gh.commits[self.gh.ref]["parents"], [])
        self.assertEqual(self.store().get("NEO_EVIDENCE_g_0"), "a")

    def test_missing_key_is_none(self):
        self.assertIsNone(self.store().get("NEO_EVIDENCE_nope_0"))

    def test_disabled_without_config(self):
        with mock.patch.dict("os.environ", {"NEO_STATE_GITHUB_TOKEN": "", "NEO_STATE_GITHUB_REPO": ""}):
            self.assertIsNone(gcs.from_env())

    def test_chunk_key_filter(self):
        self.assertTrue(gcs.is_chunk_key("NEO_CHALLENGE_TRACK_x_0"))
        self.assertFalse(gcs.is_chunk_key("NEO_STATE_JSON"))


if __name__ == "__main__":
    unittest.main()
