from rest_framework.test import APITestCase
from django.urls import reverse
from user.models import User
from rest_framework import status
from django.core import mail
import jwt
import re
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth.tokens import default_token_generator
from django.test import override_settings
from unittest.mock import patch
from datetime import timedelta
from rest_framework_simplejwt.tokens import RefreshToken

class ForgotPasswordTestCase(APITestCase):
    def setUp(self):
        self.login_url = reverse("token_obtain_pair")
        self.logout_url = reverse("logout")
        self.change_password_url = reverse("forgot_password")

        User.objects.create_user(name="testuser", email="test@test.com", password="testpassword", is_active=True, identifyCode="Test12")

        self.user = User.objects.get(email='test@test.com')
        self.change_data = {
            'token': default_token_generator.make_token(self.user),
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
        match = re.search(r"forgot-password/([\w\d]+)", html_content)
        identify_code = match.group(1)
        self.assertEqual(identify_code, "Test12")
        self.assertIn("https://", html_content)
        self.assertIn("?token=", html_content)
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


    def test_missing_wrong_and_other_users_token_cannot_reset_password(self):
        other = User.objects.create_user(email='other@example.com', name='Other')
        for token in (None, 'invalid', default_token_generator.make_token(other)):
            response = self.client.patch(self.change_password_url, {
                **self.change_data, 'token': token,
            }, format='json')
            self.assertEqual(response.status_code, 400)
            self.user.refresh_from_db()
            self.assertTrue(self.user.check_password('testpassword'))

    @override_settings(PASSWORD_RESET_TIMEOUT=1800)
    def test_expired_reset_token_is_rejected(self):
        now = default_token_generator._now()
        with patch.object(default_token_generator, '_now', return_value=now - timedelta(seconds=1801)):
            token = default_token_generator.make_token(self.user)
        response = self.client.patch(self.change_password_url, {**self.change_data, 'token': token}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_reset_token_is_single_use_and_blacklists_existing_refresh(self):
        refresh = str(RefreshToken.for_user(self.user))
        self.assertEqual(self.client.patch(self.change_password_url, self.change_data, format='json').status_code, 200)
        self.assertEqual(self.client.patch(self.change_password_url, self.change_data, format='json').status_code, 400)
        response = self.client.post(reverse('token_refresh'), {'refresh': refresh}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_social_and_inactive_accounts_cannot_reset(self):
        for provider, active in [('apple', True), (None, False)]:
            self.user.provider, self.user.is_active = provider, active
            self.user.save()
            response = self.client.patch(self.change_password_url, {
                **self.change_data, 'token': default_token_generator.make_token(self.user),
            }, format='json')
            self.assertEqual(response.status_code, 400)

    def test_missing_and_unknown_reset_input_returns_controlled_error(self):
        self.assertEqual(self.client.post(self.change_password_url, {}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(self.change_password_url, {}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(self.change_password_url, {
            **self.change_data, 'identifyCode': 'Absent',
        }, format='json').status_code, 400)
