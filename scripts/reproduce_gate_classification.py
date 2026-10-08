"""Synthetic offline replay of the captured challenge routing path; no runtime data."""
import asyncio
import cProfile
import json
import os
from pathlib import Path
import pstats
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evidence_integrity as evidence
from challenge_track import route_challenge_evidence
from runtime_observation import RuntimeObservation
from test_family_classification_performance import original_scores


async def measure(scorer):
    observer = RuntimeObservation(interval=0.01, threshold=0.2)
    body = ('unrelated context ' * 4000)[:65500] + ' invoices manual workflow csv files'
    rows = [{'url': f'https://github.com/example/repo/issues/{i}',
             'title': 'Feature request: export dependency graph', 'body': body,
             'source': 'github-issues-routed', 'metadata': {'labels': ['feature request']},
             'now_epoch': 1800000000} for i in range(24)]
    await observer.start()
    profile = cProfile.Profile()
    try:
        start, cpu = time.perf_counter(), time.process_time()
        with patch.object(evidence, 'commercial_family_scores', scorer):
            profile.enable()
            outputs = [route_challenge_evidence(**row) for row in rows]
            profile.disable()
        duration = (time.perf_counter() - start) * 1000
        cpu_ms = (time.process_time() - cpu) * 1000
        await asyncio.sleep(0.03)
        stat = pstats.Stats(profile)
        regex = [(v[0], v[2]) for k, v in stat.stats.items()
                 if 'search' in k[2] and 're.Pattern' in k[2]]
        return {'wall_ms': round(duration, 3), 'cpu_ms': round(cpu_ms, 3),
                'regex_search_calls': sum(n for n, _ in regex),
                'regex_search_cpu_ms': round(sum(t for _, t in regex) * 1000, 3),
                'event_loop_max_lag_ms': observer.private_snapshot()['event_loop_max_lag_ms']}, outputs
    finally:
        await observer.close()


async def main():
    original, before = await measure(original_scores)
    improved, after = await measure(evidence.commercial_family_scores)
    if before != after:
        raise SystemExit('Classification decisions changed')
    print(json.dumps({'synthetic': True, 'cpu_affinity_count': len(os.sched_getaffinity(0)),
                      'rows': 24, 'body_characters': 65535, 'outputs_identical': True,
                      'full_autopilot_replayed': False, 'render_quota_simulated': False,
                      'before': original, 'after': improved}, indent=2))


if __name__ == '__main__':
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    asyncio.run(main())
