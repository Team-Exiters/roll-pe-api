import jwt
import random
import string

from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail

from user.models import User


def generate_email_verification_token(email):
    payload = {
        "email": email,
        "exp": datetime.utcnow() + timedelta(minutes=5),  # 토큰 만료 시간 (5분)
        "iat": datetime.utcnow(),  # 토큰 발행 시간
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    return token

def verify_email_token(token):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])

        # 캐시에서 토큰 조회
        used_token = cache.get(f'{payload["email"]}_token', None)

        if used_token:
            raise ValueError("이미 인증된 링크입니다.")
        
        cache.set(f'{payload["email"]}_token',token, timeout=300)

        return payload  # 유효한 경우 페이로드 반환
    
    except jwt.ExpiredSignatureError:
        raise ValueError("링크가 만료되었습니다. 재전송 버튼을 눌러주세요.")
    except jwt.InvalidTokenError:
        raise ValueError("유효하지 않은 링크입니다. 재전송 버튼을 눌러주세요.") 

def generate_send_email(request, email, path_code):


    match path_code:
        case "email":
            token = generate_email_verification_token(email)
            activation_url = f"{request.scheme}://{request.get_host()}/api/user/verify-email?path_code={path_code}&token={token}"

            # 이메일 발송
            send_mail(
                subject="이메일 인증을 완료해주세요.",
                message=f"다음 링크를 클릭하여 이메일 인증을 완료하세요: {activation_url}",
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[email],
            )
        case "password":
            # email로 유저의 identity code 가져와서 링크에 쿼리파람으로 넣어주기
            identify_code = User.objects.filter(email=email).values_list('identifyCode', flat=True).first()
            activation_url = f"{settings.BASE_DOMAIN}/forgot-password?identifyCode={identify_code}"

            # 이메일 발송
            send_mail(
                subject="비밀번호 찾기",
                message=f"다음 링크를 클릭하여 비밀번호를 변경하세요: {activation_url}",
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[email],
            )
    return

def create_idenfy_number(request):

    while True:
        characters = string.ascii_letters + string.digits  # 영문 대소문자 + 숫자
        code_num = ''.join(random.choices(characters, k=6))

        # 중복 여부 확인
        if not User.objects.filter(identifyCode=code_num).exists():
            return code_num  # 중복이 없으면 반환
