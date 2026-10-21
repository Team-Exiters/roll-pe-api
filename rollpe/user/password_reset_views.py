"""Server-hosted password reset form; token arrives only in a URL fragment."""

import re
import secrets

from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .password_reset import PasswordResetError, reset_password


@require_http_methods(['GET', 'POST'])
@csrf_protect
def password_reset_page(request, identify_code):
    error, success = '', False
    if request.method == 'POST':
        password = request.POST.get('newPassword', '')
        if not re.fullmatch(r'(?=.*[a-zA-Z])(?=.*[!@#$%^*+=-])(?=.*[0-9]).{8,128}', password):
            error = '영문, 숫자, 특수문자(!@#$%^*+=-)를 포함해 8자 이상 입력해주세요. 이메일 링크를 다시 열어주세요.'
        elif password != request.POST.get('passwordConfirmation', ''):
            error = '비밀번호가 일치하지 않습니다. 이메일 링크를 다시 열어주세요.'
        else:
            try:
                reset_password(identify_code, request.POST.get('token'), password)
                success = True
            except PasswordResetError as exc:
                error = f'{exc} 새 인증 메일을 요청해주세요.'
    nonce = secrets.token_urlsafe(24)
    response = render(request, 'password_reset.html', {
        'error': error, 'success': success, 'csp_nonce': nonce,
    }, status=400 if error else 200)
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Frame-Options'] = 'DENY'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    return response
