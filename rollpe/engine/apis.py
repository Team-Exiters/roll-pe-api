from rest_framework import status
from rest_framework.views import APIView

from engine.serializers import SearchCreateSerializer
from paper.models import Paper
from paper.serializer import UserShowPaperSerializer
from utils.response import Response


class SearchAPI(APIView):
	def get(self, request):
		filter = request.GET.get('f', None)
		try:
			keyword = request.GET.get('k')
		except:
			return Response(status=400, msg="Query Param k는 필수 요소입니다. (Keyword is Required)")

		if request.user.is_anonymous:
			return Response(status=status.HTTP_401_UNAUTHORIZED)

		result_queryset = Paper.objects.filter(title__icontains=keyword)
		result_paper = UserShowPaperSerializer(result_queryset, many=True).data

		return Response(data=result_paper, status=status.HTTP_200_OK)