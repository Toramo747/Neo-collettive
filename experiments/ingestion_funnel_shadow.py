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
