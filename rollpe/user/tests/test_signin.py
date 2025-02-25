from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from django.urls import reverse
from user.models import User

class LoginAPITestCase(APITestCase):
    def setUp(self):
        self.UserModel = get_user_model()
        self.login_url = reverse('token_obtain_pair') # 로그인 엔드포인트 URL
        # self.signup_url = reverse('signup') # 로그인 엔드포인트 URL
        # self.signup_data = {
        #     "name": "testuser",
        #     "email": "test@test.com",
        #     "password": "testpassword",
        #     "sex": 1,
        #     "birth": "000101",
        #     "phoneNumber": "01012345678",
        #     "is_test":True
        # }
        # self.client.post(self.signup_url, self.signup_data, format='json')
        User.objects.create_user(name="testuser", email="test@test.com", password="testpassword", is_active=True)
        self.login_data = {
            'email': 'test@test.com',
            'password': 'testpassword',
        }

    def test_signin_success(self):
        """ 로그인 성공 """
        response = self.client.post(self.login_url, self.login_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.json().get('data'))
        self.assertIn('refresh', response.json().get('data'))

    def test_signin_fail_invalid_data(self):
        """ 로그인 실패 잘못된 데이터 사용 """
        data = {
            'email': 'test1111@test.com',
            "password": "wrongpassword"
        }
        response = self.client.post(self.login_url, data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # self.assertNotIn('access', response.json().get("data", {}))
        # self.assertNotIn('refresh', response.json().get("data", {}))

    
    def test_login_fail_empty_fields(self):
        """ 빈 데이터 """
        data = {
            "username": "",
            "password": ""
        }
        response = self.client.post(self.login_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

