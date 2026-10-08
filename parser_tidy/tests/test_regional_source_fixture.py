"""Five real parser paths with language, source selection and extra item types."""
import json
from pathlib import Path
import shutil

import pytest

import luautil
from harness.fixture_inputs import REGIONAL_FIXTURE, REGIONS
from harness.parser_fixture import change_ies_column, parse_workspace, prepare_regional_workspace

EXPECTED = json.loads((REGIONAL_FIXTURE / 'expected_regions.json').read_text(encoding='utf-8'))


def parse(root, region, version='regional-v1'):
    return parse_workspace(root, version, region=region, include_regional=True)


def snapshot(release):
    return {path.name: path.read_bytes() for path in release.glob('*.json')}


@pytest.mark.parametrize('region', REGIONS)
def test_region_language_references_and_fallback_keep_source_ids(tmp_path, region):
    db = parse(prepare_regional_workspace(tmp_path, region), region)
    expected = EXPECTED[region]
    names = expected['names']
    release = Path(db.BASE_PATH_OUTPUT)
    assert release == tmp_path / 'TavernofSoul' / ('JSON_' + region)
    output = json.loads((release / 'items_by_name.json').read_text())
    assert len(output) == 11
    for kind in ('ore', 'sword', 'staff', 'armor', 'card', 'collection'):
        assert output['harness_' + kind]['Name'] == names[kind]
    assert output['harness_ore']['Description'] == expected['ore_description']
    assert output['harness_package']['PackageContents']['items'][0]['name'] == names['ore']
    assert output['harness_recipe']['Link_Target'] == 'harness_sword'
    assert output['harness_recipe']['$ID'] == output['harness_ore']['$ID'] == '100'
    for collection, ident, key in (('jobs', '300', 'job'), ('skills', '400', 'fire'),
                                   ('skills', '403', 'support'), ('maps', '900', 'map'),
                                   ('buff', '910', 'buff'), ('attributes', '920', 'attribute')):
        assert db.data[collection][ident]['Name'] == names[key]
    assert db.data['skills']['400']['Description'] == expected['fire_description']
    fallback = db.data['skills']['403']
    assert fallback['$ID'] == '403' and fallback['Link_Job'] == '300'
    assert fallback['Description'] == expected['fallback_description']
    assert fallback['Effect'] == expected['fallback_effect']
    assert fallback['Icon'] == 'icon_regional_ktos'
    assert db.data['assets_icons']['icon_regional_ktos'] == 'icon_regional_ktos'
    for collection in ('item_monster', 'map_item'):
        provenance = db.data['build_provenance'][collection]
        assert provenance['source_region'] == 'itos'
        assert provenance['input_version'] == 'regional-source-itos-v1'
        assert (provenance['fallback_reason'] is None) == (region == 'itos')
        assert all(row['SourceRegion'] == 'itos' and row['InputVersion'] == 'regional-source-itos-v1'
                   for row in db.data[collection])


@pytest.mark.parametrize('region', REGIONS)
def test_region_lua_values_cover_magic_defense_classes_and_bonus_rounding(tmp_path, region):
    db = parse(prepare_regional_workspace(tmp_path, region), region)
    expected = EXPECTED[region]
    sword, staff, armor = (db.data['items_by_name']['harness_' + kind]
                           for kind in ('sword', 'staff', 'armor'))
    assert (sword['Stat_ATTACK_PHYSICAL_MIN'], sword['Stat_ATTACK_PHYSICAL_MAX']) == (
        expected['sword_min'], expected['sword_max'])
    assert staff['Stat_ATTACK_MAGICAL'] == expected['staff_matk']
    assert staff['RequiredClass'] == 'FFFFT'
    assert staff['Bonus'] == [['INT', 4]]
    assert (armor['Stat_DEFENSE_PHYSICAL'], armor['Stat_DEFENSE_MAGICAL']) == (
        expected['armor_def'], expected['armor_mdef'])
    assert (armor['Durability'], armor['Level'], armor['RequiredLevel'], armor['Grade']) == (-1, 35, 30, 2)
    assert armor['RequiredClass'] == 'FTFTF'
    assert armor['Bonus'] == [['STR', -3]]
    assert armor['AnvilATK'] == [] and staff['AnvilDEF'] == []
    for row, field, step in ((staff, 'AnvilATK', expected['atk_step']),
                             (armor, 'AnvilDEF', expected['def_step'])):
        assert row[field] == list(range(step, step * 40 + 1, step))
        assert row['AnvilPrice'] == list(range(expected['price_step'], expected['price_step'] * 40 + 1,
                                              expected['price_step']))
        assert row['TranscendPrice'] == [3, 6, 9, 12, 15, 18, 21, 24, 27, 30]
        assert all(type(value) is int for value in row[field] + row['AnvilPrice'])
    assert db.data['skills']['400']['sfr'] == list(range(100, 221, 10))
    assert db.data['skills']['400']['CaptionRatio'] == [40] * 13


@pytest.mark.parametrize('region', REGIONS)
def test_cards_battle_and_collections_are_parsed_from_ies(tmp_path, region):
    db = parse(prepare_regional_workspace(tmp_path, region), region)
    card = db.data['items_by_name']['harness_card']
    assert (card['Type'], card['TypeCard'], card['IconTooltip']) == ('CARD', 'ATK', 'icon_harness_card_tooltip')
    assert (card['Stat_Height'], card['Stat_Legs'], card['Stat_Weight']) == (150, 4, 22)
    collection = db.data['items_by_name']['harness_collection']
    assert collection['Link_Items'] == ['harness_ore', 'harness_dust']
    assert collection['Bonus'] == [['STR', 3], ['Maximum HP', 25]]
    assert db.data['item_type']['CARD'] == ['harness_card']
    assert db.data['item_type']['COLLECTION'] == ['harness_collection']


def test_region_switching_rebuilds_restore_lua_and_do_not_mix_names_or_values(tmp_path):
    state = luautil.lua
    workspaces, releases = {}, {}
    for region in REGIONS:
        workspaces[region] = prepare_regional_workspace(tmp_path / region, region)
        db = parse(workspaces[region], region)
        releases[region] = snapshot(Path(db.BASE_PATH_OUTPUT))
    for region in reversed(REGIONS):
        db = parse(workspaces[region], region)
        assert snapshot(Path(db.BASE_PATH_OUTPUT)) == releases[region]
        assert db.data['items_by_name']['harness_staff']['Stat_ATTACK_MAGICAL'] == EXPECTED[region]['staff_matk']
    assert luautil.lua is state


@pytest.mark.parametrize('region', ('ktos', 'ktest'))
def test_native_regions_ignore_xml_tsv_and_working_directory_translations(tmp_path, monkeypatch, region):
    root = prepare_regional_workspace(tmp_path, region)
    (root / (region + '_unpack') / 'language.ipf/wholeDicID.xml').write_text('not xml')
    (root / 'parser_tidy/poison.tsv').write_text('HARNESS_ORE_NAME\tIncorrect translation\n')
    monkeypatch.chdir(root / 'parser_tidy')
    db = parse(root, region)
    assert db.data['dictionary'] == {}
    assert db.data['items_by_name']['harness_ore']['Name'] == '원석'


@pytest.mark.parametrize('region', ('itos', 'jtos', 'twtos'))
def test_translation_missing_or_invalid_preserves_the_published_region(tmp_path, region):
    root = prepare_regional_workspace(tmp_path, region)
    db = parse(root, region)
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    language = EXPECTED[region]['translation_directory']
    translation = root / 'Translation' / language / 'regional.tsv'
    content = translation.read_bytes()
    translation.unlink()
    with pytest.raises(FileNotFoundError, match='Missing parser fixture input'):
        parse(root, region, 'regional-v2')
    assert snapshot(release) == before
    translation.write_bytes(content)
    xml = root / (region + '_unpack') / 'language.ipf/wholeDicID.xml'
    content = xml.read_bytes()
    xml.write_text('invalid xml')
    from xml.etree.ElementTree import ParseError
    with pytest.raises(ParseError):
        parse(root, region, 'regional-v2')
    assert snapshot(release) == before
    xml.write_bytes(content)
    parse(root, region, 'regional-v2')
    assert json.loads((release / 'version.json').read_text())['version'] == 'regional-v2'


@pytest.mark.parametrize('region', REGIONS)
def test_missing_and_bad_additional_source_preserve_release_and_allow_retry(tmp_path, region):
    root = prepare_regional_workspace(tmp_path, region)
    db = parse(root, region)
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    card = root / (region + '_unpack') / 'ies.ipf/cardbattle.ies'
    content = card.read_bytes()
    card.unlink()
    with pytest.raises(FileNotFoundError, match='cardbattle.ies'):
        parse(root, region, 'regional-v2')
    assert snapshot(release) == before
    card.write_bytes(content)
    change_ies_column(card, 'Height', 'invalid')
    with pytest.raises(ValueError):
        parse(root, region, 'regional-v2')
    assert snapshot(release) == before
    card.write_bytes(content)
    parse(root, region, 'regional-v2')
    assert json.loads((release / 'version.json').read_text())['version'] == 'regional-v2'


@pytest.mark.parametrize('failure', ('missing_function', 'runtime_error'))
def test_equipment_refresh_failure_cannot_publish_zero_stats(tmp_path, failure):
    root = prepare_regional_workspace(tmp_path, 'jtos')
    db = parse(root, 'jtos')
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    source = root / 'jtos_unpack/shared.ipf/item_calculate.lua'
    original = source.read_text()
    if failure == 'missing_function':
        invalid = original.replace('function SCR_HARNESS_REFRESH_STAFF(', 'function REMOVED_STAFF(')
    else:
        invalid = original.replace('item.MATK = tonumber(item.UseLv)', 'item.MATK = error("fixture failure") + tonumber(item.UseLv)')
    source.write_text(invalid)
    with pytest.raises(ValueError, match='Equipment refresh failed for harness_staff'):
        parse(root, 'jtos', 'regional-v2')
    assert snapshot(release) == before
    source.write_text(original)
    parse(root, 'jtos', 'regional-v2')
    assert json.loads((release / 'version.json').read_text())['version'] == 'regional-v2'


@pytest.mark.parametrize('region', ('ktos', 'ktest', 'jtos', 'twtos'))
def test_preferred_and_current_drop_datasets_have_truthful_provenance(tmp_path, region):
    root = prepare_regional_workspace(tmp_path, region)
    preferred = root / 'itos_unpack/ies_drop.ipf'
    current = root / (region + '_unpack') / 'ies_drop.ipf'
    shutil.copytree(preferred, current)
    change_ies_column(current / 'HARNESS_WOLF.IES', 'DropRatio', '5500')
    db = parse(root, region)
    provenance = db.data['build_provenance']['item_monster']
    assert db.data['item_monster'][0]['Chance'] == 12.5
    assert provenance['source_region'] == 'itos'
    assert 'preferred itos' in provenance['fallback_reason']
    assert 'absent' not in provenance['fallback_reason']
    # Directory selection does not borrow individual files from the lower priority source.
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    original = (preferred / 'HARNESS_WOLF.IES').read_bytes()
    (preferred / 'HARNESS_WOLF.IES').unlink()
    with pytest.raises(FileNotFoundError, match='HARNESS_WOLF.IES'):
        parse(root, region, 'regional-v2')
    assert snapshot(release) == before
    (preferred / 'HARNESS_WOLF.IES').write_bytes(original)
    shutil.rmtree(preferred)
    db = parse(root, region, 'regional-v2')
    provenance = db.data['build_provenance']['item_monster']
    assert db.data['item_monster'][0]['Chance'] == 55
    assert provenance == {'source_region': region, 'input_version': 'regional-source-' + region + '-v1',
                          'fallback_reason': None}


@pytest.mark.parametrize('region', ('itos', 'jtos'))
def test_ktest_skill_fallback_is_used_only_after_ktos_is_unavailable(tmp_path, region):
    root = prepare_regional_workspace(tmp_path, region)
    (root / 'TavernofSoul/JSON_ktos/skills_by_name.json').unlink()
    db = parse(root, region)
    skill = db.data['skills']['403']
    assert skill['Icon'] == 'icon_regional_ktest'
    assert skill['Name'] == EXPECTED[region]['names']['support']
    assert skill['$ID'] == '403'
    assert skill['Description'] == ('' if region == 'itos' else 'KTest 보충 설명')
    assert skill['Effect'] == ('' if region == 'itos' else 'KTest 보충 효과')
