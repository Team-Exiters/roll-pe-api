from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenObtainPairView
from .apis import signup_api, CustomTokenObtainPairAPI, logout_api, VerifyEmailAPI, ForgotPasswordAPI, myid_in_invate_rollpe_api, receiver_is_me_api, search_user_name
from .apis_social import social_login, KakaoLoginView

urlpatterns = [
    # path('signin', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('/signin', CustomTokenObtainPairAPI.as_view(), name='token_obtain_pair'),
    path('/token/refresh', TokenRefreshView.as_view(), name='token_refresh'),
    path('/signup', signup_api, name='signup'),
    path("/verify-email", VerifyEmailAPI.as_view(), name="verify_email"),
    path('/logout', logout_api, name='logout'),
    path('/forgot-password', ForgotPasswordAPI.as_view(), name='forgot_password'),


    path('/search-user/', search_user_name, name='search_user_name'),
    path('/papers/inviting-user/', myid_in_invate_rollpe_api, name='myid_in_invate_rollpe'),
    path('/papers/receiver/', receiver_is_me_api, name='receiver_is_me'),

    # social
    path('/social/login/<str:provider>', social_login, name='social_login'),
    path('/social-kakao', KakaoLoginView.as_view(), name='social_kakao'),
]