import time
import unittest

from evidence_integrity import demand_signal_type, migrate_evidence_memory


class DemandGuardTests(unittest.TestCase):
    def common(self, title, body, url, query=""):
        return demand_signal_type(
            title,
            body,
            "buyer",
            strong_pain_only=True,
            seller_launch_guard=True,
            url=url,
            source="brave-search",
            vendor_content_guard=True,
            web_buyer_voice_guard=True,
            supply_offer_guard=True,
            query_echo_guard=True,
            query=query,
        )

    def test_data_entry_supply_offer_has_no_positive_demand(self):
        tags=self.common(
            "Looking for a data entry freelancer? Hire a vetted expert today",
            "Our freelancers handle manual data entry at $8 per hour. Book a call.",
            "https://vendor.example/services/data-entry",
            'manual data entry "looking for" freelancer',
        )
        self.assertNotIn("BUY_INTENT",tags)
        self.assertNotIn("PAID_DEMAND",tags)
        self.assertNotIn("PAIN",tags)
        self.assertIn("COMPETITION",tags)

    def test_zapier_alternative_supply_offer_has_no_buy_intent(self):
        tags=self.common(
            "Looking for Zapier alternatives? Try FlowCo free trial",
            "FlowCo provides workflow automation for teams. Start a free trial today.",
            "https://flowco.example/services/workflow-automation",
            '"alternative to Zapier" workflow automation',
        )
        self.assertNotIn("BUY_INTENT",tags)
        self.assertNotIn("PAID_DEMAND",tags)
        self.assertIn("COMPETITION",tags)

    def test_first_person_buyer_budget_keeps_buy_and_paid_demand(self):
        tags=self.common(
            "Need help automating invoice entry into our ERP",
            "We need to hire someone to automate invoice entry into our ERP, budget $2k.",
            "https://community.example/forum/invoice-automation",
            "invoice entry automation ERP",
        )
        self.assertIn("BUY_INTENT",tags)
        self.assertIn("PAID_DEMAND",tags)

    def test_query_echo_does_not_create_buy_or_paid_demand(self):
        tags=self.common(
            "Invoice entry automation options",
            "Budget automation and looking for contractor options are discussed here.",
            "https://community.example/resources/invoice-entry",
            '"budget" "looking for" contractor invoice entry automation',
        )
        self.assertNotIn("BUY_INTENT",tags)
        self.assertNotIn("PAID_DEMAND",tags)

    def test_three_supply_offers_cannot_pass_gate(self):
        now=time.time()
        rows=[]
        examples=[
            ("a.example","Looking for a data entry freelancer? Hire a vetted expert today",
             "Our freelancers handle manual data entry at $8 per hour. Book a call.",
             "https://a.example/services/data-entry"),
            ("b.example","Need a data entry expert? Hire our specialists",
             "We offer manual data entry services. Get a quote from us.",
             "https://b.example/hire/data-entry"),
            ("c.example","Looking for data entry help? Try ExpertCo free trial",
             "Our experts handle repetitive manual data entry. Book a demo.",
             "https://c.example/services/manual-data-entry"),
        ]
        for domain,title,snippet,url in examples:
            rows.append({
                "schema_v":2,"tagger_v":3,"migration_v":2,
                "gate_eligible":True,"quarantine_reason":None,
                "domain":domain,"source":"brave-search",
                "family":"manual_data_entry",
                "problem_key_raw":"manual_data_entry:manual_data_entry",
                "problem_key":"manual_data_entry:manual_data_entry",
                "title":title,"snippet":snippet,"url":url,
                "query":'manual data entry "looking for" freelancer budget',
                "query_role":"buyer",
                "signal_types":["BUY_INTENT","PAID_DEMAND"],
                "strong_markers":["budget","freelancer"],
                "last_seen_epoch":now,
            })
        migrated,_=migrate_evidence_memory(
            rows,
            strong_pain_only=True,
            seller_launch_guard=True,
            vendor_content_guard=True,
            web_buyer_voice_guard=True,
            supply_offer_guard=True,
            query_echo_guard=True,
        )
        eligible=[r for r in migrated if r.get("gate_eligible")]
        domains={r.get("domain") for r in eligible}
        strong={r.get("domain") for r in eligible if r.get("strong_markers")}
        tags=set()
        for row in eligible:
            tags.update(row.get("signal_types") or [])
        qualified=bool(
            len(domains)>=3 and len(strong)>=1
            and "PAID_DEMAND" in tags
            and ("BUY_INTENT" in tags or "PAIN" in tags)
        )
        self.assertFalse(qualified)
        self.assertEqual(eligible,[])
        for row in migrated:
            self.assertEqual(row.get("signal_reverted"),"supply_offer")
            self.assertEqual(row.get("quarantine_reason"),"supply_offer")
            self.assertEqual(row.get("strong_markers"),[])
            self.assertFalse({"PAIN","BUY_INTENT","PAID_DEMAND"} & set(row.get("signal_types") or []))


if __name__=="__main__":
    unittest.main()
