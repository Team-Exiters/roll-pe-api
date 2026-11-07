import math

from django.db import transaction
from rest_framework import serializers
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from heart.apis import can_read
from heart.models import Heart
from paper.models import Paper
from user.blocking import blocked_ids, has_block
from user.models import ContentReport
from utils.response import Response


class ReportInput(serializers.Serializer):
    targetType = serializers.ChoiceField(choices=ContentReport.Target.choices)
    targetCode = serializers.UUIDField()
    reason = serializers.ChoiceField(choices=ContentReport.Reason.choices)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=True)


class ReportRateThrottle(UserRateThrottle):
    scope = 'content_report'
    rate = '20/day'


def heart_snapshot(heart):
    return {'code': str(heart.code), 'index': heart.location, 'authorId': heart.userFK_id,
            'content': heart.context, 'color': heart.colorFK.name, 'revisionCount': heart.revisionCount}


def content_snapshot(paper, heart, viewer):
    snapshot = {'title': paper.title, 'paperCode': str(paper.code)}
    if heart is not None:
        snapshot['heart'] = heart_snapshot(heart)
    else:
        # Paper reports include only memos visible to the reporter.
        hearts = (Heart.objects.filter(paperFK=paper)
                  .exclude(userFK_id__in=blocked_ids(viewer))
                  .select_related('colorFK').order_by('location', 'pk'))
        snapshot['hearts'] = [heart_snapshot(item) for item in hearts]
    return snapshot


class ContentReportsAPI(APIView):
    def post(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        throttle = ReportRateThrottle()
        if not throttle.allow_request(request, self):
            return Response(status=429, msg='신고 요청이 많습니다. 잠시 후 다시 시도해주세요.',
                            data={'retryAfter': math.ceil(throttle.wait() or 60)})
        serializer = ReportInput(data=request.data)
        if not serializer.is_valid():
            return Response(status=400, msg='신고 대상과 사유를 확인해주세요.')
        data = serializer.validated_data
        code = data['targetCode']
        heart_target = data['targetType'] == ContentReport.Target.HEART
        if heart_target:
            paper_id = Heart.objects.filter(code=code).values_list('paperFK_id', flat=True).first()
            paper_filter = {'pk': paper_id}
        else:
            paper_filter = {'code': code}
        # Share the parent lock with edits, deletion and delivery so evidence matches visible content.
        with transaction.atomic():
            paper = Paper.objects.select_for_update().filter(**paper_filter).first()
            if paper is None:
                return Response(status=404)
            if not can_read(paper, request.user):
                return Response(status=403)
            heart = Heart.objects.select_related('colorFK').filter(code=code, paperFK=paper).first() if heart_target else None
            if heart_target and heart is None:
                return Response(status=404)
            author_id = heart.userFK_id if heart is not None else paper.hostFK_id
            if has_block(request.user, author_id):
                return Response(status=403)
            if author_id == request.user.pk:
                return Response(status=400, msg='본인의 콘텐츠는 신고할 수 없습니다.')
            _, created = ContentReport.objects.get_or_create(
                reporterFK=request.user, targetType=data['targetType'], targetCode=code,
                defaults={
                    'reportedUserFK_id': author_id, 'paperFK': paper, 'heartFK': heart,
                    'reason': data['reason'], 'description': data.get('description', ''),
                    # Defaults are evaluated only for a new report, while holding the paper lock.
                    'snapshot': lambda: content_snapshot(paper, heart, request.user),
                },
            )
        return Response(status=201 if created else 200,
                        msg='신고가 접수되었습니다.' if created else '이미 신고가 접수된 콘텐츠입니다.',
                        data={'alreadyReported': not created})
