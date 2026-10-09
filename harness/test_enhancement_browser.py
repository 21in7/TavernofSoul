"""Source-independent expected results for the actual shipped calculator."""
import pytest

from harness.browser_calculator import run_calculator


def data():
    return {'goddess': True, 'maximum': 2, 'attack': [100, 250], 'defense': [200, 450],
            'steps': [{'step': 1, 'chance': 100, 'materials': []},
                      {'step': 2, 'chance': 0, 'materials': [
                          {'name': '</script><img src=x onerror=alert(1)>', 'quantity': 7, 'url': '/items/1'},
                          {'name': 'unknown_currency', 'quantity': 2, 'url': None}]}],
            'prices': [], 'transcendPrices': [3, 6, 9], 'transcendRate': 0.03,
            'base': {'patk': 1000, 'patk_max': 1100, 'matk': 0, 'pdef': 2000, 'mdef': 3000}}


def test_controls_use_cumulative_source_values_reset_and_safely_render_materials():
    result = run_calculator(data(), [{'anvil': 1}, {'anvil': 2, 'tc': 2, 'event': 'tc'}, {'anvil': 0, 'tc': 0}])
    assert result['initial']['patk']['text'] == '1,000'
    first, second, reset = result['results']
    assert first['calculation']['stats']['patk'] == 1100
    assert first['display']['god_materials']['text'] == '0'
    assert second['calculation']['stats'] == {'patk': 1310, 'patk_max': 1416, 'matk': 250, 'pdef': 2570, 'mdef': 3630}
    assert second['display']['god_chance']['text'] == '0%'
    assert second['display']['tc_total']['text'] == '9'
    assert second['display']['god_materials']['links'] == [
        {'text': '</script><img src=x onerror=alert(1)>', 'href': '/items/1'}]
    assert 'unknown_currency × 2' in second['display']['god_materials']['text']
    assert reset['display']['god_materials']['text'] == '—'
    assert reset['calculation']['stats']['patk'] == 1000


@pytest.mark.parametrize('value, expected', [('-3', 0), ('invalid', 0), ('Infinity', 0), ('1.9', 1), ('99', 2), ('', 0)])
def test_enhancement_input_bounds(value, expected):
    result = run_calculator(data(), [{'anvil': value}])['results'][0]
    assert result['display']['anvil']['value'] == str(expected)
    assert result['calculation']['step'] == expected


def test_event_order_normal_equipment_totals_and_transcend_bounds():
    payload = data()
    payload.update(goddess=False, prices=[10, 20], transcendRate=0.1)
    forward = run_calculator(payload, [{'anvil': 2}, {'tc': 2, 'event': 'tc'}])['results'][-1]
    reverse = run_calculator(payload, [{'tc': 2, 'event': 'tc'}, {'anvil': 2}])['results'][-1]
    assert forward == reverse
    assert forward['calculation']['stats']['patk_max'] == 1570
    assert forward['display']['anvil_price']['text'] == '20'
    assert forward['display']['anvil_total']['text'] == '30'
    result = run_calculator(payload, [{'tc': 99, 'event': 'tc'}, {'tc': -1, 'event': 'tc'}])['results']
    assert result[0]['display']['tc']['value'] == '3'
    assert result[0]['display']['tc_total']['text'] == '18'
    assert result[1]['display']['tc_bonus']['text'] == '0%'


def test_missing_material_costs_are_not_displayed_as_free():
    payload = data()
    payload['steps'][0]['materials'] = None
    assert run_calculator(payload, [{'anvil': 1}])['results'][0]['display']['god_materials']['text'] == '—'


def test_missing_controls_are_safe():
    assert run_calculator(data(), [], ids=['patk'])['initial']['patk']['text'] == ''
