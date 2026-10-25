from django.db import models
import uuid

from user.models import BaseTimeModel


class Heart(BaseTimeModel):
	userFK = models.ForeignKey(
     	'user.User', 
      	on_delete=models.DO_NOTHING
	)
	paperFK = models.ForeignKey(
    	'paper.Paper', 
    	on_delete=models.CASCADE
    )
	colorFK = models.ForeignKey(
		'paper.QueryIndexTable',
		on_delete=models.CASCADE,
		related_name='heart_color',
		)

	code = models.UUIDField(
    	default=uuid.uuid4, 
    	editable=True,
    	null=True 
	)
	danger = models.IntegerField(
		default=0
	)
	context = models.TextField(
	)
	location = models.IntegerField(
		null=True,
		blank=True
	)
	revisionCount = models.PositiveIntegerField(default=0, editable=False)
 
	class Meta:
		verbose_name = 'heart'


class HeartRevision(models.Model):
    heartFK = models.ForeignKey(Heart, on_delete=models.CASCADE, related_name='revisions')
    number = models.PositiveIntegerField()
    content = models.TextField()
    color = models.CharField(max_length=7)
    editorFK = models.ForeignKey('user.User', on_delete=models.SET_NULL, null=True)
    recordedAt = models.DateTimeField()
    # Older overwritten text cannot be recovered: version zero is the deployment-time baseline.
    baseline = models.BooleanField(default=False)

    class Meta:
        ordering = ['number']
        constraints = [models.UniqueConstraint(fields=['heartFK', 'number'], name='unique_heart_revision')]

    def __str__(self):
        label = f'{self.number}차 수정' if self.number else ('기존 기준본' if self.baseline else '원본')
        return f'{self.heartFK_id} · {label}'
