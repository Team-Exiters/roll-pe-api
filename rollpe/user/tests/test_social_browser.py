import json
from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import Client, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from user.models import SocialAuthFlow, SocialIdentity, User
from user.social_browser import SocialAuthenticationError, digest, google_profile, pkce_challenge


def http_response(data, status=200):
    response = Mock(status_code=status)
    response.json.return_value = data
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError('provider error')
    return response


class SocialBrowserTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.verifier = 'v' * 64
        self.client_state = 's' * 43
        self.patches = [
            patch('user.social_browser.requests.post'),
            patch('user.social_browser.requests.get'),
            patch('user.social_browser.id_token.verify_oauth2_token'),
        ]
        self.post, self.get, self.google = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.post.return_value = http_response({'id_token': 'google-id', 'access_token': 'provider-access'})
        self.kakao = {'id': 12345, 'kakao_account': {
            'email': 'kakao@example.com', 'is_email_valid': True, 'is_email_verified': True,
            'profile': {'nickname': '카카오 사용자'},
        }}
        self.get.return_value = http_response(self.kakao)

    def url(self, action, provider):
        return reverse(f'social_{action}', kwargs={'provider': provider})

    def params(self, provider, **overrides):
        return {
            'return_url': f'http://localhost:8081/auth/{provider}',
            'state': self.client_state, 'code_challenge': pkce_challenge(self.verifier), **overrides,
        }

    def start(self, provider, **overrides):
        response = self.client.get(self.url('start', provider), self.params(provider, **overrides))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Cache-Control'], 'no-store')
        query = parse_qs(urlsplit(response['Location']).query)
        flow = SocialAuthFlow.objects.get(state_hash=digest(query['state'][0]))
        self.google.return_value = {
            'sub': 'google-sub', 'email': 'google@example.com', 'email_verified': True,
            'name': 'Google 사용자', 'nonce': flow.nonce,
        }
        return query, flow

    def callback(self, provider, state, **params):
        return self.client.get(self.url('callback', provider), {'state': state, **params})

    def complete(self, provider):
        query, flow = self.start(provider)
        response = self.callback(provider, query['state'][0], code='provider-code')
        self.assertEqual(response.status_code, 302)
        result = parse_qs(urlsplit(response['Location']).query)
        self.assertIn('code', result)
        return result['code'][0], flow, response

    def exchange(self, provider, code, verifier=None):
        return self.client.post(self.url('exchange', provider), json.dumps({
            'code': code, 'code_verifier': verifier or self.verifier,
        }), content_type='application/json')

    def test_registered_callback_paths_and_apple_routes_are_distinct(self):
        for provider in ('google', 'kakao'):
            self.assertEqual(self.url('callback', provider), f'/api/user/social/login/{provider}/callback')
        for action in ('start', 'callback', 'exchange'):
            self.assertEqual(resolve(f'/api/user/social/login/apple/{action}').url_name, f'apple_{action}')
            self.assertEqual(self.client.get(self.url(action, 'unknown')).status_code, 404 if action != 'exchange' else 405)

    def test_start_has_independent_server_state_and_two_separate_s256_proofs(self):
        for provider in ('google', 'kakao'):
            with self.subTest(provider=provider):
                query, flow = self.start(provider)
                self.assertNotEqual(query['state'][0], self.client_state)
                self.assertEqual(flow.code_challenge, pkce_challenge(self.verifier))
                self.assertEqual(query['code_challenge'], [pkce_challenge(flow.provider_verifier)])
                self.assertEqual(query['code_challenge_method'], ['S256'])
                self.assertNotEqual(query['code_challenge'][0], flow.code_challenge)
                self.assertNotIn(flow.provider_verifier, str(query))
                self.assertNotIn('client_secret', query)
                self.assertEqual(query['redirect_uri'], [f'https://rollpe.mooo.com/api/user/social/login/{provider}/callback'])
                if provider == 'google':
                    self.assertEqual(query['nonce'], [flow.nonce])
                    self.assertEqual(query['scope'], ['openid email profile'])
                second, _ = self.start(provider)
                self.assertNotEqual(query['state'], second['state'])

    def test_rejects_open_redirects_and_ambiguous_or_malformed_start_requests(self):
        for provider in ('google', 'kakao'):
            for invalid in (
                {'return_url': 'https://evil.example/auth/google'},
                {'return_url': self.params(provider)['return_url'] + '?next=evil'},
                {'return_url': self.params(provider)['return_url'] + '#fragment'},
                {'state': 'short'}, {'state': [self.client_state, 'other']},
                {'code_challenge': 'short'},
                {'return_url': [self.params(provider)['return_url']] * 2},
            ):
                response = self.client.get(self.url('start', provider), self.params(provider, **invalid))
                self.assertEqual(response.status_code, 400)
        self.assertEqual(SocialAuthFlow.objects.count(), 0)
        self.post.assert_not_called()

    def test_missing_configuration_fails_closed(self):
        for provider in ('google', 'kakao'):
            required = ('CLIENT_ID', 'CLIENT_SECRET', 'REDIRECT_URI') if provider == 'google' else ('CLIENT_ID', 'REDIRECT_URI')
            for name in required:
                with override_settings(**{f'{provider.upper()}_AUTH_{name}': ''}):
                    response = self.client.get(self.url('start', provider), self.params(provider))
                    self.assertEqual(response.status_code, 503)
        self.assertEqual(SocialAuthFlow.objects.count(), 0)

    @override_settings(KAKAO_AUTH_CLIENT_SECRET='')
    def test_kakao_with_console_secret_feature_off_does_not_send_an_empty_secret(self):
        code, _, _ = self.complete('kakao')
        self.assertNotIn('client_secret', self.post.call_args.kwargs['data'])
        self.assertEqual(self.exchange('kakao', code).status_code, 200)

    def test_configured_kakao_secret_is_sent_only_to_the_token_endpoint(self):
        query, _ = self.start('kakao')
        self.assertNotIn('client_secret', query)
        self.callback('kakao', query['state'][0], code='code')
        self.assertEqual(self.post.call_args.kwargs['data']['client_secret'], 'test-kakao-secret')

    @override_settings(KAKAO_AUTH_CLIENT_SECRET='')
    def test_kakao_provider_still_rejects_a_missing_secret_when_console_requires_it(self):
        query, _ = self.start('kakao')
        self.post.return_value = http_response({'error': 'invalid_client'}, status=401)
        response = self.callback('kakao', query['state'][0], code='code')
        self.assertIn('error=authentication_failed', response['Location'])
        self.assertFalse(User.objects.exists())

    def test_complete_flow_returns_original_session_format_without_provider_tokens(self):
        for provider in ('google', 'kakao'):
            with self.subTest(provider=provider):
                code, flow, callback = self.complete(provider)
                params = parse_qs(urlsplit(callback['Location']).query)
                self.assertEqual(params['state'], [self.client_state])
                self.assertEqual(set(params), {'state', 'code'})
                self.assertNotIn('provider-code', callback['Location'])
                self.assertEqual(callback['Referrer-Policy'], 'no-referrer')
                self.assertEqual(self.exchange(provider, code, 'wrong' * 13).status_code, 400)
                response = self.exchange(provider, code)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Cache-Control'], 'no-store')
                data = response.json()['data']
                self.assertEqual(set(data), {'access', 'refresh', 'user'})
                self.assertEqual(data['user']['provider'], provider)
                user = User.objects.get(pk=data['user']['id'])
                self.assertFalse(user.has_usable_password())
                self.assertEqual(len(user.identifyCode), 6)
                self.assertNotIn('provider-access', response.content.decode())
                self.assertEqual(SocialIdentity.objects.filter(user=user, provider=provider).count(), 1)
                post = self.post.call_args
                self.assertEqual(post.kwargs['timeout'], 10)
                self.assertFalse(post.kwargs['allow_redirects'])
                self.assertEqual(post.kwargs['data']['code_verifier'], flow.provider_verifier)
                self.assertEqual(post.kwargs['data']['redirect_uri'], f'https://rollpe.mooo.com/api/user/social/login/{provider}/callback')
                flow.refresh_from_db()
                self.assertEqual(flow.provider_verifier, '')
                self.assertEqual(flow.status, 'consumed')
                self.assertEqual(self.exchange(provider, code).status_code, 400)

    def test_expired_unknown_duplicate_or_cross_provider_callback_does_not_contact_provider(self):
        query, flow = self.start('google')
        state = query['state'][0]
        for provider, supplied_state in [('google', 'x' * 43), ('kakao', state), ('google', [state, state])]:
            self.assertEqual(self.callback(provider, supplied_state, code='code').status_code, 400)
        SocialAuthFlow.objects.filter(pk=flow.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.callback('google', state, code='code').status_code, 400)
        self.post.assert_not_called()

    def test_callback_is_claimed_once_before_external_requests(self):
        for provider in ('google', 'kakao'):
            self.post.reset_mock()
            query, flow = self.start(provider)
            self.assertEqual(self.callback(provider, query['state'][0], code='code').status_code, 302)
            self.assertEqual(self.callback(provider, query['state'][0], code='code').status_code, 400)
            self.post.assert_called_once()

    def test_cancel_and_malformed_callback_only_return_to_the_bound_client(self):
        for provider in ('google', 'kakao'):
            for params in ({'error': 'access_denied'}, {'code': ['one', 'two']}, {'code': ''}):
                query, flow = self.start(provider, return_url=f'reactnativerollpe://auth/{provider}')
                response = self.callback(provider, query['state'][0], **params)
                self.assertTrue(response['Location'].startswith(f'reactnativerollpe://auth/{provider}?'))
                self.assertIn('error=', response['Location'])
                flow.refresh_from_db()
                self.assertEqual(flow.status, 'failed')
                self.assertEqual(flow.provider_verifier, '')
        self.assertFalse(User.objects.exists())
        self.post.assert_not_called()

    def test_exchange_binds_provider_and_expiry(self):
        code, flow, _ = self.complete('google')
        self.assertEqual(self.exchange('kakao', code).status_code, 400)
        SocialAuthFlow.objects.filter(pk=flow.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.exchange('google', code).status_code, 400)

    def test_exchange_rejects_inactive_accounts_and_deleted_identity(self):
        for provider in ('google', 'kakao'):
            code, flow, _ = self.complete(provider)
            flow.refresh_from_db()
            user = flow.identity.user
            user.is_active = False
            user.save()
            self.assertEqual(self.exchange(provider, code).status_code, 400)
            user.is_active = True
            user.save()
            flow.identity.delete()
            self.assertEqual(self.exchange(provider, code).status_code, 400)

    def test_existing_email_or_other_provider_accounts_are_never_automatically_linked(self):
        for existing_provider in (None, 'apple', 'kakao'):
            user = User.objects.create_user(email='google@example.com', name='original', provider=existing_provider)
            query, flow = self.start('google')
            response = self.callback('google', query['state'][0], code='code')
            self.assertIn('error=account_conflict', response['Location'])
            self.assertEqual(SocialIdentity.objects.count(), 0)
            self.assertEqual(User.objects.get(pk=user.pk).name, 'original')
            user.delete()

    def test_legacy_same_provider_binding_preserves_account_and_then_uses_subject(self):
        user = User.objects.create_user(email='google@example.com', name='original', provider='google', identifyCode='old123')
        code, flow, _ = self.complete('google')
        self.assertEqual(self.exchange('google', code).json()['data']['user']['id'], user.pk)
        query, flow = self.start('google')
        self.google.return_value['email'] = 'changed@example.com'
        response = self.callback('google', query['state'][0], code='code')
        second_code = parse_qs(urlsplit(response['Location']).query)['code'][0]
        self.assertEqual(self.exchange('google', second_code).json()['data']['user']['id'], user.pk)
        user.refresh_from_db()
        self.assertEqual(user.email, 'google@example.com')
        self.assertEqual(user.identifyCode, 'old123')
        self.assertEqual(User.objects.count(), 1)
        query, flow = self.start('google')
        self.google.return_value['sub'] = 'different-google-user'
        response = self.callback('google', query['state'][0], code='code')
        self.assertIn('error=account_conflict', response['Location'])
        self.assertEqual(SocialIdentity.objects.count(), 1)

    def test_unverified_email_does_not_create_or_bind_an_account(self):
        for provider in ('google', 'kakao'):
            query, flow = self.start(provider)
            if provider == 'google':
                self.google.return_value['email_verified'] = False
            else:
                self.kakao['kakao_account']['is_email_verified'] = False
            response = self.callback(provider, query['state'][0], code='code')
            self.assertIn('error=email_required', response['Location'])
        self.assertEqual(User.objects.count(), 0)

    def test_google_subjects_are_indexed_case_sensitively_independent_of_text_collation(self):
        for subject, email in [('Google-Subject', 'one@example.com'), ('google-subject', 'two@example.com')]:
            query, _ = self.start('google')
            self.google.return_value.update(sub=subject, email=email)
            response = self.callback('google', query['state'][0], code='code')
            code = parse_qs(urlsplit(response['Location']).query)['code'][0]
            self.assertEqual(self.exchange('google', code).json()['data']['user']['email'], email)
            identity = SocialIdentity.objects.get(subject_hash=digest(subject))
            self.assertEqual(identity.subject, subject)
        self.assertEqual(SocialIdentity.objects.count(), 2)

    def test_network_failure_and_invalid_token_responses_never_create_accounts(self):
        for provider in ('google', 'kakao'):
            for failure in ('timeout', 'bad-status', 'invalid-json', 'redirect', 'missing-token'):
                query, flow = self.start(provider)
                self.post.side_effect = None
                self.post.return_value = http_response({})
                if failure == 'timeout':
                    self.post.side_effect = requests.Timeout('secret-must-not-be-logged')
                elif failure == 'bad-status':
                    self.post.return_value = http_response({}, status=400)
                elif failure == 'invalid-json':
                    self.post.return_value.json.side_effect = ValueError('bad-json')
                elif failure == 'redirect':
                    self.post.return_value.status_code = 302
                with self.assertLogs('user.social_browser', level='WARNING') as logs:
                    response = self.callback(provider, query['state'][0], code='code')
                self.assertIn('error=authentication_failed', response['Location'])
                self.assertNotIn('secret-must-not-be-logged', str(logs.output))
                self.assertEqual(User.objects.count(), 0)
        self.post.side_effect = None

    def test_existing_native_social_apis_keep_their_access_token_payload_contract(self):
        self.get.side_effect = lambda url, **kwargs: (
            http_response({'app_id': 5678, 'id': 12345, 'expires_in': 3600})
            if url.endswith('/access_token_info') else http_response(self.kakao)
        )
        for provider in ('google', 'kakao'):
            self.google.return_value = {
                'sub': 'native-google', 'name': 'Native Google',
                'email': 'google@example.com', 'email_verified': True,
            }
            with patch('user.apis_social.return_env_value', return_value='native-ios-client'):
                response = self.client.post(f'/api/user/social/login/{provider}',
                                            json.dumps({'accessToken': 'native-token'}), content_type='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['data']['user']['provider'], provider)
            self.assertIn('refresh', response.json()['data'])
        self.assertFalse(SocialAuthFlow.objects.exists())


class GoogleIdentityValidationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_key = cls.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    def token(self, **overrides):
        now = int(timezone.now().timestamp())
        return jwt.encode({
            'iss': 'https://accounts.google.com', 'aud': 'test-web.apps.googleusercontent.com',
            'iat': now, 'exp': now + 60, 'sub': 'google-sub', 'nonce': 'expected-nonce',
            'email': 'google@example.com', 'email_verified': True, **overrides,
        }, self.key, algorithm='RS256', headers={'kid': 'test-key'})

    def validate(self, token):
        with patch('google.oauth2.id_token._fetch_certs', return_value={'test-key': self.public_key}):
            return google_profile(token, 'test-web.apps.googleusercontent.com', 'expected-nonce')

    def test_google_library_verifies_signature_and_claims(self):
        self.assertEqual(self.validate(self.token())['subject'], 'google-sub')

    def test_google_verified_email_accepts_boolean_and_documented_string_representation(self):
        for value in (True, 'true'):
            self.assertEqual(self.validate(self.token(email_verified=value))['email'], 'google@example.com')
        for value in (False, 'false', 'False', 'True', 1, '1', None):
            self.assertIsNone(self.validate(self.token(email_verified=value))['email'])

    def test_wrong_audience_issuer_nonce_expiry_authorized_party_and_subject_are_rejected(self):
        for claims in ({'aud': 'other-client'}, {'iss': 'https://evil.example'}, {'nonce': 'wrong'},
                       {'exp': 1}, {'azp': 'other-client'}, {'sub': ''}, {'sub': 123}, {'sub': '비ASCII'}):
            with self.subTest(claims=claims), self.assertRaises(SocialAuthenticationError):
                self.validate(self.token(**claims))

    def test_invalid_signature_is_rejected(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pem = other.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        with patch('google.oauth2.id_token._fetch_certs', return_value={'test-key': other_pem}):
            with self.assertRaises(SocialAuthenticationError):
                google_profile(self.token(), 'test-web.apps.googleusercontent.com', 'expected-nonce')
