from django.contrib.auth.hashers import check_password, make_password
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination

from heart.models import Heart
from paper.serializer import UserShowPaperSerializer, PaperCreateSerializer, PaperSerializer, QueryIndexSerializer, \
	QueryIndexCreateSerializer
from user.models import User
from utils.response import Response
from rest_framework.views import APIView

from utils.share.functions import is_invited_user
from .models import Paper, QueryIndexTable


class UserPaperAPI(APIView):
	pagination_class = PageNumberPagination

	def get(self, request):
		type = request.GET.get("type", "all")

		# TODO hot한 롤페의 기준을 정해야 한다.
		if type == "hot":
			queryset = Paper.objects.all().order_by('-createdAt')[:6]
			return Response(
				data=UserShowPaperSerializer(queryset, many=True).data,
				status=status.HTTP_200_OK
				)

		queryset = Paper.objects.all().order_by('-createdAt')
		if queryset.count() == 0:
			return Response(status=status.HTTP_404_NOT_FOUND)

		paginator = self.pagination_class()
		page = paginator.paginate_queryset(queryset, request)  # <- 페이지 분할
		serializer = UserShowPaperSerializer(page, many=True)

		return Response(
			data=paginator.get_paginated_response(serializer.data).data,
			status=status.HTTP_200_OK
		)


	def post(self, request):
		serializer = PaperCreateSerializer(data=request.data)
		if serializer.is_valid():
			paper = serializer.save()
			return Response(
				data=PaperCreateSerializer(paper).data,
				status=status.HTTP_201_CREATED
				)
		return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)


	def delete(self, request):
		"""
		Paper 삭제
		"""
		user = User.objects.get(pk=request.user.id)
		paper = Paper.objects.get(code=request.data['pcode'])

		if paper.hostFK == user:
			paper.delete()
			return Response(status=status.HTTP_204_NO_CONTENT)
		else:
			if paper.invitingUser.filter(pk=user.pk).exists():
				return Response(status=470)
			else:
				return Response(status=471)


class MyPagePaperAPI(APIView):
	"""
	count
	1. 내가 작성한(호스트가 나)인 롤페

	card
	1. 내 롤페(내가 작성한(호스트)한 + 받은 롤페)
	2. 내가 참여한 롤페
	"""

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
			receiving_paper = Paper.objects.filter(receiverFK=user, receivingStat=1).order_by('-createdAt')
			data = UserShowPaperSerializer(receiving_paper, many=True).data

		elif request.GET.get("type") == 'host':
			receiving_paper = Paper.objects.filter(hostFK=user).order_by('-createdAt')
			data = UserShowPaperSerializer(receiving_paper, many=True).data

		elif request.GET.get("type") == 'inviting':
			my_paper = Paper.objects.filter(invitingUser=user).order_by('-createdAt')
			data = UserShowPaperSerializer(my_paper, many=True).data

		else:
			return Response(
				msg="Query Param type은 main, my, host, inviting이 존재합니다.",
				status=status.HTTP_400_BAD_REQUEST
				)


		paginator = self.pagination_class()
		page = paginator.paginate_queryset(data, request)  # <- 페이지 분할
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

		except Paper.DoesNotExist as e:
			return Response(msg=str(e), status=status.HTTP_404_NOT_FOUND)

		response = UserShowPaperSerializer(paper).data
		if is_invited_user(user=user, paper=paper):
			return Response(
				data=response,
				status=status.HTTP_200_OK
				)
		else:
			return Response(status=471)

	def post(self, request):
		serializer = PaperCreateSerializer(data=request.data)
		if serializer.is_valid():
			paper = serializer.save()
			# paper만든 순간 본인도 paper_invite_user에 insert
			paper.invitingUser.add(request.user)
			return Response(
				data=PaperCreateSerializer(paper).data,
				status=status.HTTP_201_CREATED
				)
		return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PaperEnterManageAPI(APIView):
	def post(self, request):
		pcode = request.data.get('pcode', None)

		if pcode is None:
			return Response(
				msg="pcode가 없습니다.",
				status=status.HTTP_400_BAD_REQUEST
				)

		if not request.user.is_authenticated:
			return Response(status=401)

		user = User.objects.get(pk=request.user.id)

		try:
			paper = Paper.objects.get(code=pcode)
		except Paper.DoesNotExist as e:
			return Response(msg=str(e), status=status.HTTP_404_NOT_FOUND)

		request_password = request.data.get('password', None)

		if paper.invitingUser.filter(pk=user.pk).exists():
			return Response(status=473)

		if paper.viewStat:
			paper.invitingUser.add(user)
			return Response(
				msg="추가 되었습니다.",
				status=status.HTTP_204_NO_CONTENT
				)
		else:
			if request_password is None:
				return Response(
					msg="password가 없습니다.",
					status=status.HTTP_400_BAD_REQUEST
					)

			if check_password(request_password, paper.password):
				paper.invitingUser.add(user)
				return Response(
					msg="추가 되었습니다.",
					status=status.HTTP_204_NO_CONTENT
					)
			else:
				return Response(status=472)


class PaperPasswordAPI(APIView):
	def post(self, request):
		"""
		Paper Password Change Check

		requirement: pcode, original_password
		"""
		pcode = request.data.get('pcode', None)
		original_password = request.data.get('original_password', None)

		if pcode is None:
			return Response(
				msg="pcode가 필요합니다.",
				status=status.HTTP_404_NOT_FOUND
				)

		if original_password is None:
			return Response(
				msg="기존 패스워드가 필요합니다.",
				status=status.HTTP_404_NOT_FOUND
				)

		paper = Paper.objects.get(code=pcode)

		if not check_password(original_password, paper.password):
			return Response(
				msg="기존 비밀번호와 다릅니다.",
				status=472
				)

		return Response(status=status.HTTP_200_OK)


	def put(self, request):
		"""
		Paper Password Change

		Requirement: pcode, original_password, change_password
		"""
		pcode = request.data.get('pcode', None)
		original_password = request.data.get('original_password', None)
		change_password = request.data.get('change_password', None)

		if pcode is None:
			return Response(
				msg="pcode가 필요합니다.",
				status=status.HTTP_404_NOT_FOUND
				)

		if original_password is None:
			return Response(
				msg="기존 패스워드가 필요합니다.",
				status=status.HTTP_404_NOT_FOUND
				)

		if change_password is None:
			return Response(
				msg="변경 패스워드가 필요합니다.",
				status=status.HTTP_404_NOT_FOUND
				)

		if original_password == change_password:
			return Response(
				msg="변경하려는 패스워드가 기존 패스워드와 일치합니다.",
				status=status.HTTP_404_NOT_FOUND
				)

		paper = Paper.objects.get(code=pcode)

		if not check_password(original_password, paper.password):
			return Response(
				msg="기존 비밀번호와 다릅니다.",
				status=472
				)

		paper.password = make_password(change_password)
		paper.save()

		return Response(
			msg="패스워드 변경 성공",
			status=status.HTTP_204_NO_CONTENT
			)


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
		serializer = QueryIndexCreateSerializer(data=request.data)
		if serializer.is_valid():
			index = serializer.save()
			return Response(
				data=QueryIndexSerializer(index).data,
				status=status.HTTP_201_CREATED
				)
		return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)







# TODO 1. [] 롤페 나가기
@api_view(['DELETE', 'POST'])
def quit_paper(request):
	pass

# TODO 2. [] 롤페 전달하기 (reciver에게 전송)
# TODO 3. [] 참여자(초대된 유저) 강퇴
# TODO 4. [] 롤페 종료 (삭제)
# 2025.04.11 김태은