"""Offline tests for the Anomaly Arena (no network)."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import arena_anomalies as a

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def atom(entries):
    body = "".join(
        f"<entry><id>http://arxiv.org/abs/{i}</id><published>{p}</published><title>{t}</title><summary>{s}</summary></entry>"
        for i, p, t, s in entries)
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'


class AnomalyTests(unittest.TestCase):
    def test_query_phrase_is_not_a_tension_cue(self):
        e = a.parse_entries(atom([("2610.5", "2026-10-01T00:00:00Z", "H", "We revisit the Hubble tension with new data.")]))
        self.assertEqual(a.score(e, NOW, query='abs:"Hubble tension"')["tension_cues"], 0)

    def test_scoring_counts_cues_and_sigmas(self):
        e = a.parse_entries(atom([
            ("2610.1", "2026-10-01T00:00:00Z", "T1", "We find a 5.0 sigma tension with Planck."),
            ("2610.2", "2026-09-01T00:00:00Z", "T2", "Results are consistent with LCDM, no tension."),
            ("2001.3", "2020-01-01T00:00:00Z", "Old", "A 9 sigma anomaly."),
        ]))
        s = a.score(e, NOW)
        self.assertEqual(s["papers"], 2)              # 2020 paper outside the window
        self.assertEqual(s["tension_cues"], 1)        # "no tension" is a resolution cue, not a tension cue
        self.assertEqual(s["resolution_cues"], 1)
        self.assertEqual(s["sigma_median"], 5.0)

    def test_trend_labels(self):
        self.assertEqual(a.trend({"persistence": 0.5}, None)["status"], "FIRST_OBSERVATION")
        self.assertEqual(a.trend({"persistence": 0.6, "sigma_median": 4}, {"persistence": 0.4, "sigma_median": 4})["status"], "STRENGTHENING")
        self.assertEqual(a.trend({"persistence": 0.1, "sigma_median": 3}, {"persistence": 0.4, "sigma_median": 4})["status"], "FADING")

    def test_low_sample_has_no_trend_and_cannot_calibrate(self):
        self.assertEqual(a.trend({"persistence": 0.9, "low_sample": True}, {"persistence": 0.1})["status"], "INSUFFICIENT_DATA")
        one = atom([("2610.1", "2026-10-02T00:00:00Z", "X", "A puzzle remains.")])
        with tempfile.TemporaryDirectory() as d:
            r = a.run(Path(d), fetch=lambda q: one, now=NOW, pause=0, classify=False)
        self.assertIsNone(r["controls_ok"])
        self.assertTrue(all(x["low_sample"] for x in r["anomalies"].values()))

    def test_topic_name_is_not_a_tension_cue(self):
        q = 'abs:"proton radius" OR abs:"proton charge radius" "proton radius puzzle"'
        self.assertNotIn("puzzle", a.strip_query_echo("New data on the proton radius puzzle.", q))

    def test_changed_query_breaks_the_trend(self):
        feed = atom([(f"2610.{i}", "2026-10-02T00:00:00Z", "X", "A 4 sigma discrepancy remains.") for i in range(12)])
        with tempfile.TemporaryDirectory() as d:
            st = {"scoring_v": a.SCORING_V, "last": {
                "proton_radius_control": {"papers": 3, "persistence": 0.1, "sigma_median": None},
                "hubble_tension": {"papers": 12, "persistence": 0.1, "sigma_median": None}}}
            (Path(d) / "state.json").write_text(json.dumps(st))
            r = a.run(Path(d), fetch=lambda q: feed, now=NOW, pause=0, classify=False)
            st2 = json.loads((Path(d) / "state.json").read_text())
        self.assertEqual(r["anomalies"]["proton_radius_control"]["trend"]["status"], "FIRST_OBSERVATION")
        self.assertNotEqual(r["anomalies"]["hubble_tension"]["trend"]["status"], "FIRST_OBSERVATION")
        self.assertIn("query", st2["last"]["hubble_tension"])

    def test_classifier_mode_uses_stance_and_separate_baseline(self):
        feed = atom([(f"2610.{i}", "2026-10-02T00:00:00Z", "X", "A 4 sigma discrepancy remains.") for i in range(12)])
        fake = lambda texts: ["resolves" if i % 3 == 0 else "neutral" for i, _ in enumerate(texts)]
        with tempfile.TemporaryDirectory() as d:
            a.run(Path(d), fetch=lambda q: feed, now=NOW, pause=0, classify=False)
            r = a.run(Path(d), fetch=lambda q: feed, now=NOW, pause=0, classify=fake)
            st = json.loads((Path(d) / "state.json").read_text())
        h = r["anomalies"]["hubble_tension"]
        self.assertEqual(r["scoring_mode"], "stance-classifier-v1")
        self.assertEqual(r["scoring_v"], a.SCORING_V_CLASSIFIER)
        self.assertEqual(h["stance_model"]["resolves"], 4)
        self.assertEqual(h["persistence"], round(-4 / 12, 3))
        self.assertNotEqual(h["persistence"], h["persistence_cue"])
        self.assertEqual(h["trend"]["status"], "FIRST_OBSERVATION")   # cue-word baseline is not comparable
        self.assertEqual(set(st["last_by_v"]), {str(a.SCORING_V), str(a.SCORING_V_CLASSIFIER)})
        self.assertNotIn("A 4 sigma discrepancy remains", json.dumps(r))

    def test_control_outranking_real_anomalies_is_flagged(self):
        rows = {"real": {"control": False, "low_sample": False, "persistence": 0.1, "trend": {"status": "STABLE"}},
                "ctl": {"control": True, "low_sample": False, "persistence": 0.6, "trend": {"status": "FIRST_OBSERVATION"}}}
        ok, note = a.controls_check(rows)
        self.assertFalse(ok)
        self.assertIn("outranks", note)

    def test_run_writes_metadata_only_and_flags_controls(self):
        feed = atom([(f"2610.{i}", "2026-10-02T00:00:00Z", "X", "A 4 sigma discrepancy remains.") for i in range(12)])
        with tempfile.TemporaryDirectory() as d:
            r = a.run(Path(d), fetch=lambda q: feed, now=NOW, pause=0, classify=False)
            self.assertEqual(len(r["anomalies"]), len(a.ANOMALIES))
            # Same feed for every query: the control ties the real anomalies, it does not outrank them.
            self.assertTrue(r["controls_ok"], r["controls_note"])
            self.assertFalse(r["boundary"]["automatic_physical_claims"])
            dumped = json.dumps(r)
            self.assertNotIn("A 4 sigma discrepancy remains", dumped)  # abstracts are not persisted
            r2 = a.run(Path(d), fetch=lambda q: atom([]), now=NOW, pause=0, classify=False)
            st = json.loads((Path(d) / "state.json").read_text())
            st["scoring_v"] = -1          # an older, incomparable scoring version
            st.pop("last_by_v", None)
            (Path(d) / "state.json").write_text(json.dumps(st))
            r3 = a.run(Path(d), fetch=lambda q: feed, now=NOW, pause=0, classify=False)
            self.assertEqual(r3["anomalies"]["hubble_tension"]["trend"]["status"], "FIRST_OBSERVATION")
            self.assertEqual(r2["anomalies"]["hubble_tension"]["papers"], 0)


class ControlAndRetryTests(unittest.TestCase):
    def test_missing_control_is_not_calibrated(self):
        import arena_anomalies as A
        rows = {"hubble": {"control": False, "persistence": 0.4, "low_sample": False, "trend": {"status": "STABLE"}}}
        ok, note = A.controls_check(rows, expected_controls=1)
        self.assertIsNone(ok)
        self.assertIn("not fetched", note)

    def test_fetch_retries_then_succeeds(self):
        import arena_anomalies as A
        from unittest import mock
        calls = {"n": 0}
        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"<feed/>"
        def fake(req, timeout=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError()
            return R()
        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep", lambda s: None):
            self.assertEqual(A.fetch_atom("q"), "<feed/>")
        self.assertEqual(calls["n"], 3)
