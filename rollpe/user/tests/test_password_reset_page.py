from datetime import timedelta
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from user.models import User
from utils.functions import generate_send_email


class PasswordResetPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='reset@example.com', name='Reset',
                                             password='old-password', identifyCode='Reset1')
        self.url = reverse('password_reset_page', kwargs={'identify_code': 'Reset1'})
        self.token = default_token_generator.make_token(self.user)
        self.client = Client(enforce_csrf_checks=True)

    def submit(self, **changes):
        self.client.get(self.url)
        data = {'token': self.token, 'newPassword': 'New-password1!',
                'passwordConfirmation': 'New-password1!',
                'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value, **changes}
        return self.client.post(self.url, data)

    def test_get_is_scanner_safe_and_has_security_headers_and_no_token(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", response['Content-Security-Policy'])
        self.assertIn("form-action 'self'", response['Content-Security-Policy'])
        self.assertNotContains(response, self.token)
        self.assertContains(response, 'window.location.hash')
        self.assertContains(response, 'history.replaceState')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.user.refresh_from_db()
        self.assertTrue(default_token_generator.check_token(self.user, self.token))
        self.assertTrue(self.user.check_password('old-password'))

    def test_form_requires_csrf(self):
        response = self.client.post(self.url, {'token': self.token, 'newPassword': 'New-password1!',
                                              'passwordConfirmation': 'New-password1!'})
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-password'))

    def test_success_is_single_use_and_does_not_expose_token_or_password(self):
        refresh = RefreshToken.for_user(self.user)
        response = self.submit()
        self.assertContains(response, '비밀번호를 변경했어요')
        self.assertNotContains(response, self.token)
        self.assertNotContains(response, 'New-password1!')
        self.assertContains(response, 'rollpe://sign-in')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('New-password1!'))
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh['jti']).exists())
        self.assertEqual(self.submit().status_code, 400)

    def test_confirmation_and_missing_invalid_cross_user_token_are_rejected(self):
        other = User.objects.create_user(email='other@example.com', name='Other')
        for changes in ({'passwordConfirmation': 'different'}, {'newPassword': 'weak', 'passwordConfirmation': 'weak'}, {'token': ''},
                        {'token': 'invalid'}, {'token': default_token_generator.make_token(other)}):
            response = self.submit(**changes)
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, self.token, status_code=400)
            self.user.refresh_from_db()
            self.assertTrue(self.user.check_password('old-password'))

    @override_settings(PASSWORD_RESET_TIMEOUT=1800)
    def test_expired_social_inactive_and_unknown_user_rejected(self):
        now = default_token_generator._now()
        with patch.object(default_token_generator, '_now', return_value=now - timedelta(seconds=1801)):
            expired = default_token_generator.make_token(self.user)
        response = self.submit(token=expired)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, '새 인증 메일을 요청해주세요.', status_code=400)
        self.assertContains(response, 'rollpe://forgot-password', status_code=400)
        self.assertNotContains(response, expired, status_code=400)
        for provider, active in [('apple', True), (None, False)]:
            self.user.provider, self.user.is_active = provider, active
            self.user.save()
            self.assertEqual(self.submit(token=default_token_generator.make_token(self.user)).status_code, 400)
        self.url = reverse('password_reset_page', kwargs={'identify_code': 'Absent'})
        self.assertEqual(self.submit().status_code, 400)

    @override_settings(BASE_DOMAIN='unused.invalid', API_DOMAIN='api.example.com')
    def test_email_targets_api_form_with_fragment_only(self):
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.urls = []

            def handle_starttag(self, tag, attrs):
                if tag == 'a':
                    self.urls.append(dict(attrs)['href'])
        generate_send_email(self.user.email, 'password')
        parser = Links()
        parser.feed(mail.outbox[0].alternatives[0][0])
        url = urlsplit(parser.urls[0])
        self.assertEqual(url.scheme, 'https')
        self.assertEqual(url.netloc, 'api.example.com')
        self.assertEqual(url.path, self.url)
        self.assertEqual(url.query, '')
        self.assertTrue(url.fragment.startswith('token='))

    def test_original_password_policy_accepts_single_case_letters(self):
        response = self.submit(newPassword='password1!', passwordConfirmation='password1!')
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('password1!'))

    def test_new_browser_form_rejects_password_over_128_characters(self):
        password = 'Password1!' + 'a' * 119
        self.assertEqual(len(password), 129)
        response = self.submit(newPassword=password, passwordConfirmation=password)
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-password'))
        self.assertTrue(default_token_generator.check_token(self.user, self.token))
        self.assertContains(response, 'maxlength="128"', status_code=400)
