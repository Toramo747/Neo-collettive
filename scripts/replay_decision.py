#!/usr/bin/env python3
"""Offline receipt replay; prints field paths, never private field values."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zlib
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import decision_replay as dr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('trace')
    parser.add_argument('--commit', action='store_true', help='use the commit recorded in the trace')
    args = parser.parse_args()
    path = Path(args.trace).resolve()
    try:
        raw = path.read_bytes()
        if len(raw) > dr.MAX_RAW_BYTES: raise ValueError('trace_too_large')
        if path.name.endswith('.z'):
            d = zlib.decompressobj()
            raw = d.decompress(raw, dr.MAX_RAW_BYTES+1)
            if len(raw)>dr.MAX_RAW_BYTES or not d.eof or d.unused_data: raise ValueError('invalid_trace')
        trace = json.loads(raw)
        dr.validate(trace)
        if args.commit:
            commit = trace['commit']
            if not re.fullmatch('[0-9a-f]{40}', commit): raise ValueError('invalid_commit')
            repo = Path(__file__).resolve().parents[1]
            with tempfile.TemporaryDirectory() as root:
                tree = Path(root) / 'replay'
                added = False
                try:
                    subprocess.run(['git', 'worktree', 'add', '--detach', str(tree), commit], cwd=repo,
                                   check=True, capture_output=True)
                    added = True
                    script = tree / 'scripts/replay_decision.py'
                    if not script.is_file(): raise ValueError('recorded_commit_has_no_replay')
                    return subprocess.run([sys.executable, str(script), str(path)], cwd=tree).returncode
                finally:
                    if added: subprocess.run(['git','worktree','remove','--force',str(tree)], cwd=repo, capture_output=True)
        result = dr.replay(trace)
        print('IDENTICO' if result['identical'] else 'DIFF')
        for field in result['diff']: print(field)
        return 0 if result['identical'] else 1
    except Exception as exc:
        # Exceptions may contain input excerpts: never print exception values.
        print('REPLAY_RIFIUTATO ' + type(exc).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
