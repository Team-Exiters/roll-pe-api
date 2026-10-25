from rest_framework import serializers
from django.utils.timezone import localtime

from heart.models import Heart, HeartRevision
from user.serializers import UserViewSerializer


class HeartReadSerializer(serializers.ModelSerializer):
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

    def __init__(self, *args, **kwargs):
        # Legacy list callers may still pass these options.
        kwargs.pop('is_public', None)
        kwargs.pop('my_pk', None)
        super().__init__(*args, **kwargs)

    def get_createdAt(self, obj):
        return localtime(obj.createdAt).strftime('%Y.%m.%d')

    def get_version(self, obj):
        return ''


class HeartWriteSerializer(serializers.Serializer):
    paperFK = serializers.IntegerField(min_value=1)
    context = serializers.CharField(max_length=40, trim_whitespace=False)
    location = serializers.IntegerField(min_value=0)
    color = serializers.RegexField(r'^#?[0-9a-fA-F]{6}$')

    def __init__(self, *args, **kwargs):
        method = kwargs.pop('method', 'post')
        super().__init__(*args, **kwargs)
        if method == 'patch':
            self.fields['heartPK'] = serializers.IntegerField(min_value=1)

    def validate_context(self, value):
        if not value.strip() or '\n' in value or '\r' in value:
            raise serializers.ValidationError('줄바꿈 없이 내용을 입력하세요. (최대 40자)')
        return value

    def create(self, validated_data):
        heart = Heart.objects.create(**{key: validated_data[key] for key in (
            'userFK', 'paperFK', 'colorFK', 'context', 'location',
        )})
        HeartRevision.objects.create(heartFK=heart, number=0, content=heart.context,
                                     color=heart.colorFK.name, editorFK=heart.userFK, recordedAt=heart.createdAt)
        return heart

    def update(self, instance, validated_data):
        color = validated_data['colorFK']
        if instance.context == validated_data['context'] and instance.colorFK_id == color.pk:
            return instance
        HeartRevision.objects.get_or_create(heartFK=instance, number=0, defaults={
            'content': instance.context, 'color': instance.colorFK.name, 'editorFK': instance.userFK,
            'recordedAt': instance.updatedAt, 'baseline': True,
        })
        instance.context = validated_data['context']
        instance.colorFK = color
        instance.revisionCount += 1
        instance.save(update_fields=['context', 'colorFK', 'revisionCount', 'updatedAt'])
        HeartRevision.objects.create(heartFK=instance, number=instance.revisionCount, content=instance.context,
                                     color=color.name, editorFK=instance.userFK, recordedAt=instance.updatedAt)
        return instance
