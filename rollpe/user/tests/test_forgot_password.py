# from rest_framework.test import APITestCase
# from django.urls import reverse
# from user.models import User
# from rest_framework import status
# from django.core import mail
# import jwt
# from django.conf import settings
# from django.core.cache import cache

# class ForgotPasswordTestCase(APITestCase):
#     def setUp(self):
#         self.login_url = reverse("token_obtain_pair")
#         self.logout_url = reverse("logout")
#         self.change_password_url = reverse("forgot_password")
#         self.verify_email_url = reverse('verify_email')  # 이메일 인증 URL

#         User.objects.create_user(name="testuser", email="test@test.com", password="testpassword", is_active=True)
#         # 로그인
#         self.sign_in_data = {
#             "email": "test@test.com",
#             "password": "testpassword"
#         }
#         self.login_response = self.client.post(self.login_url, self.sign_in_data)
#         # 헤더에 토큰 추가
#         self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.login_response.json().get('data').get('access')}")

#         self.change_data = {
#             'refresh':self.login_response.json().get('data').get('refresh'),
#             'newPassword':'testnewpassword',
#             'newPasswordCheck':'testnewpassword'
#         }
        

#     def test_change_password_success(self):
#         """
#         마이페이지에서 비밀번호 변경 후 변경된 비밀번호로 재로그인 성공 테스트
#         """
#         response = self.client.patch(self.change_password_url, self.change_data)
#         self.assertEqual(response.status_code, status.HTTP_200_OK)
#         self.assertEqual(response.json()['message'], "비밀번호 변경이 완료되었습니다. 다시 로그인해주세요.")

#         # 비밀번호 변경후 로그아웃 시키기
#         self.client.post(self.logout_url, {"refresh": self.login_response.json().get('data').get('refresh')})

#         # 변경된 비밀번호로 로그인 시도
#         new_login_response = self.client.post(self.login_url, {'email':self.sign_in_data.get('email'), 'password':self.change_data.get('newPassword')})
#         self.assertEqual(new_login_response.status_code, status.HTTP_201_CREATED)
#         self.assertIn('access', new_login_response.json().get('data'))
#         self.assertIn('refresh', new_login_response.json().get('data'))

#     def test_send_email_sucess(self):
#         """
#         로그인 페이지에서 비밀번호 변경을 위한 이메일 발송 test
#         """

#         cache.clear()
#         mail.outbox = []

#         # 비밀번호 변경을 위한 이메일 인증
#         self.client.post(self.change_password_url, {"email": "test@test.com"},format='json')

#         # 이메일 발송 여부 확인
#         email = mail.outbox[0]
#         self.assertEqual(email.to, ["test@test.com"])

#         # 이메일 본문에서 토큰 추출
#         token_start_index = email.body.find("identifyCode=") + len("identifyCode=")
#         token = email.body[token_start_index:].strip()  # 이메일 본문에서 토큰 추출
#         self.assertTrue(token, "Token not found in email body")

#     # def test_verify_email_with_valid_token(self):
#     #     """
#     #     유효한 토큰으로 이메일 인증 성공후 비밀번호 변경 성공 테스트
#     #     """
#     #     cache.clear()
#     #     mail.outbox = []

#     #     # 비밀번호 변경을 위한 이메일 인증
#     #     self.client.post(self.change_password_url, {"email": "test@test.com"},format='json')

#     #     # 이메일 본문에서 토큰 추출
#     #     email = mail.outbox[0]
#     #     token_start_index = email.body.find("token=") + len("token=")
#     #     token = email.body[token_start_index:].strip()
        
#     #     # 이메일 인증 요청
#     #     response = self.client.get(f"{self.verify_email_url}?pathCode=password&token={token}")
#     #     html = response.content.decode('utf-8')
#     #     self.assertIn("이메일 인증이 완료되었습니다.", html)

#     #     # 비밀변호 변경 요청
#     #     response = self.client.patch(self.change_password_url, self.change_data)
#     #     self.assertEqual(response.status_code, status.HTTP_200_OK)
#     #     self.assertEqual(response.json()['message'], "비밀번호 변경이 완료되었습니다. 다시 로그인해주세요.")

#     #     # 비밀번호 변경후 로그아웃 시키기
#     #     self.client.post(self.logout_url, {"refresh": self.login_response.json().get('data').get('refresh')})

#     #     # 변경된 비밀번호로 로그인 시도
#     #     new_login_response = self.client.post(self.login_url, {'email':self.sign_in_data.get('email'), 'password':self.change_data.get('newPassword')})
#     #     self.assertEqual(new_login_response.status_code, status.HTTP_201_CREATED)
#     #     self.assertIn('access', new_login_response.json().get('data'))
#     #     self.assertIn('refresh', new_login_response.json().get('data'))

#     def test_verify_email_with_invalid_token(self):
#         """
#         잘못된 토큰으로 이메일 인증 실패 여부 테스트
#         """
#         # 잘못된 토큰으로 요청
#         invalid_token = jwt.encode({"email": "test@test.com"}, "wrong_secret", algorithm="HS256")
#         response = self.client.get(f"{self.verify_email_url}?pathCode=password&token={invalid_token}")
#         html = response.content.decode('utf-8')
#         self.assertIn("유효하지 않은 링크입니다. 재전송 버튼을 눌러주세요.", html)

#     # def test_verify_email_with_expired_token(self):
#     #     """
#     #     만료된 토큰으로 이메일 인증 실패 여부 테스트
#     #     """
#     #     cache.clear()
#     #     mail.outbox = []
        
#     #     # 비밀번호 변경을 위한 이메일 인증
#     #     self.client.post(self.change_password_url, {"email": "test@test.com"},format='json')

#     #     # 이메일 본문에서 토큰 추출
#     #     email = mail.outbox[0]
#     #     token_start_index = email.body.find("token=") + len("token=")
#     #     token = email.body[token_start_index:].strip()

#     #     # 만료된 토큰 생성 (exp를 과거로 설정)
#     #     payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
#     #     expired_token = jwt.encode(
#     #         {**payload, "exp": 0},  # 만료 시간 0으로 설정
#     #         settings.SECRET_KEY,
#     #         algorithm="HS256"
#     #     )

#     #     # 만료된 토큰으로 요청
#     #     response = self.client.get(f"{self.verify_email_url}?pathCode=password&token={expired_token}")
#     #     html = response.content.decode('utf-8')
#     #     self.assertIn("링크가 만료되었습니다. 재전송 버튼을 눌러주세요.", html)
    
#     # def test_verify_email_with_used_token(self):
#     #     """
#     #     이미 사용한 토큰으로 이메일 인증 실패 여부 테스트
#     #     """
#     #     cache.clear()
#     #     mail.outbox = []

#     #     # 비밀번호 변경을 위한 이메일 인증
#     #     self.client.post(self.change_password_url, {"email": "test@test.com"},format='json')

#     #     # 이메일 본문에서 토큰 추출
#     #     email = mail.outbox[0]
#     #     token_start_index = email.body.find("token=") + len("token=")
#     #     token = email.body[token_start_index:].strip()
        
#     #     # 같은 토큰으로 2번 요청
#     #     self.client.get(f"{self.verify_email_url}?pathCode=password&token={token}") # 성공
#     #     response = self.client.get(f"{self.verify_email_url}?pathCode=password&token={token}") # 실패
#     #     html = response.content.decode('utf-8')
#     #     self.assertIn("이미 인증된 링크입니다.", html)

