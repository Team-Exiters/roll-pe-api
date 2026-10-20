"""Isolated local tests: no production .env, MySQL, email, or external API calls."""

import base64

SECRET_KEY = 'rollpe-local-tests-only-not-for-deployment'
DEBUG = False
USE_TZ = True
TIME_ZONE = 'Asia/Seoul'
ROOT_URLCONF = 'config.urls'
AUTH_USER_MODEL = 'user.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages',
    'rest_framework', 'rest_framework_simplejwt.token_blacklist',
    'user', 'paper', 'heart', 'engine', 'utils',
]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['user.authentication.RollpeJWTAuthentication'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
EMAIL_HOST_USER = 'tests@example.com'
API_DOMAIN = 'api.example.com'
BASE_DOMAIN = 'web.example.com'
APPLE_AUTH_CLIENT_ID = 'dev.hugesilver.rollpe.web'
APPLE_AUTH_NATIVE_CLIENT_ID = 'dev.hugesilver.Roll-Pe'
APPLE_AUTH_TEAM_ID = 'TESTTEAM'
APPLE_AUTH_KEY_ID = 'TESTKEY'
APPLE_AUTH_PRIVATE_KEY_FILE = '/unused-in-mocked-tests.p8'
APPLE_AUTH_TOKEN_ENCRYPTION_KEYS = [base64.urlsafe_b64encode(b'0' * 32).decode()]
APPLE_AUTH_REDIRECT_URI = 'https://rollpe.mooo.com/api/user/social/login/apple/callback'
APPLE_AUTH_RETURN_URLS = [
    'http://localhost:8081/auth/apple', 'reactnativerollpe://auth/apple',
]
GOOGLE_AUTH_CLIENT_ID = 'test-web.apps.googleusercontent.com'
GOOGLE_AUTH_CLIENT_SECRET = 'test-google-secret'
GOOGLE_AUTH_REDIRECT_URI = 'https://rollpe.mooo.com/api/user/social/login/google/callback'
GOOGLE_AUTH_RETURN_URLS = ['http://localhost:8081/auth/google', 'reactnativerollpe://auth/google']
KAKAO_AUTH_CLIENT_ID = 'test-kakao-rest-key'
KAKAO_AUTH_APP_ID = '5678'
KAKAO_AUTH_CLIENT_SECRET = 'test-kakao-secret'
KAKAO_AUTH_REDIRECT_URI = 'https://rollpe.mooo.com/api/user/social/login/kakao/callback'
KAKAO_AUTH_RETURN_URLS = ['http://localhost:8081/auth/kakao', 'reactnativerollpe://auth/kakao']

# Password reset links expire after 30 minutes.
PASSWORD_RESET_TIMEOUT = 1800
