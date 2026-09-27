import copy, json, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from arena_micelio import sync, reverify, critic_context, load_json, save_json, NAMESPACE

class MicelioTests(unittest.TestCase):
    def _session(self):
        return {
            "schema_v":1,"namespace":NAMESPACE,"session_id":"s1","conversation_id":"s1",
            "created_at_utc":"2026-09-27T00:00:00+00:00",
            "boundary":{"production_state_write":False,"tool_opportunity_influence":"NONE","commercial_evidence_influence":"NONE",
                        "seti_peer_memory_influence":"NONE","external_usage_metrics_influence":"NONE","external_agent_contact":False,
                        "production_variant_promotion":False},
            "transcript":[
                {"valid":True,"actor":"Scout","message":{"type":"BYE","dialect_version":"neo-dialect/1.0","conversation_id":"s1","message_id":"m1","timestamp":"2026-09-27T00:00:00Z","reason":"done","status":"completed"}},
                {"valid":True,"actor":"Critic","message":{"type":"COUNTER","dialect_version":"neo-dialect/1.0","conversation_id":"s1","message_id":"m2","timestamp":"2026-09-27T00:00:01Z","proposal_id":"p","counter_id":"c1","changes":{"objection":"test"}}},
            ]
        }
    def test_no_proof_stays_hypothesis(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"sessions").mkdir()
            save_json(root/"sessions/s1.json",self._session())
            m=sync(root)
            h=[x for x in m["beliefs"] if x["belief_id"].endswith("tool-utility")][0]
            self.assertEqual(h["status"],"HYPOTHESIS"); self.assertEqual(h["confidence"],0.0)
    def test_failed_proof_quarantines(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"sessions").mkdir()
            s=self._session(); save_json(root/"sessions/s1.json",s)
            m=sync(root)
            b=[x for x in m["beliefs"] if x["belief_id"].endswith("isolation")][0]
            self.assertEqual(b["status"],"ACTIVE")
            s["boundary"]["external_agent_contact"]=True
            save_json(root/"sessions/s1.json",s)
            m=reverify(root,m)
            b=[x for x in m["beliefs"] if x["belief_id"].endswith("isolation")][0]
            self.assertEqual(b["status"],"QUARANTINE")
    def test_critic_gets_only_proven_facts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"sessions").mkdir()
            save_json(root/"sessions/s1.json",self._session())
            m=sync(root); ctx=critic_context(m)
            self.assertTrue(ctx)
            self.assertTrue(all(x.get("evidence") for x in ctx))
            self.assertFalse(any("useful free tool" in str(x.get("text")) for x in ctx))
            private=load_json(root/"critic-private.json",{})
            self.assertEqual(private.get("owner"),"Critic")
            self.assertTrue(private.get("counterexamples"))
    def test_expiry(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"sessions").mkdir()
            save_json(root/"sessions/s1.json",self._session())
            m=sync(root)
            for b in m["beliefs"]:
                if b.get("evidence"): b["expires_utc"]="2026-09-27T00:00:00+00:00"
            m=reverify(root,m,at=datetime(2026,9,28,tzinfo=timezone.utc))
            self.assertTrue(all(x["status"]=="EXPIRED" for x in m["beliefs"] if x.get("evidence")))

if __name__=="__main__": unittest.main()
