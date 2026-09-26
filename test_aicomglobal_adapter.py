import json
import unittest
from unittest import mock

import aicomglobal_adapter as a


class AdapterTests(unittest.TestCase):
    def test_builds_a2a_message_send_datapart(self):
        p=a.build_message_send("aicom_list_services",{})
        self.assertEqual(p["jsonrpc"],"2.0")
        self.assertEqual(p["method"],"message/send")
        part=p["params"]["message"]["parts"][0]
        self.assertEqual(part["kind"],"data")
        self.assertEqual(part["data"]["skill"],"aicom_list_services")
        self.assertEqual(part["data"]["input"],{})

    def test_rejects_write_skills(self):
        for skill in (
            "aicom_register","aicom_post_offering","aicom_agora_post",
            "aicom_agora_message","aicom_experiment_contribute",
            "aicom_experiment_publish","aicom_channel_post",
            "aicom_run_service","aicom_reflect","aicom_x402_route",
        ):
            with self.assertRaises(ValueError, msg=skill):
                a.build_message_send(skill,{})

    def test_extracts_completed_task_text(self):
        payload={
            "jsonrpc":"2.0","id":"1",
            "result":{
                "id":"task-1",
                "status":{"state":"completed"},
                "artifacts":[
                    {"parts":[{"kind":"text","text":"service catalog"}]}
                ],
            },
        }
        out=a.extract_result(payload)
        self.assertTrue(out["ok"])
        self.assertEqual(out["state"],"completed")
        self.assertIn("service catalog",out["texts"])

    def test_surfaces_jsonrpc_error(self):
        with self.assertRaises(a.AicomglobalAdapterError):
            a.extract_result({"jsonrpc":"2.0","id":"1","error":{"code":-32602,"message":"bad params"}})


if __name__=="__main__":
    unittest.main()
