# SPDX-License-Identifier: BUSL-1.1
"""Bounded private shadow archive export; never used by decision gates."""
from __future__ import annotations
import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

EXPORT_PATH='/api/model-shadow/private-cases'
MAX_CASES=100
SIGNAL_KEYS=('path_code','source_type','close_reason','accepted_answer','pricing_page',
             'job_board','resolved','feature_request','help_wanted','duplicate_count',
             'reaction_count','requester_key','feasibility')


def export_key(secret: str) -> str:
    return hmac.new(secret.encode(),b'neo:model-shadow:private-export:v1',hashlib.sha256).hexdigest()


def private_cases(state: dict) -> list[dict]:
    rows=list(state.get('commercial_evidence_memory') or [])
    rows+=list((state.get('challenge_track') or {}).get('memory') or [])
    out=[]
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or row.get('synthetic') or row.get('test_only'):
            continue
        source=str(row.get('source') or '')[:200]
        if any(x in source.lower() for x in ('synthetic','fixture','smoke','mock')):
            continue
        url=str(row.get('url') or '')[:1200]
        parsed=urlsplit(url)
        if parsed.scheme not in {'https','http'} or not parsed.hostname:
            continue
        text=' '.join((str(row.get('title') or '')+' '+str(row.get('snippet') or row.get('body') or '')).split())[:4000]
        if not text:
            continue
        case_id=hashlib.sha256((url+'\n'+text).encode()).hexdigest()[:24]
        if case_id in seen:
            continue
        seen.add(case_id)
        raw=row.get('structural_signals') if isinstance(row.get('structural_signals'),dict) else row
        signals={k:raw[k] for k in SIGNAL_KEYS if k in raw and isinstance(raw[k],(str,int,float,bool))}
        out.append({'id':case_id,'normalized_text':text,'title':str(row.get('title') or '')[:300],
                    'source':source,'url':url,'structural_signals':signals,
                    'date':datetime.now(timezone.utc).isoformat(),'label_origin':'','final_label':''})
        if len(out)>=MAX_CASES:
            break
    return out


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def bootstrap_archive(folder: Path, incoming: list[dict]) -> dict:
    folder.mkdir(parents=True,exist_ok=True)
    # Existing held-out sets are never written by this importer.
    public=read_rows(folder/'public.jsonl')
    hidden=read_rows(folder/'hidden.jsonl')
    reserved={str(x.get('id') or '') for x in public+hidden}
    train=read_rows(folder/'train.jsonl')
    known={str(x.get('id') or '') for x in train}
    added=0
    for row in incoming:
        key=str(row.get('id') or '')
        if key and key not in known and key not in reserved:
            train.append(row)
            known.add(key)
            added+=1
    (folder/'train.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in train))
    for name in ('public.jsonl','hidden.jsonl'):
        path=folder/name
        if not path.exists():
            path.touch()
    (folder/'ARCHIVE_GUIDE.md').write_text('''# Private model shadow archive

train.jsonl contains unlabelled real observations imported from NEO; independent judges may label these.
public.jsonl is a separate reference evaluation set. It must contain reviewed reference labels.
hidden.jsonl must be written and labelled by Andrea only, with label_origin: human.
Import never modifies existing evaluation files or inserts their IDs into training.

Each JSONL record requires id, normalized_text, source, structural_signals, date.
Evaluation also requires final_label and label_origin. Labels: buyer_tool_search,
vendor_offer, manual_recurring_work, job_posting, other.
Empty evaluation sets block promotion. Never copy held-out cases to training.
No raw records, text, sources or URLs may be printed to public Actions logs/artifacts.
''')
    return {'imported_cases':added,'train_cases':len(train),'public_cases':len(public),'hidden_cases':len(hidden)}
