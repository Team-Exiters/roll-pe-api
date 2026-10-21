"""Public association metadata; no database or authentication dependencies."""
import re

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_safe

FINGERPRINT = re.compile(r'(?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}\Z')


@require_safe
def apple_app_site_association(request):
    return JsonResponse({'applinks': {'apps': [], 'details': [{
        'appID': '42NW282TDP.dev.hugesilver.Roll-Pe',
        'paths': ['/api/user/password-reset/*'],
    }]}})


@require_safe
def android_asset_links(request):
    configured = getattr(settings, 'ANDROID_APP_LINKS_SHA256_FINGERPRINTS', [])
    # Reject the entire configuration if any fingerprint is malformed.
    valid = isinstance(configured, (list, tuple)) and configured and all(
        isinstance(value, str) and FINGERPRINT.fullmatch(value) for value in configured
    )
    statements = []
    if valid:
        statements = [{
            'relation': ['delegate_permission/common.handle_all_urls'],
            'target': {'namespace': 'android_app', 'package_name': 'dev.hugesilver.RollPe',
                       'sha256_cert_fingerprints': list(dict.fromkeys(value.upper() for value in configured))},
        }]
    return JsonResponse(statements, safe=False)
