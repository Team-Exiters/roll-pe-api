from django.shortcuts import redirect
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from functools import partial

from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework_simplejwt.tokens import RefreshToken

from utils.env import return_env_value
from utils.response import Response
from utils.functions import create_idenfy_number
from .models import User
from django.db import IntegrityError, transaction
from .apple_sessions import (
    AppleAuthenticationError, AppleUnavailable, apple_user, exchange_apple_code,
    save_credential, verify_identity_token,
)
from .social_browser import SocialAuthenticationError, kakao_profile, social_identity, verified_email


from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google.auth import exceptions as google_exceptions

import requests

# @api_view(['GET'])
@api_view(['POST'])
def social_login(request, provider):

    if provider not in ('google', 'kakao', 'apple'):
        return Response(msg='지원하지 않는 로그인 방식입니다.', status=404)

    code = request.data.get('code')
    access = request.data.get('accessToken')
    if ((code is not None and (not isinstance(code, str) or len(code) > 2048))
        or (access is not None and (not isinstance(access, str) or len(access) > 20000))
        or not (code or access)):
        return Response(msg='올바르지 않은 소셜 로그인 요청입니다.', status=400)
    apple_credential = None
    # code = request.GET.get('code')
    
    match provider:

        case "kakao":
            
            try:
                user_instance, created = kakao_login(request, code, access)
            except SocialAuthenticationError as error:
                return native_social_error(error)
            except ImproperlyConfigured:
                return Response(msg='카카오 로그인을 잠시 사용할 수 없습니다.', status=503)
            except IntegrityError:
                return Response(msg='로그인 요청이 겹쳤습니다. 다시 시도해주세요.', status=400)
        
        case "google":

            try:
                user_instance, created = google_login(request, code, access)
            except SocialAuthenticationError as error:
                return native_social_error(error)
            except (google_exceptions.TransportError, requests.RequestException, ImproperlyConfigured):
                return Response(msg='구글 인증 서버에 연결하지 못했습니다.', status=503)
            except (ValueError, google_exceptions.GoogleAuthError):
                return Response(msg='구글 인증 정보를 확인할 수 없습니다.', status=400)
            except IntegrityError:
                return Response(msg='로그인 요청이 겹쳤습니다. 다시 시도해주세요.', status=400)

        case "apple":

            try:
                user_instance, created, apple_credential = apple_login(request, code, access)
            except AppleAuthenticationError as error:
                return Response(msg=str(error), status=400)
            except AppleUnavailable:
                return Response(msg='애플 인증 설정이나 서버 연결을 확인해주세요.', status=503)

    if not user_instance.is_active:
        return Response(msg='로그인할 수 없는 계정입니다.', status=400)

    if created and provider != 'apple':
        user_instance.set_unusable_password()  # 비밀번호 없이 로그인 불가하도록 설정
        identify_token = create_idenfy_number(request)
        user_instance.identifyCode = identify_token
        user_instance.provider = provider
        user_instance.save()
    else:
        if user_instance.provider != provider:
            return Response(msg="이미 다른 SNS로 가입된 이메일입니다.", status=400)

    # user_instance로 토큰 발급
    tokens = get_tokens_for_user(user_instance, apple_credential=apple_credential)

    tokens["user"] = {
        "id": user_instance.id,
        "name": user_instance.name,
        "email": user_instance.email,
        "identifyCode": user_instance.identifyCode,
        "provider": user_instance.provider
    }

    return Response(data=tokens, status=200)


def native_social_error(error):
    messages = {
        'email_required': '로그인하려면 이메일 제공에 동의해주세요.',
        'account_conflict': '이미 다른 로그인 방식으로 가입된 이메일입니다.',
        'account_inactive': '로그인할 수 없는 계정입니다.',
    }
    return Response(msg=messages.get(error.code, '소셜 인증 정보를 확인할 수 없습니다.'), status=400)

def get_tokens_for_user(user, apple_credential=None):
    refresh = RefreshToken.for_user(user)
    if apple_credential is not None:
        refresh['apple_session'] = str(apple_credential.session_id)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

def kakao_login(request, code, access):

    if not access:
        client_id = return_env_value("SOCIAL_AUTH_KAKAO_CLIENT_ID")
        
        # call_back_url = f"https://dev.popping.world/api/user/social/login/kakao"
        call_back_url = f"{request.scheme}://{settings.BASE_DOMAIN}/oauth/callback/kakao"
        # call_back_url = f"http://localhost:8000/api/user/social/login/kakao"

        get_kakao_token = requests.post(
            "https://kauth.kakao.com/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "redirect_uri": call_back_url,
                "code": code
            },
        )
        kakao_token = get_kakao_token.json()

        access_token = kakao_token.get("access_token")
    else:
        return native_kakao_login(request, access)
        
    profile = kakao_profile(access_token)
    with transaction.atomic():
        identity = social_identity(request, 'kakao', profile)
        return identity.user, False


def native_kakao_login(request, access):
    # A native bearer token must belong to this Kakao app, not just any valid Kakao app.
    if not isinstance(access, str) or not access or len(access) > 8192:
        raise SocialAuthenticationError()
    configured_app = getattr(settings, 'KAKAO_AUTH_APP_ID', '')
    if not str(configured_app).isdecimal() or int(configured_app) <= 0:
        raise ImproperlyConfigured('Kakao app ID is not configured.')
    try:
        response = requests.get('https://kapi.kakao.com/v1/user/access_token_info',
                                headers={'Authorization': f'Bearer {access}'}, timeout=5,
                                allow_redirects=False)
        response.raise_for_status()
        info = response.json()
        if (response.status_code != 200 or not isinstance(info, dict)
            or type(info.get('app_id')) is not int or info['app_id'] != int(configured_app)
            or type(info.get('id')) is not int or info['id'] <= 0
            or type(info.get('expires_in')) is not int or info['expires_in'] <= 0):
            raise SocialAuthenticationError()
    except (requests.RequestException, ValueError, TypeError):
        raise SocialAuthenticationError() from None
    profile = kakao_profile(access)
    if profile['subject'] != str(info['id']):
        raise SocialAuthenticationError()
    with transaction.atomic():
        identity = social_identity(request, 'kakao', profile)
        return identity.user, False

def google_login(request, code, access):


    if code: 
        # 웹에서
        client_secret = return_env_value("GOOGLE_OAUTH_CLIENT_ID")
        state = return_env_value("GOOGLE_STATE")
        client_id = return_env_value("WEB_GOOGLE_OAUTH_CLIENT_KEY")

        # http://localhost:8000/api/user/social-google
        call_back_url = f"{request.scheme}://{settings.BASE_DOMAIN}/oauth/callback/google"
        # call_back_url = f"http://localhost:8000/api/user/social/login/google"

        get_google_token = requests.post(
            "https://oauth2.googleapis.com/token", 
            data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': call_back_url,
            'state': state
            }
        )
        access_token = get_google_token.json().get("access_token")

        user_data = requests.get(f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={access_token}")
        user_data = user_data.json()

    else:
        # 앱에서
        google_id_token = access
        if not isinstance(google_id_token, str) or not google_id_token or len(google_id_token) > 20000:
            raise SocialAuthenticationError()
        try:
            ios_client_id = return_env_value("IOS_GOOGLE_OAUTH_CLIENT_KEY")
        except ImproperlyConfigured:
            ios_client_id = ''
        # Android SDK requests tokens for our web client; original iOS clients keep their audience.
        client_ids = [value for value in (ios_client_id, getattr(settings, 'GOOGLE_AUTH_CLIENT_ID', '')) if value]
        if not client_ids:
            raise ImproperlyConfigured('Google client IDs are not configured.')
        claims = id_token.verify_oauth2_token(
            google_id_token, partial(google_requests.Request(), timeout=10), client_ids,
        )
        subject = claims.get('sub')
        if not isinstance(subject, str) or not 0 < len(subject) <= 255 or not subject.isascii():
            raise SocialAuthenticationError()
        profile = {
            'subject': subject,
            'email': verified_email(claims.get('email'),
                                    claims.get('email_verified') is True or claims.get('email_verified') == 'true'),
            'name': claims.get('name', ''),
        }
        with transaction.atomic():
            identity = social_identity(request, 'google', profile)
            return identity.user, False

    user_name = user_data.get('name')  # 사용자 이름은 'name' 필드에 있음
    user_email = user_data.get('email')  # 이메일은 'email' 필드에 있음

    # 가져온 이메일로 사용자 생성 및 조회후 return user_instance 
    user, created = User.objects.get_or_create(
        email=user_email,
        defaults={'name': user_name,'email':user_email}
    )

    return user, created

def apple_login(request, code, access):
    client_id = settings.APPLE_AUTH_NATIVE_CLIENT_ID
    if not client_id:
        raise AppleUnavailable('애플 앱 ID 설정을 확인해주세요.')
    nonce = request.data.get('nonce')
    if nonce is not None and not isinstance(nonce, str):
        raise AppleAuthenticationError('올바르지 않은 애플 로그인 요청입니다.')
    if code:
        claims, tokens = exchange_apple_code(code, nonce, client_id=client_id)
        if access:
            identity = verify_identity_token(access, client_id, nonce)
            if identity['sub'] != claims['sub']:
                raise AppleAuthenticationError('애플 사용자 식별자가 일치하지 않습니다.')
    elif access:
        claims = verify_identity_token(access, client_id, nonce)
        # Older iOS clients send only identityToken. They reauthenticate after 24 hours
        # and use Apple's documented manual unlink fallback on account deletion.
        tokens = {'id_token': access}
    else:
        raise AppleAuthenticationError('애플 인증 정보가 없습니다.')
    with transaction.atomic():
        user, created = apple_user(request, claims, request.data.get('name'))
        credential = save_credential(user, tokens, client_id)
    return user, created, credential


class KakaoLoginView(APIView):
    def get(self, request):
        client_id = return_env_value("SOCIAL_AUTH_KAKAO_CLIENT_ID")
        # redirect_uri = "http://localhost:8000/api/user/social/login/kakao"
        redirect_uri = f"{request.scheme}://{settings.BASE_DOMAIN}/oauth/callback/kakao"
        return redirect(
            f"https://kauth.kakao.com/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code"
        )

class GoogleLoginView(APIView):
    def get(self, request):
        client_id = return_env_value("WEB_GOOGLE_OAUTH_CLIENT_KEY")
        # 이메일과 프로필 정보를 요청하는 scope 설정
        scope = "https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"
        redirect_uri = "http://localhost:8000/api/user/social/login/google"
        return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?client_id={client_id}&response_type=code&redirect_uri={redirect_uri}&scope={scope}")

