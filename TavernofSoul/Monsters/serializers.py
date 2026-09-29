from rest_framework import serializers
from .models import Monsters, Item_Monster, Skill_Monster


class ItemMonsterSerializer(serializers.ModelSerializer):
    """Item_Monster 모델 시리얼라이저"""
    class Meta:
        model = Item_Monster
        fields = '__all__'


class SkillMonsterSerializer(serializers.ModelSerializer):
    """Skill_Monster 모델 시리얼라이저"""
    class Meta:
        model = Skill_Monster
        fields = '__all__'


class MonstersSerializer(serializers.ModelSerializer):
    """Monsters 모델 시리얼라이저"""
    class Meta:
        model = Monsters
        fields = '__all__'

