"""Offline investigation: run the actual director up to candidate telemetry.

No hidden-control entry point is executed. Network responses are fixed; scoring,
price replay, evidence migration, hysteresis and state recovery are production code.
"""
import asyncio
import copy
from contextlib import ExitStack, chdir
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import cloud_mcp as runtime
from price_validation import compact_price_evidence
from state_codec import decode_checkpoint
from types import SimpleNamespace


class ScoringCaptured(BaseException):
    """Stop after the real gate, before unrelated build/outreach actions."""


def fixture():
    state = copy.deepcopy(runtime.AUTOPILOT_STATE)
    state.update(cycles_completed=2913, commercial_evidence_memory=[],
                 commercial_evidence_archive_rows=[], pending_evidence=[],
                 commercial_evidence_store_reference=None,
                 commercial_evidence_archive_reference=None,
                 challenge_track_store_reference=None, challenge_track={},
                 gate_stability={'last_observed_commit': 'before'},
                 evidence_store_degraded=False)
    scouts = []
    for i in range(13):
        text = 'AI agent workflow documentation.'
        if i < 2:
            text += ' Our team finds this too expensive and missing feature.'
        if i == 2:
            text += ' A new release is available.'
        if i == 3:
            text += ' A free alternative exists.'
        scouts.append({'family': 'ai_tools', 'source': 'fixture',
                       'url': f'https://voice{i % 10}.invalid/issues/{i}',
                       'title': 'AI agent workflow', 'text': text})
    plan = [{'query': 'fixture prices', 'family': 'ai_tools'}]
    groups = [{'query': 'fixture prices', 'results': [
        {'url': f'https://vendor{i}.invalid/pricing', 'title': 'AI agent pricing',
         'snippet': f'AI agent plan USD {20+i} per month'} for i in range(2)]}]
    state['commercial_price_evidence'] = compact_price_evidence(plan, groups)
    now = time.time()
    state['commercial_evidence_memory'] = [
        {'evidence_id': f'fixture-{i}', 'fingerprint': f'fixture-{i}',
         'url': f'https://memory.invalid/issues/{i}', 'family': 'ai_tools',
         'schema_v': 3, 'tagger_v': 3, 'migration_v': 3,
         'excerpt': 'Our team spends hours debugging code manually every week.',
         'signal_types': ['PAIN'], 'gate_eligible': True,
         'first_seen_epoch': now-1000, 'last_seen_epoch': now-100}
        for i in range(145)]
    return state, scouts


class PostDeployDeterminismTests(unittest.TestCase):
    def score(self, state, scouts, commit):
        captured = {}
        original = runtime.build_candidate_telemetry
        def capture(rows, gate, **kwargs):
            telemetry = original(rows, gate, **kwargs)
            candidate = next(x for x in rows if x['family'] == 'ai_tools')
            captured.update(score=candidate['monetization_score'],
                            missing_codes=candidate['missing'],
                            raw_gate_pass=candidate['raw_gate_pass'],
                            monetization_score=candidate['monetization_score'],
                            competitors_with_real_price=len(candidate['existing_tools']),
                            dissatisfaction=len(candidate['dissatisfaction_signals']),
                            documented_gap=len(candidate['documented_gaps']))
            self.assertEqual(kwargs['first_cycle_after_deploy'], commit == 'after')
            self.assertTrue(telemetry)
            raise ScoringCaptured()
        with ExitStack() as stack:
            stack.enter_context(patch.object(runtime, 'AUTOPILOT_STATE', state))
            stack.enter_context(patch.object(runtime, 'DEPLOY_COMMIT', commit))
            stack.enter_context(patch.object(runtime, 'CANDIDATE_TELEMETRY_HMAC_KEY', 'test-only'))
            stack.enter_context(patch.object(runtime, 'SETI_PRIVATE_STATE', {}))
            stack.enter_context(patch.object(runtime, 'SHADOW_STUDENT', None))
            stack.enter_context(patch.object(runtime, 'build_candidate_telemetry', capture))
            for name, value in [('ask_jarvis', {}), ('ask_agents_data', {}),
                                ('evidence_scouts', scouts), ('_free_web_research', []),
                                ('_challenge_shadow_research', [])]:
                stack.enter_context(patch.object(runtime, name, AsyncMock(return_value=copy.deepcopy(value))))
            # Any accidental network call fails instead of fetching live evidence.
            stack.enter_context(patch.object(runtime.httpx, 'AsyncClient', side_effect=AssertionError('network forbidden')))
            with self.assertRaises(ScoringCaptured):
                asyncio.run(runtime.director_run('AI agent workflow', max_agents=0))
        return captured

    def roundtrip(self, state):
        # Incompressible ephemeral history forces the actual 75 KB trigger.
        state['tool_opportunities'] = {'history': ''.join(
            hashlib.sha256(str(i).encode()).hexdigest() for i in range(3500))}
        written = {}
        class RenderTransport:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def put(self, url, *, json, **kwargs):
                self_key = url.rsplit('/', 1)[-1]
                written[self_key] = json['value']
                return SimpleNamespace(is_success=True, status_code=200,
                                       json=lambda: {'value': json['value']})
        with patch.object(runtime, 'AUTOPILOT_STATE', state), \
             patch.object(runtime, 'RENDER_API_KEY', 'fixture-only'), \
             patch.object(runtime, 'RENDER_SERVICE_ID', 'fixture-only'), \
             patch.object(runtime.httpx, 'AsyncClient', return_value=RenderTransport()):
            checkpoint = asyncio.run(runtime._checkpoint_state_to_render())
        self.assertTrue(checkpoint['ok'], checkpoint)
        meta = checkpoint['compaction']
        self.assertGreater(meta['before_encoded_bytes'], meta['trigger_bytes'])
        self.assertTrue(meta['applied'])
        self.assertEqual(meta['store_mode'], 'external')
        encoded = written[runtime.STATE_ENV_KEY]
        self.assertEqual(decode_checkpoint(encoded)['commercial_price_evidence'], state['commercial_price_evidence'])
        restored = copy.deepcopy(runtime.AUTOPILOT_STATE)
        restored['gate_stability'] = {}
        with tempfile.TemporaryDirectory() as directory, chdir(directory), \
             patch.object(runtime, 'AUTOPILOT_STATE', restored), \
             patch.object(runtime, 'STATE_SNAPSHOT_PATH', str(Path(directory) / 'state.json')), \
             patch.dict(os.environ, written), \
             patch.object(runtime, '_load_cycle_floor', return_value=(None, {})), \
             patch.object(runtime.httpx, 'AsyncClient', side_effect=AssertionError('network forbidden')):
            self.assertEqual(runtime._restore_state(), 'render_env')
        self.assertEqual(restored['commercial_price_evidence'], state['commercial_price_evidence'])
        self.assertEqual(len(restored['commercial_evidence_memory']), 145)
        return restored

    def test_checkpoint_compaction_restore_first_cycle_identical(self):
        state, scouts = fixture()
        # These price receipts already exist before either execution.
        before = self.score(state, scouts, 'before')
        state['cycles_completed'] += 1
        restored = self.roundtrip(copy.deepcopy(state))
        after = self.score(restored, scouts, 'after')
        print('FIELD_DIFF ' + json.dumps({k: {'before': before[k], 'after': after[k]} for k in before}, sort_keys=True))
        self.assertEqual(before, after)
        self.assertEqual(before['score'], 85)

    def test_contextless_cache_and_source_order_do_not_create_restore_pass(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                state, scouts = fixture()
                for row in state['commercial_price_evidence']:
                    row['price_context'] = 'Plan USD 20 per month'
                if reverse:
                    scouts.reverse()
                    state['commercial_price_evidence'].reverse()
                before = self.score(state, scouts, 'before')
                state['cycles_completed'] += 1
                restored = self.roundtrip(copy.deepcopy(state))
                after = self.score(restored, scouts, 'after')
                print('CONTEXTLESS_FIELD_DIFF ' + json.dumps({k: {'before': before[k], 'after': after[k]} for k in before}, sort_keys=True))
                self.assertEqual(before, after)
                self.assertEqual(before['score'], 35)
                self.assertFalse(after['raw_gate_pass'])

    def test_missing_prices_after_restore_fail_closed(self):
        state, scouts = fixture()
        state['commercial_price_evidence'] = []
        restored = self.roundtrip(state)
        result = self.score(restored, scouts, 'after')
        self.assertIn('two_competitors_with_real_price', result['missing_codes'])
        self.assertIn('monetization_score_60', result['missing_codes'])
        self.assertFalse(result['raw_gate_pass'])
