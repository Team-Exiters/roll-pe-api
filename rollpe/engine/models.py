from django.db import models

from user.models import BaseTimeModel


# Create your models here.
class Search(BaseTimeModel):
	userFK = models.ForeignKey('user.User', on_delete=models.CASCADE)
	keywords = models.TextField()
	filter = models.JSONField(null=True, blank=True)


class Inquiry(BaseTimeModel):
    class Category(models.TextChoices):
        BUG = 'bug', '버그 제보'
        SUGGESTION = 'suggestion', '건의사항'
        OTHER = 'other', '기타 문의사항'

    class Status(models.TextChoices):
        PENDING = 'pending', '접수'
        COMPLETED = 'completed', '처리 완료'

    userFK = models.ForeignKey('user.User', on_delete=models.CASCADE, related_name='inquiries')
    requestId = models.UUIDField(editable=False)
    email = models.EmailField(max_length=254, blank=True)
    category = models.CharField(max_length=10, choices=Category.choices)
    content = models.TextField(max_length=2000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    staffNote = models.TextField(blank=True)

    class Meta:
        verbose_name = '1:1 문의'
        verbose_name_plural = '1:1 문의'
        ordering = ['-createdAt', '-pk']
        constraints = [models.UniqueConstraint(fields=['userFK', 'requestId'], name='unique_user_inquiry_request')]
