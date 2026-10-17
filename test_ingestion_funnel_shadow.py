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
                    'discarded_by_reason': [
                        {'reason': 'no_demand_signal', 'count': 38},
                        {'reason': 'no_family', 'count': 22},
                        {'reason': 'weak_family_relevance', 'count': 16},
                    ],
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


    def test_buyer_voice_is_not_human_verified(self):
        report = diagnose(fixture())
        self.assertFalse(report['buyer_voice_counter_is_verified_buyer'])
        self.assertFalse(report['differences_are_verified_rejections'])
        self.assertEqual(report['stage_semantics']['buyer_voice'],
                         'web_voice_guard_passed_or_was_not_applicable')
        self.assertEqual(report['rejection_reasons'][0],
                         {'reason': 'no_demand_signal', 'count': 38})
        self.assertTrue(report['rejections_not_directly_reconcilable_to_stage_differences'])

    def test_unrecognized_rejection_reason_is_private_and_fails_closed(self):
        sample = fixture()
        sample['autopilot']['select_diagnostics']['funnel']['discarded_by_reason'].append(
            {'reason': 'secret.example.org', 'count': 1})
        with self.assertRaisesRegex(ValueError, 'unrecognized rejection reason'):
            diagnose(sample)

    def test_duplicate_reason_and_invalid_count_fail_closed(self):
        sample = fixture()
        reasons = sample['autopilot']['select_diagnostics']['funnel']['discarded_by_reason']
        reasons.append({'reason': 'no_family', 'count': 2})
        with self.assertRaisesRegex(ValueError, 'duplicate rejection reason'):
            diagnose(sample)
        sample = fixture()
        sample['autopilot']['select_diagnostics']['funnel']['discarded_by_reason'][0]['count'] = True
        with self.assertRaises(ValueError):
            diagnose(sample)

    def test_repository_snapshot_is_supported_without_mutation(self):
        """Integrate against the committed snapshot, not a hand-copied fixture."""
        import json
        from pathlib import Path

        snapshot_path = Path(__file__).resolve().parent / 'neo_latest_result.json'
        before = snapshot_path.read_bytes()
        snapshot = json.loads(before)
        audit = diagnose(snapshot)
        self.assertEqual(snapshot_path.read_bytes(), before)
        self.assertEqual(audit['status'], 'SHADOW_DIAGNOSTIC_ONLY')
        self.assertFalse(audit['production_state_write'])
        self.assertFalse(audit['automatic_promotion'])
        self.assertEqual(audit['commercial_gate_influence'], 'NONE')
        self.assertTrue(audit['requires_independent_human_labels'])

        source = snapshot['autopilot']['select_diagnostics']
        self.assertEqual(audit['funnel'][0]['input'],
                         source['funnel']['raw_received'])
        self.assertEqual(audit['funnel'][-1]['output'],
                         source['funnel']['persisted'])
        self.assertEqual(
            audit['largest_absolute_drop']['lost'],
            max(stage['lost'] for stage in audit['funnel']),
        )
        self.assertEqual(
            {entry['source'] for entry in audit['sources']},
            {entry['source'] for entry in source['search_sources']},
        )
        self.assertEqual(
            audit['event_loop']['codec_offthread'],
            snapshot['autopilot']['runtime_observation']['codec_offthread'],
        )
        # The result may expose safe aggregates, never individual traffic or
        # private evidence, even if those fields are present in the snapshot.
        serialized = json.dumps(audit)
        for private_field in ('inbound_traffic_events', 'content_fingerprint',
                              'inbound_review_queue', 'commercial_evidence_memory',
                              'source_url', 'raw_external_text'):
            self.assertNotIn(private_field, serialized)

    def test_no_unsupported_false_negative_claim(self):
        """Aggregate attrition alone is not a human-reviewed misclassification."""
        report = diagnose(fixture())
        self.assertTrue(report['requires_independent_human_labels'])
        self.assertNotIn('false_negative_count', report)
        self.assertNotIn('validated_buyer_demand', report)
        self.assertEqual(report['commercial_gate_influence'], 'NONE')

if __name__ == '__main__':
    unittest.main()
