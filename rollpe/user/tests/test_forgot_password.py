from rest_framework.test import APITestCase
from django.urls import reverse
from user.models import User
from rest_framework import status
from django.core import mail
import jwt
import re
from django.conf import settings
from django.core.cache import cache

class ForgotPasswordTestCase(APITestCase):
    def setUp(self):
        self.login_url = reverse("token_obtain_pair")
        self.logout_url = reverse("logout")
        self.change_password_url = reverse("forgot_password")

        User.objects.create_user(name="testuser", email="test@test.com", password="testpassword", is_active=True, identifyCode="Test12")

        self.change_data = {
            'identifyCode':'Test12',
            'newPassword':'testPasswordChange'
        }

    def test_send_email_sucess(self):
        """
        로그인 페이지에서 비밀번호 변경을 위한 이메일 발송 test
        """

        cache.clear()
        mail.outbox = []

        # 비밀번호 변경을 위한 이메일 전송
        self.client.post(self.change_password_url, {"email": "test@test.com"},format='json')

        # 이메일 발송 여부 확인
        email = mail.outbox[0]
        html_content = email.alternatives[0][0]
        self.assertEqual(email.to, ["test@test.com"])
        # 이메일 본문에서 토큰 추출
        match = re.search(r"identifyCode=([\w\d]+)", html_content)
        identify_code = match.group(1)
        self.assertEqual(identify_code, "Test12")
        # self.assertTrue(token, "Token not found in email body")

    def test_change_password_sucess(self):
        """
        비밀번호 변경후 변경된 비밀번호로 로그인 성공
        """
        # 비밀번호 변경
        self.client.patch(self.change_password_url, self.change_data, format='json')

        # 변경된 비밀번호 로그인
        response = self.client.post(self.login_url, {"email":"test@test.com", "password":"testPasswordChange"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.json().get('data'))
        self.assertIn('refresh', response.json().get('data'))

