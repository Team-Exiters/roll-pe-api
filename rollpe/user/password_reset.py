"""Shared single-use password reset operation for API and browser clients."""

from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import User


class PasswordResetError(ValueError):
    pass


def reset_password(identify_code, token, new_password):
    if not all(isinstance(value, str) and value for value in (identify_code, token, new_password)):
        raise PasswordResetError('유효한 비밀번호 변경 링크와 새 비밀번호가 필요합니다.')
    with transaction.atomic():
        user = User.objects.select_for_update().filter(identifyCode=identify_code).first()
        if (user is None or not user.is_active or user.provider
                or not default_token_generator.check_token(user, token)):
            raise PasswordResetError('유효하지 않거나 만료된 비밀번호 변경 링크입니다.')
        user.set_password(new_password)
        user.save(update_fields=['password'])
        for outstanding in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=outstanding)
