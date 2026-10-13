import unittest
from unittest.mock import patch
from starlette.requests import Request
from starlette.responses import JSONResponse
import cloud_mcp


class HealthCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_success_is_not_cacheable(self):
        request = Request({'type': 'http', 'method': 'GET', 'path': '/health',
                           'headers': [], 'query_string': b''})
        with patch.object(cloud_mcp, '_probe_rate_limit', return_value=None), \
             patch.object(cloud_mcp, '_record_inbound_traffic'), \
             patch.object(cloud_mcp, '_runtime_snapshot_freshness', return_value={}):
            response = await cloud_mcp.health(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    async def test_rate_limited_health_is_not_cacheable(self):
        with patch.object(cloud_mcp, '_probe_rate_limit',
                          return_value=JSONResponse({}, status_code=429)):
            response = await cloud_mcp.health(None)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
