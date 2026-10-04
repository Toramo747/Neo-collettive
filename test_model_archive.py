import json
import tempfile
import unittest
from pathlib import Path
from model_archive import private_cases, bootstrap_archive, export_key, hidden_eval_key, control_cases_to_model_eval, EXPORT_PATH, HIDDEN_EVAL_PATH
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

    def test_shadow_observation_buffer_expands_private_export(self):
        base={'url':'https://example.test/a','title':'A','snippet':'Observed raw result','source':'brave-search'}
        extra={'url':'https://example.test/b','title':'B','snippet':'Second raw result','source':'hn-algolia-routed'}
        rows=private_cases({'commercial_evidence_memory':[base],'model_shadow_observations':[extra]})
        self.assertEqual(len(rows),2)
        self.assertEqual({row['source'] for row in rows},{'brave-search','hn-algolia-routed'})

    def test_public_control_cases_convert_to_model_eval(self):
        payload=json.load(open('data/arena/research-algorithm/control_cases.json',encoding='utf-8'))
        rows=control_cases_to_model_eval(payload['cases'],hidden=False)
        self.assertEqual(len(rows),24)
        self.assertEqual(sum(row['final_label']=='buyer_tool_search' for row in rows),12)
        self.assertEqual(sum(row['final_label']=='vendor_offer' for row in rows),12)

    def test_hidden_eval_endpoint_is_authenticated_and_human_origin(self):
        from unittest.mock import patch
        hidden={'cases':[{
            'id':'hidden-1','title':'Need a tool','body':'We need software for this workflow.',
            'source':'hn-algolia-routed','url':'https://example.test/hidden',
            'expect':{'buyer':True},
        }]}
        with patch.object(cloud_mcp,'HEARTBEAT_TOKEN','hidden-secret'), patch.dict('os.environ',{'NEO_HIDDEN_CONTROL_JSON':json.dumps(hidden)}):
            client=TestClient(cloud_mcp.app)
            self.assertEqual(client.get(HIDDEN_EVAL_PATH).status_code,403)
            proof=make_self_traffic_proof(hidden_eval_key('hidden-secret'),HIDDEN_EVAL_PATH)
            response=client.get(HIDDEN_EVAL_PATH,headers={'X-NEO-Model-Hidden-Proof':proof})
            self.assertEqual(response.status_code,200)
            rows=response.json()['cases']
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['label_origin'],'human')
            self.assertEqual(rows[0]['final_label'],'buyer_tool_search')

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
            rows=[]
            for i in range(4):
                rows.append({'id':'o'+str(i),'normalized_text':'generic discussion '+str(i),'eligible_for_training':True,'final_label':'other','label_origin':'auto'})
                rows.append({'id':'b'+str(i),'normalized_text':'looking for a tool '+str(i),'eligible_for_training':True,'final_label':'buyer_tool_search','label_origin':'auto'})
            (p/'train_labeled.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            train_student(p,p/'student.json',feature_dim=128,epochs=1)
            result=evaluate_student(p,p/'student.json')
            self.assertFalse(result['promotion_eligible'])
            self.assertFalse(result['student_not_worse_hidden'])
