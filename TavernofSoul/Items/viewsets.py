from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Items, Equipments, Cards, Gems, Equipment_Set
from .serializers import (
    ItemsSerializer, 
    EquipmentsSerializer, 
    CardsSerializer, 
    GemsSerializer,
    EquipmentSetSerializer
)


class ItemsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Items API ViewSet
    
    제공 엔드포인트:
    - GET /api/items/ - 아이템 목록 조회
    - GET /api/items/{id}/ - 특정 아이템 상세 조회
    - GET /api/items/?search=검색어 - 아이템 검색
    - GET /api/items/?type=아이템타입 - 타입별 필터링
    - GET /api/items/?grade=등급 - 등급별 필터링
    """
    queryset = Items.objects.all()
    serializer_class = ItemsSerializer
    search_fields = ['name', 'id_name', 'ids', 'descriptions']
    # filterset_fields는 django-filter 패키지가 필요합니다
    # 필요시 REQUIREMENTS.txt에 django-filter 추가 후 사용 가능
    # filterset_fields = ['type', 'grade']
    ordering_fields = ['name', 'grade', 'created', 'updated']
    ordering = ['-created']


class EquipmentsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Equipments API ViewSet
    
    제공 엔드포인트:
    - GET /api/equipments/ - 장비 목록 조회
    - GET /api/equipments/{id}/ - 특정 장비 상세 조회
    """
    queryset = Equipments.objects.select_related('item').all()
    serializer_class = EquipmentsSerializer


class CardsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Cards API ViewSet
    
    제공 엔드포인트:
    - GET /api/cards/ - 카드 목록 조회
    - GET /api/cards/{id}/ - 특정 카드 상세 조회
    """
    queryset = Cards.objects.select_related('item').all()
    serializer_class = CardsSerializer


class GemsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Gems API ViewSet
    
    제공 엔드포인트:
    - GET /api/gems/ - 보석 목록 조회
    - GET /api/gems/{id}/ - 특정 보석 상세 조회
    """
    queryset = Gems.objects.select_related('item', 'skill').all()
    serializer_class = GemsSerializer


class EquipmentSetViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Equipment_Set API ViewSet
    
    제공 엔드포인트:
    - GET /api/equipment-sets/ - 장비 세트 목록 조회
    - GET /api/equipment-sets/{id}/ - 특정 장비 세트 상세 조회
    """
    queryset = Equipment_Set.objects.prefetch_related('equipment').all()
    serializer_class = EquipmentSetSerializer

