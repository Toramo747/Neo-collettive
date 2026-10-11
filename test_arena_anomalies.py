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

    def test_run_writes_metadata_only_and_flags_controls(self):
        feed = atom([("2610.9", "2026-10-02T00:00:00Z", "X", "A 4 sigma discrepancy remains.")])
        with tempfile.TemporaryDirectory() as d:
            r = a.run(Path(d), fetch=lambda q: feed, now=NOW, pause=0)
            self.assertEqual(len(r["anomalies"]), len(a.ANOMALIES))
            self.assertTrue(r["controls_ok"])        # first observation: nothing strengthening yet
            self.assertFalse(r["boundary"]["automatic_physical_claims"])
            dumped = json.dumps(r)
            self.assertNotIn("A 4 sigma discrepancy remains", dumped)  # abstracts are not persisted
            r2 = a.run(Path(d), fetch=lambda q: atom([]), now=NOW, pause=0)
            st = json.loads((Path(d) / "state.json").read_text())
            st["scoring_v"] = -1
            (Path(d) / "state.json").write_text(json.dumps(st))
            r3 = a.run(Path(d), fetch=lambda q: feed, now=NOW, pause=0)
            self.assertEqual(r3["anomalies"]["hubble_tension"]["trend"]["status"], "FIRST_OBSERVATION")
            self.assertEqual(r2["anomalies"]["hubble_tension"]["papers"], 0)
