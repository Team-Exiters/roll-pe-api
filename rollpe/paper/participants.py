from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework.views import APIView

from heart.models import Heart
from paper.lifecycle import is_delivered
from paper.models import Paper
from user.models import User
from user.serializers import UserViewSerializer
from utils.response import Response
from utils.share.functions import is_blocked_user


def find_paper(request, lock=False):
    if not request.user.is_authenticated:
        return None, Response(status=401)
    code = (request.query_params if request.method == 'GET' else request.data).get('pcode')
    if not isinstance(code, str) or not code:
        return None, Response(status=400)
    try:
        query = Paper.objects.select_for_update() if lock else Paper.objects
        paper = query.get(code=code)
    except (ValidationError, ValueError, TypeError):
        return None, Response(status=400)
    except Paper.DoesNotExist:
        return None, Response(status=404)
    if is_blocked_user(request.user, paper):
        return None, Response(status=403, data={'reason': 'blocked'})
    return paper, None


def host_error(paper, user):
    if paper.hostFK_id != user.pk:
        return Response(status=403, data={'reason': 'hostOnly'})
    if is_delivered(paper):
        return Response(status=483)
    return None


class ParticipantInput(serializers.Serializer):
    userId = serializers.IntegerField(min_value=1)


class PaperParticipantsAPI(APIView):
    def get(self, request):
        paper, error = find_paper(request)
        if error is not None:
            return error
        error = host_error(paper, request.user)
        if error is not None:
            return error
        hearts = {heart.userFK_id: heart for heart in Heart.objects.filter(paperFK=paper)}
        ids = set(paper.invitingUser.values_list('pk', flat=True)) | set(hearts) | {paper.hostFK_id}
        users = User.objects.filter(pk__in=ids, is_active=True).exclude(blocked_papers=paper).order_by('name', 'id')
        return Response(status=200, data={'users': [{
            **UserViewSerializer(user).data,
            'isHost': user.pk == paper.hostFK_id,
            'isReceiver': user.pk == paper.receiverFK_id,
            'hasWritten': user.pk in hearts,
            'revisionCount': hearts[user.pk].revisionCount if user.pk in hearts else 0,
            'heartCode': str(hearts[user.pk].code) if user.pk in hearts else None,
        } for user in users]})

    def post(self, request):
        return self.change(request, kicking=False)

    def delete(self, request):
        return self.change(request, kicking=True)

    def change(self, request, kicking):
        with transaction.atomic():
            paper, error = find_paper(request, lock=True)
            if error is not None:
                return error
            error = host_error(paper, request.user)
            if error is not None:
                return error
            data = ParticipantInput(data=request.data)
            if not data.is_valid():
                return Response(status=400)
            target = User.objects.filter(pk=data.validated_data['userId'], is_active=True).first()
            if target is None:
                return Response(status=404, data={'reason': 'userMissing'})
            if kicking:
                # The host cannot leave through a kick; delivery must retain its designated receiver.
                if target.pk in (paper.hostFK_id, paper.receiverFK_id):
                    return Response(status=403, data={'reason': 'protected'})
                if paper.blockedUsers.filter(pk=target.pk).exists():
                    return Response(status=204)
                if not paper.invitingUser.filter(pk=target.pk).exists() and not Heart.objects.filter(paperFK=paper, userFK=target).exists():
                    return Response(status=404)
                Heart.objects.filter(paperFK=paper, userFK=target).delete()
                paper.invitingUser.remove(target)
                paper.blockedUsers.add(target)
            else:
                if paper.blockedUsers.filter(pk=target.pk).exists():
                    return Response(status=403, data={'reason': 'blocked'})
                paper.invitingUser.add(target)
            return Response(status=204)


class PaperLeaveAPI(APIView):
    def post(self, request):
        with transaction.atomic():
            paper, error = find_paper(request, lock=True)
            if error is not None:
                return error
            if paper.hostFK_id == request.user.pk:
                return Response(status=403, data={'reason': 'hostCannotLeave'})
            if is_delivered(paper):
                return Response(status=483)
            # Repeating leave is harmless; it never creates a ban or changes the receiving account.
            Heart.objects.filter(paperFK=paper, userFK=request.user).delete()
            paper.invitingUser.remove(request.user)
            return Response(status=204)
