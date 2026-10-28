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
            'paths': ['/api/user/password-reset/*', '/rollpe/*'],
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


class RollpeInvitationPageTests(SimpleTestCase):
    code = '12345678-1234-4234-8234-123456789abc'

    def test_link_preview_has_no_database_provider_or_participation_side_effects(self):
        # SimpleTestCase also forbids database access, including authentication.
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
            response = self.client.get(f'/rollpe/{self.code}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="rollpe://rollpe/{self.code}"')
        self.assertContains(response, '로그인 후 참여 여부를 확인할 수 있습니다.')
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertIn("default-src 'none'", response['Content-Security-Policy'])
        self.assertNotContains(response, '<script')

    def test_links_ignore_queries_and_never_embed_arbitrary_return_targets(self):
        response = self.client.get(f'/rollpe/{self.code}?next=https://untrusted.example&title=private-title')
        self.assertContains(response, f'href="rollpe://rollpe/{self.code}"')
        self.assertNotContains(response, 'untrusted.example')
        self.assertNotContains(response, 'private-title')

    def test_unavailable_and_private_codes_have_the_same_generic_page(self):
        for code in [self.code, '00000000-0000-0000-0000-000000000000']:
            response = self.client.get(f'/rollpe/{code}')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, '롤페에 초대받으셨나요?')

    def test_invalid_code_and_write_requests_are_rejected(self):
        for path in ['bad-code', '../home', self.code + '/content']:
            self.assertEqual(self.client.get(f'/rollpe/{path}').status_code, 404)
        self.assertEqual(self.client.post(f'/rollpe/{self.code}').status_code, 405)
        self.assertEqual(self.client.head(f'/rollpe/{self.code}').status_code, 200)
