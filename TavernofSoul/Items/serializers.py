from rest_framework import serializers
from .models import Items, Equipments, Cards, Gems, Recipes, Equipment_Set


class ItemsSerializer(serializers.ModelSerializer):
    """Items 모델 시리얼라이저"""
    class Meta:
        model = Items
        fields = '__all__'


class EquipmentsSerializer(serializers.ModelSerializer):
    """Equipments 모델 시리얼라이저"""
    item = ItemsSerializer(read_only=True)
    
    class Meta:
        model = Equipments
        fields = '__all__'
        depth = 1


class CardsSerializer(serializers.ModelSerializer):
    """Cards 모델 시리얼라이저"""
    item = ItemsSerializer(read_only=True)
    
    class Meta:
        model = Cards
        fields = '__all__'
        depth = 1


class GemsSerializer(serializers.ModelSerializer):
    """Gems 모델 시리얼라이저"""
    item = ItemsSerializer(read_only=True)
    
    class Meta:
        model = Gems
        fields = '__all__'
        depth = 1


class EquipmentSetSerializer(serializers.ModelSerializer):
    """Equipment_Set 모델 시리얼라이저"""
    class Meta:
        model = Equipment_Set
        fields = '__all__'

