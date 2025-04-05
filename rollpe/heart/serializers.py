from rest_framework import serializers
from django.utils.timezone import localtime

from user.models import User
from paper.models import Paper, QueryIndexTable
from heart.models import Heart
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
        fields = ('id', 'index', 'author', 'content', 'createdAt', 'color', 'version', 'code')
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
        
        
    def create(self, validated_data):
        
        heart_instance = Heart.objects.create(
            userFK=User.objects.get(pk=validated_data['userFK']),
            paperFK=Paper.objects.get(pk=validated_data['paperFK']),
            colorFK=QueryIndexTable.objects.get(name=validated_data['color']),
            context=validated_data['context'],
            location=validated_data['location'],
        )
        return heart_instance
    
    def update(self, validated_data):
        
        Heart.objects.filter(pk=validated_data['heartPK']).update(
            colorFK=QueryIndexTable.objects.get(name=validated_data['color']),
            context=validated_data['context'],
            location=validated_data['location'],
        )
    
    
    