import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cloud_mcp
from runtime_observation import RuntimeObservation
from state_codec import encode_checkpoint_async
from scripts.retry_deploy_smoke import run_smoke
from scripts.wait_first_autopilot_cycle import first_cycle_complete, wait_first
from test_evidence_store_atomic import _CaptureStateClient

ROOT = Path(__file__).parent


class CodecSwitchTests(unittest.IsolatedAsyncioTestCase):
    async def test_identical_bytes_and_default_sync(self):
        payload = {'rows': ['synthetic-%d' % i for i in range(30000)]}
        outputs = []
        for value in ('0', '1'):
            with patch.dict(os.environ, {'NEO_CHECKPOINT_CODEC_OFFTHREAD': value}):
                outputs.append(await encode_checkpoint_async(payload, 4000000))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(hashlib.sha256(outputs[0][0].encode()).hexdigest(),
                         hashlib.sha256(outputs[1][0].encode()).hexdigest())
        with patch.dict(os.environ, {}, clear=True), patch('state_codec.asyncio.to_thread') as thread:
            self.assertEqual(await encode_checkpoint_async(payload, 4000000), outputs[0])
            thread.assert_not_called()

    async def test_thread_error_propagates_and_never_publishes_checkpoint(self):
        with patch.dict(os.environ, {'NEO_CHECKPOINT_CODEC_OFFTHREAD': '1'}), \
             patch('state_codec.compress_checkpoint', side_effect=ValueError('synthetic codec failure')):
            with self.assertRaisesRegex(ValueError, 'synthetic codec failure'):
                await encode_checkpoint_async({'synthetic': True}, 4000000)
            _CaptureStateClient.puts = []
            with patch.object(cloud_mcp, 'RENDER_API_KEY', 'synthetic'), \
                 patch.object(cloud_mcp, 'RENDER_SERVICE_ID', 'synthetic'), \
                 patch.object(cloud_mcp, '_state_payload', return_value={'commercial_evidence_memory': []}), \
                 patch.object(cloud_mcp, 'AUTOPILOT_STATE', {}), \
                 patch.object(cloud_mcp.httpx, 'AsyncClient', _CaptureStateClient):
                result = await cloud_mcp._checkpoint_state_to_render()
            self.assertFalse(result['ok'])
            self.assertIn('synthetic codec failure', result['reason'])
            self.assertEqual(_CaptureStateClient.puts, [])

    def test_three_mib_replay_one_cpu_before_after(self):
        results = {}
        for mode in ('0', '1'):
            env = dict(os.environ, NEO_CHECKPOINT_CODEC_OFFTHREAD=mode)
            proc = subprocess.run([sys.executable, 'scripts/reproduce_loop_stall.py', '--mib', '3', '--passes', '3'],
                                  cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            results[mode] = json.loads(proc.stdout)
        sync, threaded = results['0'], results['1']
        self.assertEqual(sync['encoded_sha256'], threaded['encoded_sha256'])
        self.assertEqual(sync['cpu_affinity_count'], 1)
        self.assertGreaterEqual(sync['raw_bytes'], 3 * 1024 * 1024)
        # CPU speed on hosted runners is variable; assert the relative stall
        # reduction instead of demanding a fixed 2-second sync stall.
        sync_lag = sync['observation']['event_loop_max_lag_ms']
        threaded_lag = threaded['observation']['event_loop_max_lag_ms']
        self.assertGreater(sync_lag, 750)
        self.assertGreater(sync_lag, 2 * threaded_lag)
        self.assertLess(threaded_lag, 1000)
        self.assertFalse(sync['observation']['codec_offthread'])
        self.assertTrue(threaded['observation']['codec_offthread'])
        self.assertTrue(any(row['function'] == 'compress_checkpoint'
                            for row in sync['observation']['last_project_stack']))
        print('CPU-limited checkpoint replay: ' + json.dumps({
            mode: {'max_lag_ms': row['observation']['event_loop_max_lag_ms'],
                   'lzma_max_ms': row['observation']['phases']['checkpoint_lzma']['max_duration_ms'],
                   'sha256': row['encoded_sha256']} for mode, row in results.items()}))


class SmokeContractTests(unittest.TestCase):
    def test_final_failure_normal_and_observation(self):
        for observation in (False, True):
            sleeps, calls = [], []
            def fail(command):
                calls.append(command)
                return subprocess.CompletedProcess(command, 7)
            with tempfile.TemporaryDirectory() as tmp:
                marker = Path(tmp) / 'failed'
                code = run_smoke(['synthetic'], observation, fail, sleeps.append, marker)
                self.assertEqual(code, 0 if observation else 7)
                self.assertEqual(marker.exists(), observation)
            self.assertEqual(len(calls), 3)
            self.assertEqual(sleeps, [20, 20])

    def test_success_first_attempt(self):
        sleeps = []
        self.assertEqual(run_smoke(['synthetic'], runner=lambda c: subprocess.CompletedProcess(c, 0),
                                   sleep=sleeps.append), 0)
        self.assertEqual(sleeps, [])

    def test_first_cycle_is_explicit_and_wait_is_bounded(self):
        self.assertFalse(first_cycle_complete({'autopilot': {'cycles_completed': 900}}))
        observer = RuntimeObservation()
        self.assertFalse(observer.private_snapshot()['first_autopilot_cycle_completed'])
        observer.mark_first_cycle(901)
        observer.mark_first_cycle(902)
        obs = observer.private_snapshot()
        self.assertEqual(obs['first_autopilot_cycle_number'], 901)
        self.assertTrue(first_cycle_complete({'autopilot': {'runtime_observation': obs}}))
        now = [0]
        def sleep(seconds): now[0] += seconds
        self.assertFalse(wait_first(lambda timeout: {}, clock=lambda: now[0], sleep=sleep))
        self.assertEqual(now[0], 300)
        self.assertTrue(wait_first(lambda timeout: {'autopilot': {'runtime_observation': obs}},
                                   clock=lambda: now[0], sleep=sleep))

    def test_workflow_authorization_and_surface_contract(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/neo-render-deploy.yml').read_text())
        job = workflow['jobs']['deploy']
        steps = job['steps']
        by_name = {step['name']: step for step in steps if 'name' in step}
        auth = by_name['Authorize observation deploy']['run']
        for actor, triggering_actor, ok in [('Toramo747', 'Toramo747', True),
                                           ('someone-else', 'someone-else', False),
                                           ('Toramo747', 'someone-else', False)]:
            result = subprocess.run(['bash', '-c', auth], env=dict(os.environ, GITHUB_ACTOR=actor, GITHUB_TRIGGERING_ACTOR=triggering_actor),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, ok)
            if ok: self.assertIn('::warning::', result.stdout)
        self.assertIn("github.actor == 'Toramo747'", job['env']['OBSERVATION_DEPLOY'])
        names = list(by_name)
        wait = names.index('Wait for first completed autopilot cycle')
        surface_steps = [s for s in steps if 'retry_deploy_smoke.py' in s.get('run', '')]
        self.assertEqual(len(surface_steps), 10)
        for step in surface_steps:
            self.assertGreater(names.index(step['name']), wait)
            self.assertNotIn('--max-time 45', step['run'])
            self.assertNotIn('timeout=45', step['run'])
            self.assertNotIn('--retry ', step['run'])
            subprocess.run(['bash', '-n'], input=step['run'], text=True, check=True)
        arena = (ROOT / 'scripts/smoke_arena_surface.sh').read_text()
        subprocess.run(['bash', '-n'], input=arena, text=True, check=True)
        self.assertEqual(arena.count('--max-time 30'), 4)
        self.assertNotIn('--retry ', arena)
        rollback = [s for s in steps if s.get('name') in {
            'Restore previous Render production commit', 'Roll back failed application commit'}]
        self.assertEqual(len(rollback), 2)
        for step in rollback:
            self.assertIn("env.OBSERVATION_DEPLOY != 'true'", step['if'])
