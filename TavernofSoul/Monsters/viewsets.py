from rest_framework import viewsets
from .models import Monsters, Item_Monster, Skill_Monster
from .serializers import MonstersSerializer, ItemMonsterSerializer, SkillMonsterSerializer


class MonstersViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Monsters API ViewSet
    
    제공 엔드포인트:
    - GET /api/monsters/ - 몬스터 목록 조회
    - GET /api/monsters/{id}/ - 특정 몬스터 상세 조회
    - GET /api/monsters/?search=검색어 - 몬스터 검색
    """
    queryset = Monsters.objects.all()
    serializer_class = MonstersSerializer
    search_fields = ['name', 'id_name', 'ids', 'descriptions', 'rank', 'race', 'element']
    ordering_fields = ['name', 'level', 'hp', 'created', 'updated']
    ordering = ['-created']


class ItemMonsterViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Item_Monster API ViewSet
    
    제공 엔드포인트:
    - GET /api/item-monsters/ - 몬스터 드롭 아이템 목록 조회
    - GET /api/item-monsters/{id}/ - 특정 드롭 아이템 상세 조회
    """
    queryset = Item_Monster.objects.select_related('monster', 'item').all()
    serializer_class = ItemMonsterSerializer


class SkillMonsterViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Skill_Monster API ViewSet
    
    제공 엔드포인트:
    - GET /api/skill-monsters/ - 몬스터 스킬 목록 조회
    - GET /api/skill-monsters/{id}/ - 특정 몬스터 스킬 상세 조회
    """
    queryset = Skill_Monster.objects.prefetch_related('monsters').all()
    serializer_class = SkillMonsterSerializer
    search_fields = ['name', 'id_name', 'ids', 'element']
    ordering_fields = ['name', 'cooldown', 'sfr']

