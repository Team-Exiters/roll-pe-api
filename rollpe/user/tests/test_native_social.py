import json
from unittest.mock import Mock, patch

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import TestCase, override_settings
from django.db import IntegrityError
from django.utils import timezone

from user.models import SocialIdentity, User


class NativeSocialLoginTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_key = cls.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    def setUp(self):
        for target, value in [
            ('user.apis_social.return_env_value', 'native-ios.apps.googleusercontent.com'),
            ('google.oauth2.id_token._fetch_certs', {'test-key': self.public_key}),
        ]:
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def token(self, **claims):
        now = int(timezone.now().timestamp())
        return jwt.encode({
            'iss': 'https://accounts.google.com', 'aud': 'test-web.apps.googleusercontent.com',
            'iat': now, 'exp': now + 60, 'sub': 'same-google-account',
            'email': 'native@example.com', 'email_verified': True, 'name': 'Native User', **claims,
        }, self.key, algorithm='RS256', headers={'kid': 'test-key'})

    def login(self, provider='google', access=None):
        return self.client.post(f'/api/user/social/login/{provider}',
                                json.dumps({'accessToken': access}), content_type='application/json')

    def test_original_ios_and_android_web_audiences_reach_the_same_account(self):
        user_ids = []
        for audience in ('native-ios.apps.googleusercontent.com', 'test-web.apps.googleusercontent.com'):
            response = self.login(access=self.token(aud=audience))
            self.assertEqual(response.status_code, 200)
            data = response.json()['data']
            self.assertEqual(data['user']['provider'], 'google')
            self.assertTrue(data['access'])
            self.assertTrue(data['refresh'])
            user_ids.append(data['user']['id'])
        self.assertEqual(user_ids[0], user_ids[1])
        self.assertEqual(SocialIdentity.objects.count(), 1)
        self.assertFalse(User.objects.get().has_usable_password())

    def test_signed_google_subject_keeps_the_account_when_email_changes(self):
        first = self.login(access=self.token()).json()['data']['user']['id']
        second = self.login(access=self.token(email='changed@example.com')).json()['data']['user']['id']
        self.assertEqual(first, second)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(User.objects.get().email, 'native@example.com')

    def test_invalid_google_audience_issuer_expiry_signature_or_subject_never_creates_an_account(self):
        for claims in [
            {'aud': 'attacker.apps.googleusercontent.com'}, {'iss': 'https://attacker.example'},
            {'exp': 0}, {'iat': int(timezone.now().timestamp()) + 3600},
            {'sub': ''}, {'sub': 'x' * 256}, {'sub': '한글'},
        ]:
            with self.subTest(claims=claims):
                self.assertEqual(self.login(access=self.token(**claims)).status_code, 400)
        invalid_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode({'aud': 'test-web.apps.googleusercontent.com'}, invalid_key,
                            algorithm='RS256', headers={'kid': 'test-key'})
        self.assertEqual(self.login(access=forged).status_code, 400)
        self.assertFalse(User.objects.exists())
        self.assertFalse(SocialIdentity.objects.exists())

    def test_missing_or_unverified_google_email_cannot_create_or_link_an_account(self):
        for claims in [{'email': None}, {'email': 'bad-email'}, {'email_verified': False}, {'email_verified': 'false'}]:
            self.assertEqual(self.login(access=self.token(**claims)).status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_simultaneous_identity_creation_rolls_back_the_partial_account_and_can_be_retried(self):
        with patch('user.social_browser.SocialIdentity.objects.create', side_effect=IntegrityError('duplicate identity')):
            self.assertEqual(self.login(access=self.token()).status_code, 400)
        self.assertFalse(User.objects.exists())
        self.assertFalse(SocialIdentity.objects.exists())
        self.assertEqual(self.login(access=self.token()).status_code, 200)
        self.assertEqual(User.objects.count(), 1)

    def test_other_provider_and_inactive_accounts_are_not_linked(self):
        for provider, active in [(None, True), ('apple', True), ('google', False)]:
            with self.subTest(provider=provider, active=active):
                user = User.objects.create_user(email='native@example.com', name='Original',
                                                provider=provider, is_active=active)
                self.assertEqual(self.login(access=self.token()).status_code, 400)
                self.assertFalse(SocialIdentity.objects.exists())
                user.delete()

    @override_settings(GOOGLE_AUTH_CLIENT_ID='')
    def test_missing_all_google_audiences_returns_unavailable(self):
        with patch('user.apis_social.return_env_value', return_value=''):
            self.assertEqual(self.login(access=self.token()).status_code, 503)
        self.assertFalse(User.objects.exists())

    def test_kakao_native_token_is_validated_and_binds_the_same_stable_identity(self):
        response = Mock(status_code=200)
        account = {'id': 1234, 'kakao_account': {
            'email': 'kakao@example.com', 'is_email_valid': True, 'is_email_verified': True,
            'profile': {'nickname': 'Kakao'},
        }}
        response.json.return_value = account
        token_info = Mock(status_code=200)
        token_info.json.return_value = {'app_id': 5678, 'id': 1234, 'expires_in': 3600}
        with patch('user.social_browser.requests.get', side_effect=lambda url, **kwargs:
                   token_info if url.endswith('/access_token_info') else response) as get:
            first = self.login('kakao', 'native-kakao-token')
            self.assertEqual(first.status_code, 200)
            self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer native-kakao-token')
            self.assertEqual(get.call_args.kwargs['timeout'], 10)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            account['kakao_account']['email'] = 'changed@example.com'
            second = self.login('kakao', 'next-kakao-token')
            self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['data']['user']['id'], second.json()['data']['user']['id'])
        self.assertEqual(SocialIdentity.objects.get().subject, '1234')

    def test_kakao_rejects_foreign_apps_expired_tokens_and_mismatched_users(self):
        for overrides in [{'app_id': 9999}, {'app_id': True}, {'expires_in': 0}, {'id': True}]:
            info = Mock(status_code=200)
            info.json.return_value = {'app_id': 5678, 'id': 1234, 'expires_in': 3600, **overrides}
            with patch('user.apis_social.requests.get', return_value=info) as get:
                self.assertEqual(self.login('kakao', 'native-token').status_code, 400)
                self.assertEqual(get.call_count, 1)
        info = Mock(status_code=200)
        info.json.return_value = {'app_id': 5678, 'id': 1234, 'expires_in': 3600}
        with patch('user.apis_social.requests.get', return_value=info), \
             patch('user.apis_social.kakao_profile', return_value={'subject': '9999'}):
            self.assertEqual(self.login('kakao', 'native-token').status_code, 400)
        self.assertFalse(User.objects.exists())

    @override_settings(KAKAO_AUTH_APP_ID='')
    def test_kakao_requires_the_configured_app_before_any_network_request(self):
        with patch('user.apis_social.requests.get') as get:
            self.assertEqual(self.login('kakao', 'native-token').status_code, 503)
            get.assert_not_called()

    def test_bad_or_unverified_kakao_profile_and_network_failure_return_no_session(self):
        response = Mock(status_code=200)
        token_info = Mock(status_code=200)
        token_info.json.return_value = {'app_id': 5678, 'id': 1234, 'expires_in': 3600}
        with patch('user.social_browser.requests.get', side_effect=lambda url, **kwargs:
                   token_info if url.endswith('/access_token_info') else response) as get:
            for profile in [{'id': True}, {'id': 0}, {'id': 1234, 'kakao_account': {}}, None]:
                response.json.return_value = profile
                self.assertEqual(self.login('kakao', 'native-token').status_code, 400)
            get.side_effect = requests.Timeout('unavailable')
            self.assertEqual(self.login('kakao', 'native-token').status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_missing_native_credentials_and_unsupported_providers_are_rejected(self):
        self.assertEqual(self.login().status_code, 400)
        self.assertEqual(self.login('kakao').status_code, 400)
        self.assertEqual(self.login('unsupported', 'token').status_code, 404)
