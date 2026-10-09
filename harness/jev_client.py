"""Small Python 3.8 TypeSafe REST client; one bounded call, typed results only."""
import json
import math
import re
import socket
import urllib.error
import urllib.request

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
MAX_RESPONSE_BYTES = 65536
# Account only for binary-float representation at inclusive decimal endpoints.
FLOAT_COMPARISON_EPSILON = 1e-12


def safe_diagnostic(value):
    """Allow only local transport classifications and integer OS error codes."""
    if not isinstance(value, dict):
        return None
    error_type = value.get('error_type')
    if type(error_type) is not str or error_type not in (
            'gaierror', 'timeout', 'connection_error', 'network_error'):
        return None
    result = {'error_type': error_type}
    if type(value.get('errno')) is int:
        result['errno'] = value['errno']
    return result


def network_diagnostic(exc):
    # Inspect the reason's type, never its text, args, URL or headers.
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, socket.gaierror):
        error_type = 'gaierror'
    elif isinstance(reason, (TimeoutError, socket.timeout)):
        error_type = 'timeout'
    elif isinstance(reason, OSError):
        error_type = 'connection_error'
    else:
        error_type = 'network_error'
    return safe_diagnostic({'error_type': error_type, 'errno': getattr(reason, 'errno', None)})


class JevError(ValueError):
    def __init__(self, code, http_status=None, diagnostic=None):
        self.code = code
        self.http_status = http_status if type(http_status) is int else None
        self.diagnostic = safe_diagnostic(diagnostic)
        # Remote response bodies and authorization headers never become diagnostics.
        super().__init__(code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or \
            not low <= value <= high or not math.isfinite(value):
        raise JevError('invalid_response')
    return value


def validate_response(data, questions):
    if not isinstance(data, dict) or not isinstance(data.get('model'), str) or \
            not re.fullmatch(r'jev-[A-Za-z0-9._-]{1,60}', data['model']):
        raise JevError('invalid_response')
    answers = data.get('answers')
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise JevError('invalid_response')
    cleaned = {}
    for name, question in questions.items():
        answer = answers[name]
        kind = question['type']
        if not isinstance(answer, dict) or answer.get('type') != kind:
            raise JevError('invalid_response')
        result = {'type': kind}
        if kind == 'noul':
            result['noul'] = number(answer.get('noul'), 0, 1)
        else:
            options = (set(question['criteria']) if kind == 'choice'
                       else {str(i) for i in range(len(question['criteria']))})
            probabilities = answer.get('probabilities')
            if not isinstance(probabilities, dict) or set(probabilities) != options:
                raise JevError('invalid_response')
            probabilities = {key: number(value, 0, 1) for key, value in probabilities.items()}
            # The API rounds probabilities and scores independently to two
            # decimals. Bound that error without normalizing the original values
            # or letting relative tolerance expand the permitted discrepancy.
            probability_tolerance = max(0.001, len(options) * 0.005)
            # Compare inclusive endpoints so decimal boundary values such as a
            # sum of 1.01 are not rejected by subtraction's float roundoff.
            probability_sum = sum(probabilities.values())
            if not (1 - probability_tolerance - FLOAT_COMPARISON_EPSILON <= probability_sum <=
                    1 + probability_tolerance + FLOAT_COMPARISON_EPSILON):
                raise JevError('invalid_response')
            result.update(probabilities=probabilities, confidence=number(answer.get('confidence'), 0, 1))
            if kind == 'choice':
                choice = answer.get('choice')
                if not isinstance(choice, str) or choice not in options or \
                        probabilities[choice] < max(probabilities.values()):
                    raise JevError('invalid_response')
                result['choice'] = choice
            elif kind == 'score':
                score = number(answer.get('score'), 0, len(options) - 1)
                expected = sum(int(key) * value for key, value in probabilities.items())
                score_tolerance = max(0.001, 0.005 * (1 + sum(int(key) for key in options)))
                if not (expected - score_tolerance - FLOAT_COMPARISON_EPSILON <= score <=
                        expected + score_tolerance + FLOAT_COMPARISON_EPSILON):
                    raise JevError('invalid_response')
                if answer.get('legend') != {str(i): level for i, level in enumerate(question['criteria'])}:
                    raise JevError('invalid_response')
                result['score'] = score
            else:
                raise JevError('invalid_response')
        cleaned[name] = result
    usage = data.get('usage')
    if not isinstance(usage, dict):
        raise JevError('invalid_response')
    tokens = {}
    for name in ('input_tokens', 'output_tokens'):
        value = usage.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise JevError('invalid_response')
        tokens[name] = value
    return {'model': data['model'], 'answers': cleaned, 'usage': tokens}


def evaluate(state, questions, api_key, model, timeout=8, endpoint=ENDPOINT):
    if not api_key:
        raise JevError('missing_key')
    if not isinstance(api_key, str) or any(char in api_key for char in '\r\n\0'):
        raise JevError('invalid_key')
    if endpoint != ENDPOINT or not 0 < timeout <= 30:
        raise JevError('invalid_configuration')
    payload = json.dumps({'state': state, 'questions': questions, 'model': model},
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    request = urllib.request.Request(endpoint, data=payload, method='POST', headers={
        'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json',
        'Accept': 'application/json', 'User-Agent': 'TavernofSoul-triage/1',
    })
    try:
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
        if len(content) > MAX_RESPONSE_BYTES:
            raise JevError('response_too_large')
        return validate_response(json.loads(content.decode('utf-8')), questions)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise JevError('http_error', http_status=exc.code) from None
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        diagnostic = network_diagnostic(exc)
        code = 'timeout' if diagnostic['error_type'] == 'timeout' else 'network_error'
        raise JevError(code, diagnostic=diagnostic) from None
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, JevError):
            raise
        raise JevError('invalid_response') from None
    except OSError as exc:
        raise JevError('network_error', diagnostic=network_diagnostic(exc)) from None
