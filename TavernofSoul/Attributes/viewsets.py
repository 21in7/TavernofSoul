from rest_framework import viewsets
from .models import Attributes
from .serializers import AttributesSerializer


class AttributesViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Attributes API ViewSet
    
    제공 엔드포인트:
    - GET /api/attributes/ - 속성 목록 조회
    - GET /api/attributes/{id}/ - 특정 속성 상세 조회
    - GET /api/attributes/?search=검색어 - 속성 검색
    """
    queryset = Attributes.objects.prefetch_related('skill', 'job').all()
    serializer_class = AttributesSerializer
    search_fields = ['name', 'id_name', 'ids', 'descriptions']
    ordering_fields = ['name', 'max_lv', 'created', 'updated']
    ordering = ['-created']

