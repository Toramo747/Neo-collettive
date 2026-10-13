import unittest
from pathlib import Path


class BuyerSourceRoutingTests(unittest.TestCase):
    def test_desire_queries_honor_bounded_source_route(self):
        src=Path('cloud_mcp.py').read_text(encoding='utf-8')
        start=src.index('async def routed_public_search')
        end=src.index('async def _provider_http_get',start)
        routed=src[start:end]
        self.assertIn('route=[str(x).strip().lower() for x in (meta.get("source_route") or [])',routed)
        self.assertIn('selected_sources=[x for x in route if x in source_tasks]',routed)
        self.assertIn('tasks=[source_tasks[x]() for x in selected_sources]',routed)
        self.assertIn('batch_sources=selected_sources',routed)
        self.assertNotIn('batch_sources=["web","hn","github","stackexchange"]',routed)


if __name__=='__main__':
    unittest.main()
