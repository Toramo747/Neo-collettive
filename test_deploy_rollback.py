import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.deploy_rollback import rollback_allowed, revert_failed


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.failed = self.commit('app.py', 'base')

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], text=True).strip()

    def commit(self, path, value):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(value)
        self.git('add', '.')
        self.git('commit', '-qm', 'test')
        return self.git('rev-parse', 'HEAD')

    def test_same_commit_allowed(self):
        self.assertTrue(rollback_allowed(self.failed))

    def test_snapshot_and_arena_commits_allowed(self):
        for path in ('neo_latest_result.json', 'neo_cycle_floor.json', 'data/arena/latest.json'):
            self.commit(path, '{}')
        self.assertTrue(rollback_allowed(self.failed))

    def test_application_change_blocks_even_when_later_undone(self):
        self.commit('app.py', 'new')
        self.commit('app.py', 'base')
        self.assertFalse(rollback_allowed(self.failed))

    def test_mixed_commit_blocks(self):
        Path('neo_latest_result.json').write_text('{}')
        self.commit('app.py', 'new')
        self.assertFalse(rollback_allowed(self.failed))

    def test_unrelated_path_blocks(self):
        self.commit('data/other.json', '{}')
        self.assertFalse(rollback_allowed(self.failed))

    def test_real_revert_preserves_later_snapshots(self):
        failed = self.commit('app.py', 'failed')
        self.commit('neo_latest_result.json', '{"cycle":2}')
        self.commit('data/arena/latest.json', '{"generation":3}')
        self.assertTrue(revert_failed(failed))
        self.assertEqual(Path('app.py').read_text(), 'base')
        self.assertEqual(Path('neo_latest_result.json').read_text(), '{"cycle":2}')
        self.assertEqual(Path('data/arena/latest.json').read_text(), '{"generation":3}')

    def test_real_revert_skipped_after_new_code(self):
        failed = self.commit('app.py', 'failed')
        current = self.commit('app.py', 'newer')
        self.assertFalse(revert_failed(failed))
        self.assertEqual(self.git('rev-parse', 'HEAD'), current)
        self.assertEqual(Path('app.py').read_text(), 'newer')

    def test_real_merge_revert_uses_first_parent(self):
        main = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'feature')
        self.commit('app.py', 'failed')
        self.git('checkout', '-q', main)
        self.git('merge', '--no-ff', '-qm', 'merge feature', 'feature')
        failed = self.git('rev-parse', 'HEAD')
        self.commit('neo_cycle_floor.json', '{"cycle":3}')
        self.assertTrue(revert_failed(failed))
        self.assertEqual(Path('app.py').read_text(), 'base')
        self.assertEqual(Path('neo_cycle_floor.json').read_text(), '{"cycle":3}')
