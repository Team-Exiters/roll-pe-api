"""Google/Kakao browser authorization; provider secrets and tokens stay on the server."""

import json
import logging
import re
import secrets
from datetime import timedelta
from functools import partial
from urllib.parse import urlencode, urlsplit

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from utils.functions import create_idenfy_number
from utils.response import Response
from .oauth_utils import digest, no_store, pkce_challenge
from .models import SocialAuthFlow, SocialIdentity, User

logger = logging.getLogger(__name__)
PROVIDERS = {
    'google': ('https://accounts.google.com/o/oauth2/v2/auth', 'https://oauth2.googleapis.com/token'),
    'kakao': ('https://kauth.kakao.com/oauth/authorize', 'https://kauth.kakao.com/oauth/token'),
}


class SocialAuthenticationError(ValueError):
    def __init__(self, code='authentication_failed'):
        self.code = code
        super().__init__(code)


def provider_settings(provider):
    prefix = provider.upper() + '_AUTH_'
    return {key: getattr(settings, prefix + key, '') for key in (
        'CLIENT_ID', 'CLIENT_SECRET', 'REDIRECT_URI', 'RETURN_URLS',
    )}


def valid_return_url(value, allowed):
    if not value or len(value) > 512 or value not in allowed:
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return bool(parts.scheme and parts.netloc and not parts.query and not parts.fragment
                and not parts.username and not parts.password)


def client_redirect(flow, **params):
    response = HttpResponse(status=302)
    response['Location'] = f'{flow.return_url}?{urlencode({**params, "state": flow.client_state})}'
    return no_store(response)


@require_GET
def social_start(request, provider):
    if provider not in PROVIDERS:
        return no_store(Response(status=404, msg='지원하지 않는 로그인 방식입니다.'))
    config = provider_settings(provider)
    return_url = request.GET.get('return_url', '')
    challenge = request.GET.get('code_challenge', '')
    client_state = request.GET.get('state', '')
    if (any(len(request.GET.getlist(key)) != 1 for key in ('return_url', 'code_challenge', 'state'))
        or not valid_return_url(return_url, config['RETURN_URLS'])
        or not re.fullmatch(r'[A-Za-z0-9_-]{43}', challenge)
        or not re.fullmatch(r'[A-Za-z0-9_-]{32,64}', client_state)):
        return no_store(Response(status=400, msg='올바르지 않은 소셜 로그인 요청입니다.'))
    required = ('CLIENT_ID', 'REDIRECT_URI', 'CLIENT_SECRET') if provider == 'google' else ('CLIENT_ID', 'REDIRECT_URI')
    if not all(config[key] for key in required):
        return no_store(Response(status=503, msg='소셜 로그인 서버 설정이 완료되지 않았습니다.'))

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    SocialAuthFlow.objects.create(
        provider=provider, state_hash=digest(state), nonce=nonce, provider_verifier=verifier,
        client_state=client_state, code_challenge=challenge, return_url=return_url,
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    params = {
        'client_id': config['CLIENT_ID'], 'redirect_uri': config['REDIRECT_URI'],
        'response_type': 'code', 'state': state,
        'code_challenge': pkce_challenge(verifier), 'code_challenge_method': 'S256',
    }
    if provider == 'google':
        params.update(scope='openid email profile', nonce=nonce)
    response = HttpResponse(status=302)
    response['Location'] = f'{PROVIDERS[provider][0]}?{urlencode(params)}'
    return no_store(response)


def verified_email(value, verified):
    if verified is not True or not isinstance(value, str) or len(value) > 254:
        return None
    try:
        validate_email(value)
    except ValidationError:
        return None
    return User.objects.normalize_email(value)


def google_profile(token, client_id, nonce):
    if not isinstance(token, str) or not token:
        raise SocialAuthenticationError()
    try:
        claims = id_token.verify_oauth2_token(token, partial(google_requests.Request(), timeout=10), client_id)
    except (ValueError, google_exceptions.GoogleAuthError):
        raise SocialAuthenticationError() from None
    if (not isinstance(claims, dict)
        or not isinstance(claims.get('nonce'), str)
        or not claims['nonce'].isascii()
        or not secrets.compare_digest(claims['nonce'], nonce)
        or not isinstance(claims.get('sub'), str) or not 0 < len(claims['sub']) <= 255
        or not claims['sub'].isascii()
        or (claims.get('azp') is not None and claims['azp'] != client_id)):
        raise SocialAuthenticationError()
    return {
        'subject': claims['sub'],
        'email': verified_email(claims.get('email'),
                                claims.get('email_verified') is True or claims.get('email_verified') == 'true'),
        'name': claims.get('name', ''),
    }


def kakao_profile(access):
    if not isinstance(access, str) or not access or len(access) > 8192:
        raise SocialAuthenticationError()
    try:
        response = requests.get('https://kapi.kakao.com/v2/user/me',
                                headers={'Authorization': f'Bearer {access}'}, timeout=10,
                                allow_redirects=False)
        response.raise_for_status()
        profile = response.json()
        if not isinstance(profile, dict) or response.status_code != 200:
            raise SocialAuthenticationError()
        subject = profile.get('id')
        if type(subject) is not int or subject <= 0 or len(str(subject)) > 255:
            raise SocialAuthenticationError()
        account = profile.get('kakao_account') or {}
        name = (account.get('profile') or {}).get('nickname', '')
        email = verified_email(account.get('email'), account.get('is_email_verified'))
        if account.get('is_email_valid') is not True:
            email = None
        return {'subject': str(subject), 'email': email, 'name': name}
    except (requests.RequestException, ValueError, TypeError, AttributeError, KeyError):
        raise SocialAuthenticationError() from None


def exchange_provider_code(provider, code, flow):
    config = provider_settings(provider)
    data = {
        'grant_type': 'authorization_code', 'client_id': config['CLIENT_ID'],
        'redirect_uri': config['REDIRECT_URI'], 'code': code,
        'code_verifier': flow.provider_verifier,
    }
    if config['CLIENT_SECRET']:
        data['client_secret'] = config['CLIENT_SECRET']
    try:
        response = requests.post(PROVIDERS[provider][1], data=data, timeout=10, allow_redirects=False)
        response.raise_for_status()
        tokens = response.json()
        if not isinstance(tokens, dict) or tokens.get('error') or response.status_code != 200:
            raise SocialAuthenticationError()
        if provider == 'google':
            return google_profile(tokens.get('id_token'), config['CLIENT_ID'], flow.nonce)

        return kakao_profile(tokens.get('access_token'))
    except (requests.RequestException, ValueError, TypeError, AttributeError, KeyError):
        raise SocialAuthenticationError() from None


def social_identity(request, provider, profile):
    # Hash the case-sensitive subject before lookup; MySQL's default text collation may ignore case.
    subject_hash = digest(profile['subject'])
    identity = SocialIdentity.objects.filter(provider=provider, subject_hash=subject_hash).first()
    if identity:
        user = User.objects.select_for_update().filter(pk=identity.user_id).first()
        if not user or not user.is_active or user.provider != provider:
            raise SocialAuthenticationError('account_inactive')
        return identity
    email = profile['email']
    if not email:
        raise SocialAuthenticationError('email_required')
    user = User.objects.select_for_update().filter(email__iexact=email).first()
    if user:
        if user.provider != provider or SocialIdentity.objects.filter(user=user, provider=provider).exists():
            raise SocialAuthenticationError('account_conflict')
        if not user.is_active:
            raise SocialAuthenticationError('account_inactive')
    else:
        name = profile.get('name')
        name = strip_tags(name if isinstance(name, str) else '').strip()
        user = User(name=(name or email.split('@')[0])[:25], email=email, provider=provider,
                    identifyCode=create_idenfy_number(request))
        user.set_unusable_password()
        user.save()
    return SocialIdentity.objects.create(provider=provider, subject=profile['subject'],
                                         subject_hash=subject_hash, user=user)


@require_GET
def social_callback(request, provider):
    if provider not in PROVIDERS:
        return no_store(Response(status=404, msg='지원하지 않는 로그인 방식입니다.'))
    state = request.GET.get('state', '')
    if len(request.GET.getlist('state')) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]{43}', state):
        return no_store(Response(status=400, msg='인증 요청을 확인할 수 없습니다.'))
    flow = SocialAuthFlow.objects.filter(provider=provider, state_hash=digest(state)).first()
    if not flow or not SocialAuthFlow.objects.filter(
        pk=flow.pk, status='pending', expires_at__gt=timezone.now(),
    ).update(status='processing'):
        return no_store(Response(status=400, msg='만료되었거나 이미 사용한 인증 요청입니다.'))

    error = request.GET.get('error')
    code = request.GET.get('code', '')
    valid_code = isinstance(code, str) and 0 < len(code) <= 2048
    if error or not valid_code or len(request.GET.getlist('code')) != 1:
        SocialAuthFlow.objects.filter(pk=flow.pk).update(status='failed', provider_verifier='')
        return client_redirect(flow, error='cancelled' if error == 'access_denied' else 'authentication_failed')
    try:
        profile = exchange_provider_code(provider, code, flow)
        with transaction.atomic():
            identity = social_identity(request, provider, profile)
            exchange_code = secrets.token_urlsafe(32)
            flow.identity = identity
            flow.exchange_hash = digest(exchange_code)
            flow.status = 'complete'
            flow.provider_verifier = ''
            flow.expires_at = timezone.now() + timedelta(seconds=60)
            flow.save(update_fields=['identity', 'exchange_hash', 'status', 'provider_verifier', 'expires_at'])
    except (SocialAuthenticationError, IntegrityError) as error:
        logger.warning('%s browser authentication failed', provider)
        SocialAuthFlow.objects.filter(pk=flow.pk).update(status='failed', provider_verifier='')
        return client_redirect(flow, error=error.code if isinstance(error, SocialAuthenticationError) else 'authentication_failed')
    return client_redirect(flow, code=exchange_code)


@csrf_exempt
@require_POST
def social_exchange(request, provider):
    if provider not in PROVIDERS:
        return no_store(Response(status=404, msg='지원하지 않는 로그인 방식입니다.'))
    try:
        data = json.loads(request.body)
        code, verifier = data.get('code', ''), data.get('code_verifier', '')
        if (not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', code)
            or not isinstance(verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier)):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return no_store(Response(status=400, msg='올바르지 않은 로그인 요청입니다.'))
    with transaction.atomic():
        flow = SocialAuthFlow.objects.select_related('identity').filter(
            provider=provider, exchange_hash=digest(code), status='complete', expires_at__gt=timezone.now(),
        ).first()
        if not flow or not flow.identity or not secrets.compare_digest(flow.code_challenge, pkce_challenge(verifier)):
            return no_store(Response(status=400, msg='만료되었거나 올바르지 않은 로그인 요청입니다.'))
        user = User.objects.select_for_update().filter(pk=flow.identity.user_id).first()
        if (not user or not user.is_active or user.provider != provider
            or not SocialIdentity.objects.filter(pk=flow.identity_id, provider=provider, user=user).exists()):
            return no_store(Response(status=400, msg='로그인할 수 없는 계정입니다.'))
        if not SocialAuthFlow.objects.filter(pk=flow.pk, status='complete', expires_at__gt=timezone.now()).update(status='consumed'):
            return no_store(Response(status=400, msg='만료되었거나 이미 사용한 로그인 요청입니다.'))
        from .apis_social import get_tokens_for_user
        tokens = get_tokens_for_user(user)
        tokens['user'] = {
            'id': user.id, 'name': user.name, 'email': user.email,
            'identifyCode': user.identifyCode, 'provider': user.provider,
        }
    return no_store(Response(status=200, data=tokens))
