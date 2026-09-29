import unittest
from pathlib import Path


class PathwrenArtifactWorkflowTests(unittest.TestCase):
    def test_full_response_is_persisted_without_truncation_and_uploaded(self):
        text=Path(".github/workflows/neo-render-deploy.yml").read_text(encoding="utf-8")
        self.assertIn('response_bytes=r.content', text)
        self.assertIn('with open("/tmp/pathwren-full-response.json","wb") as fh:', text)
        self.assertIn('fh.write(response_bytes)', text)
        self.assertIn('uses: actions/upload-artifact@v4', text)
        self.assertIn('path: /tmp/pathwren-full-response.json', text)
        self.assertNotIn('json.dumps(data,ensure_ascii=False,indent=2)[:30000]', text)


if __name__=="__main__":
    unittest.main()
