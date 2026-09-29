from rest_framework import serializers
from .models import Jobs


class JobsSerializer(serializers.ModelSerializer):
    """Jobs 모델 시리얼라이저"""
    class Meta:
        model = Jobs
        fields = '__all__'

