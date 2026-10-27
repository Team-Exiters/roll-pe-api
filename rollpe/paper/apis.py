from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination

from heart.models import Heart
from paper.serializer import UserShowPaperSerializer, PaperCreateSerializer, PaperSettingsSerializer, QueryIndexSerializer, \
	QueryIndexCreateSerializer
from paper.lifecycle import delivered_paper_filter, is_delivered
from paper.invitations import accept_invitation
from user.models import User
from utils.response import Response
from rest_framework.views import APIView

from utils.share.functions import is_invited_user, is_blocked_user
from .models import Paper, PaperInvitation, QueryIndexTable


class UserPaperAPI(APIView):
	pagination_class = PageNumberPagination

	def get(self, request):
		type = request.GET.get("type", "all")
		# Discovery lists contain public papers only; private papers remain reachable
		# through the authenticated host/invitation lists and explicit entry links.
		queryset = Paper.objects.filter(viewStat=True)
		if request.user.is_authenticated:
			queryset = queryset.exclude(blockedUsers=request.user)
		queryset = queryset.order_by('-createdAt', '-pk')

		# TODO hot한 롤페의 기준을 정해야 한다.
		if type == "hot":
			return Response(
				data=UserShowPaperSerializer(queryset[:6], many=True, context={'listing': True}).data,
				status=status.HTTP_200_OK
				)

		if queryset.count() == 0:
			return Response(status=status.HTTP_404_NOT_FOUND)

		paginator = self.pagination_class()
		page = paginator.paginate_queryset(queryset, request)  # <- 페이지 분할
		serializer = UserShowPaperSerializer(page, many=True, context={'listing': True})

		return Response(
			data=paginator.get_paginated_response(serializer.data).data,
			status=status.HTTP_200_OK
		)


	def post(self, request):
		if not request.user.is_authenticated:
			return Response(status=status.HTTP_401_UNAUTHORIZED)
		serializer = PaperCreateSerializer(data=request.data, context={'request': request})
		if serializer.is_valid():
			paper = serializer.save(hostFK=request.user)
			return Response(
				data=PaperCreateSerializer(paper).data,
				status=status.HTTP_201_CREATED
				)
		return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)


	def delete(self, request):
		"""
		Paper 삭제
		"""
		if not request.user.is_authenticated:
			return Response(status=status.HTTP_401_UNAUTHORIZED)
		user = request.user
		pcode = request.data.get('pcode')
		if not pcode:
			return Response(status=400, msg="pcode가 필요합니다.")
		with transaction.atomic():
			try:
				# Heart mutations lock the same parent, so creation and deletion cannot race.
				paper = Paper.objects.select_for_update().get(code=pcode)
			except (ValidationError, ValueError, TypeError):
				return Response(status=400, msg="올바르지 않은 pcode입니다.")
			except Paper.DoesNotExist:
				return Response(status=404)

			if paper.hostFK_id != user.pk:
				return Response(status=470 if paper.invitingUser.filter(pk=user.pk).exists() else 471)
			if is_delivered(paper):
				return Response(status=483, msg="전달이 완료된 롤페는 삭제할 수 없습니다.")
			paper.delete()
			return Response(status=status.HTTP_204_NO_CONTENT)


class MyPagePaperAPI(APIView):
	"""개인 통계와 생성·수신·참여 목록. inviting은 기존 앱 호환용으로 유지합니다."""
	pagination_class = PageNumberPagination

	def get(self, request):
		user = request.user
		if user.is_anonymous:
			return Response(status=status.HTTP_401_UNAUTHORIZED)


		if request.GET.get("type") == 'main':
			host_paper = Paper.objects.filter(hostFK=user).count()
			heart = Heart.objects.filter(userFK=user).count()

			data = {
				"host": host_paper,
				"heart":heart
				}
			return Response(data=data, status=status.HTTP_200_OK)

		elif request.GET.get("type") == 'my':
			query = Paper.objects.filter(delivered_paper_filter(), receiverFK=user).order_by('-createdAt')

		elif request.GET.get("type") == 'host':
			query = Paper.objects.filter(hostFK=user)

		elif request.GET.get("type") == 'inviting':
			query = Paper.objects.filter(invitingUser=user)

		elif request.GET.get("type") == 'participating':
			# Keep the legacy inviting list; the new menu means active participation,
			# independently of pending invitations and papers hosted by this user.
			query = Paper.objects.filter(invitingUser=user).exclude(hostFK=user).exclude(delivered_paper_filter())

		else:
			return Response(
				msg="Query Param type은 main, my, host, inviting, participating이 존재합니다.",
				status=status.HTTP_400_BAD_REQUEST
				)

		query = (query.exclude(blockedUsers=user)
				 .select_related('hostFK', 'receiverFK', 'themeFK', 'sizeFK', 'ratioFK')
				 .order_by('-createdAt', '-pk'))

		if request.GET.get('type') != 'participating' and not query.exists():
			return Response(
				data=[],
				status=status.HTTP_200_OK
				)


		paginator = self.pagination_class()
		page = paginator.paginate_queryset(query, request)  # <- 페이지 분할
		serializer = UserShowPaperSerializer(page, many=True, context={'listing': True})


		return Response(
			data=paginator.get_paginated_response(serializer.data).data,
            status=status.HTTP_200_OK
			)


class PaperAPI(APIView):
	# TODO 1. [x] Rollpe response에 invitedUser 누락 추가 요청드립니다.
	# TODO 2. [x] 롤페 생성 API에 유저 추가 위해 Request Body에 invitedUser 추가 부탁드립니다.
	# 2025.03.27 정승민



	def get(self, request):
		"""
		Paper Detail Info
		"""
		pcode = request.query_params.get('pcode', None)

		if pcode is None:
			return Response(
				msg="pcode가 필요합니다.",
				status=status.HTTP_404_NOT_FOUND
				)

		if not request.user.is_authenticated:
			return Response(status=401)

		user = User.objects.get(pk=request.user.id)
		try:
			paper = Paper.objects.get(code=pcode)

		except (ValidationError, ValueError, TypeError):
			return Response(status=400, msg="올바르지 않은 pcode입니다.")
		except Paper.DoesNotExist as e:
			return Response(msg=str(e), status=status.HTTP_404_NOT_FOUND)

		if is_blocked_user(user, paper):
			return Response(status=403, msg='이 롤페에 다시 참여할 수 없습니다.')

		# Once delivered, host/writer membership and public visibility no longer grant access.
		delivered = is_delivered(paper)
		can_read = paper.receiverFK_id == user.pk if delivered else is_invited_user(user=user, paper=paper)
		if can_read:
			return Response(
				data=UserShowPaperSerializer(paper).data,
				status=status.HTTP_200_OK
				)
		else:
			# Entry prompts need only visibility and availability, never private contents.
			invitation = PaperInvitation.objects.filter(paper=paper, user=user, status=PaperInvitation.Status.PENDING, paper__hostFK__is_active=True).first()
			return Response(status=471, data={
				'code': str(paper.code),
				'title': paper.title if paper.viewStat or invitation else '',
				'viewStat': paper.viewStat,
				'canEnter': not delivered,
				**({'invitationCode': str(invitation.code)} if invitation else {}),
			})

	def post(self, request):
		if not request.user.is_authenticated:
			return Response(status=status.HTTP_401_UNAUTHORIZED)
		serializer = PaperCreateSerializer(data=request.data, context={'request': request})
		if serializer.is_valid():
			paper = serializer.save(hostFK=request.user)
			# paper만든 순간 본인도 paper_invite_user에 insert
			paper.invitingUser.add(request.user)
			return Response(
				data=PaperCreateSerializer(paper).data,
				status=status.HTTP_201_CREATED
				)
		return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

	def patch(self, request):
		if not request.user.is_authenticated:
			return Response(status=401)
		if not isinstance(request.data, dict) or not isinstance(request.data.get('pcode'), str):
			return Response(status=400, msg='pcode와 수정할 설정이 필요합니다.')
		with transaction.atomic():
			try:
				paper = Paper.objects.select_for_update().get(code=request.data['pcode'])
			except (ValidationError, ValueError, TypeError):
				return Response(status=400, msg='올바르지 않은 pcode입니다.')
			except Paper.DoesNotExist:
				return Response(status=404)
			if paper.hostFK_id != request.user.pk or is_blocked_user(request.user, paper):
				return Response(status=403, msg='방장만 롤페 설정을 수정할 수 있습니다.')
			if is_delivered(paper):
				return Response(status=483, msg='전달이 완료된 롤페는 수정할 수 없습니다.')
			serializer = PaperSettingsSerializer(paper, data={key: value for key, value in request.data.items() if key != 'pcode'})
			if not serializer.is_valid():
				return Response(status=400, msg='롤페 설정을 확인해주세요.', data=serializer.errors)
			paper = serializer.save()
			return Response(status=200, msg='롤페 설정을 변경하였습니다.', data={
				'code': str(paper.code), 'viewStat': paper.viewStat, 'receivingDate': paper.receivingDate,
			})

class PaperSendAPI(APIView):
    """Close writing early and deliver to the receiver selected when the paper was created."""

    def post(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        pcode = request.data.get('pcode')
        if not pcode:
            return Response(status=400, msg='pcode가 필요합니다.')
        with transaction.atomic():
            try:
                paper = Paper.objects.select_for_update().get(code=pcode)
            except (ValidationError, ValueError, TypeError):
                return Response(status=400, msg='올바르지 않은 pcode입니다.')
            except Paper.DoesNotExist:
                return Response(status=404)
            if paper.hostFK_id != request.user.pk:
                return Response(status=470 if paper.invitingUser.filter(pk=request.user.pk).exists() else 471)
            if paper.receiverFK_id is None or not User.objects.filter(pk=paper.receiverFK_id, is_active=True).exists():
                return Response(status=400, msg='전달할 수신자를 확인해주세요.')
            if paper.receivingStat != 1:
                # Avoid Paper.save(), which rehashes an existing private-paper password.
                Paper.objects.filter(pk=paper.pk).update(receivingStat=1, updatedAt=timezone.now())
            return Response(status=200, msg='롤페를 전달하였습니다.',
                            data={'code': str(paper.code), 'receivingStat': 1})


class PaperEnterManageAPI(APIView):
    def post(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        pcode = request.data.get('pcode')
        if not isinstance(pcode, str) or not pcode:
            return Response(status=400)
        with transaction.atomic():
            try:
                paper = Paper.objects.select_for_update().get(code=pcode)
            except (ValidationError, ValueError, TypeError):
                return Response(status=400)
            except Paper.DoesNotExist:
                return Response(status=404)
            if is_blocked_user(request.user, paper):
                return Response(status=403, msg='이 롤페에 다시 참여할 수 없습니다.')
            if paper.invitingUser.filter(pk=request.user.pk).exists():
                return Response(status=473)
            if is_delivered(paper):
                return Response(status=483)
            invitation = PaperInvitation.objects.filter(paper=paper, user=request.user, status=PaperInvitation.Status.PENDING, paper__hostFK__is_active=True).first()
            if invitation is not None:
                accept_invitation(invitation)
                return Response(status=204)
            if not paper.viewStat:
                password = request.data.get('password')
                if not isinstance(password, str) or not password:
                    return Response(status=400)
                if not check_password(password, paper.password):
                    return Response(status=472)
            paper.invitingUser.add(request.user)
            return Response(status=204)


class QueryIndexAPI(APIView):
	def get(self, request):

		# if request.user.is_anonymous:
		# 	return Response(status=401)

		query_type = request.GET.get("type", "all").upper()

		if query_type == "ALL":
			queryset = QueryIndexTable.objects.all()
		else:
			queryset = QueryIndexTable.objects.filter(type=query_type)

		response = QueryIndexSerializer(queryset, many=True).data

		return Response(
			data=response,
			status=status.HTTP_200_OK
		)

	def post(self, request):
		if not request.user.is_authenticated:
			return Response(status=status.HTTP_401_UNAUTHORIZED)
		if not request.user.is_staff:
			return Response(status=status.HTTP_403_FORBIDDEN)
		serializer = QueryIndexCreateSerializer(data=request.data)
		if serializer.is_valid():
			index = serializer.save()
			return Response(
				data=QueryIndexSerializer(index).data,
				status=status.HTTP_201_CREATED
				)
		return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)
