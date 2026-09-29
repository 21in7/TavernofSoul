# Django REST Framework API 서버 설정 가이드

이 프로젝트에 Django REST Framework를 사용한 API 서버 기능이 추가되었습니다.

## 설정 완료 사항

1. **설정 파일 업데이트**
   - `settings_ktos_d1.py`에 `rest_framework` 앱 추가
   - REST_FRAMEWORK 기본 설정 추가

2. **API 엔드포인트**
   - API 경로: `/api/`
   - API 라우터 설정: `TavernofSoul/api_urls.py`

3. **Items 앱 API 예시**
   - Serializers: `Items/serializers.py`
   - ViewSets: `Items/viewsets.py`

## 사용 가능한 API 엔드포인트

### Items API
- `GET /api/items/` - 아이템 목록 조회 (페이지네이션 지원)
- `GET /api/items/{id}/` - 특정 아이템 상세 조회
- `GET /api/items/?search=검색어` - 아이템 검색 (name, id_name, ids, descriptions 검색)
- `GET /api/items/?ordering=name` - 정렬 (name, grade, created, updated)
- `GET /api/items/?page=1` - 페이지네이션 (기본 페이지 크기: 50)

### Equipments API
- `GET /api/equipments/` - 장비 목록 조회
- `GET /api/equipments/{id}/` - 특정 장비 상세 조회

### Cards API
- `GET /api/cards/` - 카드 목록 조회
- `GET /api/cards/{id}/` - 특정 카드 상세 조회

### Gems API
- `GET /api/gems/` - 보석 목록 조회
- `GET /api/gems/{id}/` - 특정 보석 상세 조회

### Equipment Sets API
- `GET /api/equipment-sets/` - 장비 세트 목록 조회
- `GET /api/equipment-sets/{id}/` - 특정 장비 세트 상세 조회

## API 브라우저 인터페이스

Django REST Framework는 브라우저에서 API를 테스트할 수 있는 인터페이스를 제공합니다:
- 브라우저에서 `http://your-domain/api/items/` 접속 시 API 브라우저 인터페이스 확인 가능

## 다른 앱에 API 추가하기

다른 앱(Skills, Jobs, Monsters 등)에 API를 추가하려면:

1. **Serializers 생성** (예: `Skills/serializers.py`)
```python
from rest_framework import serializers
from .models import Skills

class SkillsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skills
        fields = '__all__'
```

2. **ViewSet 생성** (예: `Skills/viewsets.py`)
```python
from rest_framework import viewsets
from .models import Skills
from .serializers import SkillsSerializer

class SkillsViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Skills.objects.all()
    serializer_class = SkillsSerializer
    search_fields = ['name', 'id_name']
```

3. **API 라우터에 등록** (`TavernofSoul/api_urls.py`)
```python
from Skills.viewsets import SkillsViewSet
router.register(r'skills', SkillsViewSet, basename='skills')
```

## 고급 필터링 추가 (선택사항)

더 강력한 필터링 기능이 필요하다면 `django-filter` 패키지를 추가할 수 있습니다:

1. `REQUIREMENTS.txt`에 추가:
```
django-filter
```

2. `settings_ktos_d1.py`의 `INSTALLED_APPS`에 추가:
```python
'rest_framework',
'django_filters',
```

3. `REST_FRAMEWORK` 설정에 추가:
```python
REST_FRAMEWORK = {
    ...
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
}
```

4. ViewSet에서 사용:
```python
from django_filters.rest_framework import DjangoFilterBackend

class ItemsViewSet(viewsets.ReadOnlyModelViewSet):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['type', 'grade']
    ...
```

## 인증 설정 (선택사항)

현재 API는 모든 사용자에게 열려있습니다 (`AllowAny`). 인증이 필요하다면:

1. `settings_ktos_d1.py`에서 변경:
```python
REST_FRAMEWORK = {
    ...
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',  # 인증 필수
        # 또는 'rest_framework.permissions.IsAuthenticatedOrReadOnly',  # 읽기는 공개, 쓰기는 인증
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
        # 또는 'rest_framework.authentication.TokenAuthentication',  # Token 인증
    ],
}
```

## 테스트

서버 실행 후 다음 URL로 테스트:
- API 루트: `http://your-domain/api/`
- Items API: `http://your-domain/api/items/`
- 브라우저에서 접속하면 인터랙티브한 API 문서 확인 가능

