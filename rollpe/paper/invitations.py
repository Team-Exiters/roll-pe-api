import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from paper.lifecycle import delivered_paper_filter, is_delivered
from paper.models import Paper, PaperInvitation
from utils.response import Response
from utils.share.functions import is_blocked_user


def invite_user(paper, user):
    """Caller holds the paper lock; an existing membership is never changed."""
    if user.pk == paper.hostFK_id or paper.invitingUser.filter(pk=user.pk).exists():
        return Response(status=409, data={'reason': 'alreadyMember'})
    invitation, created = PaperInvitation.objects.get_or_create(paper=paper, user=user)
    if not created and invitation.status != PaperInvitation.Status.PENDING:
        # A new invitation gets a new identity, so an old response cannot settle it.
        invitation.code = uuid.uuid4()
        invitation.status = PaperInvitation.Status.PENDING
        invitation.respondedAt = None
        invitation.save(update_fields=['code', 'status', 'respondedAt', 'updatedAt'])
    return Response(status=204)


def accept_invitation(invitation):
    """Caller holds the paper lock, shared by membership, delivery and deletion."""
    invitation.paper.invitingUser.add(invitation.user)
    invitation.status = PaperInvitation.Status.ACCEPTED
    invitation.respondedAt = timezone.now()
    invitation.save(update_fields=['status', 'respondedAt', 'updatedAt'])


class InvitationResponseInput(serializers.Serializer):
    invitationCode = serializers.UUIDField()
    action = serializers.ChoiceField(choices=['accept', 'deny'])


class PaperInvitationsAPI(APIView):
    def get(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        query = (PaperInvitation.objects.filter(user=request.user, status=PaperInvitation.Status.PENDING,
                                               paper__hostFK__is_active=True)
                 .exclude(paper__in=Paper.objects.filter(delivered_paper_filter()))
                 .exclude(paper__blockedUsers=request.user)
                 .exclude(paper__invitingUser=request.user)
                 .select_related('paper__hostFK', 'paper__themeFK')
                 .order_by('-updatedAt', '-pk'))
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(query, request)
        # Pending invitees may see their invitation summary, never hearts or members.
        items = [{
            'invitationCode': str(invitation.code), 'sentAt': invitation.updatedAt,
            'code': str(invitation.paper.code), 'title': invitation.paper.title,
            'theme': invitation.paper.themeFK.name, 'host': {'name': invitation.paper.hostFK.name},
            'receivingDate': invitation.paper.receivingDate, 'isPublic': invitation.paper.viewStat,
        } for invitation in page]
        return Response(status=200, data=paginator.get_paginated_response(items).data)

    def post(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        data = InvitationResponseInput(data=request.data)
        if not data.is_valid():
            return Response(status=400)
        code = data.validated_data['invitationCode']
        # Resolve identity first, then always lock the parent before the invitation.
        paper_id = PaperInvitation.objects.filter(code=code, user=request.user).values_list('paper_id', flat=True).first()
        if paper_id is None:
            return Response(status=404)
        with transaction.atomic():
            try:
                paper = Paper.objects.select_for_update().get(pk=paper_id)
                invitation = PaperInvitation.objects.select_related('user').get(code=code, user=request.user, paper=paper)
            except (Paper.DoesNotExist, PaperInvitation.DoesNotExist, ValidationError):
                return Response(status=404)
            if is_blocked_user(request.user, paper) or not paper.hostFK.is_active:
                return Response(status=403)
            desired = PaperInvitation.Status.ACCEPTED if data.validated_data['action'] == 'accept' else PaperInvitation.Status.DENIED
            if invitation.status != PaperInvitation.Status.PENDING:
                return Response(status=204 if invitation.status == desired else 409)
            if is_delivered(paper):
                return Response(status=483)
            if desired == PaperInvitation.Status.ACCEPTED:
                accept_invitation(invitation)
            else:
                invitation.status = desired
                invitation.respondedAt = timezone.now()
                invitation.save(update_fields=['status', 'respondedAt', 'updatedAt'])
            return Response(status=204)
