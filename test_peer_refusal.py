"""Synthetic regression from the observed refusal; never contacts the peer."""
import json
import unittest
from unittest.mock import patch
import a2a_peer as peer

ENDPOINT='https://peer.example.net/a2a'

class PeerRefusalTests(unittest.IsolatedAsyncioTestCase):
    def test_plain_explicit_refusal(self):
        self.assertEqual(peer.explicit_peer_refusal('PAYMENT_REQUIRED. No paid request authorized.'),'PAYMENT_REQUIRED')

    def test_observed_json_text_envelope(self):
        text=json.dumps({'output':'PAYMENT_REQUIRED. I cannot proceed with this request.','model':'declared'})
        self.assertEqual(peer.explicit_peer_refusal(text),'PAYMENT_REQUIRED')

    def test_research_discussion_not_refusal(self):
        self.assertIsNone(peer.explicit_peer_refusal('Use PAYMENT_REQUIRED only when a real payment is required.'))
        self.assertIsNone(peer.explicit_peer_refusal('No payment required for this analysis.'))

    async def test_http_200_refusal_not_quality_success(self):
        async def request(method,url,budget,payload,headers):
            result={'kind':'message','role':'agent','contextId':'ctx1','parts':[{'kind':'text','text':json.dumps({'output':'PAYMENT_REQUIRED. I cannot proceed with this request.'})}]}
            return {'status':200,'body':{'jsonrpc':'2.0','id':payload['id'],'result':result},'request_started':True,'response_received':True}
        with patch.object(peer,'public_json_request',request):
            row=await peer.exchange_peer(peer.Interface(ENDPOINT,'0.3'),'A bounded question.')
        self.assertTrue(row['protocol_ok'])
        self.assertFalse(row['quality_ok'])
        self.assertEqual(row['peer_state'],'PAYMENT_REQUIRED')
        self.assertEqual(row['peer_context']['state'],'PAYMENT_REQUIRED')

    async def test_refused_peer_not_recontacted(self):
        prior={'endpoint':ENDPOINT,'protocol_version':'0.3','context_id':'ctx1','state':'PAYMENT_REQUIRED'}
        with patch.object(peer,'public_json_request') as request:
            row=await peer.exchange_peer(peer.Interface(ENDPOINT,'0.3'),'Followup.',prior)
        request.assert_not_called()
        self.assertFalse(row['post_started'])
        self.assertFalse(row['quality_ok'])

if __name__=='__main__':
    unittest.main()
