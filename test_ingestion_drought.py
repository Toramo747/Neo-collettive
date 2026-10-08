import copy
import json
import unittest
from unittest.mock import patch

import cloud_mcp as runtime
import evidence_integrity as evidence
from ingestion_diagnostics import routed_search_diagnostics
from ingestion_drought import DroughtFunnel, public_drought
from public_snapshot import sanitize_public_snapshot, validate_public_snapshot
from test_family_classification_performance import original_scores
from test_intent_classification_performance import original_contains_term


class DroughtTests(unittest.TestCase):
    def test_three_cycles_partition_old_results_and_new_rejections(self):
        memory = [{'url': 'https://old.test/path', 'fingerprint': 'old-fp'}]
        for _ in range(3):
            observer = DroughtFunnel(memory)
            for row in ({'url': 'https://old.test/path?utm_source=test'},
                        {'url': 'https://different.test/1', 'fingerprint': 'old-fp'},
                        {'url': 'https://new.test/1'}, {'url': 'https://good.test/1'}):
                observer.add('private query', row, True)
                observer.outcome('private query', row['url'],
                                 '' if 'good.test' in row['url'] else 'no_demand_signal')
            observer.new_signal('https://good.test/1', 'private query')
            row = observer.snapshot()['rows'][0]
            self.assertEqual([row[k] for k in ('raw_results', 'relevance_pass', 'useful',
                             'new_signal_row', 'duplicate_memory', 'new_rejected')], [4, 4, 1, 1, 2, 1])
            self.assertEqual(sum(x['count'] for x in row['rejections']) + row['useful'], row['raw_results'])

    def test_routing_rejections_are_retained_per_raw_result(self):
        diag = routed_search_diagnostics([[{'url': '', 'source': 'github'},
               {'url': 'https://a.test', 'snippet': 'noise'}, {'url': 'https://a.test'}]],
               'q', {}, lambda *_: {'relevant': False})
        self.assertEqual([x['reason'] for x in diag['result_receipts']],
                         ['missing_url', 'query_irrelevant', 'routing_duplicate'])

    def test_public_projection_has_only_numeric_leaves_and_is_idempotent(self):
        observer = DroughtFunnel([])
        observer.add('secret query https://private.test', {'url': 'https://private.test',
                      'source': 'private-provider'}, False, 'no_family')
        private = observer.snapshot()
        private['rows'][0]['url'] = 'https://leak.test'
        projected = public_drought(private)
        self.assertEqual(public_drought(projected), projected)
        def check(value):
            if isinstance(value, dict):
                for x in value.values(): check(x)
            elif isinstance(value, list):
                for x in value: check(x)
            else: self.assertIs(type(value), int)
        check(projected)
        raw = {'autopilot': {}, 'latest_result': {'evidence_quality': {'ingestion_diagnostics': {'drought': private}}}}
        snapshot = sanitize_public_snapshot(raw)
        validate_public_snapshot(snapshot)
        self.assertEqual(snapshot['autopilot']['select_diagnostics']['ingestion_drought'], projected)
        self.assertNotIn('private.test', json.dumps(snapshot))
        self.assertNotIn('leak.test', json.dumps(snapshot))

    def test_old_and_new_classifiers_produce_identical_funnel_labels(self):
        texts = ['We need help reconciling invoices manually. Budget 500 EUR, hiring a freelancer.',
                 'Our team spends hours cleaning CSV files manually every week.',
                 'Banana cultivation is improving in summer.',
                 'Developer code review testing workflow with no other details.',
                 'Our tool offers invoice automation pricing $20/month.',
                 'İ NEED help with spreadsheets and invoices.',
                 ('unrelated context ' * 4000) + ' invoices manual workflow csv files']
        groups = [{'query': '', 'results': [{'url': f'https://sample{i}.test/issues/1',
                   'title': text[:50], 'snippet': text, 'source': 'github-issues-routed'}
                   for i, text in enumerate(texts)]}]
        def run(original):
            with patch.object(runtime, 'AUTOPILOT_STATE', {}), patch.object(runtime, 'SHADOW_STUDENT', None):
                if original:
                    with patch.object(evidence, 'commercial_family_scores', original_scores), \
                         patch.object(evidence, 'contains_term', original_contains_term), \
                         patch.object(runtime, 'contains_term', original_contains_term):
                        return runtime._commercial_evidence_quality(copy.deepcopy(groups))
                return runtime._commercial_evidence_quality(copy.deepcopy(groups))
        before, after = run(True), run(False)
        self.assertEqual(before['ingestion_diagnostics']['drought'], after['ingestion_diagnostics']['drought'])
        self.assertEqual(before['rejected_current_results'], after['rejected_current_results'])
        self.assertEqual(before['current_cycle_useful_results'], after['current_cycle_useful_results'])
        self.assertEqual(before['problem_clusters'], after['problem_clusters'])


if __name__ == '__main__':
    unittest.main()
