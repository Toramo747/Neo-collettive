import time
import unittest
import arena_local_a2a_evolution as arena

class LocalA2AEvolutionTests(unittest.TestCase):
    def test_stratified_holdout_and_unique_cases(self):
        cases=arena.cases()
        self.assertEqual(len({c['id'] for c in cases}),30)
        for family in {c['family'] for c in cases}:
            self.assertEqual(sum(c['family']==family and c['split']=='holdout' for c in cases),2)
            self.assertEqual(sum(c['family']==family and c['split']=='train' for c in cases),3)

    def test_schema_does_not_reward_wrong_decision_or_placeholder(self):
        case=arena.cases()[0];turn=case['turns'][0]
        answer={'decision':'propose','problem_id':turn['problem_id'],'evidence_id':'','reason':'This is one concise falsifiable idea copied from the example.'}
        result=arena.evaluate(answer,turn,'ask')
        self.assertTrue(result['schema'])
        self.assertFalse(result['accepted'])
        self.assertFalse(result['substance'])
        answer.update(decision='ask',reason='Ask for read-only timing measurements before proposing a retry comparison.')
        self.assertTrue(arena.evaluate(answer,turn,'ask')['accepted'])
        answer['problem_id']='different-thread'
        self.assertFalse(arena.evaluate(answer,turn,'ask')['accepted'])

    def test_three_turns_reuse_actual_output_and_review_is_bounded(self):
        case=arena.cases()[0];calls=[]
        def infer(model,prompt,remaining):
            calls.append(prompt)
            index=min((len(calls)-1)//3,2)
            turn=case['turns'][index]
            return {'decision':case['expected'][index],'problem_id':case['id'],'evidence_id':turn['evidence_id'],'reason':'Measure first attempts separately from retries using a bounded read-only comparison.'}
        result=arena.run_config('test','critique_once',[case],time.monotonic()+10,call=infer)
        self.assertEqual(len(calls),9)
        self.assertTrue(result['results'][0]['dialogue_3_of_3'])
        self.assertIn('CANDIDATE:',calls[1])
        self.assertIn('CRITIQUE:',calls[2])
        self.assertIn('Measure first attempts',calls[3])
        self.assertNotIn('expected',calls[0])

    def test_screening_is_train_only_and_stratified(self):
        train=[c for c in arena.cases() if c['split']=='train']
        screen=arena.screening_cases(train)
        self.assertEqual(len(screen),6)
        self.assertEqual({family for _,family,_,_ in screen},
                         {'timeout','schema','context','out_of_scope','injection','missing_data'})
        holdout_ids={c['id'] for c in arena.cases() if c['split']=='holdout'}
        self.assertFalse(any(case_id in holdout_ids for case_id,_,_,_ in screen))

    def test_gamete_population_expands_without_touching_holdout(self):
        population=[(m,p,v) for m in arena.MODELS for p in arena.POLICIES for v in arena.PROMPT_VARIANTS]
        self.assertEqual(len(population),12)
        self.assertEqual(arena.POLICIES,('direct','self_review','hybrid_guard'))
        self.assertEqual(arena.PROMPT_VARIANTS,('base','strict'))

    def test_hybrid_guard_handles_only_obvious_cases(self):
        rows={c['family']:c for c in arena.cases() if c['split']=='train'}
        inj=rows['injection']['turns'][0]
        med=rows['out_of_scope']['turns'][0]
        miss=rows['missing_data']['turns'][0]
        measured=rows['timeout']['turns'][1]
        self.assertEqual(arena.deterministic_guard(inj)['decision'],'refuse')
        self.assertEqual(arena.deterministic_guard(med)['decision'],'abstain')
        self.assertEqual(arena.deterministic_guard(miss)['decision'],'ask')
        self.assertEqual(arena.deterministic_guard(measured)['decision'],'propose')
        revised=rows['timeout']['turns'][2]
        self.assertEqual(arena.deterministic_guard(revised)['decision'],'revise')

    def test_robustness_cases_are_separate_from_train_and_holdout(self):
        base_ids={c['id'] for c in arena.cases()}
        robust=arena.robustness_cases()
        self.assertEqual(len(robust),6)
        self.assertTrue(all(c['split']=='robustness' for c in robust))
        self.assertFalse(base_ids & {c['id'] for c in robust})

    def test_deadline_blocks_selection_fitness(self):
        result=arena.run_config('test','direct',arena.cases(),time.monotonic()-1)
        self.assertFalse(result['complete'])
        self.assertIsNone(result['fitness'])

if __name__=='__main__':unittest.main()
