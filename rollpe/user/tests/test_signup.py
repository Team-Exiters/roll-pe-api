from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.core import mail
from user.models import User
import jwt
import re
from django.conf import settings
from django.core.cache import cache

### 회원가입 이메일 인증용 test
class EmailVerificationTest(APITestCase):
    def setUp(self):

        # 각 테스트 전에 캐시 초기화
        cache.clear()

        self.signup_url = reverse('signup')  # 회원가입 URL
        self.verify_email_url = reverse('verify_email')  # 이메일 인증 URL
        self.user_data = {
            "name": "testuser123",
            "email": "test123@test.com",
            "password": "testpassword",
            "sex": 1,
            "birth": "000101",
            "phoneNumber": "01012345678"
        }

    def test_signup_sends_email_with_token(self):
        """
        회원가입 시 이메일 인증 링크가 전송되는지 테스트
        """

        cache.clear()
        mail.outbox = []

        # 회원가입 
        signup_response = self.client.post(self.signup_url, self.user_data, format='json')

        # 응답 코드 확인
        self.assertEqual(signup_response.status_code, status.HTTP_201_CREATED)
        self.assertIn("message", signup_response.json())
        self.assertEqual(signup_response.json()["message"], "회원가입이 완료되었습니다. 이메일을 확인해주세요.")

        # 이메일 발송 여부 확인
        self.assertEqual(len(mail.outbox), 1)  # 이메일 한 건이 발송되었는지 확인
        email = mail.outbox[0]
        self.assertEqual(email.to, [self.user_data["email"]])

        # 이메일 본문에서 토큰 추출
        html_content = email.alternatives[0][0]
        
        match = re.search(r'token=([\w.-]+)', html_content)
        token = match.group(1)

        self.assertTrue(token, "Token not found in email body")

    def test_verify_email_with_valid_token(self):
        """
        유효한 토큰으로 이메일 인증 성공 여부 테스트
        """

        cache.clear()
        mail.outbox = []

        # 회원가입 
        self.client.post(self.signup_url, self.user_data, format='json')

        # 이메일 본문에서 토큰 추출
        email = mail.outbox[0]
        html_content = email.alternatives[0][0]

        match = re.search(r'token=([\w.-]+)', html_content)
        token = match.group(1)

        # 이메일 인증 요청
        response = self.client.get(f"{self.verify_email_url}?path_code=email&token={token}")
        html = response.content.decode('utf-8')
        self.assertIn("이메일 인증이 완료되었습니다.", html)

        # 사용자 인증 여부 확인
        user = User.objects.get(email=self.user_data["email"])
        self.assertTrue(user.is_active)

    def test_verify_email_with_invalid_token(self):
        """
        잘못된 토큰으로 이메일 인증 실패 여부 테스트
        """

        cache.clear()
        mail.outbox = []

        # 회원가입 
        self.client.post(self.signup_url, self.user_data, format='json')

        # 잘못된 토큰으로 요청
        invalid_token = jwt.encode({"email": self.user_data.get('email')}, "wrong_secret", algorithm="HS256")
        response = self.client.get(f"{self.verify_email_url}?pathCode=email&token={invalid_token}")
        html = response.content.decode('utf-8')
        self.assertIn("유효하지 않은 링크입니다. 재전송 버튼을 눌러주세요.", html)

    def test_verify_email_with_expired_token(self):
        """
        만료된 토큰으로 이메일 인증 실패 여부 테스트
        """

        cache.clear()
        mail.outbox = []

        # 회원가입 
        self.client.post(self.signup_url, self.user_data, format='json')

        # 이메일 본문에서 토큰 추출
        email = mail.outbox[0]

        html_content = email.alternatives[0][0]

        match = re.search(r'token=([\w.-]+)', html_content)
        token = match.group(1)

        # 만료된 토큰 생성 (exp를 과거로 설정)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        expired_token = jwt.encode(
            {**payload, "exp": 0},  # 만료 시간 0으로 설정
            settings.SECRET_KEY,
            algorithm="HS256"
        )

        # 만료된 토큰으로 요청
        response = self.client.get(f"{self.verify_email_url}?pathCode=email&token={expired_token}")
        html = response.content.decode('utf-8')
        self.assertIn("링크가 만료되었습니다. 재전송 버튼을 눌러주세요.", html)
    
    def test_verify_email_with_used_token(self):
        """
        이미 사용한 토큰으로 이메일 인증 실패 여부 테스트
        """

        cache.clear()
        mail.outbox = []

        # 회원가입 
        self.client.post(self.signup_url, self.user_data, format='json')

        # 이메일 본문에서 토큰 추출
        email = mail.outbox[0]

        html_content = email.alternatives[0][0]

        match = re.search(r'token=([\w.-]+)', html_content)
        token = match.group(1)

        # 같은 토큰으로 2번 요청
        self.client.get(f"{self.verify_email_url}?pathCode=email&token={token}") # 성공
        response = self.client.get(f"{self.verify_email_url}?pathCode=email&token={token}") # 실패
        html = response.content.decode('utf-8')
        self.assertIn("이미 인증된 링크입니다.", html)


