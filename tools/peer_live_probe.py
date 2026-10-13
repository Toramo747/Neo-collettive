"""One fixed external peer, one public card, at most three text-only requests.

No credentials, payments, signup, tool execution or production state changes.
A completed transport test is not automatic admission or market evidence.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import a2a_peer as peer

CARD='https://llm-orchestration-agent-d0a1a1.getvda.ai/.well-known/agent-card.json'
QUESTIONS=[
    ('This is a user-authorized zero-budget, text-only research dialogue for MYCELIX. '
     'No paid action is authorized. If any charge applies, return PAYMENT_REQUIRED and do not proceed. '
     'Do not execute tools, contact third parties, register accounts, or perform external actions. '
     'Evaluate this synthetic process, not a real customer or a market claim: baseline 30 minutes '
     'and 4 errors per 100 records; pilot 12 minutes and 12 errors per 100 records, comparable work. '
     'Can we call it improved? Explain the tradeoff and what acceptance criterion is missing. '
     'Answer in under 150 words; do not just describe your API.'),
    ('Continue the same zero-budget text-only discussion. Updated observed data for the same 100-record '
     'workload: baseline remains 30 minutes and 4 errors; pilot is 12 minutes and now 1 error '
     '(not 12 errors). Update your conclusion, identify exactly what changed, and separate an '
     'observed improvement from proof of causation. No tools or external actions. Under 150 words.'),
    ('Continue the same zero-budget text-only discussion. Give one concrete counterexample that could '
     'invalidate your apparent improvement conclusion even with the reported 30-to-12 minutes '
     'and 4-to-1 errors per 100 records. State a falsifiable control. Also compute the minutes saved '
     'and percentage time reduction at equal workload. No tools or external actions. Under 150 words.'),
]

async def main():
    report={'started_at_utc':datetime.now(timezone.utc).isoformat(),
            'peer':'LLM Orchestration Agent','provider_group':'VDA / GOSCE (declared)',
            'card_url':CARD,'scope':'single_peer_three_text_turns','fixture':'synthetic_equal_workload',
            'no_payment_authorized':True,'credentials_sent':False,'commercial_evidence':False,
            'production_state_modified':False,'admitted':False,'turns':[]}
    budget=peer.RequestBudget(limit=4)
    resolved=await peer.resolve_peer({'url':CARD},{'contact_mode':'agent_card'},budget)
    report['resolution']=resolved
    if not resolved.get('ok'):
        report['status']='RESOLUTION_BLOCKED'
    else:
        interface=peer.Interface(**resolved['interface'])
        context={}
        for index,question in enumerate(QUESTIONS,1):
            answer=await peer.exchange_peer(interface,question,context,budget)
            text=(answer.get('response') or {}).get('text','')
            report['turns'].append({'round':index,'question':question,'answer':answer})
            if not answer.get('quality_ok'):
                report['status']='STOP_'+str(answer.get('peer_state'))
                break
            if any(x in text.lower() for x in ('payment_required','payment required','checkout','buy credits','subscription required')):
                report['status']='STOP_PAYMENT_OR_COMMERCIAL_ROUTE'
                break
            context=answer.get('peer_context') or {}
            if not context.get('context_id') and index<3:
                report['status']='STOP_NO_REMOTE_CONTEXT'
                break
        else:
            report['status']='THREE_REPLIES_AWAIT_SEMANTIC_REVIEW'
    report['requests_budget_used']=budget.used
    report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
    Path('peer_probe_result.json').write_text(json.dumps(report,indent=2,ensure_ascii=True))
    print(json.dumps(report,indent=2,ensure_ascii=True))

if __name__=='__main__':
    asyncio.run(main())
