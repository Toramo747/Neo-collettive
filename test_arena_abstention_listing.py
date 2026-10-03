import ast
import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import arena_collective_mind as arena


ABSTENTION={
    "proposal":"No adapter or signal-discovery change proposed. This is a coverage limitation, not a judgment about the mission.",
    "method":"Under the available evidence, I cannot supply an independently grounded design or comparison for this packet.",
    "falsifier":"No technical hypothesis was evaluated. Completion, latency and failure isolation remain untested.",
    "support_votes":6,
}


class AbstentionTests(unittest.TestCase):
    def test_abstention_is_never_a_contribution_even_with_support(self):
        self.assertTrue(arena.proposal_abstains(ABSTENTION))
        self.assertFalse(arena.proposal_substantive(ABSTENTION))
        report={"ranked_proposals":[ABSTENTION],"round1_valid_proposals":1,"round2_valid_critiques":6,"agents_contacted":6}
        self.assertEqual(arena.genome_fitness(report,arena.DEFAULT_SCORE_GENOME),0)
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(arena.evolve_score_genome(report,Path(td)/"evolution.json")["status"],"HOLD_INSUFFICIENT_PROPOSALS")

    def test_honest_abstention_has_separate_counter_and_no_retry_or_review(self):
        class Client:
            def __init__(self,**kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
        async def discover(*args): return ([{"id":"test-agent","name":"Test agent"}],{"rows":[]})
        calls=[]
        async def send(*args):
            calls.append(args)
            return 200,dict(ABSTENTION)
        assigned=[({"id":"test-agent","name":"Test agent"},arena.WORK_PACKETS[0])]
        with tempfile.TemporaryDirectory() as td, patch.object(arena.httpx,"AsyncClient",Client), patch.object(arena,"discover_agents",discover), patch.object(arena,"assign_agents_to_packets",return_value=assigned), patch.object(arena,"send_chat",send):
            report=asyncio.run(arena.run("local adapter experiment",Path(td),1))
        self.assertEqual(report["round1_abstentions"],1)
        self.assertEqual(report["round1_valid_proposals"],0)
        self.assertEqual(report["round2_valid_critiques"],0)
        self.assertEqual(report["ranked_proposals"],[])
        self.assertEqual(len(calls),1)
        self.assertEqual(report["contacts"][0]["reason"],"honest_abstention")

    def test_historical_abstention_does_not_reward_routing(self):
        report={"contacts":[{"agent_id":"test-agent","agent":"Test agent","accepted":True}],"ranked_proposals":[dict(ABSTENTION,agent="Test agent")],"round1_valid_proposals":1}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"collective-mind"
            root.mkdir()
            (root/"latest.json").write_text(json.dumps(report))
            memory=arena.load_routing_memory(Path(td))
        self.assertEqual(memory["succeeded_ids"],set())
        self.assertEqual(memory["previous_valid_proposals"],0)


class ListingTests(unittest.TestCase):
    def test_listing_identity_requires_exact_endpoint(self):
        # Extract the pure helper without importing the production runtime.
        source=ast.parse(Path("cloud_mcp.py").read_text())
        node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=="_listing_has_own_endpoint")
        scope={"re":re}
        exec(compile(ast.Module(body=[node],type_ignores=[]),"cloud_mcp.py","exec"),scope)
        matches=scope[node.name]
        base="https://neo-collettive.onrender.com"
        for name in ("mycelix","OSIXBAY","unrelated"):
            self.assertTrue(matches(json.dumps({"name":name,"url":base+"/a2a"}),base))
            self.assertFalse(matches(json.dumps({"name":name,"url":"https://other.example/a2a"}),base))
        self.assertFalse(matches(base+".evil.example/a2a",base))
        self.assertFalse(matches(base+"/a2a-other",base))
        self.assertTrue(matches(json.dumps({"wellKnownURI":base+"/.well-known/agent-card.json"}),base))


if __name__=="__main__":
    unittest.main()
