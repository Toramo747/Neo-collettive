import unittest

from ingestion_diagnostics import (
    IngestionDiagnostics,
    canonical_source,
    diagnostic_query_class,
    routed_search_diagnostics,
)


class IngestionDiagnosticsTests(unittest.TestCase):
    def test_source_aliases_are_stable(self):
        self.assertEqual(canonical_source("bing-rss-free"), "bing-rss")
        self.assertEqual(canonical_source("hn-algolia-routed"), "hn")
        self.assertEqual(canonical_source("github-issues-routed"), "github")
        self.assertEqual(canonical_source("stackexchange-routed"), "stackexchange")

    def test_query_class_prefers_planner_class(self):
        self.assertEqual(diagnostic_query_class({"class": "thesis", "role": "buyer"}), "thesis")
        self.assertEqual(diagnostic_query_class({"class": "thesis", "role": "disconfirm"}), "disconfirm")

    def test_routed_diagnostics_count_raw_and_relevance_passes(self):
        batches = [
            {"results": [{"title": "A", "url": "https://a.test/1", "snippet": "pain", "source": "bing-rss-free"}]},
            [{"title": "B", "url": "https://b.test/1", "snippet": "noise", "source": "hn-algolia-routed"}],
            [{"title": "C", "url": "https://c.test/1", "snippet": "pain", "source": "github-issues-routed"}],
            [{"title": "D", "url": "https://d.test/1", "snippet": "pain", "source": "stackexchange-routed"}],
        ]

        def relevance(_title, snippet, _query, _meta):
            return {"relevant": snippet == "pain"}

        result = routed_search_diagnostics(batches, "q", {"class": "explore"}, relevance)
        self.assertEqual(result["raw_by_source"], {"bing-rss": 1, "hn": 1, "github": 1, "stackexchange": 1})
        self.assertEqual(result["query_relevance_pass_by_source"], {"bing-rss": 1, "github": 1, "stackexchange": 1})
        self.assertEqual(result["query_relevance_pass_by_source_and_class"]["github"], {"explore": 1})

    def test_cycle_snapshot_merges_search_scout_and_rejections(self):
        diag = IngestionDiagnostics(True)
        diag.merge_web_research([{
            "ingestion_diagnostics": {
                "raw_by_source": {"bing-rss": 2, "github": 1},
                "query_relevance_pass_by_source": {"bing-rss": 1},
                "query_relevance_pass_by_source_and_class": {"bing-rss": {"convergence": 1}},
                "diagnostic_errors": 0,
            }
        }])
        diag.add_raw_rows([{"source": "hackernews"}])
        diag.record_rejection("no_family", "bing-rss-free", "explore")
        snap = diag.snapshot()
        self.assertEqual(snap["raw_results_by_source"]["bing-rss"], 2)
        self.assertEqual(snap["raw_results_by_source"]["hn"], 1)
        self.assertEqual(snap["rejected_by_source"]["bing-rss"], {"no_family": 1})
        self.assertEqual(snap["rejected_by_query_class"]["explore"], {"no_family": 1})

    def test_self_contamination_counter_is_explicit(self):
        diag=IngestionDiagnostics(True)
        diag.record_rejection("self_contamination_rejected","github-issues-routed","explore")
        snap=diag.snapshot()
        self.assertEqual(snap["self_contamination_rejected"],1)
        self.assertEqual(
            snap["rejected_by_reason"]["self_contamination_rejected"],
            1,
        )

    def test_disabled_diagnostics_are_noop(self):
        diag = IngestionDiagnostics(False)
        diag.add_raw_rows([{"source": "hackernews"}])
        diag.record_rejection("no_family", "hackernews", "scout")
        self.assertEqual(diag.snapshot(), {"enabled": False})



    def test_observed_candidate_purge_is_counted_with_reason(self):
        d=IngestionDiagnostics(True)
        d.record_observed_candidate_purge("seller_launch")
        d.record_observed_candidate_purge("family_term_missing_in_pain",2)
        snap=d.snapshot()
        self.assertEqual(snap["observed_candidates_purged"],3)
        self.assertEqual(
            snap["observed_candidates_purged_by_reason"],
            {"family_term_missing_in_pain":2,"seller_launch":1},
        )


    def test_yield_and_revalidation_metrics_are_visible(self):
        d=IngestionDiagnostics(True)
        d.record_new_signal_row("hn-algolia-routed","explore")
        d.record_new_signal_row("remoteok-api","paid_market")
        d.merge_revalidation({"attempted":3,"promoted":1,"failed":1,"unreachable":1})
        snap=d.snapshot()
        self.assertEqual(snap["new_signal_rows"],2)
        self.assertEqual(snap["new_signal_rows_by_source"],{"hn":1,"remoteok-api":1})
        self.assertEqual(snap["new_signal_rows_by_query_class"],{"explore":1,"paid_market":1})
        self.assertEqual(
            snap["revalidation"],
            {"attempted":3,"promoted":1,"failed":1,"unreachable":1},
        )


    def test_desire_experiment_metrics_and_sample_are_visible(self):
        d=IngestionDiagnostics(True)
        d.record_intent_result(
            "solution_search","desire",
            "Is there a tool for invoice entry?",
            "https://example.com/thread/1",
            ["BUY_INTENT"],
            "brave-search",
        )
        d.record_intent_result(
            "paid_automation","desire",
            "We need to hire someone to automate invoice entry",
            "https://example.com/thread/2",
            ["BUY_INTENT","PAID_DEMAND"],
            "brave-search",
        )
        d.record_intent_result(
            "","pain",
            "Manual invoice entry is repetitive",
            "https://example.com/thread/3",
            ["PAIN"],
            "hn-algolia-routed",
        )
        snap=d.snapshot()
        self.assertEqual(snap["rows_by_intent_class"],{
            "paid_automation":1,
            "solution_search":1,
        })
        self.assertEqual(snap["buyer_signals_by_query_intent"]["desire"],{
            "BUY_INTENT":2,
            "PAID_DEMAND":1,
        })
        self.assertEqual(len(snap["intent_review_sample"]),3)
        self.assertEqual(snap["intent_review_sample"][0]["query_intent"],"desire")
        self.assertEqual(snap["intent_review_sample"][1]["intent_class"],"paid_automation")

    def test_search_provider_fallback_reasons_are_visible(self):
        d=IngestionDiagnostics(True)
        d.set_search_provider({
            "name":"brave",
            "calls_cycle":8,
            "calls_day":8,
            "errors":3,
            "fallbacks":3,
            "fallback_reasons":{"HTTPStatusError:429":2,"ReadTimeout":1},
        })
        snap=d.snapshot()
        self.assertEqual(snap["search_provider"]["name"],"brave")
        self.assertEqual(snap["search_provider"]["fallback_reasons"],{
            "HTTPStatusError:429":2,
            "ReadTimeout":1,
        })

if __name__ == "__main__":
    unittest.main()
