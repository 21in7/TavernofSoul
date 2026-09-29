from rest_framework import serializers
from .models import Buffs


class BuffsSerializer(serializers.ModelSerializer):
    """Buffs 모델 시리얼라이저"""
    class Meta:
        model = Buffs
        fields = '__all__'

