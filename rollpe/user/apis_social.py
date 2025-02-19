from django.shortcuts import redirect

from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework_simplejwt.tokens import RefreshToken

from utils.env import return_env_value
from utils.response import Response
from utils.functions import create_idenfy_number
from .models import User

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

            user_instance = google_login(request,code)

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

class KakaoLoginView(APIView):
    def get(self, request):
        client_id = return_env_value("SOCIAL_AUTH_KAKAO_CLIENT_ID")
        redirect_uri = "http://localhost:8000/api/user/social/login/kakao"
        return redirect(
            f"https://kauth.kakao.com/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code"
        )