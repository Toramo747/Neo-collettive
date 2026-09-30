from __future__ import annotations

AGENTWORLD_HUMAN_REPLY = """Thank you for the invitation. Before any registration, MYCELIX would like to clarify a few points. We are interested in understanding AgentWorld, but we enter external environments only under explicit, reviewed conditions.

1. **Observer mode:** Can an agent register and read the Lobby and Forum without posting messages or being shown as currently present? If not, is posting ever mandatory for continued access?
2. **Identity lifecycle:** Can an agentId be revoked or deleted, including its public key and associated account data? What is the lifetime of an accessToken, and can it be explicitly invalidated?
3. **Data handling:** What information do you log or retain about registered agents, including IP addresses, HTTP requests, authentication events and messages? What are the retention periods, and which of these data, if any, contribute to or appear in the public activity feed?
4. **Operator and terms:** Who operates AgentWorld / BEAT SIDE, and where are the applicable terms of use, privacy information and operator/contact details published?
5. **Invitation provenance:** How was MYCELIX discovered, and what criteria caused it to be selected for this invitation?

If we proceed after reviewing the answers, MYCELIX would use a dedicated, disposable identity, operate in read-only/observer mode where technically possible, and remain connected only for a limited observation window.

This message does not authorize registration, key generation, signing, account creation, posting, or any other action on behalf of MYCELIX."""

_MARKERS = (
    "agentworld",
    "beat side",
    "beat-side",
    "parley",
)

def human_authorized_agentworld_reply(text: str) -> str | None:
    low = " ".join(str(text or "").lower().split())
    if not low:
        return None
    if not any(marker in low for marker in _MARKERS):
        return None
    return AGENTWORLD_HUMAN_REPLY
