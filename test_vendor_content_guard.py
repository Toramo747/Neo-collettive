import time
import unittest

from evidence_integrity import (
    demand_signal_type,
    migrate_evidence_memory,
)


VENDOR_ROWS = [
    {
        "schema_v":2,"tagger_v":3,"migration_v":2,"gate_eligible":True,
        "quarantine_reason":None,"domain":"portagebay.com","source":"brave-search",
        "family":"manual_data_entry","problem_key_raw":"manual_data_entry:manual_data_entry",
        "problem_key":"manual_data_entry:manual_data_entry",
        "title":"Manual Data Entry is Slowing Down Your Team",
        "snippet":"Portage Bay Solutions can help identify the processes that create the most friction and design a FileMaker-based solution that reduces manual data entry without disrupting your operations.",
        "signal_types":["PAIN"],"strong_markers":[],
        "url":"https://portagebay.com/blog/manual-data-entry-is-slowing-down-your-team",
        "last_seen_epoch":time.time(),
    },
    {
        "schema_v":2,"tagger_v":3,"migration_v":2,"gate_eligible":True,
        "quarantine_reason":None,"domain":"cgtech.com.au","source":"brave-search",
        "family":"manual_data_entry","problem_key_raw":"manual_data_entry:manual_data_entry",
        "problem_key":"manual_data_entry:manual_data_entry",
        "title":"Reduce manual data entry – CG TECH",
        "snippet":"Mistakes drop, and your team gets that time back for work that matters. We target one manual process end to end.",
        "signal_types":["PAIN"],"strong_markers":[],
        "url":"https://cgtech.com.au/challenges/reduce-manual-data-entry",
        "last_seen_epoch":time.time(),
    },
    {
        "schema_v":2,"tagger_v":3,"migration_v":2,"gate_eligible":True,
        "quarantine_reason":None,"domain":"katprotech.com","source":"brave-search",
        "family":"manual_data_entry","problem_key_raw":"manual_data_entry:manual_data_entry",
        "problem_key":"manual_data_entry:manual_data_entry",
        "title":"Using Power Automate to Reduce Manual Data Entry - KATPRO",
        "snippet":"Microsoft Power Automate offers a powerful way to eliminate inefficiencies. By automating repetitive tasks, businesses can reduce manual data entry.",
        "signal_types":["PAIN"],"strong_markers":[],
        "url":"https://katprotech.com/using-power-automate-to-reduce-manual-data-entry",
        "last_seen_epoch":time.time(),
    },
    {
        "schema_v":2,"tagger_v":3,"migration_v":2,"gate_eligible":True,
        "quarantine_reason":None,"domain":"artsyltech.com","source":"brave-search",
        "family":"manual_data_entry","problem_key_raw":"manual_data_entry:manual_data_entry",
        "problem_key":"manual_data_entry:manual_data_entry",
        "title":"Reduce Manual Data Entry: 7 Simple Fixes That Save Time",
        "snippet":"Start with an audit. Ask each team to note tasks that involve copying, typing, or moving information.",
        "signal_types":["PAIN"],"strong_markers":[],
        "url":"https://artsyltech.com/blog/how-to-stop-manual-data-entry",
        "last_seen_epoch":time.time(),
    },
    {
        "schema_v":2,"tagger_v":3,"migration_v":2,"gate_eligible":True,
        "quarantine_reason":None,"domain":"powerfulplatform.net","source":"brave-search",
        "family":"manual_data_entry","problem_key_raw":"manual_data_entry:manual_data_entry",
        "problem_key":"manual_data_entry:manual_data_entry",
        "title":"How to Reduce Manual Data Entry for Your Team – Powerful Platform",
        "snippet":"A submitted form can create a list item, notify the employee, request an approval, and log the outcome. This reduces repetitive work.",
        "signal_types":["PAIN"],"strong_markers":[],
        "url":"https://powerfulplatform.net/reduce-manual-data-entry",
        "last_seen_epoch":time.time(),
    },
]


class VendorContentGuardTests(unittest.TestCase):
    def test_five_cycle355_vendor_rows_lose_pain_and_gate_eligibility(self):
        migrated,meta=migrate_evidence_memory(
            VENDOR_ROWS,
            vendor_content_guard=True,
            web_buyer_voice_guard=True,
        )
        self.assertEqual(meta["changed"],5)
        self.assertEqual(len(migrated),5)
        for row in migrated:
            self.assertNotIn("PAIN",row.get("signal_types") or [])
            self.assertFalse(row.get("gate_eligible"))
            self.assertEqual(row.get("signal_reverted"),"vendor_content")
            self.assertEqual(row.get("context_type"),"vendor_content")
            self.assertEqual(row.get("quarantine_reason"),"vendor_content")

    def test_first_person_buyer_forum_post_keeps_pain(self):
        tags=demand_signal_type(
            "How do I stop repetitive data entry?",
            "Our team spends hours every week on manual data entry and we are struggling with errors. How can we automate it?",
            "buyer",
            strong_pain_only=True,
            url="https://www.reddit.com/r/smallbusiness/comments/abc/manual_data_entry/",
            source="brave-search",
            vendor_content_guard=True,
            web_buyer_voice_guard=True,
        )
        self.assertIn("PAIN",tags)

    def test_generic_web_without_buyer_voice_cannot_supply_pain(self):
        tags=demand_signal_type(
            "Manual Data Entry Problems and Solutions",
            "Manual data entry is repetitive and time consuming. Our platform helps automate the process.",
            "buyer",
            strong_pain_only=True,
            url="https://vendor.example/resources/manual-data-entry",
            source="brave-search",
            vendor_content_guard=True,
            web_buyer_voice_guard=True,
        )
        self.assertNotIn("PAIN",tags)

    def test_gate_cannot_pass_with_five_vendor_rows_plus_one_strong_source(self):
        strong={
            "schema_v":2,"tagger_v":3,"migration_v":2,"gate_eligible":True,
            "quarantine_reason":None,"domain":"remoteok.com","source":"remoteok-api",
            "family":"manual_data_entry","problem_key_raw":"manual_data_entry:manual_data_entry",
            "problem_key":"manual_data_entry:manual_data_entry",
            "title":"Manual Data Entry Contractor",
            "snippet":"Hiring a contractor for repetitive manual data entry.",
            "signal_types":["BUY_INTENT","PAID_DEMAND"],"strong_markers":["structured_job_market"],
            "url":"https://remoteok.com/example","last_seen_epoch":time.time(),
        }
        migrated,_=migrate_evidence_memory(
            VENDOR_ROWS+[strong],
            vendor_content_guard=True,
            web_buyer_voice_guard=True,
        )
        eligible=[r for r in migrated if r.get("gate_eligible")]
        domains={r["domain"] for r in eligible}
        fresh_domains={r["domain"] for r in eligible if time.time()-float(r.get("last_seen_epoch") or 0)<=7*86400}
        strong_domains={r["domain"] for r in eligible if r.get("strong_markers")}
        tags=set()
        for row in eligible:
            tags.update(row.get("signal_types") or [])
        gate=bool(
            len(domains)>=3 and len(fresh_domains)>=2 and len(strong_domains)>=1
            and "PAID_DEMAND" in tags and ("BUY_INTENT" in tags or "PAIN" in tags)
        )
        self.assertFalse(gate)
        self.assertEqual(domains,{"remoteok.com"})
        self.assertEqual(strong_domains,{"remoteok.com"})


if __name__=="__main__":
    unittest.main()
