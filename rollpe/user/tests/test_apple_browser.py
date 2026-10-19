import json
import tempfile
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from user.apple_browser import digest, pkce_challenge
from user.apple_sessions import APPLE_ISSUER, AppleAuthenticationError, create_client_secret, exchange_apple_code
from user.models import AppleAuthFlow, AppleCredential, User


class AppleBrowserTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.verifier = 'v' * 64
        self.client_state = 's' * 43
        self.return_url = 'http://localhost:8081/auth/apple'

    def start(self, **overrides):
        params = {
            'return_url': self.return_url,
            'state': self.client_state,
            'code_challenge': pkce_challenge(self.verifier),
            **overrides,
        }
        response = self.client.get(reverse('apple_start'), params)
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response['Location']).query)
        return query, AppleAuthFlow.objects.get(state_hash=digest(query['state'][0]))

    def callback(self, state, **params):
        return self.client.post(reverse('apple_callback'), {'state': state, **params})

    def exchange(self, code, verifier=None):
        return self.client.post(
            reverse('apple_exchange'),
            json.dumps({'code': code, 'code_verifier': verifier or self.verifier}),
            content_type='application/json',
        )

    def test_start_binds_nonce_state_and_pkce_without_cookies(self):
        query, flow = self.start()
        self.assertEqual(query['client_id'], ['dev.hugesilver.rollpe.web'])
        self.assertEqual(query['response_type'], ['code'])
        self.assertEqual(query['response_mode'], ['form_post'])
        self.assertEqual(query['nonce'], [flow.nonce])
        self.assertNotEqual(query['state'][0], self.client_state)
        self.assertEqual(flow.code_challenge, pkce_challenge(self.verifier))

    def test_rejects_open_redirect_and_malformed_challenge(self):
        for return_url in ['https://evil.example/auth/apple', self.return_url + '?next=evil']:
            response = self.client.get(reverse('apple_start'), {
                'return_url': return_url, 'state': self.client_state,
                'code_challenge': pkce_challenge(self.verifier),
            })
            self.assertEqual(response.status_code, 400)
        self.assertEqual(AppleAuthFlow.objects.count(), 0)

    @override_settings(APPLE_AUTH_KEY_ID='')
    def test_missing_server_configuration_is_not_a_fake_login(self):
        response = self.client.get(reverse('apple_start'), {
            'return_url': self.return_url, 'state': self.client_state,
            'code_challenge': pkce_challenge(self.verifier),
        })
        self.assertEqual(response.status_code, 503)
        self.assertFalse(AppleAuthFlow.objects.exists())

    @override_settings(APPLE_AUTH_TOKEN_ENCRYPTION_KEYS=[])
    def test_missing_encryption_key_never_starts_an_unprotected_login(self):
        response = self.client.get(reverse('apple_start'), {
            'return_url': self.return_url, 'state': self.client_state,
            'code_challenge': pkce_challenge(self.verifier),
        })
        self.assertEqual(response.status_code, 503)
        self.assertFalse(AppleAuthFlow.objects.exists())

    @patch('user.apple_browser.exchange_apple_code')
    def test_callback_and_single_use_exchange(self, apple):
        apple.return_value = ({'email': 'apple@example.com', 'email_verified': True, 'sub': 'apple-sub'}, {'id_token': 'verified-id', 'refresh_token': 'apple-refresh', 'access_token': 'apple-access'})
        query, flow = self.start()
        response = self.callback(query['state'][0], code='apple-code', user=json.dumps({
            'name': {'lastName': '김', 'firstName': '태은'},
        }))
        self.assertEqual(response.status_code, 302)
        result = parse_qs(urlsplit(response['Location']).query)
        self.assertEqual(result['state'], [self.client_state])
        self.assertNotIn('access', result)
        self.assertNotIn('refresh', result)
        apple.assert_called_once_with('apple-code', flow.nonce, redirect_uri='https://rollpe.mooo.com/api/user/social/login/apple/callback')
        code = result['code'][0]
        self.assertEqual(self.exchange(code, 'wrong' * 13).status_code, 400)
        success = self.exchange(code)
        self.assertEqual(success.status_code, 200)
        data = success.json()['data']
        self.assertIn('access', data)
        self.assertIn('refresh', data)
        self.assertEqual(data['user']['name'], '김태은')
        self.assertEqual(data['user']['provider'], 'apple')
        self.assertEqual(AppleCredential.objects.count(), 1)
        self.assertNotIn('apple-refresh', success.content.decode())
        self.assertNotIn('apple-refresh', AppleCredential.objects.get().token_response)
        self.assertFalse(User.objects.get(email='apple@example.com').has_usable_password())
        self.assertEqual(success['Cache-Control'], 'no-store')
        self.assertEqual(self.exchange(code).status_code, 400)
        self.assertEqual(self.callback(query['state'][0], code='apple-code').status_code, 400)

    @patch('user.apple_browser.exchange_apple_code')
    def test_invalid_and_expired_state_do_not_contact_apple(self, apple):
        self.assertEqual(self.callback('unknown', code='code').status_code, 400)
        query, flow = self.start()
        flow.expires_at = timezone.now() - timedelta(seconds=1)
        flow.save()
        self.assertEqual(self.callback(query['state'][0], code='code').status_code, 400)
        apple.assert_not_called()

    def test_cancel_is_returned_only_to_the_bound_client(self):
        query, flow = self.start(return_url='reactnativerollpe://auth/apple')
        response = self.callback(query['state'][0], error='user_cancelled_authorize')
        self.assertTrue(response['Location'].startswith('reactnativerollpe://auth/apple?'))
        self.assertEqual(parse_qs(urlsplit(response['Location']).query)['error'], ['cancelled'])
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(self.callback(query['state'][0], code='replay').status_code, 400)

    @patch('user.apple_browser.exchange_apple_code')
    def test_existing_other_provider_account_is_not_linked(self, apple):
        User.objects.create_user(email='same@example.com', name='original', provider='google')
        apple.return_value = ({'email': 'same@example.com', 'email_verified': True, 'sub': 'apple-sub'}, {'id_token': 'verified-id', 'refresh_token': 'apple-refresh'})
        query, flow = self.start()
        response = self.callback(query['state'][0], code='code')
        self.assertIn('error=authentication_failed', response['Location'])
        self.assertEqual(User.objects.get(email='same@example.com').provider, 'google')
        flow.refresh_from_db()
        self.assertIsNone(flow.exchange_hash)

    @patch('user.apple_browser.exchange_apple_code')
    def test_exchange_expires(self, apple):
        apple.return_value = ({'email': 'apple@example.com', 'email_verified': True, 'sub': 'apple-sub'}, {'id_token': 'verified-id', 'refresh_token': 'apple-refresh', 'access_token': 'apple-access'})
        query, flow = self.start()
        response = self.callback(query['state'][0], code='code')
        code = parse_qs(urlsplit(response['Location']).query)['code'][0]
        AppleAuthFlow.objects.filter(pk=flow.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.exchange(code).status_code, 400)


class AppleTokenValidationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def token(self, **overrides):
        now = int(timezone.now().timestamp())
        return jwt.encode({
            'iss': APPLE_ISSUER, 'aud': 'dev.hugesilver.rollpe.web',
            'iat': now, 'exp': now + 60, 'sub': 'subject',
            'nonce': 'expected-nonce', 'email': 'apple@example.com',
            'email_verified': True, **overrides,
        }, self.key, algorithm='RS256')

    def validate(self, token):
        with patch('user.apple_sessions.create_client_secret', return_value='secret'), \
             patch('user.apple_sessions.requests.post') as post, \
             patch('user.apple_sessions.apple_keys.get_signing_key_from_jwt', return_value=SimpleNamespace(key=self.key.public_key())):
            post.return_value.json.return_value = {'id_token': token, 'refresh_token': 'apple-refresh', 'access_token': 'apple-access'}
            return exchange_apple_code('authorization-code', 'expected-nonce')[0]

    def test_valid_signature_and_claims(self):
        self.assertEqual(self.validate(self.token())['sub'], 'subject')

    def test_rejects_wrong_audience_issuer_nonce_and_expiry(self):
        for claims in [
            {'aud': 'another-service'}, {'iss': 'https://evil.example'},
            {'nonce': 'another-request'}, {'exp': 1},
        ]:
            with self.subTest(claims=claims), self.assertRaises((jwt.PyJWTError, ValueError)):
                self.validate(self.token(**claims))

    def test_rejects_a_token_signed_by_another_key(self):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with patch('user.apple_sessions.create_client_secret', return_value='secret'), \
             patch('user.apple_sessions.requests.post') as post, \
             patch('user.apple_sessions.apple_keys.get_signing_key_from_jwt', return_value=SimpleNamespace(key=other_key.public_key())):
            post.return_value.json.return_value = {'id_token': self.token(), 'refresh_token': 'apple-refresh', 'access_token': 'apple-access'}
            with self.assertRaises(AppleAuthenticationError):
                exchange_apple_code('authorization-code', 'expected-nonce')

    def test_client_secret_uses_es256_service_id_and_short_expiry(self):
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        with tempfile.NamedTemporaryFile() as key_file:
            key_file.write(pem)
            key_file.flush()
            with override_settings(APPLE_AUTH_PRIVATE_KEY_FILE=key_file.name):
                token = create_client_secret()
        self.assertEqual(jwt.get_unverified_header(token)['kid'], 'TESTKEY')
        claims = jwt.decode(token, key.public_key(), algorithms=['ES256'], audience=APPLE_ISSUER, issuer='TESTTEAM')
        self.assertEqual(claims['sub'], 'dev.hugesilver.rollpe.web')
        self.assertEqual(claims['exp'] - claims['iat'], 300)
