"""Index lookups retain linear-scan ordering and fallback behavior."""
from DB import ToS_DB


def make_db(monsters):
    db = ToS_DB()
    db.data = {'monsters': monsters}
    return db


def test_exact_match_wins_and_duplicate_ids_keep_first_order():
    db = make_db({
        'fallback': {'$ID': 8, 'SkillType': 'mon_SLASH'},
        'first': {'$ID': 3, 'SkillType': 'Slash'},
        'second': {'$ID': 1, 'SkillType': 'SLASH'},
        'duplicate': {'$ID': 3, 'SkillType': 'slash'},
        'missing': {'$ID': 7},
    })
    assert db.getMonbySkill('sLaSh') == [3, 1]
    assert db.getMonbySkill('mon_slash') == [8]
    assert db.getMonbySkill('unknown') == []
    result = db.getMonbySkill('Slash')
    result.clear()
    assert db.getMonbySkill('Slash') == [3, 1]


def test_prefix_fallback_deduplicates_in_source_order():
    db = make_db({
        1: {'$ID': 4, 'SkillType': 'mon_Bullet'},
        2: {'$ID': 2, 'SkillType': 'MON_BULLET'},
        3: {'$ID': 4, 'SkillType': 'mon_Bullet'},
    })
    assert db.getMonbySkill('bullet') == [4, 2]


def test_index_refreshes_on_replacement_growth_and_explicit_rebuild():
    db = make_db({1: {'$ID': 1, 'SkillType': 'Slash'}})
    assert db.getMonbySkill('Slash') == [1]
    db.data['monsters'] = {2: {'$ID': 2, 'SkillType': 'Bullet'}}
    assert db.getMonbySkill('Slash') == []
    assert db.getMonbySkill('Bullet') == [2]
    db.data['monsters'][3] = {'$ID': 3, 'SkillType': 'Bullet'}
    assert db.getMonbySkill('Bullet') == [2, 3]
    db.data['monsters'][2]['SkillType'] = 'Slash'
    db.build_monster_skill_index()
    assert db.getMonbySkill('Slash') == [2]
    assert db.getMonbySkill('Bullet') == [3]


def test_repeated_lookups_do_not_scan_monsters():
    class CountedMonsters(dict):
        scans = 0

        def values(self):
            self.scans += 1
            return super().values()

    monsters = CountedMonsters({1: {'$ID': 1, 'SkillType': 'Slash'}})
    db = make_db(monsters)
    for _ in range(100):
        assert db.getMonbySkill('Slash') == [1]
        assert db.getMonbySkill('Unknown') == []
    assert monsters.scans == 1


def test_item_inputs_have_explicit_unique_precedence():
    assert isinstance(ToS_DB.ITEM_IES, tuple)
    assert len(ToS_DB.ITEM_IES) == len(set(ToS_DB.ITEM_IES))
    assert ToS_DB.ITEM_IES.index('recipe.ies') < ToS_DB.ITEM_IES.index('item_EP13.ies')


def test_skill_parse_boundary_rebuilds_after_in_place_changes(tmp_path):
    from monsters import parse_skill_mon
    db = make_db({1: {'$ID': 1, 'SkillType': 'Slash'}})
    db.data['xml_skills'] = {}
    source = tmp_path / 'skill_mon.ies'
    source.write_text('ClassID,ClassName\n', encoding='utf-8')
    db.file_dict = {'skill_mon.ies': {'path': str(source)}}
    assert db.getMonbySkill('Slash') == [1]
    db.data['monsters'][1]['SkillType'] = 'Bullet'
    parse_skill_mon(db)
    assert db.getMonbySkill('Slash') == []
    assert db.getMonbySkill('Bullet') == [1]
