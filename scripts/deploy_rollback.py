"""Determine whether a failed deploy can be reverted past snapshot-only commits."""
import argparse
import subprocess


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def snapshot_only(paths):
    return bool(paths) and all(
        p in {'neo_latest_result.json', 'neo_cycle_floor.json'}
        or p.startswith('data/arena/') for p in paths
    )


def rollback_allowed(failed, current='HEAD'):
    if subprocess.run(['git', 'merge-base', '--is-ancestor', failed, current],
                      capture_output=True).returncode:
        return False
    for commit in git('rev-list', f'{failed}..{current}').splitlines():
        # Inspect each commit, not the net diff: an application change followed
        # by its revert is still a newer application deployment to preserve.
        paths = git('diff-tree', '--no-commit-id', '--name-only', '-r',
                    f'{commit}^1', commit).splitlines()
        if not snapshot_only(paths):
            return False
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('failed')
    parser.add_argument('--current', default='HEAD')
    args = parser.parse_args()
    allowed = rollback_allowed(args.failed, args.current)
    print('allowed' if allowed else 'newer_application_commit')
    raise SystemExit(0 if allowed else 3)
