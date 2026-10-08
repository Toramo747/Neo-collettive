"""Read-only three-cycle acceptance; nonzero exit invokes the existing rollback."""
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_snapshot import sanitize_public_snapshot

ORIGIN = 'https://neo-collettive.onrender.com'


def project(status):
    state = status.get('autopilot') or {}
    if state.get('running') or not (state.get('runtime_observation') or {}).get('first_autopilot_cycle_completed'):
        return None
    latest = state.get('latest_result')
    if not isinstance(latest, dict):
        return None
    public = sanitize_public_snapshot({'autopilot': state, 'latest_result': latest})['autopilot']
    return {'cycle': int(state.get('cycles_completed') or 0),
            'ingestion_drought': public['select_diagnostics']['ingestion_drought'],
            'evidence_out': int((state.get('evidence_memory_telemetry') or {}).get('evidence_out') or 0),
            'stored_bytes': int((state.get('last_checkpoint') or {}).get('stored_bytes') or 0)}


def accept(sample, previous=None):
    drought = sample['ingestion_drought']
    if not drought['rows']:
        raise ValueError('empty_drought_rows')
    if drought.get('measurement_reliable') is not True or drought.get('unjoined_total') != 0:
        raise ValueError('unreliable_drought_measurement')
    if sample['evidence_out'] < 141:
        raise ValueError('evidence_regression')
    if not 0 < sample['stored_bytes'] < 75000:
        raise ValueError('checkpoint_budget_failed')
    if previous is not None and sample['cycle'] != previous['cycle'] + 1:
        raise ValueError('nonconsecutive_cycles')


def read(path, token):
    request = urllib.request.Request(ORIGIN + path, headers={
        'Authorization': 'Bearer ' + token, 'X-MYCELIX-Self-Traffic': 'github-actions-deploy'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    token = os.environ['NEO_ADMIN_TOKEN']
    expected = os.environ['GITHUB_SHA']
    deadline = time.monotonic() + 1320
    samples = []
    while time.monotonic() < deadline:
        if read('/health', token).get('commit') != expected:
            raise ValueError('production_commit_changed')
        sample = project(read('/api/autopilot/status', token))
        if sample is not None and (not samples or sample['cycle'] != samples[-1]['cycle']):
            # Persist only public numerical/boolean aggregates, including failure evidence.
            print(json.dumps(sample, separators=(',', ':')), flush=True)
            Path('/tmp/ingestion-deploy-observations.json').write_text(json.dumps(samples + [sample], indent=2))
            accept(sample, samples[-1] if samples else None)
            samples.append(sample)
            if len(samples) == 3:
                print('INGESTION_ACCEPTANCE three_consecutive_cycles_valid=true', flush=True)
                return
        time.sleep(15)
    raise ValueError('three_cycle_observation_timeout')


if __name__ == '__main__':
    main()
