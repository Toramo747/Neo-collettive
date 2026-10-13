import unittest

from gate_stability import apply_gate_hysteresis, opportunity_identity


class GateStabilityTests(unittest.TestCase):
    def _row(self, passed, score=90, tool="X", family="finance_ops", domains=("a.example",)):
        return {
            "family":family,
            "tool_name":tool,
            "target_user":"ops",
            "problem":"manual reconciliation",
            "gate_pass":passed,
            "monetization_score":score,
            "missing":[],
            "sources":[{"domain":d,"signal_types":["PAYMENT"]} for d in domains],
        }

    def _apply(self,state,row,cycle,when,tagger="3",genome="g60"):
        return apply_gate_hysteresis(
            state,[row],cycle=cycle,observed_at_utc=when,
            tagger_version=tagger,genome_id=genome,
        )

    def test_requires_six_hours_two_cycles_and_new_domain(self):
        s,rows=self._apply({},self._row(True),1,"2026-10-06T00:00:00+00:00")
        self.assertFalse(rows[0]["stable_gate_pass"])
        self.assertIn("min_6_hours",rows[0]["gate_confirmation"]["confirmation_blockers"])
        self.assertIn("min_2_research_cycles",rows[0]["gate_confirmation"]["confirmation_blockers"])

        s,rows=self._apply(s,self._row(True),2,"2026-10-06T00:05:00+00:00")
        self.assertFalse(rows[0]["stable_gate_pass"])
        self.assertIn("evidence_fingerprint_unchanged",rows[0]["gate_confirmation"]["confirmation_blockers"])
        self.assertIn("no_new_independent_domain",rows[0]["gate_confirmation"]["confirmation_blockers"])

        s,rows=self._apply(
            s,self._row(True,domains=("a.example","b.example")),
            3,"2026-10-06T06:01:00+00:00",
        )
        self.assertTrue(rows[0]["stable_gate_pass"])
        self.assertEqual(rows[0]["gate_confirmation"]["confirmation_blockers"],[])
        self.assertEqual(rows[0]["gate_confirmation"]["new_domains_since_first_pass"],1)
        self.assertGreaterEqual(rows[0]["gate_confirmation"]["seconds_since_first_raw_pass"],21600)

    def test_repeated_director_run_same_cycle_does_not_advance_series(self):
        s,_=self._apply({},self._row(True),7,"2026-10-06T00:00:00+00:00")
        s,rows=self._apply(
            s,self._row(True,domains=("a.example","b.example")),
            7,"2026-10-06T07:00:00+00:00",
        )
        self.assertFalse(rows[0]["stable_gate_pass"])
        self.assertEqual(rows[0]["gate_confirmation"]["pass_streak"],1)
        self.assertIn("min_2_research_cycles",rows[0]["gate_confirmation"]["confirmation_blockers"])

    def test_two_rows_same_candidate_cannot_advance_twice(self):
        row=self._row(True)
        duplicate=dict(row)
        duplicate["monetization_score"]=95
        s,rows=apply_gate_hysteresis(
            {},[row,duplicate],cycle=1,observed_at_utc="2026-10-06T00:00:00+00:00",
            tagger_version="3",genome_id="g60",
        )
        self.assertFalse(rows[0]["stable_gate_pass"])
        self.assertFalse(rows[1]["stable_gate_pass"])
        key=rows[0]["gate_candidate_key"]
        self.assertEqual(s["candidates"][key]["pass_streak"],1)

    def test_context_change_resets_confirmation_series(self):
        s,_=self._apply({},self._row(True),1,"2026-10-06T00:00:00+00:00")
        s,rows=self._apply(
            s,self._row(True,domains=("a.example","b.example")),
            2,"2026-10-06T07:00:00+00:00",
        )
        self.assertTrue(rows[0]["stable_gate_pass"])
        s,rows=self._apply(
            s,self._row(True,domains=("a.example","b.example","c.example")),
            3,"2026-10-06T08:00:00+00:00",tagger="4",
        )
        self.assertTrue(s["context_reset"])
        self.assertFalse(rows[0]["stable_gate_pass"])
        self.assertEqual(rows[0]["gate_confirmation"]["pass_streak"],1)

    def test_genome_change_resets_confirmation_series(self):
        s,_=self._apply({},self._row(True),1,"2026-10-06T00:00:00+00:00")
        s,rows=self._apply(
            s,self._row(True,domains=("a.example","b.example")),
            2,"2026-10-06T07:00:00+00:00",genome="g61",
        )
        self.assertTrue(s["context_reset"])
        self.assertFalse(rows[0]["stable_gate_pass"])


    def test_first_post_deploy_raw_pass_is_ignored_for_confirmation(self):
        row=self._row(True)
        state,rows=apply_gate_hysteresis(
            {},[row],cycle=2545,observed_at_utc="2026-10-06T18:47:00+00:00",
            tagger_version="3",genome_id="g62",commit="newdeploy",
            first_cycle_after_deploy=True,
        )
        key=rows[0]["gate_candidate_key"]
        self.assertTrue(rows[0]["raw_gate_pass"])
        self.assertFalse(rows[0]["stable_gate_pass"])
        self.assertTrue(rows[0]["gate_confirmation"]["post_deploy_pass_ignored"])
        self.assertEqual(rows[0]["gate_confirmation"]["pass_streak"],0)
        self.assertEqual(state["candidates"][key]["first_raw_pass_utc"],"")
        self.assertEqual(state["post_deploy_pass_ignored"],1)

        state,rows=apply_gate_hysteresis(
            state,[row],cycle=2546,observed_at_utc="2026-10-06T19:02:00+00:00",
            tagger_version="3",genome_id="g62",commit="newdeploy",
            first_cycle_after_deploy=False,
        )
        self.assertEqual(rows[0]["gate_confirmation"]["pass_streak"],1)
        self.assertTrue(state["candidates"][key]["first_raw_pass_utc"])

    def test_single_confirmation_failure_is_tolerated_then_stabilizes(self):
        s,rows=self._apply({},self._row(True),1,"2026-10-06T00:00:00+00:00")
        self.assertFalse(rows[0]["stable_gate_pass"])
        s,rows=self._apply(s,self._row(False,30),2,"2026-10-06T01:00:00+00:00")
        self.assertFalse(rows[0]["stable_gate_pass"])
        self.assertEqual(rows[0]["gate_confirmation"]["tolerated_fail_cycles"],1)
        s,rows=self._apply(
            s,self._row(True,domains=("a.example","b.example")),
            3,"2026-10-06T07:00:00+00:00",
        )
        self.assertTrue(rows[0]["stable_gate_pass"])
        self.assertEqual(rows[0]["gate_confirmation"]["tolerated_fail_cycles"],1)
        self.assertGreaterEqual(rows[0]["gate_confirmation"]["pass_ratio_in_window"],0.60)

    def test_three_consecutive_confirmation_failures_reset_series(self):
        s,_=self._apply({},self._row(True),1,"2026-10-06T00:00:00+00:00")
        for cycle,hour in ((2,1),(3,2),(4,3)):
            s,rows=self._apply(s,self._row(False,30),cycle,f"2026-10-06T0{hour}:00:00+00:00")
        key=rows[0]["gate_candidate_key"]
        self.assertEqual(s["candidates"][key]["first_raw_pass_utc"],"")
        self.assertEqual(s["candidates"][key]["pass_cycles"],[])
        self.assertEqual(s["candidates"][key]["confirmation_fail_streak"],0)
        self.assertEqual(s["candidates"][key]["tolerated_fail_cycles"],0)

    def test_low_pass_ratio_after_six_hours_resets_confirmation(self):
        s,_=self._apply({},self._row(True),1,"2026-10-06T00:00:00+00:00")
        s,_=self._apply(s,self._row(False,30),2,"2026-10-06T01:00:00+00:00")
        s,rows=self._apply(s,self._row(False,30),3,"2026-10-06T07:00:00+00:00")
        key=rows[0]["gate_candidate_key"]
        self.assertEqual(s["candidates"][key]["first_raw_pass_utc"],"")
        self.assertFalse(rows[0]["stable_gate_pass"])

    def test_one_failure_does_not_drop_stable_gate_but_two_distinct_do(self):
        s,_=self._apply({},self._row(True),1,"2026-10-06T00:00:00+00:00")
        s,rows=self._apply(
            s,self._row(True,domains=("a.example","b.example")),
            2,"2026-10-06T07:00:00+00:00",
        )
        self.assertTrue(rows[0]["stable_gate_pass"])
        s,rows=self._apply(s,self._row(False,30),3,"2026-10-06T08:00:00+00:00")
        self.assertTrue(rows[0]["stable_gate_pass"])
        s,rows=self._apply(s,self._row(False,30),4,"2026-10-06T09:00:00+00:00")
        self.assertFalse(rows[0]["stable_gate_pass"])

    def test_absent_candidate_decays_after_two_distinct_cycles(self):
        s,_=self._apply({},self._row(True),1,"2026-10-06T00:00:00+00:00")
        s,rows=self._apply(
            s,self._row(True,domains=("a.example","b.example")),
            2,"2026-10-06T07:00:00+00:00",
        )
        key=rows[0]["gate_candidate_key"]
        self.assertTrue(s["candidates"][key]["stable"])
        s,_=apply_gate_hysteresis(s,[],cycle=3,observed_at_utc="2026-10-06T08:00:00+00:00",tagger_version="3",genome_id="g60")
        self.assertTrue(s["candidates"][key]["stable"])
        s,_=apply_gate_hysteresis(s,[],cycle=4,observed_at_utc="2026-10-06T09:00:00+00:00",tagger_version="3",genome_id="g60")
        self.assertFalse(s["candidates"][key]["stable"])

    def test_identity_ignores_source_order_title_and_generated_text(self):
        a=self._row(True,tool="Invoice X",domains=("a.example","b.example"))
        a["title"]="Original title"
        a["trend"]="Generated wording A"
        b=dict(a)
        b["title"]="Completely reformulated title"
        b["trend"]="Generated wording B"
        b["sources"]=list(reversed(a["sources"]))
        self.assertEqual(opportunity_identity(a),opportunity_identity(b))

    def test_different_candidates_same_family_have_different_identity(self):
        self.assertNotEqual(
            opportunity_identity(self._row(True,tool="Invoice X")),
            opportunity_identity(self._row(True,tool="Invoice Y")),
        )


if __name__=="__main__":
    unittest.main()
