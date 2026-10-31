"""Public, read-only policy pages backed by the same documents as the app API."""

import secrets

from django.shortcuts import render
from django.views.decorators.http import require_safe

from utils.functions import PRIVACY


@require_safe
def privacy_policy(request):
    nonce = secrets.token_urlsafe(24)
    response = render(request, 'privacy_policy.html', {
        'policy_html': PRIVACY, 'csp_nonce': nonce,
    })
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Frame-Options'] = 'DENY'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = (
        f"default-src 'none'; style-src 'nonce-{nonce}'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    return response
