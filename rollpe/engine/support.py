import math

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from engine.models import Inquiry, Notice
from engine.notice_html import clean_notice_html
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


def published_notices():
    return Notice.objects.filter(isPublished=True, publishedAt__lte=timezone.now())


def notice_summary(notice):
    return {
        'id': notice.pk,
        'title': notice.title,
        'publishedAt': notice.publishedAt.isoformat(),
        'updatedAt': notice.updatedAt.isoformat(),
    }


class NoticesAPI(APIView):
    def get(self, request):
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(
            published_notices().only('id', 'title', 'publishedAt', 'updatedAt'), request,
        )
        items = [notice_summary(notice) for notice in page]
        return Response(status=200, data=paginator.get_paginated_response(items).data)


class NoticeAPI(APIView):
    def get(self, request, pk):
        notice = published_notices().filter(pk=pk).first()
        if notice is None:
            return Response(status=404)
        try:
            body = clean_notice_html(notice.body)
        except ValidationError:
            # Imported data may bypass the admin's validation; do not render an empty notice.
            return Response(status=404)
        return Response(status=200, data={**notice_summary(notice), 'body': body})
