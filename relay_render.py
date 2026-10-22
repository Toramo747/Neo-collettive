"""Standalone Render relay: no cloud_mcp, no NEO/Jarvis startup, no public snapshots.

The optional overlay entrypoint remains available separately. This entrypoint is
for a NEW service and will not run the main application under any configuration.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from relay_app import PREFIX, RelayOverlay
from relay_store import RelayStore
from relay_render_backup import backup_database

VERSION = "render-relay-pilot-1"
NAMESPACE = "mycelix-relay-render-pilot"


def storage_paths(env: dict) -> Path:
    """Require a real mounted volume, not an ephemeral directory named /var/data."""
    root = Path(env.get("MYCELIX_RELAY_DISK_PATH", "/var/data"))
    if not root.is_absolute() or root == Path("/") or ".." in root.parts:
        raise ValueError("invalid_disk_path")
    if not root.is_dir() or root.resolve() != root or not os.path.ismount(root):
        raise ValueError("persistent_mount_required")
    private = root / "mycelix-relay"
    if private.is_symlink():
        raise ValueError("symlink_private_directory")
    private.mkdir(mode=0o700, exist_ok=True)
    os.chmod(private, 0o700)
    return private / "relay.sqlite3"


def database_check(db: Path, *, integrity: bool = False) -> None:
    """Never create a missing database; verify schema and a rollback-only write."""
    if not db.is_file() or db.is_symlink():
        raise ValueError("database_missing")
    with closing(sqlite3.connect(db.as_uri() + "?mode=rw", uri=True, timeout=1.0,
                                 isolation_level=None)) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            metadata = dict(conn.execute("SELECT key,value FROM metadata"))
            if metadata.get("schema") != "1" or metadata.get("namespace") != NAMESPACE:
                raise ValueError("database_identity_mismatch")
            if integrity and conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("database_integrity_failed")
            conn.execute("INSERT OR REPLACE INTO metadata VALUES ('render_health_probe','1')")
            conn.rollback()
        finally:
            if conn.in_transaction:
                conn.rollback()


def public_response(data, status=200):
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff", "X-Robots-Tag": "noindex"})


class RenderRelay:
    def __init__(self, environ=None, *, engine=None):
        # The engine parameter is dependency injection for isolated tests, never a request field.
        self.env = dict(os.environ if environ is None else environ)
        flag = str(self.env.get("MYCELIX_RELAY_ENABLED", "0")).strip().lower()
        self.enabled = flag in {"1", "true"}
        self.ready = False
        self.path = None
        self.file_identity = None
        self.delegate = None
        if flag not in {"0", "false", "1", "true"}:
            self.enabled = True  # Invalid configuration must not masquerade as disabled/healthy.
            return
        if not self.enabled:
            return
        try:
            if self.env.get("MYCELIX_RELAY_STORAGE_CONFIRMED") != "1":
                raise ValueError("storage_approval_required")
            invite = self.env.get("MYCELIX_RELAY_INVITE", "")
            if not isinstance(invite, str) or not 32 <= len(invite) <= 256 or not invite.isascii():
                raise ValueError("invalid_invite")
            path = storage_paths(self.env)
            marker = path.parent / ".initialized"
            if marker.is_symlink() or path.is_symlink():
                raise ValueError("invalid_database_path")
            if marker.exists() and not path.is_file():
                raise ValueError("existing_database_missing_no_automatic_reset")
            if path.exists():
                database_check(path, integrity=True)
                # Consistent pre-start copy, not raw file copying and not an automatic restore.
                backup_database(path, path.parent / "backups", NAMESPACE)
            store = RelayStore(str(path), NAMESPACE)
            database_check(path, integrity=True)
            if not marker.exists():
                fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as fh:
                    fh.write(NAMESPACE + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            elif marker.read_text().strip() != NAMESPACE:
                raise ValueError("invalid_database_marker")
            if engine is None:
                from relay_peer import advance_peer
                engine = advance_peer
            self.path = path
            stat = path.stat()
            self.file_identity = (stat.st_dev, stat.st_ino)
            self.delegate = RelayOverlay(self.not_found, store, invite=invite, engine=engine)
            self.ready = True
        except Exception:
            # Do not print exception details, credentials, transcripts, or filesystem paths.
            self.ready = False

    def _check(self):
        if not self.ready or self.path is None:
            raise ValueError("relay_not_ready")
        if storage_paths(self.env) != self.path:
            raise ValueError("mount_changed")
        stat = self.path.stat()
        if (stat.st_dev, stat.st_ino) != self.file_identity:
            raise ValueError("database_replaced")
        database_check(self.path)

    async def not_found(self, scope, receive, send):
        await public_response({"error": "not_found"}, 404)(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            return
        path = scope.get("path", "")
        health = path == "/health" and scope.get("method") in {"GET", "HEAD"}
        relay = path == PREFIX or path.startswith(PREFIX + "/")
        if not health and not relay:
            return await self.not_found(scope, receive, send)
        available = False
        if self.enabled:
            try:
                await run_in_threadpool(self._check)
                available = True
            except Exception:
                pass
        if health:
            result = {"service": "mycelix-relay", "version": VERSION,
                      "mode": "disabled" if not self.enabled else ("ready" if available else "unavailable"),
                      "enabled": self.enabled, "storage_ready": available,
                      "commercial_influence": "NONE"}
            return await public_response(result, 200 if available or not self.enabled else 503)(scope, receive, send)
        if not self.enabled or not available:
            return await public_response({"error": "relay_disabled" if not self.enabled else "relay_unavailable"},
                                         503)(scope, receive, send)
        return await self.delegate(scope, receive, send)


if __name__ == "__main__":
    import uvicorn
    os.umask(0o077)
    uvicorn.run(RenderRelay(), host="0.0.0.0", port=int(os.getenv("PORT", "10000")),
                workers=1, access_log=False, proxy_headers=False, timeout_keep_alive=5,
                timeout_graceful_shutdown=25, limit_concurrency=64, backlog=64)
