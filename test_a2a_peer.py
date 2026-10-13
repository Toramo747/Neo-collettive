"""Offline synthetic fixtures; never run real network requests."""
import ast
import copy
from pathlib import Path
import unittest
from unittest.mock import patch, AsyncMock
import a2a_peer as peer
from a2a_peer import Interface, parse_reply, select_interface, send_request

CARD_URL='https://peer.example.net/.well-known/agent-card.json'
ENDPOINT='https://peer.example.net/a2a'
V1={'name':'Synthetic fixture','supportedInterfaces':[{'url':ENDPOINT,'protocolBinding':'JSONRPC','protocolVersion':'1.0'}]}
V03={'name':'Legacy fixture','protocolVersion':'0.3.0','url':ENDPOINT,'preferredTransport':'JSONRPC'}

class ContractTests(unittest.TestCase):
    def test_v1_interface_selected(self):
        self.assertEqual(select_interface(V1,CARD_URL),Interface(ENDPOINT,'1.0'))

    def test_v03_preserved(self):
        self.assertEqual(select_interface(V03,CARD_URL),Interface(ENDPOINT,'0.3'))

    def test_unknown_version_not_downgraded(self):
        card=copy.deepcopy(V1)
        card['supportedInterfaces'][0]['protocolVersion']='9.0'
        with self.assertRaises(ValueError): select_interface(card,CARD_URL)

    def test_unsupported_transport_rejected(self):
        card=copy.deepcopy(V1)
        card['supportedInterfaces'][0]['protocolBinding']='GRPC'
        with self.assertRaises(ValueError): select_interface(card,CARD_URL)

    def test_explicit_cross_origin_interface_is_allowed(self):
        card=copy.deepcopy(V1)
        card['supportedInterfaces'][0]['url']='https://different.example.net/a2a'
        self.assertEqual(select_interface(card,CARD_URL),Interface('https://different.example.net/a2a','1.0'))

    def test_private_ip_and_http_rejected(self):
        for url in ('https://127.0.0.1/a2a','https://10.0.0.1/a2a','http://peer.example.net/a2a'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                select_interface({**V03,'url':url},CARD_URL)

    def test_card_is_not_rpc_endpoint(self):
        with self.assertRaises(ValueError): select_interface({**V03,'url':CARD_URL},CARD_URL)

    def test_v1_wire_format(self):
        body,headers=send_request(Interface(ENDPOINT,'1.0'),'fixture')
        self.assertEqual(headers['A2A-Version'],'1.0')
        self.assertEqual(body['method'],'SendMessage')
        self.assertEqual(body['params']['message']['role'],'ROLE_USER')
        self.assertNotIn('kind',body['params']['message']['parts'][0])

    def test_v1_tenant_header(self):
        _,headers=send_request(Interface(ENDPOINT,'1.0','tenant-a'),'fixture')
        self.assertEqual(headers['A2A-Tenant'],'tenant-a')

    def test_invalid_tenant_is_rejected_by_interface_selection(self):
        card=copy.deepcopy(V1)
        card['supportedInterfaces'][0]['tenant']='x\nunsafe'
        with self.assertRaises(ValueError):
            select_interface(card,CARD_URL)

    def test_v03_wire_format(self):
        body,headers=send_request(Interface(ENDPOINT,'0.3'),'fixture')
        self.assertEqual(headers['A2A-Version'],'0.3')
        self.assertEqual(body['method'],'message/send')
        self.assertEqual(body['params']['message']['parts'][0]['kind'],'text')

    def test_followup_context_and_task(self):
        body,_=send_request(Interface(ENDPOINT,'1.0'),'evidence',context_id='opaque-context',task_id='opaque-task')
        self.assertEqual(body['params']['message']['contextId'],'opaque-context')
        self.assertEqual(body['params']['message']['taskId'],'opaque-task')

    def test_new_context_no_invented_task(self):
        body,_=send_request(Interface(ENDPOINT,'1.0'),'first contact')
        self.assertNotIn('contextId',body['params']['message'])
        self.assertNotIn('taskId',body['params']['message'])

    def test_prompt_limit_no_silent_truncation(self):
        with self.assertRaises(ValueError): send_request(Interface(ENDPOINT,'0.3'),'x'*1801)

    def test_rpc_error_http_200_not_answer(self):
        body={'jsonrpc':'2.0','id':'r1','error':{'code':-32602,'message':'Invalid params'}}
        row=parse_reply(body,version='0.3',request_id='r1',http_status=200)
        self.assertEqual(row['state'],'PROTOCOL_ERROR')
        self.assertFalse(row['protocol_ok'])

    def test_auth_payment_rate_limit(self):
        for code,state in ((402,'PAYMENT_REQUIRED'),(401,'AUTH_REQUIRED'),(429,'RATE_LIMITED')):
            row=parse_reply({},version='1.0',request_id='r1',http_status=code)
            self.assertEqual(row['state'],state)
            self.assertFalse(row['peer_validated'])

    def test_working_not_finished_answer(self):
        body={'jsonrpc':'2.0','id':'r1','result':{'task':{'id':'t1','contextId':'ctx1','status':{'state':'TASK_STATE_WORKING'}}}}
        row=parse_reply(body,version='1.0',request_id='r1',http_status=200)
        self.assertEqual(row['state'],'WORKING')
        self.assertEqual(row['task_id'],'t1')
        self.assertFalse(row['peer_validated'])

    def test_input_required_keeps_question(self):
        body={'jsonrpc':'2.0','id':'r1','result':{'task':{'id':'t1','contextId':'ctx1','status':{'state':'TASK_STATE_INPUT_REQUIRED','message':{'role':'ROLE_AGENT','parts':[{'text':'What is the control group?'}]}}}}}
        row=parse_reply(body,version='1.0',request_id='r1',http_status=200)
        self.assertEqual(row['state'],'INPUT_REQUIRED')
        self.assertIn('control group',row['text'])

    def test_user_history_not_agent_analysis(self):
        body={'jsonrpc':'2.0','id':'r1','result':{'kind':'task','id':'t1','status':{'state':'completed'},'history':[{'role':'user','parts':[{'kind':'text','text':'False analysis from prompt'}]}]}}
        row=parse_reply(body,version='0.3',request_id='r1',http_status=200)
        self.assertEqual(row['text'],'')
        self.assertFalse(row['peer_validated'])

    def test_only_agent_artifact_extracted(self):
        body={'jsonrpc':'2.0','id':'r1','result':{'task':{'id':'t1','contextId':'ctx1','status':{'state':'TASK_STATE_COMPLETED'},'artifacts':[{'parts':[{'text':'Observed conclusion'}]}],'history':[{'role':'ROLE_USER','parts':[{'text':'User prompt'}]}]}}}
        row=parse_reply(body,version='1.0',request_id='r1',http_status=200)
        self.assertEqual(row['text'],'Observed conclusion')
        self.assertFalse(row['peer_validated'])

    def test_rpc_id_mismatch_rejected(self):
        body={'jsonrpc':'2.0','id':'wrong','result':{'message':{'role':'ROLE_AGENT','parts':[{'text':'answer'}]}}}
        self.assertFalse(parse_reply(body,version='1.0',request_id='r1',http_status=200)['protocol_ok'])

    def test_v1_oneof_enforced(self):
        body={'jsonrpc':'2.0','id':'r1','result':{'task':{},'message':{}}}
        self.assertFalse(parse_reply(body,version='1.0',request_id='r1',http_status=200)['protocol_ok'])

class NetworkBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_dns_failure_does_not_count_post(self):
        with patch.object(peer.socket,'getaddrinfo',side_effect=OSError('DNS failed')):
            row=await peer.exchange_peer(Interface(ENDPOINT,'0.3'),'A bounded question.')
        self.assertFalse(row['post_started'])
        self.assertFalse(row['ok'])

    async def test_card_resolution_v1(self):
        request=AsyncMock(return_value={'status':200,'body':V1})
        with patch.object(peer,'public_json_request',request):
            row=await peer.resolve_peer({'url':CARD_URL},{'contact_mode':'agent_card'})
        self.assertTrue(row['ok'])
        self.assertEqual(row['interface']['version'],'1.0')
        self.assertIsNone(row['interface']['tenant'])

    async def test_resolution_failure_never_calls_rpc(self):
        request=AsyncMock(return_value={'status':404,'body':{}})
        with patch.object(peer,'public_json_request',request):
            row=await peer.resolve_peer({'url':CARD_URL},{'contact_mode':'agent_card'})
        self.assertFalse(row['ok'])
        self.assertFalse(row['post_started'])
        self.assertEqual(request.call_args.args[0],'GET')
        self.assertEqual(request.call_count,1)

    async def _exchange(self,state,kind='message',context='ctx1'):
        captured=[]
        async def request(method,url,budget,payload,headers):
            captured.append(payload)
            message={'kind':'message','role':'agent','contextId':context,'parts':[{'kind':'text','text':'The observed tradeoff requires a quality constraint before deployment.'}]}
            result=message if kind=='message' else {'kind':'task','id':'task1','contextId':context,'status':{'state':kind},'artifacts':[]}
            return {'status':200,'body':{'jsonrpc':'2.0','id':payload['id'],'result':result},'request_started':True,'response_received':True}
        with patch.object(peer,'public_json_request',request):
            row=await peer.exchange_peer(Interface(ENDPOINT,'0.3'),'Updated evidence.',state)
        return row,captured

    async def test_completed_task_not_reopened(self):
        prior={'endpoint':ENDPOINT,'protocol_version':'0.3','context_id':'ctx1','task_id':'task1','state':'COMPLETED'}
        row,sent=await self._exchange(prior)
        self.assertEqual(sent[0]['params']['message']['contextId'],'ctx1')
        self.assertNotIn('taskId',sent[0]['params']['message'])
        self.assertTrue(row['quality_ok'])

    async def test_input_required_continues_task(self):
        prior={'endpoint':ENDPOINT,'protocol_version':'0.3','context_id':'ctx1','task_id':'task1','state':'INPUT_REQUIRED'}
        _,sent=await self._exchange(prior)
        self.assertEqual(sent[0]['params']['message']['taskId'],'task1')

    async def test_working_polled_not_duplicate(self):
        prior={'endpoint':ENDPOINT,'protocol_version':'0.3','context_id':'ctx1','task_id':'task1','state':'WORKING'}
        row,sent=await self._exchange(prior,'working')
        self.assertEqual(sent[0]['method'],'tasks/get')
        self.assertFalse(row['quality_ok'])

    async def test_changed_context_rejected(self):
        prior={'endpoint':ENDPOINT,'protocol_version':'0.3','context_id':'ctx1','state':'MESSAGE'}
        row,_=await self._exchange(prior,context='unexpected')
        self.assertEqual(row['peer_state'],'CONTEXT_MISMATCH')
        self.assertFalse(row['quality_ok'])

    async def test_payment_no_retry(self):
        request=AsyncMock(return_value={'status':402,'body':{},'request_started':True,'response_received':True})
        with patch.object(peer,'public_json_request',request):
            row=await peer.exchange_peer(Interface(ENDPOINT,'0.3'),'Bounded interview.')
        self.assertEqual(row['peer_state'],'PAYMENT_REQUIRED')
        self.assertFalse(row['quality_ok'])
        self.assertEqual(request.call_count,1)

    async def test_request_budget(self):
        with patch.object(peer,'_request_sync') as request:
            row=await peer.exchange_peer(Interface(ENDPOINT,'0.3'),'Bounded question.',budget=peer.RequestBudget(limit=0))
        request.assert_not_called()
        self.assertFalse(row['post_started'])
        self.assertEqual(row['quality_reason'],'REQUEST_BUDGET_EXHAUSTED')

    def test_private_dns_before_connection(self):
        with patch.object(peer.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch.object(peer.socket,'create_connection') as connection:
            row=peer._request_sync('GET',CARD_URL,None,{},1)
        connection.assert_not_called()
        self.assertEqual(row['error'],'NONPUBLIC_DNS_BLOCKED')

    def test_new_peer_priority(self):
        self.assertGreater(peer.peer_priority({'max_score':90},{}),peer.peer_priority({'max_score':20},{'status':'PARKED'}))

    def test_only_allowlisted_data_envelope(self):
        self.assertEqual(peer._parts([{'data':{'history':[{'text':'fake answer'}]}}]),[])
        self.assertEqual(peer._parts([{'data':{'output':'domain answer','model':'declared'}}]),['domain answer'])

class IntegratedRoutingTests(unittest.TestCase):
    def function(self,name):
        tree=ast.parse(Path('cloud_mcp.py').read_text())
        return ast.unparse(next(n for n in tree.body if getattr(n,'name',None)==name))

    def test_negotiated_private_context(self):
        source=self.function('_seti_interview_one_candidate')
        for needle in ('_peer_interface','_peer_context','message_post_started_count','peer_a2a.RequestBudget(limit=9)',"quality.get('accepted')"):
            self.assertIn(needle,source)

    def test_old_transport_path_preserved(self):
        source=self.function('_ask_a2a_transport')
        self.assertIn('peer_a2a.exchange_peer',source)
        self.assertIn('registry_chat',source)

    def test_admitted_interface_retained(self):
        self.assertIn('_peer_interface',self.function('_seti_admitted_agent_details'))

    def test_send_not_inferred_from_attempt(self):
        self.assertIn("bool(interview_result.get('message_post_started_count'))",self.function('_seti_cycle_if_due'))

    def test_slots_count_real_a2a_attempts_not_preflight_failures(self):
        source=self.function('_seti_interview_one_candidate')
        self.assertIn('conversation_slots',source)
        self.assertIn('conversation_slot_used',source)
        self.assertIn('AUTH_BLOCKED',source)
        self.assertIn('retry_after_seconds',source)
        self.assertNotIn("if len(results) >= max(1, min(int(max_interviews or 1), 3))",source)

if __name__=='__main__':
    unittest.main()


class PeerQualityIntegrationTests(unittest.TestCase):
    def test_cloud_discards_restored_active_exhausted_seed(self):
        source=IntegratedRoutingTests().function('_anthropic_convergence_queries')
        self.assertGreaterEqual(source.count('exhausted_seed_blocked'),3)
        self.assertIn("AUTOPILOT_STATE['active_thesis'] = None",source)

    def test_cloud_refilters_ranked_after_thesis_exhaustion(self):
        source=IntegratedRoutingTests().function('_anthropic_convergence_queries')
        self.assertGreaterEqual(source.count('exhausted_seed_blocked'),2)

    def test_cloud_reopens_exhausted_seed_only_after_evidence_progress(self):
        source=IntegratedRoutingTests().function('_anthropic_convergence_queries')
        self.assertIn('current_rank=score',source)
        self.assertIn('current_missing=missing',source)
        self.assertIn('current_rank=active_rank',source)
        self.assertIn('current_rank=item[0]',source)

    def test_cloud_uses_stable_problem_identity_for_planner_queries(self):
        convergence=IntegratedRoutingTests().function('_convergence_search_queries')
        breakout=IntegratedRoutingTests().function('_stagnation_breakout_queries')
        anthropic=IntegratedRoutingTests().function('_anthropic_convergence_queries')
        self.assertIn('problem_job_tail(key)',convergence)
        self.assertIn('problem_job_tail(problem_key)',breakout)
        self.assertIn('problem_job_tail(key)',anthropic)
        self.assertIn('problem_customer_segment(key)',anthropic)
        self.assertIn('key = canonical_problem_key(family, problem_id)',anthropic)

    def test_query_builder_v2_is_wired_before_broad_discovery(self):
        entropy=IntegratedRoutingTests().function('_entropy_search_strategy')
        scouts=IntegratedRoutingTests().function('evidence_scouts')
        breakout=IntegratedRoutingTests().function('_stagnation_breakout_queries')
        self.assertIn('QUERY_BUILDER_V2_ENABLED',entropy)
        self.assertIn('build_discovery_query',entropy)
        self.assertIn('build_scout_queries',scouts)
        self.assertIn('build_breakout_queries',breakout)

    def test_explore_exploit_route_structured_sources_before_bing(self):
        source=IntegratedRoutingTests().function('routed_public_search')
        self.assertIn("query_class in {'explore', 'exploit'}",source)
        self.assertIn('free_web_search(seed, 2)',source)
        self.assertIn('_hn_query_search(seed, 3)',source)
        self.assertIn('_github_issue_query_search(seed, 3)',source)
        self.assertIn('_stackexchange_query_search(seed, 3, meta)',source)

    def test_query_builder_v2_does_not_change_thesis_generation(self):
        source=IntegratedRoutingTests().function('_anthropic_convergence_queries')
        self.assertNotIn('build_discovery_query',source)
        self.assertNotIn('build_scout_queries',source)
        self.assertNotIn('build_breakout_queries',source)

    def test_v0999_integrity_guards_are_wired(self):
        quality=IntegratedRoutingTests().function('_commercial_evidence_quality')
        routed=IntegratedRoutingTests().function('routed_public_search')
        stack=IntegratedRoutingTests().function('_stackexchange_query_search')
        self.assertIn('SELF_CONTAMINATION_GUARD_ENABLED',quality)
        self.assertIn('ATTRIBUTION_FAMILY_GUARD_ENABLED',quality)
        self.assertIn('STRONG_PAIN_GUARD_ENABLED',quality)
        self.assertIn('self_contamination_rejected',quality)
        self.assertIn('_stackexchange_query_search(seed, 3, meta)',routed)
        self.assertIn("'tagged'",stack)
        self.assertIn('EXPLORE_STRICT_ENABLED',stack)

    def test_problem_snapshot_canonicalizes_input_key(self):
        source=IntegratedRoutingTests().function('_problem_snapshot')
        import time
        from evidence_integrity import canonical_problem_key, gate_eligible_problem_key
        namespace={
            "AUTOPILOT_STATE":{
                "commercial_evidence_memory":[{
                    "family":"manual_data_entry",
                    "problem_key":"manual_data_entry:manual_data_entry",
                    "gate_eligible":True,
                    "domain":"a.com",
                    "last_seen_epoch":time.time(),
                    "strong_markers":[],
                    "signal_types":["PAIN"],
                }],
            },
            "canonical_problem_key":canonical_problem_key,
            "gate_eligible_problem_key":gate_eligible_problem_key,
            "time":time,
        }
        exec(source,namespace)
        snapshot=namespace["_problem_snapshot"]("manual_data_entry:buyers:manual_data_entry")
        self.assertEqual(snapshot["domains"],{"a.com"})
        self.assertEqual(snapshot["problem_key"],"manual_data_entry:manual_data_entry")

    def test_cloud_requires_multiturn_collaboration_before_admission(self):
        source=IntegratedRoutingTests().function('_seti_interview_one_candidate')
        self.assertIn('collaborative_rounds >= 3',source)
        self.assertIn("peer_quality.get('falsifiable_test')",source)
        self.assertIn("peer_quality.get('peer_class') == 'COLLABORATIVE'",source)
