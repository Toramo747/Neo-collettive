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


def _changed_paths(a, b):
    return set(git('diff', '--name-only', a, b).splitlines())


def revert_failed(failed):
    """Revert only if HEAD still contains no newer application commit.

    2026-10-13 incident: a shallow fetch (--depth=1) earlier in the deploy job
    made the failed commit look parentless, so `git revert` produced the EMPTY
    tree and deleted every file on main. Guards: never revert a commit whose
    parent is not available, and never push a revert that touches paths the
    failed commit did not change."""
    if git('rev-parse', '--is-shallow-repository') == 'true':
        return False
    if not rollback_allowed(failed):
        return False
    parents = git('rev-list', '--parents', '-n', '1', failed).split()[1:]
    if not parents:
        return False
    args = ['revert', '--no-edit']
    if len(parents) > 1:
        args += ['-m', '1']
    before = git('rev-parse', 'HEAD')
    git(*args, failed)
    expected = _changed_paths(parents[0], failed)
    touched = _changed_paths(before, 'HEAD')
    if not touched or not touched <= expected or not git('ls-tree', 'HEAD'):
        git('reset', '--hard', before)
        return False
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('failed')
    parser.add_argument('--current', default='HEAD')
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    if args.revert and args.current != 'HEAD':
        parser.error('--revert requires current HEAD')
    if args.revert:
        reverted = revert_failed(args.failed)
        print('reverted' if reverted else 'newer_application_commit')
        raise SystemExit(0 if reverted else 3)
    allowed = rollback_allowed(args.failed, args.current)
    print('allowed' if allowed else 'newer_application_commit')
    raise SystemExit(0 if allowed else 3)
