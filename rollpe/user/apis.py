from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.views import APIView
from rest_framework import permissions

from django.db.models import Q
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.contrib.auth.hashers import check_password
from django.contrib.auth.tokens import default_token_generator

from utils.response import Response
from utils.functions import verify_email_token, generate_send_email, create_idenfy_number, PRIVACY, TERMS

from user.serializers import UserSerializer, CustomTokenObtainPairSerializer, UserViewSerializer
from user.models import User
from user.apple_sessions import credential_for_token, revoke_apple_credentials
from user.authentication import RollpeTokenRefreshSerializer

from paper.models import Paper

def invalid_object_body(request):
    if not hasattr(request.data, 'get'):
        return Response(msg='올바르지 않은 요청입니다.', status=400)
    return None


class RollpeTokenRefreshView(TokenRefreshView):
    serializer_class = RollpeTokenRefreshSerializer


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
    error = invalid_object_body(request)
    if error is not None:
        return error
    refresh_token = request.data.get("refresh")

    if not refresh_token:
        return Response(msg="Refresh token이 없습니다.", status=403)

    try:
        token = RefreshToken(refresh_token)
        if str(token.get(api_settings.USER_ID_CLAIM)) != str(request.user.pk):
            return Response(msg='다른 사용자의 Refresh Token입니다.', status=403)
        with transaction.atomic():
            user = User.objects.select_for_update().filter(pk=request.user.pk).first()
            if user is None:
                return Response(msg='종료된 로그인 세션입니다.', status=401)
            credential = credential_for_token(user, token)
            if credential:
                credential.invalidated_at = timezone.now()
                credential.save(update_fields=['invalidated_at'])
            token.blacklist()
    except (TokenError, TypeError, ValueError):
        return Response(msg="유효한 Refresh Token이 아닙니다. ", status=403)

    return Response(msg="로그아웃 되었습니다.", status=200)


@api_view(['POST'])
@permission_classes([AllowAny])
def signup_api(request):
    error = invalid_object_body(request)
    if error is not None:
        return error
    # 회원가입 데이터 처리
    email = request.data.get("email")

    if User.objects.filter(email=email).exists():
        return Response(msg="이미 가입된 이메일입니다.", status=400)

    serializer = UserSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(msg=serializer.errors, status=400)
    try:
        with transaction.atomic():
            user = serializer.save()
            result = generate_send_email(request, user.email, path_code="email")
            if result.status_code != 200:
                transaction.set_rollback(True)
                return result
    except IntegrityError:
        return Response(msg="이미 가입된 이메일입니다.", status=400)
    return Response(msg="회원가입이 완료되었습니다. 이메일을 확인해주세요.", status=201)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def drop_user_data(request):
    error = invalid_object_body(request)
    if error is not None:
        return error

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
        if str(token.get(api_settings.USER_ID_CLAIM)) != str(request.user.pk):
            return Response(msg='다른 사용자의 Refresh Token입니다.', status=403)
    except (TokenError, TypeError, ValueError):
        return Response(msg="유효한 Refresh Token이 아닙니다. ", status=403)

    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=request.user.pk).first()
        if user is None:
            return Response(msg='이미 탈퇴한 계정입니다.', status=401)
        manual_unlink = revoke_apple_credentials(user) if user.provider == 'apple' else False
        for outstanding in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=outstanding)
        user.delete()

    if manual_unlink:
        return Response(
            msg='회원 탈퇴 되었습니다. Apple 계정 설정에서 Roll-pe 연결도 해제해주세요.',
            data={'appleRevocationRequired': True}, status=200,
        )
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
        error = invalid_object_body(request)
        if error is not None:
            return error
        email = request.data.get("email")
        path_code = request.data.get("pathCode")
        if not isinstance(email, str) or not email or path_code not in ('email', 'password'):
            return Response(msg='이메일과 인증 경로를 확인해주세요.', status=400)
        if path_code == 'password':
            user = User.objects.filter(email=email, is_active=True, provider__isnull=True).first()
            if user is None:
                return Response(msg='비밀번호를 변경할 수 없는 계정입니다.', status=400)
        result = generate_send_email(request, email, path_code=path_code)
        if result.status_code != 200:
            return result
        return Response(msg="인증 이메일을 재 전송하였습니다.", status=200)

class ForgotPasswordAPI(APIView):

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        error = invalid_object_body(request)
        if error is not None:
            return error
        email = request.data.get('email')
        if not isinstance(email, str) or not email:
            return Response(msg='이메일이 필요합니다.', status=400)

        user_query = User.objects.filter(email=email)

        if not user_query.exists():
            return Response(msg="회원가입되지 않은 이메일입니다.", status=400)
        
        if not user_query.filter(is_active=True).exists():
            return Response(msg='이메일 인증을 진행해주세요.', status=400)
        provider = user_query.values_list('provider',flat=True).first()
        if provider is not None:
            return Response(msg=f"{provider}로 회원가입된 이메일입니다. {provider}에서 비밀번호 찾기를 진행해주세요.", status=400)
        
        result = generate_send_email(request, email, path_code="password")
        if result.status_code != 200:
            return result
        return Response(msg="비밀번호 변경 이메일이 전송되었습니다.", status=200)

    def patch(self, request):
        error = invalid_object_body(request)
        if error is not None:
            return error

        identify_code = request.data.get('identifyCode')
        token = request.data.get('token')
        new_password = request.data.get('newPassword')
        if not all(isinstance(value, str) and value for value in (identify_code, token, new_password)):
            return Response(msg='유효한 비밀번호 변경 링크와 새 비밀번호가 필요합니다.', status=400)
        with transaction.atomic():
            user = User.objects.select_for_update().filter(identifyCode=identify_code).first()
            if (user is None or not user.is_active or user.provider
                    or not default_token_generator.check_token(user, token)):
                return Response(msg='유효하지 않거나 만료된 비밀번호 변경 링크입니다.', status=400)
            user.set_password(new_password)
            user.save(update_fields=['password'])
            for outstanding in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=outstanding)
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

    if not user_name_code:
        return Response(msg="검색어가 필요합니다.", status=400)

    users = User.objects.filter(Q(name__icontains=user_name_code) | Q(provider__icontains=user_name_code))
    if not users:
        return Response(msg="사용자를 찾을 수 없습니다.",status=404)
    
    page = paginator.paginate_queryset(users, request)
    serializer = UserViewSerializer(page, many=True)
    data = paginator.get_paginated_response(serializer.data).data
    
    return Response(data=data,status=200)


@api_view(['POST'])
def user_password_check(request):
    error = invalid_object_body(request)
    if error is not None:
        return error
    password = request.data.get("password", None)
    user = request.user
 
    if user.is_anonymous:
        return Response(status=401)
    
    if not isinstance(password, str) or not password:
        return Response(status=400, msg="패스워드가 없습니다.")
 
 
    return Response(status=200, data={"status": user.check_password(password)})

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def change_user_password(request):
    error = invalid_object_body(request)
    if error is not None:
        return error
    refresh_token = request.data.get('refresh')
    new_password = request.data.get('newPassword')
    if not isinstance(new_password, str) or not new_password:
        return Response(msg="새로운 비밀번호가 필요합니다.", status=400)
    if not refresh_token:
        return Response(msg="토큰이 존재하지 않습니다.", status=400)
    try:
        token = RefreshToken(refresh_token)
        if str(token.get(api_settings.USER_ID_CLAIM)) != str(request.user.pk):
            return Response(msg='다른 사용자의 Refresh Token입니다.', status=403)
    except (TokenError, TypeError, ValueError):
        return Response(msg="토큰 무효화 중 오류가 발생했습니다.", status=400)

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        credential = credential_for_token(user, token)
        if check_password(new_password, user.password):
            return Response(msg="현재 비밀번호와 새로운 비밀번호가 같습니다.", status=400)
        token.blacklist()
        if credential:
            credential.invalidated_at = timezone.now()
            credential.save(update_fields=['invalidated_at'])
        user.set_password(new_password)
        user.save(update_fields=['password'])
    return Response(msg="비밀번호 변경이 완료되었습니다. 다시 로그인해주세요.", status=200)

@api_view(["GET"])
@permission_classes([AllowAny])
def get_docs_api(request):
    documents = {'privacy': PRIVACY, 'terms': TERMS}
    data = documents.get(request.GET.get('docs'))
    if data is None:
        return Response(msg="잘못된 입력값입니다.", status=400)
    return Response(data=data, status=200)
