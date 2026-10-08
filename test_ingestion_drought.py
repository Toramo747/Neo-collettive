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
            else: self.assertIn(type(value), (int, bool))
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

class DroughtPersistenceTests(unittest.TestCase):
    def test_private_receipts_do_not_survive_disk_result_history(self):
        import tempfile
        from pathlib import Path
        observer = DroughtFunnel([])
        observer.add('private query marker', {'url': 'https://private-marker.example/x'}, True)
        observer.outcome('private query marker', 'https://private-marker.example/x')
        result = {'evidence_quality': {'ingestion_diagnostics': {'drought': observer.snapshot()}}}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(runtime, 'RESULTS_LOG_PATH', str(Path(directory) / 'results.jsonl')), \
             patch.object(runtime, 'DIRECTOR_RESULT_LOG', []):
            entry = runtime._record_director_result(result)
            self.assertIn('private_results', json.dumps(entry))
            runtime.DIRECTOR_RESULT_LOG.clear()
            restored = runtime._load_recent_results(3)
            self.assertNotIn('private_results', json.dumps(restored))
            self.assertNotIn('private_queries', json.dumps(restored))
            self.assertNotIn('private-marker.example', json.dumps(restored))


class DroughtJoinTests(unittest.TestCase):
    def test_shared_key_normalizes_query_and_provider_aliases(self):
        observer = DroughtFunnel([])
        observer.add('  My  QUERY ', {'url': 'https://a.test/path', 'source': 'bing-rss'}, False)
        observer.relevant('my query', 'https://a.test/path', 'bing-rss-free')
        observer.outcome('MY query', 'https://a.test/path', source='bing-rss-free')
        observer.new_signal('https://a.test/path', ' my query ', 'bing-rss-free')
        result = observer.snapshot()
        self.assertEqual(result['unjoined_total'], 0)
        self.assertTrue(result['measurement_reliable'])
        self.assertEqual(result['rows'][0]['provider_code'], 1)
        self.assertEqual(result['rows'][0]['new_signal_row'], 1)
        self.assertEqual(result['rows'][0]['relevance_pass'], 1)

    def test_missing_outcome_is_unjoined_not_routing_limit(self):
        observer = DroughtFunnel([])
        observer.add('q', {'url': 'https://a.test'}, True)
        result = observer.snapshot()
        self.assertEqual(result['private_results'][0]['reason'], 'unjoined')
        self.assertEqual(result['unjoined_total'], 1)
        self.assertFalse(public_drought(result)['measurement_reliable'])

    def test_only_explicit_router_cutoff_is_routing_limit(self):
        from ingestion_diagnostics import mark_routing_limit
        rows = [{'url': f'https://a.test/{i}', 'source': 'bing-rss-free'} for i in range(3)]
        diag = routed_search_diagnostics([rows], 'q', {}, lambda *_: {'relevant': True})
        mark_routing_limit(diag, rows[:1], 1)
        self.assertEqual([x['reason'] for x in diag['result_receipts']], ['', 'routing_limit', 'routing_limit'])
        observer = DroughtFunnel([])
        for row in diag['result_receipts']:
            observer.add('q', row, row['relevance_pass'], row['reason'])
        observer.outcome('q', rows[0]['url'], source='bing-rss-free')
        self.assertTrue(observer.snapshot()['measurement_reliable'])
        self.assertEqual(observer.snapshot()['private_results'][1]['reason'], 'routing_limit')

    def test_no_cutoff_does_not_hide_missing_outcome(self):
        from ingestion_diagnostics import mark_routing_limit
        rows = [{'url': 'https://a.test', 'source': 'bing-rss-free'}]
        diag = routed_search_diagnostics([rows], 'q', {}, lambda *_: {'relevant': True})
        mark_routing_limit(diag, [], 6)
        self.assertEqual(diag['result_receipts'][0]['reason'], '')

class DroughtCheckpointBudgetTests(unittest.TestCase):
    def test_three_cycles_of_150_receipts_add_at_most_3000_encoded_bytes(self):
        import hashlib
        from state_codec import encode_checkpoint
        from state_compaction import drop_ephemeral_checkpoint_state
        baseline_state = copy.deepcopy(runtime.AUTOPILOT_STATE)
        baseline_state['dialogue_history'] = [{'cycle': c} for c in range(3)]
        # Main's checkpoint representation has no drought diagnostics. All
        # non-drought fields use the identical production payload and codec.
        with patch.object(runtime, 'AUTOPILOT_STATE', baseline_state):
            baseline = runtime._state_payload()
        instrumented_state = copy.deepcopy(baseline_state)
        for c in range(3):
            observer = DroughtFunnel([])
            for i in range(150):
                query = f'private query {i % 10}'
                url = 'https://private.example/' + ''.join(hashlib.sha256(f'{c}-{i}-{j}'.encode()).hexdigest() for j in range(4))
                source = ('bing-rss', 'hn', 'github')[i % 3]
                observer.add(query, {'url': url, 'source': source}, True)
                observer.outcome(query, url, 'no_family', source)
            instrumented_state['dialogue_history'][c]['ingestion_diagnostics'] = {'drought': observer.snapshot()}
        with patch.object(runtime, 'AUTOPILOT_STATE', instrumented_state):
            actual = runtime._state_payload()
        for payload in (actual, drop_ephemeral_checkpoint_state(instrumented_state)):
            self.assertNotIn('private_results', json.dumps(payload))
            self.assertNotIn('private_queries', json.dumps(payload))
            self.assertNotIn('private.example', json.dumps(payload))
        # Measured isolated run: baseline=13447, instrumented=14015, delta=568 bytes.
        # Same production codec, same timestamp: compare only diagnostics growth.
        actual['state_saved_at_utc'] = baseline['state_saved_at_utc']
        actual['runtime_observation'] = baseline['runtime_observation']
        before = encode_checkpoint(baseline, 4000000)[2]
        after = encode_checkpoint(actual, 4000000)[2]
        growth = after - before
        print(f'CHECKPOINT_BUDGET baseline={before} instrumented={after} delta={growth} bytes')
        self.assertLessEqual(growth, 3000, f'measured growth: {growth} encoded bytes')

    def test_cycle_result_has_exactly_one_drought_copy(self):
        import ast
        from pathlib import Path
        tree = ast.parse(Path(runtime.__file__).read_text())
        candidates = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)
                      and 'evidence_quality' in [k.value for k in n.keys if isinstance(k, ast.Constant)]
                      and 'ingestion_diagnostics' in [k.value for k in n.keys if isinstance(k, ast.Constant)]]
        quality = {'ingestion_diagnostics': {'drought': {'private_results': ['private-marker']}}}
        self.assertTrue(candidates)
        for node in candidates:
            result = {}
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value in {'evidence_quality', 'ingestion_diagnostics'}:
                    result[key.value] = eval(compile(ast.Expression(value), '<cycle-result>', 'eval'), {'evidence_quality': quality})
            self.assertEqual(json.dumps(result).count('"drought"'), 1)
