"""Observation only: bounded phase timings and stacks without values or source text."""
import asyncio
from contextlib import contextmanager
import functools
import inspect
import logging
from pathlib import Path
import sys
import threading
import time

PHASES = frozenset({
    'restore', 'restore_merge', 'migration', 'research', 'challenge_research',
    'gate', 'director', 'autopilot', 'checkpoint', 'checkpoint_payload',
    'checkpoint_compaction', 'checkpoint_json', 'checkpoint_zlib',
    'checkpoint_lzma', 'checkpoint_decode', 'checkpoint_local_write',
    'render_write', 'evidence_store_write', 'challenge_store_write',
    'commercial_gate', 'gate_hysteresis', 'seti', 'outcome',
})
LOG = logging.getLogger('neo.runtime_observation')
LOG.setLevel(logging.INFO)
if not LOG.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter('%(message)s'))
    LOG.addHandler(_handler)
LOG.propagate = False


class RuntimeObservation:
    def __init__(self, root=None, interval=0.25, threshold=2.0):
        self.root = Path(root or Path(__file__).parent).resolve()
        self.interval = interval
        self.threshold = threshold
        self._lock = threading.Lock()
        self._stats = {}
        self._stalls = 0
        self._max_lag = 0.0
        self._last_stack = []
        self._stop = threading.Event()
        self._thread = None
        self._task = None
        self._thread_id = None
        self._deadline = None
        self._sampled_deadline = None

    @contextmanager
    def phase(self, name):
        if name not in PHASES:
            raise ValueError('unregistered observation phase')
        wall = time.perf_counter()
        cpu = time.process_time()
        thread_cpu = time.thread_time()
        try:
            yield
        finally:
            duration = max(0.0, (time.perf_counter() - wall) * 1000)
            cpu_ms = max(0.0, (time.process_time() - cpu) * 1000)
            thread_ms = max(0.0, (time.thread_time() - thread_cpu) * 1000)
            with self._lock:
                row = self._stats.setdefault(name, {'count': 0, 'max_duration_ms': 0.0})
                row['count'] += 1
                row['last_duration_ms'] = round(duration, 3)
                row['last_process_cpu_ms'] = round(cpu_ms, 3)
                row['last_thread_cpu_ms'] = round(thread_ms, 3)
                row['max_duration_ms'] = round(max(row['max_duration_ms'], duration), 3)
            # Never format arguments, return values, exceptions or frame locals.
            LOG.info('runtime_phase phase=%s duration_ms=%.3f process_cpu_ms=%.3f thread_cpu_ms=%.3f',
                     name, duration, cpu_ms, thread_ms)

    def timed(self, name):
        def decorate(fn):
            if inspect.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def run(*args, **kwargs):
                    with self.phase(name):
                        return await fn(*args, **kwargs)
            else:
                @functools.wraps(fn)
                def run(*args, **kwargs):
                    with self.phase(name):
                        return fn(*args, **kwargs)
            return run
        return decorate

    def project_stack(self, frame):
        rows = []
        while frame is not None:
            code = frame.f_code
            try:
                relative = Path(code.co_filename).resolve().relative_to(self.root)
                # Exclude dependencies, observation machinery and caller locals.
                if relative.suffix == '.py' and relative.name != 'runtime_observation.py':
                    rows.append({'file': relative.as_posix(), 'function': code.co_name,
                                 'line': frame.f_lineno})
            except ValueError:
                pass
            frame = frame.f_back
        return rows[:12]

    def _sample(self):
        while not self._stop.wait(self.interval):
            deadline = self._deadline
            if deadline is None:
                continue
            lag = max(0.0, time.perf_counter() - deadline)
            if lag <= self.threshold:
                continue
            frame = sys._current_frames().get(self._thread_id)
            try:
                stack = self.project_stack(frame)
            finally:
                del frame
            with self._lock:
                self._max_lag = max(self._max_lag, lag * 1000)
                if stack:
                    self._last_stack = stack
            # At most one stack record per blocked heartbeat deadline.
            if self._sampled_deadline != deadline:
                self._sampled_deadline = deadline
                LOG.warning('event_loop_stack lag_ms=%.3f stack=%s', lag * 1000, stack)

    async def _heartbeat(self):
        while True:
            self._deadline = time.perf_counter() + self.interval
            await asyncio.sleep(self.interval)
            lag = max(0.0, time.perf_counter() - self._deadline) * 1000
            with self._lock:
                self._max_lag = max(self._max_lag, lag)
                if lag > self.threshold * 1000:
                    self._stalls += 1
            if lag > self.threshold * 1000:
                LOG.warning('event_loop_stall lag_ms=%.3f', lag)

    async def start(self):
        if self._task is not None:
            return
        self._thread_id = threading.get_ident()
        self._stop.clear()
        self._task = asyncio.create_task(self._heartbeat(), name='runtime-observation')
        self._thread = threading.Thread(target=self._sample, daemon=True,
                                        name='runtime-stack-observer')
        self._thread.start()
        # Arm the heartbeat before the first autopilot task can execute.
        await asyncio.sleep(0)

    async def close(self):
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._deadline = None
        # No join on the event loop: observer exits via Event.wait.

    def private_snapshot(self):
        with self._lock:
            return {'event_loop_stalls': self._stalls,
                    'event_loop_max_lag_ms': round(self._max_lag, 3),
                    'phases': {k: dict(v) for k, v in self._stats.items()},
                    'last_project_stack': [dict(x) for x in self._last_stack]}


OBSERVATION = RuntimeObservation()


def public_observation(value):
    """Numeric allowlist only; no stack, arbitrary phase name or text is public."""
    value = value if isinstance(value, dict) else {}
    def number(x):
        import math
        return round(max(0.0, float(x)), 3) if isinstance(x, (int, float)) and math.isfinite(x) else 0
    phases = value.get('phases') if isinstance(value.get('phases'), dict) else {}
    if not phases and isinstance(value.get('slowest_phases'), list):
        phases = {row.get('phase'): row for row in value['slowest_phases']
                  if isinstance(row, dict) and isinstance(row.get('phase'), str)}
    rows = [{'phase': name, 'max_duration_ms': number(row.get('max_duration_ms')),
             'last_duration_ms': number(row.get('last_duration_ms')),
             'last_process_cpu_ms': number(row.get('last_process_cpu_ms'))}
            for name, row in phases.items() if name in PHASES and isinstance(row, dict)]
    rows.sort(key=lambda x: x['max_duration_ms'], reverse=True)
    return {'event_loop_stalls': int(number(value.get('event_loop_stalls'))),
            'event_loop_max_lag_ms': number(value.get('event_loop_max_lag_ms')),
            'slowest_phases': rows[:5]}
