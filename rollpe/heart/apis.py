from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from django.utils.timezone import localtime, now, make_aware
from datetime import datetime, time, timedelta

from utils.response import Response
from utils.share.functions import is_only_invited_user, is_valid_uuid, is_host
from paper.models import Paper
from heart.models import Heart
from heart.serializers import HeartReadSerializer, HeartWriteSerializer


class HeartAPI(APIView):
    pagination_class = PageNumberPagination
    def get(self, request):
        # 로그인 여부 검증
        if not request.user.is_authenticated:
            return Response(status=401)
        
        pcode = request.GET.get('pcode')
        hcode = request.GET.get('hcode')
        
        if hcode:
            # 상세정보 가져오기
            if not is_valid_uuid(hcode):
                return Response(status=404)
            
            try:
                heart_instance = Heart.objects.get(code=hcode)
            except Heart.DoesNotExist:
                return Response(status=404)
            
            paper_instance = heart_instance.paperFK
            
            is_public = paper_instance.viewStat
            
            if not is_public and not is_only_invited_user(request.user, paper_instance):
                return Response(status=471)
            
            serializer = HeartReadSerializer(heart_instance)
            
            return Response(
                data=serializer.data,
                status=200
            )
        else:
            # 목록 가져오기
            if not (pcode and is_valid_uuid(pcode)):
                return Response(status=404)
            
            try:
                paper_instance = Paper.objects.get(code=pcode)
            except Paper.DoesNotExist:
                return Response(status=404)
            
            is_public = paper_instance.viewStat
            
            # 비공개 롤링페이퍼일 경우 초대된 유저인지 검증
            if not is_public and not is_only_invited_user(request.user, paper_instance):
                return Response(status=471)
            
            heart_instance_list = Heart.objects.filter(paperFK__code=pcode).order_by('createdAt')
            
            my_heart = heart_instance_list.filter(userFK=request.user.id).first()
            my_pk = my_heart.id if my_heart else 0
            
            paginator = self.pagination_class()
            page = paginator.paginate_queryset(heart_instance_list, request)
            serializer = HeartReadSerializer(
                page, 
                is_public=is_public,
                my_pk=my_pk,
                many=True,
            )
            return Response(
                data=paginator.get_paginated_response(serializer.data).data,
                status=200
            )
            
    
    def post(self, request):
        # 로그인 여부 검증
        if not request.user.is_authenticated:
            return Response(status=401)
        
        # serialzier 검증
        serializer = HeartWriteSerializer(data=request.data, method='post')
        if not serializer.is_valid():
            return Response(data=serializer.errors, status=480)
        
        validated_data = serializer.validated_data
        
        # 존재하는 Paper인지 검증
        try:
            paper_instance = Paper.objects.get(pk=validated_data['paperFK'])
        except Paper.DoesNotExist:
            return Response(status=404)
        
        # 중복 작성 검증
        if Heart.objects.filter(userFK=request.user.id, paperFK=paper_instance.id).exists():
            return Response(status=482)
        
        # 중복 index 검증
        if Heart.objects.filter(location=validated_data['location'], paperFK=paper_instance.id).exists():
            return Response(status=485)
        
        # 비공개 롤링페이퍼일 경우만 검증
        if not paper_instance.viewStat and not is_only_invited_user(request.user, paper_instance):
            return Response(status=471)
        
        validated_data['userFK'] = request.user.id
        heart_instance = serializer.create(validated_data)
        read_serializer = HeartReadSerializer(Heart.objects.get(pk=heart_instance.id))
        
        return Response(
            data=read_serializer.data,
            status=201
        )
    
    
    def patch(self, request):
        # 로그인 여부 검증
        if not request.user.is_authenticated:
            return Response(status=401)

        serializer = HeartWriteSerializer(data=request.data, method='patch')
        if not serializer.is_valid():
            return Response(data=serializer.errors, status=480)
        
        heart_id = serializer.validated_data['heartPK']
        
        # 객체 존재 여부 검증
        try:
            heart_instance = Heart.objects.get(pk=heart_id)
        except Heart.DoesNotExist:
            return Response(status=404)
        
        # 작성자 검증
        if not heart_instance.userFK == request.user:
            return Response(status=481)
        
        # 수정 가능 유효 시간 검증
        datetime_value = make_aware(datetime.combine(heart_instance.paperFK.receivingDate, time.min))
        deadline = datetime_value - timedelta(days=1, seconds=1)
        current_time = localtime(now())
        
        if deadline < current_time:
            return Response(status=483)
        
        serializer.update(validated_data=serializer.validated_data)
        
        read_serializer = HeartReadSerializer(Heart.objects.get(pk=heart_id))
            
        return Response(
            data=read_serializer.data,
            status=200
        )
    
    def delete(self, request):
        
        if not request.user.is_authenticated:
            return Response(status=401)
        
        hcode = request.GET.get('hcode')
        
        if not is_valid_uuid(hcode):
            return Response(status=404)
        
        try:
            heart_instance = Heart.objects.get(code=hcode)
        except Heart.DoesNotExist:
            return Response(status=404)
        
        # 작성자 검증
        if not heart_instance.userFK == request.user:
            if not is_host(request.user, heart_instance.paperFK):
                return Response(status=470)
        
        heart_instance.delete()
        
        return Response(status=204)
    

@api_view(['GET'])
def get_my_heart_list(request):
    """"""
    if not request.user.is_authenticated:
            return Response(status=401)

    heart_instance_list = Heart.objects.filter(userFK=request.user).order_by('-createdAt')
    
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