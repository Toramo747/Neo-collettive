import unittest

from peer_quality import classify_peer_response, falsifiable_test_signature


class PeerQualityTests(unittest.TestCase):
    def test_scalpstream_like_reply_is_payment_required(self):
        text=(
            "ScalpStream machine-payable research feeds x402. "
            "Payment: per request over x402 (HTTP 402). Price ~ $0.01/request, payable in XRP or USDC."
        )
        row=classify_peer_response(text,peer_state="MESSAGE",protocol_ok=True,quality_ok=True,markers={})
        self.assertEqual(row["peer_class"],"PAYMENT_REQUIRED")
        self.assertEqual(row["blocked_followup_state"],"PAYMENT_BLOCKED")

    def test_fodda_like_reply_is_auth_required(self):
        text=(
            "Fodda A2A endpoint is operational. Provide an API key via Authorization: Bearer token "
            "for full access to trend intelligence."
        )
        row=classify_peer_response(text,peer_state="COMPLETED",protocol_ok=True,quality_ok=True,markers={"protocol":True})
        self.assertEqual(row["peer_class"],"AUTH_REQUIRED")
        self.assertEqual(row["blocked_followup_state"],"AUTH_BLOCKED")

    def test_paid_service_without_explicit_payment_protocol_is_commercial(self):
        text=(
            "We provide API integration diagnostics. A fixed-scope diagnostic starts at USD 49 "
            "and a repair pilot starts at USD 149. Contact us for contracting and a quote."
        )
        row=classify_peer_response(text,peer_state="MESSAGE",protocol_ok=True,quality_ok=True,markers={"capabilities":True})
        self.assertEqual(row["peer_class"],"COMMERCIAL_SERVICE")

    def test_substantive_protocol_peer_is_collaborative(self):
        text=(
            "I am Atlas, a public research agent. My capabilities include evidence review and "
            "technical critique. I support A2A JSON-RPC message/send. A limitation is that I cannot "
            "inspect private systems. Documentation is available at https://example.org/docs."
        )
        markers={"identity":True,"capabilities":True,"protocol":True,"limits":True,"evidence":True}
        row=classify_peer_response(text,peer_state="MESSAGE",protocol_ok=True,quality_ok=True,markers=markers)
        self.assertEqual(row["peer_class"],"COLLABORATIVE")
        self.assertFalse(row["falsifiable_test"])

    def test_falsifiable_second_round_signature(self):
        text=(
            "Input: provide a public JSON document. Expected observable output: a list of contradictions. "
            "Control: provide the same document with no contradictions. The claim is false if the system "
            "reports contradictions in the negative case."
        )
        result=falsifiable_test_signature(text)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["score"],3)


if __name__=="__main__":
    unittest.main()
