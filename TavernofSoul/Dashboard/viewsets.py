from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Max
from .models import Version


class DashboardVersionView(APIView):
    """
    Dashboard Version API View
    
    제공 엔드포인트:
    - GET /api/dashboard/ - 현재 dashboard version 조회
    """
    
    def get(self, request):
        """모든 dashboard version을 중복 제거하여 반환합니다. (각 version별 가장 최근 것만)"""
        try:
            # 각 version별로 가장 최근 created를 가진 레코드들만 필터링
            # version으로 그룹화하고 각 그룹의 최대 created를 찾기
            latest_by_version = Version.objects.values('version').annotate(
                latest_created=Max('created')
            ).order_by('-latest_created')
            
            # 각 version별 최신 레코드들의 version과 created를 리스트로 추출
            versions = [
                {
                    'version': item['version'],
                    'created': item['latest_created'].isoformat() if item['latest_created'] else None
                }
                for item in latest_by_version
            ]
            
            return Response({
                'dashboard_version': versions
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
