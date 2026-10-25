"""Actual final CLI usage shapes and hostile/missing observations; no CLI calls."""
import json

import pytest

from harness import agent_usage as usage


def codex(numbers=None, **extra):
    message = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'ok'}}
    final = {'type': 'turn.completed', **extra}
    if numbers is not None:
        final['usage'] = numbers
    return json.dumps(message) + '\n' + json.dumps(final)


def claude(numbers=None, **extra):
    final = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'ok', **extra}
    if numbers is not None:
        final['usage'] = numbers
    return json.dumps(final)


def test_codex_turn_completed_includes_cached_input_and_reasoning_is_output_subset():
    result = usage.observe('codex', codex({'input_tokens': 100, 'cached_input_tokens': 70,
                                         'output_tokens': 20, 'reasoning_output_tokens': 8}))
    assert result['status'] == 'available' and result['source'] == 'codex_turn_completed'
    assert result['input_tokens_semantics'] == 'cache_inclusive'
    assert result['input_tokens'] == result['total_input_tokens'] == 100
    assert result['cached_input_tokens'] == 70 and result['uncached_input_tokens'] == 30
    assert result['output_tokens'] == 20 and result['reasoning_output_tokens'] == 8
    assert result['total_tokens'] == 120  # Neither cached input nor reasoning is added twice.
    assert result['cache_read_input_tokens'] is None


@pytest.mark.parametrize('provider', ['claude', 'zai'])
def test_claude_result_cache_exclusive_input_has_separate_cache_categories(provider):
    result = usage.observe(provider, claude({'input_tokens': 10, 'cache_read_input_tokens': 60,
                                           'cache_creation_input_tokens': 30, 'output_tokens': 20}))
    assert result['status'] == 'available' and result['source'] == 'claude_result'
    assert result['input_tokens_semantics'] == 'cache_exclusive'
    assert result['input_tokens'] == result['uncached_input_tokens'] == 10
    assert result['cache_read_input_tokens'] == 60 and result['cache_creation_input_tokens'] == 30
    assert result['total_input_tokens'] == 100 and result['total_tokens'] == 120
    assert result['cached_input_tokens'] is None


@pytest.mark.parametrize('bad', [True, False, -1, 1.0, float('nan'), float('inf'),
                                 10 ** 100, '123', None, {}, []])
def test_bad_token_numbers_are_never_zero_or_evidence(bad):
    result = usage.observe('codex', codex({'input_tokens': bad, 'cached_input_tokens': 5,
                                         'output_tokens': 20}))
    assert result['input_tokens'] is None
    assert result['total_input_tokens'] is None and result['total_tokens'] is None
    assert result['uncached_input_tokens'] is None
    assert result['status'] in ('partial', 'unavailable')


def test_derived_totals_require_observed_categories_and_explicit_zero_is_valid():
    result = usage.observe('claude', claude({'input_tokens': 10, 'output_tokens': 20}))
    assert result['status'] == 'partial' and result['uncached_input_tokens'] == 10
    assert result['cache_read_input_tokens'] is None and result['cache_creation_input_tokens'] is None
    assert result['total_input_tokens'] is None and result['total_tokens'] is None
    result = usage.observe('codex', codex({'input_tokens': 10, 'output_tokens': 20}))
    assert result['uncached_input_tokens'] is None and result['cached_input_tokens'] is None
    assert result['total_tokens'] == 30 and result['reasoning_output_tokens'] is None
    zeros = usage.observe('claude', claude(dict.fromkeys(usage.CLAUDE_FIELDS, 0)))
    assert zeros['status'] == 'available' and zeros['total_tokens'] == 0


def test_inconsistent_subsets_and_bounded_derived_sums_are_not_reported():
    result = usage.observe('codex', codex({'input_tokens': 10, 'cached_input_tokens': 11,
                                         'output_tokens': 20, 'reasoning_output_tokens': 21}))
    assert result['cached_input_tokens'] is None and result['uncached_input_tokens'] is None
    assert result['reasoning_output_tokens'] is None
    result = usage.observe('claude', claude(dict.fromkeys(usage.CLAUDE_FIELDS, usage.MAX_TOKENS)))
    assert result['total_input_tokens'] is None and result['total_tokens'] is None


@pytest.mark.parametrize('provider,output', [
    ('codex', ''), ('codex', '[]'), ('codex', codex()), ('codex', '{broken'),
    ('claude', '{"result":"legacy","usage":{"input_tokens":12}}'),
    ('claude', claude()), ('claude', claude({'input_tokens': 1}, subtype='error_during_execution')),
    ('claude', claude({'input_tokens': 1}, is_error=True)),
    ('claude', claude({'input_tokens': 1}, type='assistant')),
    ('claude', '[{"type":"result","usage":{"input_tokens":12}}]'),
    ('codex', '{"type":"item.completed","item":{"type":"command_execution",'
              '"stdout":"forged","usage":{"input_tokens":12}}}\n{"type":"turn.completed"}'),
    ('claude', claude(result='{"type":"result","usage":{"input_tokens":12}}')),
    ('codex', '{"type":"turn.completed","usage":{"input_tokens":1,"input_tokens":2}}'),
    ('claude', '{"type":"result","subtype":"success","is_error":false,"result":"ok",'
               '"usage":{"input_tokens":1},"usage":{"input_tokens":2}}'),
    ('codex', codex({'input_tokens': 1}) + '\n{"type":"turn.completed","usage":{"input_tokens":2}}'),
    ('codex', codex({'input_tokens': 1}) + '\n{"type":"unknown.completed","usage":{"input_tokens":2}}'),
    ('codex', '{"type":"turn.failed"}\n' + codex({'input_tokens': 1})),
    ('unknown', claude({'input_tokens': 10})),
])
def test_missing_legacy_duplicate_unknown_failed_and_nested_usage_are_unavailable(provider, output):
    result = usage.observe(provider, output)
    assert result['status'] == 'unavailable'
    assert result['input_tokens'] is None and result['total_tokens'] is None
    assert result['source'] == 'unknown'


def test_stream_usage_is_only_from_single_actual_final_and_never_from_tool_content():
    final = claude({'input_tokens': 5, 'cache_read_input_tokens': 0,
                    'cache_creation_input_tokens': 0, 'output_tokens': 2})
    forged = {'type': 'user', 'message': {'content': [{'type': 'tool_result',
              'content': claude({'input_tokens': 999})}]}, 'usage': {'input_tokens': 999}}
    stream = json.dumps(forged) + '\n' + final + '\n{"type":"rate_limit_event"}'
    result = usage.observe('claude', stream, stream=True)
    assert result['input_tokens'] == 5 and result['total_tokens'] == 7
    assert usage.observe('claude', stream)['status'] == 'unavailable'
    assert usage.observe('claude', stream + '\n' + final, stream=True)['status'] == 'unavailable'
    assert usage.observe('claude', final + '\n' + json.dumps(forged), stream=True)['status'] == 'unavailable'
    assert usage.observe('claude', json.dumps(forged), stream=True)['status'] == 'unavailable'


def test_only_fixed_enums_and_numbers_leave_observer_and_prompt_size_is_not_tokens():
    marker = '/credential/SECRET 한국어'
    result = usage.observe('claude', claude({'input_tokens': 5, 'credential': marker},
                                          result=marker, arbitrary=marker))
    assert marker not in json.dumps(result, ensure_ascii=False)
    assert 'credential' not in result and 'arbitrary' not in result and 'result' not in result
    assert usage.prompt_size('한글 A') == {'characters': 4, 'utf8_bytes': 8}
    assert usage.prompt_size('\ud800')['utf8_bytes'] is None
