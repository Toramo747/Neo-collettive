import ast
import asyncio
from runtime_observation import OBSERVATION
from pathlib import Path
import unittest

from ingestion_diagnostics import IngestionDiagnostics, routed_search_diagnostics
from public_snapshot import sanitize_public_snapshot


def load_research(search):
    tree=ast.parse(Path('cloud_mcp.py').read_text())
    fn=next(x for x in tree.body if isinstance(x,ast.AsyncFunctionDef) and x.name=='_free_web_research')
    ns={'OBSERVATION':OBSERVATION,'asyncio':asyncio,'routed_public_search':search}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'cloud_mcp.py','exec'),ns)
    return ns['_free_web_research']


class ResearchDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_deadline_keeps_completed_query_and_cancels_only_pending(self):
        cancelled=asyncio.Event()
        diag=routed_search_diagnostics([{'results':[{
            'source':'brave-search','url':'https://example.test/a','title':'A','snippet':'pain'
        }]}],'fast',{},lambda *args:{'relevant':True},['web'])
        async def search(q,meta,limit):
            if q=='fast':
                return {'query':q,'results':[{'url':'https://example.test/a'}],
                        'ingestion_diagnostics':diag}
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        rows=await load_research(search)(['fast','slow'],timeout_seconds=.02)
        self.assertTrue(cancelled.is_set())
        d=IngestionDiagnostics();d.set_queries_planned(2);d.merge_web_research(rows)
        funnel=d.snapshot()['funnel']
        self.assertEqual(funnel['queries_executed'],1)
        self.assertEqual(funnel['raw_received'],1)
        self.assertEqual(funnel['queries_skipped_by_reason'],{'deadline':1})
        self.assertEqual(funnel['errors_by_source'],{'web':{'web_research_deadline_exceeded':1}})

    async def test_empty_plan_and_query_cap_are_explicit(self):
        calls=[]
        async def search(q,meta,limit):
            calls.append(q);return {'query':q,'results':[]}
        fn=load_research(search)
        empty=await fn([],query_meta={'planned':{}})
        d=IngestionDiagnostics();d.merge_web_research(empty)
        self.assertEqual(d.snapshot()['funnel']['queries_skipped_by_reason'],{'empty_plan':1})
        rows=await fn([str(i) for i in range(12)],timeout_seconds=1)
        d=IngestionDiagnostics();d.merge_web_research(rows)
        self.assertEqual(len(calls),10)
        self.assertEqual(d.snapshot()['funnel']['queries_skipped_by_reason'],{'query_limit':2})

    async def test_money_deadline_retains_distinct_error_code(self):
        async def search(*args):
            await asyncio.Event().wait()
        rows=await load_research(search)(['money'],timeout_seconds=.01,
                                       deadline_code='money_first_deadline_exceeded')
        d=IngestionDiagnostics();d.merge_web_research(rows)
        self.assertEqual(d.snapshot()['funnel']['errors_by_source'],
                         {'web':{'money_first_deadline_exceeded':1}})

    def test_nonweb_scouts_use_the_same_funnel_and_safe_projection(self):
        d=IngestionDiagnostics()
        rows=[{'source':'github-issues','url':'https://example.test/a'},
              {'source':'mcp-registry','url':'https://example.test/b'}]
        d.add_raw_rows(rows)
        for row in rows:d.record_scout_deduped(row)
        d.record_scout_relevance('github-issues','scout')
        d.record_funnel_stage('family_matched')
        snap=d.snapshot()
        self.assertEqual(snap['funnel']['raw_received'],2)
        self.assertEqual(snap['funnel']['deduped'],2)
        self.assertEqual(snap['funnel']['query_relevant'],1)
        self.assertEqual(snap['query_relevance_pass_by_source']['github'],1)
        self.assertEqual(snap['funnel']['monotonicity_warnings'],[])
        snap['funnel']['queries_skipped_by_reason']={'deadline':2}
        public=sanitize_public_snapshot({'latest_result':{'evidence_quality':{
            'ingestion_diagnostics':snap}},'autopilot':{}})
        projected=public['autopilot']['select_diagnostics']['funnel']
        self.assertEqual(projected['queries_skipped_by_reason'],[{'reason':'deadline','count':2}])
        self.assertNotIn('https://',str(public))


if __name__=='__main__':unittest.main()
