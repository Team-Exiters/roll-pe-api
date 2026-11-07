import math

from django.db import transaction
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from rest_framework import serializers
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from engine.models import Inquiry
from user.models import User
from utils.response import Response


class InquiryInput(serializers.Serializer):
    requestId = serializers.UUIDField()
    category = serializers.ChoiceField(choices=Inquiry.Category.choices)
    content = serializers.CharField(max_length=2000, trim_whitespace=True)


class InquiryThrottle(UserRateThrottle):
    scope = 'inquiry'
    rate = '10/day'


@method_decorator(never_cache, name='dispatch')
class InquiriesAPI(APIView):
    def post(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        serializer = InquiryInput(data=request.data)
        if not serializer.is_valid():
            return Response(status=400, msg='문의유형과 내용을 확인해주세요.')
        data = serializer.validated_data
        # Serialize a retry with account withdrawal; never recreate data for an inactive account.
        with transaction.atomic():
            user = User.objects.select_for_update().filter(pk=request.user.pk, is_active=True).first()
            if user is None:
                return Response(status=401)
            existing = Inquiry.objects.filter(userFK=user, requestId=data['requestId']).exists()
            if not existing:
                throttle = InquiryThrottle()
                if not throttle.allow_request(request, self):
                    return Response(status=429, msg='문의 요청이 많습니다. 잠시 후 다시 시도해주세요.',
                                    data={'retryAfter': math.ceil(throttle.wait() or 60)})
                Inquiry.objects.create(userFK=user, email=user.email or '', **data)
        return Response(status=200 if existing else 201, data={'received': True})
