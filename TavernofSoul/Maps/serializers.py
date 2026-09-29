from rest_framework import serializers
from .models import Maps, Map_Item, Map_NPC, Map_Item_Spawn


class MapItemSerializer(serializers.ModelSerializer):
    """Map_Item 모델 시리얼라이저"""
    class Meta:
        model = Map_Item
        fields = '__all__'


class MapNPCSerializer(serializers.ModelSerializer):
    """Map_NPC 모델 시리얼라이저"""
    class Meta:
        model = Map_NPC
        fields = '__all__'


class MapItemSpawnSerializer(serializers.ModelSerializer):
    """Map_Item_Spawn 모델 시리얼라이저"""
    class Meta:
        model = Map_Item_Spawn
        fields = '__all__'


class MapsSerializer(serializers.ModelSerializer):
    """Maps 모델 시리얼라이저"""
    class Meta:
        model = Maps
        fields = '__all__'

