"""Private, bounded store for the opt-in MYCELIX rendezvous pilot.

No networking, autopilot imports, shared state, or commercial evidence writes.
All state transitions and their replies commit in one SQLite transaction.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
MESSAGE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
MAX_TEXT_BYTES = 8192


class RelayError(Exception):
    def __init__(self, code: str, status: int = 400, retry_after: int = 0):
        super().__init__(code)
        self.code, self.status, self.retry_after = code, status, retry_after


def token_hash(token: str) -> str:
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise RelayError("invalid_credentials", 401)
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def message_fields(message_id: str, text: str) -> None:
    if not isinstance(message_id, str) or not MESSAGE_ID.fullmatch(message_id):
        raise RelayError("invalid_message_id")
    if not isinstance(text, str) or not text.strip():
        raise RelayError("text_required")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise RelayError("message_too_large", 413)


def nonnegative(value: int) -> int:
    if type(value) is not int or not 0 <= value <= 1000000:
        raise RelayError("invalid_sequence")
    return value


class RelayStore:
    def __init__(self, path: str, namespace: str, *, clock: Callable = time.time,
                 ttl: int = 86400, capacity: int = 32, max_exchanges: int = 24,
                 requests_per_minute: int = 60):
        p = Path(path)
        if not p.is_absolute() or not p.parent.is_dir() or p.is_symlink():
            raise ValueError("explicit_private_database_path_required")
        # The operator supplies a private directory on a confirmed persistent volume.
        if os.name == "posix" and p.parent.stat().st_mode & 0o077:
            raise ValueError("database_directory_must_be_private")
        if not namespace or not 60 <= ttl <= 604800:
            raise ValueError("invalid_namespace_or_ttl")
        if not 1 <= capacity <= 128 or not 1 <= max_exchanges <= 64:
            raise ValueError("invalid_capacity")
        if not 1 <= requests_per_minute <= 600:
            raise ValueError("invalid_rate_limit")
        self.path, self.namespace, self.clock = str(p), namespace, clock
        self.ttl, self.capacity, self.max_exchanges = ttl, capacity, max_exchanges
        self.requests_per_minute = requests_per_minute
        fd = os.open(p, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(p, 0o600)
        with self._tx() as db:
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for key, value in (("schema", "1"), ("namespace", namespace)):
                row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
                if row and row[0] != value:
                    raise ValueError("incompatible_relay_database")
                db.execute("INSERT OR IGNORE INTO metadata VALUES (?,?)", (key, value))
            db.execute("""CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, agent_id TEXT NOT NULL,
                expires REAL NOT NULL, closed INTEGER NOT NULL DEFAULT 0,
                ack INTEGER NOT NULL DEFAULT 0, last_seq INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT '{}')""")
            db.execute("""CREATE TABLE IF NOT EXISTS exchanges (
                thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                message_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                incoming TEXT NOT NULL, response TEXT NOT NULL, seq INTEGER NOT NULL,
                PRIMARY KEY(thread_id,message_id), UNIQUE(thread_id,seq))""")
            db.execute("""CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                kind TEXT NOT NULL, seq INTEGER NOT NULL, at REAL NOT NULL)""")
            db.execute("CREATE TABLE IF NOT EXISTS limits (bucket TEXT PRIMARY KEY, window INTEGER, used INTEGER)")

    @contextmanager
    def _tx(self):
        db = sqlite3.connect(self.path, timeout=1.5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _limit(self, db, bucket: str, maximum: int):
        window = int(self.clock()) // 60
        row = db.execute("SELECT window,used FROM limits WHERE bucket=?", (bucket,)).fetchone()
        used = row[1] if row and row[0] == window else 0
        if used >= maximum:
            raise RelayError("rate_limited", 429, 60 - int(self.clock()) % 60)
        db.execute("INSERT OR REPLACE INTO limits VALUES (?,?,?)", (bucket, window, used + 1))

    def _auth(self, db, thread_id: str, token: str, *, terminal_ok=False):
        digest = token_hash(token)
        row = db.execute("SELECT * FROM threads WHERE id=?", (str(thread_id)[:128],)).fetchone()
        expected = row["token_hash"] if row else "0" * 64
        if not hmac.compare_digest(expected, digest) or row is None:
            raise RelayError("invalid_credentials", 401)
        if not terminal_ok and (row["closed"] or self.clock() >= row["expires"]):
            raise RelayError("thread_closed_or_expired", 410)
        self._limit(db, "thread:" + row["id"], self.requests_per_minute)
        return row

    def _audit(self, db, thread_id: str, kind: str, seq: int):
        db.execute("INSERT INTO audit(thread_id,kind,seq,at) VALUES (?,?,?,?)",
                   (thread_id, kind, seq, self.clock()))
        db.execute("DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 2048)")

    def _exchange(self, db, row, message_id, text, in_reply_to, engine):
        message_fields(message_id, text)
        nonnegative(in_reply_to)
        digest = hashlib.sha256(json.dumps([text, in_reply_to], ensure_ascii=False).encode()).hexdigest()
        old = db.execute("SELECT request_hash,response FROM exchanges WHERE thread_id=? AND message_id=?",
                         (row["id"], message_id)).fetchone()
        if old:
            if not hmac.compare_digest(old[0], digest):
                raise RelayError("message_id_conflict", 409)
            return json.loads(old[1])
        if in_reply_to != row["last_seq"]:
            raise RelayError("reply_out_of_order", 409)
        if row["last_seq"] // 2 >= self.max_exchanges:
            raise RelayError("thread_capacity_reached", 409)
        state, reply = engine(json.loads(row["state"]), text)
        if not isinstance(state, dict) or not isinstance(reply, str) or not reply.strip():
            raise ValueError("invalid_engine_output")
        state_json = json.dumps(state, ensure_ascii=False)
        if len(state_json.encode()) > 16384 or len(reply.encode()) > MAX_TEXT_BYTES:
            raise ValueError("engine_output_too_large")
        seq = row["last_seq"] + 2
        response = {"thread_id": row["id"], "expires_at": row["expires"],
                    "message": {"sequence": seq, "in_reply_to": message_id, "text": reply},
                    "state": state, "commercial_influence": "NONE"}
        encoded = json.dumps(response, ensure_ascii=False)
        db.execute("INSERT INTO exchanges VALUES (?,?,?,?,?,?)",
                   (row["id"], message_id, digest, text, encoded, seq))
        db.execute("UPDATE threads SET state=?,last_seq=?,ack=MAX(ack,?) WHERE id=?",
                   (state_json, seq, in_reply_to, row["id"]))
        self._audit(db, row["id"], "exchange_committed", seq)
        return response

    def open(self, token: str, agent_id: str, message_id: str, text: str, engine):
        digest = token_hash(token)
        message_fields(message_id, text)
        if not isinstance(agent_id, str) or not agent_id.strip() or len(agent_id) > 180:
            raise RelayError("invalid_agent_id")
        with self._tx() as db:
            self._limit(db, "open", 12)
            # Lazy bounded retention, not a background task: erase after expiry + 24h.
            db.execute("DELETE FROM limits WHERE bucket IN (SELECT 'thread:'||id FROM threads WHERE expires<?)",
                       (self.clock() - 86400,))
            db.execute("DELETE FROM threads WHERE expires<?", (self.clock() - 86400,))
            row = db.execute("SELECT * FROM threads WHERE token_hash=?", (digest,)).fetchone()
            if row:
                if row["agent_id"] != agent_id:
                    raise RelayError("thread_identity_conflict", 409)
                row = self._auth(db, row["id"], token)
                # Replay-safe enrollment uses the same client-held capability and message_id.
                return self._exchange(db, row, message_id, text, 0, engine)
            if db.execute("SELECT COUNT(*) FROM threads").fetchone()[0] >= self.capacity:
                raise RelayError("relay_capacity_reached", 429, 60)
            if db.execute("SELECT COUNT(*) FROM threads WHERE agent_id=? AND expires>? AND closed=0",
                          (agent_id, self.clock())).fetchone()[0] >= 2:
                raise RelayError("agent_capacity_reached", 429, 60)
            tid = "rly-" + secrets.token_hex(16)
            db.execute("INSERT INTO threads(id,token_hash,agent_id,expires) VALUES (?,?,?,?)",
                       (tid, digest, agent_id, self.clock() + self.ttl))
            row = db.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
            self._audit(db, tid, "thread_created", 0)
            return self._exchange(db, row, message_id, text, 0, engine)

    def reply(self, thread_id, token, message_id, text, in_reply_to, engine):
        with self._tx() as db:
            row = self._auth(db, thread_id, token)
            return self._exchange(db, row, message_id, text, in_reply_to, engine)

    def poll(self, thread_id, token, after=0):
        nonnegative(after)
        with self._tx() as db:
            row = self._auth(db, thread_id, token)
            if after > row["last_seq"]:
                raise RelayError("cursor_ahead", 409)
            records = db.execute("SELECT response FROM exchanges WHERE thread_id=? AND seq>? ORDER BY seq LIMIT 16",
                                 (thread_id, after)).fetchall()
            messages = [json.loads(r[0])["message"] for r in records]
            cursor = messages[-1]["sequence"] if messages else after
            return {"thread_id": thread_id, "messages": messages, "next_cursor": cursor,
                    "has_more": cursor < row["last_seq"], "acknowledged_through": row["ack"],
                    "expires_at": row["expires"], "state": json.loads(row["state"]),
                    "poll_after_seconds": 15, "commercial_influence": "NONE"}

    def ack(self, thread_id, token, through):
        nonnegative(through)
        with self._tx() as db:
            row = self._auth(db, thread_id, token)
            if through > row["last_seq"] or through % 2:
                raise RelayError("invalid_ack", 409)
            effective = max(row["ack"], through)
            if effective != row["ack"]:
                db.execute("UPDATE threads SET ack=? WHERE id=?", (effective, thread_id))
                self._audit(db, thread_id, "ack", effective)
            return {"thread_id": thread_id, "acknowledged_through": effective}

    def close(self, thread_id, token):
        with self._tx() as db:
            row = self._auth(db, thread_id, token, terminal_ok=True)
            if not row["closed"]:
                db.execute("UPDATE threads SET closed=1 WHERE id=?", (thread_id,))
                self._audit(db, thread_id, "closed", row["last_seq"])
            return {"thread_id": thread_id, "closed": True}
