from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination

from heart.models import Heart
from paper.serializer import UserShowPaperSerializer, PaperCreateSerializer, QueryIndexSerializer, \
	QueryIndexCreateSerializer
from paper.lifecycle import delivered_paper_filter, is_delivered
from user.models import User
from utils.response import Response
from rest_framework.views import APIView

from utils.share.functions import is_invited_user, is_blocked_user
from .models import Paper, QueryIndexTable


class UserPaperAPI(APIView):
	pagination_class = PageNumberPagination

	def get(self, request):
		type = request.GET.get("type", "all")

		# TODO hot한 롤페의 기준을 정해야 한다.
		if type == "hot":
			queryset = Paper.objects.exclude(blockedUsers=request.user).order_by('-createdAt')[:6] if request.user.is_authenticated else Paper.objects.all().order_by('-createdAt')[:6]
			return Response(
				data=UserShowPaperSerializer(queryset, many=True, context={'listing': True}).data,
				status=status.HTTP_200_OK
				)

		queryset = Paper.objects.exclude(blockedUsers=request.user).order_by('-createdAt') if request.user.is_authenticated else Paper.objects.all().order_by('-createdAt')
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
	"""
	count
	1. 내가 작성한(호스트가 나)인 롤페

	card
	1. 내 롤페(내가 작성한(호스트)한 + 받은 롤페)
	2. 내가 참여한 롤페
	"""
	pagination_class = PageNumberPagination

	def get(self, request):
		user = request.user
		if user.is_anonymous:
			return Response(status=status.HTTP_401_UNAUTHORIZED)


		if request.GET.get("type") == 'main':
			host_paper = len(Paper.objects.filter(hostFK=user))
			heart = len(Heart.objects.filter(userFK=user))

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

		else:
			return Response(
				msg="Query Param type은 main, my, host, inviting이 존재합니다.",
				status=status.HTTP_400_BAD_REQUEST
				)

		if len(query) == 0 :
			return Response(
				data=[],
				status=status.HTTP_200_OK
				)


		paginator = self.pagination_class()
		page = paginator.paginate_queryset(query, request)  # <- 페이지 분할
		serializer = UserShowPaperSerializer(page, many=True)


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

		# Delivery makes the receiver eligible to read even without writer membership.
		can_receive = paper.receiverFK_id == user.pk and is_delivered(paper)
		if is_invited_user(user=user, paper=paper) or can_receive:
			return Response(
				data=UserShowPaperSerializer(paper).data,
				status=status.HTTP_200_OK
				)
		else:
			return Response(status=471)

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
