from datetime import timedelta
from unittest.mock import Mock, patch

import requests
from cryptography.fernet import Fernet
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from user.apis_social import get_tokens_for_user
from user.apple_sessions import AppleAuthenticationError, apple_user, save_credential, stored_tokens
from user.models import AppleCredential, User
from user.serializers import UserSerializer


def apple_response(status=200, payload=None):
    response = Mock(status_code=status)
    response.json.return_value = payload or {'access_token': 'new-apple-access'}
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


class AppleIdentityTests(TestCase):
    def setUp(self):
        self.request = APIRequestFactory().get('/')

    def identity(self, subject='apple-user', email='apple@example.com', **overrides):
        return {'sub': subject, 'email': email, 'email_verified': True, **overrides}

    def test_verified_subject_survives_changed_or_missing_email(self):
        user, created = apple_user(self.request, self.identity(), '<b>사용자</b>')
        self.assertTrue(created)
        self.assertEqual(user.name, '사용자')
        same, created = apple_user(self.request, self.identity(email='changed@example.com'))
        self.assertEqual(same.pk, user.pk)
        self.assertFalse(created)
        same, _ = apple_user(self.request, {'sub': 'apple-user'})
        self.assertEqual(same.pk, user.pk)
        self.assertEqual(User.objects.count(), 1)

    def test_legacy_apple_account_is_bound_once_to_verified_email(self):
        user = User.objects.create_user(email='apple@example.com', name='기존', provider='apple')
        bound, created = apple_user(self.request, self.identity())
        self.assertEqual(bound.pk, user.pk)
        self.assertFalse(created)
        self.assertEqual(bound.apple_subject, 'apple-user')
        with self.assertRaises(AppleAuthenticationError):
            apple_user(self.request, self.identity(subject='different-subject'))
        self.assertEqual(User.objects.count(), 1)

    def test_other_providers_and_inactive_accounts_are_never_linked(self):
        user = User.objects.create_user(email='apple@example.com', name='기존', provider='google')
        with self.assertRaises(AppleAuthenticationError):
            apple_user(self.request, self.identity())
        user.provider, user.is_active = 'apple', False
        user.save()
        with self.assertRaises(AppleAuthenticationError):
            apple_user(self.request, self.identity())
        user.refresh_from_db()
        self.assertIsNone(user.apple_subject)

    def test_email_less_apple_accounts_do_not_share_a_placeholder_email(self):
        first, _ = apple_user(self.request, {'sub': 'one'})
        second, _ = apple_user(self.request, {'sub': 'two'})
        self.assertNotEqual(first.pk, second.pk)
        self.assertIsNone(first.email)
        self.assertIsNone(second.email)
        self.assertFalse(first.has_usable_password())

    def test_unverified_email_does_not_claim_an_existing_account(self):
        existing = User.objects.create_user(email='apple@example.com', name='기존', provider='apple')
        user, _ = apple_user(self.request, self.identity(email_verified=False))
        self.assertNotEqual(user.pk, existing.pk)
        self.assertIsNone(user.email)

    def test_normal_signup_still_requires_an_email_and_cannot_set_apple_subject(self):
        for email in (None, ''):
            serializer = UserSerializer(data={'name': '테스트', 'email': email, 'password': 'password'})
            self.assertFalse(serializer.is_valid())
        serializer = UserSerializer(data={
            'name': '테스트', 'email': 'other@example.com', 'password': 'password',
            'apple_subject': 'forged',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('apple_subject', serializer.validated_data)

    def test_token_response_is_encrypted_and_supports_key_rotation(self):
        user, _ = apple_user(self.request, self.identity())
        tokens = {'id_token': 'sensitive-id', 'access_token': 'sensitive-access', 'refresh_token': 'sensitive-refresh'}
        credential = save_credential(user, tokens, settings.APPLE_AUTH_CLIENT_ID)
        for value in tokens.values():
            self.assertNotIn(value, credential.token_response)
        with override_settings(APPLE_AUTH_TOKEN_ENCRYPTION_KEYS=[
            Fernet.generate_key().decode(), *settings.APPLE_AUTH_TOKEN_ENCRYPTION_KEYS,
        ]):
            self.assertEqual(stored_tokens(credential), tokens)


class AppleSessionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            name='사용자', email='apple@example.com', provider='apple',
            apple_subject='apple-subject', identifyCode='123abc',
        )
        self.credential = self.new_credential()
        self.tokens = get_tokens_for_user(self.user, self.credential)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.tokens['access']}")

    def new_credential(self, client_id=None, tokens=None):
        return save_credential(self.user, tokens or {
            'refresh_token': 'apple-refresh', 'id_token': 'apple-id', 'access_token': 'apple-access',
        }, client_id or settings.APPLE_AUTH_CLIENT_ID)

    def stale(self):
        AppleCredential.objects.filter(pk=self.credential.pk).update(
            verified_at=timezone.now() - timedelta(days=2),
        )

    def refresh(self, tokens=None):
        client = APIClient()  # Refresh does not require an access header.
        return client.post(reverse('token_refresh'), {'refresh': (tokens or self.tokens)['refresh']}, format='json')

    def account_request(self):
        return self.client.post(reverse('password_check'), {'password': 'not-a-password'}, format='json')

    def delete(self, tokens=None, identify='123abc'):
        return self.client.delete(reverse('drop_user'), {
            'refresh': (tokens or self.tokens)['refresh'], 'identifyCode': identify,
        }, format='json')

    @patch('user.apple_sessions.requests.post')
    def test_fresh_session_does_not_call_apple_and_keeps_session_binding(self, post):
        response = self.refresh()
        self.assertEqual(response.status_code, 200)
        from rest_framework_simplejwt.tokens import AccessToken
        self.assertEqual(AccessToken(response.json()['access'])['apple_session'], str(self.credential.session_id))
        self.assertEqual(self.account_request().status_code, 200)
        post.assert_not_called()

    @patch('user.apple_sessions.create_client_secret', return_value='test-secret')
    @patch('user.apple_sessions.requests.post')
    def test_refresh_verifies_with_apple_once_per_day(self, post, secret):
        self.stale()
        post.return_value = apple_response(payload={'access_token': 'new-access', 'refresh_token': 'rotated-refresh'})
        self.assertEqual(self.refresh().status_code, 200)
        self.assertEqual(self.refresh().status_code, 200)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs['data']['grant_type'], 'refresh_token')
        self.assertEqual(post.call_args.kwargs['data']['refresh_token'], 'apple-refresh')
        secret.assert_called_once_with(settings.APPLE_AUTH_CLIENT_ID)
        self.credential.refresh_from_db()
        self.assertEqual(stored_tokens(self.credential)['refresh_token'], 'rotated-refresh')

    @patch('user.apple_sessions.create_client_secret', return_value='test-secret')
    @patch('user.apple_sessions.requests.post')
    def test_revocation_denies_existing_access_and_refresh_without_rolling_back(self, post, secret):
        self.stale()
        post.return_value = apple_response(status=400, payload={'error': 'invalid_grant'})
        self.assertEqual(self.refresh().status_code, 401)
        self.credential.refresh_from_db()
        self.assertIsNotNone(self.credential.invalidated_at)
        self.assertIsNotNone(self.credential.apple_revoked_at)
        self.assertEqual(stored_tokens(self.credential), {})
        self.assertEqual(self.account_request().status_code, 401)
        self.assertEqual(self.refresh().status_code, 401)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    @patch('user.apple_sessions.create_client_secret', return_value='test-secret')
    @patch('user.apple_sessions.requests.post', side_effect=requests.Timeout())
    def test_temporary_failure_does_not_revoke_account_or_repeatedly_call_apple(self, post, secret):
        self.stale()
        self.assertEqual(self.refresh().status_code, 503)
        self.assertEqual(self.refresh().status_code, 503)
        self.credential.refresh_from_db()
        self.assertIsNone(self.credential.invalidated_at)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(stored_tokens(self.credential)['refresh_token'], 'apple-refresh')

    @patch('user.apple_sessions.create_client_secret', return_value='test-secret')
    @patch('user.apple_sessions.requests.post')
    def test_malformed_apple_response_cannot_renew_the_app_session(self, post, secret):
        self.stale()
        post.return_value = apple_response()
        post.return_value.json.return_value = ['not-a-token-response']
        self.assertEqual(self.refresh().status_code, 503)
        self.credential.refresh_from_db()
        self.assertIsNone(self.credential.invalidated_at)

    @patch('user.apple_sessions.verify_identity_token', return_value={'sub': 'another-user'})
    @patch('user.apple_sessions.create_client_secret', return_value='test-secret')
    @patch('user.apple_sessions.requests.post')
    def test_refresh_never_switches_to_a_different_apple_user(self, post, secret, verify):
        self.stale()
        post.return_value = apple_response(payload={'access_token': 'new-access', 'id_token': 'wrong-user'})
        self.assertEqual(self.refresh().status_code, 401)
        self.assertEqual(self.account_request().status_code, 401)
        self.user.refresh_from_db()
        self.assertEqual(self.user.apple_subject, 'apple-subject')

    @patch('user.apple_sessions.requests.post')
    def test_logout_ends_only_this_app_session_without_revoking_apple_consent(self, post):
        other = self.new_credential()
        other_tokens = get_tokens_for_user(self.user, other)
        response = self.client.post(reverse('logout'), {'refresh': self.tokens['refresh']}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.account_request().status_code, 401)
        self.assertEqual(self.refresh().status_code, 401)
        self.assertEqual(self.refresh(other_tokens).status_code, 200)
        self.credential.refresh_from_db()
        self.assertIsNone(self.credential.apple_revoked_at)
        self.assertEqual(stored_tokens(self.credential)['refresh_token'], 'apple-refresh')
        post.assert_not_called()

    @patch('user.apple_sessions.requests.post')
    def test_other_users_refresh_cannot_logout_or_delete_an_account(self, post):
        other = User.objects.create_user(email='other@example.com', name='다른 사용자')
        tokens = {'refresh': str(RefreshToken.for_user(other))}
        self.assertEqual(self.client.post(reverse('logout'), tokens, format='json').status_code, 403)
        self.assertEqual(self.delete(tokens).status_code, 403)
        self.assertEqual(self.account_request().status_code, 200)
        self.assertFalse(BlacklistedToken.objects.exists())
        post.assert_not_called()

    @patch('user.apple_sessions.create_client_secret', return_value='test-secret')
    @patch('user.apple_sessions.requests.post')
    def test_delete_revokes_all_credentials_and_invalidates_all_local_tokens(self, post, secret):
        second = self.new_credential(client_id=settings.APPLE_AUTH_NATIVE_CLIENT_ID)
        second_tokens = get_tokens_for_user(self.user, second)
        post.return_value = apple_response()
        response = self.delete()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_count, 2)
        for call in post.call_args_list:
            self.assertTrue(call.args[0].endswith('/auth/revoke'))
            self.assertEqual(call.kwargs['data']['token_type_hint'], 'refresh_token')
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(AppleCredential.objects.filter(user_id=self.user.pk).exists())
        self.assertEqual(BlacklistedToken.objects.count(), 2)
        self.assertEqual(self.refresh().status_code, 401)
        self.assertEqual(self.refresh(second_tokens).status_code, 401)
        self.assertEqual(self.account_request().status_code, 401)

    @patch('user.apple_sessions.create_client_secret', return_value='test-secret')
    @patch('user.apple_sessions.requests.post')
    def test_delete_includes_apple_credentials_from_logged_out_devices(self, post, secret):
        self.client.post(reverse('logout'), {'refresh': self.tokens['refresh']}, format='json')
        second = get_tokens_for_user(self.user, self.new_credential())
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {second['access']}")
        post.return_value = apple_response()
        self.assertEqual(self.delete(second).status_code, 200)
        self.assertEqual(post.call_count, 2)

    @patch('user.apple_sessions.create_client_secret', return_value='test-secret')
    @patch('user.apple_sessions.requests.post', side_effect=requests.Timeout())
    def test_delete_failure_keeps_account_and_credentials_for_retry(self, post, secret):
        self.assertEqual(self.delete().status_code, 503)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(BlacklistedToken.objects.exists())
        self.credential.refresh_from_db()
        self.assertIsNone(self.credential.invalidated_at)
        self.assertEqual(stored_tokens(self.credential)['refresh_token'], 'apple-refresh')
        post.side_effect = None
        post.return_value = apple_response()
        self.assertEqual(self.delete().status_code, 200)

    @patch('user.apple_sessions.requests.post')
    def test_deletion_with_no_stored_apple_token_still_fulfils_request(self, post):
        self.credential.token_response = self.new_credential(tokens={'id_token': 'legacy-id'}).token_response
        self.credential.save(update_fields=['token_response'])
        response = self.delete()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['appleRevocationRequired'])
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        post.assert_not_called()

    @patch('user.apple_sessions.requests.post')
    def test_pre_migration_account_without_any_apple_credentials_can_be_deleted(self, post):
        self.user.apple_credentials.all().delete()
        self.user.apple_subject = None
        self.user.save(update_fields=['apple_subject'])
        legacy = get_tokens_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {legacy['access']}")
        response = self.delete(legacy)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['appleRevocationRequired'])
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        post.assert_not_called()

    @patch('user.apple_sessions.requests.post')
    def test_normal_account_deletion_does_not_contact_apple(self, post):
        normal = User.objects.create_user(email='normal@example.com', name='일반 사용자', identifyCode='normal')
        tokens = get_tokens_for_user(normal)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.delete(tokens, identify='normal').status_code, 200)
        self.assertFalse(User.objects.filter(pk=normal.pk).exists())
        post.assert_not_called()

    def test_invalidated_deleted_inactive_and_malformed_sessions_are_rejected(self):
        token = RefreshToken.for_user(self.user)
        token['apple_session'] = 'not-a-uuid'
        self.assertEqual(self.refresh({'refresh': str(token)}).status_code, 401)
        legacy_token = RefreshToken.for_user(self.user)
        self.assertEqual(self.refresh({'refresh': str(legacy_token)}).status_code, 401)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.refresh().status_code, 401)
        self.user.delete()
        self.assertEqual(self.refresh().status_code, 401)

    @patch('user.apple_sessions.requests.post')
    def test_legacy_identity_only_session_requires_reauthentication_after_a_day(self, post):
        self.credential.token_response = self.new_credential(tokens={'id_token': 'legacy-id'}).token_response
        self.credential.save(update_fields=['token_response'])
        self.stale()
        self.assertEqual(self.refresh().status_code, 401)
        self.assertEqual(self.account_request().status_code, 401)
        post.assert_not_called()


class AppleNativeCompatibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('social_login', kwargs={'provider': 'apple'})

    @patch('user.apis_social.verify_identity_token')
    def test_existing_native_identity_token_payload_still_logs_in(self, verify):
        verify.return_value = {'sub': 'native-sub', 'email': 'native@example.com', 'email_verified': True}
        response = self.client.post(self.url, {'accessToken': 'native-id', 'name': '기존 사용자'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.json()['data'])
        verify.assert_called_once_with('native-id', settings.APPLE_AUTH_NATIVE_CLIENT_ID, None)
        self.assertEqual(User.objects.get().apple_subject, 'native-sub')
        self.assertEqual(stored_tokens(AppleCredential.objects.get()), {'id_token': 'native-id'})

    @patch('user.apis_social.exchange_apple_code')
    def test_new_native_authorization_code_is_stored_for_future_revocation(self, exchange):
        exchange.return_value = (
            {'sub': 'native-sub', 'email': 'native@example.com', 'email_verified': True},
            {'id_token': 'native-id', 'refresh_token': 'native-refresh', 'access_token': 'native-access'},
        )
        response = self.client.post(self.url, {'code': 'native-code', 'nonce': 'bound-request'}, format='json')
        self.assertEqual(response.status_code, 200)
        exchange.assert_called_once_with('native-code', 'bound-request', client_id=settings.APPLE_AUTH_NATIVE_CLIENT_ID)
        self.assertEqual(stored_tokens(AppleCredential.objects.get())['refresh_token'], 'native-refresh')

    @patch('user.apis_social.verify_identity_token', side_effect=AppleAuthenticationError('유효하지 않은 인증'))
    def test_invalid_identity_is_a_controlled_error_without_creating_an_account(self, verify):
        response = self.client.post(self.url, {'accessToken': 'invalid'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())

    @override_settings(APPLE_AUTH_NATIVE_CLIENT_ID='')
    @patch('user.apis_social.exchange_apple_code')
    def test_missing_native_app_id_never_falls_back_to_web_client(self, exchange):
        response = self.client.post(self.url, {'code': 'native-code'}, format='json')
        self.assertEqual(response.status_code, 503)
        exchange.assert_not_called()
