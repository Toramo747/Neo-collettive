"""envstore (ops/hetzner/envstore) must look like the Render env-var API to NEO.

Covers the exact shapes cloud_mcp.py and render_saved_env.py rely on:
list pages with ``envVar``/``cursor``, PUT echoing ``value`` (the checkpoint
verifies the echo), DELETE 204, 404 on missing keys, bearer auth, atomic
writes, deploy hook/list, and the one-shot .env import used at migration.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import socket
import threading
import urllib.error
import urllib.request

import pytest

import render_saved_env

ROOT = pathlib.Path(__file__).resolve().parent
APP = ROOT / "ops" / "hetzner" / "envstore" / "app.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def envstore(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVSTORE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ENVSTORE_TOKEN", "t0ken")
    monkeypatch.setenv("ENVSTORE_SERVICE_ID", "neo")
    monkeypatch.setenv("ENVSTORE_DEPLOY_HOOK", "hook123")
    monkeypatch.setenv("ENVSTORE_DEPLOY_COMMAND", "")
    spec = importlib.util.spec_from_file_location("envstore_app", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    port = _free_port()
    server = mod.ThreadingHTTPServer(("127.0.0.1", port), mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield mod, f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def _call(base, method, path, body=None, token="t0ken"):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


def test_put_get_delete_match_render_shapes(envstore):
    _, base = envstore
    status, body = _call(base, "PUT", "/v1/services/neo/env-vars/NEO_STATE_JSON", {"value": "zlib:abc"})
    assert status == 200 and body == {"key": "NEO_STATE_JSON", "value": "zlib:abc"}
    status, body = _call(base, "GET", "/v1/services/neo/env-vars/NEO_STATE_JSON")
    assert status == 200 and body["value"] == "zlib:abc"
    status, _ = _call(base, "DELETE", "/v1/services/neo/env-vars/NEO_STATE_JSON")
    assert status == 204
    status, _ = _call(base, "GET", "/v1/services/neo/env-vars/NEO_STATE_JSON")
    assert status == 404
    status, _ = _call(base, "DELETE", "/v1/services/neo/env-vars/NEO_STATE_JSON")
    assert status == 404


def test_rejects_bad_token_and_bad_keys(envstore):
    _, base = envstore
    assert _call(base, "GET", "/v1/services/neo/env-vars", token="wrong")[0] == 401
    assert _call(base, "GET", "/v1/services/other/env-vars")[0] == 404
    assert _call(base, "PUT", "/v1/services/neo/env-vars/bad%20key", {"value": "x"})[0] == 400
    assert _call(base, "PUT", "/v1/services/neo/env-vars/NEO_X", {"value": 5})[0] == 400


def test_list_pages_are_readable_by_render_saved_env(envstore):
    _, base = envstore
    for i in range(7):
        _call(base, "PUT", f"/v1/services/neo/env-vars/NEO_EVIDENCE_{i:02d}", {"value": f"v{i}"})
    _call(base, "PUT", "/v1/services/neo/env-vars/SECRET_KEY", {"value": "hidden"})
    status, page = _call(base, "GET", "/v1/services/neo/env-vars?limit=3")
    assert status == 200 and len(page) == 3 and page[0]["envVar"]["key"] == "NEO_EVIDENCE_00"
    assert page[-1]["cursor"] == "NEO_EVIDENCE_02"
    status, page2 = _call(base, "GET", "/v1/services/neo/env-vars?limit=3&cursor=NEO_EVIDENCE_02")
    assert [p["envVar"]["key"] for p in page2] == ["NEO_EVIDENCE_03", "NEO_EVIDENCE_04", "NEO_EVIDENCE_05"]

    saved = render_saved_env.fetch_saved_env(base + "/v1", "neo", "t0ken")
    assert saved["ok"] is True
    assert set(saved["values"]) == {f"NEO_EVIDENCE_{i:02d}" for i in range(7)}
    assert "SECRET_KEY" in saved["key_names"] and "SECRET_KEY" not in saved["values"]


def test_service_and_deploys(envstore):
    _, base = envstore
    status, svc = _call(base, "GET", "/v1/services/neo")
    assert status == 200 and svc["id"] == "neo" and svc["suspended"] == "not_suspended" and svc["ownerId"]
    assert _call(base, "GET", "/deploy/nope?ref=abc")[0] == 404
    status, dep = _call(base, "POST", "/deploy/hook123?ref=0123abcd", token=None)
    assert status == 201 and dep["commit"]["id"] == "0123abcd"
    status, rows = _call(base, "GET", "/v1/services/neo/deploys?limit=5")
    assert status == 200 and rows[0]["deploy"]["id"] == dep["id"] and rows[0]["deploy"]["trigger"] == "hook"
    assert _call(base, "POST", "/deploy/hook123?ref=../../etc", token=None)[0] == 400


def test_atomic_write_leaves_no_tmp_files(envstore, tmp_path):
    mod, base = envstore
    big = "x" * 200_000
    _call(base, "PUT", "/v1/services/neo/env-vars/NEO_BIG", {"value": big})
    vars_dir = tmp_path / "data" / "vars"
    assert sorted(os.listdir(vars_dir)) == ["NEO_BIG"]
    assert (vars_dir / "NEO_BIG").read_text() == big


def test_import_dotenv_filters_by_prefix(envstore, tmp_path):
    mod, base = envstore
    dotenv = tmp_path / "render.env"
    dotenv.write_text('NEO_STATE_JSON="zlib:abc"\nRENDER_API_KEY=secret\nBACKUP_1=b\n# c\nbroken\n')
    assert mod.import_dotenv(str(dotenv), ("NEO_", "BACKUP_")) == 2
    assert _call(base, "GET", "/v1/services/neo/env-vars/NEO_STATE_JSON")[1]["value"] == "zlib:abc"
    assert _call(base, "GET", "/v1/services/neo/env-vars/RENDER_API_KEY")[0] == 404
