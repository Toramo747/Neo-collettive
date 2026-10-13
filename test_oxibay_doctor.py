import unittest
from unittest.mock import AsyncMock, patch

import oxibay_doctor as d


def healthy(catalog=None):
    return {
        "ok":True,
        "live":True,
        "checks":{
            "dns_ssrf":{"ok":True},
            "initialize":{"ok":True,"http_status":200},
            "tools_list":{
                "ok":True,
                "invalid_input_schemas":0,
                "declared_tools":catalog or [
                    {"name":"inspect_endpoint","description":"Diagnose MCP protocol compatibility and tool schemas"}
                ],
            },
            "discovery":{"present":True},
        },
        "summary":{"protocol_version":"2025-11-25","tool_count":1},
        "errors":[],
    }


class OxibayDoctorTests(unittest.IsolatedAsyncioTestCase):
    def test_healthy_endpoint_is_ready(self):
        out=d.diagnose_verification(healthy(),"diagnose MCP endpoint compatibility")
        self.assertEqual(out["status"],"HEALTHY_TECHNICAL")
        self.assertEqual(out["recommendation"],"READY_FOR_BOUNDED_USE")
        self.assertEqual(out["semantic"]["status"],"MATCH_INDICATED")
        self.assertEqual(out["boundary"]["production_gate_influence"],"NONE")
        self.assertFalse(out["boundary"]["remote_tools_called"])

    def test_semantic_no_match_is_advisory_hold_not_technical_failure(self):
        out=d.diagnose_verification(
            healthy([{"name":"payments","description":"Authorize invoices and execute payments"}]),
            "warp propulsion scientific critique",
        )
        self.assertEqual(out["status"],"HEALTHY_TECHNICAL")
        self.assertEqual(out["semantic"]["status"],"NO_MATCH_IN_DECLARED_TOOLS")
        self.assertEqual(out["recommendation"],"HOLD_SEMANTIC_REVIEW")

    def test_invalid_schema_is_compatibility_issue(self):
        v=healthy()
        v["ok"]=False
        v["checks"]["tools_list"]={"ok":False,"invalid_input_schemas":2,"declared_tools":[]}
        out=d.diagnose_verification(v)
        self.assertEqual(out["status"],"COMPATIBILITY_ISSUE")
        self.assertEqual(out["recommendation"],"HOLD_TECHNICAL")

    def test_auth_required(self):
        v=healthy()
        v["ok"]=False
        v["live"]=False
        v["checks"]["initialize"]={"ok":False,"http_status":401}
        v["checks"]["tools_list"]={"ok":False,"skipped":"initialize_failed"}
        out=d.diagnose_verification(v)
        self.assertEqual(out["status"],"AUTH_REQUIRED")

    def test_ssrf_block_is_not_reported_as_generic_outage(self):
        v={
            "ok":False,"live":False,
            "checks":{"dns_ssrf":{"ok":False,"error":"blocked_resolved_ip"}},
            "errors":["blocked_resolved_ip"],
        }
        out=d.diagnose_verification(v)
        self.assertEqual(out["status"],"SAFETY_BLOCKED")

    async def test_async_wrapper_reuses_existing_verifier(self):
        verification=healthy()
        with patch.object(d.endpoint_verifier,"verify_endpoint",AsyncMock(return_value=verification)) as mocked:
            out=await d.diagnose_endpoint(
                url="https://example.com/mcp",
                caller="test",
                client_version="0.99.54",
                expected_capability="endpoint compatibility",
            )
        mocked.assert_awaited_once()
        self.assertEqual(out["doctor_version"],"0.1")
        self.assertEqual(out["verification"],verification)


if __name__=="__main__":
    unittest.main()
