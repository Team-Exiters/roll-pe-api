import jwt
import random
import string

from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.core.mail import EmailMultiAlternatives

from user.models import User

from utils.response import Response

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
    try:
        from_email = settings.EMAIL_HOST_USER
        to = [email]

        match path_code:
            case "email":
                subject = "롤페 이메일 인증"
                token = generate_email_verification_token(email)
                activation_url = f"https://{settings.API_DOMAIN}/api/user/verify-email?path_code={path_code}&token={token}"
                html_content = (
                    '<p>이메일 인증</p><br>'
                    '<p>아래 링크를 클릭하여 이메일 인증을 완료해주세요.</p><br>'
                    f'<p><a href="{activation_url}">이메일 인증하기</a></p>'
                )
            case "password":
                subject="롤페 비밀번호 찾기"

                identify_code = User.objects.filter(email=email).values_list('identifyCode', flat=True).first()
                activation_url = f"http://{settings.BASE_DOMAIN}/forgot-password?identifyCode={identify_code}"
                # activation_url = f"{request.scheme}://{settings.BASE_DOMAIN}/forgot-password?identifyCode={identify_code}"

                html_content = (
                    '<p>비밀번호 찾기</p><br>'
                    '<p>아래 링크로 접속해서 비밀번호 변경을 진행해주세요.</p><br>'
                    f'<p><a href="{activation_url}">비밀변호 변경하기</a></p>'
                )

        msg = EmailMultiAlternatives(subject, '', from_email, to)
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        
        return Response(msg="이메일 전송 성공", status=200)
        
    except Exception as e:
        return Response(msg=f"이메일 전송 실패: {str(e)}", status=400)

def create_idenfy_number(request):

    while True:
        characters = string.ascii_letters + string.digits  # 영문 대소문자 + 숫자
        code_num = ''.join(random.choices(characters, k=6))

        # 중복 여부 확인
        if not User.objects.filter(identifyCode=code_num).exists():
            return code_num  # 중복이 없으면 반환