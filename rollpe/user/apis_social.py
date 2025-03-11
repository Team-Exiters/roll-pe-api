from django.shortcuts import redirect
from django.conf import settings

from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework_simplejwt.tokens import RefreshToken

from utils.env import return_env_value
from utils.response import Response
from utils.functions import create_idenfy_number
from .models import User


from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

import jwt
from jwt import PyJWKClient
import requests

# @api_view(['GET'])
@api_view(['POST'])
def social_login(request, provider):

    code = request.data.get('code')
    access = request.data.get('accessToken')
    # code = request.GET.get('code')
    
    match provider:

        case "kakao":
            
            user_instance, created = kakao_login(request, code, access)
        
        case "google":

            user_instance, created = google_login(request, code, access)

        case "apple":

            user_instance, created = apple_login(request, code, access)

    if created:
        user_instance.set_unusable_password()  # 비밀번호 없이 로그인 불가하도록 설정
        identify_token = create_idenfy_number(request)
        user_instance.identifyCode = identify_token
        user_instance.provider = provider
        user_instance.save()
    else:
        if user_instance.provider != provider:
            return Response(msg="이미 다른 SNS로 가입된 이메일입니다.", status=400)

    # user_instance로 토큰 발급
    tokens = get_tokens_for_user(user_instance)

    tokens["user"] = {
        "id": user_instance.id,
        "name": user_instance.name,
        "email": user_instance.email,
        "identifyCode": user_instance.identifyCode,
        "provider": user_instance.provider
    }

    return Response(data=tokens, status=200)

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
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

    # web에서 넘어오는 인가코드 (web에서 ios로그인 구현시 추가 구현 필요)
    if code: 
        identity_token = code

    # app에서 넘어오는 identity_token
    else:
        identity_token = access

    # JWT 검증
    decoded_token = decode_apple_identity_token(identity_token)
    if not decoded_token:
        return Response(msg="유효하지 않는 Apple 토큰입니다.", status=400)
    
    user_email = decoded_token.get("email")  # 애플이 제공한 이메일
    # apple_id = decoded_token.get("sub")  # 애플 유저 고유 ID
    apple_name = request.data.get('name')  # 애플 유저 고유 ID

    user, created = User.objects.get_or_create(
        email=user_email,
        defaults={'name': apple_name,'email':user_email}
    )

    return user, created

def decode_apple_identity_token(identity_token):
    """애플 JWT(identityToken) 검증"""
    try:
        # JWT Header에서 'kid' 가져오기
        headers = jwt.get_unverified_header(identity_token)
        kid = headers.get("kid")

        # 애플의 공개 키 가져오기
        apple_keys_url = "https://appleid.apple.com/auth/keys"  # 애플 공개 키 URL
        jwks_client = PyJWKClient(apple_keys_url)

        # 'kid'와 일치하는 공개 키 찾기
        signing_key = jwks_client.get_signing_key(kid).key  # 공개 키 가져오기

        # JWT 검증 및 디코딩
        decoded_token = jwt.decode(identity_token, signing_key, algorithms=["RS256"], audience=return_env_value("APP_APPLE_BUNDEL_ID"))

        # 'aud' 값 검증 (내 서비스의 client_id와 일치하는지 확인)
        valid_client_ids = [return_env_value("APP_APPLE_BUNDEL_ID")]  # 여기에 애플 로그인에서 받은 클라이언트 ID를 설정
        if decoded_token.get("aud") not in valid_client_ids:
            print(f"Invalid audience: {decoded_token.get('aud')}")
            return None  # 보안 문제! 인증 거부

        return decoded_token  # 검증 성공 시 사용자 정보 반환
    except Exception as e:
        print(f"JWT 검증 실패: {e}")
        return Response(status=400)


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

