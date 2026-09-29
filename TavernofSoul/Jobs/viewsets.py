from rest_framework import viewsets
from .models import Jobs
from .serializers import JobsSerializer


class JobsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Jobs API ViewSet
    
    제공 엔드포인트:
    - GET /api/jobs/ - 직업 목록 조회 (is_starter가 먼저 정렬됨)
    - GET /api/jobs/{id}/ - 특정 직업 상세 조회
    - GET /api/jobs/?search=검색어 - 직업 검색
    - GET /api/jobs/?is_starter=true - is_starter가 True인 직업만 조회
    - GET /api/jobs/?is_starter=false - is_starter가 False인 직업만 조회
    """
    queryset = Jobs.objects.all()
    serializer_class = JobsSerializer
    search_fields = ['name', 'id_name', 'ids', 'descriptions', 'job_tree']
    ordering_fields = ['name', 'job_tree', 'created', 'updated', 'is_starter']
    ordering = ['-is_starter', '-created']

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # is_starter로 필터링
        is_starter = self.request.query_params.get('is_starter', None)
        if is_starter is not None:
            is_starter_bool = is_starter.lower() in ('true', '1', 'yes')
            queryset = queryset.filter(is_starter=is_starter_bool)
        
        return queryset

