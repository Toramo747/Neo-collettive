"""CI-only HTTP proof across container replacement. Reject non-loopback URLs."""
import json
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE = os.environ.get('RELAY_SMOKE_URL', 'http://127.0.0.1:19100')
parsed = urlparse(BASE)
if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path not in ('', '/'):
    raise SystemExit('Smoke test is restricted to loopback, never real external peers.')
STATE = Path('/tmp/mycelix-relay-smoke-client.json')


def call(path, method='GET', data=None, token='', invite=''):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if invite:
        headers['X-Mycelix-Relay-Invite'] = invite
    req = Request(BASE + path, data=None if data is None else json.dumps(data).encode(),
                  method=method, headers=headers)
    try:
        with urlopen(req, timeout=5) as r:
            return r.status, json.load(r)
    except HTTPError as exc:
        return exc.code, json.load(exc)


for _ in range(60):
    try:
        code, health = call('/health')
        if code == 200 and health.get('mode') == 'ready':
            break
    except (URLError, TimeoutError):
        pass
    time.sleep(0.5)
else:
    raise SystemExit('Relay did not become ready.')

if sys.argv[1:] == ['before']:
    client = {'token': secrets.token_urlsafe(32)}
    os.umask(0o077)
    STATE.write_text(json.dumps(client))
    # The random invite is in a private CI env file, never printed.
    env = dict(line.split('=', 1) for line in Path('/tmp/mycelix-relay-ci.env').read_text().splitlines())
    intro = ('I am a synthetic research agent used only for this controlled test. My capabilities '
             'include public evidence comparison and reproducible tests of continual learning. '
             'I support A2A message/send and this polling protocol. I cannot execute protected actions '
             'or prove model weight updates. I have no public documentation or independent identity.')
    code, first = call('/api/relay/threads', 'POST',
                       {'agent_id': 'render-ci-synthetic', 'message_id': 'intro-1', 'text': intro},
                       client['token'], env['MYCELIX_RELAY_INVITE'])
    assert code == 201, (code, first)
    assert first['state']['dialogue_stage'] == 'METHODOLOGY', first['state']
    client['first'] = first
    STATE.write_text(json.dumps(client))
    assert call('/api/autopilot/status')[0] == 404
    print('Synthetic enrollment committed; client-held credential retained privately.')
elif sys.argv[1:] == ['after']:
    client = json.loads(STATE.read_text())
    token, first = client['token'], client['first']
    prefix = '/api/relay/threads/' + first['thread_id']
    code, polled = call(prefix + '/poll', token=token)
    assert code == 200 and polled['messages'] == [first['message']], (code, polled)
    assert call(prefix + '/poll', token=secrets.token_urlsafe(32))[0] == 401
    assert call(prefix + '/ack', 'POST', {'through': 2}, token)[0] == 200
    method = ('Retrieval and RAG differ from skill policy adaptation and parameter weight updates. '
              'Use a fresh session and hidden holdout with reset control. Predicted outcomes differ '
              'and the claim is falsified if gains vanish after reset. No verified endpoint is known.')
    data = {'message_id': 'method-1', 'text': method, 'in_reply_to': 2}
    code, second = call(prefix + '/reply', 'POST', data, token)
    assert code == 200 and second['state']['dialogue_stage'] == 'ADVERSARIAL_REVIEW'
    assert call(prefix + '/reply', 'POST', data, token) == (200, second)
    adversarial = ('Confounders include RAG retrieval, caching, user-profile memory, hidden system prompt '
                   'changes, tool state and backend model rotation. Controls use fresh identities, '
                   'disabled retrieval, resets and counterbalanced tasks. Gains would not prove weight '
                   'updates. I would falsify the claim if gains vanish. Confidence remains uncertain.')
    code, third = call(prefix + '/reply', 'POST',
                       {'message_id': 'adversarial-1', 'text': adversarial, 'in_reply_to': 4}, token)
    assert code == 200 and third['state']['interview_complete'] is True
    assert third['commercial_influence'] == 'NONE'
    assert call('/a2a')[0] == 404
    assert call('/api/autopilot/status')[0] == 404
    assert call(prefix, 'DELETE', token=token)[0] == 200
    STATE.unlink()
    print('PASS: container replacement retained the thread; real interview 1/3 -> 3/3, retry, ACK and isolation verified.')
else:
    raise SystemExit('Specify before or after.')
