from unittest.mock import patch

from django.test import SimpleTestCase, override_settings


class AppLinkMetadataTests(SimpleTestCase):
    def test_apple_identity_path_content_type_and_no_redirect(self):
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
            response = self.client.get('/.well-known/apple-app-site-association')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(response.json()['applinks']['details'], [{
            'appID': '42NW282TDP.dev.hugesilver.Roll-Pe',
            'paths': ['/api/user/password-reset/*'],
        }])

    @override_settings(ANDROID_APP_LINKS_SHA256_FINGERPRINTS=[])
    def test_android_empty_by_default(self):
        self.assertEqual(self.client.get('/.well-known/assetlinks.json').json(), [])

    @override_settings(ANDROID_APP_LINKS_SHA256_FINGERPRINTS=['ab:' * 31 + 'ab'])
    def test_android_verified_format_and_public_package(self):
        response = self.client.get('/.well-known/assetlinks.json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        target = response.json()[0]['target']
        self.assertEqual(target['package_name'], 'dev.hugesilver.RollPe')
        self.assertEqual(target['sha256_cert_fingerprints'], ['AB:' * 31 + 'AB'])

    def test_malformed_configuration_denies_all(self):
        for value in [['AA:BB'], ['AB:' * 31 + 'AB', 'invalid'], 'AB:' * 31 + 'AB']:
            with override_settings(ANDROID_APP_LINKS_SHA256_FINGERPRINTS=value):
                self.assertEqual(self.client.get('/.well-known/assetlinks.json').json(), [])

    def test_public_endpoints_are_read_only(self):
        for url in ['/.well-known/assetlinks.json', '/.well-known/apple-app-site-association']:
            self.assertEqual(self.client.post(url).status_code, 405)
            self.assertEqual(self.client.head(url).status_code, 200)
