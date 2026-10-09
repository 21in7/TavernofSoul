"""Five real parser paths with language, source selection and extra item types."""
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

import luautil
import vaivora
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


def _tooltip_context(root, region='ktos'):
    return SimpleNamespace(
        PATH_INPUT_DATA=str(root / 'input'),
        transaltion_path=str(root / 'translation'),
        region=region,
        data={'dictionary': {'dup': 'incorrect dictionary text'}, 'items_by_name': {}},
    )


def _write_tooltip_xml(c, xml):
    path = Path(c.PATH_INPUT_DATA) / 'language.ipf' / 'DicIDTable.xml'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding='utf-8')
    return path


def _write_tooltip_tsv(c, text):
    path = Path(c.transaltion_path) / 'tooltip.tsv'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def test_tooltip_attributes_preserve_numeric_order_preorder_and_pattern_semantics(tmp_path):
    c = _tooltip_context(tmp_path)
    _write_tooltip_xml(c, '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE root [<!ENTITY greeting "안녕">]>
<root xmlns:n="urn:ignored">
  <dic_data FilenameWithKey="prefix/tooltip_Order_Data_10" kr="열🌟"/>
  <dic_data FilenameWithKey="tooltip_Nested_Data_2" kr="outer">
    <dic_data FilenameWithKey="tooltip_Child_Data_1" kr="child"/>
    <dic_data FilenameWithKey="tooltip_Nested_Data_02" kr="inner"/>
  </dic_data>
  <dic_data FilenameWithKey="tooltip_Order_Data_2" kr="old"/>
  <dic_data FilenameWithKey="tooltip_Order_Data_1" kr="&greeting;&amp;&lt;&quot;&apos;"/>
  <dic_data FilenameWithKey="tooltip_Order_Data_02" kr="둘"/>
  <dic_data FilenameWithKey="tooltip_Blank_Data_10" kr="must be cleared"/>
  <dic_data FilenameWithKey="tooltip_Blank_Data_10" ID="" kr="">ignored text</dic_data>
  <dic_data FilenameWithKey="tooltip_Blank_Data_2" kr="must be cleared"/>
  <dic_data FilenameWithKey="tooltip_Blank_Data_2">ignored text<b>child text</b></dic_data>
  <dic_data FilenameWithKey="tooltip_Blank_Data_1" kr=""/>ignored tail
  <dic_data FilenameWithKey="tooltip_Text_Data_1" kr="attribute">ignored text</dic_data>ignored tail
  <wrapper><dic_data FilenameWithKey="other:tooltip_A_9_Data_1" kr="searched"/></wrapper>
  <dic_data FilenameWithKey="tooltip_Newline_Data_1&#10;" kr="last newline"/>
  <dic_data FilenameWithKey="tooltip_BadNewlines_Data_1&#10;&#10;" kr="ignored"/>
  <dic_data FilenameWithKey="tooltip_BadSuffix_Data_1suffix" kr="ignored"/>
  <dic_data FilenameWithKey="tooltip_BadSpace_Data_1 " kr="ignored"/>
  <dic_data FilenameWithKey="tooltip_Bad-Name_Data_1" kr="ignored"/>
  <dic_data FilenameWithKey="tooltip_Negative_Data_-1" kr="ignored"/>
  <dic_data FilenameWithKey="Tooltip_Case_Data_1" kr="ignored"/>
  <dic_data FilenameWithKey="ordinary" kr="ignored"/>
  <dic_data FilenameWithKey="" kr="ignored"/>
  <dic_data Key="tooltip_WrongAttribute_Data_1" kr="ignored"/>
  <other FilenameWithKey="tooltip_WrongTag_Data_1" kr="ignored"/>
  <Dic_data FilenameWithKey="tooltip_WrongCase_Data_1" kr="ignored"/>
  <n:dic_data FilenameWithKey="tooltip_Namespace_Data_1" kr="ignored"/>
  <dic_data xmlns="urn:ignored" FilenameWithKey="tooltip_DefaultNamespace_Data_1" kr="ignored"/>
  <!-- <dic_data FilenameWithKey="tooltip_Comment_Data_1" kr="ignored"/> -->
  <?ignored tooltip_Instruction_Data_1?>
</root>''')
    assert list(vaivora._build_tooltip_index(c).items()) == [
        ('Order', '안녕&<"\'둘열🌟'),
        ('Nested', 'inner'),
        ('Child', 'child'),
        ('Blank', ''),
        ('Text', 'attribute'),
        ('A_9', 'searched'),
        ('Newline', 'last newline'),
    ]


@pytest.mark.parametrize('encoding', ('utf-8', 'utf-16', 'iso-8859-1'))
def test_tooltip_xml_declared_encoding_and_entities(tmp_path, encoding):
    c = _tooltip_context(tmp_path)
    path = _write_tooltip_xml(c, '<root/>')
    xml = '''<?xml version="1.0" encoding="%s"?>
<!DOCTYPE root [<!ENTITY word "caf&#233;">]>
<root><dic_data FilenameWithKey="tooltip_Encoded_Data_1" kr="café &word;"/></root>''' % encoding
    path.write_bytes(xml.encode(encoding))
    assert vaivora._build_tooltip_index(c) == {'Encoded': 'café café'}


@pytest.mark.parametrize('region', ('ktos', 'ktest', 'itos', 'jtos', 'twtos'))
def test_tooltip_regions_use_tsv_duplicates_and_kr_fallback(tmp_path, monkeypatch, region):
    c = _tooltip_context(tmp_path, region)
    _write_tooltip_xml(c, '''<root>
  <dic_data FilenameWithKey="tooltip_Translated_Data_10" ID="discarded" kr="old XML"/>
  <dic_data FilenameWithKey="tooltip_Translated_Data_10" ID="dup" kr="열"/>
  <dic_data FilenameWithKey="tooltip_Translated_Data_2" ID="empty" kr="둘"/>
  <dic_data FilenameWithKey="tooltip_Translated_Data_1" ID="absent" kr="하나"/>
  <dic_data FilenameWithKey="tooltip_MissingId_Data_1" kr="missing ID"/>
  <dic_data FilenameWithKey="tooltip_EmptyId_Data_1" ID="" kr="empty ID"/>
  <dic_data FilenameWithKey="tooltip_EmptyKr_Data_1" ID="unknown"/>
  <dic_data FilenameWithKey="tooltip_EmptyKr_Data_2" ID="unknown2" kr=""/>
  <dic_data FilenameWithKey="tooltip_EntityId_Data_1" ID="A&amp;B" kr="실체"/>
</root>''')
    _write_tooltip_tsv(c, 'discarded\twrong XML translation\ndup\told\nempty\told\ndup\t翻訳✨\nempty\t\n'
                         '\tID 없는 번역\nA&B\tentity translated\n')
    if region in ('ktos', 'ktest'):
        def poison_loader(_c):
            pytest.fail('Native tooltip indexing must not access translations')
        monkeypatch.setattr(vaivora, '_load_dicid_translation', poison_loader)
        expected = {'Translated': '하나둘열', 'MissingId': 'missing ID',
                    'EmptyId': 'empty ID', 'EmptyKr': '', 'EntityId': '실체'}
    else:
        expected = {'Translated': '하나둘翻訳✨', 'MissingId': 'ID 없는 번역',
                    'EmptyId': 'ID 없는 번역', 'EmptyKr': '', 'EntityId': 'entity translated'}
    assert vaivora._build_tooltip_index(c) == expected


def test_tooltip_rebuilds_after_xml_tsv_region_and_input_path_changes(tmp_path):
    c = _tooltip_context(tmp_path / 'first', 'itos')
    _write_tooltip_xml(c, '''<root>
  <dic_data FilenameWithKey="tooltip_First_Data_1" ID="x" kr="첫"/>
  <dic_data FilenameWithKey="tooltip_Stale_Data_1" kr="stale"/>
</root>''')
    _write_tooltip_tsv(c, 'x\tfirst translation\n')
    assert vaivora._build_tooltip_index(c) == {'First': 'first translation', 'Stale': 'stale'}
    _write_tooltip_xml(c, '''<root>
  <dic_data FilenameWithKey="tooltip_First_Data_1" ID="x" kr="둘"/>
  <dic_data FilenameWithKey="tooltip_Fresh_Data_1" kr="fresh"/>
</root>''')
    assert vaivora._build_tooltip_index(c) == {'First': 'first translation', 'Fresh': 'fresh'}
    _write_tooltip_tsv(c, 'x\tsecond translation\n')
    assert vaivora._build_tooltip_index(c) == {'First': 'second translation', 'Fresh': 'fresh'}
    for region in ('ktos', 'ktest'):
        c.region = region
        assert vaivora._build_tooltip_index(c) == {'First': '둘', 'Fresh': 'fresh'}
    c.region = 'jtos'
    assert vaivora._build_tooltip_index(c) == {'First': 'second translation', 'Fresh': 'fresh'}

    other = _tooltip_context(tmp_path / 'other', 'twtos')
    _write_tooltip_xml(other, '''<root>
  <dic_data FilenameWithKey="tooltip_First_Data_1" ID="x" kr="셋"/>
  <dic_data FilenameWithKey="tooltip_OnlyOther_Data_1" kr="other"/>
</root>''')
    _write_tooltip_tsv(other, 'x\tthird translation\n')
    first_input, first_translation = c.PATH_INPUT_DATA, c.transaltion_path
    c.PATH_INPUT_DATA = other.PATH_INPUT_DATA
    assert vaivora._build_tooltip_index(c) == {'First': 'second translation', 'OnlyOther': 'other'}
    c.transaltion_path = other.transaltion_path
    result = vaivora._build_tooltip_index(c)
    assert result == {'First': 'third translation', 'OnlyOther': 'other'}
    result['First'] = 'mutated returned index'
    assert vaivora._build_tooltip_index(other) == {'First': 'third translation', 'OnlyOther': 'other'}
    assert vaivora._build_tooltip_index(c) == {'First': 'third translation', 'OnlyOther': 'other'}
    c.PATH_INPUT_DATA, c.transaltion_path = first_input, first_translation
    assert vaivora._build_tooltip_index(c) == {'First': 'second translation', 'Fresh': 'fresh'}


def test_missing_tooltip_xml_warns_with_exact_path_and_returns_empty(tmp_path, caplog):
    c = _tooltip_context(tmp_path)
    path = Path(c.PATH_INPUT_DATA) / 'language.ipf' / 'DicIDTable.xml'
    with caplog.at_level('WARNING'):
        assert vaivora._build_tooltip_index(c) == {}
    assert [(record.levelname, record.getMessage()) for record in caplog.records] == [
        ('WARNING', 'DicIDTable.xml not found at ' + str(path)),
    ]


@pytest.mark.parametrize('tail', (
    '<broken></root>', '</root><broken', '</root>trailing data',
    '<dic_data kr="&undefined;"/></root>',
))
def test_tooltip_malformed_tail_propagates_closes_file_and_allows_retry(tmp_path, monkeypatch, tail):
    c = _tooltip_context(tmp_path)
    path = _write_tooltip_xml(c, '<root><dic_data FilenameWithKey="tooltip_Ready_Data_1" '
                                 'kr="valid"/>' + tail)
    opened = []
    real_open = open

    def tracked_open(*args, **kwargs):
        source = real_open(*args, **kwargs)
        if args[0] in (path, str(path)):
            opened.append(source)
        return source

    monkeypatch.setattr('builtins.open', tracked_open)
    with pytest.raises(ET.ParseError):
        vaivora._build_tooltip_index(c)
    assert opened and all(source.closed for source in opened)
    path.write_text('<root><dic_data FilenameWithKey="tooltip_Retry_Data_1" kr="정상"/></root>',
                    encoding='utf-8')
    assert vaivora._build_tooltip_index(c) == {'Retry': '정상'}
    assert all(source.closed for source in opened)


def test_tooltip_read_error_propagates_closes_file_and_allows_retry(tmp_path, monkeypatch):
    c = _tooltip_context(tmp_path)
    path = _write_tooltip_xml(c, '<root><dic_data FilenameWithKey="tooltip_Retry_Data_1" kr="정상"/></root>')
    failure = OSError('fixture XML read failed')

    class FailingReader(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise failure
            return super().read(size)

    source = FailingReader(b'<root><dic_data FilenameWithKey="tooltip_Partial_Data_1" kr="partial"/>')
    real_open = open

    def failing_open(file, *args, **kwargs):
        if file in (path, str(path)):
            return source
        return real_open(file, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr('builtins.open', failing_open)
        with pytest.raises(OSError) as caught:
            vaivora._build_tooltip_index(c)
        assert caught.value is failure
        assert source.closed
    assert vaivora._build_tooltip_index(c) == {'Retry': '정상'}


@pytest.mark.parametrize('region', ('ktos', 'ktest', 'itos', 'jtos', 'twtos'))
def test_additional_options_keep_bonus_order_file_precedence_and_repeat_append(tmp_path, region):
    c = _tooltip_context(tmp_path, region)
    _write_tooltip_xml(c, '''<root>
  <dic_data FilenameWithKey="tooltip_First_Data_2" ID="fallback" kr="둘"/>
  <dic_data FilenameWithKey="tooltip_First_Data_1" ID="first" kr="첫"/>
  <dic_data FilenameWithKey="tooltip_Vision_Lv4_Data_1" ID="level" kr="레벨4"/>
  <dic_data FilenameWithKey="tooltip_Empty_Data_1" ID="empty"/>
  <dic_data FilenameWithKey="tooltip_Fourth_Data_1" ID="absent" kr="마지막"/>
  <dic_data FilenameWithKey="tooltip_Vision_lV4_Data_1" ID="mixed" kr="혼합"/>
  <dic_data FilenameWithKey="tooltip_Old_Data_1" kr="wrong earlier option"/>
</root>''')
    _write_tooltip_tsv(c, 'first\ttranslated first\nlevel\ttranslated level\n'
                         'mixed\ttranslated mixed\nempty\t\n')
    header = 'ClassName,AdditionalOption_1,AdditionalOption_2,AdditionalOption_3,AdditionalOption_4\n'
    sources = {
        'item.ies': 'shared,Old,,,\nonly_item,Fourth,Missing,,\nno_opts,,,,\n',
        'equip.ies': ('shared,Old,,,\nshared,First,Vision_Lv4,Empty,Fourth\n'
                      'unresolved,Missing,First,,Vision_lV4\nonly_unknown,Missing,,,\n'
                      'unregistered,First,,,\n,First,,,\n'),
        'late.ies': 'shared,Old,,,\n',
        'empty.ies': 'shared,,,,\n',
        'unlisted.ies': 'shared,Old,,,\n',
    }
    # file_dict order is irrelevant; the configured lists choose the inputs.
    c.file_dict = {}
    for name in reversed(tuple(sources)):
        path = tmp_path / name
        path.write_text(header + sources[name], encoding='utf-8')
        c.file_dict[name] = {'path': str(path)}
    c.file_dict['gone.ies'] = {'path': str(tmp_path / 'absent.ies')}
    c.ITEM_IES = ('ITEM.IES', 'Equip.IES', 'late.ies', 'empty.ies', 'unknown.ies', 'gone.ies')
    # Re-reading equip after late restores its row, without appending twice.
    # Rows with no options do not erase an earlier selected row.
    c.EQUIPMENT_IES = ('Equip.IES', 'empty.ies')
    shared = {'Name': 'shared item', 'Bonus': [['STR', 7], ['lv4', 'existing level text']]}
    unresolved = {'Name': 'unresolved item', 'Bonus': [['DEX', 3]]}
    only_item = {'Name': 'ordinary item'}
    only_unknown = {'Name': 'unknown item', 'Bonus': [['CON', 5]]}
    no_opts = {'Name': 'no options', 'Bonus': [['INT', 2]]}
    c.data['items_by_name'] = {
        'shared': shared, 'unresolved': unresolved, 'only_item': only_item,
        'only_unknown': only_unknown, 'no_opts': no_opts,
    }
    c.data['items'] = {'1': shared, '2': unresolved, '3': only_item,
                       '4': only_unknown, '5': no_opts}
    native = region in ('ktos', 'ktest')
    first = '첫둘' if native else 'translated first둘'
    level = '레벨4' if native else 'translated level'
    mixed = '혼합' if native else 'translated mixed'
    shared_append = [['add_opt', first], ['lv4', level], ['add_opt', ''], ['add_opt', '마지막']]
    unresolved_append = [['add_opt', first], ['lv4', mixed]]

    for run in (1, 2):
        vaivora.parse_additional_options(c)
        assert c.data['items']['1']['Bonus'] == [['STR', 7], ['lv4', 'existing level text']] + shared_append * run
        assert c.data['items']['2']['Bonus'] == [['DEX', 3]] + unresolved_append * run
        assert c.data['items']['3']['Bonus'] == [['add_opt', '마지막']] * run
        assert c.data['items']['4']['Bonus'] == [['CON', 5]]
        assert c.data['items']['5']['Bonus'] == [['INT', 2]]
