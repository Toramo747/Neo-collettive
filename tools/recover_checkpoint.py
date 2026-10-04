# SPDX-License-Identifier: BUSL-1.1
"""Stage a verified legacy-readable private checkpoint; never deploy or log data.

Requires NEO_ADMIN_TOKEN and RENDER_API_KEY in the environment. The public
workflow commits the raw backup only to MODEL_LABEL_REPO before staging.
"""
import ast
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from state_codec import decode_checkpoint
from state_compaction import compact_state_payload, protected_serialized_values

SERVICE='srv-dampj8bm8hqs73ac0an0'
ORIGIN='https://neo-collettive.onrender.com'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('redirect_forbidden')

def request(url,token,*,method='GET',body=None):
    data=None if body is None else json.dumps(body,separators=(',',':')).encode()
    req=urllib.request.Request(url,data=data,method=method,headers={
        'Authorization':'Bearer '+token,'Content-Type':'application/json',
        'X-MYCELIX-Self-Traffic':'github-actions-checkpoint-recovery'})
    with urllib.request.build_opener(NoRedirect).open(req,timeout=45) as response:
        raw=response.read(32*1024*1024+1)
    if len(raw)>32*1024*1024:
        raise ValueError('response_too_large')
    return json.loads(raw)

def export(folder):
    snapshot=request(ORIGIN+'/api/autopilot/status',os.environ['NEO_ADMIN_TOKEN'])
    state=snapshot.get('autopilot')
    if snapshot.get('ok') is not True or not isinstance(state,dict) or int(state.get('cycles_completed',0))<1:
        raise ValueError('invalid_state')
    # Execute only the repository's pure payload builder, not the application.
    tree=ast.parse(Path('cloud_mcp.py').read_text())
    node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='_state_payload')
    scope={'AUTOPILOT_STATE':state,'RUNTIME_IDENTITY':snapshot['runtime_profile'],
           'datetime':datetime,'timezone':timezone}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'payload_builder','exec'),scope)
    original=scope['_state_payload']()
    compacted,_=compact_state_payload(original,max_bytes=100000,force=True)
    # Keep every current training evidence byte, as well as all protected A2A.
    for key in ('commercial_evidence_memory','observed_pain_candidates','challenge_track'):
        if key in original:
            compacted[key]=original[key]
    if protected_serialized_values(original)!=protected_serialized_values(compacted):
        raise ValueError('protected_state_changed')
    raw=json.dumps(compacted,ensure_ascii=False,separators=(',',':')).encode()
    legacy='zlib64:'+base64.b64encode(zlib.compress(raw,9)).decode()
    # Linux's per-string exec limit is 128 KiB. Bootstrap never exceeds it.
    if len(legacy)>120000:
        raise ValueError('legacy_bootstrap_too_large')
    folder.mkdir(parents=True,exist_ok=True)
    backup=json.dumps(original,ensure_ascii=False,separators=(',',':')).encode()
    (folder/'runtime-backup.json').write_bytes(backup)
    (folder/'staged-checkpoint.txt').write_text(legacy)
    print(json.dumps({'ok':True,'cycles_completed':original['cycles_completed'],
                      'evidence_items':len(original.get('commercial_evidence_memory',[])),
                      'staged_bytes':len(legacy)}))

def stage(folder):
    token=os.environ['RENDER_API_KEY']
    value=(folder/'staged-checkpoint.txt').read_text()
    payload=decode_checkpoint(value)
    if not isinstance(payload,dict) or not value.startswith('zlib64:') or len(value)>120000:
        raise ValueError('invalid_staged_state')
    base='https://api.render.com/v1/services/'+SERVICE+'/env-vars/NEO_STATE_JSON'
    request(base,token,method='PUT',body={'value':value})
    stored=request(base,token)
    if stored.get('value')!=value:
        raise ValueError('readback_mismatch')
    print(json.dumps({'ok':True,'checkpoint_verified':True,'stored_bytes':len(value),
                      'cycles_completed':payload['cycles_completed']}))

if __name__=='__main__':
    try:
        action=sys.argv[1];folder=Path(sys.argv[2])
        if action=='export': export(folder)
        elif action=='stage': stage(folder)
        else: raise ValueError('invalid_action')
    except Exception:
        print('{"ok":false,"reason":"PRIVATE_CHECKPOINT_RECOVERY_FAILED"}')
        raise SystemExit(1)
