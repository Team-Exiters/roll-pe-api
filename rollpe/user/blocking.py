from contextlib import contextmanager

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from user.models import User, UserBlock
from user.serializers import UserViewSerializer
from utils.response import Response


def blocked_ids(user):
    if not user.is_authenticated:
        return User.objects.none().values_list('pk', flat=True)
    return UserBlock.objects.filter(blocker=user).values_list('blocked_id', flat=True)


def related_block_ids(user):
    return User.objects.filter(Q(blocked_by__blocker=user) | Q(blocked_users__blocked=user)).values_list('pk', flat=True)


def has_block(blocker, blocked_id):
    return blocker.is_authenticated and UserBlock.objects.filter(blocker=blocker, blocked_id=blocked_id).exists()


def blocked_pair(first_id, second_id):
    return UserBlock.objects.filter(Q(blocker_id=first_id, blocked_id=second_id) |
                                    Q(blocker_id=second_id, blocked_id=first_id)).exists()


@contextmanager
def locked_users(first_id, second_id):
    # Serialize blocking and invitations in a stable order, including across workers.
    with transaction.atomic():
        list(User.objects.select_for_update().filter(pk__in=[first_id, second_id]).order_by('pk'))
        yield


class BlockInput(serializers.Serializer):
    userId = serializers.IntegerField(min_value=1)


class UserBlocksAPI(APIView):
    def get(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        users = User.objects.filter(blocked_by__blocker=request.user).order_by('-blocked_by__createdAt', '-pk')
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(users, request)
        return Response(status=200, data=paginator.get_paginated_response(UserViewSerializer(page, many=True).data).data)

    def post(self, request):
        return self.change(request, blocking=True)

    def delete(self, request):
        return self.change(request, blocking=False)

    def change(self, request, blocking):
        if not request.user.is_authenticated:
            return Response(status=401)
        data = BlockInput(data=request.data)
        if not data.is_valid():
            return Response(status=400)
        target_id = data.validated_data['userId']
        if target_id == request.user.pk:
            return Response(status=400)
        with locked_users(request.user.pk, target_id):
            if blocking:
                if not User.objects.filter(pk=target_id, is_active=True).exists():
                    return Response(status=404)
                UserBlock.objects.get_or_create(blocker=request.user, blocked_id=target_id)
                from paper.models import PaperInvitation
                invitations = list(PaperInvitation.objects.filter(
                    Q(paper__hostFK=request.user, user_id=target_id) |
                    Q(paper__hostFK_id=target_id, user=request.user),
                    status=PaperInvitation.Status.PENDING,
                ).values_list('pk', flat=True))
                # Update by ID so this write never locks joined paper rows after user rows.
                PaperInvitation.objects.filter(pk__in=invitations).update(
                    status=PaperInvitation.Status.DENIED, respondedAt=timezone.now(), updatedAt=timezone.now())
            else:
                UserBlock.objects.filter(blocker=request.user, blocked_id=target_id).delete()
        return Response(status=204)
