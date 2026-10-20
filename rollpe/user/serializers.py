from rest_framework import serializers
from .models import User
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from utils.response import Response

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):

    def validate(self, attrs):

        # 사용자 인증 시도를 위해 이메일과 비밀번호 가져오기
        email = attrs.get("email")
        password = attrs.get("password")

        user_instance = User.objects.filter(email=email).first()

        # 이메일 존재 여부 확인
        if not user_instance:
            return Response(
                msg="사용자를 찾을 수 없습니다.",
                status=404
            )

        # 비밀번호 확인
        if not user_instance.check_password(password):
            return Response(
                msg="비밀번호가 틀렸습니다.",
                status=401
            )

        if not user_instance.is_active:
            return Response(
                msg="이메일 인증을 진행해주세요.",
                status=403
            )

        # 기본 JWT 토큰 생성 로직 실행
        tokens = super().validate(attrs)

        # 추가 사용자 정보 포함 (선택)
        tokens["user"] = {
            "id": user_instance.id,
            "name": user_instance.name,
            "email": user_instance.email,
            "identifyCode": user_instance.identifyCode,
            "provider": user_instance.provider
        }

        return Response(data=tokens, status=201)

class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = ('name', 'email', 'password', 'birth', 'sex', 'phoneNumber')
        extra_kwargs = {
            'email': {'required': True, 'allow_blank': False, 'allow_null': False},
            'password': {'write_only': True},
        }

    def create(self, validated_data):
        return User.objects.create_user(**validated_data, is_active=False)


class UserViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            'id',
            'identifyCode',
            'name',
            'provider'
        )
