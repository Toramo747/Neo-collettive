import os
import secrets
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from starlette.testclient import TestClient
from relay_render import RenderRelay, NAMESPACE, database_check, storage_paths
from relay_render_backup import backup_database


def synthetic_peer(previous, text):
    n = previous.get('round', 0) + 1
    return {'round': n, 'commercial_influence': 'NONE'}, 'Synthetic question ' + str(n)


class RenderRelayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {'MYCELIX_RELAY_ENABLED': '1', 'MYCELIX_RELAY_STORAGE_CONFIRMED': '1',
                    'MYCELIX_RELAY_DISK_PATH': str(self.root), 'MYCELIX_RELAY_INVITE': 'i' * 40}
        self.token = secrets.token_urlsafe(32)
        self.headers = {'Authorization': 'Bearer ' + self.token, 'X-Mycelix-Relay-Invite': 'i' * 40}
        self.mount = patch('relay_render.os.path.ismount', return_value=True)
        self.mount.start()
        self.addCleanup(self.mount.stop)
        self.addCleanup(self.tmp.cleanup)

    def make(self, env=None):
        return RenderRelay(self.env if env is None else env, engine=synthetic_peer)

    def enroll(self, client):
        r = client.post('/api/relay/threads', headers=self.headers,
                        json={'agent_id': 'synthetic-render-pilot', 'message_id': 'intro-1', 'text': 'test intro'})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def test_disabled_never_touches_database(self):
        with patch('relay_render.storage_paths', side_effect=AssertionError('must not touch disk')):
            with TestClient(self.make({})) as c:
                r = c.get('/health')
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()['mode'], 'disabled')
                self.assertFalse(r.json()['storage_ready'])
                self.assertEqual(c.get('/api/relay/info').status_code, 503)

    def test_missing_mount_fails_closed(self):
        with patch('relay_render.os.path.ismount', return_value=False):
            with TestClient(self.make()) as c:
                self.assertEqual(c.get('/health').status_code, 503)
                self.assertEqual(c.get('/api/relay/info').status_code, 503)
            self.assertFalse((self.root / 'mycelix-relay').exists())

    def test_missing_operator_confirmation_rejected(self):
        self.env['MYCELIX_RELAY_STORAGE_CONFIRMED'] = '0'
        with TestClient(self.make()) as c:
            self.assertEqual(c.get('/health').status_code, 503)

    def test_invalid_flag_not_silently_healthy(self):
        self.env['MYCELIX_RELAY_ENABLED'] = 'ture'
        with TestClient(self.make()) as c:
            self.assertEqual(c.get('/health').status_code, 503)

    def test_missing_invite_rejected(self):
        self.env.pop('MYCELIX_RELAY_INVITE')
        with TestClient(self.make()) as c:
            self.assertEqual(c.get('/health').status_code, 503)

    def test_real_directory_and_database_permissions(self):
        a = self.make()
        self.assertTrue(a.ready)
        self.assertEqual(a.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(a.path.stat().st_mode & 0o777, 0o600)

    def test_private_symlink_rejected(self):
        (self.root / 'mycelix-relay').symlink_to(self.root, target_is_directory=True)
        self.assertFalse(self.make().ready)

    def test_database_symlink_rejected(self):
        p = self.root / 'mycelix-relay'
        p.mkdir(mode=0o700)
        (p / 'relay.sqlite3').symlink_to(self.root / 'victim')
        self.assertFalse(self.make().ready)
        self.assertFalse((self.root / 'victim').exists())

    def test_disk_root_and_relative_path_rejected(self):
        for root in ('/', 'var/data', str(self.root / '..' / self.root.name)):
            with self.subTest(root=root):
                self.env['MYCELIX_RELAY_DISK_PATH'] = root
                self.assertFalse(self.make().ready)

    def test_health_is_sanitized_and_rollback_only(self):
        a = self.make()
        with TestClient(a) as c:
            self.enroll(c)
            r = c.get('/health')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()['mode'], 'ready')
            for secret in (self.token, 'i' * 40, str(self.root), 'synthetic-render-pilot'):
                self.assertNotIn(secret, r.text)
        db = sqlite3.connect(a.path)
        try:
            self.assertIsNone(db.execute("SELECT value FROM metadata WHERE key='render_health_probe'").fetchone())
        finally:
            db.close()

    def test_original_application_endpoints_not_exposed(self):
        with TestClient(self.make()) as c:
            for path in ('/', '/a2a', '/api/autopilot/status', '/api/render/diagnostics', '/api/admin/seti-interviews'):
                self.assertEqual(c.get(path).status_code, 404)

    def test_recreation_preserves_messages_ack_and_replay(self):
        a = self.make()
        with TestClient(a) as c:
            first = self.enroll(c)
            tid = first['thread_id']
            c.post('/api/relay/threads/' + tid + '/ack', headers=self.headers, json={'through': 2})
        with TestClient(self.make()) as c:
            r = c.get('/api/relay/threads/' + tid + '/poll', headers=self.headers).json()
            self.assertEqual(r['messages'][0], first['message'])
            self.assertEqual(r['acknowledged_through'], 2)
            self.assertEqual(self.enroll(c), first)
            data = {'message_id': 'reply-1', 'in_reply_to': 2, 'text': 'answer'}
            second = c.post('/api/relay/threads/' + tid + '/reply', headers=self.headers, json=data).json()
            self.assertEqual(second['message']['sequence'], 4)
        with TestClient(self.make()) as c:
            replay = c.post('/api/relay/threads/' + tid + '/reply', headers=self.headers, json=data).json()
            self.assertEqual(replay, second)
            self.assertEqual(replay['state']['round'], 2)

    def test_missing_existing_database_never_reset(self):
        a = self.make()
        a.path.unlink()
        with TestClient(self.make()) as c:
            self.assertEqual(c.get('/health').status_code, 503)
        self.assertFalse(a.path.exists())

    def test_database_removed_during_operation_fails_without_recreating(self):
        a = self.make()
        with TestClient(a) as c:
            first = self.enroll(c)
            a.path.unlink()
            self.assertEqual(c.get('/health').status_code, 503)
            self.assertEqual(c.get('/api/relay/threads/' + first['thread_id'] + '/poll', headers=self.headers).status_code, 503)
            self.assertFalse(a.path.exists())

    def test_database_replaced_while_running_rejected(self):
        a = self.make()
        copy = backup_database(a.path, a.path.parent / 'backups', NAMESPACE)
        os.replace(copy, a.path)
        with TestClient(a) as c:
            self.assertEqual(c.get('/health').status_code, 503)

    def test_mount_loss_after_start_is_unhealthy(self):
        a = self.make()
        with patch('relay_render.os.path.ismount', return_value=False):
            with TestClient(a) as c:
                self.assertEqual(c.get('/health').status_code, 503)

    def test_wrong_database_namespace_is_not_modified(self):
        a = self.make()
        with closing(sqlite3.connect(a.path)) as db:
            db.execute("UPDATE metadata SET value='foreign' WHERE key='namespace'")
            db.commit()
        before = a.path.read_bytes()
        self.assertFalse(self.make().ready)
        self.assertEqual(a.path.read_bytes(), before)

    def test_corrupt_database_preserved_for_recovery(self):
        a = self.make()
        a.path.write_bytes(b'not a sqlite database')
        self.assertFalse(self.make().ready)
        self.assertEqual(a.path.read_bytes(), b'not a sqlite database')

    def test_backup_contains_committed_data_and_no_plaintext_token(self):
        a = self.make()
        with TestClient(a) as c:
            first = self.enroll(c)
        copy = backup_database(a.path, a.path.parent / 'backups', NAMESPACE)
        self.assertEqual(copy.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.token.encode(), copy.read_bytes())
        with closing(sqlite3.connect(copy)) as db:
            self.assertEqual(db.execute('SELECT id FROM threads').fetchone()[0], first['thread_id'])
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0], 'ok')

    def test_backup_rotation_bounded_and_unrelated_files_preserved(self):
        a = self.make()
        directory = a.path.parent / 'backups'
        directory.mkdir(mode=0o700)
        (directory / 'operator-note.txt').write_text('keep')
        for _ in range(5):
            backup_database(a.path, directory, NAMESPACE)
        self.assertEqual(len(list(directory.glob('relay-*.sqlite3'))), 3)
        self.assertTrue((directory / 'operator-note.txt').exists())

    def test_backup_failure_blocks_activation_not_main(self):
        a = self.make()
        with patch('relay_render.backup_database', side_effect=OSError('private details')):
            with TestClient(self.make()) as c:
                r = c.get('/health')
                self.assertEqual(r.status_code, 503)
                self.assertNotIn('private details', r.text)
        self.assertTrue(a.path.is_file())

    def test_database_check_never_creates_missing_database(self):
        p = self.root / 'missing.sqlite3'
        with self.assertRaises(ValueError):
            database_check(p)
        self.assertFalse(p.exists())

    def test_same_credentials_on_another_thread_denied(self):
        with TestClient(self.make()) as c:
            first = self.enroll(c)
            h = dict(self.headers, Authorization='Bearer ' + secrets.token_urlsafe(32))
            r = c.get('/api/relay/threads/' + first['thread_id'] + '/poll', headers=h)
            self.assertEqual(r.status_code, 401)


if __name__ == '__main__':
    unittest.main()
