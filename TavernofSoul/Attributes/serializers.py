from rest_framework import serializers
from .models import Attributes


class AttributesSerializer(serializers.ModelSerializer):
    """Attributes 모델 시리얼라이저"""
    class Meta:
        model = Attributes
        fields = '__all__'
        depth = 1  # ManyToMany 관계 포함

