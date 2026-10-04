import unittest
from pathlib import Path


class BuyerSourceRoutingTests(unittest.TestCase):
    def test_desire_queries_honor_bounded_source_route(self):
        src=Path('cloud_mcp.py').read_text(encoding='utf-8')
        self.assertIn('route=[str(x).strip().lower() for x in (meta.get("source_route") or [])',src)
        self.assertIn('selected_sources=[x for x in route if x in source_tasks]',src)
        self.assertIn('tasks=[source_tasks[x]() for x in selected_sources]',src)
        self.assertIn('batch_sources=selected_sources',src)
        self.assertNotIn('batch_sources=["web","hn","github","stackexchange"]',src)


if __name__=='__main__':
    unittest.main()
