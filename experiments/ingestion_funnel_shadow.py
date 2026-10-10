# SPDX-License-Identifier: BUSL-1.1
"""Read-only, aggregate-only audit of a published OXIBAY runtime snapshot.

This module never imports the runtime, mutates evidence, or scores candidates.
"""
import argparse
import json
from pathlib import Path

STAGES = (
    'raw_received', 'query_relevant', 'family_matched',
    'buyer_voice', 'commercial_signal', 'persisted',
)
SOURCES = frozenset(('bing-rss', 'brave', 'github', 'hn', 'stackexchange'))
# Fixed public reason enum: unknown/private strings must not escape in reports.
REJECTION_REASONS = frozenset((
    'unknown', 'missing_url', 'routing_duplicate', 'query_irrelevant',
    'relevance_error', 'routing_limit', 'self_contamination_rejected',
    'noise_domain', 'github_noise', 'github_no_buyer_problem_context',
    'no_family', 'weak_family_relevance', 'context_too_short',
    'no_demand_signal', 'unjoined',
))
# These are independent instrumentation counters, not labels by humans.
# In cloud_mcp.ingest(), buyer_voice increments when the generic-web voice
# guard is not missing; it does not verify buyer identity on HN/GitHub.
STAGE_SEMANTICS = {
    'raw_received': 'provider_receipts',
    'query_relevant': 'query_relevance_counter',
    'family_matched': 'family_found_before_strength_and_context_checks',
    'buyer_voice': 'web_voice_guard_passed_or_was_not_applicable',
    'commercial_signal': 'signal_types_nonempty_not_commercial_gate_approval',
    'persisted': 'merged_or_appended_evidence_rows_not_new_qualified_buyers',
}


def nonnegative_integer(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f'invalid nonnegative integer: {label}')
    return value


def diagnose(snapshot):
    """Return only fixed labels and numeric aggregates, never source text or IDs."""
    if not isinstance(snapshot, dict) or snapshot.get('snapshot_schema') != 7:
        raise ValueError('expected snapshot schema 7')
    state = snapshot.get('autopilot')
    if not isinstance(state, dict):
        raise ValueError('autopilot state missing')
    selection = state.get('select_diagnostics')
    funnel = selection.get('funnel') if isinstance(selection, dict) else None
    if not isinstance(funnel, dict):
        raise ValueError('select funnel missing')

    values = [nonnegative_integer(funnel.get(k), k) for k in STAGES]
    if any(left < right for left, right in zip(values, values[1:])):
        raise ValueError('non-monotonic funnel: cannot interpret stage loss')
    transitions = [
        {'from': STAGES[i], 'to': STAGES[i+1],
         'input': values[i], 'output': values[i+1],
         'lost': values[i] - values[i+1],
         'retention_percent': round(100 * values[i+1] / values[i], 2) if values[i] else None}
        for i in range(len(STAGES) - 1)
    ]
    # Sorting uses only counts, and never implies that rejected rows are false negatives.
    priority = sorted(transitions, key=lambda x: (-x['lost'], STAGES.index(x['from'])))

    sources = selection.get('search_sources')
    if not isinstance(sources, list):
        raise ValueError('search source diagnostics missing')
    per_source = []
    for row in sources:
        if not isinstance(row, dict) or row.get('source') not in SOURCES:
            raise ValueError('unrecognized source diagnostic')
        per_source.append({
            'source': row['source'],
            **{k: nonnegative_integer(row.get(k), k)
               for k in ('attempts', 'raw_results', 'relevance_pass', 'errors')},
        })
    if len({row['source'] for row in per_source}) != len(per_source):
        raise ValueError('duplicate source summary')
    if sum(row['raw_results'] for row in per_source) != values[0]:
        raise ValueError('source totals disagree with funnel')

    reasons = funnel.get('discarded_by_reason')
    if not isinstance(reasons, list):
        raise ValueError('rejection reason aggregate missing')
    rejected = {}
    for item in reasons:
        if not isinstance(item, dict) or item.get('reason') not in REJECTION_REASONS:
            raise ValueError('invalid or unrecognized rejection reason')
        reason = item['reason']
        if reason in rejected:
            raise ValueError('duplicate rejection reason')
        rejected[reason] = nonnegative_integer(item.get('count'), 'rejection count')

    provider = selection.get('search_provider') or {}
    reasons = provider.get('fallback_reasons') or []
    budget_paced = sum(nonnegative_integer(item.get('count'), 'fallback count')
                       for item in reasons if isinstance(item, dict)
                       and item.get('reason') == 'budget_paced')
    observation = state.get('runtime_observation') or {}
    stalls = nonnegative_integer(observation.get('event_loop_stalls'), 'event_loop_stalls')
    max_lag = observation.get('event_loop_max_lag_ms')
    if type(max_lag) not in (float, int) or not (0 <= max_lag < 1e9):
        raise ValueError('invalid event loop max lag')
    if type(observation.get('codec_offthread')) is not bool:
        raise ValueError('invalid codec switch')

    return {
        'status': 'SHADOW_DIAGNOSTIC_ONLY',
        'snapshot_schema': 7,
        'production_state_write': False,
        'commercial_gate_influence': 'NONE',
        'automatic_promotion': False,
        'funnel': transitions,
        'stage_semantics': STAGE_SEMANTICS.copy(),
        'differences_are_verified_rejections': False,
        'buyer_voice_counter_is_verified_buyer': False,
        'rejection_reasons': [
            {'reason': key, 'count': rejected[key]}
            for key in sorted(rejected, key=lambda k: (-rejected[k], k))
        ],
        'rejections_not_directly_reconcilable_to_stage_differences': True,
        'largest_absolute_drop': {'from': priority[0]['from'],
                                  'to': priority[0]['to'],
                                  'lost': priority[0]['lost']},
        'sources': sorted(per_source, key=lambda row: row['source']),
        'brave_budget_paced_fallbacks': budget_paced,
        'event_loop': {'stalls': stalls, 'max_lag_ms': max_lag,
                       'codec_offthread': observation['codec_offthread']},
        'requires_independent_human_labels': True,
    }


def main():
    parser = argparse.ArgumentParser(description='Inspect existing snapshot without mutations')
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(json.loads(args.snapshot.read_text(encoding='utf-8')))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
