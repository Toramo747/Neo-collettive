import asyncio
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import verify_quote_conformance as vc


class ConformanceTests(unittest.TestCase):
    def test_local_fixture_matches_all_calculated_expectations(self):
        vector = vc.load_vector()
        page = (vc.ROOT / vector['page']['path']).read_bytes()
        self.assertEqual(len(page.decode().splitlines()), 22)
        result = asyncio.run(vc.offline(vector, page))
        self.assertEqual(result['offline_passed'], 11)
        self.assertEqual(sum(bool(c['live']) for c in vector['cases']), 6)
        labels = {c['expected_outcome'] for c in vector['cases']}
        self.assertTrue({'verbatim', 'paraphrase', 'not_found', 'quote_too_short', 'quote_too_long'} <= labels)

    def test_modified_fixture_is_rejected(self):
        vector = vc.load_vector()
        with self.assertRaises(ValueError):
            asyncio.run(vc.offline(vector, b'altered public page'))

    def test_live_budget_is_checked_before_network(self):
        vector = vc.load_vector()
        for case in vector['cases']:
            case['live'] = True
        with patch.object(vc, 'read_url', side_effect=AssertionError('must not fetch')):
            with self.assertRaises(ValueError):
                vc.live(vector)

    def test_protocol_json_and_sse_are_parsed(self):
        result = {'ok': True, 'outcome': 'not_found'}
        packet = json.dumps({'result': {'structuredContent': result}})
        self.assertEqual(vc.parse_mcp(packet.encode()), result)
        self.assertEqual(vc.parse_mcp(('event: message\ndata: ' + packet + '\n\n').encode()), result)
        with self.assertRaises(ValueError):
            vc.parse_mcp(b'{"error":{"code":-1}}')
