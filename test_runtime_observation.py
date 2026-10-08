import asyncio
import base64
import json
import lzma
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import zlib

from runtime_observation import RuntimeObservation, public_observation
from state_codec import encode_checkpoint
from public_snapshot import sanitize_public_snapshot, validate_public_snapshot


def simulated_cpu_phase():
    deadline = time.perf_counter() + 0.18
    while time.perf_counter() < deadline:
        sum(i * i for i in range(1000))


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocking_function_is_captured_during_stall(self):
        observer = RuntimeObservation(interval=0.01, threshold=0.04)
        await observer.start()
        try:
            with observer.phase('gate'):
                simulated_cpu_phase()
            await asyncio.sleep(0.02)
            result = observer.private_snapshot()
            self.assertEqual(result['event_loop_stalls'], 1)
            self.assertGreater(result['event_loop_max_lag_ms'], 100)
            self.assertTrue(any(x['function'] == 'simulated_cpu_phase'
                                for x in result['last_project_stack']))
            self.assertGreater(result['phases']['gate']['last_process_cpu_ms'], 50)
        finally:
            await observer.close()

    async def test_waiting_async_io_is_not_a_stall(self):
        observer = RuntimeObservation(interval=0.01, threshold=0.1)
        await observer.start()
        try:
            await asyncio.sleep(0.16)
            self.assertEqual(observer.private_snapshot()['event_loop_stalls'], 0)
        finally:
            await observer.close()

    async def test_return_and_exception_semantics_are_unchanged(self):
        observer = RuntimeObservation()
        result = object()
        @observer.timed('gate')
        def sync():
            return result
        @observer.timed('research')
        async def async_fn():
            return result
        @observer.timed('checkpoint')
        async def cancelled():
            raise asyncio.CancelledError()
        self.assertIs(sync(), result)
        self.assertIs(await async_fn(), result)
        with self.assertRaises(asyncio.CancelledError):
            await cancelled()
        self.assertEqual(observer.private_snapshot()['phases']['checkpoint']['count'], 1)

    def test_public_projection_excludes_stack_values_and_arbitrary_names(self):
        private = {'event_loop_stalls': 2, 'event_loop_max_lag_ms': 2345,
                   'last_project_stack': [{'file': 'secret.py', 'function': 'sensitive'}],
                   'phases': {'gate': {'max_duration_ms': 2100, 'args': 'https://private.example'},
                              'private.example': {'max_duration_ms': 9000}}}
        result = public_observation(private)
        self.assertEqual(result, public_observation(result))
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('example', json.dumps(result))
        snapshot = sanitize_public_snapshot({'autopilot': {'runtime_observation': private}})
        validate_public_snapshot(snapshot)
        self.assertEqual(snapshot['autopilot']['runtime_observation'], result)

    def test_instrumented_codec_is_byte_identical_to_original(self):
        payload = {'rows': ['synthetic-value-%d' % i for i in range(30000)]}
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
        value = 'zlib64:' + base64.b64encode(zlib.compress(raw, 9)).decode()
        if len(value) > min(60000, 4000000):
            alternative = 'xz64:' + base64.b64encode(lzma.compress(raw, preset=3)).decode()
            if len(alternative) < len(value):
                value = alternative
        self.assertEqual(encode_checkpoint(payload, 4000000), (value, len(raw), len(value)))
