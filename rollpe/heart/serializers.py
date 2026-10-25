from rest_framework import serializers
from django.utils.timezone import localtime
from django.db import transaction

from user.models import User
from paper.models import Paper, QueryIndexTable
from heart.models import Heart, HeartRevision
from user.serializers import UserViewSerializer

# class HeartReadSerializer(serializers.ModelSerializer):
    
#     def __init__(self, *args, **kwargs):
#         self.is_public = kwargs.pop('is_public', True)
#         self.my_pk = kwargs.pop('my_pk', 0)
#         super().__init__(*args, **kwargs)

#     userName = serializers.CharField(source='userFK.name')
#     rollingPaperName = serializers.CharField(source='paperFK.title')
#     createdAt = serializers.SerializerMethodField()
#     blur=serializers.SerializerMethodField()
#     color=serializers.CharField(source='colorFK.name')

#     class Meta:
#         model = Heart
#         fields = ('id', 'userName', 'rollingPaperName', 'context', 'danger', 'createdAt', 'location', 'blur', 'code', 'color')
       
#     def get_createdAt(self, obj):
#         return localtime(obj.createdAt).strftime('%Y.%m.%d')    
    
#     def get_blur(self, obj):
#         if self.is_public or self.my_pk == 0 or self.my_pk >= obj.id:
#             return False
#         return True
    
    
class HeartReadSerializer(serializers.ModelSerializer):
    
    def __init__(self, *args, **kwargs):
        self.is_public = kwargs.pop('is_public', True)
        self.my_pk = kwargs.pop('my_pk', 0)
        super().__init__(*args, **kwargs)

    # userName = serializers.CharField(source='userFK.name')
    # rollingPaperName = serializers.CharField(source='paperFK.title')
    # createdAt = serializers.SerializerMethodField()
    # blur=serializers.SerializerMethodField()
    
    index = serializers.IntegerField(source='location')
    author = UserViewSerializer(source='userFK')
    content = serializers.CharField(source='context')
    createdAt = serializers.SerializerMethodField()
    color = serializers.CharField(source='colorFK.name')
    version = serializers.SerializerMethodField()
    code = serializers.CharField()
    

    class Meta:
        model = Heart
        fields = ('id', 'index', 'author', 'content', 'createdAt', 'color', 'version', 'code', 'revisionCount')
        depth = 1
       
    def get_createdAt(self, obj):
        return localtime(obj.createdAt).strftime('%Y.%m.%d')  
      
    def get_version(self, obj):
        return ''
    
    # def get_blur(self, obj):
    #     if self.is_public or self.my_pk == 0 or self.my_pk >= obj.id:
    #         return False
    #     return True
    

    
class HeartWriteSerializer(serializers.ModelSerializer):
    
    def __init__(self, *args, **kwargs):
        self.method = kwargs.pop('method', 'post')
        super().__init__(*args, **kwargs)
        
        self.fields['paperFK'] = serializers.IntegerField()
        self.fields['context'] = serializers.CharField()
        self.fields['location'] = serializers.IntegerField()
        self.fields['color'] = serializers.CharField()
        
        if self.method == 'patch': 
            self.fields['heartPK'] = serializers.CharField()            
    
    class Meta:
        model = Heart
        fields = ()
        
        
    @transaction.atomic
    def create(self, validated_data):
        paper = Paper.objects.select_for_update().get(pk=validated_data['paperFK'])
        heart = Heart.objects.create(
            userFK=User.objects.get(pk=validated_data['userFK']),
            paperFK=paper,
            colorFK=QueryIndexTable.objects.get(name=validated_data['color']),
            context=validated_data['context'], location=validated_data['location'],
        )
        HeartRevision.objects.create(heartFK=heart, number=0, content=heart.context,
                                     color=heart.colorFK.name, editorFK=heart.userFK, recordedAt=heart.createdAt)
        return heart

    @transaction.atomic
    def update(self, validated_data):
        paper_id = Heart.objects.values_list('paperFK_id', flat=True).get(pk=validated_data['heartPK'])
        Paper.objects.select_for_update().get(pk=paper_id)
        heart = Heart.objects.get(pk=validated_data['heartPK'])
        color = QueryIndexTable.objects.get(name=validated_data['color'])
        if heart.context == validated_data['context'] and heart.colorFK_id == color.pk:
            return heart
        HeartRevision.objects.get_or_create(heartFK=heart, number=0, defaults={
            'content': heart.context, 'color': heart.colorFK.name, 'editorFK': heart.userFK,
            'recordedAt': heart.updatedAt, 'baseline': True,
        })
        heart.context = validated_data['context']
        heart.colorFK = color
        heart.location = validated_data['location']
        heart.revisionCount += 1
        heart.save(update_fields=['context', 'colorFK', 'location', 'revisionCount', 'updatedAt'])
        HeartRevision.objects.create(heartFK=heart, number=heart.revisionCount, content=heart.context,
                                     color=color.name, editorFK=heart.userFK, recordedAt=heart.updatedAt)
        return heart
