"""The engine XML extension preserves ScriptName controls without repairing XML."""
import io
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

import game_xml
import skill_bytool


FORBIDDEN_CONTROLS = tuple(chr(code) for code in range(32) if code not in (9, 10, 13))


def tree_values(root):
    """Include node order, attributes, text and tails so lost nodes cannot pass."""
    return [(node.tag, dict(node.attrib), node.text, node.tail) for node in root.iter()]


@pytest.mark.parametrize('xml', [
    '<Root/>',
    '<?xml version="1.0"?><Root ScriptName="plain &amp; valid"><Child/>tail</Root>',
    '<Root><!-- ScriptName="fake" --><![CDATA[<Fake ScriptName="fake"/>]]>'
    '<?engine ScriptName="fake"?><Child ScriptName=\'single\'/></Root>',
    '<Root xmlns:s="urn:test" s:ScriptName="valid" ScriptName="&gt;x}"/>',
])
def test_normal_xml_matches_standard_elementtree(xml):
    expected = tree_values(ET.fromstring(xml))
    assert tree_values(game_xml.fromstring(xml)) == expected
    assert tree_values(game_xml.parse(io.StringIO(xml)).getroot()) == expected


@pytest.mark.parametrize('control', FORBIDDEN_CONTROLS,
                         ids=['U+{:04X}'.format(ord(char)) for char in FORBIDDEN_CONTROLS])
@pytest.mark.parametrize('quote', ['"', "'"])
def test_every_forbidden_ascii_control_is_restored_only_in_scriptname(control, quote):
    # A quoted > before and inside ScriptName must not end the actual start tag.
    xml = '<Root Other="a > b"><Child ScriptName={q}푗}}>{c}&gt;x{q}/></Root>'.format(
        q=quote, c=control)
    with pytest.raises(ET.ParseError):
        ET.fromstring(xml)
    root = game_xml.fromstring(xml)
    assert root.attrib == {'Other': 'a > b'}
    assert root[0].attrib == {'ScriptName': '푗}>' + control + '>x'}
    assert [node.tag for node in root.iter()] == ['Root', 'Child']


@pytest.mark.parametrize('whitespace', ['\t', '\n', '\r', '\r\n', '\t\n\r'])
def test_allowed_attribute_whitespace_retains_standard_xml_normalization(whitespace):
    xml = '<Root ScriptName="a' + whitespace + 'b">a' + whitespace + 'b</Root>'
    assert tree_values(game_xml.fromstring(xml)) == tree_values(ET.fromstring(xml))


@pytest.mark.parametrize('collision', ['literal', 'character-reference', 'dtd-entity'])
def test_marker_collision_does_not_change_unrelated_values(collision):
    marker = '__TOS_SCRIPTNAME_CONTROL__0__'
    encoded = ''.join('&#{};'.format(ord(char)) for char in marker)
    declaration = ''
    if collision == 'literal':
        value = marker
    elif collision == 'character-reference':
        value = encoded
    else:
        declaration = '<!DOCTYPE Root [<!ENTITY marker "' + encoded + '">]>'
        value = '&marker;'
    xml = (declaration + '<Root Other="' + value + '"><Child ScriptName="a\x01b"/>'
           '<Child ScriptName="' + value + '"/>' + value + '</Root>')
    root = game_xml.fromstring(xml)
    assert root.attrib == {'Other': marker}
    assert root[0].get('ScriptName') == 'a\x01b'
    assert root[1].get('ScriptName') == marker
    assert root[1].tail == marker


@pytest.mark.parametrize('fragment', [
    '<!-- <Fake ScriptName="a\x01b"/> -->',
    '<![CDATA[<Fake ScriptName="a\x01b"/>]]>',
    '<?engine <Fake ScriptName="a\x01b"/> ?>',
])
def test_fake_attributes_in_comments_cdata_and_pi_remain_invalid(fragment):
    with pytest.raises(ET.ParseError):
        game_xml.fromstring('<Root ScriptName="allowed\x01">' + fragment + '</Root>')


@pytest.mark.parametrize('name', ['scriptname', 'SCRIPTNAME', 'OtherScriptName',
                                 'ScriptNameExtra', 's:ScriptName'])
def test_attribute_name_must_be_exact(name):
    with pytest.raises(ET.ParseError):
        game_xml.fromstring('<Root xmlns:s="urn:test" ' + name + '="a\x01b"/>')


@pytest.mark.parametrize('control', FORBIDDEN_CONTROLS,
                         ids=['U+{:04X}'.format(ord(char)) for char in FORBIDDEN_CONTROLS])
@pytest.mark.parametrize('location', ['other-attribute', 'text', 'tail'])
def test_every_forbidden_control_outside_scriptname_remains_invalid(control, location):
    if location == 'other-attribute':
        body = '<Child Other="a' + control + 'b"/>'
    elif location == 'text':
        body = 'a' + control + 'b<Child/>'
    else:
        body = '<Child/>a' + control + 'b'
    with pytest.raises(ET.ParseError):
        game_xml.fromstring('<Root ScriptName="allowed\x01">' + body + '</Root>')


@pytest.mark.parametrize('xml', [
    '<Root ScriptName="ok\x01" Other="bad\x01"/>',
    '<Root ScriptName="ok\x01">bad\x01<Child/></Root>',
    '<Root ScriptName="ok\x01"><Child/>bad\x01</Root>',
    '<Root ScriptName="&#1;"/>',
    '<Root ScriptName="&#x01;"/>',
    '<Root ScriptName="ok\x01"><Child></Root>',
    '<Root ScriptName="ok\x01" Other=unquoted/>',
    '<Root ScriptName="ok\x01" ScriptName="duplicate"/>',
    '<Root ScriptName="ok\x01" Other="unterminated/>',
    '<Root ScriptName="ok\x01">&undefined;</Root>',
    '<Root ScriptName="ok\x01"/><Second/>',
    '<Root ScriptName="ok\x01" <Child/>',
    '<Root ScriptName="ok\x01"></Root ScriptName="bad\x01">',
    '<Root ScriptName="ok\x01"><!-- unterminated</Root>',
    '<Root ScriptName="ok\x01"><![CDATA[unterminated</Root>',
    '<Root ScriptName="ok\x01"><?engine unterminated</Root>',
    '<Root ScriptName="ok\x01"/>trailing text',
])
def test_other_controls_and_malformed_markup_still_raise_parseerror(xml):
    with pytest.raises(ET.ParseError):
        game_xml.fromstring(xml)
    with pytest.raises(ET.ParseError):
        game_xml.parse(io.StringIO(xml))


def synthetic_skill_xml(script_name):
    return '''<?xml version="1.0" encoding="utf-8"?>
<Skills Preserve="root">
  <Unused ScriptName="{script}" Other="quoted > boundary"><Leaf>keep me</Leaf>tail</Unused>
  <Skill Name="Regression_ControlSkill">
    <ResultList><ToolScp Scp="S_R_TGTBUFF">
      <Arg Str="Regression_ShieldBuff"/><Arg Num="1"/><Arg Num="0"/>
      <Arg Num="2500"/><Arg Num="0"/><Arg Num="75"/>
    </ToolScp></ResultList>
  </Skill>
  <Skill Name="Regression_EmptySkill"><ResultList/><EtcList/></Skill>
  <Unrelated Flag="retained">final text</Unrelated>
</Skills>'''.format(script=script_name)


def test_synthetic_file_preserves_all_nodes_original_attributes_and_bytes(tmp_path):
    controls = ''.join(FORBIDDEN_CONTROLS)
    xml = synthetic_skill_xml('푗}' + controls + '&gt;x}')
    path = tmp_path / 'engine.xml'
    original = xml.encode('utf-8')
    path.write_bytes(original)
    expected = ET.fromstring(synthetic_skill_xml('safe'))
    expected.find('Unused').set('ScriptName', '푗}' + controls + '>x}')
    with path.open(encoding='utf-8', newline='') as stream:
        parsed = game_xml.parse(stream).getroot()
    assert tree_values(parsed) == tree_values(expected)
    assert len(list(parsed.iter())) == 16
    assert path.read_bytes() == original


def test_multiple_scriptname_values_are_restored_without_changing_other_values():
    xml = '<Root ScriptName="one\x00"><Child ScriptName=\'two\x01\x1f\'>' \
          'keep<Leaf ScriptName="three\x0b" Other="one"/>tail</Child></Root>'
    root = game_xml.fromstring(xml)
    assert tree_values(root) == [
        ('Root', {'ScriptName': 'one\x00'}, None, None),
        ('Child', {'ScriptName': 'two\x01\x1f'}, 'keep', None),
        ('Leaf', {'ScriptName': 'three\x0b', 'Other': 'one'}, None, 'tail'),
    ]


def test_skill_metadata_is_identical_with_unused_scriptname_controls(tmp_path):
    results = []
    for variant, script_name in [('normal', 'safe'), ('controls', '푗}\x01&gt;x}\x1f')]:
        root = tmp_path / variant
        directory = root / 'skill_bytool.ipf'
        directory.mkdir(parents=True)
        path = directory / 'synthetic.xml'
        original = synthetic_skill_xml(script_name).encode('utf-8')
        path.write_bytes(original)
        db = SimpleNamespace(PATH_INPUT_DATA=str(root), data={})
        skill_bytool.parse(db)
        results.append(db.data['xml_skills'])
        assert path.read_bytes() == original
    expected = {'Regression_ControlSkill': {
        'ClassName': 'Regression_ControlSkill',
        'TargetBuffs': ['Regression_ShieldBuff;2.5;75'],
    }}
    assert results == [expected, expected]
