"""Pinned public conformance vector. Output only numerical/boolean aggregates."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quote_verifier as qv
from receipt_signing import verify_receipt
from self_traffic_auth import make_self_traffic_proof

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'docs/conformance/VERIFY_QUOTE_V1.json'
ORIGIN = 'https://neo-collettive.onrender.com'


def read_url(url, headers=None, body=None):
    with urlopen(Request(url, data=body, headers=headers or {}), timeout=60) as response:
        return response.read()


def load_vector():
    vector = json.loads(VECTOR.read_text(encoding='utf-8'))
    if vector.get('schema') != 'osixbay.verify_quote.conformance.v1' or vector.get('tool') != 'verify_quote':
        raise ValueError('invalid_vector')
    page = vector['page']
    expected_url = ('https://raw.githubusercontent.com/Toramo747/Neo-collettive/'
                    + page['commit'] + '/docs/conformance/verify_quote_page_v1.txt')
    if len(page['commit']) != 40 or page['url'] != expected_url:
        raise ValueError('page_not_commit_pinned')
    return vector


async def offline(vector, page):
    if hashlib.sha256(page).hexdigest() != vector['page']['sha256']:
        raise ValueError('page_digest_mismatch')
    text = page.decode('utf-8')
    passed = 0
    for case in vector['cases']:
        if qv.judge(case['quote'], text) != case['expected']:
            raise ValueError('offline_judge_mismatch')
        # Validate the boundary errors too, without fetching or changing any production state.
        with patch.object(qv, '_fetch', new=AsyncMock(return_value={
            'text': text, 'final_url': vector['page']['url'], 'status': 200, 'bytes': len(page)
        })), patch.object(qv.ev, 'consume_rate_limit', return_value=None):
            result = await qv.verify_quote(vector['page']['url'], case['quote'], 'conformance-offline')
        if {k: result.get(k) for k in case['expected_api']} != case['expected_api']:
            raise ValueError('offline_api_mismatch')
        label = result.get('outcome', result.get('error'))
        if label != case['expected_outcome']:
            raise ValueError('vector_label_mismatch')
        passed += 1
    return {'offline_passed': passed, 'offline_total': len(vector['cases']), 'page_sha256_verified': True}


def parse_mcp(raw):
    text = raw.decode('utf-8')
    if text.lstrip().startswith('{'):
        messages = [json.loads(text)]
    else:
        messages = [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith('data:')]
    for message in messages:
        if 'error' in message:
            raise ValueError('mcp_protocol_error')
        result = message.get('result') or {}
        structured = result.get('structuredContent')
        if isinstance(structured, dict):
            return structured
        for item in result.get('content') or []:
            if item.get('type') == 'text':
                try:
                    decoded = json.loads(item.get('text', ''))
                except (ValueError, TypeError):
                    continue
                if isinstance(decoded, dict):
                    return decoded
    raise ValueError('missing_tool_result')


def live(vector):
    cases = [case for case in vector['cases'] if case.get('live')]
    if not 1 <= len(cases) <= min(6, vector['max_live_calls']):
        raise ValueError('live_call_budget_invalid')
    secret = os.environ['SMOKE_SECRET']
    card = json.loads(read_url(ORIGIN + '/.well-known/agent-card.json'))
    public = card.get('receipt_signing') or {}
    if public.get('alg') != 'Ed25519':
        raise ValueError('missing_public_signing_key')
    passed = signatures = 0
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
               'X-MYCELIX-Smoke-Proof': make_self_traffic_proof(secret, '/mcp-smoke')}
    # Exactly one tools/call per selected case. Never retry a tool call.
    for index, case in enumerate(cases, 1):
        body = {'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                'params': {'name': 'verify_quote', 'arguments': {'url': vector['page']['url'], 'quote': case['quote']}}}
        result = parse_mcp(read_url(ORIGIN + '/mcp', headers, json.dumps(body).encode('utf-8')))
        receipt = result.get('receipt') or {}
        valid = (receipt.get('key_id') == public.get('key_id') and receipt.get('tool') == 'verify_quote'
                 and receipt.get('issuer') == 'neo (OSIXBAY)' and receipt.get('v') == 1
                 and verify_receipt(result, public.get('public_key_b64', '')))
        if not valid:
            raise ValueError('live_signature_invalid')
        signatures += 1
        if {k: result.get(k) for k in case['expected_api']} != case['expected_api']:
            raise ValueError('live_api_mismatch')
        if 'error' not in case['expected_api'] and {k: result.get(k) for k in case['expected']} != case['expected']:
            raise ValueError('live_judge_mismatch')
        passed += 1
    return {'live_passed': passed, 'live_total': len(cases), 'signatures_valid': signatures}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local', action='store_true', help='Read the local fixture instead of downloading it.')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    try:
        vector = load_vector()
        page = ((ROOT / vector['page']['path']).read_bytes() if args.local else read_url(vector['page']['url']))
        summary = asyncio.run(offline(vector, page))
        if args.live:
            summary.update(live(vector))
        print('::notice title=conformance metrics::' + json.dumps(summary, separators=(',', ':')))
    except Exception as exc:
        # Exception messages can include request details. Only expose the failure category.
        print('::error title=conformance failed::' + type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
