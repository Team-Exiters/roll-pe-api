"""Apple credential verification, encrypted storage, and revocation."""

import json
import secrets
from datetime import timedelta
from pathlib import Path

import jwt
import requests
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.html import strip_tags
from jwt import PyJWKClient
from rest_framework.exceptions import APIException, AuthenticationFailed

from utils.functions import create_idenfy_number
from .models import AppleCredential, User

APPLE_ISSUER = 'https://appleid.apple.com'
apple_keys = PyJWKClient(f'{APPLE_ISSUER}/auth/keys')


class AppleAuthenticationError(ValueError):
    pass


class AppleUnavailable(APIException):
    status_code = 503
    default_detail = '애플 인증 서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.'
    default_code = 'apple_unavailable'


def token_cipher():
    try:
        keys = settings.APPLE_AUTH_TOKEN_ENCRYPTION_KEYS
        if not keys:
            raise ValueError()
        return MultiFernet([Fernet(key) for key in keys])
    except (ValueError, TypeError):
        raise AppleUnavailable('애플 토큰 암호화 설정을 확인해주세요.') from None


def stored_tokens(credential):
    try:
        tokens = json.loads(token_cipher().decrypt(credential.token_response.encode()).decode())
        if not isinstance(tokens, dict):
            raise ValueError()
        return tokens
    except (InvalidToken, ValueError, TypeError):
        raise AppleUnavailable('애플 인증 정보를 읽지 못했습니다.') from None


def encrypted_tokens(tokens):
    return token_cipher().encrypt(json.dumps(tokens).encode()).decode()


def create_client_secret(client_id=None):
    now = timezone.now()
    try:
        private_key = Path(settings.APPLE_AUTH_PRIVATE_KEY_FILE).read_text()
        return jwt.encode(
            {'iss': settings.APPLE_AUTH_TEAM_ID, 'iat': int(now.timestamp()),
             'exp': int((now + timedelta(minutes=5)).timestamp()),
             'aud': APPLE_ISSUER, 'sub': client_id or settings.APPLE_AUTH_CLIENT_ID},
            private_key, algorithm='ES256', headers={'kid': settings.APPLE_AUTH_KEY_ID},
        )
    except (OSError, ValueError, TypeError, jwt.PyJWTError):
        raise AppleUnavailable('애플 인증 키 설정을 확인해주세요.') from None


def verify_identity_token(token, client_id, nonce=None):
    if not client_id:
        raise AppleUnavailable('애플 클라이언트 설정을 확인해주세요.')
    try:
        key = apple_keys.get_signing_key_from_jwt(token).key
        required = ['exp', 'iat', 'sub', 'iss', 'aud'] + (['nonce'] if nonce is not None else [])
        claims = jwt.decode(token, key, algorithms=['RS256'], issuer=APPLE_ISSUER,
                            audience=client_id, options={'require': required})
    except jwt.PyJWKClientConnectionError:
        raise AppleUnavailable() from None
    except (jwt.PyJWTError, ValueError, TypeError):
        raise AppleAuthenticationError('유효하지 않은 애플 인증 정보입니다.') from None
    if not isinstance(claims['sub'], str) or not claims['sub'] or len(claims['sub']) > 255:
        raise AppleAuthenticationError('애플 사용자 식별자를 확인할 수 없습니다.')
    if nonce is not None and not secrets.compare_digest(str(claims['nonce']), nonce):
        raise AppleAuthenticationError('애플 로그인 요청이 일치하지 않습니다.')
    return claims


def exchange_apple_code(code, nonce, client_id=None, redirect_uri=None):
    client_id = client_id or settings.APPLE_AUTH_CLIENT_ID
    data = {'grant_type': 'authorization_code', 'code': code, 'client_id': client_id,
            'client_secret': create_client_secret(client_id)}
    if redirect_uri is not None:
        data['redirect_uri'] = redirect_uri
    try:
        response = requests.post(f'{APPLE_ISSUER}/auth/token', data=data, timeout=10)
        response.raise_for_status()
        tokens = response.json()
        if not isinstance(tokens, dict):
            raise ValueError()
        if not isinstance(tokens.get('refresh_token'), str) or not tokens['refresh_token']:
            raise ValueError()
        claims = verify_identity_token(tokens['id_token'], client_id, nonce)
    except (requests.RequestException, KeyError, ValueError, TypeError):
        raise AppleAuthenticationError('애플 인증 코드를 확인하지 못했습니다.') from None
    return claims, tokens


def apple_user(request, claims, name=''):
    """Bind verified sub first; bind a legacy Apple email account only once."""
    subject = claims['sub']
    email = claims.get('email')
    if not (isinstance(email, str) and email and claims.get('email_verified') in (True, 'true')):
        email = None
    name = strip_tags(name if isinstance(name, str) else '').strip()
    name = (name or (email.split('@')[0] if email else 'Apple 사용자'))[:25]
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().filter(apple_subject=subject).first()
            created = False
            if user is None and email:
                user = User.objects.select_for_update().filter(email=email).first()
                if user and (user.provider != 'apple' or user.apple_subject):
                    raise AppleAuthenticationError('이미 다른 계정에 연결된 이메일입니다.')
            if user is None:
                user, created = User.objects.get_or_create(
                    apple_subject=subject, defaults={'email': email, 'name': name, 'provider': 'apple'},
                )
            if user.provider != 'apple' or not user.is_active:
                raise AppleAuthenticationError('로그인할 수 없는 계정입니다.')
            if not user.apple_subject:
                user.apple_subject = subject
                user.save(update_fields=['apple_subject'])
            if created:
                user.set_unusable_password()
                user.identifyCode = create_idenfy_number(request)
                user.save(update_fields=['password', 'identifyCode'])
    except IntegrityError:
        raise AppleAuthenticationError('애플 계정 연결을 확인해주세요.') from None
    return user, created


def save_credential(user, tokens, client_id):
    return AppleCredential.objects.create(
        user=user, client_id=client_id, token_response=encrypted_tokens(tokens), verified_at=timezone.now(),
    )


def credential_for_token(user, token):
    session_id = token.get('apple_session')
    if session_id is None:
        if user.provider == 'apple' and user.apple_subject:
            raise AuthenticationFailed('애플 로그인을 다시 진행해주세요.')
        return None  # Existing, not-yet-migrated native accounts retain their old session contract.
    try:
        credential = AppleCredential.objects.get(user=user, session_id=session_id)
    except (AppleCredential.DoesNotExist, ValidationError, ValueError, TypeError):
        raise AuthenticationFailed('유효하지 않은 로그인 세션입니다.') from None
    if user.provider != 'apple' or credential.invalidated_at or credential.apple_revoked_at:
        raise AuthenticationFailed('종료된 로그인 세션입니다. 다시 로그인해주세요.')
    return credential


def validate_apple_session(credential):
    """Validate with Apple on app-token refresh, at most one attempt per day per grant."""
    failure = None
    with transaction.atomic():
        try:
            user = User.objects.select_for_update().get(pk=credential.user_id)
            credential = AppleCredential.objects.select_for_update().get(pk=credential.pk, user=user)
        except (User.DoesNotExist, AppleCredential.DoesNotExist):
            raise AuthenticationFailed('종료된 로그인 세션입니다.') from None
        now = timezone.now()
        if credential.invalidated_at or credential.apple_revoked_at:
            raise AuthenticationFailed('애플 로그인을 다시 진행해주세요.')
        if credential.verified_at > now - timedelta(days=1):
            return
        tokens = stored_tokens(credential)
        refresh = tokens.get('refresh_token')
        if not refresh:
            failure = AuthenticationFailed('애플 로그인을 다시 진행해주세요.')
            credential.invalidated_at = now
        elif credential.checked_at and credential.checked_at > now - timedelta(days=1):
            raise AppleUnavailable('애플 계정 상태를 확인하지 못했습니다. 다시 로그인해주세요.')
        else:
            credential.checked_at = now
            try:
                response = requests.post(f'{APPLE_ISSUER}/auth/token', data={
                    'grant_type': 'refresh_token', 'refresh_token': refresh,
                    'client_id': credential.client_id,
                    'client_secret': create_client_secret(credential.client_id),
                }, timeout=10)
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError()
                if response.status_code == 400 and payload.get('error') == 'invalid_grant':
                    credential.invalidated_at = now
                    credential.apple_revoked_at = now
                    credential.token_response = encrypted_tokens({})
                    failure = AuthenticationFailed('애플 계정 연결이 해제되었습니다. 다시 로그인해주세요.')
                else:
                    response.raise_for_status()
                    if not payload.get('access_token'):
                        raise ValueError()
                    if payload.get('id_token'):
                        claims = verify_identity_token(payload['id_token'], credential.client_id)
                        if claims['sub'] != user.apple_subject:
                            raise AppleAuthenticationError('애플 사용자 식별자가 일치하지 않습니다.')
                    tokens.update(payload)
                    credential.token_response = encrypted_tokens(tokens)
                    credential.verified_at = now
            except AppleAuthenticationError:
                credential.invalidated_at = now
                failure = AuthenticationFailed('애플 로그인을 다시 진행해주세요.')
            except (requests.RequestException, ValueError, TypeError, AppleUnavailable):
                failure = AppleUnavailable()
        credential.save(update_fields=[
            'checked_at', 'verified_at', 'invalidated_at', 'apple_revoked_at', 'token_response',
        ])
    # Raise after commit so a revoked credential cannot be revived by transaction rollback.
    if failure:
        raise failure


def revoke_apple_credentials(user):
    """Return whether legacy credentials need the documented manual unlink fallback."""
    credentials = list(user.apple_credentials.select_for_update().all())
    manual_unlink = user.provider == 'apple' and not credentials
    for credential in credentials:
        if credential.apple_revoked_at:
            continue
        token = stored_tokens(credential).get('refresh_token')
        if not token:
            manual_unlink = True
            continue
        try:
            response = requests.post(f'{APPLE_ISSUER}/auth/revoke', data={
                'client_id': credential.client_id, 'client_secret': create_client_secret(credential.client_id),
                'token': token, 'token_type_hint': 'refresh_token',
            }, timeout=10)
            response.raise_for_status()
        except requests.RequestException:
            raise AppleUnavailable('애플 연결을 해제하지 못했습니다. 잠시 후 다시 시도해주세요.') from None
        credential.apple_revoked_at = timezone.now()
        credential.invalidated_at = credential.apple_revoked_at
        credential.token_response = encrypted_tokens({})
        credential.save(update_fields=['apple_revoked_at', 'invalidated_at', 'token_response'])
    return manual_unlink
