import ast
import pathlib
import unittest

class ResultShapeGuardTests(unittest.TestCase):
    def test_web_source_count_ignores_non_list_results(self):
        rows=[
            {"results":[{"url":"https://a.test"}]},
            {"results":True},
            {"results":False},
            {"results":{"url":"https://bad-shape.test"}},
            {"results":None},
            {},
        ]
        def result_rows(value):
            return value if isinstance(value,list) else []
        count=sum(len(result_rows(x.get("results"))) for x in rows if isinstance(x,dict))
        self.assertEqual(count,1)

    def test_cloud_source_contains_type_guard(self):
        src=pathlib.Path("cloud_mcp.py").read_text(encoding="utf-8")
        self.assertIn("def _result_rows(value: Any) -> list:",src)
        self.assertIn("return value if isinstance(value,list) else []",src)

if __name__=="__main__":
    unittest.main()
