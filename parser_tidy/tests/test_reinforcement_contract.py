"""Reject malformed optional enhancement data at the shared release boundary."""
import copy
import json
from pathlib import Path

import pytest

from harness.parser_fixture import parse_workspace, prepare_equipment_workspace
from ipfparser.contracts import ContractError, validate_release


@pytest.fixture(scope='module')
def release(tmp_path_factory):
    root = prepare_equipment_workspace(tmp_path_factory.mktemp('reinforcement-contract'))
    db = parse_workspace(root, 'reinforcement-contract', include_equipment=True)
    return {path.stem: json.loads(path.read_text()) for path in Path(db.BASE_PATH_OUTPUT).glob('*.json')}


def bad_data(data, case):
    table = data['goddess_reinf']['560']
    material = data['goddess_reinf_mat']['560']['weapon']['6']
    if case == 'probability': table[5]['BasicProp'] = '100001'
    elif case == 'negative_bonus': table[5]['AddAtk'] = '-1'
    elif case == 'large_bonus': table[5]['AddAtk'] = '2147483648'
    elif case == 'duplicate_step': table[5]['ClassID'] = '5'
    elif case == 'missing_step': table.pop(5)
    elif case == 'duplicate_level': data['goddess_reinf']['0560'] = copy.deepcopy(table)
    elif case == 'duplicate_material_step': data['goddess_reinf_mat']['560']['weapon']['06'] = material.copy()
    elif case == 'negative_quantity': material['harness_ore'] = -1
    elif case == 'fractional_quantity': material['harness_ore'] = 0.5
    elif case == 'boolean_quantity': material['harness_ore'] = True
    elif case == 'missing_table': data['goddess_reinf'].pop('560')
    elif case == 'missing_pair': data.pop('goddess_reinf_mat')
    elif case == 'unknown_group': data['goddess_reinf_mat']['560']['mystery'] = {}
    elif case == 'short_calculation': data['items_by_name']['harness_sword']['AnvilATK'].pop()
    elif case == 'calculation_level': data['items_by_name']['harness_sword']['GoddessReinforceLevel'] = 580
    elif case == 'gem_zero_level': data['items_by_name']['harness_gem']['BonusWeapon'][0]['Level'] = 0
    elif case == 'gem_boolean_level': data['items_by_name']['harness_gem']['BonusWeapon'][0]['Level'] = True
    elif case == 'gem_bad_value': data['items_by_name']['harness_gem']['BonusWeapon'][0]['Value'] = {}
    elif case == 'gem_empty_stat': data['items_by_name']['harness_gem']['BonusWeapon'][0]['Stat'] = ''


@pytest.mark.parametrize('case', ('probability', 'negative_bonus', 'large_bonus', 'duplicate_step',
    'missing_step', 'duplicate_level', 'duplicate_material_step', 'negative_quantity',
    'fractional_quantity', 'boolean_quantity', 'missing_table', 'missing_pair', 'unknown_group',
    'short_calculation', 'calculation_level', 'gem_zero_level', 'gem_boolean_level', 'gem_bad_value', 'gem_empty_stat'))
def test_invalid_enhancement_data_is_rejected(release, case):
    value = copy.deepcopy(release)
    bad_data(value, case)
    with pytest.raises(ContractError):
        validate_release(value)


def test_optional_legacy_bonus_level_and_text_values_are_preserved_without_inference(release):
    value = copy.deepcopy(release)
    bonus = value['items_by_name']['harness_gem']['BonusWeapon'][0]
    bonus.pop('Level')
    bonus['Value'] = '기존 설명'
    before = copy.deepcopy(value)
    validate_release(value)
    assert value == before
