import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import wallet_watch as ww  # noqa: E402

ADDR = "0x" + "ab" * 20


class WalletWatchTest(unittest.TestCase):
    def test_records_incoming_once_and_advances(self):
        calls = []

        def call(method, params):
            calls.append(method)
            if method == "eth_blockNumber":
                return hex(5000)
            f = params[0]
            assert f["topics"][2] == "0x" + "0" * 24 + ADDR[2:]
            if int(f["fromBlock"], 16) <= 4500 <= int(f["toBlock"], 16):
                return [{"transactionHash": "0x" + "1" * 64, "logIndex": "0x3", "blockNumber": hex(4500),
                         "topics": [ww.TRANSFER, "0x" + "0" * 24 + "cd" * 20, f["topics"][2]], "data": hex(5000)}]
            return []
        with tempfile.TemporaryDirectory() as d:
            w = Path(d) / "common" / "wallet"
            w.mkdir(parents=True)
            (w / "address.txt").write_text(ADDR + "\n")
            self.assertEqual(ww.watch(d, call), 0)
            self.assertEqual(ww.watch(d, call), 0)
            rows = [json.loads(l) for l in (w / "incoming.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["amount_usdc"], 0.005)
            self.assertEqual(json.loads((w / "state.json").read_text())["next_block"], 5001)

    def test_bad_address(self):
        with tempfile.TemporaryDirectory() as d:
            w = Path(d) / "common" / "wallet"
            w.mkdir(parents=True)
            (w / "address.txt").write_text("not an address")
            self.assertEqual(ww.watch(d, lambda m, p: hex(1)), 1)


if __name__ == "__main__":
    unittest.main()
