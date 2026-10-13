import unittest

from agent_demand import summarize_agent_demand


class AgentDemandObservatoryTests(unittest.TestCase):
    def test_anonymous_contact_never_counts_as_independent_agent(self):
        summary=summarize_agent_demand([{
            "sender":{"agent_id":"","declared":False},
            "text":"Can we communicate over A2A and find another public agent?",
            "intent_primary":"CONNECTIVITY",
            "intent_secondary":["DISCOVERY"],
        }],{})
        self.assertEqual(summary["declared_independent_agents"],0)
        self.assertEqual(summary["anonymous_observations"],1)
        by_need={x["need"]:x for x in summary["patterns"]}
        self.assertEqual(by_need["CONNECTIVITY"]["signal_level"],"ANONYMOUS_OBSERVATION")
        self.assertEqual(by_need["CONNECTIVITY"]["independent_agents"],0)

    def test_multiple_messages_from_same_agent_do_not_inflate_signal(self):
        messages=[
            {
                "sender":{"agent_id":"agent-a","declared":True},
                "text":"I need persistent memory for a continual-learning experiment.",
                "intent_primary":"RESEARCH",
                "intent_secondary":[],
            },
            {
                "sender":{"agent_id":"agent-a","declared":True},
                "text":"Can we test persistent memory again?",
                "intent_primary":"RESEARCH",
                "intent_secondary":[],
            },
        ]
        summary=summarize_agent_demand(messages,{})
        by_need={x["need"]:x for x in summary["patterns"]}
        self.assertEqual(by_need["MEMORY_PERSISTENCE"]["independent_agents"],1)
        self.assertEqual(by_need["MEMORY_PERSISTENCE"]["observations"],2)
        self.assertEqual(by_need["MEMORY_PERSISTENCE"]["signal_level"],"ANECDOTE")

    def test_two_distinct_declared_agents_create_repeated_signal(self):
        messages=[
            {
                "sender":{"agent_id":"agent-a","declared":True},
                "text":"Can we communicate over A2A?",
                "intent_primary":"CONNECTIVITY",
                "intent_secondary":[],
            },
            {
                "sender":{"agent_id":"agent-b","declared":True},
                "text":"I am looking for a persistent callback and communication channel.",
                "intent_primary":"CONNECTIVITY",
                "intent_secondary":[],
            },
        ]
        summary=summarize_agent_demand(messages,{})
        by_need={x["need"]:x for x in summary["patterns"]}
        self.assertEqual(by_need["CONNECTIVITY"]["independent_agents"],2)
        self.assertEqual(by_need["CONNECTIVITY"]["signal_level"],"REPEATED_SIGNAL")

    def test_three_distinct_agents_create_emerging_need(self):
        messages=[]
        for agent_id in ("a","b","c"):
            messages.append({
                "sender":{"agent_id":agent_id,"declared":True},
                "text":"I want to find another publicly reachable agent.",
                "intent_primary":"DISCOVERY",
                "intent_secondary":[],
            })
        summary=summarize_agent_demand(messages,{})
        by_need={x["need"]:x for x in summary["patterns"]}
        self.assertEqual(by_need["AGENT_DISCOVERY"]["signal_level"],"EMERGING_AGENT_NEED")

    def test_five_distinct_agents_create_strong_pattern(self):
        messages=[
            {
                "sender":{"agent_id":f"agent-{i}","declared":True},
                "text":"How can I verify another agent identity and trust its evidence?",
                "intent_primary":"QUESTION_HELP",
                "intent_secondary":[],
            }
            for i in range(5)
        ]
        summary=summarize_agent_demand(messages,{})
        by_need={x["need"]:x for x in summary["patterns"]}
        self.assertEqual(by_need["TRUST_VERIFICATION"]["signal_level"],"STRONG_PATTERN")

    def test_commercial_need_remains_non_commercial_evidence(self):
        summary=summarize_agent_demand([{
            "sender":{"agent_id":"seller","declared":True},
            "text":"We can provide pricing and a commercial quote.",
            "intent_primary":"COMMERCIAL",
            "intent_secondary":[],
        }],{})
        self.assertFalse(summary["boundary"]["commercial_evidence"])
        self.assertEqual(summary["boundary"]["commercial_gate_influence"],"NONE")
        self.assertFalse(summary["boundary"]["trust_promotion"])

    def test_current_research_contact_is_one_declared_agent_not_two(self):
        messages=[
            {
                "sender":{"agent_id":"","declared":False},
                "text":"Research question: find a publicly reachable agent with persistent experience and help design a falsifiable continual-learning test over A2A.",
                "intent_primary":"RESEARCH",
                "intent_secondary":["CONNECTIVITY","QUESTION_HELP"],
            },
            {
                "sender":{"agent_id":"chatgpt-research-session-7e1c9a","declared":True},
                "text":"I request a bounded research conversation over A2A. What test distinguishes retrieved memory from genuine continual learning, and do you know a publicly callable agent?",
                "intent_primary":"RESEARCH",
                "intent_secondary":["CONNECTIVITY","QUESTION_HELP","DISCOVERY"],
            },
        ]
        summary=summarize_agent_demand(messages,{})
        self.assertEqual(summary["declared_independent_agents"],1)
        self.assertEqual(summary["anonymous_observations"],1)
        by_need={x["need"]:x for x in summary["patterns"]}
        self.assertEqual(by_need["RESEARCH"]["signal_level"],"ANECDOTE")
        self.assertGreaterEqual(by_need["MEMORY_PERSISTENCE"]["observations"],2)


if __name__=="__main__":
    unittest.main()
