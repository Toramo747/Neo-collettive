import time
import unittest

from inbound_traffic import classify_inbound_event
from self_traffic_auth import make_self_traffic_proof, verify_self_traffic_proof


class SelfTrafficHmacPortTests(unittest.TestCase):
    def test_valid_proof_verifies_and_allows_self_classification(self):
        proof=make_self_traffic_proof("secret","/api/heartbeat",timestamp=1000)
        verified=verify_self_traffic_proof("secret","/api/heartbeat",proof,now=1000)
        self.assertTrue(verified["valid"])
        category,reason,_=classify_inbound_event(
            endpoint="/a2a",method="POST",rpc_method="message/send",has_text=True,
            self_marker="github-actions-heartbeat",self_verified=True,
        )
        self.assertEqual(category,"self_traffic")
        self.assertEqual(reason,"verified_mycelix_self_proof")

    def test_chatgpt_research_session_requires_and_accepts_valid_hmac(self):
        proof=make_self_traffic_proof("secret","/a2a",timestamp=1000)
        verified=verify_self_traffic_proof("secret","/a2a",proof,now=1000)
        self.assertTrue(verified["valid"])
        category,reason,_=classify_inbound_event(
            endpoint="/a2a",method="POST",rpc_method="message/send",has_text=True,
            declared_agent_id="chatgpt-research-session-test",
            self_verified=verified["valid"],
        )
        self.assertEqual(category,"self_traffic")
        self.assertEqual(reason,"verified_mycelix_self_proof")

        external,_,_=classify_inbound_event(
            endpoint="/a2a",method="POST",rpc_method="message/send",has_text=True,
            declared_agent_id="chatgpt-research-session-test",
            self_verified=False,
        )
        self.assertEqual(external,"real_contact")

    def test_unsigned_marker_is_not_self_traffic(self):
        category,_,_=classify_inbound_event(
            endpoint="/a2a",method="POST",rpc_method="message/send",has_text=True,
            self_marker="github-actions-heartbeat",self_verified=False,
        )
        self.assertEqual(category,"real_contact")

    def test_expired_proof_is_rejected(self):
        proof=make_self_traffic_proof("secret","/api/heartbeat",timestamp=1000)
        verified=verify_self_traffic_proof("secret","/api/heartbeat",proof,now=1301)
        self.assertFalse(verified["valid"])
        self.assertEqual(verified["reason"],"proof_expired")

    def test_chatgpt_research_session_expired_proof_is_external(self):
        proof=make_self_traffic_proof("secret","/a2a",timestamp=1000)
        verified=verify_self_traffic_proof("secret","/a2a",proof,now=1301)
        self.assertFalse(verified["valid"])
        self.assertEqual(verified["reason"],"proof_expired")
        category,reason,_=classify_inbound_event(
            endpoint="/a2a",method="POST",rpc_method="message/send",has_text=True,
            declared_agent_id="chatgpt-research-session-test",
            self_verified=bool(verified["valid"]),
        )
        self.assertEqual(category,"real_contact")
        self.assertEqual(reason,"declared_user_authorized_unverified")

    def test_wrong_path_is_rejected(self):
        proof=make_self_traffic_proof("secret","/api/heartbeat",timestamp=1000)
        verified=verify_self_traffic_proof("secret","/mcp",proof,now=1000)
        self.assertFalse(verified["valid"])
        self.assertEqual(verified["reason"],"signature_invalid")

    def test_empty_secret_fails_closed(self):
        verified=verify_self_traffic_proof("","/api/heartbeat","1000:deadbeef",now=1000)
        self.assertEqual(verified,{"valid":False,"reason":"secret_unconfigured"})


if __name__=="__main__":
    unittest.main()
