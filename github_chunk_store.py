"""Chunk store for the big memory generations in a dedicated private GitHub repo.

Why: the evidence and challenge-track generations used to live as Render env
vars. On 15-17/10 failed writes left orphan chunks until the env hit 300 keys /
16 MB; deploys and checkpoints failed for three days. With this store only the
small state summary (NEO_STATE_JSON, ~56 KB) stays in Render.

Layout: one file per chunk key, ``chunks/<ENV_KEY>``, same values as before, so
references and decoding are unchanged. Every write or delete is ONE commit made
with the Git Data API (blobs -> tree -> commit -> ref). History is squashed into
a single parentless commit every ``SQUASH_EVERY`` commits (only the latest
state matters in this repo), so the repo does not grow without bound.

Config (both required): NEO_STATE_GITHUB_TOKEN (fine-grained, Contents read and
write on that one repo) and NEO_STATE_GITHUB_REPO ("owner/name"). Absent -> the
store is disabled and the service keeps using Render env vars as before.
Values and the token are never logged.
"""
from __future__ import annotations

import base64
import os
from typing import Any

import httpx

API = "https://api.github.com"
DIR = "chunks/"
SQUASH_EVERY = 150
TIMEOUT = 15.0
CHUNK_PREFIXES = ("NEO_EVIDENCE_", "NEO_COMMERCIAL_EVIDENCE_", "NEO_CHALLENGE_TRACK_")


def is_chunk_key(key: str) -> bool:
    return any(str(key or "").startswith(p) for p in CHUNK_PREFIXES)


class GitHubChunkStore:
    def __init__(self, repo: str, token: str, branch: str = "main"):
        self.repo = repo.strip()
        self.token = token.strip()
        self.branch = branch
        self._index: dict[str, str] | None = None   # key -> blob sha
        self._cache: dict[str, str] = {}             # key -> value
        self._commits_since_squash = 0
        self.stats = {"writes": 0, "write_failures": 0, "deletes": 0, "squashes": 0, "reads": 0, "read_failures": 0}

    # ---- helpers -----------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "osixbay-state"}

    def _url(self, path: str) -> str:
        return f"{API}/repos/{self.repo}/{path}"

    # ---- reads (sync: used at boot through _persisted_env) ------------------------
    def _load_index(self) -> dict[str, str]:
        if self._index is not None:
            return self._index
        index: dict[str, str] = {}
        try:
            with httpx.Client(timeout=TIMEOUT) as c:
                r = c.get(self._url(f"git/trees/{self.branch}?recursive=1"), headers=self._headers())
                if r.status_code == 200:
                    for item in r.json().get("tree") or []:
                        path = str(item.get("path") or "")
                        if item.get("type") == "blob" and path.startswith(DIR):
                            index[path[len(DIR):]] = str(item.get("sha") or "")
                elif r.status_code not in (404, 409):  # 409 = empty repo
                    self.stats["read_failures"] += 1
                    return {}  # do not cache a failed listing
        except httpx.HTTPError:
            self.stats["read_failures"] += 1
            return {}
        self._index = index
        return index

    def get(self, key: str) -> str | None:
        if key in self._cache:
            return self._cache[key]
        sha = self._load_index().get(key)
        if not sha:
            return None
        try:
            with httpx.Client(timeout=TIMEOUT) as c:
                r = c.get(self._url(f"git/blobs/{sha}"), headers=self._headers())
            if r.status_code != 200:
                self.stats["read_failures"] += 1
                return None
            value = base64.b64decode(r.json().get("content") or "").decode("utf-8")
        except (httpx.HTTPError, ValueError, UnicodeError):
            self.stats["read_failures"] += 1
            return None
        self.stats["reads"] += 1
        self._cache[key] = value
        return value

    def keys(self) -> list[str]:
        return sorted(self._load_index())

    # ---- writes (async: used by checkpoints) --------------------------------------
    async def _commit(self, client: httpx.AsyncClient, entries: list[dict[str, Any]], message: str) -> bool:
        ref = await client.get(self._url(f"git/ref/heads/{self.branch}"), headers=self._headers())
        if ref.status_code != 200:
            return False
        head = ref.json()["object"]["sha"]
        commit = await client.get(self._url(f"git/commits/{head}"), headers=self._headers())
        if commit.status_code != 200:
            return False
        tree = await client.post(self._url("git/trees"), headers=self._headers(),
                                 json={"base_tree": commit.json()["tree"]["sha"], "tree": entries})
        if tree.status_code != 201:
            return False
        new = await client.post(self._url("git/commits"), headers=self._headers(),
                                json={"message": message, "tree": tree.json()["sha"], "parents": [head]})
        if new.status_code != 201:
            return False
        upd = await client.patch(self._url(f"git/refs/heads/{self.branch}"), headers=self._headers(),
                                 json={"sha": new.json()["sha"], "force": False})
        return upd.status_code == 200

    async def put_many(self, values: dict[str, str]) -> bool:
        if not values:
            return True
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                entries, shas = [], {}
                for key, value in values.items():
                    b = await c.post(self._url("git/blobs"), headers=self._headers(),
                                     json={"content": value, "encoding": "utf-8"})
                    if b.status_code != 201:
                        self.stats["write_failures"] += 1
                        return False
                    shas[key] = b.json()["sha"]
                    entries.append({"path": DIR + key, "mode": "100644", "type": "blob", "sha": shas[key]})
                ok = False
                for _ in range(2):  # one retry if the branch moved (non-fast-forward)
                    if await self._commit(c, entries, f"state: write {len(entries)} chunks"):
                        ok = True
                        break
                if not ok:
                    self.stats["write_failures"] += 1
                    return False
        except (httpx.HTTPError, KeyError, ValueError):
            self.stats["write_failures"] += 1
            return False
        index = self._index if self._index is not None else {}
        index.update(shas)
        self._index = index
        self._cache.update(values)
        self.stats["writes"] += 1
        self._commits_since_squash += 1
        if self._commits_since_squash >= SQUASH_EVERY:
            await self.squash()
        return True

    async def delete_many(self, keys: list[str]) -> bool:
        present = [k for k in keys if k in self._load_index()]
        if not present:
            return True
        entries = [{"path": DIR + k, "mode": "100644", "type": "blob", "sha": None} for k in present]
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                ok = await self._commit(c, entries, f"state: delete {len(entries)} chunks")
        except (httpx.HTTPError, KeyError, ValueError):
            return False
        if ok:
            for k in present:
                (self._index or {}).pop(k, None)
                self._cache.pop(k, None)
            self.stats["deletes"] += 1
            self._commits_since_squash += 1
        return ok

    async def squash(self) -> bool:
        """Replace history with one parentless commit holding the current tree."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                ref = await c.get(self._url(f"git/ref/heads/{self.branch}"), headers=self._headers())
                head = ref.json()["object"]["sha"]
                tree = (await c.get(self._url(f"git/commits/{head}"), headers=self._headers())).json()["tree"]["sha"]
                new = await c.post(self._url("git/commits"), headers=self._headers(),
                                   json={"message": "state: squashed history (only the latest state is kept)",
                                         "tree": tree, "parents": []})
                if new.status_code != 201:
                    return False
                upd = await c.patch(self._url(f"git/refs/heads/{self.branch}"), headers=self._headers(),
                                    json={"sha": new.json()["sha"], "force": True})
        except (httpx.HTTPError, KeyError, ValueError):
            return False
        if upd.status_code == 200:
            self._commits_since_squash = 0
            self.stats["squashes"] += 1
            return True
        return False


def from_env() -> GitHubChunkStore | None:
    token = (os.getenv("NEO_STATE_GITHUB_TOKEN") or "").strip()
    repo = (os.getenv("NEO_STATE_GITHUB_REPO") or "").strip()
    if not token or "/" not in repo:
        return None
    return GitHubChunkStore(repo, token, branch=(os.getenv("NEO_STATE_GITHUB_BRANCH") or "main").strip() or "main")
