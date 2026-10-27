from django.db import transaction
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from heart.models import Heart
from heart.serializers import HeartReadSerializer, HeartWriteSerializer
from paper.models import Paper, QueryIndexTable
from paper.lifecycle import delivered_paper_filter, is_delivered
from utils.response import Response
from utils.share.functions import is_invited_user, is_valid_uuid, is_host, is_blocked_user


def can_read(paper, user):
    if is_blocked_user(user, paper):
        return False
    if is_delivered(paper):
        return paper.receiverFK_id == user.pk
    return paper.viewStat or is_invited_user(user, paper)


def mutation_error(paper, user, data=None):
    if is_blocked_user(user, paper):
        return Response(status=403, msg='이 롤페에 다시 참여할 수 없습니다.')
    if not paper.viewStat and not is_invited_user(user, paper):
        return Response(status=471)
    if is_delivered(paper):
        return Response(status=483, msg='롤페가 종료되어 마음을 변경할 수 없습니다.')
    if data is not None:
        maximum = paper.sizeFK.query.get('max', 12)
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
            maximum = 12
        if data['location'] >= maximum:
            return Response(status=480)
    return None


def selected_color(paper, name):
    palette = 'MONOCOLOR' if paper.themeFK.name == '추모' else 'COLOR'
    return QueryIndexTable.objects.filter(type=palette, name__iexact=name.lstrip('#')).order_by('id').first()


class HeartAPI(APIView):
    pagination_class = PageNumberPagination

    def get(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        hcode = request.GET.get('hcode')
        pcode = request.GET.get('pcode')
        if not is_valid_uuid(hcode or pcode):
            return Response(status=404)
        if hcode:
            heart = Heart.objects.select_related('paperFK').filter(code=hcode).first()
            if heart is None:
                return Response(status=404)
            if not can_read(heart.paperFK, request.user):
                return Response(status=471)
            return Response(data=HeartReadSerializer(heart).data, status=200)
        paper = Paper.objects.filter(code=pcode).first()
        if paper is None:
            return Response(status=404)
        if not can_read(paper, request.user):
            return Response(status=471)
        hearts = Heart.objects.filter(paperFK=paper).order_by('createdAt')
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(hearts, request)
        return Response(data=paginator.get_paginated_response(HeartReadSerializer(page, many=True).data).data, status=200)

    def post(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        serializer = HeartWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(data=serializer.errors, status=480)
        data = serializer.validated_data
        # Every mutation locks the parent first, serializing writes without altering historical data.
        with transaction.atomic():
            paper = Paper.objects.select_for_update().filter(pk=data['paperFK']).first()
            if paper is None:
                return Response(status=404)
            error = mutation_error(paper, request.user, data)
            if error is not None:
                return error
            if Heart.objects.filter(userFK=request.user, paperFK=paper).exists():
                return Response(status=482)
            if Heart.objects.filter(location=data['location'], paperFK=paper).exists():
                return Response(status=485)
            color = selected_color(paper, data['color'])
            if color is None:
                return Response(status=480)
            heart = serializer.save(userFK=request.user, paperFK=paper, colorFK=color)
            return Response(data=HeartReadSerializer(heart).data, status=201)

    def patch(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        serializer = HeartWriteSerializer(data=request.data, method='patch')
        if not serializer.is_valid():
            return Response(data=serializer.errors, status=480)
        data = serializer.validated_data
        with transaction.atomic():
            paper = Paper.objects.select_for_update().filter(pk=data['paperFK']).first()
            if paper is None:
                return Response(status=404)
            heart = Heart.objects.filter(pk=data['heartPK']).first()
            if heart is None:
                return Response(status=404)
            if heart.userFK_id != request.user.pk:
                return Response(status=481)
            if heart.paperFK_id != paper.pk or heart.location != data['location']:
                return Response(status=480)
            error = mutation_error(paper, request.user, data)
            if error is not None:
                return error
            color = selected_color(paper, data['color'])
            if color is None:
                return Response(status=480)
            heart = serializer.update(heart, {**data, 'colorFK': color})
            return Response(data=HeartReadSerializer(heart).data, status=200)

    def delete(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        hcode = request.GET.get('hcode')
        if not is_valid_uuid(hcode):
            return Response(status=404)
        with transaction.atomic():
            target = Heart.objects.filter(code=hcode).values('paperFK_id').first()
            if target is None:
                return Response(status=404)
            paper = Paper.objects.select_for_update().filter(pk=target['paperFK_id']).first()
            heart = Heart.objects.filter(code=hcode).first()
            if paper is None or heart is None:
                return Response(status=404)
            if heart.userFK_id != request.user.pk and not is_host(request.user, paper):
                return Response(status=470)
            error = mutation_error(paper, request.user)
            if error is not None:
                return error
            heart.delete()
            return Response(status=204)


@api_view(['GET'])
def get_my_heart_list(request):
    """"""
    if not request.user.is_authenticated:
            return Response(status=401)

    # Authorship does not retain access to a paper after it has been delivered.
    heart_instance_list = (Heart.objects.filter(userFK=request.user)
                           .filter(Q(paperFK__receiverFK=request.user) | ~delivered_paper_filter('paperFK__'))
                           .exclude(paperFK__blockedUsers=request.user).order_by('-createdAt', '-pk'))
    
    pagination_class = PageNumberPagination
    paginator = pagination_class()
    page = paginator.paginate_queryset(heart_instance_list, request)
    
    serializer = HeartReadSerializer(
        page, 
        many=True,
    )
    return Response(
        data=paginator.get_paginated_response(serializer.data).data,
        status=200
    )
