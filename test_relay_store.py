import concurrent.futures
import json
import os
import secrets
import sqlite3
import tempfile
import unittest

from relay_store import RelayError, RelayStore


def engine(old, text):
    n = old.get("round", 0) + 1
    return {"round": n, "identity_status": "self_declared"}, "Question " + str(n)


class RelayStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = self.temp.name + "/relay.sqlite3"
        self.now = [1800000000.0]
        self.store = RelayStore(self.path, "test", clock=lambda: self.now[0])
        self.token = secrets.token_urlsafe(32)

    def open(self, token=None, agent="pilot"):
        return self.store.open(token or self.token, agent, "intro", "Initial introduction", engine)

    def assert_error(self, code, fn, *args):
        with self.assertRaises(RelayError) as caught:
            fn(*args)
        self.assertEqual(caught.exception.code, code)

    def test_poll_survives_full_store_restart(self):
        result = self.open()
        self.store = RelayStore(self.path, "test", clock=lambda: self.now[0])
        polled = self.store.poll(result["thread_id"], self.token)
        self.assertEqual(polled["messages"], [result["message"]])
        self.assertEqual(polled["state"]["round"], 1)

    def test_enrollment_retry_after_lost_response_returns_same_thread(self):
        first = self.open()
        again = self.open()
        self.assertEqual(first, again)
        self.assertEqual(len(self.store.poll(first["thread_id"], self.token)["messages"]), 1)

    def test_three_round_exchange_without_callback(self):
        first = self.open()
        tid = first["thread_id"]
        for n in (2, 3):
            first = self.store.reply(tid, self.token, "reply-" + str(n), "answer", first["message"]["sequence"], engine)
        self.assertEqual(first["state"]["round"], 3)
        self.assertEqual([m["sequence"] for m in self.store.poll(tid, self.token)["messages"]], [2, 4, 6])

    def test_reply_retry_does_not_double_advance(self):
        tid = self.open()["thread_id"]
        first = self.store.reply(tid, self.token, "reply", "answer", 2, engine)
        second = self.store.reply(tid, self.token, "reply", "answer", 2, engine)
        self.assertEqual(first, second)
        self.assertEqual(self.store.poll(tid, self.token)["state"]["round"], 2)

    def test_same_id_with_changed_text_rejected(self):
        tid = self.open()["thread_id"]
        self.assert_error("message_id_conflict", self.store.reply, tid, self.token, "intro", "different", 0, engine)

    def test_out_of_order_reply_rejected(self):
        tid = self.open()["thread_id"]
        self.assert_error("reply_out_of_order", self.store.reply, tid, self.token, "later", "answer", 0, engine)

    def test_concurrent_duplicate_replies_commit_once(self):
        tid = self.open()["thread_id"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.store.reply, tid, self.token, "same", "answer", 2, engine) for _ in range(2)]
        self.assertEqual(futures[0].result(), futures[1].result())
        self.assertEqual(self.store.poll(tid, self.token)["state"]["round"], 2)

    def test_concurrent_different_replies_cannot_skip_round(self):
        tid = self.open()["thread_id"]
        def attempt(i):
            try:
                return self.store.reply(tid, self.token, str(i), "answer", 2, engine)
            except RelayError as exc:
                return exc.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(results.count("reply_out_of_order"), 1)

    def test_ack_is_monotonic_and_not_destructive(self):
        tid = self.open()["thread_id"]
        self.store.ack(tid, self.token, 2)
        self.assertEqual(self.store.ack(tid, self.token, 0)["acknowledged_through"], 2)
        self.assertEqual(len(self.store.poll(tid, self.token)["messages"]), 1)
        self.assertEqual(self.store.poll(tid, self.token, 2)["messages"], [])

    def test_ack_rejects_inbound_and_future_sequences(self):
        tid = self.open()["thread_id"]
        for value in (1, 4):
            self.assert_error("invalid_ack", self.store.ack, tid, self.token, value)

    def test_capability_does_not_grant_access_to_another_thread(self):
        tid = self.open()["thread_id"]
        other = secrets.token_urlsafe(32)
        self.assert_error("invalid_credentials", self.store.poll, tid, other)
        self.assert_error("invalid_credentials", self.store.reply, tid, other, "x", "answer", 2, engine)
        self.assert_error("invalid_credentials", self.store.ack, tid, other, 2)
        self.assert_error("invalid_credentials", self.store.close, tid, other)

    def test_claiming_same_name_does_not_share_state(self):
        tid1 = self.open()["thread_id"]
        token2 = secrets.token_urlsafe(32)
        tid2 = self.open(token2)["thread_id"]
        self.assertNotEqual(tid1, tid2)
        self.assert_error("invalid_credentials", self.store.poll, tid1, token2)

    def test_unknown_and_wrong_token_have_same_error(self):
        tid = self.open()["thread_id"]
        self.assert_error("invalid_credentials", self.store.poll, "unknown", self.token)
        self.assert_error("invalid_credentials", self.store.poll, tid, secrets.token_urlsafe(32))

    def test_closed_thread_cannot_be_reopened(self):
        tid = self.open()["thread_id"]
        self.store.close(tid, self.token)
        self.assertTrue(self.store.close(tid, self.token)["closed"])
        self.assert_error("thread_closed_or_expired", self.store.poll, tid, self.token)
        self.assert_error("thread_closed_or_expired", self.open)

    def test_expiry_survives_restart_and_poll_does_not_extend_it(self):
        tid = self.open()["thread_id"]
        self.now[0] += 86399
        self.store.poll(tid, self.token)
        self.now[0] += 2
        self.store = RelayStore(self.path, "test", clock=lambda: self.now[0])
        self.assert_error("thread_closed_or_expired", self.store.poll, tid, self.token)
        self.assert_error("thread_closed_or_expired", self.store.reply, tid, self.token, "x", "answer", 2, engine)

    def test_storage_failure_does_not_advance_state(self):
        tid = self.open()["thread_id"]
        def broken(old, text):
            raise RuntimeError("deliberate test failure")
        with self.assertRaises(RuntimeError):
            self.store.reply(tid, self.token, "x", "answer", 2, broken)
        self.assertEqual(self.store.poll(tid, self.token)["state"]["round"], 1)
        self.assertEqual(self.store.reply(tid, self.token, "x", "answer", 2, engine)["state"]["round"], 2)

    def test_failed_enrollment_leaves_no_orphan(self):
        def broken(old, text):
            raise RuntimeError("deliberate test failure")
        with self.assertRaises(RuntimeError):
            self.store.open(self.token, "pilot", "intro", "text", broken)
        self.assertEqual(self.open()["state"]["round"], 1)

    def test_tokens_never_persist_as_plaintext(self):
        tid = self.open()["thread_id"]
        self.store.ack(tid, self.token, 2)
        with sqlite3.connect(self.path) as db:
            dump = "\n".join(db.iterdump())
            audit = db.execute("SELECT kind,seq,at FROM audit").fetchall()
        self.assertNotIn(self.token, dump)
        self.assertNotIn("Initial introduction", str(audit))
        if os.name == "posix":
            self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_namespace_mismatch_fails_closed(self):
        self.open()
        with self.assertRaises(ValueError):
            RelayStore(self.path, "other")

    def test_rate_limit_does_not_change_round(self):
        tid = self.open()["thread_id"]
        self.store.requests_per_minute = 1
        self.store.poll(tid, self.token)
        self.assert_error("rate_limited", self.store.poll, tid, self.token)
        self.now[0] += 60
        self.assertEqual(self.store.poll(tid, self.token)["state"]["round"], 1)

    def test_capacity_is_bounded(self):
        self.store.capacity = 1
        self.open()
        self.assert_error("relay_capacity_reached", self.open, secrets.token_urlsafe(32), "other")

    def test_thread_exchange_budget_is_bounded(self):
        self.store.max_exchanges = 1
        tid = self.open()["thread_id"]
        self.assert_error("thread_capacity_reached", self.store.reply, tid, self.token, "x", "answer", 2, engine)

    def test_large_multibyte_message_is_rejected(self):
        self.assert_error("message_too_large", self.store.open, self.token, "pilot", "intro", "\u20ac" * 3000, engine)

    def test_cursor_validation(self):
        tid = self.open()["thread_id"]
        for value in (True, -1, "2", 1.5):
            self.assert_error("invalid_sequence", self.store.poll, tid, self.token, value)
        self.assert_error("cursor_ahead", self.store.poll, tid, self.token, 4)

    def test_retention_purges_old_private_content_and_releases_capacity(self):
        self.store.capacity = 1
        self.open()
        self.now[0] += 172801
        new = self.open(secrets.token_urlsafe(32), "new")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM threads").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT id FROM threads").fetchone()[0], new["thread_id"])


if __name__ == "__main__":
    unittest.main()
