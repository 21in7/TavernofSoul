from rest_framework import serializers
from .models import Skills


class SkillsSerializer(serializers.ModelSerializer):
    """Skills 모델 시리얼라이저"""
    class Meta:
        model = Skills
        fields = '__all__'
        depth = 1  # ForeignKey 관계(job) 자동 포함

