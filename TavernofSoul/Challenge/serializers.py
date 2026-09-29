from rest_framework import serializers
from .models import ChallengeModeAutoMap


class ChallengeModeAutoMapSerializer(serializers.ModelSerializer):
    """ChallengeModeAutoMap 모델 시리얼라이저"""
    class Meta:
        model = ChallengeModeAutoMap
        fields = '__all__'
