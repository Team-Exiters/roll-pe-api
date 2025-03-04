from rest_framework.test import APITestCase
from django.urls import reverse
from user.models import User
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status

class LogoutAPITest(APITestCase):
    
    def setUp(self):
        # self.signup_url = reverse("signup")
        self.login_url = reverse("token_obtain_pair")
        self.logout_url = reverse("logout")

        # 회원가입
        # self.sign_up_data = {
        #     "name": "testuser",
        #     "email": "test@test.com",
        #     "password": "testpassword",
        #     "sex": 1,
        #     "birth": "000101",
        #     "phoneNumber": "01012345678",
        #     "is_test":True
        # }
        # self.client.post(self.signup_url, self.sign_up_data, format='json')
        User.objects.create_user(name="testuser", email="test@test.com", password="testpassword", is_active=True)
        # 로그인
        self.sign_in_data = {
            "email": "test@test.com",
            "password": "testpassword",
        }
        self.login_response = self.client.post(self.login_url, self.sign_in_data)

        # 헤더에 토큰 추가
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.login_response.json().get('data').get('access')}")

    """리프레시 토큰이 유효할 때 로그아웃 성공"""
    def test_logout_success(self):
        response = self.client.post(self.logout_url, {"refresh": self.login_response.json().get('data').get('refresh')})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    """ 잘못된 리프레시 토근 사용으로 로그아웃 실패 """
    def test_logout_invalid_token(self):
        response = self.client.post(self.logout_url, {"refresh": "invalidToken"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
    """ 리프레시 토큰이 없는 경우 로그아웃 실패 """
    def test_logout_no_token(self):
        response = self.client.post(self.logout_url, {})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)