from rest_framework import viewsets
from rest_framework.response import Response
from .models import ChallengeModeAutoMap
from .serializers import ChallengeModeAutoMapSerializer
from Dashboard.models import Version


class ChallengeModeAutoMapViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Challenge Mode Auto Map API ViewSet
    
    제공 엔드포인트:
    - GET /api/challenge-mode-auto-maps/ - 챌린지 모드 자동 맵 목록 조회
    - GET /api/challenge-mode-auto-maps/{id}/ - 특정 맵 상세 조회
    - GET /api/challenge-mode-auto-maps/?search=검색어 - 맵 검색
    - GET /api/challenge-mode-auto-maps/?class_id=1 - ClassID로 필터링
    - GET /api/challenge-mode-auto-maps/?map_name=맵이름 - MapName으로 필터링
    - GET /api/challenge-mode-auto-maps/?ordering=class_id - 정렬
    """
    queryset = ChallengeModeAutoMap.objects.all()
    serializer_class = ChallengeModeAutoMapSerializer
    search_fields = ['name', 'class_name', 'map_name', 'value_str']
    ordering_fields = ['class_id', 'name', 'map_name', 'created', 'updated']
    ordering = ['class_id']

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # class_id로 필터링
        class_id = self.request.query_params.get('class_id', None)
        if class_id is not None:
            try:
                queryset = queryset.filter(class_id=int(class_id))
            except ValueError:
                pass
        
        # map_name으로 필터링
        map_name = self.request.query_params.get('map_name', None)
        if map_name is not None:
            queryset = queryset.filter(map_name__icontains=map_name)
        
        return queryset
    
    def _get_dashboard_version(self):
        """최신 dashboard version을 가져옵니다."""
        try:
            ver = Version.objects.latest('created')
            return ver.version
        except:
            return None
    
    def list(self, request, *args, **kwargs):
        """목록 조회 시 dashboard_version을 포함합니다."""
        response = super().list(request, *args, **kwargs)
        response.data['dashboard_version'] = self._get_dashboard_version()
        return response
    
    def retrieve(self, request, *args, **kwargs):
        """상세 조회 시 dashboard_version을 포함합니다."""
        response = super().retrieve(request, *args, **kwargs)
        response.data['dashboard_version'] = self._get_dashboard_version()
        return response