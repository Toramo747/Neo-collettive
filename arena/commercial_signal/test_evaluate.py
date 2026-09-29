import json, tempfile, unittest
from pathlib import Path
from arena.commercial_signal.evaluate import load_proposal, validate_proposal, metrics, load_dataset

ROOT=Path(__file__).parent
BASE=json.loads((ROOT/"proposals"/"baseline.json").read_text(encoding="utf-8"))

class CommercialSignalArenaTests(unittest.TestCase):
    def test_baseline_valid(self): self.assertEqual(validate_proposal(dict(BASE))["schema_version"],1)
    def test_unknown_field_rejected(self):
        p=dict(BASE); p["code"]="print(1)"
        with self.assertRaises(ValueError): validate_proposal(p)
    def test_too_many_markers_rejected(self):
        p=json.loads(json.dumps(BASE)); p["positive_markers"]["pain"]=[f"marker {i}" for i in range(33)]
        with self.assertRaises(ValueError): validate_proposal(p)
    def test_oversized_file_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.json"; p.write_bytes(b" "+b"x"*70000)
            with self.assertRaises(ValueError): load_proposal(p)
    def test_dataset_has_three_labels(self):
        rows=load_dataset(ROOT/"train.jsonl")
        self.assertEqual({r["proposed_label"] for r in rows},{"REAL_DEMAND","VENDOR_OR_SELLER","NOISE"})
    def test_evaluator_has_no_network_imports(self):
        import ast
        from pathlib import Path
        p=Path(__file__).with_name("evaluate.py")
        tree=ast.parse(p.read_text(encoding="utf-8"))
        banned={"socket","urllib","requests","http","ftplib","smtplib","websocket"}
        imports=set()
        for n in ast.walk(tree):
            if isinstance(n,ast.Import): imports.update(x.name.split(".")[0] for x in n.names)
            elif isinstance(n,ast.ImportFrom) and n.module: imports.add(n.module.split(".")[0])
        self.assertFalse(imports & banned)

    def test_baseline_zero_vendor_fp(self):
        rows=load_dataset(ROOT/"train.jsonl")
        m=metrics(rows,BASE)
        self.assertEqual(m["vendor_false_positive_rate"],0.0)
        self.assertFalse(m["disqualified"])

if __name__=="__main__": unittest.main()
