"""Regression for the captured gate -> family regex scan path."""
import json
import random
import re
from pathlib import Path
import unittest
from unittest.mock import patch

import evidence_integrity as evidence


def original_scores(text):
    """Pre-fix scorer, retained as the semantic reference, without a prefilter."""
    low = (text or '').lower()
    scores = {}
    for family, _ in evidence.FAMILY_TERMS:
        expansions = set(evidence.FAMILY_EXPANSIONS.get(family, ()))
        score = 0
        for term in evidence.family_relevance_terms(family):
            if not evidence.contains_term(low, term):
                continue
            words = max(1, len(term.split()))
            weight = 1 if words == 1 else min(6, words + 1)
            if term in expansions:
                weight += 2
            score += weight
        if score:
            scores[family] = score
    return scores


class FamilyClassificationPerformanceTests(unittest.TestCase):
    def test_all_terms_overlaps_boundaries_inflections_and_unicode_match_reference(self):
        terms = list(dict.fromkeys(t for f, _ in evidence.FAMILY_TERMS
                                  for t in evidence.family_relevance_terms(f)))
        cases = ['', 'manually spent spending spendt wasted half a day',
                 'invoices invoice reconciliation csv files manual workflow',
                 'excel excellent CRM crmfoo _crm crm_ ci/cd',
                 'fınance ınvoıce ſpreadſheet KPI İNVOICE Straße ﬃ']
        cases += [f'{term} {term.upper()} x{term}y _{term}_ ({term})' for term in terms]
        # Exercise IGNORECASE's extra Unicode equivalents inside actual aliases.
        cases += [t.replace('i', '\u0131').replace('s', '\u017f') for t in terms]
        rng = random.Random(215)
        alphabet = 'abc def_/-ıſİKßé01234\n'
        cases += [''.join(rng.choices(alphabet, k=250)) + ' ' + rng.choice(terms)
                  for _ in range(100)]
        for text in cases:
            with self.subTest(text=text[:60]):
                self.assertEqual(evidence.commercial_family_scores(text), original_scores(text))
        # Non-ASCII aliases deliberately bypass the literal prefilter.
        with patch.object(evidence, 'FAMILY_RELEVANCE_TERMS', {'finance_ops': ('ıſK', 'école')}):
            for text in ('ISK école', 'ıſK ÉCOLE'):
                self.assertEqual(evidence.commercial_family_scores(text), original_scores(text))

    def test_absent_terms_do_not_rescan_large_issue_body(self):
        text = ('unrelated context ' * 4000)[:65500] + ' invoices manual workflow csv files'
        expected = original_scores(text)
        with patch.object(evidence, 'contains_term', wraps=evidence.contains_term) as match:
            actual = evidence.commercial_family_scores(text)
        self.assertEqual(actual, expected)
        # Observed defect: 252 full regex scans for a largely unrelated body.
        # Preserve matches but bound expensive scans to possible aliases.
        self.assertLess(match.call_count, 25)

    def test_unmodified_public_control_texts_match_reference(self):
        for name in ('data/arena/research-algorithm/control_cases.json',
                     'data/challenge/control_cases.json'):
            data = json.loads(Path(name).read_text())
            def strings(value):
                if isinstance(value, str): yield value
                elif isinstance(value, dict):
                    for child in value.values(): yield from strings(child)
                elif isinstance(value, list):
                    for child in value: yield from strings(child)
            for text in strings(data):
                self.assertEqual(evidence.commercial_family_scores(text), original_scores(text))
