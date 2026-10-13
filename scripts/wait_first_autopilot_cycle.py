"""Read-only signed polling; logs contain only the explicit completion signal."""
import json
import os
import subprocess
import time
import urllib.request


def first_cycle_complete(status):
    ap = status.get('autopilot') or {}
    obs = ap.get('runtime_observation') or {}
    return obs.get('first_autopilot_cycle_completed') is True


def wait_first(fetch, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + 300
    while clock() < deadline:
        try:
            status = fetch(min(30, max(0.1, deadline - clock())))
            if first_cycle_complete(status):
                print('First autopilot cycle after startup completed', flush=True)
                return True
        except Exception:
            print('First-cycle status unavailable; bounded retry', flush=True)
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(5, remaining))
    return False


def fetch(timeout):
    deadline = time.monotonic() + timeout
    target = 'https://neo-collettive.onrender.com/api/autonomy/status'
    env = dict(os.environ, NEO_HEARTBEAT_TOKEN=os.environ.get('HEARTBEAT_TOKEN', ''))
    proof = subprocess.check_output(['python', 'self_traffic_auth.py', 'sign-url',
                                    target, '--marker', 'github-actions-deploy'], env=env, text=True, timeout=timeout).strip()
    req = urllib.request.Request(target, headers={
        'X-MYCELIX-Self-Traffic': 'github-actions-deploy',
        'X-MYCELIX-Self-Traffic-Proof': proof})
    with urllib.request.urlopen(req, timeout=max(0.01, deadline - time.monotonic())) as response:
        return json.load(response)


if __name__ == '__main__':
    if not wait_first(fetch):
        print('::warning::First autopilot cycle did not finish within 300 seconds')
        raise SystemExit(1)
