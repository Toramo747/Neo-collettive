# SPDX-License-Identifier: BUSL-1.1
"""Validate experimental Arena gametes without executing external agents or changing production."""
from __future__ import annotations
import json
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACK = ROOT / "data/arena/gametes/seed-2026-10-09.json"
EXPECTED = {"collective-mind": 4, "llm-guided-search": 3, "warp-propulsion": 2, "research-algorithm": 1}
SCORE_KEYS = {"evidence", "confidence", "gain", "support"}
ROUTING_KEYS = {"name", "ready_bonus", "novelty_bonus", "prior_failure_penalty", "http_error_penalty"}
GUARD_KEYS = {"name", "abstention_threshold", "require_test_signal", "require_falsifier_signal"}
WARP_KEYS = {"family", "wall_thickness", "bubble_radius", "effective_beta", "shear_control", "lapse_modulation"}
ALGO_KEYS = {"query_mode", "query_count", "recency_days", "min_relevance_tokens", "suffix_family", "topic_shape", "query_frame", "term_order", "source_scope"}

def validate(data: dict) -> dict:
    assert data["schema_v"] == 1
    assert data["status"] == "SHADOW_CANDIDATES_NOT_VALIDATED"
    assert data["allocation"] == EXPECTED
    b = data["boundary"]
    for k in ("arena_only", "manual_review_required"):
        assert b[k] is True, k
    for k in ("network_calls", "external_agent_contact", "production_state_write", "automatic_promotion", "paid_provider_calls", "personal_data_included"):
        assert b[k] is False, k
    assert b["commercial_gate_influence"] == "NONE"
    assert b["commercial_evidence_influence"] == "NONE"
    gs = data["gametes"]
    assert len(gs) == 10 and len({g["id"] for g in gs}) == 10
    for arena, count in EXPECTED.items():
        assert sum(g["arena"] == arena for g in gs) == count
    for g in gs:
        assert all(isinstance(g[k], str) and len(g[k]) >= 35 for k in ("hypothesis", "method", "falsifier"))
        genes = g["genes"]
        if g["kind"] == "score_genome":
            assert set(genes) == SCORE_KEYS and sum(genes.values()) == 100
            assert all(isinstance(x,(int,float)) and math.isfinite(x) and x>=0 for x in genes.values())
        elif g["kind"] == "routing":
            assert set(genes) == ROUTING_KEYS
            assert all(isinstance(x,int) and 0 <= x <= 40 for k,x in genes.items() if k != "name")
        elif g["kind"] == "quality_guard":
            assert set(genes) == GUARD_KEYS and 1 <= genes["abstention_threshold"] <= 99
            assert type(genes["require_test_signal"]) is bool and type(genes["require_falsifier_signal"]) is bool
        elif g["kind"] == "prompt_mutation":
            assert set(genes) == {"parent_mutation","instruction"}
            assert genes["parent_mutation"] in ("first_person_pain","buyer_intent","paid_demand","operational_burden","pain_plus_buyer","pain_plus_burden","buyer_plus_paid","precision_pain")
            assert len(genes["instruction"]) <= 400
        elif g["kind"] == "theoretical_candidate":
            assert set(genes) == WARP_KEYS
            assert genes["family"] in ("alcubierre_like","natario_like","irrotational_shift","positive_energy_subluminal")
            for key,low,high in (("wall_thickness",.08,1.25),("bubble_radius",.5,3),("effective_beta",.2,1.5),("shear_control",0,1),("lapse_modulation",0,.4)):
                assert low <= genes[key] <= high
        elif g["kind"] == "query_genome":
            assert set(genes) == ALGO_KEYS
            assert genes["query_mode"] in ("pain","buyer","workaround","mixed")
            assert genes["suffix_family"] in ("core","intent","ops")
            assert genes["topic_shape"] in ("exact","compact")
            assert genes["query_frame"] in ("plain","need","looking_for")
            assert genes["term_order"] in ("topic_first","signal_first")
            assert genes["source_scope"] in ("comments","stories","all")
            assert 2 <= genes["query_count"] <= 4 and 7 <= genes["recency_days"] <= 45 and 1 <= genes["min_relevance_tokens"] <= 3
        else:
            raise AssertionError("Unrecognized kind: " + str(g["kind"]))
    return {"valid":True,"count":len(gs),"allocation":EXPECTED,"production_promoted":False,"fitness_measured":False}

class PackTests(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(PACK.read_text(encoding="utf-8"))
    def test_pack_contract(self):
        self.assertTrue(validate(self.data)["valid"])
    def test_no_autopromotion(self):
        self.assertFalse(self.data["boundary"]["automatic_promotion"])
    def test_reject_mutated_guard(self):
        data=json.loads(json.dumps(self.data))
        data["boundary"]["commercial_gate_influence"]="ENABLED"
        with self.assertRaises(AssertionError):
            validate(data)
    def test_reject_invalid_warp_beta(self):
        data=json.loads(json.dumps(self.data))
        next(g for g in data["gametes"] if g["id"]=="WARP-01")["genes"]["effective_beta"]=5
        with self.assertRaises(AssertionError):
            validate(data)
    def test_reject_duplicate_id(self):
        data=json.loads(json.dumps(self.data))
        data["gametes"][1]["id"]=data["gametes"][0]["id"]
        with self.assertRaises(AssertionError):
            validate(data)

if __name__ == "__main__":
    unittest.main()
