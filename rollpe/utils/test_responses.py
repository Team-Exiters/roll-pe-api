import json

from django.middleware.common import CommonMiddleware
from django.test import RequestFactory, SimpleTestCase

from utils.response import Response


class NoContentResponseTests(SimpleTestCase):
    def test_no_content_has_no_json_body_or_json_content_type(self):
        response = Response(status=204, data={'ignored': True}, msg='ignored')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        self.assertNotIn('Content-Type', response)

    def test_production_common_middleware_cannot_advertise_a_nonzero_body(self):
        response = Response(status=204)
        response = CommonMiddleware(lambda request: response).process_response(
            RequestFactory().delete('/api/heart'), response,
        )
        self.assertEqual(response.content, b'')
        self.assertIn(response.get('Content-Length'), (None, '0'))

    def test_other_statuses_keep_the_existing_json_envelope(self):
        for status in (200, 201, 400, 401, 403, 404, 483):
            with self.subTest(status=status):
                response = Response(status=status, msg='응답 검증', data={'value': 1})
                payload = json.loads(response.content)
                self.assertEqual(response.status_code, status)
                self.assertEqual(payload['status_code'], status)
                self.assertEqual(payload['message'], '응답 검증')
                self.assertEqual(payload['data'], {'value': 1})
                self.assertEqual(set(payload), {'status_code', 'message', 'code', 'link', 'data'})
