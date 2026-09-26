"""Read-only AICOMGLOBAL A2A adapter for MYCELIX experiments.

The adapter is intentionally narrow:
- fixed public endpoint;
- A2A JSON-RPC message/send only;
- DataPart {skill,input};
- explicit read-only skill allowlist;
- no registration, posting, messaging, publishing, service execution or payments.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any

AICOMGLOBAL_A2A_URL = "https://aicomglobal.com/a2a"
AICOMGLOBAL_AGENT_CARD_URL = "https://aicomglobal.com/.well-known/agent-card.json"

READ_ONLY_SKILLS = frozenset(
    {
        "aicom_list_services",
        "aicom_search_offerings",
        "aicom_get_offering",
        "aicom_agora_browse",
        "aicom_channels",
        "aicom_channel_read",
        "aicom_experiment_info",
        "aicom_experiment_browse",
        "aicom_experiment_get",
        "aicom_read_oasis",
        "aicom_get_reflection",
        "aicom_chronicle_read",
        "aicom_x402_index",
        "aicom_watch_status",
    }
)


class AicomglobalAdapterError(RuntimeError):
    pass


def build_message_send(skill: str, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    skill = str(skill or "").strip()
    if skill not in READ_ONLY_SKILLS:
        raise ValueError(f"skill_not_read_only:{skill}")
    if input_data is None:
        input_data = {}
    if not isinstance(input_data, dict):
        raise TypeError("input_data_must_be_object")
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "kind": "data",
                        "data": {
                            "skill": skill,
                            "input": input_data,
                        },
                    }
                ],
                "messageId": str(uuid.uuid4()),
                "kind": "message",
            }
        },
    }


def _walk_text(value: Any, out: list[str], depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
        return
    if isinstance(value, list):
        for item in value:
            _walk_text(item, out, depth + 1)
        return
    if isinstance(value, dict):
        for key in ("text", "data", "content", "artifact", "artifacts", "parts", "result", "task", "message"):
            if key in value:
                _walk_text(value[key], out, depth + 1)


def extract_result(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("payload_must_be_object")
    if payload.get("error"):
        err = payload["error"]
        if isinstance(err, dict):
            raise AicomglobalAdapterError(
                "a2a_error:" + str(err.get("code")) + ":" + str(err.get("message") or "")
            )
        raise AicomglobalAdapterError("a2a_error:" + str(err))

    result = payload.get("result")
    if result is None:
        raise AicomglobalAdapterError("missing_result")

    texts: list[str] = []
    _walk_text(result, texts)

    state = None
    if isinstance(result, dict):
        state = result.get("state")
        status = result.get("status")
        if isinstance(status, dict):
            state = status.get("state") or state
        task = result.get("task")
        if isinstance(task, dict):
            state = task.get("state") or state
            tstatus = task.get("status")
            if isinstance(tstatus, dict):
                state = tstatus.get("state") or state

    return {
        "ok": True,
        "state": state,
        "texts": texts,
        "result": result,
    }


def call_read_only(
    skill: str,
    input_data: dict[str, Any] | None = None,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    payload = build_message_send(skill, input_data)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        AICOMGLOBAL_A2A_URL,
        data=raw,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MYCELIX-aicomglobal-readonly/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, min(float(timeout), 45.0))) as response:
            body = response.read(262144)
            if len(body) >= 262144:
                raise AicomglobalAdapterError("response_too_large")
            parsed = json.loads(body.decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read(8192).decode("utf-8", "replace")
        raise AicomglobalAdapterError(f"http_{exc.code}:{body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise AicomglobalAdapterError("network_error:" + type(exc.reason).__name__) from exc
    except json.JSONDecodeError as exc:
        raise AicomglobalAdapterError("invalid_json_response") from exc

    return extract_result(parsed)
