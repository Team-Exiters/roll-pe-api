from django.urls import include, path
from .apis import signup_api, CustomTokenObtainPairAPI, logout_api, VerifyEmailAPI, ForgotPasswordAPI, \
    myid_in_invate_rollpe_api, receiver_is_me_api, search_user_name, user_password_check, change_user_password, drop_user_data, get_docs_api, RollpeTokenRefreshView
from .apis_social import social_login, KakaoLoginView, GoogleLoginView
from .apple_browser import apple_start, apple_callback, apple_exchange
from .social_browser import social_start, social_callback, social_exchange
from .password_reset_views import password_reset_page

urlpatterns = [
    path('/password-reset/<str:identify_code>', password_reset_page, name='password_reset_page'),
    # path('signin', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('/signin', CustomTokenObtainPairAPI.as_view(), name='token_obtain_pair'),
    path('/token/refresh', RollpeTokenRefreshView.as_view(), name='token_refresh'),
    path('/signup', signup_api, name='signup'),
    path("/verify-email", VerifyEmailAPI.as_view(), name="verify_email"),
    path('/logout', logout_api, name='logout'),
    path('/forgot-password', ForgotPasswordAPI.as_view(), name='forgot_password'),
    path('/password-check', user_password_check, name='password_check'),
    path('/change-password', change_user_password, name='change_password'),
    path('/drop-user', drop_user_data, name='drop_user'),

    path('/search-user/', search_user_name, name='search_user_name'),
    path('/papers/inviting-user/', myid_in_invate_rollpe_api, name='myid_in_invate_rollpe'),
    path('/papers/receiver/', receiver_is_me_api, name='receiver_is_me'),

    # social
    path('/social/login/apple/start', apple_start, name='apple_start'),
    path('/social/login/apple/callback', apple_callback, name='apple_callback'),
    path('/social/login/apple/exchange', apple_exchange, name='apple_exchange'),
    path('/social/login/', include([
        path('<str:provider>/start', social_start, name='social_start'),
        path('<str:provider>/callback', social_callback, name='social_callback'),
        path('<str:provider>/exchange', social_exchange, name='social_exchange'),
    ])),
    path('/social/login/<str:provider>', social_login, name='social_login'),
    path('/social-kakao', KakaoLoginView.as_view(), name='social_kakao'),
    path('/social-google', GoogleLoginView.as_view(), name='social_google'),

    # 개인정보처리방침, 이용약관
    path('/docs',get_docs_api, name='docs')
]
