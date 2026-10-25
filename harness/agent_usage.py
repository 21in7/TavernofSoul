"""Numeric observations from final CLI envelopes, independent of billing policy.

Python 3.8 stdlib only. Never recurse into tool/stdout content looking for usage,
retain raw envelopes, or substitute estimates for missing observations.
"""
import json

MAX_TOKENS = 1000000000
MAX_OUTPUT_CHARS = 16777216
CODEX_FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')
CLAUDE_FIELDS = ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens')


def number(value):
    return value if type(value) is int and 0 <= value <= MAX_TOKENS else None


def prompt_size(prompt):
    result = {'characters': None, 'utf8_bytes': None}
    try:
        result = {'characters': len(prompt), 'utf8_bytes': len(prompt.encode('utf-8'))}
    except Exception:
        pass
    return result


def unavailable():
    return {'version': 'agent-usage-v1', 'status': 'unavailable', 'source': 'unknown',
            'input_tokens_semantics': 'unknown',
            **{field: None for field in dict.fromkeys(CODEX_FIELDS + CLAUDE_FIELDS)},
            'total_input_tokens': None, 'uncached_input_tokens': None, 'total_tokens': None}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate envelope field.')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Invalid JSON number.')


def _parse(text):
    return json.loads(text, object_pairs_hook=_unique, parse_constant=_invalid_constant)


def _final(provider, output, stream):
    if not isinstance(output, str) or len(output) > MAX_OUTPUT_CHARS:
        return None
    if provider == 'codex' or stream:
        events = [_parse(line) for line in output.splitlines() if line.strip()]
        if not events or any(not isinstance(event, dict) for event in events):
            return None
        if provider == 'codex':
            allowed = {'thread.started', 'turn.started', 'item.started', 'item.updated',
                       'item.completed', 'turn.completed'}
            finals = [event for event in events if event.get('type') == 'turn.completed']
            if (any(event.get('type') not in allowed for event in events) or
                    len(finals) != 1 or events[-1] is not finals[0]):
                return None
            return finals[0]
        allowed = {'system', 'assistant', 'user', 'result', 'rate_limit_event'}
        finals = [event for event in events if event.get('type') == 'result']
        substantive = [event for event in events if event.get('type') != 'rate_limit_event']
        if (any(event.get('type') not in allowed for event in events) or
                len(finals) != 1 or not substantive or substantive[-1] is not finals[0]):
            return None
        final = finals[0]
    else:
        final = _parse(output)
    if (not isinstance(final, dict) or final.get('type') != 'result' or
            final.get('subtype') != 'success' or final.get('is_error') is not False or
            not isinstance(final.get('result'), str) or not final['result'].strip()):
        return None
    return final


def _sum(*values):
    return number(sum(values)) if all(value is not None for value in values) else None


def observe(provider, output, *, stream=False):
    """Best effort only: missing/ambiguous/malformed evidence never fails a call."""
    result = unavailable()
    try:
        if provider not in ('codex', 'claude', 'zai'):
            return result
        final = _final(provider, output, stream)
        if final is None or not isinstance(final.get('usage'), dict):
            return result
        fields = CODEX_FIELDS if provider == 'codex' else CLAUDE_FIELDS
        result.update({field: number(final['usage'].get(field)) for field in fields})
        result['source'] = 'codex_turn_completed' if provider == 'codex' else 'claude_result'
        result['input_tokens_semantics'] = 'cache_inclusive' if provider == 'codex' else 'cache_exclusive'
        inp, out = result['input_tokens'], result['output_tokens']
        if provider == 'codex':
            cached, reasoning = result['cached_input_tokens'], result['reasoning_output_tokens']
            if inp is not None and cached is not None and cached > inp:
                result['cached_input_tokens'] = cached = None
            if out is not None and reasoning is not None and reasoning > out:
                result['reasoning_output_tokens'] = None
            result['total_input_tokens'] = inp
            if inp is not None and cached is not None:
                result['uncached_input_tokens'] = inp - cached
            required = CODEX_FIELDS[:3]
        else:
            result['total_input_tokens'] = _sum(inp, result['cache_read_input_tokens'],
                                                 result['cache_creation_input_tokens'])
            result['uncached_input_tokens'] = inp
            required = CLAUDE_FIELDS
        result['total_tokens'] = _sum(result['total_input_tokens'], out)
        if any(result[field] is not None for field in fields):
            result['status'] = 'available' if all(result[field] is not None for field in required) else 'partial'
        return result
    except Exception:
        return unavailable()
