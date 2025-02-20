from django.shortcuts import redirect

from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework_simplejwt.tokens import RefreshToken

from utils.env import return_env_value
from utils.response import Response
from utils.functions import create_idenfy_number
from .models import User

import jwt
from jwt.algorithms import RSAAlgorithm
import requests

# @api_view(['GET'])
@api_view(['POST'])
def social_login(request, provider):

    code = request.data.get('code')
    access = request.data.get('accessToken')
    # code = request.GET.get('code')
    
    match provider:

        case "kakao":
            
            user_instance = kakao_login(request, code, access)
        
        case "google":

            user_instance = google_login(request, code)
        
        case "apple":

            user_instance = apple_login(request, code, access)

    # user_instance로 토큰 발급
    tokens = get_tokens_for_user(user_instance)

    tokens["user"] = {
        "name": user_instance.name,
        "email": user_instance.email,
        "identifyCode": user_instance.identifyCode,
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

        call_back_url = f"http://localhost:8000/api/user/social/login/kakao"

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

    if created:
        user.set_unusable_password()  # 비밀번호 없이 로그인 불가하도록 설정
        identify_token = create_idenfy_number(request)
        user.identifyCode = identify_token
        user.provider = "kakao"
        user.save()
    
    return user

def google_login(request, code):

    return

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
    apple_id = decoded_token.get("sub")  # 애플 유저 고유 ID
    # apple_name = decoded_token.get("name")  # 애플 유저 고유 ID

    user, created = User.objects.get_or_create(
        email=user_email,
        defaults={'name': apple_id,'email':user_email}
    )

    if created:
        user.set_unusable_password()
        identify_token = create_idenfy_number(request)
        user.identifyCode = identify_token
        user.provider = "apple"
        user.save()

    return user

def get_apple_public_keys():
#     """애플의 공개 키를 가져오는 함수"""
    public_key_url = return_env_value("APPLE_PUBLIC_KEYS_URL")
    response = requests.get(public_key_url)

    if response.status_code != 200:
        return None
    
    return response.json().get("keys")

def decode_apple_identity_token(identity_token):
    """애플 JWT(identityToken) 검증"""
    try:
        # JWT Header에서 'kid' 가져오기
        headers = jwt.get_unverified_header(identity_token)
        kid = headers.get("kid")

        # 애플의 공개 키 가져오기
        apple_keys = get_apple_public_keys()
        if not apple_keys:
            return None

        # 'kid'와 일치하는 공개 키 찾기
        key = next((k for k in apple_keys if k["kid"] == kid), None)
        if not key:
            return None

        # 공개 키를 사용하여 JWT 검증
        public_key = RSAAlgorithm.from_jwk(key)
        decoded_token = jwt.decode(identity_token, public_key, algorithms=["RS256"])

        # 'aud' 값 검증 (내 서비스의 client_id와 일치하는지 확인)
        valid_client_ids = [return_env_value("APP_APPLE_BUNDEL_ID")]
        # valid_client_ids = [return_env_value("APPLE_PUBLIC_KEYS_URL"), return_env_value("APP_APPLE_BUNDEL_ID")]  # 웹 & iOS 지원
        if decoded_token.get("aud") not in valid_client_ids:
            return None  # 보안 문제! 인증 거부

        return decoded_token  # 검증 성공 시 사용자 정보 반환

    except jwt.ExpiredSignatureError:
        return None  # 토큰이 만료됨
    except jwt.InvalidTokenError:
        return None  # 유효하지 않은 토큰

class KakaoLoginView(APIView):
    def get(self, request):
        client_id = return_env_value("SOCIAL_AUTH_KAKAO_CLIENT_ID")
        redirect_uri = "http://localhost:8000/api/user/social/login/kakao"
        return redirect(
            f"https://kauth.kakao.com/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code"
        )
