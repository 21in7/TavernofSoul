"""Routing observations must preserve verification rules and never start agents."""
import copy
import errno
import io
import json
import socket
import urllib.error

import pytest

from harness import agent_models, jev_client, triage


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_models, 'KEY_FILE', tmp_path / '.agent-keys.json')
    monkeypatch.setattr(triage, 'REPORTS', tmp_path / 'reports')
    for name in agent_models.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(agent_models, 'run', lambda *a, **kw: pytest.fail('Triage started an agent'))
    monkeypatch.setattr(agent_models.subprocess, 'run',
                        lambda *a, **kw: pytest.fail('Triage started a subprocess'))
    evaluate = jev_client.evaluate
    monkeypatch.setattr(jev_client, 'evaluate',
                        lambda *a, **kw: pytest.fail('Unexpected live TypeSafe request'))
    return evaluate


@pytest.fixture
def response():
    return json.loads((triage.ROOT / 'harness/fixtures/triage/response.json').read_text(encoding='utf-8'))


def decide(response, paths=None):
    return triage.observe('다운로드 오류 메시지를 설명해 주세요.',
                          paths or ['downloader/downloader.py'], fixture=response)


@pytest.fixture
def rounded_response():
    questions = triage.load_policy()['questions']
    levels = questions['complexity']['criteria']
    # Keep the observed response local to this test module rather than depending
    # on an external response fixture's numbers or labels.
    return {
        'model': 'jev-1.13.0',
        'answers': {
            'domain': {
                'type': 'choice', 'choice': 'downloader', 'confidence': 1.0,
                'probabilities': {label: 1.0 if label == 'downloader' else 0.0
                                  for label in questions['domain']['criteria']},
            },
            'complexity': {
                'type': 'score', 'score': 0.07,
                'probabilities': {'0': 0.94, '1': 0.06, '2': 0.0}, 'confidence': 0.91,
                'legend': {str(i): level for i, level in enumerate(levels)},
            },
            'contract_impact': {'type': 'noul', 'noul': 0.0},
        },
        'usage': {'input_tokens': 500, 'output_tokens': 100},
    }


def test_observed_rounding_passes_without_changing_advisory_contract(rounded_response):
    original = copy.deepcopy(rounded_response)
    report = decide(rounded_response)
    assert report['status'] == 'passed' and report['source'] == 'fixture'
    assert report['answers']['complexity'] == {
        'type': 'score', 'score': 0.07,
        'probabilities': {'0': 0.94, '1': 0.06, '2': 0.0}, 'confidence': 0.91,
    }
    assert rounded_response == original and 'fallback_reason' not in report
    assert report['recommendation']['role'] == 'downloader'
    assert report['recommendation']['required_checks'] == ['check-downloader']
    assert report['recommendation']['execution_allowed'] is False
    assert not report['api_called'] and not report['agent_started']


@pytest.mark.parametrize('above', [False, True])
def test_rounding_uses_original_score_at_existing_routing_threshold(rounded_response, above):
    threshold = triage.load_policy()['thresholds']['direct_complexity_max']
    score = threshold + 0.01 if above else threshold
    expected = threshold if above else threshold + 0.01
    # Put the weighted average on the other side of the routing decision.
    if expected <= 1:
        probabilities = {'0': 1 - expected, '1': expected, '2': 0.0}
    else:
        probabilities = {'0': 0.0, '1': 2 - expected, '2': expected - 1}
    rounded_response['answers']['complexity'].update(score=score, probabilities=probabilities)
    report = decide(rounded_response)
    assert report['status'] == 'passed' and 'fallback_reason' not in report
    assert report['answers']['complexity']['score'] == score
    assert report['answers']['complexity']['probabilities'] == probabilities
    assert report['answers']['complexity']['confidence'] == 0.91
    assert report['recommendation']['role'] == ('coordinator' if above else 'downloader')
    assert report['recommendation']['required_checks'] == (['check'] if above else ['check-downloader'])
    assert ('implementation_planning_needed' in report['recommendation']['reasons']) is above
    assert report['recommendation']['execution_allowed'] is False


@pytest.mark.parametrize('question', ['domain', 'complexity'])
@pytest.mark.parametrize('below', [False, True])
def test_rounding_preserves_confidence_and_existing_confidence_thresholds(rounded_response, question, below):
    threshold = triage.load_policy()['thresholds'][question + '_confidence']
    confidence = threshold - 1e-6 if below else threshold
    rounded_response['answers'][question]['confidence'] = confidence
    report = decide(rounded_response)
    assert report['status'] == 'passed' and 'fallback_reason' not in report
    assert report['answers'][question]['confidence'] == confidence
    assert report['answers']['complexity']['score'] == 0.07
    assert report['answers']['complexity']['probabilities'] == {'0': 0.94, '1': 0.06, '2': 0.0}
    assert report['recommendation']['role'] == ('coordinator' if below else 'downloader')
    assert ('low_' + question + '_confidence' in report['recommendation']['reasons']) is below
    assert report['recommendation']['execution_allowed'] is False


@pytest.mark.parametrize('probabilities,score', [
    ({'0': 0.33, '1': 0.33, '2': 0.33}, 0.99),
    ({'0': 0.34, '1': 0.34, '2': 0.33}, 1.0),
])
def test_rounded_probability_sums_pass_and_remain_original_in_reports(rounded_response, probabilities, score):
    rounded_response['answers']['complexity'].update(probabilities=probabilities, score=score)
    report = decide(rounded_response)
    assert report['status'] == 'passed' and 'fallback_reason' not in report
    assert report['answers']['complexity']['probabilities'] == probabilities
    assert report['answers']['complexity']['score'] == score
    assert report['answers']['complexity']['confidence'] == 0.91
    assert report['recommendation']['execution_allowed'] is False


@pytest.mark.parametrize('probabilities,score', [
    ({'0': 0.924, '1': 0.06, '2': 0.0}, 0.07),  # Sum error 0.016 > 0.015.
    ({'0': 0.956, '1': 0.06, '2': 0.0}, 0.07),
    ({'0': 0.94, '1': 0.06, '2': 0.0}, 0.081),  # Score error 0.021 > 0.02.
    ({'0': 0.94, '1': 0.06, '2': 0.0}, 1.0),
])
def test_excess_rounding_error_keeps_invalid_response_fallback_contract(rounded_response, probabilities, score):
    rounded_response['answers']['complexity'].update(probabilities=probabilities, score=score)
    report = decide(rounded_response)
    assert report['status'] == 'fallback' and report['fallback_reason'] == 'invalid_response'
    assert report['recommendation']['role'] == 'coordinator'
    assert report['recommendation']['required_checks'] == ['check']
    assert report['recommendation']['reasons'] == ['invalid_response']
    assert report['recommendation']['execution_allowed'] is False
    assert not report['api_called'] and not report['agent_started']
    assert 'answers' not in report and 'diagnostic' not in report and 'http_status' not in report


@pytest.mark.parametrize('score,accepted', [(0.07, True), (0.081, False)])
def test_wire_rounding_validation_makes_one_request_and_preserves_fallback(
        rounded_response, isolated, monkeypatch, score, accepted):
    rounded_response['answers']['complexity']['score'] = score
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-typesafe-private')
    monkeypatch.setattr(jev_client, 'evaluate', isolated)
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            return io.BytesIO(json.dumps(rounded_response).encode('utf-8'))
    monkeypatch.setattr(jev_client.urllib.request, 'build_opener', lambda handler: Opener())
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: pytest.fail('Unexpected DNS probe'))
    report = triage.observe('다운로드를 설명해 주세요.', ['downloader/downloader.py'], live=True)
    assert len(calls) == 1 and report['source'] == 'api' and report['api_called']
    assert not report['agent_started'] and report['recommendation']['execution_allowed'] is False
    if accepted:
        assert report['status'] == 'passed' and 'fallback_reason' not in report
        assert report['answers']['complexity']['score'] == 0.07
        assert report['answers']['complexity']['probabilities'] == {'0': 0.94, '1': 0.06, '2': 0.0}
        assert report['answers']['complexity']['confidence'] == 0.91
        assert report['recommendation']['role'] == 'downloader'
        assert report['recommendation']['required_checks'] == ['check-downloader']
    else:
        assert report['status'] == 'fallback' and report['fallback_reason'] == 'invalid_response'
        assert report['recommendation']['role'] == 'coordinator'
        assert report['recommendation']['required_checks'] == ['check']
        assert 'answers' not in report
    assert 'test-typesafe-private' not in json.dumps(report)
    assert 'diagnostic' not in report and 'http_status' not in report


def test_offline_fixture_produces_advisory_role_and_records_comparison(response):
    report = triage.observe('다운로드 오류 메시지를 설명해 주세요.', ['downloader/downloader.py'],
                            fixture=response, expected_role='downloader')
    assert report['status'] == 'passed' and report['source'] == 'fixture'
    assert not report['agent_started'] and not report['api_called']
    assert report['comparison'] == {'expected_role': 'downloader', 'agrees': True}
    assert report['recommendation']['role'] == 'downloader'
    assert report['recommendation']['provider'] == 'zai'
    assert report['recommendation']['required_checks'] == ['check-downloader']
    assert report['recommendation']['execution_allowed'] is False
    assert len(report['state_sha256']) == len(report['policy_sha256']) == 64
    assert '다운로드 오류 메시지' not in json.dumps(report, ensure_ascii=False)


@pytest.mark.parametrize('path,expected', [
    ('downloader/unpacker_pak.py', 'check-downloader'),
    ('parser_tidy/monsters.py', 'check-parser'),
    ('TavernofSoul/Items/views.py', 'check-django'),
    ('Makefile', 'check'), ('harness', 'check'),
    ('TavernofSoul/ipfparser/contracts.py', 'check'),
    ('parser_tidy/DB.py', 'check'), ('cron_itos.sh', 'check'),
])
def test_mandatory_checks_follow_supplied_paths(path, expected):
    assert triage.path_rules([path])['required_checks'] == [expected]


@pytest.mark.parametrize('paths', [
    ['downloader/downloader.py', 'parser_tidy/monsters.py'],
    ['parser_tidy/DB.py'], ['TavernofSoul/ipfparser/contracts.py'],
    ['harness/runner.py'], ['docs/data-contracts.md'],
])
def test_jev_cannot_relax_cross_area_or_shared_contract_checks(response, paths):
    report = decide(response, paths)
    assert report['recommendation']['role'] == 'coordinator'
    assert report['recommendation']['required_checks'] == ['check']
    assert 'path_rules_require_planning' in report['recommendation']['reasons']


def test_jev_owner_disagreement_requires_planning(response):
    report = decide(response, ['parser_tidy/monsters.py'])
    assert report['recommendation']['role'] == 'coordinator'
    assert 'domain_disagrees_with_paths' in report['recommendation']['reasons']


@pytest.mark.parametrize('question,field,value,reason', [
    ('domain', 'confidence', 0.74, 'low_domain_confidence'),
    ('complexity', 'confidence', 0.69, 'low_complexity_confidence'),
    ('contract_impact', 'noul', 0.21, 'possible_contract_impact'),
    ('contract_impact', 'noul', 0.5, 'possible_contract_impact'),
])
def test_uncertain_answers_recommend_codex_planning(response, question, field, value, reason):
    response['answers'][question][field] = value
    report = decide(response)
    assert report['status'] == 'passed'
    assert report['recommendation']['role'] == 'coordinator'
    assert report['recommendation']['required_checks'] == ['check']
    assert reason in report['recommendation']['reasons']
    if question == 'contract_impact':
        assert report['recommendation']['review_required']


def test_high_fractional_complexity_requires_planning(response):
    response['answers']['complexity'].update(score=0.8, probabilities={'0': 0.2, '1': 0.8, '2': 0})
    report = decide(response)
    assert 'implementation_planning_needed' in report['recommendation']['reasons']


def test_model_cannot_remove_path_based_review(response):
    domain = response['answers']['domain']
    domain['choice'] = 'parser'
    domain['probabilities']['parser'], domain['probabilities']['downloader'] = 0.96, 0.01
    report = decide(response, ['parser_tidy/items.py'])
    assert report['recommendation']['role'] == 'parser'
    assert report['recommendation']['review_required'] is True


@pytest.mark.parametrize('files', [[], ['unknown/new.py']])
def test_no_established_file_scope_cannot_select_a_specialist(response, files):
    report = triage.observe('아직 파일 범위를 정하지 못했습니다.', files, fixture=response)
    assert report['recommendation']['role'] == 'coordinator'


@pytest.mark.parametrize('path', [
    '.agent-keys.json', '.git/config', '.codex/config.toml', 'ktos_unpack/item.ies',
    'ktos_patch/patch.ipf', 'IPFUnpacker/main.cpp', 'Translation/en.tsv',
    'TavernofSoul/JSON_itos/items.json', 'downloader/revision.csv',
])
def test_runtime_scope_never_contacts_jev(path, monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-typesafe-private')
    report = triage.observe('이 파일의 변경 작업을 판단해 주세요.', [path], live=True)
    assert report['fallback_reason'] == 'protected_runtime_scope'
    assert report['path_rules']['protected_paths'] == [path]
    assert not report['api_called'] and report['recommendation']['role'] == 'coordinator'


@pytest.mark.parametrize('path', ['../outside.py', '/etc/passwd', '.', '', 'a\nfile.py', 'a\\b.py'])
def test_invalid_scope_is_rejected_without_network(path):
    with pytest.raises(ValueError):
        triage.observe('판단해 주세요.', [path], live=True)


def test_path_normalization_deduplicates_without_reading_source_files():
    absolute = str(triage.ROOT / 'downloader/proposed_file.py')
    assert triage.scoped_paths([absolute, './downloader/proposed_file.py'], 128) == [
        'downloader/proposed_file.py']


def test_default_mode_is_rules_only_even_with_a_registered_key(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-typesafe-private')
    report = triage.observe('다운로드를 설명해 주세요.', ['downloader/downloader.py'])
    assert not report['api_called'] and report['source'] == 'rules_only'
    assert report['fallback_reason'] == 'live_not_requested'
    assert report['recommendation']['role'] == 'coordinator'


def test_missing_key_is_a_visible_fallback():
    report = triage.observe('다운로드를 설명해 주세요.', ['downloader/downloader.py'], live=True)
    assert report['status'] == 'fallback' and not report['api_called']
    assert report['fallback_reason'] == 'missing_typesafe_key'


@pytest.mark.parametrize('code,status', [('network_error', None), ('timeout', None), ('http_error', 429),
                                       ('http_error', 529), ('invalid_response', None)])
def test_live_api_failures_preserve_planning_and_do_not_start_agents(code, status, monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-typesafe-private')
    def fail(*args):
        raise jev_client.JevError(code, http_status=status)
    monkeypatch.setattr(jev_client, 'evaluate', fail)
    report = triage.observe('다운로드를 설명해 주세요.', ['downloader/downloader.py'], live=True)
    assert report['source'] == 'api' and report['api_called']
    assert report['status'] == 'fallback' and report['fallback_reason'] == code
    assert report['recommendation']['role'] == 'coordinator'
    assert report['recommendation']['required_checks'] == ['check']
    assert report['recommendation']['execution_allowed'] is False
    if status:
        assert report['http_status'] == status


@pytest.mark.parametrize('wrapped', [False, True])
@pytest.mark.parametrize('failure,code,diagnostic', [
    (socket.gaierror(-3, 'unregistered-secret remote response Authorization: Bearer test-typesafe-private'),
     'network_error', {'error_type': 'gaierror', 'errno': -3}),
    (socket.timeout('unregistered-secret test-typesafe-private'),
     'timeout', {'error_type': 'timeout'}),
    (ConnectionRefusedError(errno.ECONNREFUSED, 'unregistered-secret test-typesafe-private'),
     'network_error', {'error_type': 'connection_error', 'errno': errno.ECONNREFUSED}),
])
def test_transport_diagnostics_reach_reports_without_relaxing_fallback(
        failure, code, diagnostic, wrapped, isolated, monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-typesafe-private')
    monkeypatch.setattr(jev_client, 'evaluate', isolated)
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert request.full_url == jev_client.ENDPOINT
            if wrapped:
                raise urllib.error.URLError(failure)
            raise failure

    monkeypatch.setattr(jev_client.urllib.request, 'build_opener', lambda handler: Opener())
    monkeypatch.setattr(socket, 'getaddrinfo',
                        lambda *a, **kw: pytest.fail('Unexpected DNS probe'))
    report = triage.observe('다운로드를 설명해 주세요.', ['downloader/downloader.py'], live=True)
    assert len(calls) == 1 and report['api_called'] and not report['agent_started']
    assert report['source'] == 'api' and report['status'] == 'fallback'
    assert report['fallback_reason'] == code and report['diagnostic'] == diagnostic
    assert report['recommendation']['role'] == 'coordinator'
    assert report['recommendation']['required_checks'] == ['check']
    assert report['recommendation']['reasons'] == [code]
    assert report['recommendation']['execution_allowed'] is False
    serialized = json.dumps(report)
    for secret in ('test-typesafe-private', 'unregistered-secret', 'remote response', 'Authorization'):
        assert secret not in serialized


def test_http_transport_failure_preserves_status_and_discards_response(isolated, monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-typesafe-private')
    monkeypatch.setattr(jev_client, 'evaluate', isolated)
    body = io.BytesIO(b'unregistered-secret remote response test-typesafe-private')
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(jev_client.ENDPOINT, 429, 'unregistered-secret',
                                         {'Authorization': 'Bearer test-typesafe-private'}, body)

    monkeypatch.setattr(jev_client.urllib.request, 'build_opener', lambda handler: Opener())
    report = triage.observe('다운로드를 설명해 주세요.', ['downloader/downloader.py'], live=True)
    assert len(calls) == 1 and body.closed
    assert report['status'] == 'fallback' and report['fallback_reason'] == 'http_error'
    assert report['http_status'] == 429 and 'diagnostic' not in report
    assert report['recommendation']['role'] == 'coordinator'
    assert report['recommendation']['required_checks'] == ['check']
    assert report['recommendation']['execution_allowed'] is False
    serialized = json.dumps(report)
    for secret in ('test-typesafe-private', 'unregistered-secret', 'remote response', 'Authorization'):
        assert secret not in serialized


def test_report_filters_diagnostics_again_at_the_error_boundary(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-typesafe-private')

    def fail(*args):
        error = jev_client.JevError('network_error')
        error.diagnostic = {'error_type': 'gaierror', 'errno': -3,
                            'message': 'unregistered-secret',
                            'headers': {'Authorization': 'Bearer test-typesafe-private'}}
        error.http_status = 'unregistered-secret'
        raise error

    monkeypatch.setattr(jev_client, 'evaluate', fail)
    report = triage.observe('다운로드를 설명해 주세요.', ['downloader/downloader.py'], live=True)
    assert report['diagnostic'] == {'error_type': 'gaierror', 'errno': -3}
    assert 'http_status' not in report and 'unregistered-secret' not in json.dumps(report)
    assert report['recommendation']['role'] == 'coordinator'
    assert report['recommendation']['required_checks'] == ['check']
    assert report['recommendation']['execution_allowed'] is False


def test_registered_secrets_are_removed_from_request_state_and_reports(response, monkeypatch):
    keys = {'TYPESAFE_API_KEY': 'test-typesafe-private', 'ANTHROPIC_API_KEY': 'test-claude-private',
            'ZAI_API_KEY': 'test-zai-private'}
    for name, value in keys.items():
        monkeypatch.setenv(name, value)
    calls = []
    def evaluate(state, questions, key, model, timeout, endpoint):
        calls.append(state)
        assert key == keys['TYPESAFE_API_KEY']
        assert endpoint == jev_client.ENDPOINT and model == 'jev-1.13.0'
        assert all(value not in json.dumps(state) for value in keys.values())
        return jev_client.validate_response(response, questions)
    monkeypatch.setattr(jev_client, 'evaluate', evaluate)
    report = triage.observe(' '.join(keys.values()), ['downloader/downloader.py'], live=True)
    assert report['status'] == 'passed' and len(calls) == 1
    assert all(value not in json.dumps(report) for value in keys.values())


def test_invalid_fixture_is_a_failed_evaluation(response):
    response['answers']['complexity']['score'] = 100
    report = decide(response)
    assert report['status'] == 'fallback' and report['fallback_reason'] == 'invalid_response'
    assert report['recommendation']['role'] == 'coordinator'


def test_task_limits_do_not_silently_truncate_and_live_cannot_use_fixtures(response):
    for task in (' ', '가' * 8001):
        with pytest.raises(ValueError):
            triage.observe(task, [], fixture=response)
    with pytest.raises(ValueError):
        triage.observe('유효한 작업', [], live=True, fixture=response)


def test_policy_changes_are_detectable_and_invalid_scales_are_rejected(tmp_path, monkeypatch):
    policy = triage.load_policy()
    changed = copy.deepcopy(policy)
    changed['thresholds']['domain_confidence'] = 0.9
    assert triage.digest(policy) != triage.digest(changed)
    changed['questions']['complexity']['criteria'] = {'0': 'a', '1': 'b', '2': 'c'}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(changed), encoding='utf-8')
    monkeypatch.setattr(triage, 'CONFIG', path)
    with pytest.raises(ValueError, match='Invalid triage policy'):
        triage.load_policy()


def test_cli_writes_private_fixture_report_and_failed_live_probe_exits_nonzero(tmp_path, capsys):
    task = tmp_path / 'task.txt'
    task.write_text('다운로드 오류 메시지를 설명해 주세요.', encoding='utf-8')
    args = ['recommend', '--task-file', str(task), '--file', 'downloader/downloader.py']
    fixture = triage.ROOT / 'harness/fixtures/triage/response.json'
    assert triage.main(args + ['--fixture-response', str(fixture), '--expected-role', 'downloader']) == 0
    reports = list(triage.REPORTS.glob('*.json'))
    assert len(reports) == 1 and reports[0].stat().st_mode & 0o777 == 0o600
    assert json.loads(reports[0].read_text())['source'] == 'fixture'
    assert triage.main(args + ['--live']) == 1
    assert 'missing_typesafe_key' in capsys.readouterr().out
    assert triage.main(args) == 0  # A deliberate rules-only observation is supported.


def test_smoke_is_one_typed_probe_without_agent_execution(response, monkeypatch, capsys):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-typesafe-private')
    calls = []
    def evaluate(state, questions, *args):
        calls.append(state)
        return jev_client.validate_response(response, questions)
    monkeypatch.setattr(jev_client, 'evaluate', evaluate)
    assert triage.main(['smoke', '--live']) == 0
    assert len(calls) == 1
    assert '"agent_started": false' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        triage.main(['smoke'])
