import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import decision_replay as dr
from price_validation import compact_price_evidence, persisted_price_groups
from public_snapshot import sanitize_public_snapshot


def receipt():
    cache=compact_price_evidence([{'query':'prices','family':'ai_tools'}], [
        {'query':'prices','results':[{'url':f'https://vendor{i}.invalid/pricing',
          'title':'AI agent pricing','snippet':'AI agent plan USD 20 per month'} for i in range(2)]}])
    groups=persisted_price_groups(cache)
    meta={g['query']:{'query':g['query'],'class':'tool_market_validation','role':'price_validation',
          'family':'ai_tools','query_intent':'persisted_verified_competitor_price','validation_kind':'persisted_strict'} for g in groups}
    trace=dr.begin(web_research=groups,query_meta=meta,
        demand_evidence=[{'family':'ai_tools','url':'https://buyer.invalid/pain',
          'title':'AI agent missing feature','text':'AI agent too expensive and missing feature.'}],
        seti_catalog=[],price_cache=cache,persisted_insert_at=0,source_diagnostics={},usage_evidence={},
        hysteresis={},now='2026-10-08T12:00:00+00:00',cycle=42,first_cycle_after_deploy=True,
        commit='a'*40,version='0.99.54',tagger_version='3',policy_version=1,genome_id='fixture',guards={})
    trace['output']=dr.evaluate(trace['inputs'])
    trace['input_hash']=dr.digest(trace['inputs'])
    trace['output_hash']=dr.digest(trace['output'])
    trace['replay_ok']=True
    return trace


class DecisionReplayTests(unittest.TestCase):
    def test_captured_inputs_replay_identically_and_buffer_survives_restart(self):
        trace=receipt()
        self.assertTrue(dr.replay(trace)['identical'])
        with tempfile.TemporaryDirectory() as d:
            b=dr.TraceBuffer(d)
            for n in range(23):
                t=copy.deepcopy(trace)
                t['cycle']=t['inputs']['cycle']=n
                t['input_hash']=dr.digest(t['inputs'])
                b.save(t)
            self.assertEqual(len(b.paths()),20)
            restored=dr.TraceBuffer(d)
            self.assertEqual(restored.public()['last_trace_cycle'],22)
            self.assertEqual(os.stat(restored.paths()[-1]).st_mode & 0o777,0o600)
            self.assertEqual(os.stat(d).st_mode & 0o777,0o700)
            with self.assertRaises(ValueError): restored.read('../secret')

    def test_different_hash_seeds_same_output(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.json';p.write_text(json.dumps(receipt()['inputs']))
            code='import json,sys,decision_replay as d;print(d.digest(d.evaluate(json.load(open(sys.argv[1])))))'
            hashes=[subprocess.check_output([sys.executable,'-c',code,str(p)],env={**os.environ,'PYTHONHASHSEED':str(n)},text=True).strip() for n in (1,17,951)]
            self.assertEqual(len(set(hashes)),1, 'hash-seed divergence: document; do not fix scoring')

    def test_changed_price_cache_reports_field_diff_and_integrity_is_enforced(self):
        trace=receipt()
        trace['inputs']['price_cache']=[]
        with self.assertRaises(ValueError): dr.replay(trace)
        trace['input_hash']=dr.digest(trace['inputs']) # explicit controlled counterfactual
        result=dr.replay(trace)
        self.assertFalse(result['identical'])
        self.assertTrue(any('competitors_with_real_price' in p for p in result['diff']))
        self.assertTrue(any('missing_codes' in p for p in result['diff']))

    def test_private_buffer_cannot_change_checkpoint_bytes(self):
        import cloud_mcp as runtime
        from state_codec import encode_checkpoint
        with tempfile.TemporaryDirectory() as d, patch.object(dr,'BUFFER',dr.TraceBuffer(d)), \
             patch.object(runtime.OBSERVATION,'private_snapshot',return_value={}):
            before=runtime._state_payload()
            dr.BUFFER.save(receipt())
            after=runtime._state_payload()
            # Only the real checkpoint's clock changes between calls.
            after['state_saved_at_utc']=before['state_saved_at_utc']
            self.assertEqual(encode_checkpoint(before,100000)[0],encode_checkpoint(after,100000)[0])
            self.assertNotIn('decision_replay',after)
            self.assertNotIn('price_cache',json.dumps(after))

    def test_public_allowlist_rejects_private_material(self):
        data={'trace_count':1,'last_trace_cycle':42,'input_hash':'b'*16,'output_hash':'c'*16,
              'replay_ok':True,'inputs':receipt()['inputs'],'query':'secret query','url':'https://private.invalid'}
        projected=sanitize_public_snapshot({'autopilot':{'decision_replay':data}})['autopilot']['decision_replay']
        self.assertEqual(set(projected),{'trace_count','last_trace_cycle','input_hash','output_hash','replay_ok'})
        self.assertNotIn('http',json.dumps(projected));self.assertNotIn('secret',json.dumps(projected))
        data['input_hash']='https://private.invalid'
        self.assertEqual(sanitize_public_snapshot({'autopilot':{'decision_replay':data}})['autopilot']['decision_replay']['input_hash'],'')

    def test_admin_auth_and_no_store(self):
        from route_policy import ROUTE_POLICY, ADMIN
        self.assertEqual(ROUTE_POLICY["/api/admin/decision-traces"],ADMIN)
        import cloud_mcp as runtime
        import asyncio
        from starlette.requests import Request
        def req(auth=''):
            return Request({'type':'http','method':'GET','path':'/api/admin/decision-traces',
                            'query_string':b'', 'headers':[(b'authorization',auth.encode())]})
        with tempfile.TemporaryDirectory() as d, patch.object(dr,'BUFFER',dr.TraceBuffer(d)), patch.object(runtime,'NEO_ADMIN_TOKEN','fixture-token'):
            denied=asyncio.run(runtime.api_admin_decision_traces(req()))
            self.assertNotEqual(denied.status_code,200)
            allowed=asyncio.run(runtime.api_admin_decision_traces(req('Bearer fixture-token')))
            self.assertEqual(allowed.status_code,200)
            self.assertEqual(allowed.headers['cache-control'],'no-store')

    def test_cli_identical_diff_and_corrupt_without_private_values(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'trace.json';t=receipt();p.write_text(json.dumps(t))
            def run():return subprocess.run([sys.executable,'scripts/replay_decision.py',str(p)],capture_output=True,text=True)
            self.assertEqual(run().stdout.strip(),'IDENTICO')
            t['inputs']['price_cache']=[];t['input_hash']=dr.digest(t['inputs']);p.write_text(json.dumps(t))
            result=run();self.assertEqual(result.returncode,1);self.assertIn('DIFF',result.stdout)
            self.assertNotIn('https://',result.stdout)
            t['output_hash']='0'*64;p.write_text(json.dumps(t));self.assertEqual(run().returncode,2)

    def test_recording_failure_does_not_raise_or_claim_success(self):
        with tempfile.TemporaryDirectory() as d, patch.object(dr,'BUFFER',dr.TraceBuffer(d)), patch.object(dr.BUFFER,'save',side_effect=OSError('private text')):
            t=receipt();o=t['output'];dr.finish(t,o['analysis'],o['hysteresis'],o['stable_rows'])
            self.assertTrue(dr.BUFFER.failed)
            self.assertFalse(dr.BUFFER.public()['replay_ok'])

    def test_actual_director_captures_replayable_first_cycle(self):
        import asyncio
        from contextlib import ExitStack
        from unittest.mock import AsyncMock
        import cloud_mcp as runtime
        class StopAfterDecision(BaseException): pass
        state=copy.deepcopy(runtime.AUTOPILOT_STATE)
        state.update(commercial_price_evidence=receipt()['inputs']['price_cache'],
                     commercial_evidence_memory=[], commercial_evidence_archive_rows=[], pending_evidence=[],
                     commercial_evidence_store_reference=None, gate_stability={}, evidence_store_degraded=False)
        with tempfile.TemporaryDirectory() as d, ExitStack() as stack:
            stack.enter_context(patch.object(dr,'BUFFER',dr.TraceBuffer(d)))
            stack.enter_context(patch.object(runtime,'AUTOPILOT_STATE',state))
            stack.enter_context(patch.object(runtime,'DEPLOY_COMMIT','a'*40))
            stack.enter_context(patch.object(runtime,'SHADOW_STUDENT',None))
            stack.enter_context(patch.object(runtime,'SETI_PRIVATE_STATE',{}))
            for name,value in [('ask_jarvis',{}),('ask_agents_data',{}),('_free_web_research',[]),
                               ('evidence_scouts',receipt()['inputs']['demand_evidence']),('_challenge_shadow_research',[])]:
                stack.enter_context(patch.object(runtime,name,AsyncMock(return_value=value)))
            stack.enter_context(patch.object(runtime.httpx,'AsyncClient',side_effect=AssertionError('no network')))
            stack.enter_context(patch.object(runtime,'build_candidate_telemetry',side_effect=StopAfterDecision))
            with self.assertRaises(StopAfterDecision): asyncio.run(runtime.director_run('AI agent tool',max_agents=0))
            self.assertEqual(len(dr.BUFFER.paths()),1)
            trace=dr.BUFFER.read(dr.BUFFER.paths()[0].name)
            self.assertTrue(trace['first_cycle_after_deploy'])
            self.assertTrue(trace['replay_ok'])
            self.assertTrue(dr.replay(trace)['identical'])
            self.assertEqual(len(trace['output']['candidates']),len(dr.scoring.CATEGORY_CONFIGS))

    def test_invalid_source_date_uses_explicit_now_and_observer_is_passive(self):
        t=receipt();i=t['inputs'];i['demand_evidence'][0]['date']='invalid-date'
        first=dr.evaluate(i);second=dr.evaluate(i)
        self.assertEqual(dr.digest(first),dr.digest(second))
        row=next(x for x in first['analysis']['top5'] if x['family']=='ai_tools')
        self.assertTrue(all(x['date']==i['now'] for x in row['sources']))
        from tool_opportunity import analyze_tool_opportunities
        args=(i['web_research'],i['demand_evidence'],i['seti_catalog'],i['query_meta'])
        plain=analyze_tool_opportunities(*args,now_utc=i['now'])
        observed=analyze_tool_opportunities(*args,now_utc=i['now'],decision_observer=dr.observer([]))
        self.assertEqual(plain,observed)

    def test_commit_replay_uses_recorded_git_worktree_and_cleans_up(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=root/'repo';repo.mkdir();(repo/'scripts').mkdir()
            for name in ('decision_replay.py','tool_opportunity.py','gate_stability.py','price_validation.py','scripts/replay_decision.py'):
                shutil.copyfile(name,repo/name)
            def git(*args): return subprocess.check_output(['git',*args],cwd=repo,stderr=subprocess.DEVNULL,text=True).strip()
            git('init');git('add','.')
            git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
            sha=git('rev-parse','HEAD');t=receipt();t['commit']=t['inputs']['commit']=sha
            t['output']=dr.evaluate(t['inputs']);t['output_hash']=dr.digest(t['output']);t['input_hash']=dr.digest(t['inputs'])
            path=root/'receipt.json';path.write_text(json.dumps(t))
            result=subprocess.run([sys.executable,str(repo/'scripts/replay_decision.py'),str(path),'--commit'],cwd=repo,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout)
            self.assertEqual(result.stdout.strip(),'IDENTICO')
            self.assertEqual(git('worktree','list','--porcelain').count('worktree '),1)
