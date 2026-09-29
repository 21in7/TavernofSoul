from rest_framework.renderers import JSONRenderer
from Dashboard.models import Version


class DashboardVersionJSONRenderer(JSONRenderer):
    """
    모든 API 응답에 dashboard_version을 자동으로 추가하는 커스텀 JSON Renderer
    """
    
    def render(self, data, accepted_media_type=None, renderer_context=None):
        """
        응답 데이터에 dashboard_version을 추가합니다.
        """
        # dashboard_version 가져오기
        dashboard_version = self._get_dashboard_version()
        
        # data가 dict인 경우에만 dashboard_version 추가
        if isinstance(data, dict):
            data['dashboard_version'] = dashboard_version
        
        # 원래 JSONRenderer의 render 메서드 호출
        return super().render(data, accepted_media_type, renderer_context)
    
    def _get_dashboard_version(self):
        """최신 dashboard version을 가져옵니다."""
        try:
            ver = Version.objects.latest('created')
            return ver.version
        except Version.DoesNotExist:
            return None
        except Exception:
            return None
