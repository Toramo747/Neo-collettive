import copy
import unittest
from experiments.ingestion_funnel_shadow import diagnose


def fixture():
    return {
        'snapshot_schema': 7,
        'private_source_text': 'CONFIDENTIAL-NEVER-EMIT',
        'autopilot': {
            'runtime_observation': {
                'event_loop_stalls': 84, 'event_loop_max_lag_ms': 12846.824,
                'codec_offthread': False,
            },
            'select_diagnostics': {
                'funnel': {
                    'raw_received': 140, 'query_relevant': 113,
                    'family_matched': 54, 'buyer_voice': 2,
                    'commercial_signal': 0, 'persisted': 0,
                },
                'search_sources': [
                    {'source': 'bing-rss', 'attempts': 14, 'raw_results': 84,
                     'relevance_pass': 71, 'errors': 0},
                    {'source': 'brave', 'attempts': 14, 'raw_results': 0,
                     'relevance_pass': 0, 'errors': 14},
                    {'source': 'github', 'attempts': 0, 'raw_results': 20,
                     'relevance_pass': 10, 'errors': 0},
                    {'source': 'hn', 'attempts': 14, 'raw_results': 36,
                     'relevance_pass': 32, 'errors': 0},
                ],
                'search_provider': {
                    'fallback_reasons': [{'reason': 'budget_paced', 'count': 14}]},
            },
        },
    }


class FunnelAuditTests(unittest.TestCase):
    def test_real_snapshot_aggregates(self):
        result = diagnose(fixture())
        self.assertEqual(result['largest_absolute_drop'],
                         {'from': 'query_relevant', 'to': 'family_matched', 'lost': 59})
        self.assertEqual(result['funnel'][2]['lost'], 52)
        self.assertEqual(result['brave_budget_paced_fallbacks'], 14)
        self.assertEqual(result['event_loop']['max_lag_ms'], 12846.824)
        self.assertEqual(result['commercial_gate_influence'], 'NONE')
        self.assertFalse(result['production_state_write'])

    def test_no_private_content_leak(self):
        import json
        result = json.dumps(diagnose(fixture()))
        self.assertNotIn('CONFIDENTIAL-NEVER-EMIT', result)
        self.assertNotIn('private_source_text', result)

    def test_nonmonotonic_or_invalid_counts_fail_closed(self):
        for value in (-1, 2.0, None, True):
            data = fixture()
            data['autopilot']['select_diagnostics']['funnel']['buyer_voice'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                diagnose(data)
        data = fixture()
        data['autopilot']['select_diagnostics']['funnel']['family_matched'] = 115
        with self.assertRaises(ValueError):
            diagnose(data)

    def test_source_mismatch_fails_closed(self):
        data = fixture()
        data['autopilot']['select_diagnostics']['search_sources'][0]['raw_results'] = 85
        with self.assertRaises(ValueError):
            diagnose(data)

    def test_unknown_source_fails_closed_without_echoing_name(self):
        data = copy.deepcopy(fixture())
        data['autopilot']['select_diagnostics']['search_sources'][0]['source'] = 'secret.example.org'
        with self.assertRaisesRegex(ValueError, 'unrecognized source diagnostic'):
            diagnose(data)


if __name__ == '__main__':
    unittest.main()
