from django.shortcuts import redirect
from django.conf import settings

from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework_simplejwt.tokens import RefreshToken

from utils.env import return_env_value
from utils.response import Response
from utils.functions import create_idenfy_number
from .models import User
from django.db import transaction
from .apple_sessions import (
    AppleAuthenticationError, AppleUnavailable, apple_user, exchange_apple_code,
    save_credential, verify_identity_token,
)


from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

import requests

# @api_view(['GET'])
@api_view(['POST'])
def social_login(request, provider):

    code = request.data.get('code')
    access = request.data.get('accessToken')
    apple_credential = None
    # code = request.GET.get('code')
    
    match provider:

        case "kakao":
            
            user_instance, created = kakao_login(request, code, access)
        
        case "google":

            user_instance, created = google_login(request, code, access)

        case "apple":

            try:
                user_instance, created, apple_credential = apple_login(request, code, access)
            except AppleAuthenticationError as error:
                return Response(msg=str(error), status=400)
            except AppleUnavailable:
                return Response(msg='애플 인증 설정이나 서버 연결을 확인해주세요.', status=503)

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
        access_token = access
        
    user_kakao_account = requests.get(
        "https://kapi.kakao.com/v2/user/me",
        headers={"Authorization": f"Bearer {access_token}"},
    ).json()

    # user_kakao_account에서email 가져오기
    user_name = user_kakao_account['kakao_account']['profile']['nickname']
    user_email = user_kakao_account['kakao_account']['email']
    
    # 가져온 이메일로 사용자 생성 및 조회후 return user_instance 
    user, created = User.objects.get_or_create(
        email=user_email,
        defaults={'name': user_name,'email':user_email}
    )

    return user, created

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
        client_id = return_env_value("IOS_GOOGLE_OAUTH_CLIENT_KEY")
        decoded_token = id_token.verify_oauth2_token(google_id_token, google_requests.Request(), client_id)
        user_data = decoded_token

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

