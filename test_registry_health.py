import unittest

from registry_health import (
    classify_verification,
    final_category,
    is_opted_out,
    normalize_registry_rows,
    render_report,
    render_social_draft,
)


def row(name, *, latest=True, status="active", remotes=None, packages=None, version="1.0.0"):
    return {
        "server": {
            "name": name,
            "version": version,
            "remotes": remotes or [],
            "packages": packages or [],
        },
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "isLatest": latest,
                "status": status,
            }
        },
    }


class RegistryHealthListingTests(unittest.TestCase):
    def test_keeps_only_active_latest_and_splits_access_classes(self):
        rows = normalize_registry_rows([
            row("a/remote", remotes=[{"type":"streamable-http","url":"https://a.example/mcp"}]),
            row("b/pkg", packages=[{"registryType":"npm","identifier":"b"}]),
            row("c/old", latest=False, remotes=[{"type":"streamable-http","url":"https://c.example/mcp"}]),
            row("d/deprecated", status="deprecated", remotes=[{"type":"streamable-http","url":"https://d.example/mcp"}]),
            row("e/sse", remotes=[{"type":"sse","url":"https://e.example/sse"}]),
            row("f/meta"),
            row("g/sse-plus-package", remotes=[{"type":"sse","url":"https://g.example/sse"}], packages=[{"registryType":"npm","identifier":"g"}]),
        ])
        by_name={x["name"]:x for x in rows}
        self.assertEqual(set(by_name), {"a/remote","b/pkg","e/sse","f/meta","g/sse-plus-package"})
        self.assertEqual(by_name["a/remote"]["access_class"], "remote")
        self.assertEqual(by_name["b/pkg"]["access_class"], "package_only")
        self.assertEqual(by_name["e/sse"]["access_class"], "remote_unverifiable_transport")
        self.assertEqual(by_name["g/sse-plus-package"]["access_class"], "remote_unverifiable_transport")
        self.assertEqual(by_name["f/meta"]["access_class"], "metadata_only")

    def test_opt_out_matches_exact_name_or_remote(self):
        server={"name":"a/remote","remotes":[{"url":"https://a.example/mcp"}]}
        self.assertTrue(is_opted_out(server,{"a/remote"}))
        self.assertTrue(is_opted_out(server,{"https://a.example/mcp"}))
        self.assertFalse(is_opted_out(server,{"a"}))

    def test_classification_is_mutually_exclusive(self):
        auth={"checks":{"initialize":{"http_status":401,"ok":False}},"errors":["initialize_failed"]}
        server_error={"checks":{"initialize":{"http_status":503,"ok":False}},"errors":["initialize_failed"]}
        good={
            "checks":{
                "initialize":{"http_status":200,"ok":True},
                "tools_list":{"ok":True,"invalid_input_schemas":0},
                "discovery":{"present":True},
            },
            "errors":[],
        }
        issue={
            "checks":{
                "initialize":{"http_status":200,"ok":True},
                "tools_list":{"ok":True,"invalid_input_schemas":0},
                "discovery":{"present":False},
            },
            "errors":[],
        }
        dead={"checks":{},"errors":["dns_error"]}
        not_mcp={"checks":{"initialize":{"http_status":200,"ok":False}},"errors":["initialize_failed"]}
        self.assertEqual(classify_verification(auth),"AUTH_REQUIRED")
        self.assertEqual(classify_verification(server_error),"SERVER_ERROR")
        self.assertEqual(classify_verification(good),"OK")
        self.assertEqual(classify_verification(issue),"OK_WITH_ISSUES")
        self.assertEqual(classify_verification(dead),"UNREACHABLE")
        self.assertEqual(classify_verification(not_mcp),"NOT_MCP")

    def test_report_is_aggregate_only(self):
        summary={
            "servers_total":10,"remote_verifiable":6,"package_only":4,
            "remote_unverifiable_transport":0,"metadata_only":0,"opted_out":0,
            "scanned":6,
            "categories":{"OK":{"count":4},"AUTH_REQUIRED":{"count":1},"UNREACHABLE":{"count":1}},
            "protocol_versions":{"2025-11-25":4},
            "invalid_input_schemas":1,"discovery_present":3,"tls_failures":1,
            "latency_ms":{"median":120.0,"p90":400.0,"samples":5},
        }
        report=render_report(summary,"2026-09-26")
        self.assertIn("MCP Registry Health Report",report)
        self.assertIn("aggregate results only",report)
        self.assertNotIn("example.com",report)
        social=render_social_draft(summary,"2026-09-26")
        self.assertEqual(len([x for x in social.splitlines() if x.strip()]),5)

    def test_second_probe_disagreement_is_intermittent(self):
        self.assertEqual(final_category({"category":"SERVER_ERROR"},{"category":"OK"}),"INTERMITTENT")
        self.assertEqual(final_category({"category":"SERVER_ERROR"},{"category":"SERVER_ERROR"}),"SERVER_ERROR")
        self.assertEqual(final_category({"category":"OK"},None),"OK")


if __name__ == "__main__":
    unittest.main()
