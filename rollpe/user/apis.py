from django.core.handlers.asgi import ASGIRequest
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.views import APIView
from rest_framework import permissions

from django.db.models import Q
from django.shortcuts import redirect, get_object_or_404
from django.conf import settings
from django.contrib.auth.hashers import check_password

from utils.response import Response
from utils.functions import verify_email_token, generate_send_email, create_idenfy_number

from user.serializers import UserSerializer, CustomTokenObtainPairSerializer, UserViewSerializer
from user.models import User

from paper.models import Paper

class CustomTokenObtainPairAPI(TokenObtainPairView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):

        serializer = CustomTokenObtainPairSerializer(data=request.data)

        if serializer.is_valid():
            response_data = serializer.validated_data
            
            return response_data  # Response 내부에서 반환된 값을 그대로 전달
        else:
            # 실패 시 errors 반환
            return Response(data=serializer.errors, status=400)
        

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_api(request):
    refresh_token = request.data.get("refresh")

    if not refresh_token:
        return Response(msg="Refresh token이 없습니다.", status=403)

    try:
        token = RefreshToken(refresh_token)
        token.blacklist()  
    except TokenError as e:
        return Response(msg="유효한 Refresh Token이 아닙니다. ", status=403)

    return Response(msg="로그아웃 되었습니다.", status=200)


@api_view(['POST'])
@permission_classes([AllowAny])
def signup_api(request):
    email = request.data.get("email")

    if User.objects.filter(email=email).exists():
        return Response(msg="이미 가입된 이메일입니다.", status=400)

    serializer = UserSerializer(data=request.data)
    if serializer.is_valid():
        try:
            user = serializer.create(serializer.validated_data)
            
            # 이메일 전송 시도 및 결과 확인
            email_response = generate_send_email(request, user.email, path_code="email")
            if isinstance(email_response, Response) and email_response.status_code != 200:
                # 이메일 전송 실패 시 생성된 사용자 삭제
                user.delete()
                return email_response

            return Response(msg="회원가입이 완료되었습니다. 이메일을 확인해주세요.", status=201)
        
        except Exception as e:
            return Response(msg=f"회원가입 처리 중 오류가 발생했습니다: {str(e)}", status=400)
    else:
        return Response(msg=serializer.errors, status=400)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def drop_user_data(request):

    identify_code = request.data.get("identifyCode")
    refresh_token = request.data.get("refresh")

    if not identify_code:
        return Response(msg="식별 코드가 없습니다.", status=400)

    if not refresh_token:
        return Response(msg="Refresh token이 없습니다.", status=403)
    
    if request.user.identifyCode != identify_code:
        return Response(msg="잘못된 접근입니다.", status=400)

    try:
        token = RefreshToken(refresh_token)
        token.blacklist()  
    except TokenError as e:
        return Response(msg="유효한 Refresh Token이 아닙니다. ", status=403)

    User.objects.filter(pk=request.user.id).delete()

    return Response(msg="회원 탈퇴 되었습니다.", status=200)

### 예정 : 추후 이메일 인증 완료 페이지 redirect ###
# 회원가입 이메일 인증시 
# 비밀번호 찾기 이메일 인증시
class VerifyEmailAPI(APIView):


    permission_classes = [permissions.AllowAny]
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'success_email_auth.html'

    def get(self, request):
        from rest_framework.response import Response as djangoResponse

        token = request.GET.get("token")
        path_code = request.GET.get("path_code")

        if not token:
            return Response(msg="토큰이 필요합니다.", status=400)

        try:
            payload = verify_email_token(token)
            user_email = payload["email"]

            # 이메일 인증 완료 처리

            match path_code:

                case "email":
                    user = get_object_or_404(User, email=user_email)
                    identify_code = create_idenfy_number(request)
                    user.is_active = True
                    user.identifyCode = identify_code
                    user.save()
                    
                case "password":
                    
                    pass

            # return redirect(redirect_url)
            return djangoResponse({"msg": "이메일 인증이 완료되었습니다."})
        
        except ValueError as e:
            # return Response(msg=str(e), status=400)
            return djangoResponse({"msg": str(e)})
    
    def patch(self, request):
        email = request.data["email"]

        path_code = request.data["pathCode"]
        generate_send_email(request, email, path_code=path_code)
        return Response(msg="인증 이메일을 재 전송하였습니다.", status=200)

class ForgotPasswordAPI(APIView):

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data['email']

        user_query = User.objects.filter(email=email)

        if not user_query.exists():
            return Response(msg="회원가입되지 않은 이메일입니다.", status=400)
        
        provider = user_query.values_list('provider',flat=True).first()
        if provider is not None:
            return Response(msg=f"{provider}로 회원가입된 이메일입니다. {provider}에서 비밀번호 찾기를 진행해주세요.", status=400)
        
        generate_send_email(request, email, path_code="password")
        return Response(msg="비밀번호 변경 이메일이 전송되었습니다.", status=200)

    def patch(self, request):

        identify_code = request.data['identifyCode']
        new_password = request.data['newPassword']

        user = User.objects.get(identifyCode=identify_code)
        
        user.set_password(new_password)
        user.save()

        return Response(msg="비밀번호 변경이 완료되었습니다. 다시 로그인해주세요.", status=200)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def myid_in_invate_rollpe_api(request):
    user = request.user

    # invitingUser에 현재 사용자(user)가 포함된 Papers 조회
    papers = Paper.objects.filter(invitingUser=user).distinct()
    
    data = {
        "count": papers.count(),
        "papers": [
            {
                "id": paper.id,
                "title": paper.title,
                "description": paper.description,
                "receivingDate": paper.receivingDate,
            }
            for paper in papers
        ]
    }
    
    return Response(data=data, status=200)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def receiver_is_me_api(request):
    user = request.user
        
    # receiverFK_id가 현재 사용자(user)의 ID인 Papers 조회
    papers = Paper.objects.filter(receiverFK=user).distinct()
    
    data = {
        "count": papers.count(),
        "papers": [
            {
                "id": paper.id,
                "title": paper.title,
                "description": paper.description,
                "receivingDate": paper.receivingDate,
            }
            for paper in papers
        ]
    }
    
    return Response(data=data, status=200)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_user_name(request):

    paginator = PageNumberPagination()

    user_name_code = request.GET.get("nameCode")

    users = User.objects.filter(Q(name__icontains=user_name_code) | Q(provider__icontains=user_name_code))
    if not users:
        return Response(msg="사용자를 찾을 수 없습니다.",status=404)
    
    page = paginator.paginate_queryset(users, request)
    serializer = UserViewSerializer(page, many=True)
    data = paginator.get_paginated_response(serializer.data).data
    
    return Response(data=data,status=200)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def user_password_check(request):
    password = request.data.get("password", None)
    user = request.user

    if user.is_anonymous:
        return Response(status=401)

    if password is None:
        return Response(status=400, msg="패스워드가 없습니다.")

    if user.check_password(password):

        return Response(status=200)
    else:
        return Response(status=400, msg="비밀번호가 일치하지 않습니다.")

@api_view(['PATCH'])
def change_user_password(request):

    refresh_token = request.data.get("refresh")

    # password = request.data['password']
    new_password = request.data['newPassword']
    
    # 현재 비밀번호 확인
    # if not check_password(password, request.user.password):
    #     return Response(msg="현재 비밀번호가 틀렸습니다.", status=400)
    
    # 현재와 변경된 비밀변호가 같음
    if check_password(new_password, request.user.password):
        return Response(msg="현재 비밀번호와 새로운 비밀번호가 같습니다.", status=400)

    request.user.set_password(new_password)
    request.user.save()
    
    # 리프레시 토큰 무효화 처리 (로그아웃)
    if refresh_token:
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()  
        except Exception as e:
            return Response(msg="토큰 무효화 중 오류가 발생했습니다.", status=400)
    else:
        return Response(msg="토큰이 존재하지 않습니다.", status=400)

    return Response(msg="비밀번호 변경이 완료되었습니다. 다시 로그인해주세요.", status=200)

# rollpe2025!
# testpassword!