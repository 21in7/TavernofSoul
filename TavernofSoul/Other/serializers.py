from rest_framework import serializers
from .models import Achievements


class AchievementsSerializer(serializers.ModelSerializer):
    """Achievements 모델 시리얼라이저"""
    class Meta:
        model = Achievements
        fields = '__all__'

