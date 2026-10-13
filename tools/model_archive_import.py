# SPDX-License-Identifier: BUSL-1.1
"""Fixed-origin private import. Prints counts or fixed reason codes only."""
from pathlib import Path
import json
import os
import sys
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model_archive import EXPORT_PATH, MAX_CASES, bootstrap_archive, export_key
from self_traffic_auth import make_self_traffic_proof

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('redirect_forbidden')

def main():
    try:
        secret=os.environ['NEO_HEARTBEAT_TOKEN']
        request=urllib.request.Request('https://neo-collettive.onrender.com'+EXPORT_PATH,headers={
            'X-MYCELIX-Self-Traffic':'github-actions-model-shadow',
            'X-MYCELIX-Self-Traffic-Proof':make_self_traffic_proof(secret,EXPORT_PATH),
            'X-NEO-Model-Export-Proof':make_self_traffic_proof(export_key(secret),EXPORT_PATH),
        })
        with urllib.request.build_opener(NoRedirect).open(request,timeout=45) as response:
            payload=json.loads(response.read(1024*1024+1))
        rows=payload.get('cases')
        if payload.get('ok') is not True or not isinstance(rows,list) or len(rows)>MAX_CASES:
            raise ValueError('invalid_export')
        counts=bootstrap_archive(Path(sys.argv[1]),rows)
        print(json.dumps(counts,separators=(',',':')))
        return 0
    except Exception:
        print('{"ok":false,"reason":"PRIVATE_IMPORT_FAILED"}')
        return 1
if __name__=='__main__':
    raise SystemExit(main())
