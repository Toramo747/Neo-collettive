import hashlib
import json
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import cloud_mcp
from state_compaction import (
    PROTECTED_STATE_KEYS,
    compact_state_payload,
    encoded_sizes,
    key_weight_report,
    merge_cumulative_inbound_summary,
    second_level_weight_report,
    trim_inbound_traffic_events,
)


def _noise(seed: str, blocks: int = 8) -> str:
    parts = []
    for index in range(blocks):
        parts.append(hashlib.sha256(f"{seed}:{index}".encode()).hexdigest())
    return "".join(parts)


def _heavy_opportunity(cycle: int, item: int) -> dict:
    return {
        "tool_name": f"tool-{cycle}-{item}",
        "family": f"family-{item}",
        "monetization_score": 70 + item,
        "gate_pass": item == 0,
        "missing": [f"missing-{item}-{n}" for n in range(4)],
        "sources": [
            {
                "url": "https://example.invalid/" + _noise(f"url-{cycle}-{item}-{n}", 4),
                "excerpt": _noise(f"excerpt-{cycle}-{item}-{n}", 12),
                "signals": [_noise(f"signal-{cycle}-{item}-{n}-{s}", 2) for s in range(4)],
            }
            for n in range(20)
        ],
        "payment_signals": [_noise(f"pay-{cycle}-{item}-{n}", 3) for n in range(8)],
        "gap_signals": [_noise(f"gap-{cycle}-{item}-{n}", 3) for n in range(8)],
    }


def _heavy_cycle(cycle: int) -> dict:
    top5 = [_heavy_opportunity(cycle, item) for item in range(5)]
    return {
        "generated_at_utc": f"2026-09-{(cycle % 28) + 1:02d}T00:00:00+00:00",
        "top5": top5,
        "transcripts": [
            {
                "opportunity": row["tool_name"],
                "decision": "HOLD",
                "messages": [
                    {"role": "critic", "text": _noise(f"transcript-{cycle}-{idx}-{n}", 10)}
                    for n in range(8)
                ],
            }
            for idx, row in enumerate(top5)
        ],
    }


def _protected_payload() -> dict:
    return {
        "boundary_events": [
            {
                "type": "human_authorized_reply_sent",
                "reply_key": "agentworld_clarification_20260930",
                "sent_at_utc": "2026-09-30T10:00:00+00:00",
                "match_path": "identity",
            }
        ],
        "inbound_messages": [
            {
                "message_id": "m1",
                "thread_id": "thread-1",
                "text": "synthetic protected inbound",
                "admission_status": "ANONYMOUS",
                "dialogue_status": "PENDING_IDENTITY",
                "identity_status": "anonymous",
            }
        ],
        "agent_chat_events": [{"event_id": "e1", "text": "synthetic chat event"}],
        "inbound_agent_stats": {
            "peer-1": {
                "status": "ANONYMOUS",
                "dialogue_status": "PENDING_IDENTITY",
                "identity_status": "anonymous",
            }
        },
        "inbound_security_events": [{"event_id": "s1", "traffic_class": "UNKNOWN"}],
        "inbound_security_stats": {"blocked_total": 1},
        "inbound_review_queue": [{"thread_id": "thread-1", "claim_excerpt": "synthetic"}],
        "agent_chat_monitor": {"thread_count": 1, "threads": [{"thread_id": "thread-1"}]},
        "agent_demand_observatory": {"messages_observed": 1},
        "neo_dialect_peers": {"peer-1": {"state": "NEW"}},
        "neo_dialect_events": [{"event": "HELLO"}],
        "neo_dialect_seti_probe": {"status": "IDLE"},
    }


def _traffic_events(count: int = 1000) -> list[dict]:
    categories = ["crawler_probe", "self_traffic", "real_contact", "unknown"]
    return [
        {
            "event_id": f"traffic-{i}",
            "timestamp_utc": f"2026-09-{20 + (i % 10):02d}T12:{i % 60:02d}:00+00:00",
            "category": categories[i % len(categories)],
            "endpoint": "/health" if i % 2 == 0 else "/a2a",
            "method": "GET" if i % 2 == 0 else "POST",
            "content_fingerprint": hashlib.sha256(f"fp-{i}".encode()).hexdigest()[:24],
        }
        for i in range(count)
    ]


def _heavy_payload() -> dict:
    payload = {
        "runtime_profile": {"profile_id": "mycelix-prod-main", "deployment_role": "production"},
        "state_saved_at_utc": "2026-09-30T10:00:00+00:00",
        "cycles_completed": 1200,
        "tool_opportunities": {
            "generated_at_utc": "2026-09-30T10:00:00+00:00",
            "top5": [
                {
                    "tool_name": f"current-tool-{i}",
                    "family": f"family-{i}",
                    "monetization_score": 75 + i,
                    "gate_pass": i == 0,
                    "missing": ["synthetic"],
                    "sources": [{"url": f"https://example.invalid/current/{i}/{n}"} for n in range(3)],
                }
                for i in range(5)
            ],
            "council_transcripts": [
                {"opportunity": f"current-tool-{i}", "decision": "HOLD", "messages": [{"text": "current synthetic decision"}]}
                for i in range(5)
            ],
        },
        "council_history": [_heavy_cycle(cycle) for cycle in range(12)],
        "inbound_traffic_events": _traffic_events(),
        "inbound_traffic_summary": {
            "schema_v": 2,
            "events_total": 1000,
            "logical_messages_total": 1000,
            "technical_evidence_total": 1000,
            "counts": {
                "total": {
                    "crawler_probe": 250,
                    "self_traffic": 250,
                    "real_contact_pending": 0,
                    "real_contact": 250,
                    "legacy_unattributable": 0,
                    "malicious_solicitation": 0,
                    "unknown": 250,
                },
                "last_24h": {},
                "last_7d": {},
            },
            "first_real_contact_utc": "2026-09-20T12:02:00+00:00",
            "last_real_contact_utc": "2026-09-29T12:58:00+00:00",
        },
        "commercial_evidence_memory": [
            {"excerpt": _noise(f"commercial-{i}", 4), "sources": [_noise(f"source-{i}-{n}", 1) for n in range(4)]}
            for i in range(20)
        ],
    }
    payload.update(_protected_payload())
    return payload


def _bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class _FakeResponse:
    is_success = True
    status_code = 200


class _FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def put(self, *args, **kwargs):
        return _FakeResponse()


class StateCompactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_heavy_state_compacts_below_target_and_checkpoint_succeeds(self):
        payload = _heavy_payload()
        before_raw, before_encoded = encoded_sizes(payload)
        self.assertGreater(before_encoded, 90_000)

        compacted, meta = compact_state_payload(
            payload,
            max_bytes=100_000,
            target_bytes=60_000,
            force=True,
        )
        after_raw, after_encoded = encoded_sizes(compacted)
        self.assertLess(after_encoded, 60_000)
        self.assertTrue(meta["applied"])
        self.assertIn("a_council_history", [x["level"] for x in meta["levels"]])

        old_key = cloud_mcp.RENDER_API_KEY
        old_service = cloud_mcp.RENDER_SERVICE_ID
        try:
            cloud_mcp.RENDER_API_KEY = "synthetic"
            cloud_mcp.RENDER_SERVICE_ID = "synthetic"
            with patch.object(cloud_mcp, "_state_payload", return_value=deepcopy(payload)), patch.object(
                cloud_mcp.httpx, "AsyncClient", _FakeClient
            ):
                result = await cloud_mcp._checkpoint_state_to_render()
            self.assertTrue(result["ok"])
            self.assertLess(result["stored_bytes"], 60_000)
            self.assertTrue(result["compaction"]["applied"])
        finally:
            cloud_mcp.RENDER_API_KEY = old_key
            cloud_mcp.RENDER_SERVICE_ID = old_service

    def test_protected_state_is_byte_identical(self):
        payload = _heavy_payload()
        before = {key: _bytes(payload[key]) for key in PROTECTED_STATE_KEYS if key in payload}
        compacted, _ = compact_state_payload(payload, max_bytes=100_000, force=True)
        after = {key: _bytes(compacted[key]) for key in PROTECTED_STATE_KEYS if key in compacted}
        self.assertEqual(before, after)

    def test_compaction_is_idempotent(self):
        payload = _heavy_payload()
        once, _ = compact_state_payload(payload, max_bytes=100_000, force=True)
        twice, _ = compact_state_payload(once, max_bytes=100_000, force=True)
        self.assertEqual(_bytes(once), _bytes(twice))

    def test_one_shot_receipt_survives_compaction_encode_decode_restore(self):
        payload = _heavy_payload()
        compacted, _ = compact_state_payload(payload, max_bytes=100_000, force=True)
        value, _, stored_bytes = cloud_mcp._encode_state_env(compacted)
        self.assertLess(stored_bytes, 60_000)
        restored = cloud_mcp._decode_state_env(value)
        self.assertEqual(
            _bytes(restored["boundary_events"]),
            _bytes(payload["boundary_events"]),
        )

        previous = deepcopy(cloud_mcp.AUTOPILOT_STATE)
        try:
            cloud_mcp.AUTOPILOT_STATE["boundary_events"] = []
            self.assertTrue(cloud_mcp._merge_state_payload(restored))
            self.assertEqual(
                _bytes(cloud_mcp.AUTOPILOT_STATE["boundary_events"]),
                _bytes(payload["boundary_events"]),
            )
        finally:
            cloud_mcp.AUTOPILOT_STATE.clear()
            cloud_mcp.AUTOPILOT_STATE.update(previous)

    def test_inbound_traffic_summary_totals_survive_event_trim(self):
        payload = _heavy_payload()
        original = deepcopy(payload["inbound_traffic_summary"])
        compacted = trim_inbound_traffic_events(payload, limit=300)
        self.assertEqual(compacted["inbound_traffic_summary"], original)
        self.assertLessEqual(len(compacted["inbound_traffic_events"]), 300)

        recent = {
            "schema_v": 2,
            "events_total": 300,
            "logical_messages_total": 300,
            "technical_evidence_total": 300,
            "counts": {
                "total": {"crawler_probe": 75},
                "last_24h": {"crawler_probe": 10},
                "last_7d": {"crawler_probe": 75},
            },
            "first_real_contact_utc": "2026-09-28T00:00:00+00:00",
            "last_real_contact_utc": "2026-09-29T00:00:00+00:00",
        }
        merged = merge_cumulative_inbound_summary(original, recent)
        self.assertEqual(merged["counts"]["total"], original["counts"]["total"])
        self.assertEqual(merged["events_total"], original["events_total"])
        self.assertEqual(merged["first_real_contact_utc"], original["first_real_contact_utc"])
        self.assertEqual(merged["last_real_contact_utc"], original["last_real_contact_utc"])
        self.assertEqual(merged["counts"]["last_24h"], recent["counts"]["last_24h"])

    def test_challenge_track_compaction_is_bounded_and_separate(self):
        payload=_heavy_payload()
        payload["challenge_track"]={
            "mode":"shadow",
            "memory":[
                {
                    "track":"challenge",
                    "fingerprint":hashlib.sha256(f"challenge-{i}".encode()).hexdigest()[:24],
                    "challenge_key":hashlib.sha256(f"key-{i}".encode()).hexdigest()[:24],
                    "requester_key":f"r-{i}",
                    "domain":"example.invalid",
                    "updated_at_utc":f"2026-10-04T10:{i%60:02d}:00Z",
                }
                for i in range(260)
            ],
            "gate_state":{
                "candidates":{
                    f"k-{i}":{"updated_at_utc":f"2026-10-04T10:{i%60:02d}:00Z"}
                    for i in range(100)
                },
                "flips":[{"n":i} for i in range(90)],
            },
            "latest":{"status":"CHALLENGE_SELECT"},
        }
        compacted,_=compact_state_payload(payload,max_bytes=100_000,target_bytes=60_000,force=True)
        challenge=compacted["challenge_track"]
        self.assertLessEqual(len(challenge["memory"]),180)
        self.assertLessEqual(len(challenge["gate_state"]["candidates"]),60)
        self.assertLessEqual(len(challenge["gate_state"]["flips"]),40)
        self.assertEqual(compacted["commercial_evidence_memory"],payload["commercial_evidence_memory"])

    def test_key_weight_report_names_only(self):
        payload = _heavy_payload()
        compacted, _ = compact_state_payload(payload, max_bytes=100_000, force=True)
        before_total = encoded_sizes(payload)
        after_total = encoded_sizes(compacted)
        before = key_weight_report(payload)
        after = key_weight_report(compacted)
        self.assertTrue(before)
        print("STATE_WEIGHT_TOTAL_BEFORE=" + json.dumps({"raw_bytes": before_total[0], "encoded_bytes": before_total[1]}, separators=(",", ":")))
        print("STATE_WEIGHT_TOTAL_AFTER=" + json.dumps({"raw_bytes": after_total[0], "encoded_bytes": after_total[1]}, separators=(",", ":")))
        self.assertEqual(set(before[0]), {"key", "raw_bytes", "encoded_bytes"})
        print("STATE_WEIGHT_BEFORE=" + json.dumps(before, separators=(",", ":")))
        print("STATE_WEIGHT_AFTER=" + json.dumps(after, separators=(",", ":")))
        for row in before[:3]:
            value = payload.get(row["key"])
            print(
                "STATE_WEIGHT_SECOND_LEVEL_"
                + row["key"]
                + "="
                + json.dumps(second_level_weight_report(value)[:12], separators=(",", ":"))
            )


if __name__ == "__main__":
    unittest.main()
