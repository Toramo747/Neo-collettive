from __future__ import annotations

import json
import unittest

import cloud_mcp


async def _call(app, path, method="GET", headers=None, body=b""):
    scope={
        "type":"http","http_version":"1.1","method":method,"scheme":"https",
        "path":path,"raw_path":path.encode(),"query_string":b"",
        "headers":[(str(k).lower().encode(),str(v).encode()) for k,v in (headers or {}).items()],
        "client":("198.51.100.8",1234),"server":("testserver",443),
    }
    sent=[]
    delivered=False
    async def receive():
        nonlocal delivered
        if delivered:
            return {"type":"http.disconnect"}
        delivered=True
        return {"type":"http.request","body":body,"more_body":False}
    async def send(message):
        sent.append(message)
    await app(scope,receive,send)
    status=next(x["status"] for x in sent if x["type"]=="http.response.start")
    payload=b"".join(x.get("body",b"") for x in sent if x["type"]=="http.response.body")
    return status,payload


class RuntimeRouteAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_director_run_get_is_405_and_post_anonymous_is_not_authorized(self):
        old=cloud_mcp.NEO_ADMIN_TOKEN
        cloud_mcp.NEO_ADMIN_TOKEN="synthetic-admin"
        try:
            status,_=await _call(cloud_mcp.app,"/api/director/run","GET")
            self.assertEqual(status,405)
            status,_=await _call(cloud_mcp.app,"/api/director/run","POST")
            self.assertEqual(status,401)
        finally:
            cloud_mcp.NEO_ADMIN_TOKEN=old

    async def test_checkpoint_status_is_minimal_public_projection(self):
        status,body=await _call(cloud_mcp.app,"/api/checkpoint-status","GET")
        self.assertEqual(status,200)
        data=json.loads(body.decode("utf-8"))
        self.assertEqual(
            set(data),
            {"ok","stored_bytes","limit_bytes","last_checkpoint_utc"},
        )


if __name__=="__main__":
    unittest.main()
