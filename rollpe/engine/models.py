from django.db import models

from user.models import BaseTimeModel


# Create your models here.
class Search(BaseTimeModel):
	userFK = models.ForeignKey('user.User', on_delete=models.CASCADE)
	keywords = models.TextField()
	filter = models.JSONField(null=True, blank=True)
