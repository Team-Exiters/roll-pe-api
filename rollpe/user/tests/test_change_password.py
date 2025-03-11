from rest_framework.test import APITestCase
from django.urls import reverse
from user.models import User
from rest_framework import status
from django.core import mail
import jwt
from django.conf import settings
from django.core.cache import cache

class ChangePasswordTestCase(APITestCase):

    def setUp(self):
        self.login_url = reverse("token_obtain_pair")
        self.logout_url = reverse("logout")
        self.change_password_url = reverse("change_password")
        self.verify_email_url = reverse('verify_email')  # 이메일 인증 URL

        User.objects.create_user(name="testuser", email="test@test.com", password="testpassword", is_active=True)
        # 로그인
        self.sign_in_data = {
            "email": "test@test.com",
            "password": "testpassword"
        }
        self.login_response = self.client.post(self.login_url, self.sign_in_data)
        # 헤더에 토큰 추가
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.login_response.json().get('data').get('access')}")

        self.change_data = {
            'refresh':self.login_response.json().get('data').get('refresh'),
            'newPassword':'testnewpassword',
        }
        self.change_invalid_data = {
            'refresh':self.login_response.json().get('data').get('refresh'),
            'newPassword':'testpassword',
        }

    def test_change_password_success(self):
        """
        마이페이지에서 비밀번호 변경 후 변경된 비밀번호로 재로그인 성공 테스트
        """
        response = self.client.patch(self.change_password_url, self.change_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['message'], "비밀번호 변경이 완료되었습니다. 다시 로그인해주세요.")

        # 비밀번호 변경후 로그아웃 시키기
        self.client.post(self.logout_url, {"refresh": self.login_response.json().get('data').get('refresh')})

        # 변경된 비밀번호로 로그인 시도
        new_login_response = self.client.post(self.login_url, {'email':self.sign_in_data.get('email'), 'password':self.change_data.get('newPassword')})
        self.assertEqual(new_login_response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', new_login_response.json().get('data'))
        self.assertIn('refresh', new_login_response.json().get('data'))
    
    def test_change_incvaild_password(self):
        """
        마이페이지에서 현재 비밀번호와 같은 비밀번호로 변경 테스트
        """
        response = self.client.patch(self.change_password_url, self.change_invalid_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
