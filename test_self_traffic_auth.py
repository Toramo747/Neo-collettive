import unittest

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


if __name__=="__main__":
    unittest.main()
