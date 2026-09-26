import asyncio
import unittest

import neo_dialect as nd
from dialect_peer_harness import Provider, CallResult, SpendBudget, run_once

class Scripted(Provider):
    provider="Fake"
    model="fake-1"
    def __init__(self):
        self.n=0
    async def call(self,incoming,budget):
        budget.take()
        self.n+=1
        conv=incoming["conversation_id"]
        if self.n==1:
            msg=nd.capabilities(conv,"fake",["market-category-summary"])
        elif self.n==2:
            msg=nd.new_envelope("COUNTER",conv,proposal_id="proposal-1",counter_id="c1",changes={"category":"api-integration-tools"})
        else:
            msg=nd.new_envelope("RESULT",conv,agreement_id="agreement-1",status="ok",summary={"done":True})
        import json
        return CallResult(json.dumps(msg),10,10,None)

class HarnessTests(unittest.TestCase):
    def test_full_sequence(self):
        old_cap=SpendBudget().cap
        p=Scripted()
        b=SpendBudget()
        b.cap=10
        row=asyncio.run(run_once(p,1,b))
        self.assertTrue(row["completed"])
        self.assertTrue(row["dialect_adopted"])
        self.assertEqual(row["adoption_turn"],2)
        self.assertEqual(row["valid_messages"],3)
        self.assertEqual(row["invalid_messages"],0)
        self.assertEqual(row["turns_total"],7)

if __name__=="__main__":
    unittest.main()
