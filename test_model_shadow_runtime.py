import base64
import hashlib
import json
import os
import resource
import tempfile
import time
import unittest

import model_shadow


@unittest.skipIf(model_shadow.np is None,"numpy not installed in current lightweight CI")
class ModelShadowStudentRuntimeTests(unittest.TestCase):
    def _artifact(self,dim=4096):
        np=model_shadow.np
        labels=["buyer_tool_search","vendor_offer","manual_recurring_work","job_posting","other"]
        weights=np.zeros((len(labels),dim),dtype="<f4")
        weights[0,0]=1.0
        bias=np.zeros(len(labels),dtype="<f4")
        payload={
            "schema_v":1,
            "mode":"shadow",
            "trained":True,
            "version":"student-test-v1",
            "feature_dim":dim,
            "ngram_min":3,
            "ngram_max":5,
            "labels":labels,
            "weights_f32_b64":base64.b64encode(weights.tobytes()).decode("ascii"),
            "bias_f32_b64":base64.b64encode(bias.tobytes()).decode("ascii"),
            "training_manifest_sha256":"1"*64,
        }
        payload["artifact_sha256"]=hashlib.sha256(
            json.dumps(payload,sort_keys=True,separators=(",",":")).encode("utf-8")
        ).hexdigest()
        return payload

    def test_student_artifact_and_inference_fit_render_budget(self):
        payload=self._artifact()
        encoded=json.dumps(payload,separators=(",",":")).encode()
        self.assertLess(len(encoded),5_000_000)
        before=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        model=model_shadow.StudentModel(payload)
        started=time.perf_counter()
        for _ in range(100):
            result=model.predict("We manually reconcile invoices and are looking for a tool.")
            self.assertIn(result["label"],payload["labels"])
        elapsed=time.perf_counter()-started
        after=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux ru_maxrss is KiB. Keep a large safety margin under Render 512 MB.
        self.assertLess(after-before,128*1024)
        self.assertLess(elapsed,5.0)

    def test_runtime_loader_is_shadow_only(self):
        payload=self._artifact()
        payload["mode"]="production"
        with tempfile.TemporaryDirectory() as td:
            path=os.path.join(td,"student.json")
            open(path,"w",encoding="utf-8").write(json.dumps(payload))
            self.assertIsNone(model_shadow.load_student(path))


if __name__=="__main__":
    unittest.main()
