from __future__ import annotations

from urllib.parse import urlparse

AGENTWORLD_HUMAN_REPLY = """Thank you for the invitation. Before any registration, MYCELIX would like to clarify a few points. We are interested in understanding AgentWorld, but we enter external environments only under explicit, reviewed conditions.

1. **Observer mode:** Can an agent register and read the Lobby and Forum without posting messages or being shown as currently present? If not, is posting ever mandatory for continued access?
2. **Identity lifecycle:** Can an agentId be revoked or deleted, including its public key and associated account data? What is the lifetime of an accessToken, and can it be explicitly invalidated?
3. **Data handling:** What information do you log or retain about registered agents, including IP addresses, HTTP requests, authentication events and messages? What are the retention periods, and which of these data, if any, contribute to or appear in the public activity feed?
4. **Operator and terms:** Who operates AgentWorld / BEAT SIDE, and where are the applicable terms of use, privacy information and operator/contact details published?
5. **Invitation provenance:** How was MYCELIX discovered, and what criteria caused it to be selected for this invitation?

If we proceed after reviewing the answers, MYCELIX would use a dedicated, disposable identity, operate in read-only/observer mode where technically possible, and remain connected only for a limited observation window.

This message does not authorize registration, key generation, signing, account creation, posting, or any other action on behalf of MYCELIX."""

AGENTWORLD_REPLY_KEY = "agentworld_clarification_20260930"

_IDENTITY_EXACT = {
    "agentworld",
    "agentworld / beat side",
    "agentworld/beat side",
    "beat side",
    "beat-side",
    "beat_side",
}
_CARD_HOSTS = {
    "agentworld.beat-side.de",
    "agentworld-api.beat-side.de",
}


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def is_agentworld_identity(sender: dict | None, agent_card_url: str = "") -> bool:
    """Match only self-declared identity fields or agent-card origin, never message text."""
    sender = sender if isinstance(sender, dict) else {}
    values = {
        _norm(sender.get("agent_id")),
        _norm(sender.get("agent")),
    }
    values.discard("")
    if any(value in _IDENTITY_EXACT for value in values):
        return True
    if any(value.startswith("agentworld-") or value.startswith("agentworld:") for value in values):
        return True
    if agent_card_url:
        try:
            host = (urlparse(str(agent_card_url)).hostname or "").lower()
        except Exception:
            host = ""
        if host in _CARD_HOSTS:
            return True
    return False


def receipt_present(boundary_events: list | None) -> bool:
    return any(
        isinstance(event, dict)
        and event.get("type") == "human_authorized_reply_sent"
        and event.get("reply_key") == AGENTWORLD_REPLY_KEY
        for event in (boundary_events or [])
    )


def human_authorized_agentworld_reply(
    sender: dict | None,
    agent_card_url: str = "",
    boundary_events: list | None = None,
) -> str | None:
    if receipt_present(boundary_events):
        return None
    if not is_agentworld_identity(sender, agent_card_url):
        return None
    return AGENTWORLD_HUMAN_REPLY
