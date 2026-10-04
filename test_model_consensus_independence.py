import json
import tempfile
import unittest
from pathlib import Path
from model_judges import choose_automatic_label, lexicon_judge
from tools.model_shadow_batch import create_review_sample, nli_judge

class IndependentConsensusTests(unittest.TestCase):
    def test_models_and_structure_can_overrule_lexicon(self):
        votes=[{'judge':j,'label':'buyer_tool_search','confidence':.95} for j in ('nli','local_llm','structural')]
        votes.append({'judge':'lexicon','label':'vendor_offer','confidence':1})
        self.assertEqual(choose_automatic_label(votes)['label'],'buyer_tool_search')

    def test_lexicon_and_duplicates_cannot_supply_missing_judge(self):
        votes=[{'judge':j,'label':'buyer_tool_search','confidence':.95} for j in ('nli','local_llm','lexicon','nli')]
        self.assertFalse(choose_automatic_label(votes)['eligible_for_training'])


    def test_strict_model_pair_allowed_when_structural_abstains(self):
        votes=[
            {'judge':'nli','label':'buyer_tool_search','confidence':.95},
            {'judge':'local_llm','label':'buyer_tool_search','confidence':.90},
            {'judge':'structural','label':'other','confidence':.60},
            {'judge':'lexicon','label':'vendor_offer','confidence':1.0},
        ]
        result=choose_automatic_label(votes)
        self.assertTrue(result['eligible_for_training'])
        self.assertEqual(result['label'],'buyer_tool_search')
        self.assertEqual(result['agreed_judges'],2)

    def test_strict_model_pair_requires_high_confidence(self):
        votes=[
            {'judge':'nli','label':'buyer_tool_search','confidence':.95},
            {'judge':'local_llm','label':'buyer_tool_search','confidence':.84},
            {'judge':'structural','label':'other','confidence':.60},
        ]
        self.assertFalse(choose_automatic_label(votes)['eligible_for_training'])

    def test_structural_vote_must_agree_when_present(self):
        votes=[
            {'judge':'nli','label':'buyer_tool_search','confidence':.95},
            {'judge':'local_llm','label':'buyer_tool_search','confidence':.95},
            {'judge':'structural','label':'vendor_offer','confidence':.95},
        ]
        self.assertFalse(choose_automatic_label(votes)['eligible_for_training'])

    def test_unrecognized_lexicon_abstains(self):
        self.assertLess(lexicon_judge('','The weather is pleasant.','','')['confidence'],.7)

    def test_nli_has_neutral_and_coherent_template(self):
        def pipe(text, labels, **kwargs):
            self.assertIn('a generic discussion unrelated to these needs',labels)
            self.assertEqual(kwargs['hypothesis_template'],'This text describes {}.')
            return {'labels':['a generic discussion unrelated to these needs'],'scores':[.95]}
        self.assertEqual(nli_judge(pipe,'weather')['label'],'other')

    def test_discarded_model_disagreement_prioritized_for_review(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            rows=[{'id':'priority','final_label':'','judge_labels':[
                {'judge':j,'label':label,'confidence':.95} for j,label in (
                    ('nli','buyer_tool_search'),('local_llm','buyer_tool_search'),('lexicon','other'))]},
                {'id':'regular','final_label':'other'}]
            (p/'train_labeled.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            create_review_sample(p,1)
            self.assertEqual(json.loads((p/'weekly_review_queue.jsonl').read_text())['id'],'priority')
