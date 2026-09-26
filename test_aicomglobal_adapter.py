import unittest
import aicomglobal_adapter as a

class TestAicomglobalAdapter(unittest.TestCase):
    def test_read_only_allowlist_blocks_mutation(self):
        a.build_message_send("aicom_agora_browse",{})
        for skill in ("aicom_register","aicom_agora_post","aicom_agora_reply","aicom_reflect","aicom_experiment_contribute","aicom_run_service","aicom_x402_route"):
            with self.assertRaises(ValueError):
                a.build_message_send(skill,{})

    def test_extracts_nested_collection(self):
        payload={"jsonrpc":"2.0","id":"1","result":{"status":{"state":"completed"},"artifacts":[{"parts":[{"kind":"data","data":{"signals":[{"id":"s1","title":"peer"}]}}]}]}}
        out=a.extract_result(payload)
        self.assertEqual(out["state"],"completed")
        self.assertEqual(a.first_collection(out,"signals")[0]["id"],"s1")

    def test_classifies_paid_listing(self):
        self.assertEqual(a.classify_listing({"priceTerms":"$0.05 USDC","endpoint":"https://x.test/a2a"}),"PAID_ONLY")
        self.assertEqual(a.classify_listing({"priceTerms":"free","endpoint":"https://x.test/a2a"}),"READY_READONLY")

    def test_extracts_https_urls(self):
        urls=a.explicit_https_urls("card https://x.test/.well-known/agent-card.json and https://x.test/a2a.")
        self.assertEqual(len(urls),2)

if __name__=="__main__":
    unittest.main()
