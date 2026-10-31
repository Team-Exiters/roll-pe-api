import re
from unittest.mock import patch

from django.test import SimpleTestCase

from utils.functions import PRIVACY


class PrivacyPolicyPageTests(SimpleTestCase):
    def test_public_html_matches_the_existing_app_policy_without_database_or_network(self):
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
            response = self.client.get('/privacy-policy')
            api = self.client.get('/api/user/docs?docs=privacy')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/html; charset=utf-8')
        self.assertContains(response, '<html lang="ko">')
        self.assertContains(response, '<h1>롤페 개인정보처리방침</h1>')
        self.assertContains(response, PRIVACY)
        self.assertEqual(api.json()['data'], PRIVACY)
        self.assertFalse(response.cookies)

    def test_both_url_forms_accept_head_and_ignore_untrusted_input(self):
        for path in ['/privacy-policy', '/privacy-policy/']:
            response = self.client.get(path, {'content': '<script>untrusted.example</script>'},
                                       HTTP_AUTHORIZATION='Bearer invalid')
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'untrusted.example')
            self.assertNotContains(response, '<script')
            head = self.client.head(path)
            self.assertEqual(head.status_code, 200)
            self.assertEqual(head.content, b'')
            self.assertNotIn('Location', response)

    def test_page_is_read_only_and_has_no_external_resource_dependencies(self):
        for method in ['post', 'put', 'patch', 'delete']:
            self.assertEqual(getattr(self.client, method)('/privacy-policy').status_code, 405)
        response = self.client.get('/privacy-policy')
        policy = response['Content-Security-Policy']
        self.assertIn("default-src 'none'", policy)
        nonce = re.search(r"style-src 'nonce-([^']+)'", policy).group(1)
        self.assertContains(response, f'<style nonce="{nonce}">', count=1)
        for element in ['<script', '<img', '<iframe', '<form', '@font-face', '<link']:
            self.assertNotContains(response, element)
