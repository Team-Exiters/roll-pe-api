import uuid

from django.db import models
from django.contrib.auth.hashers import make_password

from user.models import BaseTimeModel
PAPER_QUERY_TYPE =[
		("COLOR", "색상"),
		("THEME", "테마"),
		("SIZE", "사이즈"),
		("RATIO", "비율")
		]

class QueryIndexTable(models.Model):
	name = models.CharField(max_length=100)
	query = models.JSONField(
		default=dict,
		)
	type = models.CharField(
		choices=PAPER_QUERY_TYPE,
		max_length=10,
		)
	is_vip = models.BooleanField(default=False)

# Create your models here.
class Paper(BaseTimeModel):
	hostFK = models.ForeignKey(
     'user.User',
	    on_delete=models.DO_NOTHING,
	    related_name='paper_host'
	)

	receiverFK = models.ForeignKey(
     'user.User', 
		on_delete=models.DO_NOTHING,
		related_name='paper_receiver',
		null=True,
		blank=True
	)

	themeFK = models.ForeignKey(
		QueryIndexTable,
		on_delete=models.DO_NOTHING,
		related_name='paper_theme'
		)

	sizeFK = models.ForeignKey(
		QueryIndexTable,
		on_delete=models.DO_NOTHING,
		related_name='paper_size'
		)

	ratioFK = models.ForeignKey(
		QueryIndexTable,
		on_delete=models.DO_NOTHING,
		related_name='paper_ratio'
		)

	receiverName = models.CharField(max_length=15, null=True, blank=True)

	receiverTel = models.CharField(max_length=11, null=True, blank=True)

	receivingDate = models.DateField()

	receivingStat = models.IntegerField(default=0)

	viewStat = models.BooleanField(default=False)

	title = models.CharField(max_length=100)

	description = models.TextField(null=True, blank=True)

	code = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

	password = models.CharField(max_length=128, null=True, blank=True)

	invitingUser = models.ManyToManyField('user.User', related_name='inviting_user', blank=True)
	blockedUsers = models.ManyToManyField('user.User', related_name='blocked_papers', blank=True)

	def save(self, *args, **kwargs):
		if not self.password:
				self.viewStat = True
		else:
				# password가 있을 경우 해시 처리
				self.password = make_password(self.password)
				
		super().save(*args, **kwargs)


class PaperInvitation(BaseTimeModel):
    class Status(models.TextChoices):
        PENDING = 'pending'
        ACCEPTED = 'accepted'
        DENIED = 'denied'

    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='invitations')
    user = models.ForeignKey('user.User', on_delete=models.CASCADE, related_name='paper_invitations')
    code = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    respondedAt = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['paper', 'user'], name='unique_paper_invitation_user')]
