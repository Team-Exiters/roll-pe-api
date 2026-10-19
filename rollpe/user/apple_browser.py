"""Apple browser authorization, callback, and one-time PKCE exchange."""

import base64
import hashlib
import json
import logging
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from utils.response import Response
from .apple_sessions import (
    APPLE_ISSUER, AppleAuthenticationError, AppleUnavailable, apple_user,
    exchange_apple_code, save_credential, token_cipher,
)
from .models import AppleAuthFlow, AppleCredential, User

logger = logging.getLogger(__name__)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def pkce_challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def no_store(response):
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


def client_redirect(flow, **params):
    response = HttpResponse(status=302)
    # return_url was matched against the exact configured allowlist at start.
    response['Location'] = f'{flow.return_url}?{urlencode({**params, "state": flow.client_state})}'
    return no_store(response)


@require_GET
def apple_start(request):
    return_url = request.GET.get('return_url', '')
    challenge = request.GET.get('code_challenge', '')
    client_state = request.GET.get('state', '')
    if (
        return_url not in settings.APPLE_AUTH_RETURN_URLS
        or not re.fullmatch(r'[A-Za-z0-9_-]{43}', challenge)
        or not re.fullmatch(r'[A-Za-z0-9_-]{32,64}', client_state)
    ):
        return no_store(Response(status=400, msg='올바르지 않은 애플 로그인 요청입니다.'))
    if not all((
        settings.APPLE_AUTH_CLIENT_ID, settings.APPLE_AUTH_TEAM_ID,
        settings.APPLE_AUTH_KEY_ID, settings.APPLE_AUTH_PRIVATE_KEY_FILE,
        settings.APPLE_AUTH_REDIRECT_URI,
    )):
        return no_store(Response(status=503, msg='애플 로그인 설정이 완료되지 않았습니다.'))
    try:
        token_cipher()
    except AppleUnavailable:
        return no_store(Response(status=503, msg='애플 토큰 암호화 설정이 완료되지 않았습니다.'))

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    AppleAuthFlow.objects.create(
        state_hash=digest(state), nonce=nonce, client_state=client_state,
        code_challenge=challenge, return_url=return_url,
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    params = {
        "client_id": settings.APPLE_AUTH_CLIENT_ID,
        "redirect_uri": settings.APPLE_AUTH_REDIRECT_URI,
        "response_type": "code", "response_mode": "form_post",
        "scope": "name email", "state": state, "nonce": nonce,
    }
    response = HttpResponse(status=302)
    response['Location'] = f'{APPLE_ISSUER}/auth/authorize?{urlencode(params)}'
    return no_store(response)


# Apple posts from its own origin; this single callback uses one-time state instead of a CSRF cookie.
@csrf_exempt
@require_POST
def apple_callback(request):
    state = request.POST.get('state', '')
    if not state or len(state) > 128:
        return no_store(Response(status=400, msg='인증 요청을 확인할 수 없습니다.'))
    flow = AppleAuthFlow.objects.filter(state_hash=digest(state)).first()
    if not flow:
        return no_store(Response(status=400, msg='인증 요청을 확인할 수 없습니다.'))
    claimed = AppleAuthFlow.objects.filter(
        pk=flow.pk, status='pending', expires_at__gt=timezone.now(),
    ).update(status='processing')
    if not claimed:
        return no_store(Response(status=400, msg='만료되었거나 이미 사용한 인증 요청입니다.'))

    if request.POST.get('error'):
        flow.status = 'failed'
        flow.save(update_fields=['status'])
        error = 'cancelled' if request.POST['error'] == 'user_cancelled_authorize' else 'authentication_failed'
        return client_redirect(flow, error=error)
    code = request.POST.get('code', '')
    if not code or len(code) > 2048:
        flow.status = 'failed'
        flow.save(update_fields=['status'])
        return client_redirect(flow, error='authentication_failed')

    try:
        profile = json.loads(request.POST.get('user', '{}'))
        parts = profile.get('name', {})
        name = ''.join(str(parts.get(key, '')) for key in ('lastName', 'firstName'))
    except (ValueError, TypeError, AttributeError):
        name = ''
    try:
        claims, tokens = exchange_apple_code(
            code, flow.nonce, redirect_uri=settings.APPLE_AUTH_REDIRECT_URI,
        )
        with transaction.atomic():
            user, _ = apple_user(request, claims, name)
            credential = save_credential(user, tokens, settings.APPLE_AUTH_CLIENT_ID)
            exchange_code = secrets.token_urlsafe(32)
            flow.user = user
            flow.credential = credential
            flow.exchange_hash = digest(exchange_code)
            flow.status = 'complete'
            flow.expires_at = timezone.now() + timedelta(seconds=60)
            flow.save(update_fields=['user', 'credential', 'exchange_hash', 'status', 'expires_at'])
    except (AppleAuthenticationError, AppleUnavailable):
        # Do not log authorization codes, tokens, or profile data.
        logger.warning('Apple browser authentication failed')
        flow.status = 'failed'
        flow.save(update_fields=['status'])
        return client_redirect(flow, error='authentication_failed')

    return client_redirect(flow, code=exchange_code)


@csrf_exempt
@require_POST
def apple_exchange(request):
    try:
        data = json.loads(request.body)
        code = data.get('code', '')
        verifier = data.get('code_verifier', '')
        if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', code):
            raise ValueError()
        if not isinstance(verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return no_store(Response(status=400, msg='올바르지 않은 로그인 요청입니다.'))

    with transaction.atomic():
        flow = AppleAuthFlow.objects.filter(
            exchange_hash=digest(code), status='complete', expires_at__gt=timezone.now(),
        ).first()
        if not flow or not secrets.compare_digest(flow.code_challenge, pkce_challenge(verifier)):
            return no_store(Response(status=400, msg='만료되었거나 올바르지 않은 로그인 요청입니다.'))
        # Use the same user -> credential lock order as refresh/logout/deletion.
        user = User.objects.select_for_update().filter(pk=flow.user_id).first()
        if not user or not user.is_active or user.provider != 'apple':
            return no_store(Response(status=400, msg='로그인할 수 없는 계정입니다.'))
        credential = AppleCredential.objects.filter(pk=flow.credential_id, user=user).first()
        if not credential or credential.invalidated_at or credential.apple_revoked_at:
            return no_store(Response(status=400, msg='종료된 로그인 세션입니다.'))
        claimed = AppleAuthFlow.objects.filter(
            pk=flow.pk, status='complete', expires_at__gt=timezone.now(),
        ).update(status='consumed')
        if not claimed:
            return no_store(Response(status=400, msg='만료되었거나 이미 사용한 로그인 요청입니다.'))
        from .apis_social import get_tokens_for_user
        tokens = get_tokens_for_user(user, apple_credential=credential)
        tokens['user'] = {
            'id': user.id, 'name': user.name, 'email': user.email,
            'identifyCode': user.identifyCode, 'provider': user.provider,
        }
    return no_store(Response(status=200, data=tokens))
