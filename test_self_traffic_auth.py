import unittest
from unittest.mock import patch

import cloud_mcp
from inbound_traffic import classify_inbound_event
from self_traffic_auth import make_self_traffic_proof, verify_self_traffic_proof


class SelfTrafficAuthTests(unittest.TestCase):
    def test_valid_proof_allows_self_classification(self):
        proof=make_self_traffic_proof("secret","/a2a",timestamp=1_000)
        verified=verify_self_traffic_proof("secret","/a2a",proof,now=1_000)
        self.assertTrue(verified["valid"])
        category,_,_=classify_inbound_event(
            endpoint="/a2a",method="POST",rpc_method="message/send",has_text=True,
            self_marker="github-actions-heartbeat",self_verified=verified["valid"],
        )
        self.assertEqual(category,"self_traffic")

    def test_unsigned_marker_is_external(self):
        verified=verify_self_traffic_proof("secret","/a2a","",now=1_000)
        self.assertFalse(verified["valid"])
        category,_,_=classify_inbound_event(
            endpoint="/a2a",method="POST",rpc_method="message/send",has_text=True,
            self_marker="github-actions-heartbeat",self_verified=verified["valid"],
        )
        self.assertEqual(category,"real_contact")

    def test_expired_proof_is_external(self):
        proof=make_self_traffic_proof("secret","/a2a",timestamp=1_000)
        verified=verify_self_traffic_proof("secret","/a2a",proof,now=1_301)
        self.assertFalse(verified["valid"])
        self.assertEqual(verified["reason"],"proof_expired")
        category,_,_=classify_inbound_event(
            endpoint="/a2a",method="POST",rpc_method="message/send",has_text=True,
            self_marker="github-actions-heartbeat",self_verified=verified["valid"],
        )
        self.assertEqual(category,"real_contact")

    def test_missing_server_secret_warns_and_remains_fail_closed(self):
        with self.assertLogs("mycelix",level="WARNING") as captured:
            missing=cloud_mcp._warn_if_self_traffic_secret_missing("")
        self.assertTrue(missing)
        self.assertIn("NEO_HEARTBEAT_TOKEN is empty or unset",captured.output[0])
        self.assertNotIn("secret=",captured.output[0].lower())

        verified=verify_self_traffic_proof("","/a2a","1000:not-a-valid-signature",now=1_000)
        self.assertEqual(verified,{"valid":False,"reason":"secret_unconfigured"})
        category,_,_=classify_inbound_event(
            endpoint="/a2a",method="POST",rpc_method="message/send",has_text=True,
            self_marker="github-actions-heartbeat",self_verified=verified["valid"],
        )
        self.assertNotEqual(category,"self_traffic")

    def test_configured_server_secret_does_not_warn(self):
        with patch.object(cloud_mcp.LOGGER,"warning") as warning:
            missing=cloud_mcp._warn_if_self_traffic_secret_missing("configured")
        self.assertFalse(missing)
        warning.assert_not_called()


if __name__=="__main__":
    unittest.main()
