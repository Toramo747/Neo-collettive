"""Bounded smoke retries; observation mode preserves evidence after final failure."""
import argparse
import os
import subprocess
import time
from pathlib import Path


def run_smoke(command, observation=False, runner=subprocess.run, sleep=time.sleep, failure_marker=None):
    for attempt in range(1, 4):
        print(f'surface_smoke attempt={attempt}/3', flush=True)
        result = runner(command)
        if result.returncode == 0:
            return 0
        if attempt < 3:
            sleep(20)
    if observation:
        if failure_marker:
            Path(failure_marker).touch()
        print('::warning::OBSERVATION_DEPLOY: surface smoke failed after 3 attempts; rollback skipped', flush=True)
        return 0
    return result.returncode or 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('script')
    args = parser.parse_args()
    raise SystemExit(run_smoke(['bash', args.script],
                     observation=os.getenv('OBSERVATION_DEPLOY') == 'true',
                     failure_marker='/tmp/neo-observation-smoke-failed'))
