from rest_framework import viewsets
from .models import Buffs
from .serializers import BuffsSerializer


class BuffsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Buffs API ViewSet
    
    제공 엔드포인트:
    - GET /api/buffs/ - 버프 목록 조회
    - GET /api/buffs/{id}/ - 특정 버프 상세 조회
    - GET /api/buffs/?search=검색어 - 버프 검색
    """
    queryset = Buffs.objects.all()
    serializer_class = BuffsSerializer
    search_fields = ['name', 'id_name', 'ids', 'descriptions', 'keyword']
    ordering_fields = ['name', 'applytime', 'created', 'updated']
    ordering = ['-created']

