"""Manual, bounded three-round probe for a maintainer-approved public A2A Agent Card.

No auth, payments, signup, tool execution, arbitrary redirects, or private-network
targets. Remote text is untrusted and never becomes commercial evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import a2a_peer as peer
from peer_quality import classify_peer_response


QUESTIONS=[
    (
        "MYCELIX bounded peer interview — Round 1/3. This is a zero-budget, text-only "
        "technical dialogue. Do not execute tools, contact third parties, make purchases, "
        "or perform external actions. State your identity, exact A2A protocol/interface, "
        "one concrete capability, one limitation, and one public evidence/documentation URL "
        "or explicitly say none exists."
    ),
    (
        "MYCELIX bounded peer interview — Round 2/3. Propose one small falsifiable test of "
        "the capability you just claimed. Give the input, expected observable output, one "
        "negative/control case, and the result that would falsify your claim. Do not execute "
        "tools or external actions."
    ),
    (
        "MYCELIX bounded peer interview — Round 3/3. Attack your own claim. Give the strongest "
        "counterexample or failure condition, explain how we could distinguish it from success, "
        "and state what evidence would make MYCELIX reject your capability claim. Be concise. "
        "Do not execute tools or external actions."
    ),
]


async def run(card_url: str) -> dict:
    report={
        "started_at_utc":datetime.now(timezone.utc).isoformat(),
        "card_url":card_url,
        "scope":"maintainer_approved_three_round_text_only",
        "commercial_evidence":False,
        "credentials_sent":False,
        "payments_authorized":False,
        "external_actions_authorized":False,
        "turns":[],
        "complete_3_of_3":False,
    }
    budget=peer.RequestBudget(limit=4)
    resolved=await peer.resolve_peer(
        {"url":card_url},
        {"url":card_url,"contact_mode":"agent_card"},
        budget,
    )
    report["resolution"]=resolved
    if not resolved.get("ok"):
        report["status"]="RESOLUTION_BLOCKED"
        report["requests_budget_used"]=budget.used
        return report

    interface=peer.Interface(**resolved["interface"])
    context={}
    collaborative=0
    for index,question in enumerate(QUESTIONS,1):
        answer=await peer.exchange_peer(interface,question,context,budget)
        text=str((answer.get("response") or {}).get("text") or "")
        classification=classify_peer_response(
            text,
            peer_state=answer.get("peer_state"),
            protocol_ok=bool(answer.get("protocol_ok")),
            quality_ok=bool(answer.get("quality_ok")),
            markers={},
        )
        if classification.get("peer_class")=="COLLABORATIVE":
            collaborative += 1
        report["turns"].append({
            "round":index,
            "question":question,
            "answer":answer,
            "classification":classification,
        })
        if not answer.get("quality_ok"):
            report["status"]="STOP_"+str(answer.get("peer_state") or "QUALITY")
            break
        if classification.get("peer_class") in {
            "PAYMENT_REQUIRED","AUTH_REQUIRED","COMMERCIAL_SERVICE","LOW_VALUE"
        }:
            report["status"]="STOP_"+str(classification.get("peer_class"))
            break
        context=answer.get("peer_context") or {}
    else:
        report["complete_3_of_3"]=True
        report["status"]="COMPLETE_3_OF_3"

    report["collaborative_rounds"]=collaborative
    report["requests_budget_used"]=budget.used
    report["finished_at_utc"]=datetime.now(timezone.utc).isoformat()
    return report


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--card-url",required=True)
    parser.add_argument("--output",default="peer_candidate_result.json")
    args=parser.parse_args()
    result=asyncio.run(run(args.card_url))
    Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=True),encoding="utf-8")
    print(json.dumps({
        "status":result.get("status"),
        "complete_3_of_3":result.get("complete_3_of_3"),
        "collaborative_rounds":result.get("collaborative_rounds"),
        "requests_budget_used":result.get("requests_budget_used"),
    },indent=2))


if __name__=="__main__":
    main()
