"""Report configuration presence without values, database or provider requests."""
import os
from pathlib import Path

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Inspect social login prerequisites locally without exposing configuration values.'
    requires_system_checks = []
    requires_migrations_checks = False

    def handle(self, *args, **options):
        def present(name):
            return bool(getattr(settings, name, ''))

        def report(label, names):
            missing = [name for name in names if not present(name)]
            self.stdout.write(f'{label}: ' + ('configured' if not missing else 'missing ' + ', '.join(missing)))

        report('Apple native identity-token verification', ['APPLE_AUTH_NATIVE_CLIENT_ID'])
        signing = ['APPLE_AUTH_TEAM_ID', 'APPLE_AUTH_KEY_ID', 'APPLE_AUTH_PRIVATE_KEY_FILE',
                   'APPLE_AUTH_TOKEN_ENCRYPTION_KEYS']
        report('Apple native code exchange / revocation', ['APPLE_AUTH_NATIVE_CLIENT_ID', *signing])
        report('Apple browser', ['APPLE_AUTH_CLIENT_ID', 'APPLE_AUTH_REDIRECT_URI',
                                 'APPLE_AUTH_RETURN_URLS', *signing])
        key_file = getattr(settings, 'APPLE_AUTH_PRIVATE_KEY_FILE', '')
        if key_file:
            try:
                readable = Path(key_file).is_file()
                if readable:
                    with open(key_file, 'rb') as stream:
                        stream.read(1)
            except (OSError, ValueError):
                readable = False
            self.stdout.write('Apple signing key file: ' + ('readable (contents not validated)' if readable else 'unreadable'))
        keys = getattr(settings, 'APPLE_AUTH_TOKEN_ENCRYPTION_KEYS', [])
        if keys:
            try:
                for key in keys:
                    Fernet(key)
            except (ValueError, TypeError):
                self.stdout.write('Apple encryption keys: invalid format')
            else:
                self.stdout.write('Apple encryption keys: valid format')
        google_native = present('GOOGLE_AUTH_CLIENT_ID') or bool(os.environ.get('IOS_GOOGLE_OAUTH_CLIENT_KEY'))
        self.stdout.write('Google native: ' + ('configured' if google_native else 'missing GOOGLE_AUTH_CLIENT_ID or IOS_GOOGLE_OAUTH_CLIENT_KEY'))
        report('Google browser', ['GOOGLE_AUTH_CLIENT_ID', 'GOOGLE_AUTH_CLIENT_SECRET',
                                  'GOOGLE_AUTH_REDIRECT_URI', 'GOOGLE_AUTH_RETURN_URLS'])
        report('Kakao native', ['KAKAO_AUTH_APP_ID'])
        report('Kakao browser', ['KAKAO_AUTH_CLIENT_ID', 'KAKAO_AUTH_REDIRECT_URI', 'KAKAO_AUTH_RETURN_URLS'])
        self.stdout.write('Kakao browser secret: ' + ('configured' if present('KAKAO_AUTH_CLIENT_SECRET') else 'absent; confirm console secret is disabled'))
        self.stdout.write('Presence checks only; provider console, credentials, network and database are not validated.')
