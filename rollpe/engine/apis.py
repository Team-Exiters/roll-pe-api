from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from paper.models import Paper
from paper.lifecycle import delivered_paper_filter
from paper.serializer import UserShowPaperSerializer
from utils.response import Response


class SearchAPI(APIView):
	pagination_class = PageNumberPagination
	def get(self, request):
		keyword = request.GET.get('k')
		if keyword is None or not keyword.strip() or len(keyword.strip()) > 100:
			return Response(status=400, msg="Query Param k는 필수 요소입니다. (Keyword is Required)")

		if request.user.is_anonymous:
			return Response(status=status.HTTP_401_UNAUTHORIZED)

		queryset = Paper.objects.filter(viewStat=True, title__icontains=keyword.strip()).exclude(
			delivered_paper_filter()
		).exclude(blockedUsers=request.user).select_related(
			'hostFK', 'receiverFK', 'themeFK', 'sizeFK', 'ratioFK'
		).order_by('-createdAt', '-pk')

		paginator = self.pagination_class()
		page = paginator.paginate_queryset(queryset, request)  # <- 페이지 분할
		serializer = UserShowPaperSerializer(page, many=True, context={'listing': True})

		return Response(data=paginator.get_paginated_response(serializer.data).data, status=status.HTTP_200_OK)
