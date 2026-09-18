"""Offline tests for resumable background response transport."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.background_review import BackgroundResponses, ResponseTransportError
from src.astra_review import usage_estimate


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.post_responses = []
        self.get_responses = []
        self.closed = False
    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.post_responses.pop(0)
    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return self.get_responses.pop(0)
    def close(self):
        self.closed = True


class BackgroundTransportTests(unittest.TestCase):
    def test_create_forces_background_and_store_false(self):
        session = FakeSession()
        session.post_responses = [FakeResponse(payload={'id':'resp_1','status':'queued'})]
        client = BackgroundResponses('fake', session=session)
        result = client.create({'model':'gpt-6-astra','input':'x','store':True})
        self.assertEqual(result['id'], 'resp_1')
        body = session.posts[0][1]['json']
        self.assertTrue(body['background'])
        self.assertFalse(body['store'])

    def test_retrieve_same_id(self):
        session = FakeSession()
        session.get_responses = [FakeResponse(payload={'id':'resp_1','status':'completed'})]
        client = BackgroundResponses('fake', session=session)
        self.assertEqual(client.retrieve('resp_1')['status'], 'completed')

    def test_retrieve_wrong_id_rejected(self):
        session = FakeSession()
        session.get_responses = [FakeResponse(payload={'id':'resp_other','status':'completed'})]
        client = BackgroundResponses('fake', session=session)
        with self.assertRaises(ResponseTransportError):
            client.retrieve('resp_1')

    def test_poll_reuses_response_id_no_create(self):
        session = FakeSession()
        session.get_responses = [
            FakeResponse(payload={'id':'resp_1','status':'in_progress'}),
            FakeResponse(payload={'id':'resp_1','status':'completed'}),
        ]
        client = BackgroundResponses('fake', session=session)
        result = client.poll('resp_1', max_wait_seconds=30, interval_seconds=1, sleep=lambda _: None)
        self.assertTrue(result.terminal)
        self.assertEqual(result.response['status'], 'completed')
        self.assertEqual(len(session.posts), 0)
        self.assertEqual(len(session.gets), 2)

    def test_cancel_uses_existing_id(self):
        session = FakeSession()
        session.post_responses = [FakeResponse(payload={'id':'resp_1','status':'cancelled'})]
        client = BackgroundResponses('fake', session=session)
        self.assertEqual(client.cancel('resp_1')['status'], 'cancelled')
        self.assertTrue(session.posts[0][0].endswith('/responses/resp_1/cancel'))

    def test_http_error_does_not_expose_body(self):
        session = FakeSession()
        session.get_responses = [FakeResponse(status_code=500, payload={'secret':'do not print'}, headers={'x-request-id':'req_1'})]
        client = BackgroundResponses('fake', session=session)
        with self.assertRaisesRegex(ResponseTransportError, 'req_1') as cm:
            client.retrieve('resp_1')
        self.assertNotIn('secret', str(cm.exception))


class FlexPricingTests(unittest.TestCase):
    def test_short_context_flex_rates(self):
        response = {
            'id':'resp_1','model':'gpt-6-astra','service_tier':'flex',
            'usage': {
                'input_tokens': 6000,
                'input_tokens_details': {'cached_tokens':0},
                'output_tokens': 2000,
                'output_tokens_details': {'reasoning_tokens':500},
            }
        }
        result = usage_estimate(response)
        self.assertEqual(str(result['cost_low_usd']), '0.08')
        self.assertEqual(str(result['cost_high_usd']), '0.0875')
        self.assertEqual(result['rates']['service_tier'], 'flex')


if __name__ == '__main__':
    unittest.main(verbosity=2)
