from rest_framework import viewsets
from django.db.models import Q
from .models import Skills
from .serializers import SkillsSerializer


class SkillsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Skills API ViewSet
    
    제공 엔드포인트:
    - GET /api/skills/ - 스킬 목록 조회
    - GET /api/skills/{id}/ - 특정 스킬 상세 조회
    - GET /api/skills/?search=검색어 - 스킬 검색
    - GET /api/skills/?job_id=직업ID - 직업 ID로 필터링
    - GET /api/skills/?job_ids=직업IDS - 직업 ids 필드로 필터링
    - GET /api/skills/?jobs_ids=직업IDS1,직업IDS2 - 여러 직업 ids로 필터링 (OR 조건)
    """
    queryset = Skills.objects.select_related('job').all()
    serializer_class = SkillsSerializer
    search_fields = ['name', 'id_name', 'ids', 'descriptions', 'element']
    ordering_fields = ['name', 'cooldown', 'created', 'updated']
    ordering = ['-created']

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # job_id로 필터링 (job의 pk)
        job_id = self.request.query_params.get('job_id', None)
        if job_id is not None:
            queryset = queryset.filter(job_id=job_id)
        
        # job_ids로 필터링 (job의 ids 필드)
        job_ids = self.request.query_params.get('job_ids', None)
        if job_ids is not None:
            queryset = queryset.filter(job__ids=job_ids)
        
        # jobs_ids로 필터링 (여러 job ids, 콤마로 구분, OR 조건)
        jobs_ids = self.request.query_params.get('jobs_ids', None)
        if jobs_ids is not None:
            ids_list = [id.strip() for id in jobs_ids.split(',') if id.strip()]
            if ids_list:
                query = Q()
                for job_id_value in ids_list:
                    query |= Q(job__ids=job_id_value)
                queryset = queryset.filter(query)
        
        return queryset
