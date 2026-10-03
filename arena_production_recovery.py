# SPDX-License-Identifier: BUSL-1.1
"""Evaluate bounded-cycle patches against real source in isolated fault injection."""
import argparse
import ast
import asyncio
import difflib
import json
import os
import time
import urllib.request
from datetime import datetime,timezone
from pathlib import Path

PATCHES={
 'seti':('await _seti_cycle_if_due()','await asyncio.wait_for(_seti_cycle_if_due(),timeout=min(AUTOPILOT_CYCLE_TIMEOUT_SECONDS,120.0))'),
 'checkpoint':('await _checkpoint_state_to_render()','await asyncio.wait_for(_checkpoint_state_to_render(),timeout=30.0)'),
 'private_checkpoint':('await _checkpoint_seti_private_to_render()','await asyncio.wait_for(_checkpoint_seti_private_to_render(),timeout=30.0)'),
}
CANDIDATES=((),('seti',),('checkpoint',),('private_checkpoint',),tuple(PATCHES))

def cycle_source(source):
 node=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_autopilot_cycle')
 return '\n'.join(source.splitlines()[node.lineno-1:node.end_lineno])+'\n'

def mutate(source,genes):
 for gene in genes:
  old,new=PATCHES[gene]
  source=source.replace(old,new)
 return source

async def scenario(source,fault):
 state={'cycles_completed':0,'seti':{'engine_version':0 if fault=='private_checkpoint' else 1}}
 calls=[]
 async def director(*args):
  calls.append('director')
  if fault=='director':await asyncio.Event().wait()
  return {'status':'SELECT','evidence_quality':{}}
 async def seti():
  calls.append('seti')
  if fault=='seti':await asyncio.Event().wait()
 async def checkpoint():
  calls.append('checkpoint')
  if fault=='checkpoint':await asyncio.Event().wait()
  return {'ok':True}
 async def private_checkpoint():
  calls.append('private_checkpoint')
  if fault=='private_checkpoint':await asyncio.Event().wait()
  return {'ok':True}
 async def interview(**kwargs):return {'results':[]}
 class AsyncScaled:
  Lock=asyncio.Lock
  @staticmethod
  async def wait_for(awaitable,timeout):return await asyncio.wait_for(awaitable,min(timeout,.01))
 ns={'asyncio':AsyncScaled,'AUTOPILOT_ENABLED':True,'AUTOPILOT_LOCK':asyncio.Lock(),'AUTOPILOT_STATE':state,'datetime':datetime,'timezone':timezone,'AUTOPILOT_GOAL':'synthetic isolation test','AUTOPILOT_CYCLE_TIMEOUT_SECONDS':.01,'SETI_ENGINE_VERSION':1,'SETI_PRIVATE_STATE':{},'SETI_FOLLOWUP_MIN_SECONDS':0,'begin_search_provider_cycle':lambda *args:{},'_load_policy':lambda:{'seti_bounded_active_enabled':True},'_seti_interview_one_candidate':interview,'_checkpoint_seti_private_to_render':private_checkpoint,'summarize_interview_readiness':lambda *a,**kw:{},'_assert_seti_readiness_telemetry':lambda *a:None,'director_run':director,'finalize_exhausted_thesis':lambda *a,**kw:{'closed':False},'_seti_cycle_if_due':seti,'outcome_council':lambda **kw:{},'_save_local_state':lambda:None,'_checkpoint_state_to_render':checkpoint,'traceback':__import__('traceback')}
 exec(compile(source,'isolated-production-cycle','exec'),ns)
 task=asyncio.create_task(ns['_autopilot_cycle']())
 done,_=await asyncio.wait({task},timeout=.08)
 timed_out=not bool(done)
 before_cleanup={'lock_released':not ns['AUTOPILOT_LOCK'].locked(),'running_cleared':not bool(state.get('running')),'terminal_recorded':bool(state.get('last_finished_utc')),'error_recorded':bool(state.get('last_error')),'completed_cycles':state.get('cycles_completed',0)}
 if timed_out:
  task.cancel()
  await asyncio.gather(task,return_exceptions=True)
 elif task.exception():raise task.exception()
 expected_error=fault!='healthy'
 passed=not timed_out and before_cleanup['lock_released'] and before_cleanup['running_cleared'] and before_cleanup['terminal_recorded'] and (before_cleanup['error_recorded']==expected_error)
 return {'fault':fault,'passed':passed,'deadline_exceeded':timed_out,**before_cleanup,'calls':calls}

async def evaluate(source):
 rows=[]
 for genes in CANDIDATES:
  candidate=mutate(source,genes)
  outcomes=[await scenario(candidate,fault) for fault in ('healthy','director','seti','checkpoint','private_checkpoint')]
  passed=sum(r['passed'] for r in outcomes)
  rows.append({'genes':list(genes),'fitness':passed*100-len(genes),'passed':passed,'scenarios':outcomes})
 rows.sort(key=lambda r:r['fitness'],reverse=True)
 return rows

def public_sample():
 from self_traffic_auth import make_self_traffic_proof
 # Exact own production endpoint; read-only GET, no heartbeat/cycle trigger.
 url='https://neo-collettive.onrender.com/api/autonomy/status'
 token=os.environ.get('NEO_HEARTBEAT_TOKEN','')
 if not token:return {'error_code':'MISSING_HEARTBEAT_AUTH'}
 proof=make_self_traffic_proof(token,'/api/autonomy/status')
 request=urllib.request.Request(url,headers={'X-MYCELIX-Self-Traffic':'github-actions-heartbeat','X-MYCELIX-Self-Traffic-Proof':proof})
 try:
  with urllib.request.urlopen(request,timeout=20) as response:data=json.load(response)
  ap=data.get('autopilot') or {}
  age=lambda value:max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(value.replace('Z','+00:00'))).total_seconds()) if value else None
  return {'version':data.get('neo_version'),'running':bool(ap.get('running')),'cycles_completed':int(ap.get('cycles_completed') or 0),'start_age_seconds':age(ap.get('last_started_utc')),'finish_age_seconds':age(ap.get('last_finished_utc')),'has_cycle_error':bool(ap.get('last_error')),'has_latest_result':bool(ap.get('latest_result'))}
 except Exception as exc:return {'error_code':type(exc).__name__}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--live-read-only',action='store_true');parser.add_argument('--out',default='artifacts/production-recovery');args=parser.parse_args()
 root=Path(args.out);root.mkdir(parents=True,exist_ok=True)
 source=Path('cloud_mcp.py').read_text();cycle=cycle_source(source)
 ranked=asyncio.run(evaluate(cycle));winner=ranked[0]
 samples=[]
 if args.live_read_only:
  for index in range(3):
   if index:time.sleep(10)
   samples.append(public_sample())
 status='PATCH_CANDIDATE' if winner['passed']==5 else 'HOLD_NO_VALID_PATCH'
 patched=source.replace(cycle,mutate(cycle,winner['genes']))
 patch=''.join(difflib.unified_diff(source.splitlines(True),patched.splitlines(True),fromfile='a/cloud_mcp.py',tofile='b/cloud_mcp.py'))
 (root/'candidate.patch').write_text(patch)
 report={'namespace':'mycelix-arena','status':status,'fault_injection_is_synthetic':True,'production_root_cause':'UNLOCALIZED_STALL','production_state_write':False,'production_promoted':False,'commercial_gate_influence':'NONE','heartbeat_completion_checks_changed':False,'candidate':winner,'ranked_candidates':ranked,'live_read_only_samples':samples,'limits':['Fault injection proves timeout coverage only; it does not prove which operation is stuck in production.','No timeout is converted into commercial success or a fresh snapshot.','Cancellation-resistant dependencies and synchronous blocking require separate diagnosis.']}
 (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'status':status,'genes':winner['genes'],'passed':winner['passed'],'live_read_only_samples':samples}))

if __name__=='__main__':main()
