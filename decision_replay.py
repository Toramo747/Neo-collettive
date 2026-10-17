"""Private, versioned decision receipts. No logging and no checkpoint state."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import zlib

import gate_stability as gate
import tool_opportunity as scoring
import price_validation as pricing

SCHEMA_V = 1
MAX_RAW_BYTES = 16 * 1024 * 1024
LOCK = threading.RLock()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def config():
    def value(x):
        if isinstance(x, re.Pattern): return {'pattern': x.pattern, 'flags': x.flags}
        if isinstance(x, (set, frozenset)): return sorted(value(v) for v in x)
        if isinstance(x, (list, tuple)): return [value(v) for v in x]
        if isinstance(x, dict): return {k: value(v) for k, v in x.items()}
        return x
    return {m.__name__: {k: value(v) for k, v in vars(m).items()
                        if k.isupper()}
            for m in (scoring, gate, pricing)} | {
        'category_order': list(scoring.CATEGORY_CONFIGS),
        'environment': {k: os.getenv(k) for k in ('TZ', 'NEO_GATE_CONFIRM_FAIL_RESET', 'NEO_GATE_CONFIRM_MIN_PASS_RATIO')},
    }


def begin(*, web_research, query_meta, demand_evidence, seti_catalog,
          price_cache, persisted_insert_at, source_diagnostics, usage_evidence,
          hysteresis, now, cycle, first_cycle_after_deploy, commit,
          version, tagger_version, policy_version, genome_id, guards):
    # Freeze BEFORE any scorer or hysteresis mutations.
    datetime.fromisoformat(now.replace('Z', '+00:00'))
    values = locals().copy()
    values['config'] = config()
    values['python_hash_seed'] = os.getenv('PYTHONHASHSEED', 'random')
    return {'schema_v': SCHEMA_V, 'commit': commit, 'tagger_version': tagger_version,
            'policy_version': policy_version, 'config_fingerprint': digest(values['config']),
            'cycle': cycle, 'first_cycle_after_deploy': first_cycle_after_deploy,
            'now': now, 'inputs': deepcopy(values)}


def observer(sink):
    def receive(component):
        try:
            sink.append(deepcopy(component))
        except Exception:
            BUFFER.failed = True
    return receive


def output(analysis, state, rows, components=None):
    indexed = {r['family']: r for r in rows}
    candidates = []
    for component in components or []:
        row = indexed.get(component['family'])
        candidates.append({**deepcopy(component),
            'stable_gate_pass': row['stable_gate_pass'] if row else None,
            'hysteresis_evaluated': row is not None})
    return {'analysis': deepcopy(analysis), 'hysteresis': deepcopy(state),
            'stable_rows': deepcopy(rows), 'candidates': candidates}


def evaluate(inputs):
    i = deepcopy(inputs)
    if i['config'] != config():
        raise ValueError('configuration_mismatch')
    # Replace cached-price groups at their ORIGINAL insertion point. Current
    # cycle fresh prices remain fresh inputs, never retroactively cached.
    web = [g for g in i['web_research'] if not g.get('_persisted_price_family')]
    meta = {k: v for k, v in i['query_meta'].items()
            if v.get('query_intent') != 'persisted_verified_competitor_price'}
    cached = pricing.persisted_price_groups(i['price_cache'])
    at = i['persisted_insert_at']
    web[at:at] = cached
    for group in cached:
        q = group['query']
        meta[' '.join(q.split()).lower()] = {
            'query': q, 'class': 'tool_market_validation', 'role': 'price_validation',
            'family': group['_persisted_price_family'],
            'query_intent': 'persisted_verified_competitor_price', 'validation_kind': 'persisted_strict'}
    components = []
    analysis = scoring.analyze_tool_opportunities(web, i['demand_evidence'], i['seti_catalog'], meta,
        now_utc=i['now'], source_diagnostics=i['source_diagnostics'], usage_evidence=i['usage_evidence'],
        decision_observer=observer(components))
    state, rows = gate.apply_gate_hysteresis(i['hysteresis'], analysis['top5'],
        version=i['version'], commit=i['commit'], observed_at_utc=i['now'], cycle=i['cycle'],
        tagger_version=i['tagger_version'], genome_id=i['genome_id'],
        first_cycle_after_deploy=i['first_cycle_after_deploy'])
    return output(analysis, state, rows, components)


def differences(a, b, path='output'):
    if type(a) is not type(b): return [path]
    if isinstance(a, dict):
        return [p for k in sorted(set(a) | set(b)) for p in
                ([path+'.'+k] if k not in a or k not in b else differences(a[k], b[k], path+'.'+k))]
    if isinstance(a, list):
        return ([path+'.length'] if len(a) != len(b) else []) + [p for n, (x, y) in enumerate(zip(a,b))
                for p in differences(x, y, f'{path}[{n}]')]
    return [] if a == b else [path]


def validate(trace):
    if trace.get('schema_v') != SCHEMA_V: raise ValueError('unsupported_schema')
    if digest(trace['inputs']) != trace['input_hash']: raise ValueError('input_integrity_failed')
    if digest(trace['output']) != trace['output_hash']: raise ValueError('output_integrity_failed')
    if digest(trace['inputs']['config']) != trace['config_fingerprint']: raise ValueError('config_integrity_failed')
    for key in ('commit', 'tagger_version', 'policy_version', 'cycle', 'first_cycle_after_deploy', 'now'):
        if trace[key] != trace['inputs'][key]: raise ValueError('metadata_integrity_failed')


def replay(trace):
    validate(trace)
    result = evaluate(trace['inputs'])
    return {'identical': digest(result) == trace['output_hash'], 'output_hash': digest(result),
            'diff': differences(trace['output'], result)}


class TraceBuffer:
    """20 compressed receipts, atomic 0600 files in a private 0700 directory.

    Set NEO_DECISION_TRACE_DIR to an existing durable private mount for restart
    continuity. Default /tmp survives process restart only, not container deploy.
    """
    def __init__(self, directory=None):
        self.directory = Path(directory or os.getenv('NEO_DECISION_TRACE_DIR', '/tmp/neo-decision-traces'))
        self.failed = False

    def paths(self):
        return sorted(self.directory.glob('*.trace.z'))

    def save(self, trace):
        raw = encoded(trace)
        if len(raw) > MAX_RAW_BYTES: raise ValueError('trace_too_large')
        data = zlib.compress(raw, 9)
        with LOCK:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.directory, 0o700)
            name = f"{int(trace['cycle']):020d}-{trace['input_hash'][:16]}.trace.z"
            fd, tmp = tempfile.mkstemp(dir=self.directory, prefix='.pending-')
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(data); f.flush(); os.fsync(f.fileno())
                os.replace(tmp, self.directory / name)
                for p in self.paths()[:-20]: p.unlink()
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
            self.failed = False

    def read(self, name):
        if not re.fullmatch(r'\d{20}-[0-9a-f]{16}\.trace\.z', name): raise ValueError('invalid_trace_id')
        with LOCK:
            decoder = zlib.decompressobj()
            raw = decoder.decompress((self.directory / name).read_bytes(), MAX_RAW_BYTES+1)
            if len(raw)>MAX_RAW_BYTES or not decoder.eof or decoder.unused_data: raise ValueError('invalid_trace')
            trace = json.loads(raw)
            validate(trace)
            return trace

    def public(self):
        try:
            paths = self.paths()
            last = self.read(paths[-1].name) if paths else {}
            return {'trace_count': len(paths), 'last_trace_cycle': int(last.get('cycle', 0)),
                    'input_hash': last.get('input_hash', '')[:16], 'output_hash': last.get('output_hash', '')[:16],
                    'replay_ok': bool(last.get('replay_ok')) and not self.failed}
        except Exception:
            return {'trace_count': 0, 'last_trace_cycle': 0, 'input_hash': '', 'output_hash': '', 'replay_ok': False}


BUFFER = TraceBuffer()


def finish(trace, analysis, state, rows, components=None):
    if trace is None: return
    try:
        trace['output'] = output(analysis, state, rows, components)
        trace['input_hash'] = digest(trace['inputs'])
        trace['output_hash'] = digest(trace['output'])
        trace['replay_ok'] = replay(trace)['identical']
        BUFFER.save(trace)
    except Exception:
        BUFFER.failed = True
