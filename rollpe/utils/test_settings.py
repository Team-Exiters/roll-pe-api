import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import DisallowedHost, ImproperlyConfigured
from django.test import RequestFactory, SimpleTestCase, override_settings


SETTINGS_FILE = Path(__file__).resolve().parents[1] / 'config' / 'settings.py'


class ServerSettingsTests(SimpleTestCase):
    def load_settings(self, values=None, dotenv=''):
        environment = {
            'DJANGO_SECRET_KEY': 'local-settings-tests-only-not-for-deployment',
            'DJANGO_DATABASE_NAME': 'unused',
            'DJANGO_DATABASE_USER': 'unused',
            'DJANGO_DATABASE_PASSWORD': 'unused',
            'DJANGO_DATABASE_HOST': 'localhost',
            'DJANGO_DATABASE_PORT': '3306',
            'API_DOMAIN': 'api.example.com',
        }
        for key, value in (values or {}).items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        with TemporaryDirectory() as directory:
            Path(directory, '.env').write_text(dotenv)
            # Exercise the real .env loader without reading production settings or credentials.
            with patch.dict(os.environ, environment, clear=True), patch('utils.env.BASE_DIR', Path(directory)):
                return runpy.run_path(str(SETTINGS_FILE))

    def test_api_domain_is_loaded_from_dotenv_and_process_environment_takes_priority(self):
        dotenv = 'API_DOMAIN=mail-api.example.com\nDJANGO_DEBUG=False\n'
        loaded = self.load_settings({'API_DOMAIN': None}, dotenv)
        self.assertEqual(loaded['API_DOMAIN'], 'mail-api.example.com')
        self.assertIs(loaded['DEBUG'], False)
        self.assertIn('mail-api.example.com', loaded['ALLOWED_HOSTS'])
        self.assertEqual(loaded['CSRF_TRUSTED_ORIGINS'], ['https://mail-api.example.com'])
        self.assertEqual(self.load_settings(dotenv=dotenv)['API_DOMAIN'], 'api.example.com')

    def test_missing_or_invalid_domain_cannot_generate_links_to_a_fallback_or_injected_destination(self):
        for domain in (
            None, '', 'https://api.example.com', 'api.example.com/path',
            'user@api.example.com', 'api.example.com?other=1', 'api.example.com#fragment',
            'api.example.com:abc', 'api.example.com:65536', 'api.example.com:0',
            'api.example.com\nattacker.example.com',
        ):
            with self.subTest(domain=domain), self.assertRaises(ImproperlyConfigured):
                self.load_settings({'API_DOMAIN': domain})

    def test_debug_false_is_a_boolean_and_missing_debug_defaults_to_false(self):
        self.assertIs(self.load_settings()['DEBUG'], False)
        for value in ('False', 'false', '0', 'off', ''):
            with self.subTest(value=value):
                self.assertIs(self.load_settings({'DJANGO_DEBUG': value})['DEBUG'], False)
        loaded = self.load_settings({'DJANGO_DEBUG': 'True'})
        self.assertIs(loaded['DEBUG'], True)
        self.assertIn('http://localhost:8000', loaded['CSRF_TRUSTED_ORIGINS'])

    def test_allowed_hosts_accept_api_and_loopback_but_reject_an_unrelated_host(self):
        loaded = self.load_settings({'API_DOMAIN': ' api.example.com:8443 '})
        self.assertEqual(loaded['API_DOMAIN'], 'api.example.com:8443')
        with override_settings(ALLOWED_HOSTS=loaded['ALLOWED_HOSTS']):
            for host in ('api.example.com:8443', 'localhost:8000', '127.0.0.1:8000', '[::1]:8000'):
                self.assertEqual(RequestFactory().get('/', HTTP_HOST=host).get_host(), host)
            with self.assertRaises(DisallowedHost):
                RequestFactory().get('/', HTTP_HOST='attacker.example.com').get_host()
        ipv6 = self.load_settings({'API_DOMAIN': '[::1]:8443'})
        self.assertIn('[::1]', ipv6['ALLOWED_HOSTS'])

    def test_explicit_allowed_hosts_are_trimmed_and_cannot_allow_every_host(self):
        loaded = self.load_settings({'DJANGO_ALLOWED_HOSTS': ' api.example.com, internal.example.com '})
        self.assertEqual(loaded['ALLOWED_HOSTS'], ['api.example.com', 'internal.example.com'])
        for hosts in ('*', 'api.example.com,*', '', ' , '):
            with self.subTest(hosts=hosts), self.assertRaises(ImproperlyConfigured):
                self.load_settings({'DJANGO_ALLOWED_HOSTS': hosts})

    def test_social_callback_defaults_follow_api_domain_and_explicit_values_are_preserved(self):
        loaded = self.load_settings({'API_DOMAIN': 'login-api.example.com'})
        for provider in ('google', 'kakao'):
            self.assertEqual(
                loaded[f'{provider.upper()}_AUTH_REDIRECT_URI'],
                f'https://login-api.example.com/api/user/social/login/{provider}/callback',
            )
        explicit = self.load_settings({
            'GOOGLE_AUTH_REDIRECT_URI': 'https://callback.example.com/google',
            'KAKAO_AUTH_REDIRECT_URI': 'https://callback.example.com/kakao',
        })
        self.assertEqual(explicit['GOOGLE_AUTH_REDIRECT_URI'], 'https://callback.example.com/google')
        self.assertEqual(explicit['KAKAO_AUTH_REDIRECT_URI'], 'https://callback.example.com/kakao')
