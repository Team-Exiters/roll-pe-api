from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from engine.serializers import SearchCreateSerializer
from paper.models import Paper
from paper.serializer import UserShowPaperSerializer
from utils.response import Response


class SearchAPI(APIView):
	pagination_class = PageNumberPagination
	def get(self, request):
		filter = request.GET.get('f', None)
		try:
			keyword = request.GET.get('k')
		except:
			return Response(status=400, msg="Query Param k는 필수 요소입니다. (Keyword is Required)")

		if request.user.is_anonymous:
			return Response(status=status.HTTP_401_UNAUTHORIZED)

		queryset = Paper.objects.filter(title__icontains=keyword).order_by('-createdAt')
		if queryset.count() == 0:
			return Response(status=status.HTTP_404_NOT_FOUND)

		paginator = self.pagination_class()
		page = paginator.paginate_queryset(queryset, request)  # <- 페이지 분할
		serializer = UserShowPaperSerializer(page, many=True)

		return Response(data=paginator.get_paginated_response(serializer.data).data, status=status.HTTP_200_OK)