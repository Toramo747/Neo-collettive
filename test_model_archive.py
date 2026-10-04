import json
import tempfile
import unittest
from pathlib import Path
from model_archive import private_cases, bootstrap_archive, export_key, EXPORT_PATH
from self_traffic_auth import make_self_traffic_proof
from starlette.testclient import TestClient
import cloud_mcp

class PrivateArchiveTests(unittest.TestCase):
    def test_real_only_bounded_export_without_lexical_labels(self):
        row={'url':'https://example.test/1','title':'Test request','snippet':'Manual recurring tasks','source':'web','final_label':'vendor_offer','query':'private query'}
        rows=private_cases({'commercial_evidence_memory':[row,dict(row,synthetic=True),dict(row,source='smoke')]})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['final_label'],'')
        self.assertNotIn('query',rows[0])
        self.assertEqual(len(private_cases({'commercial_evidence_memory':[dict(row,url='https://example.test/'+str(i)) for i in range(150)]})),100)

    def test_idempotent_import_preserves_heldout_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            held=json.dumps({'id':'held','label_origin':'human'})+'\n'
            (p/'hidden.jsonl').write_text(held)
            counts=bootstrap_archive(p,[{'id':'train'},{'id':'held'}])
            self.assertEqual(counts['imported_cases'],1)
            self.assertEqual(bootstrap_archive(p,[{'id':'train'}])['imported_cases'],0)
            self.assertEqual((p/'hidden.jsonl').read_text(),held)

    def test_export_requires_both_path_and_purpose_proofs(self):
        from unittest.mock import patch
        with patch.object(cloud_mcp,'HEARTBEAT_TOKEN','export-secret'), patch.object(cloud_mcp,'NEO_ADMIN_TOKEN','admin-secret'):
            client=TestClient(cloud_mcp.app)
            self.assertIn(client.get(EXPORT_PATH).status_code,(401,403))
            headers={'X-MYCELIX-Self-Traffic-Proof':make_self_traffic_proof('export-secret',EXPORT_PATH)}
            self.assertEqual(client.get(EXPORT_PATH,headers=headers).status_code,403)
            headers['X-NEO-Model-Export-Proof']=make_self_traffic_proof(export_key('export-secret'),EXPORT_PATH)
            response=client.get(EXPORT_PATH,headers=headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['cache-control'],'no-store')

    def test_empty_eval_blocks_promotion(self):
        import numpy as np
        from tools.model_shadow_batch import train_student,evaluate_student
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            for name in ('public.jsonl','hidden.jsonl'):
                (p/name).touch()
            (p/'train_labeled.jsonl').write_text(''.join(json.dumps({'id':str(i),'normalized_text':'request '+str(i),'eligible_for_training':True,'final_label':'other','label_origin':'auto'})+'\n' for i in range(4)))
            train_student(p,p/'student.json',feature_dim=128,epochs=1)
            result=evaluate_student(p,p/'student.json')
            self.assertFalse(result['promotion_eligible'])
            self.assertFalse(result['student_not_worse_hidden'])
