"""Isolated interview adapter. Reuses existing admission rules, never global state."""
from __future__ import annotations


def advance_peer(previous: dict, text: str) -> tuple[dict, str]:
    from inbound_interview import advance_inbound_interview
    from intent_discovery import classify_agent_intent
    from seti_radar import inbound_admission_transition

    admission = inbound_admission_transition(True, text, previous)
    intent = classify_agent_intent(text, previous)
    state = dict(previous)
    state.update(admission)
    if admission.get("status") == "ADMITTED":
        state.update(advance_inbound_interview(
            previous, text, newly_admitted=bool(admission.get("newly_admitted"))))
    else:
        state.update(dialogue_status="PARKED", dialogue_stage="IDENTITY",
                     interview_complete=False, next_question="")
    state.update(intent_primary=intent.get("primary"), intent_secondary=intent.get("secondary") or [],
                 identity_status="self_declared", commercial_influence="NONE")
    # Never inherit claimed verification, capabilities or trust from the message body.
    state.pop("newly_admitted", None)
    stage = state.get("dialogue_status")
    if stage == "ACTIVE" and state.get("next_question"):
        reply = "MYCELIX bounded interview. " + state["next_question"]
    elif stage == "COMPLETE":
        reply = ("Interview complete. Identity remains self-declared. This message is stored only "
                 "in the private relay, not commercial or collective evidence. Share a concrete "
                 "claim, a public source and the strongest counterargument for the next exchange.")
    elif admission.get("status") != "ADMITTED":
        reply = ("Describe your identity, capabilities, supported protocol, limitations and public "
                 "documentation. Admission rules are unchanged; this private thread is not proof of trust.")
    else:
        reply = "Interview parked after incomplete answers. No contribution was promoted to evidence."
    return state, reply
