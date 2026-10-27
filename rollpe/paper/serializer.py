from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone
from rest_framework import serializers

from heart.models import Heart
from heart.serializers import HeartReadSerializer
from paper.models import Paper, QueryIndexTable
from paper.lifecycle import KOREA
from user.serializers import UserViewSerializer


class UserShowPaperSerializer(serializers.ModelSerializer):
	host = serializers.SerializerMethodField()
	theme = serializers.SerializerMethodField()
	size = serializers.SerializerMethodField()
	ratio = serializers.SerializerMethodField()
	receive = serializers.SerializerMethodField()
	createdAt = serializers.SerializerMethodField()
	hearts = serializers.SerializerMethodField()
	invitingUser = serializers.SerializerMethodField()
	maxHeartLength = serializers.SerializerMethodField()

	class Meta:
		model = Paper
		fields = [
			"id",
			"code",
			"title",
			"host",
			'receive',
			"viewStat",
			"theme",
			'size',
			'ratio',
			'maxHeartLength',
			'hearts',
			'invitingUser',
			'createdAt',
			]

	def get_host(self, paper):
		return UserViewSerializer(paper.hostFK).data

	def get_receive(self, paper):
		return {
			"receiver": UserViewSerializer(paper.receiverFK).data,
			"receivingDate": paper.receivingDate,
			"receivingStat": paper.receivingStat,
			}

	def get_theme(self, paper):
		return paper.themeFK.name

	def get_size(self, paper):
		return paper.sizeFK.name

	def get_ratio(self, paper):
		return paper.ratioFK.name

	def get_createdAt(self, paper):
		return paper.createdAt

	def get_maxHeartLength(self, paper):
		return paper.sizeFK.query.get('max')

	def get_hearts(self, paper):

		hearts = Heart.objects.filter(paperFK=paper)
		if self.context.get('listing'):
			return {'count': hearts.count()}
		serializer = HeartReadSerializer(hearts, many=True)

		if len(serializer.data) == 0:
			return {"count": 0}

		return {
			"count": len(serializer.data),
			"data": serializer.data
			}

	def get_invitingUser(self, paper):
		if self.context.get('listing') or not paper.invitingUser:
			return []
		return UserViewSerializer(paper.invitingUser.all(), many=True).data


class PaperCreateSerializer(serializers.ModelSerializer):
	class Meta:
		model = Paper
		fields = [
			'hostFK', 'receiverFK', 'receiverName',
			'receiverTel', 'receivingDate', 'receivingStat',
			'themeFK', 'sizeFK', 'ratioFK',
			'viewStat', 'title', 'description', 'password',
			]
		read_only_fields = ("id", "createdAt", "updatedAt", "code")

		extra_kwargs = {
      'password': {'required': False, 'allow_null': True, 'write_only': True},
      'hostFK': {'required': False}
    }

	def validate_hostFK(self, host):
		request = self.context.get('request')
		if request is not None and host.pk != request.user.pk:
			raise serializers.ValidationError("본인만 호스트로 지정할 수 있습니다.")
		return host

	def validate_receiverTel(self, receiverTel):
		if receiverTel is None:
			return receiverTel
		if not receiverTel.isdigit():
			raise serializers.ValidationError("receiverTel 영역의 값은 int로 이루어져야 합니다.")

		if len(receiverTel) != 11:
			raise serializers.ValidationError("receiverTel 영역의 값은 11자리여야 합니다. 010XXXXXXXX 형식")

		return receiverTel

	def validate(self, attrs):
		receiverFK = attrs.get('receiverFK')
		receiverName = attrs.get('receiverName')
		receiverTel = attrs.get('receiverTel')

		if not receiverFK and (not receiverName or not receiverTel):
			raise serializers.ValidationError(
				"수신자 정보를 위해 receiverFK 또는 receiverName, receiverTel 중 최소 하나는 반드시 전달되어야 합니다."
				)
		return attrs


class PaperSettingsSerializer(serializers.Serializer):
    viewStat = serializers.BooleanField(required=False)
    password = serializers.CharField(required=False, allow_blank=True, max_length=50, trim_whitespace=False, write_only=True)
    receivingDate = serializers.DateField(required=False, input_formats=['%Y-%m-%d'])

    def validate(self, attrs):
        if not self.initial_data or set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError('공개 설정, 비밀번호, 전달일만 수정할 수 있습니다.')
        if 'viewStat' in self.initial_data and not isinstance(self.initial_data['viewStat'], bool):
            raise serializers.ValidationError('공개 설정을 확인해주세요.')
        if 'password' in self.initial_data and not isinstance(self.initial_data['password'], str):
            raise serializers.ValidationError('비밀번호 형식을 확인해주세요.')
        public = attrs.get('viewStat', self.instance.viewStat)
        password = attrs.get('password', '')
        if public and password:
            raise serializers.ValidationError('공개 롤페에는 비밀번호를 설정할 수 없습니다.')
        if not public and ((password and not password.strip())
                           or (not password and (self.instance.viewStat or not self.instance.password))):
            raise serializers.ValidationError('비공개 롤페의 비밀번호를 입력해주세요.')
        day = attrs.get('receivingDate', self.instance.receivingDate)
        today = timezone.localdate(timezone.now(), KOREA)
        if day != self.instance.receivingDate and not today + timedelta(days=1) <= day <= today + timedelta(days=30):
            raise serializers.ValidationError('전달일은 내일부터 30일 이내로 선택해주세요.')
        return attrs

    def update(self, instance, validated_data):
        changes = {}
        public = validated_data.get('viewStat', instance.viewStat)
        if public != instance.viewStat:
            changes['viewStat'] = public
        if public and instance.password:
            changes['password'] = None
        elif not public and validated_data.get('password') and (not instance.password or not check_password(validated_data['password'], instance.password)):
            changes['password'] = make_password(validated_data['password'])
        day = validated_data.get('receivingDate', instance.receivingDate)
        if day != instance.receivingDate:
            changes['receivingDate'] = day
        if changes:
            # Paper.save hashes passwords on every call, including existing hashes.
            changes['updatedAt'] = timezone.now()
            Paper.objects.filter(pk=instance.pk).update(**changes)
            for key, value in changes.items():
                setattr(instance, key, value)
        return instance


class QueryIndexSerializer(serializers.ModelSerializer):
	name = serializers.SerializerMethodField()
	class Meta:
		model = QueryIndexTable
		fields = ('id', 'name', 'query', 'type', 'is_vip')

	def get_name(self, paper):
		if paper.type == "COLOR":
			return "#" + paper.name
		else:
			return paper.name


class QueryIndexCreateSerializer(serializers.ModelSerializer):
	class Meta:
		model = QueryIndexTable
		fields = ('name', 'query', 'type', 'is_vip')
