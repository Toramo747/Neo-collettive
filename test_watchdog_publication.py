import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import textwrap
import unittest


class WatchdogPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = Path('.github/workflows/mycelix-heartbeat-watchdog-v2.yml').read_text()

    def script(self, step, marker):
        section = self.workflow.split('      - name: ' + step, 1)[1]
        script = section.split("python - <<'" + marker + "'\n", 1)[1]
        return textwrap.dedent(script.split('\n          ' + marker, 1)[0])

    def run_script(self, script, files):
        with tempfile.TemporaryDirectory() as directory:
            for name, value in files.items():
                Path(directory, name).write_text(json.dumps(value))
            script = script.replace('/tmp/', directory + '/')
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(script, '<watchdog>', 'exec'), {})
            result = Path(directory, 'primary-active')
            return result.read_text() if result.exists() else None

    def freshness(self, age):
        script = self.script('Fail if runtime snapshot is older than 90 minutes', 'PY')
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=age)).isoformat()
        return self.run_script(script, {'snapshot.json': {'captured_at_utc': stamp}})

    def test_recent_published_snapshot_passes(self):
        self.freshness(89)

    def test_publication_older_than_90_minutes_fails(self):
        with self.assertRaisesRegex(SystemExit, 'no runtime snapshot published for more than 90 minutes'):
            self.freshness(91)

    def test_missing_invalid_and_future_timestamps_fail_closed(self):
        script = self.script('Fail if runtime snapshot is older than 90 minutes', 'PY')
        for value in (None, 'invalid', '2026-01-01T00:00:00'):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                self.run_script(script, {'snapshot.json': {'captured_at_utc': value}})
        with self.assertRaisesRegex(SystemExit, 'in the future'):
            self.freshness(-10)

    def test_running_or_queued_primary_is_not_cancelled(self):
        script = self.script('Dispatch primary heartbeat if runtime or snapshot is stale', 'PYRUN')
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        for status in ('queued', 'in_progress', 'waiting', 'pending', 'requested'):
            with self.subTest(status=status):
                self.assertEqual(self.run_script(script, {'primary-runs.json': {'workflow_runs': [
                    {'id': 1, 'status': status, 'created_at': stamp}
                ]}}), '1')

    def test_completed_or_expired_primary_allows_recovery(self):
        script = self.script('Dispatch primary heartbeat if runtime or snapshot is stale', 'PYRUN')
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=21)).isoformat()
        for runs in ([], [{'id': 1, 'status': 'in_progress', 'created_at': stamp}],
                     [{'id': 1, 'status': 'completed', 'created_at': stamp}]):
            self.assertEqual(self.run_script(script, {'primary-runs.json': {'workflow_runs': runs}}), '0')


if __name__ == '__main__':
    unittest.main()
