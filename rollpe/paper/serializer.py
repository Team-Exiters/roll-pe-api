from rest_framework import serializers

from heart.models import Heart
from heart.serializers import HeartReadSerializer
from paper.models import Paper, QueryIndexTable
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
		serializer = HeartReadSerializer(hearts, many=True)

		if len(serializer.data) == 0:
			return {"count": 0}

		return {
			"count": len(serializer.data),
			"data": serializer.data
			}

	def get_invitingUser(self, paper):
		if not paper.invitingUser:
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

	def validate_receiverTel(self, receiverTel):
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


class PaperSerializer(serializers.ModelSerializer):
	host = serializers.SerializerMethodField()
	receiver = serializers.SerializerMethodField()

	theme = serializers.SerializerMethodField()
	size = serializers.SerializerMethodField()
	ratio = serializers.SerializerMethodField()
	invitingUser = serializers.SerializerMethodField()

	class Meta:
		model = Paper
		fields = (
			'host', 'receiver',
			'theme', 'size', 'ratio',
			'viewStat', 'title', 'description', 'invitingUser', 'createdAt'
		)

	def get_host(self, paper):
		return UserViewSerializer(paper.hostFK).data

	def get_receiver(self, paper):
		response = dict()

		response["id"] = UserViewSerializer(paper.receiverFK).data if paper.receiverFK else None
		response["name"] = paper.receiverFK.name if paper.receiverFK else paper.receiverName
		response["tel"] = "" if paper.receiverTel else paper.receiverTel
		response["date"] = paper.receivingDate
		response["stat"] = paper.receivingStat
		response["is_user"] = True if paper.receiverFK else False

		return response

	def get_theme(self, paper):
		return QueryIndexSerializer(paper.themeFK).data

	def get_size(self, paper):
		return QueryIndexSerializer(paper.sizeFK).data

	def get_ratio(self, paper):
		return QueryIndexSerializer(paper.ratioFK).data

	def get_invitingUser(self, paper):
		if not paper.invitingUser:
			return []
		return UserViewSerializer(paper.invitingUser.all(), many=True).data



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
