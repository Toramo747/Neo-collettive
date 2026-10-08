"""Local synthetic checkpoint replay: no runtime backup, credentials or network."""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_observation import OBSERVATION
from state_codec import decode_checkpoint, encode_checkpoint


async def replay(mib, passes):
    # 3 MiB matches the raw checkpoint size observed in the prior compaction
    # regression. Content is deterministic, synthetic and incompressible enough
    # to exercise both existing compression branches.
    rng = random.Random(214)
    payload = {'synthetic_history': rng.randbytes(mib * 1024 * 1024 // 2).hex()}
    encoded, raw_bytes, _ = encode_checkpoint(payload, 32 * 1024 * 1024)
    await OBSERVATION.start()
    try:
        with OBSERVATION.phase('autopilot'):
            with OBSERVATION.phase('restore'):
                restored = decode_checkpoint(encoded)
            for _ in range(passes):
                encode_checkpoint(restored, 32 * 1024 * 1024)
        await asyncio.sleep(0.3)
        return {'raw_bytes': raw_bytes, 'encoding_passes': passes,
                'cpu_affinity_count': len(os.sched_getaffinity(0)),
                'synthetic': True, 'production_cause_proven': False,
                'observation': OBSERVATION.private_snapshot()}
    finally:
        await OBSERVATION.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mib', type=int, default=3, choices=range(1, 25))
    parser.add_argument('--passes', type=int, default=3, choices=range(1, 21))
    args = parser.parse_args()
    # Restrict this local subprocess to one available CPU. This is not a
    # simulation of Render's 0.15-core quota, and results must say so.
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(json.dumps(asyncio.run(replay(args.mib, args.passes)), indent=2))
