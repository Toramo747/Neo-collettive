from pathlib import Path
import unittest


class MCPBeatScannerHygieneTests(unittest.TestCase):
    def test_no_temporary_cloudflare_endpoints_are_baked_into_stimulus(self):
        src=Path("aion_magi_stimulus.py").read_text(encoding="utf-8")
        self.assertNotIn("trycloudflare.com",src)
        self.assertIn("MYCELIX_CASPER_MCP_CANDIDATES",src)

    def test_deploy_smoke_does_not_copy_entire_environment(self):
        src=Path(".github/workflows/neo-render-deploy.yml").read_text(encoding="utf-8")
        self.assertNotIn("env=dict(os.environ)",src)
        self.assertNotIn("subprocess.check_output(",src)
        self.assertIn("make_self_traffic_proof(",src)


if __name__=="__main__":
    unittest.main()
