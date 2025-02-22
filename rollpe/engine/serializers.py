from rest_framework import serializers
from engine.models import Search


class SearchCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Search