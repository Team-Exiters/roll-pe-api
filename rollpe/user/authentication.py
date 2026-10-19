from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings

from .apple_sessions import credential_for_token, validate_apple_session


class RollpeJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        credential_for_token(user, validated_token)
        return user


class RollpeTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        token = self.token_class(attrs['refresh'])
        user = get_user_model().objects.filter(
            **{api_settings.USER_ID_FIELD: token.get(api_settings.USER_ID_CLAIM)},
        ).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed('로그인할 수 없는 계정입니다.')
        credential = credential_for_token(user, token)
        if credential:
            validate_apple_session(credential)
        return super().validate(attrs)
