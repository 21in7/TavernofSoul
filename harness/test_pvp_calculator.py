"""Pytest executes the delivered, dependency-free JS; Node is required, never skipped.

Numerical oracles are fixed examples and ordering/complement properties, not a
second implementation of the supplied formulas. The DOM double tests wiring;
Playwright separately tests the real rendered template and browser layout.
"""
import json
import math
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'TavernofSoul/static/js/pvp-calculator.js'
DEFAULTS = {
    'myLevel': 500, 'opponentLevel': 500, 'accuracy': 20000, 'evasion': 20000,
    'critical': 20000, 'criticalResistance': 20000, 'block': 20000,
    'blockPenetration': 20000,
}
STATS = tuple(key for key in DEFAULTS if key not in ('myLevel', 'opponentLevel'))
BASE = {'hit': 90, 'evasion': 10, 'critical': 10, 'block': 30, 'levelFactor': 1}

# Kept inline so no extra driver file or package is needed.
DRIVER = r"""
'use strict';
const fs = require('fs');
const vm = require('vm');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const api = require(process.argv[1]);
if (request.operation === 'calculate') {
    const results = request.cases.map(raw => {
        const before = JSON.stringify(raw);
        const validation = api.validateInputs(raw);
        const calculation = api.calculate(raw);
        if (before !== JSON.stringify(raw)) throw new Error('input was mutated');
        return {validation, calculation};
    });
    process.stdout.write(JSON.stringify({defaults: api.DEFAULTS, limits: api.LIMITS, results}));
} else {
    const keys = Object.keys(api.DEFAULTS);
    const fields = Object.fromEntries(keys.map(key => [key, {
        value: String(api.DEFAULTS[key]), attributes: {},
        setAttribute(name, value) { this.attributes[name] = value; }
    }]));
    const errors = Object.fromEntries(keys.map(key => [key, {hidden: true}]));
    const summary = {hidden: true};
    const outputs = ['hit', 'evasion', 'critical', 'block', 'levelFactor'].map(key => ({
        key, textContent: '—', getAttribute(name) {
            if (name !== 'data-pvp-result') throw new Error(name);
            return key;
        }
    }));
    const listeners = {};
    const form = {
        querySelector(selector) {
            const match = selector.match(/^\[name="(.+)"\]$/);
            if (!match || !fields[match[1]]) throw new Error(selector);
            return fields[match[1]];
        },
        addEventListener(name, listener) { listeners[name] = listener; }
    };
    const element = {
        querySelector(selector) {
            if (selector === 'form') return form;
            if (selector === '[data-pvp-error]') return summary;
            const match = selector.match(/^#pvp-(.+)-error$/);
            if (!match || !errors[match[1]]) throw new Error(selector);
            return errors[match[1]];
        },
        querySelectorAll(selector) {
            if (selector !== '[data-pvp-result]') throw new Error(selector);
            return outputs;
        }
    };
    let onReady;
    const document = {
        readyState: request.readyState,
        getElementById(id) {
            if (id !== 'pvp-calculator') throw new Error(id);
            return element;
        },
        addEventListener(name, listener) {
            if (name !== 'DOMContentLoaded') throw new Error(name);
            onReady = listener;
        }
    };
    const window = {};
    vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {document, window});
    const waiting = Object.keys(listeners).length === 0;
    if (request.readyState === 'loading') {
        if (!onReady) throw new Error('DOMContentLoaded was not registered');
        onReady();
    }
    function snapshot(prevented) {
        return {
            values: Object.fromEntries(keys.map(key => [key, fields[key].value])),
            invalid: Object.fromEntries(keys.map(key => [key, fields[key].attributes['aria-invalid']])),
            errors: Object.fromEntries(keys.map(key => [key, !errors[key].hidden])),
            summaryVisible: !summary.hidden,
            results: Object.fromEntries(outputs.map(output => [output.key, output.textContent])),
            prevented
        };
    }
    const snapshots = [snapshot(false)];
    for (const action of request.actions) {
        Object.entries(action.values || {}).forEach(([key, value]) => { fields[key].value = value; });
        let prevented = false;
        if (!listeners[action.event]) throw new Error('Missing listener: ' + action.event);
        listeners[action.event]({preventDefault() { prevented = true; }});
        snapshots.push(snapshot(prevented));
    }
    process.stdout.write(JSON.stringify({waiting, events: Object.keys(listeners), snapshots}));
}
"""


def node(request):
    process = subprocess.run(
        ['node', '-e', DRIVER, str(SCRIPT)], input=json.dumps(request),
        capture_output=True, text=True, timeout=20,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def calculations(*overrides):
    response = node({'operation': 'calculate',
                     'cases': [dict(DEFAULTS, **change) for change in overrides]})
    return response['results']


def valid_result(record):
    assert record['validation']['valid'] is True
    assert record['validation']['errors'] == {}
    assert record['calculation']['valid'] is True
    assert record['calculation']['errors'] == {}
    results = record['calculation']['results']
    assert set(results) == set(BASE)
    for key in ('hit', 'evasion', 'critical', 'block'):
        assert math.isfinite(results[key]) and 0 <= results[key] <= 100
    assert 0 <= results['levelFactor'] <= 1
    assert results['hit'] + results['evasion'] == pytest.approx(100)
    return results


def test_defaults_equal_stats_and_zero_stats_have_independent_baselines():
    response = node({'operation': 'calculate', 'cases': [DEFAULTS]})
    assert response['defaults'] == DEFAULTS
    assert response['limits'] == {'level': 10000, 'stat': 10**12, 'characters': 64}
    for record in calculations({}, {key: 0 for key in DEFAULTS},
                               {key: 123.5 for key in STATS}):
        assert valid_result(record) == pytest.approx(BASE)


def test_plus_ten_changes_small_stat_ratios_and_critical_example():
    small, large, critical = [valid_result(record) for record in calculations(
        {'accuracy': 10, 'evasion': 0, 'critical': 10, 'criticalResistance': 0,
         'block': 10, 'blockPenetration': 0},
        {'accuracy': 20000, 'evasion': 10000, 'critical': 20000,
         'criticalResistance': 10000, 'block': 20000, 'blockPenetration': 10000},
        {'critical': 25000, 'criticalResistance': 20000},
    )]
    # Known values for the adjusted 20:10 ratio, including block's direction.
    assert small['hit'] == pytest.approx(97.2972972973)
    assert small['critical'] == pytest.approx(30.7692307692)
    assert small['block'] == pytest.approx(63.1578947368)
    # The same raw 2:1 ratio differs at low and high stats because of +10.
    low_ratio = valid_result(calculations({'accuracy': 20, 'evasion': 10,
                                         'critical': 20, 'criticalResistance': 10,
                                         'block': 20, 'blockPenetration': 10})[0])
    for key in ('hit', 'critical', 'block'):
        assert low_ratio[key] < large[key]
    assert critical['critical'] == pytest.approx(14.8, abs=0.02)
    assert critical['hit'] == pytest.approx(90)
    assert critical['block'] == pytest.approx(30)


@pytest.mark.parametrize('gap,factor,hit,evasion', [
    (-500, 1, 90, 10), (-1, 1, 90, 10), (0, 1, 90, 10),
    (1, .98, 88.2, 11.8), (25, .5, 45, 55), (49, .02, 1.8, 98.2),
    (50, 0, 0, 100), (51, 0, 0, 100), (9500, 0, 0, 100),
])
def test_level_boundaries_affect_only_final_hit_and_opponent_evasion(gap, factor, hit, evasion):
    result = valid_result(calculations({'opponentLevel': 500 + gap})[0])
    assert result == pytest.approx({'hit': hit, 'evasion': evasion,
                                  'critical': 10, 'block': 30, 'levelFactor': factor})


@pytest.mark.parametrize('own,opponent,result_key', [
    ('accuracy', 'evasion', 'hit'), ('critical', 'criticalResistance', 'critical'),
    ('block', 'blockPenetration', 'block'),
])
def test_own_stats_increase_probability_and_opponent_stats_reduce_it(own, opponent, result_key):
    records = calculations(*[{own: value} for value in (0, 100, 20000, 25000, 10**12)],
                           *[{opponent: value} for value in (0, 100, 20000, 25000, 10**12)])
    results = [valid_result(record) for record in records]
    own_values = [result[result_key] for result in results[:5]]
    opponent_values = [result[result_key] for result in results[5:]]
    assert all(a < b for a, b in zip(own_values, own_values[1:]))
    assert all(a > b for a, b in zip(opponent_values, opponent_values[1:]))
    for result in results:
        for unrelated in {'hit', 'critical', 'block'} - {result_key}:
            assert result[unrelated] == pytest.approx(BASE[unrelated])


def test_large_valid_extremes_remain_finite_and_bounded():
    records = calculations(
        {key: 10**12 for key in STATS},
        {'accuracy': 10**12, 'evasion': 0, 'critical': 10**12,
         'criticalResistance': 0, 'block': 10**12, 'blockPenetration': 0},
        {'accuracy': 0, 'evasion': 10**12, 'critical': 0,
         'criticalResistance': 10**12, 'block': 0, 'blockPenetration': 10**12},
    )
    equal, favorable, adverse = [valid_result(record) for record in records]
    assert equal == pytest.approx(BASE)
    for key in ('hit', 'critical', 'block'):
        assert favorable[key] > 99.99
        assert adverse[key] < 0.01


@pytest.mark.parametrize('field', tuple(DEFAULTS))
@pytest.mark.parametrize('value', [
    '', '   ', '-1', '-0', '-1e-400', '1e-400', 'NaN', 'Infinity', '-Infinity',
    '1e309', '1000000000001', '0x10', '1,000', 'abc', '2.3.4',
    '1' * 65, '0' * 64 + '1', None, True, [], {},
])
def test_invalid_input_is_rejected_without_any_result(field, value):
    record = calculations({field: value})[0]
    assert record['validation']['valid'] is False
    assert record['validation']['errors'] == {field: 'invalid'}
    assert record['calculation'] == {'valid': False, 'errors': {field: 'invalid'}, 'results': None}


@pytest.mark.parametrize('field', ['myLevel', 'opponentLevel'])
@pytest.mark.parametrize('value', ['500.5', '10001', '1e-3'])
def test_levels_require_integers_in_the_documented_range(field, value):
    record = calculations({field: value})[0]
    assert record['calculation']['valid'] is False
    assert record['calculation']['results'] is None
    assert record['calculation']['errors'] == {field: 'invalid'}


def test_decimal_exponent_whitespace_and_character_boundary_are_supported():
    for record in calculations({'accuracy': '  +2e4  ', 'myLevel': '5e2', 'block': '20000.0'},
                               {'accuracy': '0' * 63 + '0', 'evasion': '.5', 'critical': '1e-300'}):
        valid_result(record)
    assert valid_result(calculations({'accuracy': '  +2e4  '})[0]) == pytest.approx(BASE)
    incomplete = dict(DEFAULTS)
    del incomplete['block']
    response = node({'operation': 'calculate', 'cases': [None, {}, incomplete]})
    for record in response['results']:
        assert record['calculation']['valid'] is False
        assert record['calculation']['results'] is None
        assert 'block' in record['calculation']['errors']


@pytest.mark.parametrize('ready_state', ['loading', 'complete'])
def test_real_script_bootstrap_events_clear_errors_and_reset_all_fields(ready_state):
    response = node({'operation': 'dom', 'readyState': ready_state, 'actions': [
        {'event': 'input', 'values': {'critical': '25000'}},
        {'event': 'change', 'values': {'opponentLevel': '550'}},
        {'event': 'input', 'values': {'accuracy': '-1e-400'}},
        {'event': 'change', 'values': {'accuracy': '20000'}},
        {'event': 'submit', 'values': {'block': '0'}},
        {'event': 'input', 'values': {key: '' for key in DEFAULTS}},
        {'event': 'reset'},
    ]})
    assert response['waiting'] is (ready_state == 'loading')
    assert set(response['events']) == {'input', 'change', 'submit', 'reset'}
    initial, changed, boundary, invalid, repaired, submitted, empty, reset = response['snapshots']
    expected_display = {'hit': '90.00%', 'evasion': '10.00%', 'critical': '10.00%',
                        'block': '30.00%', 'levelFactor': '1.00 ×'}
    assert initial['results'] == expected_display
    assert changed['results']['critical'] == '14.79%'
    assert boundary['results'] == dict(changed['results'], hit='0.00%', evasion='100.00%',
                                      levelFactor='0.00 ×')
    assert invalid['values']['accuracy'] == '-1e-400'
    assert invalid['invalid']['accuracy'] == 'true'
    assert invalid['errors']['accuracy'] is True
    assert invalid['summaryVisible'] is True
    assert set(invalid['results'].values()) == {'—'}
    assert repaired['results'] == boundary['results']
    assert repaired['summaryVisible'] is False
    assert not any(repaired['errors'].values())
    assert submitted['prevented'] is True
    assert submitted['results']['block'] != repaired['results']['block']
    assert all(empty['errors'].values()) and empty['summaryVisible']
    assert set(empty['results'].values()) == {'—'}
    assert reset['prevented'] is True
    assert reset['values'] == {key: str(value) for key, value in DEFAULTS.items()}
    assert reset['results'] == expected_display
    assert set(reset['invalid'].values()) == {'false'}
    assert not any(reset['errors'].values()) and not reset['summaryVisible']
