from rest_framework import viewsets
from .models import Achievements
from .serializers import AchievementsSerializer


class AchievementsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Achievements API ViewSet
    
    제공 엔드포인트:
    - GET /api/achievements/ - 업적 목록 조회
    - GET /api/achievements/{id}/ - 특정 업적 상세 조회
    - GET /api/achievements/?search=검색어 - 업적 검색
    """
    queryset = Achievements.objects.all()
    serializer_class = AchievementsSerializer
    search_fields = ['name', 'id_name', 'ids', 'descriptions', 'group']
    ordering_fields = ['name', 'created', 'updated']
    ordering = ['-created']

