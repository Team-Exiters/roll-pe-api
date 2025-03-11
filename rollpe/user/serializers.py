from rest_framework import serializers
from .models import User
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate
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
        # user = authenticate(email=email, password=password)
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

    is_test = serializers.BooleanField(required=False, write_only=True) # 테스트 환경을위한 필드

    class Meta:
        model = User
        fields = '__all__'
        extra_kwargs = {
            'is_test': {'write_only': True}  # 클라이언트로부터 읽지 못하도록 설정
        }

    def create(self, validated_data):

        password = validated_data.pop('password')
        is_test = validated_data.pop('is_test', False)

        user = User.objects.create(**validated_data)
        # user = User.objects.create_user(password=password, **validated_data)
        user.set_password(password)

        if is_test:  # 테스트 환경인 경우
            user.is_active = True
        else:  # 실제 API 호출인 경우
            user.is_active = False

        user.save()
        
        return user



class UserViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            'id',
            'code',
            'identifyCode',
            'name',
            'provider'
        )
