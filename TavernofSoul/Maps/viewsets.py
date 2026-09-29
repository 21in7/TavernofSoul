from rest_framework import viewsets
from .models import Maps, Map_Item, Map_NPC, Map_Item_Spawn
from .serializers import (
    MapsSerializer, 
    MapItemSerializer, 
    MapNPCSerializer, 
    MapItemSpawnSerializer
)


class MapsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Maps API ViewSet
    
    제공 엔드포인트:
    - GET /api/maps/ - 맵 목록 조회
    - GET /api/maps/{id}/ - 특정 맵 상세 조회
    - GET /api/maps/?search=검색어 - 맵 검색
    """
    queryset = Maps.objects.all()
    serializer_class = MapsSerializer
    search_fields = ['name', 'id_name', 'ids', 'type']
    ordering_fields = ['name', 'level', 'star', 'created', 'updated']
    ordering = ['-created']


class MapItemViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Map_Item API ViewSet
    
    제공 엔드포인트:
    - GET /api/map-items/ - 맵 아이템 목록 조회
    - GET /api/map-items/{id}/ - 특정 맵 아이템 상세 조회
    """
    queryset = Map_Item.objects.select_related('map', 'item').all()
    serializer_class = MapItemSerializer


class MapNPCViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Map_NPC API ViewSet
    
    제공 엔드포인트:
    - GET /api/map-npcs/ - 맵 NPC 목록 조회
    - GET /api/map-npcs/{id}/ - 특정 맵 NPC 상세 조회
    """
    queryset = Map_NPC.objects.select_related('map', 'monster').all()
    serializer_class = MapNPCSerializer


class MapItemSpawnViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Map_Item_Spawn API ViewSet
    
    제공 엔드포인트:
    - GET /api/map-item-spawns/ - 맵 아이템 스폰 목록 조회
    - GET /api/map-item-spawns/{id}/ - 특정 맵 아이템 스폰 상세 조회
    """
    queryset = Map_Item_Spawn.objects.select_related('map', 'item').all()
    serializer_class = MapItemSpawnSerializer

