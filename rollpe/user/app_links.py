"""Public association metadata; no database or authentication dependencies."""
import re
import secrets

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

FINGERPRINT = re.compile(r'(?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}\Z')


@require_safe
def apple_app_site_association(request):
    return JsonResponse({'applinks': {'apps': [], 'details': [{
        'appID': '42NW282TDP.dev.hugesilver.Roll-Pe',
        'paths': ['/api/user/password-reset/*', '/rollpe/*'],
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


@require_safe
def rollpe_invitation_page(request, code):
    """Browser fallback only; opening a link never reads or joins a paper."""
    nonce = secrets.token_urlsafe(24)
    response = render(request, 'rollpe_invitation.html', {
        'app_url': f'rollpe://rollpe/{code}', 'csp_nonce': nonce,
    })
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Frame-Options'] = 'DENY'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = (
        f"default-src 'none'; style-src 'nonce-{nonce}'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    return response
