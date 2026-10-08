"""Anonymous equivalent of the 85 -> 35 competitor-price disappearance.

Fresh inputs and durable price cache must describe the same observations.
This does not assert equality after new provider observations arrive.
"""
import copy
import unittest
from unittest.mock import patch

import cloud_mcp as runtime
from price_validation import compact_price_evidence, persisted_price_groups
from state_codec import decode_checkpoint, encode_checkpoint
from state_compaction import compact_state_payload
from tool_opportunity import _cached_price_observation, analyze_tool_opportunities

NOW = '2026-10-08T16:27:00+00:00'


def fixture(extra=''):
    plan = [{'query': 'anonymous pricing', 'family': 'ai_tools',
             'role': 'price_validation', 'validation_kind': 'pricing'}]
    groups = [{'query': plan[0]['query'], 'results': [
        {'url': f'https://vendor-{i}.example/pricing', 'title': f'AI Agent {i} new release',
         'snippet': 'AI agent plans for production teams',
         'page_text': ('unrelated context ' * 50) + f'USD {10+i} per month ' + extra,
         'page_fetched': True, 'source': 'bing-rss-free'} for i in range(2)]}]
    demand = [{'url': 'https://buyer.example/issues/1', 'domain': 'buyer.example',
               'title': 'AI agent export limitation', 'snippet':
               'Our AI agent tool is too expensive and missing feature; we need export workflow.',
               'source': 'github-issues-routed', 'family': 'ai_tools',
               'problem_key': 'ai_tools:export_workflow', 'last_seen_epoch': 1791476820,
               'first_seen_epoch': 1791476820}]
    return plan, groups, demand


def decision(groups, demand, plan):
    meta = {' '.join(x['query'].split()).lower(): x for x in plan}
    row = next(x for x in analyze_tool_opportunities(groups, demand, [], meta, NOW)['top5']
               if x['family'] == 'ai_tools')
    return (row['monetization_score'], row['missing'], row['gate_pass'])


class PriceCacheScoreReplayTests(unittest.TestCase):
    def roundtrip(self, extra='', reverse=False, repetitions=1, price_in_title=False, only_one=False):
        plan, groups, demand = fixture(extra)
        if reverse:
            groups[0]['results'].reverse()
        if price_in_title:
            for i, row in enumerate(groups[0]['results']):
                row['title'] += f' USD {10+i} per month'
                row['page_text'] = 'AI agent plans'
        if only_one:
            groups[0]['results'] = groups[0]['results'][:1]
        before = decision(groups, demand, plan)
        initial = copy.deepcopy(runtime.AUTOPILOT_STATE)
        initial['commercial_evidence_memory'] = demand
        initial['commercial_price_evidence'] = compact_price_evidence(plan, groups)
        initial['cycles_completed'] = 2926
        initial['tool_opportunities'] = {'top5': [{'monetization_score': before[0]}]}
        for _ in range(repetitions):
            with patch.object(runtime, 'AUTOPILOT_STATE', initial):
                checkpoint = copy.deepcopy(runtime._state_payload())
            compacted, meta = compact_state_payload(checkpoint, max_bytes=60000,
                                                   target_bytes=1, force=True)
            self.assertTrue(meta['applied'])
            self.assertNotIn('tool_opportunities', compacted)
            self.assertEqual(compacted['commercial_price_evidence'], checkpoint['commercial_price_evidence'])
            restored = decode_checkpoint(encode_checkpoint(compacted, 4000000)[0])
            with patch.object(runtime, 'AUTOPILOT_STATE', copy.deepcopy(runtime.AUTOPILOT_STATE)):
                runtime._merge_state_payload(restored)
                replay = persisted_price_groups(runtime.AUTOPILOT_STATE['commercial_price_evidence'])
                replay_plan = [{'query': x['query'], 'family': x['_persisted_price_family'],
                                'role': 'price_validation', 'validation_kind': 'persisted_strict'} for x in replay]
                after = decision(replay, runtime.AUTOPILOT_STATE['commercial_evidence_memory'], replay_plan)
                initial = copy.deepcopy(runtime.AUTOPILOT_STATE)
            self.assertEqual(before, after, 'score, missing codes and raw gate must survive cache/checkpoint/restore')
        return before

    def test_complete_state_preserves_85_score_missing_codes_and_raw_gate(self):
        self.assertEqual(self.roundtrip(), (85, [], True))

    def test_counters_outside_price_window_survive_all_compaction_levels(self):
        self.assertEqual(self.roundtrip(('other context ' * 60) + 'free forever')[0], 65)

    def test_order_and_three_consecutive_restores_preserve_decision(self):
        self.assertEqual(self.roundtrip(reverse=True, repetitions=3), (85, [], True))

    def test_title_only_price_is_replayed_without_inventing_page_text(self):
        self.assertEqual(self.roundtrip(price_in_title=True), (85, [], True))

    def test_missing_codes_and_failed_raw_gate_are_preserved(self):
        score, missing, raw_pass = self.roundtrip(only_one=True)
        self.assertEqual(score, 55)
        self.assertEqual(missing, ['two_competitors_with_real_price',
                                   'three_independent_source_domains', 'monetization_score_60'])
        self.assertFalse(raw_pass)

    def test_legacy_or_malformed_receipts_use_legacy_classification(self):
        plan, groups, _ = fixture()
        item = persisted_price_groups(compact_price_evidence(plan, groups))[0]['results'][0]
        self.assertIsNotNone(_cached_price_observation(item, 'ai_tools'))
        for mutation in ({'_persisted_price_receipt_v': 999},
                         {'_persisted_price_receipt': {}},
                         {'_persisted_price_receipt': {'signal_types': 'PAYMENT'}},
                         {'url': 'https://different.example/pricing'},
                         {'page_text': 'no verified price'}):
            changed = copy.deepcopy(item)
            changed.update(mutation)
            self.assertIsNone(_cached_price_observation(changed, 'ai_tools'))
        legacy = copy.deepcopy(item)
        legacy.pop('_persisted_price_receipt')
        legacy.pop('_persisted_price_receipt_v')
        self.assertIsNone(_cached_price_observation(legacy, 'ai_tools'))
        self.assertEqual(len(persisted_price_groups([{'family': 'ai_tools',
                         'url': item['url'], 'strict_price_verified': True}])), 1)

    def test_fresh_provider_payload_cannot_override_classification_with_receipt(self):
        plan, groups, demand = fixture()
        before = decision(groups, demand, plan)
        for row in groups[0]['results']:
            row['_persisted_price_receipt_v'] = 1
            row['_persisted_price_receipt'] = {'signal_types': ['PAYMENT'], 'real_price': True}
        self.assertEqual(decision(groups, demand, plan), before)


if __name__ == '__main__':
    unittest.main()
