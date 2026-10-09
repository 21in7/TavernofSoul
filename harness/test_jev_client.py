"""Exercise the TypeSafe wire protocol and failure boundaries without network."""
import copy
import errno
import io
import json
import socket
import urllib.error

import pytest

from harness import jev_client as client, triage


@pytest.fixture
def response():
    path = triage.ROOT / 'harness/fixtures/triage/response.json'
    return json.loads(path.read_text(encoding='utf-8'))


def questions():
    return triage.load_policy()['questions']


@pytest.fixture
def rounded_score_response():
    criteria = ['local explanation', 'implementation planning', 'cross-area redesign']
    question = {'complexity': {'type': 'score', 'criteria': criteria}}
    data = {
        'model': 'jev-1.13.0',
        'answers': {'complexity': {
            'type': 'score', 'score': 0.07,
            'probabilities': {'0': 0.94, '1': 0.06, '2': 0.0},
            'confidence': 0.91,
            'legend': {str(i): level for i, level in enumerate(criteria)},
        }},
        'usage': {'input_tokens': 500, 'output_tokens': 100},
    }
    return data, question


def test_independently_rounded_observed_score_preserves_original_numbers(rounded_score_response):
    data, question = rounded_score_response
    original = copy.deepcopy(data)
    result = client.validate_response(data, question)
    assert result['answers']['complexity'] == {
        'type': 'score', 'score': 0.07,
        'probabilities': {'0': 0.94, '1': 0.06, '2': 0.0}, 'confidence': 0.91,
    }
    assert data == original


@pytest.mark.parametrize('probabilities,score', [
    ({'0': 0.33, '1': 0.33, '2': 0.33}, 0.99),  # Sum 0.99 stays unnormalized.
    ({'0': 0.34, '1': 0.34, '2': 0.33}, 1.0),   # Sum 1.01 stays unnormalized.
])
def test_two_decimal_probability_sums_are_preserved(rounded_score_response, probabilities, score):
    data, question = rounded_score_response
    data['answers']['complexity'].update(probabilities=probabilities, score=score)
    result = client.validate_response(data, question)['answers']['complexity']
    assert result['probabilities'] == probabilities and result['score'] == score
    assert result['confidence'] == 0.91


@pytest.mark.parametrize('kind,count', [('choice', 2), ('choice', 5), ('score', 3), ('score', 4)])
@pytest.mark.parametrize('direction', [-1, 1])
@pytest.mark.parametrize('offset,accepted', [(-1e-10, True), (0.0, True), (1e-10, False)])
def test_probability_sum_rounding_limit_tracks_option_count(kind, count, direction, offset, accepted):
    levels = ['level {}'.format(i) for i in range(count)]
    criteria = {str(i): level for i, level in enumerate(levels)} if kind == 'choice' else levels
    probabilities = {str(i): 0.0 for i in range(count)}
    probabilities.update({'0': 0.5 + direction * (count * 0.005 + offset), '1': 0.5})
    answer = {'type': kind, 'probabilities': probabilities, 'confidence': 0.91}
    if kind == 'choice':
        answer['choice'] = '0' if direction > 0 else '1'
    else:
        answer.update(score=0.5, legend={str(i): level for i, level in enumerate(levels)})
    data = {'model': 'jev-1.13.0', 'answers': {'rounded': answer},
            'usage': {'input_tokens': 1, 'output_tokens': 1}}
    question = {'rounded': {'type': kind, 'criteria': criteria}}
    if accepted:
        result = client.validate_response(data, question)['answers']['rounded']
        assert result['probabilities'] == probabilities and result['confidence'] == 0.91
    else:
        with pytest.raises(client.JevError, match='^invalid_response$'):
            client.validate_response(data, question)


@pytest.mark.parametrize('count', [2, 3, 4])
@pytest.mark.parametrize('direction', [-1, 1])
@pytest.mark.parametrize('offset,accepted', [(-1e-10, True), (0.0, True), (1e-10, False)])
def test_score_rounding_limit_tracks_level_indices(count, direction, offset, accepted):
    levels = ['level {}'.format(i) for i in range(count)]
    probabilities = {str(i): 0.0 for i in range(count)}
    probabilities.update({'0': 0.5, '1': 0.5})
    tolerance = 0.005 * (1 + sum(range(count)))
    score = 0.5 + direction * (tolerance + offset)
    data = {'model': 'jev-1.13.0', 'answers': {'rounded': {
        'type': 'score', 'probabilities': probabilities, 'score': score, 'confidence': 0.91,
        'legend': {str(i): level for i, level in enumerate(levels)},
    }}, 'usage': {'input_tokens': 1, 'output_tokens': 1}}
    question = {'rounded': {'type': 'score', 'criteria': levels}}
    if accepted:
        result = client.validate_response(data, question)['answers']['rounded']
        assert result['score'] == score and result['probabilities'] == probabilities
    else:
        with pytest.raises(client.JevError, match='^invalid_response$'):
            client.validate_response(data, question)


@pytest.mark.parametrize('probability_zero', [0.485, 0.515])
def test_three_level_probability_sum_boundaries_are_inclusive(rounded_score_response, probability_zero):
    data, question = rounded_score_response
    answer = data['answers']['complexity']
    answer.update(probabilities={'0': probability_zero, '1': 0.5, '2': 0.0}, score=0.5)
    assert client.validate_response(data, question)['answers']['complexity']['probabilities'] == \
        answer['probabilities']  # Sums 0.985/1.015: the 0.015 limit.


@pytest.mark.parametrize('score', [0.04, 0.08])
def test_observed_score_rounding_boundaries_are_inclusive(rounded_score_response, score):
    data, question = rounded_score_response
    data['answers']['complexity']['score'] = score
    assert client.validate_response(data, question)['answers']['complexity']['score'] == score


def test_zero_expected_score_allows_the_absolute_boundary(rounded_score_response):
    data, question = rounded_score_response
    answer = data['answers']['complexity']
    answer.update(probabilities={'0': 1.0, '1': 0.0, '2': 0.0}, score=0.02)
    assert client.validate_response(data, question)['answers']['complexity']['score'] == 0.02


@pytest.mark.parametrize('field,value', [
    ('score', True), ('score', float('nan')), ('score', float('inf')),
    ('score', -0.01), ('score', 2.01), ('score', 1.0),
    ('probabilities', {'0': True, '1': 0.0, '2': 0.0}),
    ('probabilities', {'0': float('inf'), '1': 0.0, '2': 0.0}),
    ('probabilities', {'0': -0.001, '1': 1.0, '2': 0.0}),
    ('probabilities', {'0': 1.001, '1': 0.0, '2': 0.0}),
    ('probabilities', {'0': 0.94, '1': 0.06}),
    ('probabilities', {'0': 0.94, '1': 0.06, '2': 0.0, '3': 0.0}),
    ('confidence', float('nan')), ('confidence', float('inf')),
])
def test_rounding_does_not_relax_score_types_ranges_or_labels(rounded_score_response, field, value):
    data, question = rounded_score_response
    data['answers']['complexity'][field] = value
    with pytest.raises(client.JevError, match='^invalid_response$'):
        client.validate_response(data, question)


@pytest.mark.parametrize('change', ['different', 'missing', 'extra'])
def test_rounding_still_requires_the_exact_legend(rounded_score_response, change):
    data, question = rounded_score_response
    legend = data['answers']['complexity']['legend']
    if change == 'different':
        legend['1'] = 'different level'
    elif change == 'missing':
        del legend['2']
    else:
        legend['3'] = 'extra level'
    with pytest.raises(client.JevError, match='^invalid_response$'):
        client.validate_response(data, question)


@pytest.mark.parametrize('change', ['missing', 'extra', 'nonmaximum'])
def test_rounded_choice_still_requires_exact_labels_and_a_maximum_choice(change):
    probabilities = {'a': 0.49, 'b': 0.52}  # Rounded sum 1.01 is allowed for two options.
    if change == 'missing':
        del probabilities['a']
    elif change == 'extra':
        probabilities['c'] = 0.0
    data = {'model': 'jev-1.13.0', 'answers': {'domain': {
        'type': 'choice', 'choice': 'a' if change == 'nonmaximum' else 'b',
        'probabilities': probabilities, 'confidence': 0.91,
    }}, 'usage': {'input_tokens': 1, 'output_tokens': 1}}
    question = {'domain': {'type': 'choice', 'criteria': {'a': 'area a', 'b': 'area b'}}}
    with pytest.raises(client.JevError, match='^invalid_response$'):
        client.validate_response(data, question)


def test_fractional_score_and_noul_are_preserved(response):
    result = client.validate_response(response, questions())
    assert result['answers']['complexity']['score'] == 0.1
    assert result['answers']['contract_impact'] == {'type': 'noul', 'noul': 0.05}
    assert result['usage'] == {'input_tokens': 500, 'output_tokens': 100}


@pytest.mark.parametrize('path,value', [
    (('model',), 'jev-secret\nremote-diagnostic'),
    (('answers', 'domain', 'type'), 'score'),
    (('answers', 'domain', 'choice'), 'parser'),
    (('answers', 'domain', 'confidence'), True),
    (('answers', 'domain', 'confidence'), 10 ** 400),
    (('answers', 'domain', 'probabilities', 'downloader'), 0.8),
    (('answers', 'domain', 'probabilities', 'parser'), float('nan')),
    (('answers', 'complexity', 'score'), 1),
    (('answers', 'complexity', 'legend'), {'0': 'different scale'}),
    (('answers', 'complexity', 'confidence'), -0.01),
    (('answers', 'contract_impact', 'noul'), float('inf')),
    (('answers', 'contract_impact', 'noul'), 'false'),
    (('usage', 'input_tokens'), False),
    (('usage', 'output_tokens'), -1),
])
def test_unusable_typed_results_are_rejected(response, path, value):
    data = copy.deepcopy(response)
    parent = data
    for name in path[:-1]:
        parent = parent[name]
    parent[path[-1]] = value
    with pytest.raises(client.JevError, match='^invalid_response$'):
        client.validate_response(data, questions())


def test_missing_and_extra_question_results_are_rejected(response):
    del response['answers']['contract_impact']
    with pytest.raises(client.JevError):
        client.validate_response(response, questions())
    response['answers']['unexpected'] = {'type': 'noul', 'noul': 0}
    with pytest.raises(client.JevError):
        client.validate_response(response, questions())


def test_only_typed_results_are_kept(response):
    response['diagnostic'] = 'untrusted text'
    response['answers']['domain']['explanation'] = 'untrusted text'
    response['usage']['untrusted'] = 'untrusted text'
    assert 'untrusted text' not in json.dumps(client.validate_response(response, questions()))


def test_actual_request_encodes_korean_and_uses_bearer_without_retries(response, monkeypatch):
    calls = []
    state = {'task': '다운로드 실패를 조사해 주세요', 'scoped_files': ['downloader/downloader.py']}

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert request.full_url == client.ENDPOINT
            assert request.get_method() == 'POST'
            assert request.get_header('Authorization') == 'Bearer test-typesafe-private'
            assert request.get_header('Content-type') == 'application/json'
            assert timeout == 8
            assert json.loads(request.data.decode('utf-8')) == {
                'state': state, 'model': 'jev-1.13.0', 'questions': questions()}
            return io.BytesIO(json.dumps(response).encode('utf-8'))

    def build(handler):
        assert isinstance(handler, client.NoRedirect)
        return Opener()

    monkeypatch.setattr(client.urllib.request, 'build_opener', build)
    result = client.evaluate(state, questions(), 'test-typesafe-private', 'jev-1.13.0')
    assert result['model'] == 'jev-1.13.0' and len(calls) == 1


@pytest.mark.parametrize('status', [301, 401, 422, 429, 529])
def test_http_failures_do_not_retry_or_expose_remote_bodies(status, monkeypatch):
    calls = []
    body = io.BytesIO(b'test-typesafe-private remote diagnostic')

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(client.ENDPOINT, status, 'untrusted message', {}, body)

    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda handler: Opener())
    with pytest.raises(client.JevError) as error:
        client.evaluate({}, questions(), 'test-typesafe-private', 'jev-1.13.0')
    assert error.value.code == 'http_error' and error.value.http_status == status
    assert str(error.value) == 'http_error' and body.closed and len(calls) == 1
    assert error.value.diagnostic is None
    serialized = json.dumps(vars(error.value))
    assert 'test-typesafe-private' not in serialized and 'untrusted message' not in serialized


@pytest.mark.parametrize('failure,expected,diagnostic', [
    (socket.gaierror(-3, 'private diagnostic'), 'network_error',
     {'error_type': 'gaierror', 'errno': -3}),
    (urllib.error.URLError(socket.gaierror(-3, 'private diagnostic')), 'network_error',
     {'error_type': 'gaierror', 'errno': -3}),
    (socket.timeout('private diagnostic'), 'timeout', {'error_type': 'timeout'}),
    (urllib.error.URLError(socket.timeout('private diagnostic')), 'timeout',
     {'error_type': 'timeout'}),
    (TimeoutError(errno.ETIMEDOUT, 'private diagnostic'), 'timeout',
     {'error_type': 'timeout', 'errno': errno.ETIMEDOUT}),
    (ConnectionRefusedError(errno.ECONNREFUSED, 'private diagnostic'), 'network_error',
     {'error_type': 'connection_error', 'errno': errno.ECONNREFUSED}),
    (urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, 'private diagnostic')),
     'network_error', {'error_type': 'connection_error', 'errno': errno.ECONNREFUSED}),
    (OSError(errno.ENETUNREACH, 'private diagnostic'), 'network_error',
     {'error_type': 'connection_error', 'errno': errno.ENETUNREACH}),
    (urllib.error.URLError('private diagnostic gaierror(-3)'), 'network_error',
     {'error_type': 'network_error'}),
    (OSError('private diagnostic'), 'network_error', {'error_type': 'connection_error'}),
])
def test_network_failures_have_sanitized_codes(failure, expected, diagnostic, monkeypatch):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert request.full_url == client.ENDPOINT and timeout == 8
            raise failure
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda handler: Opener())
    monkeypatch.setattr(client.socket, 'getaddrinfo',
                        lambda *a, **kw: pytest.fail('Unexpected DNS probe'))
    with pytest.raises(client.JevError, match='^' + expected + '$') as error:
        client.evaluate({}, questions(), 'test-key', 'jev-1.13.0')
    assert error.value.diagnostic == diagnostic and len(calls) == 1
    assert error.value.__cause__ is None and error.value.__suppress_context__
    serialized = json.dumps(vars(error.value))
    assert 'private diagnostic' not in serialized and 'test-key' not in serialized


@pytest.mark.parametrize('value,expected', [
    (None, None),
    ('private diagnostic', None),
    ({'error_type': 'untrusted remote response', 'errno': -3}, None),
    ({'error_type': 'gaierror', 'errno': 'test-key'}, {'error_type': 'gaierror'}),
    ({'error_type': 'timeout', 'errno': True}, {'error_type': 'timeout'}),
    ({'error_type': 'connection_error', 'errno': 1.5}, {'error_type': 'connection_error'}),
    ({'error_type': 'gaierror', 'errno': -3, 'message': 'remote response',
      'headers': {'Authorization': 'Bearer test-key'}, 'body': 'test-key'},
     {'error_type': 'gaierror', 'errno': -3}),
])
def test_diagnostics_only_keep_allowlisted_types_and_integer_codes(value, expected):
    error = client.JevError('network_error', diagnostic=value)
    assert error.diagnostic == expected
    if isinstance(value, dict):
        assert error.diagnostic is not value
    assert str(error) == 'network_error'


@pytest.mark.parametrize('status', ['test-key remote response', True, 429.0])
def test_http_status_diagnostics_require_an_integer(status):
    assert client.JevError('http_error', http_status=status).http_status is None


@pytest.mark.parametrize('content,expected', [
    (b'not-json private diagnostic', 'invalid_response'),
    (b'\xff', 'invalid_response'),
    (b'{}', 'invalid_response'),
    (b'x' * (client.MAX_RESPONSE_BYTES + 1), 'response_too_large'),
])
def test_response_is_bounded_and_must_be_valid_utf8_json(content, expected, monkeypatch):
    class Body(io.BytesIO):
        def read(self, size):
            assert size == client.MAX_RESPONSE_BYTES + 1
            return super().read(size)
    class Opener:
        def open(self, *args, **kwargs):
            return Body(content)
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda handler: Opener())
    with pytest.raises(client.JevError, match='^' + expected + '$'):
        client.evaluate({}, questions(), 'test-key', 'jev-1.13.0')


def test_redirects_are_not_followed():
    assert client.NoRedirect().redirect_request(None, None, 302, '', {},
                                               'https://other.example') is None


@pytest.mark.parametrize('key,endpoint', [
    ('', client.ENDPOINT), ('key\nheader', client.ENDPOINT),
    ('key\0suffix', client.ENDPOINT), ('key', 'https://other.example'),
])
def test_missing_credentials_and_changed_endpoint_never_open_network(key, endpoint, monkeypatch):
    monkeypatch.setattr(client.urllib.request, 'build_opener',
                        lambda *a: pytest.fail('Invalid configuration reached network'))
    with pytest.raises(client.JevError):
        client.evaluate({}, questions(), key, 'jev-1.13.0', endpoint=endpoint)
