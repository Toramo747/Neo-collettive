"""Offline replay of the sampled intent path; synthetic bodies, no runtime data."""
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
from runtime_observation import RuntimeObservation
from test_intent_classification_performance import original_contains_term


async def measure(matcher):
    body = ('unrelated context ' * 4000)[:65500] + ' invoices manual workflow csv files'
    observer = RuntimeObservation(interval=0.01, threshold=0.2)
    await observer.start()
    profiler = cProfile.Profile()
    try:
        start, cpu = time.perf_counter(), time.process_time()
        with patch.object(evidence, 'contains_term', matcher):
            profiler.enable()
            outputs = [evidence.classify_intent_class(
                'Feature request: export dependency graph', body,
                'https://example.test/issues/1', 'brave-search') for _ in range(24)]
            profiler.disable()
        wall_ms, cpu_ms = (time.perf_counter()-start)*1000, (time.process_time()-cpu)*1000
        await asyncio.sleep(0.03)
        stats = pstats.Stats(profiler)
        regex = [(v[0], v[2]) for k, v in stats.stats.items()
                 if 'search' in k[2] and 're.Pattern' in k[2]]
        return {'wall_ms': round(wall_ms, 3), 'cpu_ms': round(cpu_ms, 3),
                'regex_search_calls': sum(n for n, _ in regex),
                'regex_search_cpu_ms': round(sum(t for _, t in regex)*1000, 3),
                'event_loop_max_lag_ms': observer.private_snapshot()['event_loop_max_lag_ms']}, outputs
    finally:
        await observer.close()


async def main():
    before, original = await measure(original_contains_term)
    after, improved = await measure(evidence.contains_term)
    if original != improved: raise SystemExit('Intent decisions changed')
    print(json.dumps({'synthetic': True, 'cpu_affinity_count': len(os.sched_getaffinity(0)),
                      'rows': 24, 'body_characters': 65535, 'outputs_identical': True,
                      'full_autopilot_replayed': False, 'render_quota_simulated': False,
                      'before': before, 'after': after}, indent=2))


if __name__ == '__main__':
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    asyncio.run(main())
