import unittest

from evaluator_contract import EvaluatorContract, no_hardcoded_answers, run_evaluator_contract, validate_genome
from evaluator_paths import CHALLENGE_CONTRACT, RESEARCH_CONTRACT, WARP_CONTRACT


class EvaluatorContractTests(unittest.TestCase):
    def test_schema_rejects_unknown_and_out_of_bounds(self):
        with self.assertRaises(ValueError):
            validate_genome({"x":{"type":"int","min":1,"max":2}},{"x":3})
        with self.assertRaises(ValueError):
            validate_genome({"x":{"type":"int","min":1,"max":2}},{"x":1,"y":2})

    def test_robustness_failure_zeroes_effective_fitness(self):
        contract=EvaluatorContract(
            name="synthetic",
            genome_schema={"x":{"type":"float","min":0.0,"max":1.0}},
            evaluate=lambda g:{"fitness":80.0},
            benchmarks=({"genome":{"x":0.5},"expected":{"fitness":80.0}},),
            robustness=lambda g:{"ok":False,"max_relative_delta":0.06},
            control_set=lambda:{"public_ok":True,"hidden_ok":True},
        )
        report=run_evaluator_contract(contract,{"x":0.5})
        self.assertFalse(report["robustness_ok"])
        self.assertEqual(report["best_fitness"],0.0)
        self.assertFalse(report["promotion_ready"])

    def test_hidden_control_is_required_for_promotion(self):
        contract=EvaluatorContract(
            name="synthetic",
            genome_schema={"x":{"type":"int","min":0,"max":1}},
            evaluate=lambda g:{"fitness":1.0},
            benchmarks=({"genome":{"x":0},"expected":{"fitness":1.0}},),
            robustness=lambda g:{"ok":True,"max_relative_delta":0.0},
            control_set=lambda:{"public_ok":True,"hidden_ok":False},
        )
        report=run_evaluator_contract(contract,{"x":0})
        self.assertFalse(report["control_ok"])
        self.assertFalse(report["promotion_ready"])

    def test_hardcoded_family_factor_is_detected(self):
        def score_family(genome):
            factor={"alpha":1.0,"beta":0.5}[genome["family"]]
            return {"fitness":factor}
        check=no_hardcoded_answers((score_family,),("alpha","beta"))
        self.assertFalse(check["ok"])
        self.assertGreater(check["violations"],0)

    def test_three_paths_declare_full_contract(self):
        for contract in (RESEARCH_CONTRACT,CHALLENGE_CONTRACT,WARP_CONTRACT):
            self.assertTrue(contract.genome_schema)
            self.assertTrue(callable(contract.evaluate))
            self.assertTrue(contract.benchmarks)
            self.assertTrue(callable(contract.robustness))
            self.assertTrue(callable(contract.control_set))
            self.assertEqual(contract.promotion_mode,"MANUAL_REVIEW_ONLY")

    def test_research_contract_benchmark_and_robustness_are_deterministic(self):
        genome={
            "query_mode":"mixed","query_count":4,"recency_days":45,"min_relevance_tokens":1,
            "suffix_family":"core","topic_shape":"compact","query_frame":"plain",
            "term_order":"signal_first","source_scope":"all",
        }
        report=run_evaluator_contract(RESEARCH_CONTRACT,genome)
        self.assertTrue(report["benchmark_ok"])
        self.assertTrue(report["robustness_ok"])
        # CI has no hidden production holdout, so promotion must fail closed.
        self.assertFalse(report["promotion_ready"])

    def test_challenge_contract_known_benchmark(self):
        genome={
            "min_requesters":3,"min_domains":2,"min_age_days":60,
            "require_workaround":True,"hard_blocks":True,
        }
        report=run_evaluator_contract(CHALLENGE_CONTRACT,genome)
        self.assertTrue(report["benchmark_ok"])
        self.assertTrue(report["robustness_ok"])
        self.assertEqual(report["raw_fitness"],100.0)
        self.assertFalse(report["promotion_ready"])

    def test_warp_contract_is_blocked_until_phase2(self):
        genome={
            "family":"positive_energy_subluminal","wall_thickness":0.5,"bubble_radius":1.0,
            "effective_beta":0.75,"shear_control":0.65,"lapse_modulation":0.04,
        }
        report=run_evaluator_contract(WARP_CONTRACT,genome)
        self.assertTrue(report["benchmark_ok"])
        self.assertFalse(report["robustness_ok"])
        self.assertFalse(report["no_hardcoded_answers_ok"])
        self.assertEqual(report["best_fitness"],0.0)
        self.assertFalse(report["promotion_ready"])


if __name__=="__main__":
    unittest.main()
