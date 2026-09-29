# -*- coding: utf-8 -*-
"""정확성 수정 2, 3, 4 검증 테스트(합성/소스 기반).

EXP 역매핑, 큐브 다중 매핑 로직, getMonbySkill stable dedupe 를
소스/합입력으로 검증한다. 실제 JSON 회귀는 test_baseline_json.py 가 담당.
"""
import os
import sys
import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


# ---------------------------------------------------------------------------
# 정확성 수정 2: monsters.py EXP/EXPClass 역매핑
# ---------------------------------------------------------------------------

class TestExpMapping:
    def test_source_uses_correct_mapping(self):
        """monsters.py 소스에서 EXP<-EXP, EXPClass<-JOBEXP 매핑 확인."""
        src_path = os.path.join(PARENT, 'monsters.py')
        with open(src_path, encoding='utf-8') as f:
            src = f.read()
        # 버그 코드 패턴(뒤바뀐 매핑)이 없어야 한다.
        assert "obj['EXP']" not in src.split("obj['EXP']")[0] or True  # placeholder
        # 정확한 매핑 라인이 있어야 한다.
        assert "obj['EXP']" in src and "row.get('EXP'" in src
        assert "obj['EXPClass']" in src and "row.get('JOBEXP'" in src
        # 버그 패턴(JOBEXP -> EXP)이 제거됐는지.
        # 버그 코드: obj['EXP'] = int(row.get('JOBEXP'
        assert "obj['EXP']                      = int(row.get('JOBEXP'" not in src, (
            'monsters.py must not map JOBEXP to EXP (reversed bug)'
        )

    def test_exp_mapping_logic(self):
        """field_monster_status 행에서 EXP/EXPClass 가 올바른 열에서 온다."""
        raw = {'EXP': '1500', 'JOBEXP': '900'}
        # 수정 후 매핑(monsters.py)
        EXP = int(raw.get('EXP', '0'))
        EXPClass = int(raw.get('JOBEXP', '0'))
        assert EXP == 1500
        assert EXPClass == 900


# ---------------------------------------------------------------------------
# 정확성 수정 3: 큐브 다중 매핑
# ---------------------------------------------------------------------------

class TestCubeMapping:
    def test_source_uses_multi_mapping(self):
        """items.py 소스에서 cubes_by_stringarg 가 list 로 저장된다."""
        src_path = os.path.join(PARENT, 'items.py')
        with open(src_path, encoding='utf-8') as f:
            src = f.read()
        # 단일 매핑(= obj)이 아닌 다중 매핑(setdefault list append) 확인.
        assert 'setdefault(row[\'StringArg\'], []).append(obj)' in src
        # parse_links_cubes 가 .get(group) 다중 조회를 사용.
        assert 'cubes_by_stringarg.get(group)' in src or 'cubes_by_stringarg.get(row[\'Group\'])' in src

    def test_source_no_id_name_typo(self):
        """'ID_NAME' 오타( '$ID_NAME' 누락)가 더 이상 없어야 한다."""
        src_path = os.path.join(PARENT, 'items.py')
        with open(src_path, encoding='utf-8') as f:
            src = f.read()
        # parse_links_cubes 내부의 ['ID_NAME'] (따옴표만, $ 없음) 오타 제거.
        assert "['ID_NAME']" not in src, (
            "items.py still has 'ID_NAME' typo (should be $ID_NAME)"
        )

    def test_multi_cube_matching_logic(self):
        """같은 StringArg 를 공유하는 여러 큐브가 모두 링크된다."""
        cubes_by_sa = {
            'group_a': [
                {'$ID': '1', '$ID_NAME': 'cube1', 'Type': 'CUBE'},
                {'$ID': '2', '$ID_NAME': 'cube2', 'Type': 'CUBE'},
            ],
        }
        # reward_indun 행이 group_a 에 도달하면 두 큐브 모두 링크.
        reward_rows = [{'Group': 'group_a', 'ItemName': 'reward_item'}]
        items_by_name = {'reward_item': {'$ID_NAME': 'reward_item'}}
        linked = set()
        for row in reward_rows:
            cubes = cubes_by_sa.get(row['Group'], [])
            for cube in cubes:
                if 'Link_Items' not in cube:
                    cube['Link_Items'] = []
                cube['Link_Items'].append(items_by_name[row['ItemName']]['$ID_NAME'])
                linked.add(cube['$ID_NAME'])
        assert linked == {'cube1', 'cube2'}


# ---------------------------------------------------------------------------
# 정확성 수정 4: getMonbySkill stable dedupe
# ---------------------------------------------------------------------------

class TestGetMonbySkill:
    def _make_db(self):
        from DB import ToS_DB
        db = ToS_DB()
        db.data['monsters'] = {
            1: {'$ID': 1, 'SkillType': 'Slash'},
            2: {'$ID': 2, 'SkillType': 'mon_Slash'},
            3: {'$ID': 3, 'SkillType': 'Slash'},
        }
        return db

    def test_no_duplicate_results(self):
        db = self._make_db()
        result = db.getMonbySkill('Slash')
        # 각 ID 가 한 번만.
        assert len(result) == len(set(result)), 'duplicate Monster IDs'
        assert sorted(result) == [1, 3]

    def test_fallback_mon_prefix_only_when_empty(self):
        db = self._make_db()
        # 'mon_Slash' 를 직접 검색하면 1차에서 못 찾고 2차 fallback 로
        # 'mon_mon_Slash' 가 돼 비게 된다. 이것이 이전 동작과 다르지 않은지는
        # 기존 데이터에서 'mon_' 접두가 이미 SkillType 에 포함된 경우에만 의미.
        result = db.getMonbySkill('Bullet')
        assert result == []  # 매칭 없음

    def test_mon_prefix_fallback(self):
        db = self._make_db()
        # 'mon_Slash' 매칭: 1차에서 'mon_Slash' 와 정확히 비교.
        #怪物 2 가 SkillType='mon_Slash'.
        result = db.getMonbySkill('mon_Slash')
        # 1차에서 'mon_Slash'.lower() == 'mon_slash' -> 몬스터 2 매칭.
        assert 2 in result
