from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from user.models import AppleAuthFlow, SocialAuthFlow


class ConfigurationDiagnosticsTests(SimpleTestCase):
    @override_settings(APPLE_AUTH_NATIVE_CLIENT_ID='private-client-value', APPLE_AUTH_TEAM_ID='', APPLE_AUTH_PRIVATE_KEY_FILE='', APPLE_AUTH_TOKEN_ENCRYPTION_KEYS=[])
    def test_no_database_network_or_secret_values(self):
        output = StringIO()
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
            call_command('check_social_auth', stdout=output)
        self.assertIn('Apple native identity-token verification: configured', output.getvalue())
        self.assertIn('APPLE_AUTH_TEAM_ID', output.getvalue())
        self.assertNotIn('private-client-value', output.getvalue())

    @override_settings(APPLE_AUTH_TOKEN_ENCRYPTION_KEYS=['secret-invalid-key'], APPLE_AUTH_PRIVATE_KEY_FILE='/no/such/private-signing-file.p8')
    def test_invalid_keys_and_file_are_redacted(self):
        output = StringIO()
        call_command('check_social_auth', stdout=output)
        self.assertIn('invalid format', output.getvalue())
        self.assertIn('unreadable', output.getvalue())
        self.assertNotIn('secret-invalid-key', output.getvalue())
        self.assertNotIn('/no/such', output.getvalue())


class ExpiredFlowCleanupTests(TestCase):
    def test_default_dry_run_and_bounded_apply_preserve_recent_rows(self):
        now = timezone.now()
        for model in (AppleAuthFlow, SocialAuthFlow):
            for index, age in enumerate([48, 48, 48, 0, -1]):
                model.objects.create(state_hash=str(index), nonce='nonce', client_state='state', code_challenge='challenge', return_url='rollpe://auth/apple', expires_at=now - timedelta(hours=age))
        call_command('cleanup_auth_flows', limit=2, stdout=StringIO())
        self.assertEqual(AppleAuthFlow.objects.count(), 5)
        call_command('cleanup_auth_flows', apply=True, limit=2, stdout=StringIO())
        for model in (AppleAuthFlow, SocialAuthFlow):
            self.assertEqual(model.objects.count(), 3)
            self.assertTrue(model.objects.filter(state_hash='3').exists())
            self.assertTrue(model.objects.filter(state_hash='4').exists())

    def test_reject_unsafe_bounds(self):
        for kwargs in ({'limit': 0}, {'limit': 10001}, {'older_than_hours': 0}):
            with self.assertRaises(CommandError):
                call_command('cleanup_auth_flows', stdout=StringIO(), **kwargs)
