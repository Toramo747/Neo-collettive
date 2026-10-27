"""27/10: verifier for the official x402 Offer and Receipt extension, against artifacts signed here with throwaway keys."""
import base64
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import x402_offer_receipt as orr  # noqa: E402

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, Prehashed  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402

OFFER = {"version": 1, "resourceUrl": "https://api.example.com/premium-data", "scheme": "exact", "network": "eip155:8453",
         "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "payTo": None, "amount": "10000", "validUntil": 0}


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def eth_key():
    k = ec.generate_private_key(ec.SECP256K1())
    n = k.public_key().public_numbers()
    pub = n.x.to_bytes(32, "big") + n.y.to_bytes(32, "big")
    return k, orr._lint.checksum("0x" + orr.keccak256(pub)[-20:].hex())


def eth_sign(k, digest: bytes, addr: str) -> str:
    r, s = decode_dss_signature(k.sign(digest, ec.ECDSA(Prehashed(hashes.SHA256()))))
    if s > orr.N // 2:
        s = orr.N - s
    for v in (27, 28):
        sig = r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v])
        if orr.recover_address(digest, sig) == addr:
            return "0x" + sig.hex()
    raise AssertionError("no recovery id matched")


class OfferReceiptTest(unittest.TestCase):
    def test_recover_known_vector(self):
        # keccak/secp256k1 sanity: private key 1 is the generator, address 0x7E5F...5Bdf
        k = ec.derive_private_key(1, ec.SECP256K1())
        n = k.public_key().public_numbers()
        addr = orr._lint.checksum("0x" + orr.keccak256(n.x.to_bytes(32, "big") + n.y.to_bytes(32, "big"))[-20:].hex())
        self.assertEqual(addr, "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf")

    def test_independent_vector_from_eth_account(self):
        # produced once with eth-account (Account.from_key(0x11*32), encode_typed_data); not by this module
        payload = {"version": 1, "resourceUrl": "https://api.example.com/premium-data", "scheme": "exact", "network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "payTo": "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A", "amount": "10000", "validUntil": 1703123516}
        self.assertEqual(orr.eip712_digest("offer", payload).hex(), "ebad6efda5199a4e7104d467b844f0be1121b950a024ecdf8bec088e6f595217")
        v = orr.verify({"format": "eip712", "payload": payload, "signature": "0xa9bde3fcd370853537b8913dbd13189c730d0ae75ed56c7e77a4d2081ef05d1d0e4cf438e5718cfdff9b0f47c1abaa0a5433d7b7708367c6dcada9f0de831c801c"}, "offer", now=1703000000)
        self.assertTrue(v["ok"], v)
        self.assertEqual((v["signer"], v["authorization"]["status"]), ("0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A", "established"))

    def test_eip712_offer_signed_by_payto(self):
        k, addr = eth_key()
        payload = {**OFFER, "payTo": addr}
        art = {"format": "eip712", "acceptIndex": 0, "payload": payload, "signature": eth_sign(k, orr.eip712_digest("offer", payload), addr)}
        accepts = {"scheme": "exact", "network": "eip155:8453", "asset": OFFER["asset"], "payTo": addr, "amount": "10000"}
        v = orr.verify(art, "offer", accepts=accepts)
        self.assertTrue(v["ok"], v)
        self.assertEqual((v["signer"], v["authorization"]["status"]), (addr, "established"))
        v = orr.verify(art, "offer", accepts={**accepts, "amount": "20000"})
        self.assertFalse(v["ok"])
        self.assertTrue(any("amount" in f for f in v["fails"]))
        tampered = {**art, "payload": {**payload, "amount": "1"}}
        v = orr.verify(tampered, "offer")
        self.assertNotEqual(v["signer"], addr)
        self.assertEqual(v["authorization"]["status"], "not_established")

    def test_eip712_receipt_and_transaction(self):
        k, addr = eth_key()
        tx = "0x" + "ab" * 32
        payload = {"version": 1, "network": "eip155:8453", "resourceUrl": "https://api.example.com/x", "payer": "0x" + "1" * 40,
                   "issuedAt": 1700000000, "transaction": tx}
        art = {"format": "eip712", "payload": payload, "signature": eth_sign(k, orr.eip712_digest("receipt", payload), addr)}
        self.assertTrue(orr.verify(art, "receipt", pay_to=addr, transaction=tx)["ok"])
        v = orr.verify(art, "receipt", pay_to=addr, transaction="0x" + "cd" * 32)
        self.assertTrue(any("different transaction" in f for f in v["fails"]))
        v = orr.verify(art, "receipt")
        self.assertTrue(v["ok"])
        self.assertEqual(v["authorization"]["status"], "not_established")

    def test_jws_eddsa_did_key_and_did_web(self):
        sk = Ed25519PrivateKey.generate()
        raw = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        n = int.from_bytes(b"\xed\x01" + raw, "big")
        s58 = ""
        while n:
            n, r = divmod(n, 58)
            s58 = orr._B58[r] + s58
        payload = {"version": 1, "network": "eip155:8453", "resourceUrl": "https://neo.example/x402/timestamp",
                   "payer": "0x" + "1" * 40, "issuedAt": 1700000000}

        def jws(kid):
            h = b64u(json.dumps({"alg": "EdDSA", "kid": kid}).encode()); p = b64u(json.dumps(payload).encode())
            return f"{h}.{p}." + b64u(sk.sign(f"{h}.{p}".encode()))
        v = orr.verify({"format": "jws", "signature": jws("did:key:z" + s58)}, "receipt")
        self.assertTrue(v["ok"] and v["signature_valid"], v)
        self.assertEqual(v["authorization"]["status"], "not_established")
        kid = "did:web:neo.example#key-1"
        doc = {"verificationMethod": [{"id": kid, "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "x": b64u(raw)}}]}
        v = orr.verify({"format": "jws", "signature": jws(kid)}, "receipt", did_document=doc)
        self.assertEqual(v["authorization"]["status"], "established", v)
        self.assertEqual(orr.did_web_url(kid), "https://neo.example/.well-known/did.json")
        other = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        bad = {"verificationMethod": [{"id": kid, "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "x": b64u(other)}}]}
        self.assertFalse(orr.verify({"format": "jws", "signature": jws(kid)}, "receipt", did_document=bad)["ok"])

    def test_jws_es256k_did_jwk(self):
        k = ec.generate_private_key(ec.SECP256K1())
        n = k.public_key().public_numbers()
        jwk = {"kty": "EC", "crv": "secp256k1", "x": b64u(n.x.to_bytes(32, "big")), "y": b64u(n.y.to_bytes(32, "big"))}
        kid = "did:jwk:" + b64u(json.dumps(jwk).encode()) + "#0"
        payload = {**OFFER, "payTo": "0x" + "2" * 40}
        h = b64u(json.dumps({"alg": "ES256K", "kid": kid}).encode()); p = b64u(json.dumps(payload).encode())
        r, s = decode_dss_signature(k.sign(f"{h}.{p}".encode(), ec.ECDSA(hashes.SHA256())))
        tok = f"{h}.{p}." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        self.assertTrue(orr.verify({"format": "jws", "signature": tok}, "offer")["signature_valid"])

    def test_malformed_inputs_fail_cleanly(self):
        for art in ({}, {"format": "eip712"}, {"format": "jws", "signature": "x.y"}, {"format": "eip712", "payload": OFFER, "signature": "0x12"}):
            self.assertFalse(orr.verify(art, "offer")["ok"], art)
        self.assertFalse(orr.verify({"format": "jws"}, "nonsense")["ok"])


if __name__ == "__main__":
    unittest.main()
