"""Semantic reference and regression for the observed intent regex stall."""
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch
import evidence_integrity as evidence


def original_contains_term(text, term):
    if not text or not term:
        return False
    return bool(evidence._term_regex(term).search(text))


class IntentClassificationPerformanceTests(unittest.TestCase):
    def test_literal_boundaries_controlled_forms_and_unicode_match_reference(self):
        terms = list(dict.fromkeys(
            list(evidence.BUYER_VOICE_PHRASES) + list(evidence.SUPPLY_OFFER_TERMS)
            + list(evidence.PAIN_TERMS) + list(evidence.BUY_INTENT_TERMS)
            + list(evidence.BUYER_PAID_TERMS) + ['spend', 'waste time', 'isk', 'école', 'ı', 'ſ', 'İ', 'ß', '   ']))
        texts = ['', 'manually spending spent spendt wasted half a day wasting our hours',
                 'I NEED i need İ NEED ı need ſeeking KPI ISK ıſK Straße ﬃ école',
                 'i\u0307 need _i need_ xi needy /i need/']
        texts += [f'{term} ({term.upper()}) x{term}y _{term}_' for term in terms]
        texts += [term.upper().replace('I', 'İ').replace('S', 'ſ').replace('K', 'K') for term in terms]
        rng = random.Random(216)
        texts += [''.join(rng.choices(' abcİıſKßéﬃ_0123\n', k=160)) for _ in range(60)]
        for text in texts:
            for term in terms:
                self.assertEqual(evidence.contains_term(text, term), original_contains_term(text, term),
                                 (text[:60], term))

    def test_absent_buyer_phrases_do_not_run_regex_on_large_body(self):
        text = ('unrelated context ' * 4000)[:65535]
        with patch.object(evidence, '_term_regex', wraps=evidence._term_regex) as regex:
            actual = [evidence.contains_term(text, phrase) for phrase in evidence.BUYER_VOICE_PHRASES]
        self.assertEqual(actual, [False] * len(evidence.BUYER_VOICE_PHRASES))
        self.assertEqual(regex.call_count, 0)

    def test_public_controls_keep_voice_intent_and_demand_decisions(self):
        def strings(value):
            if isinstance(value, str): yield value
            elif isinstance(value, dict):
                for child in value.values(): yield from strings(child)
            elif isinstance(value, list):
                for child in value: yield from strings(child)
        texts = ['we pay to automate this manual workflow', 'our tool pricing starts at 20',
                 'what do you use for invoices?', 'İ NEED help', 'wasting half a day']
        for name in ('data/arena/research-algorithm/control_cases.json', 'data/challenge/control_cases.json'):
            texts.extend(strings(json.loads(Path(name).read_text())))
        def decisions(text, source):
            return (evidence.buyer_voice_present('', text), evidence.seller_voice_present('', text),
                    evidence.first_person_buyer_voice_present('', text),
                    evidence.classify_intent_class('', text, 'https://example.test/issues/1', source),
                    evidence.demand_signal_type('', text, 'pain_research'))
        for text in texts:
            for source in ('github-issues-routed', 'brave-search'):
                with patch.object(evidence, 'contains_term', original_contains_term):
                    expected = decisions(text, source)
                self.assertEqual(decisions(text, source), expected)
