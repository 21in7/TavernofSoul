"""
API URL Configuration

이 파일은 Django REST Framework를 사용한 API 엔드포인트를 정의합니다.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.reverse import reverse


class CustomDefaultRouter(DefaultRouter):
    """
    API 루트 뷰에 dashboard_version을 추가하는 커스텀 라우터
    """
    def get_api_root_view(self, api_urls=None):
        """
        API 루트 뷰를 생성하고 dashboard_version을 추가합니다.
        """
        api_root_dict = {}
        list_name = self.routes[0].name
        for prefix, viewset, basename in self.registry:
            api_root_dict[prefix] = list_name.format(basename=basename)
        
        class APIRoot(APIView):
            _ignore_model_permissions = True
            schema = None  # API 스키마에서 제외
            
            def get(self, request, format=None):
                ret = {}
                for key, url_name in api_root_dict.items():
                    ret[key] = reverse(url_name, request=request, format=format)
                
                # dashboard_version을 URL로 추가
                ret['dashboard_version'] = reverse('dashboard-version', request=request, format=format)
                
                return Response(ret)
        
        return APIRoot.as_view()


# REST Framework 라우터 생성
router = CustomDefaultRouter()

# Items 앱
from Items.viewsets import (
    ItemsViewSet, 
    EquipmentsViewSet, 
    CardsViewSet, 
    GemsViewSet,
    EquipmentSetViewSet
)
router.register(r'items', ItemsViewSet, basename='items')
router.register(r'equipments', EquipmentsViewSet, basename='equipments')
router.register(r'cards', CardsViewSet, basename='cards')
router.register(r'gems', GemsViewSet, basename='gems')
router.register(r'equipment-sets', EquipmentSetViewSet, basename='equipment-sets')

# Jobs 앱
from Jobs.viewsets import JobsViewSet
router.register(r'jobs', JobsViewSet, basename='jobs')

# Skills 앱
from Skills.viewsets import SkillsViewSet
router.register(r'skills', SkillsViewSet, basename='skills')

# Monsters 앱
from Monsters.viewsets import MonstersViewSet, ItemMonsterViewSet, SkillMonsterViewSet
router.register(r'monsters', MonstersViewSet, basename='monsters')
router.register(r'item-monsters', ItemMonsterViewSet, basename='item-monsters')
router.register(r'skill-monsters', SkillMonsterViewSet, basename='skill-monsters')

# Maps 앱
from Maps.viewsets import MapsViewSet, MapItemViewSet, MapNPCViewSet, MapItemSpawnViewSet
router.register(r'maps', MapsViewSet, basename='maps')
router.register(r'map-items', MapItemViewSet, basename='map-items')
router.register(r'map-npcs', MapNPCViewSet, basename='map-npcs')
router.register(r'map-item-spawns', MapItemSpawnViewSet, basename='map-item-spawns')

# Attributes 앱
from Attributes.viewsets import AttributesViewSet
router.register(r'attributes', AttributesViewSet, basename='attributes')

# Buffs 앱
from Buffs.viewsets import BuffsViewSet
router.register(r'buffs', BuffsViewSet, basename='buffs')

# Other 앱 (Achievements)
from Other.viewsets import AchievementsViewSet
router.register(r'achievements', AchievementsViewSet, basename='achievements')

# Challenge 앱
from Challenge.viewsets import ChallengeModeAutoMapViewSet
router.register(r'challenge-mode-auto-maps', ChallengeModeAutoMapViewSet, basename='challenge-mode-auto-maps')

# Dashboard 앱
from Dashboard.viewsets import DashboardVersionView

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/', DashboardVersionView.as_view(), name='dashboard-version'),
]

