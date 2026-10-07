import os
import hashlib
import unittest
from copy import deepcopy
from unittest.mock import patch

import cloud_mcp
from commercial_evidence_store import decode_external_store, encode_external_store, split_active_archive


class _Response:
    def __init__(self, ok=True, status=200, value=None):
        self.is_success=ok
        self.status_code=status
        self._value=value
    def json(self):
        return {"value":self._value} if self._value is not None else {}


class _FailSecondClient:
    puts=[]
    def __init__(self,*args,**kwargs):
        self.n=0
    async def __aenter__(self):
        return self
    async def __aexit__(self,*args):
        return False
    async def put(self,url,headers=None,json=None):
        self.n+=1
        type(self).puts.append((url,(json or {}).get("value")))
        if self.n==2:
            return _Response(False,500)
        return _Response(True,200,(json or {}).get("value"))
    async def get(self,url,headers=None):
        return _Response(False,404)
    async def delete(self,*args,**kwargs):
        return _Response(True,204)


class _CaptureStateClient:
    puts=[]
    def __init__(self,*args,**kwargs):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self,*args):
        return False
    async def put(self,url,headers=None,json=None):
        type(self).puts.append(url)
        return _Response(True,200,(json or {}).get("value"))
    async def get(self,*args,**kwargs):
        return _Response(False,404)
    async def delete(self,*args,**kwargs):
        return _Response(True,204)


class EvidenceStoreAtomicTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_second_new_chunk_keeps_previous_generation_restorable(self):
        old_rows=[{"evidence_id":f"old-{i}","gate_eligible":True,"blob":"x"*400} for i in range(12)]
        old_ref,old_chunks=encode_external_store(old_rows,chunk_bytes=1024,store="render_env_chunks_v2")
        env={
            cloud_mcp._commercial_evidence_env_key(i,old_ref):chunk
            for i,chunk in enumerate(old_chunks)
        }
        new_rows=old_rows+[{"evidence_id":f"new-{i}","gate_eligible":False,"blob":"".join(hashlib.sha256(f"{i}:{n}".encode()).hexdigest() for n in range(60))} for i in range(20)]
        old_key=cloud_mcp.RENDER_API_KEY
        old_service=cloud_mcp.RENDER_SERVICE_ID
        old_chunk=cloud_mcp.COMMERCIAL_EVIDENCE_CHUNK_BYTES
        try:
            cloud_mcp.RENDER_API_KEY="synthetic"
            cloud_mcp.RENDER_SERVICE_ID="synthetic"
            cloud_mcp.COMMERCIAL_EVIDENCE_CHUNK_BYTES=1024
            _FailSecondClient.puts=[]
            with patch.dict(os.environ,env,clear=False), patch.object(cloud_mcp.httpx,"AsyncClient",_FailSecondClient):
                result=await cloud_mcp._write_commercial_evidence_store(new_rows,previous_reference=old_ref)
                self.assertFalse(result["ok"])
                restored=decode_external_store(old_ref,[
                    os.environ[cloud_mcp._commercial_evidence_env_key(i,old_ref)]
                    for i in range(len(old_chunks))
                ])
            self.assertEqual(restored,old_rows)
            self.assertEqual(old_ref["sha256"],encode_external_store(old_rows,chunk_bytes=1024,store="render_env_chunks_v2")[0]["sha256"])
        finally:
            cloud_mcp.RENDER_API_KEY=old_key
            cloud_mcp.RENDER_SERVICE_ID=old_service
            cloud_mcp.COMMERCIAL_EVIDENCE_CHUNK_BYTES=old_chunk

    def test_external_store_reference_keeps_only_one_previous_generation(self):
        rows_a=[{"evidence_id":"a","gate_eligible":True}]
        rows_b=rows_a+[{"evidence_id":"b","gate_eligible":True}]
        rows_c=rows_b+[{"evidence_id":"c","gate_eligible":True}]
        rows_d=rows_c+[{"evidence_id":"d","gate_eligible":True}]
        ref_a,_=encode_external_store(rows_a,chunk_bytes=1024,store="render_env_chunks_v2")
        ref_b,_=encode_external_store(
            rows_b,chunk_bytes=1024,store="render_env_chunks_v2",previous_generation=ref_a
        )
        ref_c,_=encode_external_store(
            rows_c,chunk_bytes=1024,store="render_env_chunks_v2",previous_generation=ref_b
        )
        ref_d,_=encode_external_store(
            rows_d,chunk_bytes=1024,store="render_env_chunks_v2",previous_generation=ref_c
        )
        previous=ref_d.get("previous_generation")
        self.assertIsInstance(previous,dict)
        self.assertEqual(previous.get("sha256"),ref_c.get("sha256"))
        self.assertNotIn("previous_generation",previous)

        same_ref,_=encode_external_store(
            rows_d,chunk_bytes=1024,store="render_env_chunks_v2",previous_generation=ref_d
        )
        same_previous=same_ref.get("previous_generation")
        self.assertIsInstance(same_previous,dict)
        self.assertEqual(same_previous.get("sha256"),ref_c.get("sha256"))
        self.assertNotIn("previous_generation",same_previous)

    def test_discarded_ancestor_generations_returns_only_tail_beyond_retained_predecessor(self):
        rows_a=[{"evidence_id":"a","gate_eligible":True}]
        rows_b=rows_a+[{"evidence_id":"b","gate_eligible":True}]
        rows_c=rows_b+[{"evidence_id":"c","gate_eligible":True}]
        rows_d=rows_c+[{"evidence_id":"d","gate_eligible":True}]
        rows_e=rows_d+[{"evidence_id":"e","gate_eligible":True}]
        ref_a,_=encode_external_store(rows_a,chunk_bytes=1024,store="render_env_chunks_v2")
        ref_b,_=encode_external_store(rows_b,chunk_bytes=1024,store="render_env_chunks_v2",previous_generation=ref_a)
        legacy_c=dict(encode_external_store(rows_c,chunk_bytes=1024,store="render_env_chunks_v2",previous_generation=ref_b)[0])
        legacy_c["previous_generation"]=ref_b
        legacy_d=dict(encode_external_store(rows_d,chunk_bytes=1024,store="render_env_chunks_v2",previous_generation=legacy_c)[0])
        legacy_d["previous_generation"]=legacy_c
        new_ref,_=encode_external_store(rows_e,chunk_bytes=1024,store="render_env_chunks_v2",previous_generation=legacy_d)
        self.assertEqual((new_ref.get("previous_generation") or {}).get("sha256"),legacy_d.get("sha256"))
        stale=cloud_mcp._discarded_ancestor_generations(legacy_d,new_ref)
        self.assertEqual(
            [row.get("sha256") for row in stale],
            [legacy_c.get("sha256"),ref_b.get("sha256"),ref_a.get("sha256")],
        )
        self.assertTrue(all("previous_generation" not in row for row in stale))

    def test_corrupt_current_generation_recovers_previous_before_degrading(self):
        previous_rows=[{"evidence_id":f"p-{i}","gate_eligible":True} for i in range(5)]
        previous_ref,previous_chunks=encode_external_store(previous_rows,chunk_bytes=1024,store="render_env_chunks_v2")
        current_rows=previous_rows+[{"evidence_id":"new","gate_eligible":False}]
        current_ref,current_chunks=encode_external_store(
            current_rows,chunk_bytes=1024,store="render_env_chunks_v2",previous_generation=previous_ref
        )
        env={}
        for i,chunk in enumerate(previous_chunks):
            env[cloud_mcp._commercial_evidence_env_key(i,previous_ref)]=chunk
        for i,chunk in enumerate(current_chunks):
            env[cloud_mcp._commercial_evidence_env_key(i,current_ref)]=("corrupt" if i==0 else chunk)
        with patch.dict(os.environ,env,clear=False):
            hydrated,meta=cloud_mcp._hydrate_external_commercial_evidence({"commercial_evidence_memory":current_ref})
        self.assertEqual(meta["status"],"recovered_previous_generation")
        self.assertFalse(hydrated["evidence_store_degraded"])
        self.assertEqual(hydrated["commercial_evidence_memory"],previous_rows)
        self.assertEqual(hydrated["commercial_evidence_store_reference"]["sha256"],previous_ref["sha256"])

    def test_archive_recovers_previous_generation_and_reports_real_count(self):
        active_rows=[{"evidence_id":"active","gate_eligible":True}]
        archive_prev=[{"evidence_id":"arch-1","gate_eligible":False},{"evidence_id":"arch-2","gate_eligible":False}]
        active_ref,active_chunks=encode_external_store(active_rows,chunk_bytes=1024,store="render_env_chunks_v2")
        archive_prev_ref,archive_prev_chunks=encode_external_store(
            archive_prev,chunk_bytes=1024,store="render_env_archive_v1"
        )
        archive_current_ref,archive_current_chunks=encode_external_store(
            archive_prev+[{"evidence_id":"arch-3","gate_eligible":False}],
            chunk_bytes=1024,
            store="render_env_archive_v1",
            previous_generation=archive_prev_ref,
        )
        env={}
        for i,chunk in enumerate(active_chunks):
            env[cloud_mcp._commercial_evidence_env_key(i,active_ref)]=chunk
        for i,chunk in enumerate(archive_prev_chunks):
            env[cloud_mcp._commercial_evidence_env_key(i,archive_prev_ref,archive=True)]=chunk
        for i,chunk in enumerate(archive_current_chunks):
            env[cloud_mcp._commercial_evidence_env_key(i,archive_current_ref,archive=True)]=("corrupt" if i==0 else chunk)
        with patch.dict(os.environ,env,clear=False):
            hydrated,meta=cloud_mcp._hydrate_external_commercial_evidence({
                "commercial_evidence_memory":active_ref,
                "commercial_evidence_archive_reference":archive_current_ref,
            })
        self.assertFalse(hydrated["evidence_store_degraded"])
        self.assertEqual(hydrated["commercial_evidence_archive_rows"],archive_prev)
        self.assertEqual(hydrated["evidence_store_status"]["active_count"],1)
        self.assertEqual(hydrated["evidence_store_status"]["archive_count"],2)
        self.assertEqual(meta["status"],"recovered_previous_archive_generation")

    def test_degraded_store_reports_zero_loaded_active_and_bounds_pending(self):
        rows=[{"evidence_id":f"expected-{i}","gate_eligible":True} for i in range(4)]
        ref,chunks=encode_external_store(rows,chunk_bytes=1024,store="render_env_chunks_v2")
        pending=[
            {"evidence_id":f"pending-{i}","gate_eligible":False,"last_seen_epoch":i}
            for i in range(cloud_mcp.COMMERCIAL_PENDING_EVIDENCE_LIMIT+25)
        ]
        env={cloud_mcp._commercial_evidence_env_key(0,ref):"corrupt"}
        with patch.dict(os.environ,env,clear=False):
            hydrated,meta=cloud_mcp._hydrate_external_commercial_evidence({
                "commercial_evidence_memory":ref,
                "pending_evidence":pending,
            })
        status=hydrated["evidence_store_status"]
        self.assertEqual(status["active_count"],0)
        self.assertEqual(status["expected_active_count"],4)
        self.assertEqual(status["pending_count"],cloud_mcp.COMMERCIAL_PENDING_EVIDENCE_LIMIT)
        self.assertEqual(status["pending_overflow_count"],25)
        self.assertEqual(meta["evidence_count"],0)

    async def test_corrupt_store_without_previous_blocks_evidence_rewrite(self):
        rows=[{"evidence_id":"keep","gate_eligible":True}]
        ref,chunks=encode_external_store(rows,chunk_bytes=1024,store="render_env_chunks_v2")
        env={cloud_mcp._commercial_evidence_env_key(0,ref):"corrupt"}
        with patch.dict(os.environ,env,clear=False):
            hydrated,meta=cloud_mcp._hydrate_external_commercial_evidence({
                "commercial_evidence_memory":ref,
                "pending_evidence":[{"evidence_id":"pending","gate_eligible":False}],
            })
        self.assertEqual(meta["status"],"degraded")
        self.assertTrue(hydrated["evidence_store_degraded"])
        self.assertEqual(hydrated["commercial_evidence_store_reference"],ref)

        previous=deepcopy(cloud_mcp.AUTOPILOT_STATE)
        old_key=cloud_mcp.RENDER_API_KEY
        old_service=cloud_mcp.RENDER_SERVICE_ID
        try:
            cloud_mcp.AUTOPILOT_STATE.update(hydrated)
            cloud_mcp.RENDER_API_KEY="synthetic"
            cloud_mcp.RENDER_SERVICE_ID="synthetic"
            _CaptureStateClient.puts=[]
            minimal={
                "commercial_evidence_memory":[],
                "pending_evidence":hydrated["pending_evidence"],
                "commercial_evidence_store_reference":ref,
                "commercial_evidence_archive_reference":None,
                "evidence_store_degraded":True,
                "evidence_store_status":hydrated["evidence_store_status"],
            }
            with patch.object(cloud_mcp,"_state_payload",return_value=minimal), patch.object(cloud_mcp.httpx,"AsyncClient",_CaptureStateClient):
                result=await cloud_mcp._checkpoint_state_to_render()
            self.assertTrue(result["ok"])
            self.assertTrue(all(url.endswith("/env-vars/"+cloud_mcp.STATE_ENV_KEY) for url in _CaptureStateClient.puts))
            self.assertEqual(cloud_mcp.AUTOPILOT_STATE["commercial_evidence_store_reference"],ref)
        finally:
            cloud_mcp.AUTOPILOT_STATE.clear()
            cloud_mcp.AUTOPILOT_STATE.update(previous)
            cloud_mcp.RENDER_API_KEY=old_key
            cloud_mcp.RENDER_SERVICE_ID=old_service

    def test_3500_rows_archive_only_old_non_gate_eligible_without_loss(self):
        rows=[]
        for i in range(3500):
            rows.append({
                "evidence_id":f"ev-{i}",
                "gate_eligible":bool(i%17==0),
                "last_seen_epoch":3500-i,
            })
        active,archive=split_active_archive(rows,active_limit=3000)
        self.assertEqual(len(active)+len(archive),3500)
        self.assertFalse(any(bool(row.get("gate_eligible")) for row in archive))
        self.assertEqual({row["evidence_id"] for row in active+archive},{row["evidence_id"] for row in rows})


if __name__=="__main__":
    unittest.main()
