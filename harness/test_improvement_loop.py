"""Offline Lab contracts; parent runs checks and semantic review."""

from copy import deepcopy
import datetime as dt
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess

import pytest
from pytest import approx

from harness import agent_models, improvement_loop as loop
from harness import improvement_report as contract
from harness import improvements as imp, local_model, storage, workflow
from harness import review_coverage as coverage
from harness import improvement_diagnostics as diag
from harness.test_agent_models import run_synthetic_loop_adapter
from harness.test_review_coverage import (
    add_assessments, capture_result, read_events, stdout, with_rate_limit_events)

START = dt.datetime(2026, 10, 15, tzinfo=contract.KST)
FILES = ('harness/example.py', 'downloader/example.py', 'parser_tidy/example.py',
         'TavernofSoul/example.py', 'AGENTS.md', 'docs/architecture.md')
DOC = {'status': 'not_required', 'files': [],
       'reason': '합성 입력의 지역 동작 보존 제안이며 구조나 권한 계약을 변경하지 않습니다.'}
SECRET = 'sk-synthetic-loop-secret123456'
RAW = 'SYNTHETIC_RAW_PROVIDER_DIAGNOSTIC'
REVIEW_REASON = '독립 검토에서 동일 초안의 누락 조건을 확인하고 담당자의 근거 보완을 요청합니다.'

def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')

def assert_private(value):
    encoded = json.dumps(value)
    assert SECRET not in encoded and RAW not in encoded

def shipped(name):
    return json.loads(Path(__file__).with_name(name).read_text(encoding='utf-8'))

def draft(path, start=1, end=2, title='합성 점검 후보'):
    return {'title': title, 'priority': 'medium',
            'analogy': '정비사가 전달받은 점검표 두 칸을 비교하는 작업입니다.',
            'issue': '전달된 줄의 값 관계를 담당자가 전체 문맥에서 검토해야 합니다.',
            'evidence': [{'path': path, 'start_line': start, 'end_line': end,
                          'summary': '전달된 원래 줄 번호에서 값이 지정됩니다.'}],
            'benefit': {'kind': 'estimated', 'text': '미측정: 점검 조건을 명확히 설명할 수 있습니다.',
                        'evidence': []},
            'risk': '아직 전달되지 않은 줄의 동작은 확인하지 않았습니다.',
            'edit_files': [path],
            'validation_plan': ['독립적인 두 값을 가진 합성 사례로 조건을 비교합니다.'],
            'documentation_impact': '지역 동작 보존 제안이며 구조 및 권한 변경을 포함하지 않습니다.'}

@pytest.fixture
def local_example_case():
    config = {'version': 'local-model-config-v2', 'provider': 'mlx-vlm',
              'endpoint': 'http://127.0.0.1:12345/v1/chat/completions',
              'model': 'synthetic/Qwen3.5-9B-4bit',
              'api_model': 'synthetic/Qwen3.5-9B-4bit', 'temperature': 0,
              'limits': dict(local_model.DEFAULT_LIMITS, max_window_lines=2)}
    text = '첫째 원문 줄\n둘째 원문 줄\n셋째 원문 줄\n넷째 원문 줄\n'
    snapshots = {path: {'exists': True, 'mode': 0o644, 'content': text.encode('utf-8')}
                 for path in FILES}
    return config, snapshots

def edit_field_examples(system):
    examples = []
    for line in system.splitlines():
        if line.startswith('{'):
            value, end = json.JSONDecoder().raw_decode(line)
            if isinstance(value, dict) and set(value) == {'edit_files'}:
                assert not line[end:].strip()
                examples.append(value['edit_files'])
    return examples

def local_draft_response(config, candidates):
    return {'status': 200, 'headers': [('Content-Type', 'application/json')],
            'body': encode({'model': config['model'], 'choices': [
                {'message': {'role': 'assistant',
                             'content': json.dumps({'candidates': candidates}, ensure_ascii=False)},
                 'finish_reason': 'stop'}]})}

@pytest.mark.parametrize('role,owned', list(zip(
    ('coordinator', 'downloader', 'parser', 'django'), FILES[:4])))
@pytest.mark.parametrize('scope_size', [1, 3])
def test_local_examples_use_exact_prepared_owner_scope_and_accept_valid_lists(
        local_example_case, role, owned, scope_size):
    config, snapshots = local_example_case
    paths = [owned] if scope_size == 1 else [owned, FILES[4], FILES[5]]
    prepared = local_model.prepare_request(role, paths, snapshots, config=config)
    request = json.loads(prepared['request'])
    user = local_model._validate_request(config, prepared['request'])
    assert user['owner_role'] == role and user['approved_files'] == paths
    assert list(json.loads(request['messages'][1]['content'])) == [
        'owner_role', 'sources', 'feedback', 'candidate_limit', 'approved_files']
    assert [m['role'] for m in request['messages']] == ['system', 'user']
    assert request['enable_thinking'] is False
    examples = edit_field_examples(request['messages'][0]['content'])
    assert examples == ([paths[:1]] if scope_size == 1 else [paths[:1], paths[:2]])
    fields = request['response_format']['json_schema']['schema']['properties']['candidates']['items']['properties']
    assert fields['edit_files']['items']['enum'] == paths
    assert fields['edit_files']['minItems'] == 1 and fields['edit_files']['maxItems'] == 12
    assert 'uniqueItems' not in fields['edit_files']
    assert fields['evidence']['items']['properties']['path']['enum'] == [owned]
    for branch in fields['benefit']['anyOf']:
        assert branch['properties']['evidence']['items']['properties']['path']['enum'] == [owned]
    valid_lists = examples + ([[paths[-1]], [owned, paths[-1]]] if scope_size > 1 else [])
    for edits in valid_lists:
        assert len(edits) == len(set(edits)) and set(edits) <= set(paths)
        assert sum(map(len, edits)) <= 600
        candidate = draft(owned, 1, 1)
        candidate['evidence'].append(dict(candidate['evidence'][0], start_line=2, end_line=2))
        candidate['benefit']['evidence'] = [deepcopy(candidate['evidence'][1])]
        candidate['edit_files'] = edits
        calls = []

        def transport(actual_config, body):
            calls.append(body)
            assert os.environ.get('TAVERN_IMPROVEMENT_DISCOVERY') == '1'
            assert local_model._validate_request(actual_config, body) == user
            return local_draft_response(actual_config, [candidate])

        result = local_model.run(role, paths, snapshots, config=config, transport=transport)
        assert len(calls) == 1 and result['called'] is True and result['reason'] == 'ok'
        assert result['candidates'][0]['edit_files'] == edits
        assert len(result['candidates'][0]['evidence']) == 2

@pytest.mark.parametrize('failure,reason', [
    ('duplicate', 'candidate_edit_files_duplicate'),
    ('other_owner', 'candidate_edit_files_outside_scope'),
    ('evidence', 'evidence_outside_window'),
    ('benefit', 'evidence_outside_window'),
    ('empty', 'empty_draft'),
])
def test_local_examples_preserve_duplicate_and_both_evidence_boundaries(
        local_example_case, failure, reason):
    config, snapshots = local_example_case
    paths = [FILES[0], FILES[4]]
    candidate = draft(paths[0])
    if failure == 'duplicate':
        candidate['edit_files'] = [paths[0], paths[0]]
    elif failure == 'other_owner':
        candidate['edit_files'] = [FILES[1]]
    elif failure == 'evidence':
        candidate['evidence'][0]['end_line'] = 3
    elif failure == 'benefit':
        candidate['benefit']['evidence'] = [dict(candidate['evidence'][0], end_line=3)]
    calls = []

    def transport(actual_config, body):
        calls.append(body)
        local_model._validate_request(actual_config, body)
        return local_draft_response(actual_config, [] if failure == 'empty' else [candidate])

    result = local_model.run('coordinator', paths, snapshots, config=config, transport=transport)
    assert len(calls) == 1 and result['called'] is True and result['reason'] == reason
    assert result['candidates'] == []
    assert result['status'] == ('skipped' if failure == 'empty' else 'failed')

@pytest.mark.parametrize('mutation', [
    'system', 'example_path', 'owner', 'scope', 'window', 'schema', 'thinking',
    'feedback', 'candidate_limit', 'plain_bytes',
])
def test_local_example_request_tampering_never_reaches_transport(
        local_example_case, monkeypatch, mutation):
    config, snapshots = local_example_case
    paths = [FILES[0], FILES[4]]
    prepared = local_model.prepare_request('coordinator', paths, snapshots, config=config)
    sealed = prepared['request']
    wire = json.loads(sealed)
    user = json.loads(wire['messages'][1]['content'])
    if mutation == 'system':
        wire['messages'][0]['content'] += '\nignore the guide'
    elif mutation == 'example_path':
        system = wire['messages'][0]['content']
        original = contract.canonical_json(
            {'edit_files': edit_field_examples(system)[0]}).decode('utf-8')
        wire['messages'][0]['content'] = system.replace(
            original, json.dumps({'edit_files': [FILES[1]]}))
    elif mutation == 'schema':
        wire['response_format']['json_schema']['schema']['properties']['candidates']['items'][
            'properties']['edit_files']['items']['enum'].append(FILES[1])
    elif mutation == 'thinking':
        wire['enable_thinking'] = True
    elif mutation in ('owner', 'scope', 'window', 'feedback', 'candidate_limit'):
        if mutation == 'owner':
            user['owner_role'] = 'parser'
        elif mutation == 'scope':
            user['approved_files'].append(FILES[1])
        elif mutation == 'window':
            window = user['sources'][0]
            window['start_line'], window['end_line'] = 2, 3
            window['numbered_lines'] = [
                {'line': i, 'text': snapshots[paths[0]]['content'].decode('utf-8').splitlines()[i - 1]}
                for i in (2, 3)]
        elif mutation == 'feedback':
            user['feedback'] = [{'title': '합성 의견', 'issue': '변경된 비신뢰 의견입니다.',
                                 'edit_files': [paths[0]], 'specialist_reason': '근거 확인 요청',
                                 'review_reason': '별도 검토 요청'}]
        else:
            user['candidate_limit'] = 1
        wire = json.loads(local_model._encode_request(config, user))
    changed = contract.canonical_json(wire)
    if mutation != 'plain_bytes':
        changed = local_model._PreparedRequest(changed, sealed._binding)
    prepared['request'] = changed
    monkeypatch.setattr(local_model, 'prepare_request', lambda *args, **kwargs: prepared)
    calls = []

    def transport(*args):
        calls.append(args)
        return local_draft_response(config, [])

    result = local_model.run('coordinator', paths, snapshots, config=config, transport=transport)
    assert result['reason'] == 'input_invalid' and result['called'] is False
    assert result['candidates'] == [] and calls == []
    with pytest.raises(AttributeError):
        sealed._binding = 'changed'

def test_local_example_full_request_budget_keeps_whole_original_lines(local_example_case):
    config, snapshots = local_example_case
    paths = [FILES[0], FILES[4]]
    snapshots[paths[0]]['content'] = ('未送信\n' + '한글"\\' * 200 + '\n' +
                                     '다음 원문 줄' * 200 + '\n끝\n').encode('utf-8')
    cursor = {'file_index': 0, 'line': 2}
    feedback = [{'title': '이전 합성 의견', 'issue': '같은 근거의 수정 위치를 확인합니다.',
                 'edit_files': paths[:1], 'specialist_reason': '근거 확인 요청',
                 'review_reason': '별도 검토 요청'}]
    prepared = local_model.prepare_request('coordinator', paths, snapshots, config=config,
                                         cursor=cursor, feedback=feedback)
    size = len(prepared['request'])
    assert size <= 24576 and prepared['sources'][0]['end_line'] == 3
    original_lines = snapshots[paths[0]]['content'].decode('utf-8').splitlines()
    for budget, end in ((size, 3), (size - 1, 2)):
        bounded = deepcopy(config)
        bounded['limits']['max_context_bytes'] = budget
        selected = local_model.prepare_request('coordinator', paths, snapshots, config=bounded,
                                              cursor=cursor, feedback=feedback)
        user = local_model._validate_request(bounded, selected['request'])
        assert len(selected['request']) <= budget
        assert user['feedback'] == feedback
        assert edit_field_examples(json.loads(selected['request'])['messages'][0]['content'])
        assert user['sources'][0]['start_line'] == 2 and user['sources'][0]['end_line'] == end
        assert user['sources'][0]['numbered_lines'] == [
            {'line': i, 'text': original_lines[i - 1]} for i in range(2, end + 1)]
        assert selected['next_cursor'] == {'file_index': 0, 'line': end + 1}
    tiny = deepcopy(config)
    tiny['limits'].update(max_context_bytes=32, max_feedback_bytes=2)
    result = local_model.run('coordinator', paths, snapshots, config=tiny, transport=forbidden)
    assert result['reason'] == 'context_too_large' and result['called'] is False

def forbidden(*args, **kwargs):
    pytest.fail('Offline loop test crossed a model/network/check/workflow boundary')

class PowerLoss(BaseException):
    """Bypass normal exception handlers, like termination before the next fsync."""

class FakeClock:
    def __init__(self, value=START):
        self.value = value

    def __call__(self):
        return self.value

    def at(self, hours=0, minutes=0, seconds=0):
        self.value = START + dt.timedelta(hours=hours, minutes=minutes, seconds=seconds)
        return self.value

class FixtureFS(storage.FileSystem):
    def __init__(self, mount):
        self.mount = mount

    def mount_ready(self, path):
        return path == self.mount

    def free_bytes(self, path):
        assert path == self.mount
        return 2 ** 40

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for key in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                'TAVERN_IMPROVEMENT_UNATTENDED', local_model.CONFIG_ENV,
                storage.CONFIG_ENV, storage.REPORT_ENV,
                'ANTHROPIC_API_KEY', 'ZAI_API_KEY', 'OPENAI_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    for obj, name in ((agent_models, 'run'), (agent_models, 'load_keys'),
                      (storage, 'resolve_storage'), (workflow, 'execute'),
                      (workflow, 'run_check'), (workflow.git_publish, 'prepare'),
                      (subprocess, 'run'), (subprocess, 'Popen'),
                      (http.client, 'HTTPConnection'), (http.client, 'HTTPSConnection'),
                      (socket, 'socket'), (socket, 'create_connection'),
                      (socket, 'getaddrinfo'), (local_model, 'http_transport')):
        monkeypatch.setattr(obj, name, forbidden)

class Lab:
    def instruction(self, record):
        path = self.root.parent / 'synthetic-user-instruction.txt'
        path.write_text('제안 ' + record['id'] + ' 승인', encoding='utf-8')
        path.chmod(0o600)
        return path

    def spent(self):
        return self.ledger()['claude_spent_usd']

    def slots(self):
        return self.ledger()['slots']

    def calls(self):
        return self.ledger()['calls']

    def report(self):
        return self.state()['round']['report']

    def state(self):
        return self.store.read(loop.STATE_FILE)

    def ledger(self, date=None):
        return self.state()['days'][date or self.clock().date().isoformat()]

    def save_loop(self):
        self.loop_path.write_bytes(encode(self.config))

    def save_local(self):
        self.local_path.write_bytes(encode(self.local_config))
        self.local_path.chmod(0o600)

    def quota(self, key, timeout, max_bytes):
        assert key == SECRET and 0 < timeout <= 20 and max_bytes <= 65536
        state = self.state()
        slot = self.clock().strftime('%Y-%m-%dT%H')
        assert state['days'][self.clock().date().isoformat()]['slots'][slot]['status'] == 'claimed'
        self.quotas.append(slot)
        return 200, encode(quota_body(self.clock()))

    def local(self, role, paths, snapshots, **options):
        self.active_owner = role
        self.events.append(('local_explorer', role))
        self.assert_reserved('mlx-vlm')
        assert paths == imp.role_scope(role, FILES, self.discovery)
        return local_model.run(role, paths, snapshots, transport=self.local_http, **options)

    def local_http(self, config, body):
        assert os.environ.get('TAVERN_IMPROVEMENT_DISCOVERY') == '1'
        assert len(body) <= 24576 and config['limits']['timeout_seconds'] <= 180
        request = json.loads(body)
        assert set(request) == {'model', 'stream', 'max_tokens', 'temperature',
                                'enable_thinking', 'response_format', 'messages'}
        assert request['model'] == config['model'] and request['stream'] is False
        assert request['max_tokens'] <= 3072
        assert request['enable_thinking'] is False
        assert [m['role'] for m in request['messages']] == ['system', 'user']
        user = json.loads(request['messages'][1]['content'])
        assert user['owner_role'] == self.active_owner
        assert request['response_format']['type'] == 'json_schema'
        schema = request['response_format']['json_schema']
        assert schema['strict'] is True
        fields = schema['schema']['properties']['candidates']['items']['properties']
        assert fields['edit_files']['items']['enum'] == user['approved_files']
        assert fields['evidence']['items']['properties']['path']['enum'] == [user['sources'][0]['path']]
        self.local_requests.append(deepcopy(user))
        self.wire_requests.append(body)
        source = user['sources'][0]
        candidates = [draft(source['path'], source['start_line'], source['end_line'],
                            '로컬 ' + self.active_owner + ' 점검 후보')]
        if self.local_transform:
            candidates = self.local_transform(user, candidates)
        content = json.dumps({'candidates': candidates}, ensure_ascii=False)
        envelope = {'model': config['model'], 'choices': [
            {'message': {'role': 'assistant', 'content': content, 'tool_calls': None,
                         'tool_call_id': None, 'reasoning_content': None, 'reasoning': None,
                         'name': None}, 'finish_reason': 'stop'}]}
        body = encode(envelope)
        return {'status': 200, 'headers': [('Content-Type', 'application/json'),
                                          ('Content-Length', str(len(body)))], 'body': body}

    def assert_reserved(self, provider):
        state = self.state()
        pending = state['inflight']
        assert pending['provider'] == provider
        day = state['days'][pending['date']]
        slot = day['slots'][pending['slot']]
        assert slot['status'] == 'calling' and day['calls'] >= 1
        if provider == 'claude':
            assert 0 < pending['reservation_usd'] <= .2
            assert day['claude_spent_usd'] >= pending['reservation_usd']

    def cloud(self, role, prompt, keys, **options):
        spec = self.models['roles'][role]
        self.assert_reserved(spec['provider'])
        assert os.environ.get('TAVERN_IMPROVEMENT_DISCOVERY') == '1'
        assert options['write'] is False and options['scoped'] is True
        assert options['timeout'] <= self.config['model_timeout_seconds'] < 600
        assert SECRET not in prompt and 'nextResetTime' not in prompt
        paths = json.loads(re.search(r'Approved readable files \(exact paths\): (.*)\n', prompt).group(1))
        assert paths == imp.role_scope(role, FILES, self.discovery)
        context = options['workspace']
        assert self.root not in context.parents and context not in self.root.parents
        expected = getattr(self, 'expected_sources', None)
        present = [p for p in paths if expected[p]['exists']] if expected else paths
        assert sorted(str(p.relative_to(context)) for p in context.rglob('*') if p.is_file()) == sorted(present)
        for path in present:
            content = expected[path]['content'] if expected else (self.root / path).read_bytes()
            assert (context / path).read_bytes() == content
            assert (context / path).stat().st_mode & 0o777 == 0o400
        self.events.append(('independent_reviewer' if role == 'reviewer' else 'specialist', role))
        self.cloud_requests.append({'role': role, 'prompt': prompt, 'options': options})
        if role == 'reviewer':
            assert 0 < options['max_budget_usd'] <= .2
            prior = json.loads(prompt.split('\nPrior candidates: ', 1)[1])
            response = {'reviews': [dict(candidate_id=r['id'], verdict='eligible',
                                        reason=REVIEW_REASON, documentation=deepcopy(DOC))
                                    for r in prior], 'documentation': deepcopy(DOC)}
            add_assessments(response, options['discovery_review'])
        else:
            assert 'max_budget_usd' not in options
            context = json.loads(prompt.rsplit('\n', 1)[1])
            candidates = deepcopy(context['local_drafts'])
            for c in candidates:
                c['issue'] = '담당자 보완: ' + c['issue']
            response = {'candidates': candidates}
        result = dict(role=role, provider=spec['provider'], model=spec['model'],
                      status='passed', response=json.dumps(response, ensure_ascii=False),
                      diagnostics=RAW)
        if role == 'reviewer':
            result['cli_estimated_cost_usd'] = .04
        result = self.cloud_transform(role, result, response, options) if self.cloud_transform else result
        if role == 'reviewer':
            capture = options['discovery_review']
            if getattr(self, 'review_no_read', False):
                pass
            elif getattr(self, 'review_trace_transform', None):
                capture.accept(stdout(self.review_trace_transform(read_events(capture, result['response']))))
            else:
                capture_result(capture, result)
        return result

    def tick(self, hour=None, minutes=0, seconds=0, **options):
        if hour is not None:
            self.clock.at(hour, minutes, seconds)
        arguments = dict(selected=self.selected, runner=self.cloud, local_runner=self.local,
                         quota_transport=self.quota, keys={'ZAI_API_KEY': SECRET}, clock=self.clock)
        arguments.update(options)
        return loop.tick(**arguments)

    def hours(self, start=0, count=9):
        return [self.tick(hour) for hour in range(start, start + count)]

@pytest.fixture
def lab(tmp_path, monkeypatch):
    lab = Lab()
    lab.config = shipped('improvement-loop-config.json')
    lab.discovery = shipped('improvement-config.json')
    lab.models = shipped('agent-models.json')
    lab.policy = shipped('workflow-config.json')
    lab.local_config = shipped('local-model-config.json.example')
    lab.local_config['limits']['max_window_lines'] = 2
    lab.root = tmp_path / 'sources'
    lab.root.mkdir(mode=0o700)
    for name in FILES:
        path = lab.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join('value_{} = {}\n'.format(i, i) for i in range(1, 7)), encoding='utf-8')
        path.chmod(0o644)
    lab.scope = lab.root / 'harness/improvement-scope.txt'
    lab.scope.write_text('\n'.join(FILES) + '\n', encoding='utf-8')
    discovery_path = lab.root / 'harness/improvement-config.json'
    discovery_path.write_bytes(encode(lab.discovery))
    lab.loop_path = lab.root / 'harness/improvement-loop-config.json'
    lab.save_loop()
    lab.local_path = lab.root / 'logs/harness/local-model.json'
    lab.local_path.parent.mkdir(parents=True, mode=0o700)
    lab.save_local()
    lab.selected = storage.Storage(root=lab.root,
        artifacts=storage.DirectorySpec(tmp_path / 'artifacts', tmp_path, 0),
        temporary=storage.DirectorySpec(tmp_path / 'contexts', tmp_path, 0),
        config_path=tmp_path / 'synthetic-policy.json', env={}, fs=FixtureFS(tmp_path))
    monkeypatch.setattr(imp, 'ROOT', lab.root)
    monkeypatch.setattr(imp, 'CONFIG', discovery_path)
    monkeypatch.setattr(imp, 'REPORTS', lab.root / 'logs/harness/improvements')
    monkeypatch.setattr(local_model, 'ROOT', lab.root)
    monkeypatch.setattr(loop, 'CONFIG', lab.loop_path)
    monkeypatch.setattr(agent_models, 'load_config', lambda: deepcopy(lab.models))
    monkeypatch.setattr(workflow, 'load_policy', lambda: deepcopy(lab.policy))
    lab.clock = FakeClock()
    real_now = imp._now
    monkeypatch.setattr(imp, '_now', lambda now=None: real_now(lab.clock() if now is None else now))
    lab.store = imp.Store(lab.selected)
    lab.events, lab.cloud_requests, lab.local_requests, lab.wire_requests, lab.quotas = [], [], [], [], []
    lab.cloud_transform = lab.local_transform = None
    return lab

def quota_body(now=START, kind='TOKENS_LIMIT', percentage=1, weekly=None):
    reset = int((now + dt.timedelta(hours=5)).timestamp() * 1000)
    limits = [{'type': 'TIME_LIMIT', 'unit': 5, 'number': 1, 'remaining': 100},
              {'type': kind, 'unit': 3, 'number': 5,
               'percentage': percentage, 'nextResetTime': reset}]
    if weekly is not None:
        limits.append({'type': kind, 'unit': 6, 'number': 1, 'percentage': weekly,
                       'nextResetTime': int((now + dt.timedelta(days=7)).timestamp() * 1000)})
    return {'data': {'level': 'lite', 'limits': limits}}

def test_nine_stages_real_validation_and_private_local_provenance(lab):
    results = lab.hours()
    expected = [(stage, role) for role in contract.SPECIALIST_ROLES
                for stage in ('local_explorer', 'specialist')] + [('independent_reviewer', 'reviewer')]
    assert lab.events == expected
    assert [r['calls_today'] for r in results] == list(range(1, 10))
    state = lab.state()
    report = state['round']['report']
    assert state['stage_index'] == 9 and state['last_review_at'] == lab.clock().isoformat()
    assert report['status'] == 'scanned' and report['review_complete']
    assert len(report['proposals']) == 4
    assert [a['role'] for a in report['agents']] == list(contract.ROLES)
    assert all(a['status'] == 'succeeded' for a in report['agents'])
    assert all(a['provider'] != 'mlx-vlm' and 'result' not in a for a in report['agents'])
    assert len(report['local_participation']) == 4
    for local in report['local_participation']:
        assert local['provider'] == 'mlx-vlm' and local['model'] == lab.local_config['model']
        assert local['stage'] == 'local_explorer' and local['called'] is True
        assert local['cost'] is None and local['cost_status'] == 'not_metered'
        assert local['read_windows'] and 'request' not in local and 'response' not in local
    for record in report['proposals']:
        saved = lab.store.read('proposals/' + record['id'] + '.json')
        assert saved['proposal'] == record and saved['scan_id'] == report['scan_id']
        assert imp._eligible(lab.store, record['id']) == record
    assert lab.spent() == approx(.04)
    assert lab.quotas == ['2026-10-15T03']
    assert 'TAVERN_IMPROVEMENT_DISCOVERY' not in os.environ
    for entry in lab.cloud_requests:
        assert not entry['options']['workspace'].exists()
    for directory in ('decisions', 'approvals', 'claims', 'executions'):
        assert not lab.store.path(directory).exists()

def test_same_slot_restart_and_clock_rollback_never_replay(lab):
    lab.tick(0)
    first = lab.store.path(loop.STATE_FILE).read_bytes()
    lab.store = imp.Store(lab.selected)
    for minute in (0, 1, 59):
        assert lab.tick(0, minute)['reason'] == 'slot_already_claimed'
        assert lab.store.path(loop.STATE_FILE).read_bytes() == first
    lab.tick(1)
    after = lab.store.path(loop.STATE_FILE).read_bytes()
    assert lab.tick(0, 59)['reason'] == 'clock_rollback'
    assert lab.store.path(loop.STATE_FILE).read_bytes() == after
    assert len(lab.events) == 2 and lab.calls() == 2

def test_hourly_opportunities_never_exceed_twenty_four_in_kst_day(lab):
    lab.local_transform = lambda user, cs: cs + [dict(deepcopy(cs[0]), title=cs[0]['title'] + ' 두번째')]
    for hour in range(24):
        before = len(lab.events)
        lab.tick(hour)
        assert len(lab.events) - before == 1
        assert lab.tick(hour, 59)['reason'] == 'slot_already_claimed'
    assert len(lab.events) == lab.calls() == 24
    assert len(lab.slots()) == 24
    for entry in lab.state()['completed']:
        report = lab.store.read('scans/' + entry['scan_id'] + '.json')
        assert len(report['proposals']) == 8
    lab.tick(24)
    assert lab.calls() == 1 and len(lab.events) == 25

def test_lower_day_cap_blocks_new_slot_but_morning_still_finalizes(lab):
    lab.config['max_calls_per_day'] = 1
    lab.save_loop()
    lab.tick(0)
    assert lab.tick(1)['reason'] == 'daily_call_limit'
    result = lab.tick(9)
    assert result['reason'] == 'daily_call_limit' and len(lab.events) == 1
    report = lab.store.read('days/2026-10-15.json')
    assert report['review_complete'] is False and report['proposals'] == []
    assert report['status'] == 'failed'
    assert all(a['status'] == 'not_called' for a in report['agents'])
    assert '미호출 5개' in report['summary']

@pytest.mark.parametrize('project', [False, True])
def test_contending_lock_does_not_claim_or_report_a_scan(lab, project):
    with lab.store.lock(project=project):
        result = lab.tick(9)
    assert result['status'] == 'paused'
    assert result['reason'] == ('project_lock_busy' if project else 'discovery_lock_busy')
    assert lab.events == []
    if project:
        assert lab.calls() == 0
        assert lab.store.read('days/2026-10-15.json')['review_complete'] is False
        assert lab.tick(9)['reason'] == 'slot_already_claimed'
        assert lab.tick(10)['calls_today'] == 1
    else:
        assert not lab.store.exists(loop.STATE_FILE)
        assert not lab.store.exists('days/2026-10-15.json')
        assert lab.tick(9)['calls_today'] == 1

def test_reentrant_tick_inside_model_cannot_double_admit(lab):
    actual = lab.local
    reentered = []

    def local(*args, **kwargs):
        reentered.append(lab.tick())
        return actual(*args, **kwargs)

    lab.tick(0, local_runner=local)
    assert reentered[0]['reason'] == 'discovery_lock_busy'
    assert len(lab.events) == 1 and lab.calls() == 1

def test_project_lock_is_shared_even_with_different_artifact_policy(lab):
    other = storage.Storage(root=lab.root,
        artifacts=storage.DirectorySpec(lab.root.parent / 'other-artifacts', lab.root.parent, 0),
        temporary=storage.DirectorySpec(lab.root.parent / 'other-contexts', lab.root.parent, 0),
        config_path=lab.root.parent / 'other-policy.json', env={}, fs=FixtureFS(lab.root.parent))
    with lab.store.lock(project=True):
        result = lab.tick(9, selected=other)
    assert result['reason'] == 'project_lock_busy'
    assert lab.events == [] and imp.Store(other).read(loop.STATE_FILE)['days']['2026-10-15']['calls'] == 0

@pytest.mark.parametrize('failure', ['readiness', 'storage_config', 'loop_config'])
def test_storage_unready_never_falls_back_or_loads_credentials(lab, monkeypatch, failure):
    attempts = []

    def unavailable(*args, **kwargs):
        attempts.append(failure)
        if failure == 'loop_config':
            raise loop.LoopError(RAW + SECRET)
        raise storage.StorageError(RAW + SECRET)

    options = {'keys': None, 'deliver': True, 'publisher': forbidden}
    if failure == 'readiness':
        monkeypatch.setattr(storage.Storage, 'check_ready', unavailable)
    elif failure == 'storage_config':
        monkeypatch.setattr(storage, 'resolve_storage', unavailable)
        options['selected'] = None
    else:
        monkeypatch.setattr(loop, 'load_config', unavailable)
    for obj, name in ((agent_models, 'load_keys'), (local_model, 'load_config'),
                      (loop, '_tick_locked'), (loop, '_freeze_unavailable_morning'),
                      (loop, 'publish'), (imp.Store, 'write')):
        monkeypatch.setattr(obj, name, forbidden)
    result = lab.tick(9, **options)
    assert result['status'] == 'paused' and lab.events == []
    assert result['reason'] == ('storage_readiness_invalid' if failure == 'readiness' else 'config_invalid')
    assert attempts == [failure]
    assert lab.quotas == [] and lab.cloud_requests == [] and lab.local_requests == []
    assert not lab.store.exists(loop.STATE_FILE)
    assert not lab.store.exists('days/2026-10-15.json')
    serialized = json.dumps(result)
    assert len(serialized) < 1024 and SECRET not in serialized and RAW not in serialized

@pytest.mark.parametrize('minute,second,admitted', [(49, 59, True), (50, 0, False), (59, 59, False)])
def test_midnight_guard_covers_entire_tick_deadline(lab, minute, second, admitted):
    result = lab.tick(23, minute, second)
    assert len(lab.events) == int(admitted)
    assert result['calls_today'] == int(admitted)
    if not admitted:
        assert result['reason'] == 'midnight_guard'
    assert lab.tick(23, 59, 59)['reason'] == 'slot_already_claimed'

@pytest.mark.parametrize('finish_hour,reason', [(24, 'clock_crossed_accounting_day'),
                                                (22, 'clock_rollback_during_call')])
def test_wall_clock_jump_during_call_stops_instead_of_resetting_allowance(lab, finish_hour, reason):
    actual = lab.local

    def jumping(*args, **kwargs):
        result = actual(*args, **kwargs)
        lab.clock.at(finish_hour)
        return result

    result = lab.tick(23, local_runner=jumping)
    assert result['reason'] == reason and len(lab.events) == 1
    assert lab.report()['review_complete'] is False
    entry = lab.state()['local_history'][0]
    assert entry['call_finished_at'] == lab.clock().isoformat()
    assert entry['finished_at'] >= entry['started_at']
    slots = lab.ledger(entry['slot'][:10])['slots']
    assert slots[entry['slot']]['call_finished_at'] == entry['call_finished_at']
    if finish_hour == 24:
        for date in ('2026-10-15', '2026-10-16'):
            assert lab.ledger(date)['calls'] == 1 and lab.ledger(date)['stopped']
        assert lab.tick(25)['reason'] == reason and len(lab.events) == 1

def test_slot_claim_precedes_configuration_failure_and_is_not_retried(lab):
    lab.local_path.unlink()
    result = lab.tick(0)
    assert result['reason'] == 'config_unavailable'
    assert lab.calls() == 0 and lab.events == []
    lab.save_local()
    assert lab.tick(0, 1)['reason'] == 'slot_already_claimed'
    assert lab.tick(1)['calls_today'] == 1

def test_invalid_config_at_report_time_still_freezes_truthful_report(lab):
    lab.local_path.unlink()
    lab.tick(9)
    report = lab.store.read('days/2026-10-15.json')
    assert report['status'] == 'failed' and report['proposals'] == []
    assert report['errors'] == ['current_dependencies_unavailable']
    payload = lab.store.read('web/2026-10-15.json')
    contract.validate_web_report(payload)
    assert all(a['status'] == 'not_called' for a in payload['agents'])

@pytest.mark.parametrize('name,value', [
    ('daily_budget_usd', True), ('daily_budget_usd', float('nan')),
    ('daily_budget_usd', float('inf')), ('daily_budget_usd', 0),
    ('daily_budget_usd', -1), ('daily_budget_usd', 1.01),
    ('reviewer_max_budget_usd', .21), ('max_calls_per_day', 25),
    ('max_calls_per_day', True), ('slot_minutes', 30), ('report_hour', 8),
    ('model_timeout_seconds', 521), ('midnight_guard_seconds', 599),
    ('max_candidates', 9), ('max_candidates_per_specialist', 3),
    ('quota_timeout_seconds', 21), ('quota_pause_percentage', 81),
    ('timezone', 'UTC'), ('unexpected', 'field')])
def test_configuration_rejects_nonfinite_bool_unknown_and_policy_expansion(lab, name, value):
    config = deepcopy(lab.config)
    config[name] = value
    with pytest.raises(loop.LoopError):
        loop.validate_config(config)

def test_configuration_requires_explicit_fields_and_cross_field_bounds(lab):
    config = deepcopy(lab.config)
    del config['daily_budget_usd']
    with pytest.raises(loop.LoopError):
        loop.validate_config(config)
    for changes in ({'daily_budget_usd': .1}, {'tick_timeout_seconds': 500},
                    {'max_candidates_per_specialist': 1, 'max_candidates': 8}):
        with pytest.raises(loop.LoopError):
            loop.validate_config(dict(lab.config, **changes))

@pytest.mark.parametrize('kind', ['TOKENS_LIMIT', 'CREDIT_LIMIT'])
@pytest.mark.parametrize('percentage,weekly,ready', [(0, None, True), (79.999, 20, True),
                                                   (80, None, False), (1, 80, False), (100, 1, False)])
def test_glm_legacy_credit_and_optional_weekly_headroom(kind, percentage, weekly, ready):
    result = loop.validate_quota(quota_body(kind=kind, percentage=percentage, weekly=weekly), START)
    assert result['status'] == ('ready' if ready else 'paused')
    assert result['reason'] == ('quota_ready' if ready else 'quota_headroom')
    assert len(result['limits']) == (1 if weekly is None else 2)

@pytest.mark.parametrize('kind', ['TOKENS_LIMIT', 'CREDIT_LIMIT'])
@pytest.mark.parametrize('percentage', [0, 0.0])
@pytest.mark.parametrize('missing', [False, True])
def test_glm_zero_idle_five_hour_reset_stays_unknown(kind, percentage, missing):
    body = quota_body(kind=kind, percentage=percentage)
    body.update(code=200, success=True)
    model = body['data']['limits'][1]
    model['nextResetTime'] = None
    if missing:
        del model['nextResetTime']
    result = loop.validate_quota(body, START)
    assert result == {'status': 'ready', 'reason': 'quota_ready', 'limits': [
        {'type': kind, 'unit': 3, 'number': 5, 'percentage': percentage,
         'nextResetTime': None}]}
    assert loop.validate_quota(body, START + dt.timedelta(hours=1)) == result

@pytest.mark.parametrize('kind', ['TOKENS_LIMIT', 'CREDIT_LIMIT'])
@pytest.mark.parametrize('missing', [False, True])
@pytest.mark.parametrize('percentage', [1, 80, True, '0', -1, 101,
                                      float('nan'), float('inf')])
def test_glm_missing_reset_does_not_excuse_nonzero_or_invalid_usage(kind, missing, percentage):
    body = quota_body(kind=kind)
    model = body['data']['limits'][1]
    model.update(percentage=percentage, nextResetTime=None)
    if missing:
        del model['nextResetTime']
    assert loop.validate_quota(body, START)['reason'] == 'quota_malformed'

@pytest.mark.parametrize('reset', [True, False, 0, -1, '', 'unknown', 1.5,
                                  float('nan'), float('inf'),
                                  int(START.timestamp() * 1000),
                                  int((START + dt.timedelta(days=9)).timestamp() * 1000)])
def test_glm_zero_idle_never_accepts_a_present_invalid_reset(reset):
    body = quota_body(percentage=0)
    body['data']['limits'][1]['nextResetTime'] = reset
    assert loop.validate_quota(body, START)['reason'] == 'quota_malformed'

@pytest.mark.parametrize('envelope', [
    {'success': False}, {'success': None}, {'success': 1}, {'success': 'true'},
    {'code': 500}, {'code': None}, {'code': True}, {'code': 200.0}, {'code': '200'},
    {'code': 200, 'success': False}, {'code': 500, 'success': True}])
def test_glm_failure_or_malformed_envelope_is_not_zero_idle(envelope):
    body = quota_body(percentage=0)
    body['data']['limits'][1]['nextResetTime'] = None
    body.update(envelope)
    assert loop.validate_quota(body, START)['reason'] == 'quota_malformed'

@pytest.mark.parametrize('kind', ['TOKENS_LIMIT', 'CREDIT_LIMIT'])
@pytest.mark.parametrize('weekly,ready', [(0, True), (79.999, True), (80, False)])
def test_glm_zero_idle_keeps_optional_weekly_headroom(kind, weekly, ready):
    body = quota_body(kind=kind, percentage=0, weekly=weekly)
    body['data']['limits'][1]['nextResetTime'] = None
    result = loop.validate_quota(body, START)
    assert result['status'] == ('ready' if ready else 'paused')
    assert result['reason'] == ('quota_ready' if ready else 'quota_headroom')
    assert result['limits'][0]['nextResetTime'] is None
    assert result['limits'][1] == body['data']['limits'][2]

@pytest.mark.parametrize('kind', ['TOKENS_LIMIT', 'CREDIT_LIMIT'])
@pytest.mark.parametrize('changes', [{}, {'nextResetTime': None}, {'nextResetTime': False},
                                   {'percentage': True}, {'unit': 6, 'number': 2}])
def test_glm_zero_idle_does_not_allow_missing_or_invalid_weekly_reset(kind, changes):
    body = quota_body(kind=kind, percentage=0, weekly=0)
    body['data']['limits'][1]['nextResetTime'] = None
    weekly = body['data']['limits'][2]
    if not changes:
        del weekly['nextResetTime']
    weekly.update(changes)
    assert loop.validate_quota(body, START)['reason'] == 'quota_malformed'

@pytest.mark.parametrize('kind', ['TOKENS_LIMIT', 'CREDIT_LIMIT'])
def test_glm_duplicate_idle_window_is_still_malformed(kind):
    body = quota_body(kind=kind, percentage=0)
    model = body['data']['limits'][1]
    model['nextResetTime'] = None
    body['data']['limits'].append(deepcopy(model))
    assert loop.validate_quota(body, START)['reason'] == 'quota_malformed'

@pytest.mark.parametrize('kind', ['TOKENS_LIMIT', 'CREDIT_LIMIT'])
def test_glm_zero_idle_admits_only_the_current_specialist_and_keeps_unknown_reset(lab, kind):
    lab.hours(count=3)
    requests = []

    def transport(key, timeout, max_bytes):
        assert key == SECRET
        requests.append(lab.clock())
        assert lab.slots()['2026-10-15T03']['status'] == 'claimed'
        body = quota_body(lab.clock(), kind=kind, percentage=0)
        body.update(code=200, success=True)
        body['data']['limits'][1]['nextResetTime'] = None
        return 200, encode(body)

    result = lab.tick(3, quota_transport=transport)
    assert result['calls_today'] == 4 and lab.state()['stage_index'] == 4
    assert lab.events[-1] == ('specialist', 'downloader') and len(lab.events) == 4
    quota = lab.slots()['2026-10-15T03']['quota']
    assert quota['status'] == 'ready' and quota['limits'][0]['nextResetTime'] is None
    assert lab.tick(3, 59, quota_transport=transport)['reason'] == 'slot_already_claimed'
    assert requests == [START + dt.timedelta(hours=3)]

@pytest.mark.parametrize('changes', [
    {'type': 'UNKNOWN_LIMIT'}, {'unit': 6, 'number': 2}, {'unit': True},
    {'percentage': True}, {'percentage': -1}, {'percentage': 101},
    {'percentage': float('nan')}, {'percentage': float('inf')},
    {'nextResetTime': True}, {'nextResetTime': 0},
    {'nextResetTime': int((START + dt.timedelta(days=9)).timestamp() * 1000)}])
def test_glm_unknown_malformed_percentage_or_reset_fails_closed(changes):
    body = quota_body()
    body['data']['limits'][1].update(changes)
    assert loop.validate_quota(body, START)['status'] == 'paused'

def test_glm_time_limit_alone_duplicate_and_weekly_without_model_window_are_not_ready():
    body = quota_body()
    model = body['data']['limits'].pop()
    assert loop.validate_quota(body, START)['reason'] == 'quota_model_limit_missing'
    body['data']['limits'].append(dict(model, unit=6, number=1))
    assert loop.validate_quota(body, START)['status'] == 'paused'
    body['data']['limits'] = [model, deepcopy(model)]
    assert loop.validate_quota(body, START)['reason'] == 'quota_malformed'

@pytest.mark.parametrize('failure', ['redirect', 'http_error', 'exception', 'oversize',
                                     'malformed', 'missing_key'])
def test_quota_failure_preserves_slot_and_never_calls_glm_or_leaks_raw(lab, failure):
    lab.hours(count=3)
    calls = []

    def transport(key, timeout, max_bytes):
        calls.append((timeout, max_bytes))
        if failure == 'exception':
            raise TimeoutError(SECRET + RAW)
        return {'redirect': (302, encode({'secret': SECRET})),
                'http_error': (503, encode(quota_body(lab.clock(), percentage=0))),
                'oversize': (200, b'x' * (max_bytes + 1)),
                'malformed': (200, (SECRET + RAW).encode())}[failure]

    keys = {} if failure == 'missing_key' else {'ZAI_API_KEY': SECRET}
    result = lab.tick(3, quota_transport=transport, keys=keys)
    assert result['status'] == 'paused' and len(lab.events) == 3
    assert lab.calls() == 3
    assert lab.tick(3, 59)['reason'] == 'slot_already_claimed'
    assert len(calls) == (0 if failure == 'missing_key' else 1)
    retained = json.dumps(lab.state(), ensure_ascii=False) + json.dumps(result)
    assert SECRET not in retained and RAW not in retained
    assert lab.tick(4)['calls_today'] == 4
    assert lab.quotas[-1] == '2026-10-15T04'

def test_glm_eighty_percent_pauses_actual_stage_until_new_slot_has_headroom(lab):
    lab.hours(count=3)
    result = lab.tick(3, quota_transport=lambda *args: (200, encode(quota_body(lab.clock(), percentage=80))))
    assert result['reason'] == 'quota_headroom' and len(lab.events) == 3
    assert lab.state()['stage_index'] == 3
    assert lab.tick(4)['calls_today'] == 4
    assert lab.events[-1] == ('specialist', 'downloader')

@pytest.mark.parametrize('code', [200, 302])
def test_real_quota_transport_uses_only_fixed_https_get_without_following_redirects(monkeypatch, code):
    calls, timeouts, connections = [], [], []
    body = encode(quota_body())

    class Response:
        status = code

        def __init__(self):
            self.remaining = body

        def getheaders(self):
            return [('Content-Length', str(len(body)))]

        def getheader(self, name):
            assert name == 'Content-Length'
            return str(len(body))

        def read1(self, size):
            assert code == 200
            part, self.remaining = self.remaining[:size], self.remaining[size:]
            return part

    class HTTPS:
        def __init__(self, host, timeout):
            assert host == 'api.z.ai' and timeout <= 20
            self.sock = self
            self.closed = False
            connections.append(self)

        def request(self, method, path, headers):
            calls.append((method, path))
            assert headers['Authorization'] == SECRET
            assert headers['Connection'] == 'close'

        def getresponse(self):
            return Response()

        def settimeout(self, value):
            assert 0 < value <= 15
            timeouts.append(value)

        def close(self):
            self.closed = True

    monkeypatch.setattr(http.client, 'HTTPSConnection', HTTPS)
    result = loop.fetch_glm_quota({'ZAI_API_KEY': SECRET}, START)
    assert calls == [('GET', '/api/monitor/usage/quota/limit')]
    assert len(connections) == 1 and connections[0].closed
    assert result['status'] == ('ready' if code == 200 else 'paused')
    assert bool(timeouts) is (code == 200)
    assert SECRET not in json.dumps(result)

@pytest.mark.parametrize('mode', ['unknown', 'timeout', 'failed_known', 'invalid_cost', 'negative_cost'])
def test_reviewer_failure_or_unknown_cost_conservatively_consumes_reservation(lab, mode):
    lab.hours(count=8)

    def transform(role, result, response, options):
        assert role == 'reviewer'
        if mode == 'timeout':
            raise TimeoutError(RAW + SECRET)
        if mode == 'unknown':
            result.pop('cli_estimated_cost_usd')
        elif mode == 'failed_known':
            result.update(status='failed', cli_estimated_cost_usd=.01)
        else:
            result['cli_estimated_cost_usd'] = float('nan') if mode == 'invalid_cost' else -1
        return result

    lab.cloud_transform = transform
    lab.tick(8)
    assert lab.spent() == approx(.2)
    slot = lab.slots()['2026-10-15T08']
    assert slot['cost_status'] in ('reservation_consumed_unknown', 'reservation_consumed_failed')
    reviewer = lab.report()['agents'][-1]
    if mode != 'failed_known':
        assert reviewer['cost'] is None and reviewer['cost_status'] == 'unknown'
    assert_private(lab.state())
    assert lab.tick(8, 1)['reason'] == 'slot_already_claimed'
    lab.store = imp.Store(lab.selected)
    lab.tick(9)
    assert lab.spent() == approx(.2)

def test_remaining_budget_is_passed_as_downward_override_and_settled(lab):
    lab.hours(count=8)
    state = lab.state()
    state['days']['2026-10-15']['claude_spent_usd'] = .93
    lab.store.write(loop.STATE_FILE, state)
    lab.tick(8)
    request = lab.cloud_requests[-1]
    assert request['options']['max_budget_usd'] == approx(.07)
    assert lab.spent() == approx(.97)
    assert lab.models['roles']['reviewer']['max_budget_usd'] == 2

def test_loop_cap_never_increases_smaller_existing_reviewer_budget(lab):
    lab.models['roles']['reviewer']['max_budget_usd'] = .05
    lab.hours()
    assert lab.cloud_requests[-1]['options']['max_budget_usd'] == .05
    assert lab.spent() == approx(.04)

def test_exhausted_budget_holds_reviewer_and_later_stages_but_not_morning(lab):
    lab.hours(count=8)
    state = lab.state()
    state['days']['2026-10-15']['claude_spent_usd'] = 1
    lab.store.write(loop.STATE_FILE, state)
    assert lab.tick(8)['reason'] == 'daily_budget_limit'
    for hour in (9, 10, 11):
        assert lab.tick(hour)['reason'] == 'daily_budget_limit'
        assert lab.state()['stage_index'] == 8
    assert len(lab.events) == 8 and lab.calls() == 8
    assert len(lab.local_requests) == 4 and len(lab.cloud_requests) == 4
    assert lab.state()['inflight'] is None
    assert lab.store.read('days/2026-10-15.json')['status'] == 'partial'
    assert lab.store.read('days/2026-10-15.json')['proposals'] == []

@pytest.mark.parametrize('invalid', [False, True])
def test_actual_cost_over_reservation_is_recorded_and_stops_day(lab, invalid):
    lab.hours(count=8)
    lab.cloud_transform = lambda role, result, response, options: dict(result, cli_estimated_cost_usd=.27,
        **({'response': '{broken'} if invalid else {}))
    result = lab.tick(8)
    assert result['reason'] == 'daily_budget_overrun'
    assert lab.spent() == approx(.27)
    assert lab.slots()['2026-10-15T08']['budget_overrun'] is True
    lab.tick(9)
    assert len(lab.events) == 9 and lab.calls() == 9
    assert lab.store.exists('days/2026-10-15.json')

@pytest.mark.parametrize('invalid', [False, True])
def test_overrun_persisted_before_interruption_is_never_reduced_to_reservation(lab, monkeypatch, invalid):
    lab.hours(count=8)
    lab.cloud_transform = lambda role, result, response, options: dict(result, cli_estimated_cost_usd=.27,
        **({'response': '{broken'} if invalid else {}))
    actual = imp.Store.write

    def crash_after_estimate(store, name, value):
        result = actual(store, name, value)
        if (name == loop.STATE_FILE and value['inflight'] is not None and
                value['days']['2026-10-15']['slots']['2026-10-15T08'].get('budget_overrun')):
            raise PowerLoss()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(imp.Store, 'write', crash_after_estimate)
        with pytest.raises(PowerLoss):
            lab.tick(8)
    assert lab.spent() == approx(.27)
    lab.tick(8, 1)
    assert lab.spent() == approx(.27)
    reviewer = lab.report()['agents'][-1]
    assert reviewer['cost'] == approx(.27) and reviewer['status'] == 'failed'
    if invalid:
        assert reviewer['reason'] == 'role_json_invalid'
        assert reviewer['failure_detail']['cause'] == 'json_invalid'
        assert lab.state()['participation'][-1]['failure_detail'] == reviewer['failure_detail']
    assert lab.tick(9)['reason'] == 'daily_budget_overrun'
    assert len(lab.events) == 9

def test_failed_durable_reservation_never_starts_reviewer_or_retries_slot(lab, monkeypatch):
    lab.hours(count=8)
    actual = imp.Store.write

    def disk_full(store, name, value):
        if name == loop.STATE_FILE and value['inflight'] is not None:
            raise OSError(RAW + SECRET)
        return actual(store, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(imp.Store, 'write', disk_full)
        lab.tick(8)
    assert len(lab.events) == 8
    assert lab.calls() == 8 and lab.spent() == 0
    assert lab.state()['inflight'] is None
    assert lab.tick(8, 1)['reason'] == 'slot_already_claimed'
    assert len(lab.events) == 8

@pytest.mark.parametrize('when', ['before_runner', 'during_runner'])
def test_power_loss_keeps_reservation_and_recovers_stage_once(lab, monkeypatch, when):
    lab.hours(count=8)
    actual = imp.Store.write

    def interrupted_write(store, name, value):
        result = actual(store, name, value)
        if name == loop.STATE_FILE and value['inflight'] is not None:
            raise PowerLoss()
        return result

    def interrupted_runner(*args, **kwargs):
        lab.assert_reserved('claude')
        raise PowerLoss()

    with monkeypatch.context() as patch:
        if when == 'before_runner':
            patch.setattr(imp.Store, 'write', interrupted_write)
        with pytest.raises(PowerLoss):
            lab.tick(8, runner=interrupted_runner if when == 'during_runner' else lab.cloud)
    assert lab.state()['inflight']['reservation_usd'] == .2
    assert lab.calls() == 9 and lab.spent() == approx(.2)
    lab.store = imp.Store(lab.selected)
    assert lab.tick(8, 1)['reason'] == 'slot_already_claimed'
    recovered = lab.state()
    assert recovered['inflight'] is None and recovered['stage_index'] == 9
    assert recovered['round']['report']['agents'][-1]['reason'] == 'interrupted_unknown'
    assert recovered['round']['report']['agents'][-1]['cost'] is None
    lab.tick(9)
    assert lab.spent() == approx(.2)
    assert lab.calls() == 10
    assert all(c['role'] != 'reviewer' for c in lab.cloud_requests)

def test_cross_midnight_recovery_charges_both_days_without_double_refund(lab):
    lab.hours(count=8)

    def crash(*args, **kwargs):
        raise PowerLoss()

    with pytest.raises(PowerLoss):
        lab.tick(23, runner=crash)
    result = lab.tick(24)
    assert result['reason'] == 'clock_crossed_accounting_day'
    for date, count in (('2026-10-15', 9), ('2026-10-16', 1)):
        assert lab.ledger(date)['calls'] == count
        assert lab.ledger(date)['claude_spent_usd'] == approx(.2)
        assert lab.ledger(date)['stopped'] is True
    lab.tick(25)
    assert lab.spent() == approx(.2) and lab.calls() == 1

def test_interrupted_local_cursor_is_durable_and_paired_owner_runs_independently(lab):
    def crash(*args, **kwargs):
        lab.assert_reserved('mlx-vlm')
        raise PowerLoss()

    with pytest.raises(PowerLoss):
        lab.tick(0, local_runner=crash)
    assert lab.state()['cursors']['coordinator'] == {'file_index': 0, 'line': 3}
    lab.store = imp.Store(lab.selected)
    lab.tick(1)
    assert [r['role'] for r in lab.cloud_requests] == ['coordinator']
    context = json.loads(lab.cloud_requests[-1]['prompt'].rsplit('\n', 1)[1])
    assert context['local_drafts'] == []
    assert context['feedback'][0]['specialist_reason'] == 'local_interrupted_unknown'
    assert lab.calls() == 2
    local = lab.report()['local_participation'][0]
    assert local['status'] == 'failed' and local['reason'] == 'interrupted_unknown'
    lab.hours(start=2, count=8)
    request = lab.local_requests[-1]
    assert request['owner_role'] == 'coordinator'
    assert request['sources'][0]['start_line'] == 3
    assert request['feedback'][0]['specialist_reason'] == 'local_interrupted_unknown'
    assert request['feedback'][1]['specialist_reason'] == 'specialist_empty_candidates'

@pytest.mark.parametrize('crash', [False, True])
def test_empty_local_feedback_survives_failed_or_interrupted_independent_owner(lab, crash):
    lab.local_transform = lambda user, candidates: []
    lab.tick(0)

    def unavailable(*args, **kwargs):
        lab.assert_reserved(lab.models['roles']['coordinator']['provider'])
        if crash:
            raise PowerLoss()
        raise RuntimeError(RAW)

    if crash:
        with pytest.raises(PowerLoss):
            lab.tick(1, runner=unavailable)
    else:
        lab.tick(1, runner=unavailable)
    lab.store = imp.Store(lab.selected)
    assert lab.tick(1, 1)['reason'] == 'slot_already_claimed'
    assert lab.calls() == 2 and lab.state()['stage_index'] == 2
    lab.hours(start=2, count=7)
    report = lab.report()
    assert report['review_complete'] is True and report['status'] == 'partial'
    assert report['agents'][0]['status'] in ('failed', 'unavailable')
    assert report['agents'][-1]['status'] == 'succeeded'
    assert report['proposals'] == [] and lab.calls() == 9
    lab.tick(9)
    request = lab.local_requests[-1]
    assert request['owner_role'] == 'coordinator'
    assert request['sources'][0]['start_line'] == 3
    assert [entry['specialist_reason'] for entry in request['feedback']] == [
        'empty_draft', 'specialist_interrupted_unknown' if crash else 'role_execution_failed']
    assert RAW not in json.dumps(request)

def test_settlement_survives_crash_before_derived_scan_and_does_not_repeat_review(lab, monkeypatch):
    lab.hours(count=8)
    actual = imp.Store.write

    def crash_on_scan(store, name, value):
        if name.startswith('scans/') and value.get('review_complete'):
            raise PowerLoss()
        return actual(store, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(imp.Store, 'write', crash_on_scan)
        with pytest.raises(PowerLoss):
            lab.tick(8)
    assert lab.state()['inflight'] is None and lab.state()['stage_index'] == 9
    assert lab.spent() == approx(.04)
    lab.tick(9)
    assert sum(c['role'] == 'reviewer' for c in lab.cloud_requests) == 1
    assert lab.store.read('days/2026-10-15.json')['review_complete'] is True

def legacy(lab, complete=True, cost=.0434664, cost_status='cli_estimated_usd'):
    report = {'scan_id': '123456789-abcdef', 'date': '2026-10-15',
              'review_complete': complete, 'agents': [
                  {'role': role, 'provider': lab.models['roles'][role]['provider'],
                   'status': 'succeeded', 'cost': cost if role == 'reviewer' else None,
                   'cost_status': cost_status if role == 'reviewer' else 'unknown'}
                  for role in contract.ROLES]}
    lab.store.write('days/2026-10-15.json', report)
    lab.store.write('scans/' + report['scan_id'] + '.json', report)
    return report

@pytest.mark.parametrize('cost', [.0434664, .07125])
def test_legacy_day_and_scan_are_carried_once_without_hardcoded_cost_or_redelivery(lab, cost):
    old = legacy(lab, cost=cost)
    body = lab.store.path('days/2026-10-15.json').read_bytes()
    lab.tick(9, publisher=forbidden)
    assert lab.calls() == 6
    assert lab.spent() == approx(cost)
    assert lab.ledger()['legacy_seen'] == [old['scan_id']]
    lab.store = imp.Store(lab.selected)
    lab.tick(10, publisher=forbidden)
    assert lab.calls() == 7
    assert lab.spent() == approx(cost)
    assert lab.store.path('days/2026-10-15.json').read_bytes() == body
    assert lab.store.read(loop._publication_name('2026-10-15'))['status'] == 'legacy_preserved'

def test_indexed_legacy_and_exact_day_pointer_carry_in_without_rescanning(lab):
    first = legacy(lab, cost=.03)
    lab.tick(0)
    second = deepcopy(first)
    second['scan_id'] = '123456790-abcdef'
    second['agents'][-1]['cost'] = .02
    lab.store.write('scans/' + second['scan_id'] + '.json', second)
    lab.store.write('days/2026-10-15.json', second)
    already_accounted = dict(deepcopy(second), scan_id='123456791-abcdef',
                             loop_engine=loop.STATE_VERSION)
    lab.store.write('scans/' + already_accounted['scan_id'] + '.json', already_accounted)
    lab.tick(1)
    assert lab.calls() == 12
    assert lab.spent() == approx(.05)
    assert lab.ledger()['legacy_seen'] == [first['scan_id'], second['scan_id']]
    lab.store = imp.Store(lab.selected)
    lab.tick(2)
    assert lab.calls() == 13 and lab.spent() == approx(.05)

@pytest.mark.parametrize('complete,cost,status', [(False, .0434664, 'cli_estimated_usd'),
                                               (True, None, 'unknown')])
def test_unknown_legacy_activity_consumes_day_budget_conservatively(lab, complete, cost, status):
    legacy(lab, complete, cost, status)
    lab.tick(0)
    day = lab.ledger()
    assert day['claude_spent_usd'] == approx(1)
    assert day['legacy_cost_status'] == 'unknown_consumed'
    if not complete:
        assert day['calls'] >= 24 and lab.events == []

def test_owner_cursor_rotates_contiguous_original_line_windows_across_restarts(lab):
    lab.hours(count=10)
    requests = [r for r in lab.local_requests if r['owner_role'] == 'coordinator']
    assert [(r['sources'][0]['start_line'], r['sources'][0]['end_line']) for r in requests] == [(1, 2), (3, 4)]
    lab.store = imp.Store(lab.selected)
    lab.hours(start=10, count=18)
    requests = [r for r in lab.local_requests if r['owner_role'] == 'coordinator']
    windows = [r['sources'][0] for r in requests]
    assert [(w['path'], w['start_line'], w['end_line']) for w in windows] == [
        (FILES[0], 1, 2), (FILES[0], 3, 4), (FILES[0], 5, 6), ('AGENTS.md', 1, 2)]
    for window in windows:
        assert [line['line'] for line in window['numbered_lines']] == list(range(window['start_line'], window['end_line'] + 1))
        assert all(line['text'] == 'value_{} = {}'.format(line['line'], line['line']) for line in window['numbered_lines'])

def test_long_single_line_is_explicit_skip_and_specialist_still_runs(lab):
    (lab.root / FILES[0]).write_text('x' * 30000 + '\nvalue = 2\n', encoding='utf-8')
    result = lab.tick(0)
    assert result['reason'] == 'line_too_long' and lab.local_requests == []
    assert lab.calls() == 0
    participation = lab.report()['local_participation'][0]
    assert participation['called'] is False and participation['status'] == 'skipped'
    assert participation['skipped_lines'] == [{'path': FILES[0], 'start_line': 1, 'end_line': 1,
                                              'reason': 'line_too_long'}]
    assert lab.state()['cursors']['coordinator'] == {'file_index': 0, 'line': 2}
    lab.tick(1)
    assert [r['role'] for r in lab.cloud_requests] == ['coordinator']

@pytest.mark.parametrize('failure,reason', [
    ('empty', 'empty_draft'), ('timeout', 'timeout'),
    ('outside_evidence', 'evidence_outside_window'), ('outside_benefit', 'evidence_outside_window'),
    ('basename', 'candidate_invalid'), ('too_many', 'candidate_invalid'),
    ('edit_invalid', 'candidate_edit_files_invalid'),
    ('edit_duplicate', 'candidate_edit_files_duplicate'),
    ('edit_scope', 'candidate_edit_files_outside_scope'),
])
def test_failed_local_draft_keeps_regular_owner_slot_and_truthful_diagnostic(lab, failure, reason):
    def transform(user, cs):
        if user['owner_role'] != 'coordinator':
            return cs
        if failure == 'timeout':
            raise TimeoutError(RAW + SECRET)
        if failure == 'empty':
            return []
        if failure == 'too_many':
            return [dict(deepcopy(cs[0]), title='합성 후보 ' + str(i)) for i in range(3)]
        if failure == 'outside_evidence':
            cs[0]['evidence'][0]['end_line'] = 3
        elif failure == 'outside_benefit':
            cs[0]['benefit']['evidence'] = [dict(cs[0]['evidence'][0], start_line=3, end_line=3)]
        elif failure.startswith('edit_'):
            cs[0]['edit_files'] = {
                'edit_invalid': ['/private/' + SECRET],
                'edit_duplicate': [FILES[0], FILES[0]],
                'edit_scope': ['harness/unapproved.py'],
            }[failure]
        else:
            cs[0]['evidence'][0]['path'] = 'example.py'
        return cs

    lab.local_transform = transform
    lab.tick(0)
    failed = lab.report()['local_participation'][0]
    assert failed['status'] == 'failed' and failed['called'] is True
    assert failed['reason'] == reason
    original_detail = failed['failure_detail']
    entry = lab.state()['local_history'][0]
    assert entry['failure_detail'] == original_detail
    assert entry['stage_index'] == 0 and entry['owner_role'] == 'coordinator'
    assert entry['scan_id'] == failed['scan_id'] and entry['slot'] == failed['slot']
    assert lab.slots()[entry['slot']]['failure_detail'] == original_detail
    assert lab.state()['round']['drafts']['coordinator']['reason'] == reason
    assert lab.state()['feedback']['coordinator'][0]['specialist_reason'] == reason
    assert len(lab.local_requests) == 1
    result = lab.tick(1)
    owner = lab.report()['agents'][0]
    assert owner['status'] == 'succeeded' and owner['provider'] == lab.models['roles']['coordinator']['provider']
    assert len(lab.cloud_requests) == 1 and lab.calls() == 2
    assert 'Independently inspect' in lab.cloud_requests[0]['prompt']
    lab.hours(start=2, count=7)
    assert lab.report()['status'] == 'scanned'
    assert [c['role'] for c in lab.cloud_requests] == list(contract.ROLES)
    lab.tick(9)
    assert failed['reason'] == reason
    assert entry in lab.state()['local_history']
    assert lab.local_requests[-1]['feedback'][0]['specialist_failure_detail'] == original_detail
    assert loop.status(now=lab.clock(), selected=lab.selected)['local_history'][0] == entry
    public = lab.store.read('web/2026-10-15.json')
    assert public['agents'][0]['status'] == 'succeeded'
    assert public['status'] == 'scanned' and public['counts']['candidates'] == 3
    assert all(a['provider'] != 'mlx-vlm' for a in public['agents'])
    assert_private(lab.state())
    assert 'harness/unapproved.py' not in json.dumps(lab.state())
    assert 'local_participation' not in public and reason not in json.dumps(public)

@pytest.mark.parametrize('reason', [RAW + SECRET, {'raw': SECRET}, 'candidate_edit_files_typo',
                                 'timeout', 'config_permissions', True])
def test_private_local_reason_requires_adapter_provenance(lab, reason):
    def forged(role, paths, snapshots, **options):
        return {'provider': 'mlx-vlm', 'model': lab.local_config['model'],
                'stage': 'local_explorer', 'owner_role': role, 'status': 'failed',
                'called': True, 'reason': reason, 'candidates': [],
                'failure_detail': dict(diag.sanitize_detail(None), reason='timeout', cause='timeout',
                                       errno=True, exit_code=10 ** 100, http_status=SECRET)}

    lab.tick(0, local_runner=forged)
    failed = lab.report()['local_participation'][0]
    assert failed['reason'] == 'transport_failed'
    assert failed['failure_detail'] == diag.sanitize_detail(None)
    lab.tick(1)
    assert [r['role'] for r in lab.cloud_requests] == ['coordinator']
    assert lab.calls() == 2
    assert_private(lab.state())

def test_engine_revalidates_evidence_against_prepared_window_even_if_injected_runner_lies(lab):
    def forged(role, paths, snapshots, **options):
        return {'provider': 'mlx-vlm', 'model': lab.local_config['model'],
                'stage': 'local_explorer', 'owner_role': role, 'status': 'succeeded',
                'called': True, 'reason': 'ok',
                'read_windows': [{'path': FILES[0], 'start_line': 1, 'end_line': 6}],
                'candidates': [draft(FILES[0], 3, 4)]}

    lab.tick(0, local_runner=forged)
    local = lab.report()['local_participation'][0]
    assert local['status'] == 'failed'
    assert local['read_windows'] == [{'path': FILES[0], 'start_line': 1, 'end_line': 2}]
    assert lab.state()['round']['drafts']['coordinator']['candidates'] == []
    lab.tick(1)
    assert [r['role'] for r in lab.cloud_requests] == ['coordinator']

def test_all_empty_locals_allow_independent_specialists_and_empty_pool_review(lab):
    lab.local_transform = lambda user, cs: []
    lab.hours()
    report = lab.report()
    assert len(lab.events) == 9 and len(lab.cloud_requests) == 5
    assert report['review_complete'] is True and report['status'] == 'scanned'
    assert all(a['status'] == 'succeeded' for a in report['agents'])
    assert 'Independently evaluate coverage' in lab.cloud_requests[-1]['prompt']
    assert lab.state()['stage_index'] == 9
    lab.tick(9)
    assert lab.events[-1] == ('local_explorer', 'coordinator')

@pytest.mark.parametrize('metadata', [False, True])
def test_rate_limit_metadata_is_absent_from_persisted_proof_and_public_report(lab, metadata):
    lab.local_transform = lambda user, cs: []
    if metadata:
        lab.review_trace_transform = with_rate_limit_events
    lab.hours()
    scan = lab.report()
    assert scan['review_complete'] is True and coverage.validate(scan)
    assert len(lab.cloud_requests) == 5 and len(lab.events) == 9
    lab.store = imp.Store(lab.selected)
    persisted = lab.store.read('scans/' + scan['scan_id'] + '.json')
    assert persisted['source_review'] == scan['source_review']
    lab.tick(9)
    report = lab.store.read('days/2026-10-15.json')
    public = lab.store.read('web/2026-10-15.json')
    assert public['status'] == 'scanned'
    assert public['headline'] == '점검 완료 · 확인한 범위에서 제안 없음'
    assert public['counts']['eligible'] == 0
    for value in (scan, persisted, report, public):
        encoded = json.dumps(value)
        assert all(private not in encoded for private in (
            'PRIVATE_RATE_METADATA', 'private-session', 'notice-uuid', 'rate_limit_info', 'errorCode'))
    for rendered in (contract.render_html(public), contract.render_markdown(public)):
        assert 'PRIVATE_RATE_METADATA' not in rendered and 'private-session' not in rendered

@pytest.mark.parametrize('mode', [
    'no_read', 'self_claim', 'read_failed', 'wrong_range', 'trailing_lf', 'wrong_total', 'verified'])
def test_empty_pool_requires_real_bounded_owner_and_document_reads_after_restart(lab, mode):
    lab.local_transform = lambda user, cs: []
    lab.review_no_read = mode in ('no_read', 'self_claim')
    if mode == 'self_claim':
        def claim(role, result, response, options):
            if role == 'reviewer':
                result.update(read_files=list(FILES), source_review={'verified': True})
                response['documentation']['reason'] = '모든 파일을 읽었다는 모델의 자기 주장만 담은 설명입니다.'
                result['response'] = json.dumps(response)
            return result
        lab.cloud_transform = claim
    if mode in ('read_failed', 'wrong_range', 'trailing_lf', 'wrong_total', 'verified'):
        def damage(events):
            files = [event['tool_use_result']['file'] for event in events if event['type'] == 'user']
            assert files
            for file in files:
                assert file['content'] == (
                    'value_1 = 1\nvalue_2 = 2\nvalue_3 = 3\n'
                    'value_4 = 4\nvalue_5 = 5\nvalue_6 = 6')
                assert (file['startLine'], file['numLines'], file['totalLines']) == (1, 6, 7)
            if mode == 'read_failed':
                events[1]['message']['content'][0]['is_error'] = True
            elif mode == 'wrong_range':
                files[0]['startLine'] += 1
            elif mode == 'trailing_lf':
                files[0]['content'] += '\n'
            elif mode == 'wrong_total':
                files[0]['totalLines'] -= 1
            return events
        lab.review_trace_transform = damage
    lab.hours()
    scan = lab.report()
    assert scan['review_complete'] is (mode == 'verified')
    assert len(lab.cloud_requests) == 5 and len(lab.events) == 9
    lab.store = imp.Store(lab.selected)
    lab.tick(9)
    report = lab.store.read('days/2026-10-15.json')
    public = lab.store.read('web/2026-10-15.json')
    assert public['counts']['eligible'] == 0 and public['proposals'] == []
    if mode == 'verified':
        assert coverage.validate(scan)
        purposes = {p for w in scan['source_review']['plan'] for p in w['purposes']}
        assert set(contract.SPECIALIST_ROLES) | {'documentation'} <= purposes
        assert sum(w['size'] for w in scan['source_review']['plan']) <= coverage.MAX_SOURCE
        assert public['status'] == 'scanned'
        assert public['headline'] == '점검 완료 · 확인한 범위에서 제안 없음'
        assert '표본' in public['summary']
    else:
        assert public['status'] in ('partial', 'failed')
        assert '점검 미완료' in public['headline']
        assert report['review_complete'] is False
    for rendered in (contract.render_html(public), contract.render_markdown(public)):
        assert ('점검 미완료' in rendered) is (mode != 'verified')
    assert 'source_review' not in json.dumps(public)

@pytest.mark.parametrize('later', ['empty', 'failure', 'review_failure'])
def test_two_eligible_survive_later_round_zero_or_failure_with_original_authority(lab, later):
    def two(user, candidates):
        return [dict(candidates[0], title='다운로더 제안 ' + str(i)) for i in range(2)] if user['owner_role'] == 'downloader' else []
    lab.local_transform = two
    lab.hours(start=8)
    original = deepcopy(lab.report())
    assert len(original['proposals']) == 2
    lab.local_transform = lambda user, candidates: []
    if later != 'empty':
        def fail(role, result, response, options):
            if role == ('reviewer' if later == 'review_failure' else 'downloader'):
                result['status'] = 'failed'
            return result
        lab.cloud_transform = fail
    lab.hours(start=17)
    lab.store = imp.Store(lab.selected)
    lab.tick(33)
    report = lab.store.read('days/2026-10-16.json')
    public = lab.store.read('web/2026-10-16.json')
    assert public['counts']['eligible'] == 2 and len(public['proposals']) == 2
    assert {r['id'] for r in report['proposals']} == {r['id'] for r in original['proposals']}
    assert report['morning_aggregate'] == coverage.VERSION
    assert 'source_review' not in report and 'source_review_binding' not in report
    for record in report['proposals']:
        origin = report['retained_provenance'][record['id']]
        assert origin['scan_id'] == original['scan_id']
        assert origin['source_review_binding'] == original['source_review_binding']
        saved = lab.store.read('proposals/' + record['id'] + '.json')
        assert saved['scan_id'] == original['scan_id']
        assert imp._eligible(lab.store, record['id']) == record
        instruction = lab.root / 'explicit-instruction.txt'
        instruction.write_text('제안 ' + record['id'] + ' 승인', encoding='utf-8')
        instruction.chmod(0o600)
        imp.approve(record['id'], instruction, now=lab.clock(), selected=lab.selected)
        imp._authorization(lab.store, record['id'], lab.clock())
    if later != 'empty':
        assert public['status'] == 'partial'
        assert any(a['status'] == 'failed' for a in public['agents'])
    assert_private(public)
    assert all(k not in json.dumps(public) for k in ('source_review', 'retained_provenance', 'diagnostic', 'local_participation'))
    before = lab.store.path('web/2026-10-16.json').read_bytes()
    lab.tick(34)
    assert lab.store.path('web/2026-10-16.json').read_bytes() == before

@pytest.mark.parametrize('verdict', ['rejected', 'needs_evidence'])
def test_newer_explicit_verdict_overrides_eligible_and_never_rebinds_approval(lab, verdict):
    def stable(role, result, response, options):
        if role != 'reviewer':
            for candidate in response['candidates']:
                for item in candidate['evidence'] + candidate['benefit']['evidence']:
                    item.update(start_line=1, end_line=2)
            result['response'] = json.dumps(response)
        return result
    lab.cloud_transform = stable
    lab.hours(start=8)
    first = lab.report()
    pid = first['proposals'][0]['id']
    instruction = lab.root / 'explicit-instruction.txt'
    instruction.write_text('제안 ' + pid + ' 승인', encoding='utf-8')
    instruction.chmod(0o600)
    imp.approve(pid, instruction, now=lab.clock(), selected=lab.selected)
    approval_bytes = lab.store.path('approvals/' + pid + '.json').read_bytes()
    def reject(role, result, response, options):
        stable(role, result, response, options)
        if role == 'reviewer':
            for item in response['reviews']:
                item['verdict'] = verdict
                item['reason'] = '후속 독립 확인에서 효과 근거가 성립하지 않아 명시적으로 거절합니다.'
            result['response'] = json.dumps(response)
        return result
    lab.cloud_transform = reject
    lab.hours(start=17)
    lab.store = imp.Store(lab.selected)
    lab.tick(33)
    report = lab.store.read('days/2026-10-16.json')
    assert pid in {r['id'] for r in report['proposals']}
    assert all(r['review']['verdict'] == verdict for r in report['proposals'])
    assert lab.store.read('web/2026-10-16.json')['counts']['eligible'] == 0
    with pytest.raises(imp.ImprovementError):
        imp._authorization(lab.store, pid, lab.clock())
    assert lab.store.path('approvals/' + pid + '.json').read_bytes() == approval_bytes
    assert not lab.store.exists('claims/' + pid + '.json')

@pytest.mark.parametrize('damage', ['legacy', 'range', 'source_binding', 'scope_binding', 'protocol'])
def test_persisted_read_proof_is_revalidated_for_approve_and_morning(lab, damage):
    lab.hours()
    scan = lab.report()
    pid = scan['proposals'][0]['id']
    if damage == 'legacy':
        scan.pop('source_review')
    elif damage == 'range':
        scan['source_review']['plan'][0]['start_line'] += 1
    elif damage == 'source_binding':
        scan['source_review']['fingerprints_digest'] = '0' * 64
    elif damage == 'scope_binding':
        scan['scope_fingerprint']['sha256'] = '0' * 64
    elif damage == 'protocol':
        scan['source_review']['version'] = 'legacy-self-report'
    lab.store.write('scans/' + scan['scan_id'] + '.json', scan)
    lab.store = imp.Store(lab.selected)
    with pytest.raises(imp.ImprovementError,
                       match=r'^Independent source Read evidence is required\.$'):
        imp.approve(pid, lab.root / 'must-not-open.txt', now=lab.clock(), selected=lab.selected)
    lab.tick(9)
    assert lab.store.read('web/2026-10-15.json')['counts']['eligible'] == 0
    assert not lab.store.exists('approvals/' + pid + '.json')

def test_completed_index_duplicate_is_deduplicated_without_directory_discovery(lab, monkeypatch):
    lab.hours()
    state = lab.state()
    state['completed'] *= 2
    lab.store.write(loop.STATE_FILE, state)
    monkeypatch.setattr(Path, 'iterdir', forbidden)
    lab.tick(9)
    public = lab.store.read('web/2026-10-15.json')
    assert public['counts']['eligible'] == 4
    assert len({r['id'] for r in public['proposals']}) == len(public['proposals']) == 3

def test_completed_index_over_bound_fails_before_any_source_scan_read(lab, monkeypatch):
    lab.hours()
    state = lab.state()
    state['completed'] *= 33
    names = []
    original = lab.store.read
    def bounded(name):
        names.append(name)
        return original(name)
    monkeypatch.setattr(lab.store, 'read', bounded)
    report = state['round']['report']
    with lab.store.lock(), lab.store.lock(project=True):
        with pytest.raises(loop.LoopError, match='completed_index_invalid'):
            loop._freeze_morning(lab.store, state, START.replace(hour=9), lab.discovery,
                                 report['loop_dependencies'])
    assert not any(n.startswith('scans/') for n in names)

@pytest.mark.parametrize('changed', ['source', 'control', 'unknown'])
def test_retained_candidates_never_become_public_eligible_under_changed_dependencies(lab, changed):
    lab.hours()
    pid = lab.report()['proposals'][0]['id']
    if changed == 'source':
        (lab.root / 'AGENTS.md').write_text('changed source\n')
    elif changed == 'control':
        lab.config['daily_budget_usd'] = .9
        lab.save_loop()
    else:
        lab.local_path.write_text('{broken private configuration')
    lab.store = imp.Store(lab.selected)
    lab.tick(9)
    public = lab.store.read('web/2026-10-15.json')
    assert public['counts']['eligible'] == 0 and public['status'] != 'scanned'
    with pytest.raises((imp.ImprovementError, ValueError)):
        imp.approve(pid, lab.root / 'must-not-open.txt', now=lab.clock(), selected=lab.selected)

def test_refined_issue_same_draft_digest_and_review_reason_reach_next_actual_http_prompt(lab):
    lab.hours()
    report = lab.report()
    coordinator = report['proposals'][0]
    digest = lab.state()['round']['drafts']['coordinator']['draft_digest']
    assert coordinator['candidate']['issue'].startswith('담당자 보완: ')
    lab.store = imp.Store(lab.selected)
    lab.tick(9)
    sent = lab.local_requests[-1]
    feedback = sent['feedback'][0]
    assert feedback['candidate_id'] == coordinator['id']
    assert feedback['draft_digest'] == digest
    assert feedback['issue'] == coordinator['candidate']['issue']
    assert feedback['specialist_reason'] == coordinator['candidate']['issue']
    assert feedback['review_reason'] == REVIEW_REASON
    assert sent['sources'][0]['start_line'] == 3

def test_same_rejected_draft_error_is_sent_back_in_next_cycle(lab):
    def reject_owner(role, result, response, options):
        if role == 'coordinator':
            result['response'] = '{malformed ' + RAW + SECRET
        return result
    lab.cloud_transform = reject_owner
    lab.hours()
    digest = lab.state()['round']['drafts']['coordinator']['draft_digest']
    lab.tick(9)
    feedback = lab.local_requests[-1]['feedback'][0]
    assert feedback['draft_digest'] == digest
    assert feedback['specialist_reason'] == 'role_json_invalid'
    assert feedback['title'] == '로컬 coordinator 점검 후보'
    assert 'candidate_id' not in feedback
    assert_private(feedback)

def test_feedback_and_public_projection_redact_secrets_from_accepted_prose(lab):
    def sensitive_prose(role, result, response, options):
        if role == 'reviewer':
            for item in response['reviews']:
                item['reason'] += ' Bearer ' + SECRET + ' https://synthetic.invalid/private'
            result['response'] = json.dumps(response, ensure_ascii=False)
        return result

    lab.cloud_transform = sensitive_prose
    lab.hours()
    lab.tick(9)
    feedback = lab.local_requests[-1]['feedback'][0]
    assert REVIEW_REASON in feedback['review_reason']
    assert SECRET not in json.dumps(feedback) and 'https://synthetic.invalid' not in json.dumps(feedback)
    payload = lab.store.read('web/2026-10-15.json')
    assert SECRET not in json.dumps(payload) and 'https://synthetic.invalid' not in json.dumps(payload)
    contract.validate_web_report(payload)

@pytest.mark.parametrize('invalid', ['coverage', 'documentation'])
def test_incomplete_independent_review_never_leaves_any_eligible_proposal(lab, invalid):
    def corrupt(role, result, response, options):
        if role == 'reviewer':
            if invalid == 'coverage':
                response['reviews'].pop()
            else:
                del response['reviews'][0]['documentation']
            result['response'] = json.dumps(response, ensure_ascii=False)
        return result

    lab.cloud_transform = corrupt
    lab.hours()
    report = lab.report()
    assert report['review_complete'] is False and report['status'] == 'partial'
    for record in report['proposals']:
        assert 'review' not in record
        with pytest.raises(imp.ImprovementError):
            imp._eligible(lab.store, record['id'])
    lab.tick(9)
    assert lab.store.read('web/2026-10-15.json')['counts']['eligible'] == 0

def test_independently_rejected_candidate_is_reportable_but_never_approvable(lab):
    def reject(role, result, response, options):
        if role == 'reviewer':
            for item in response['reviews']:
                item['verdict'] = 'rejected'
            result['response'] = json.dumps(response, ensure_ascii=False)
        return result

    lab.cloud_transform = reject
    lab.hours()
    assert lab.report()['review_complete'] is True
    for record in lab.report()['proposals']:
        with pytest.raises(imp.ImprovementError):
            imp._eligible(lab.store, record['id'])
    lab.tick(9)
    public = lab.store.read('web/2026-10-15.json')
    assert public['counts']['candidates'] == 4 and public['counts']['eligible'] == 0

@pytest.mark.parametrize('change', ['scope', 'loop_config', 'local_config', 'agent_config', 'workflow_config'])
def test_control_change_invalidates_progress_but_preserves_completed_history(lab, change):
    lab.hours()
    old = deepcopy(lab.report())
    if change == 'scope':
        lab.scope.write_text('\n'.join(FILES[:-1]) + '\n', encoding='utf-8')
    elif change == 'loop_config':
        lab.config['daily_budget_usd'] = .9
        lab.save_loop()
    elif change == 'local_config':
        lab.local_config['temperature'] = .1
        lab.save_local()
    elif change == 'agent_config':
        lab.models['roles']['coordinator']['effort'] = 'medium'
    else:
        lab.policy['max_rounds'] = 1
    local_runner = lab.local
    if change == 'scope':
        def local_runner(role, paths, snapshots, **options):
            lab.active_owner = role
            return local_model.run(role, paths, snapshots, transport=lab.local_http, **options)
    lab.tick(9, local_runner=local_runner)
    state = lab.state()
    assert state['completed'] and state['completed'][-1]['scan_id'] == old['scan_id']
    assert state['round']['report']['scan_id'] != old['scan_id']
    assert state['round']['report']['proposals'] == []
    assert state['round']['report']['review_complete'] is False
    assert lab.local_requests[-1]['feedback'] == []
    assert lab.local_requests[-1]['sources'][0]['start_line'] == 1
    invalidated = lab.store.read('loop/invalidated/' + old['scan_id'] + '.json')
    assert invalidated['review_complete'] is False and 'dependencies_changed' in invalidated['errors']
    assert all('review' not in r for r in invalidated['proposals'])
    assert lab.store.read('scans/' + old['scan_id'] + '.json')['review_complete'] is True
    morning = lab.store.read('days/2026-10-15.json')
    assert morning['proposals'] == [] and morning['review_complete'] is False

def test_source_change_during_call_completes_snapshot_review_but_is_stale(lab):
    lab.hours(count=8)
    def mutate(role, result, response, options):
        (lab.root / FILES[0]).write_text('changed = 1\nchanged = 2\n', encoding='utf-8')
        return result
    lab.cloud_transform = mutate
    lab.tick(8)
    report = lab.report()
    assert report['review_complete'] is True
    assert report['current_fresh_at_last_tick'] is False
    assert all('review' in r for r in report['proposals'])
    assert lab.state()['completed'][-1]['scan_id'] == report['scan_id']
    with pytest.raises(loop.LoopError, match='loop_dependencies_changed'):
        loop.validate_scan_freshness(report, selected=lab.selected)

def test_morning_boundary_freezes_once_then_later_research_cannot_regenerate(lab):
    priority = {'coordinator': 'low', 'downloader': 'high', 'parser': 'medium', 'django': 'high'}
    lab.local_transform = lambda user, cs: [dict(c, priority=priority[user['owner_role']]) for c in cs]
    lab.hours()
    before = len(lab.events)
    assert lab.tick(8, 59, 59)['reason'] == 'slot_already_claimed'
    assert not lab.store.exists('days/2026-10-15.json')
    result = lab.tick(9)
    assert len(lab.events) == before + 1
    report = lab.store.read('days/2026-10-15.json')
    assert report['generated_at'] == lab.clock().isoformat() and report['date'] == '2026-10-15'
    assert report['review_complete'] is True and report['status'] == 'scanned'
    assert report['report_window'] == {'start': '2026-10-14T09:00:00+09:00',
                                      'end': '2026-10-15T09:00:00+09:00'}
    payload = lab.store.read('web/2026-10-15.json')
    contract.validate_web_report(payload)
    assert contract.verify_web_digest(payload, '2026-10-15')
    assert payload['counts'] == {'candidates': 4, 'reported': 3, 'additional_candidates': 1, 'eligible': 4}
    ranked = sorted(report['proposals'], key=lambda r: (
        {'high': 0, 'medium': 1, 'low': 2}[r['candidate']['priority']], r['id']))
    assert [p['id'] for p in payload['proposals']] == [r['id'] for r in ranked[:3]]
    frozen = {n: lab.store.path(n).read_bytes() for n in ('days/2026-10-15.json',
               'web/2026-10-15.json', 'web/2026-10-15.html', 'web/2026-10-15.md')}
    assert result['next_role'] == 'coordinator' and result['next_stage'] == 'specialist'
    lab.hours(start=10, count=9)
    for name, body in frozen.items():
        assert lab.store.path(name).read_bytes() == body
    assert len(lab.state()['completed']) == 2

def test_catchup_freezes_only_current_date_without_historical_models_or_reports(lab):
    lab.tick(0)
    before = len(lab.events)
    lab.tick(24 * 4 + 14)
    assert len(lab.events) == before + 1
    days = sorted(p.name for p in lab.store.path('days').iterdir())
    assert days == ['2026-10-19.json']
    report = lab.store.read('days/2026-10-19.json')
    assert report['status'] == 'failed' and report['proposals'] == []
    assert all(a['status'] == 'not_called' for a in report['agents'])
    assert report['local_participation'] == []

def test_latest_review_in_half_open_window_selected_and_priority_projection_is_bounded(lab):
    lab.hours(start=8, count=9)
    first = lab.state()['completed'][-1]['scan_id']
    lab.hours(start=17, count=9)
    second = lab.state()['completed'][-1]['scan_id']
    assert second != first
    lab.tick(33)
    report = lab.store.read('days/2026-10-16.json')
    assert report['reviewed_scan_id'] == second
    assert report['date'] == '2026-10-16' and report['review_complete'] is True
    assert len({r['id'] for r in report['proposals']}) == len(report['proposals']) <= 8

def test_review_finishing_exactly_nine_is_excluded_from_that_mornings_report(lab):
    lab.hours(start=1, count=9)
    report = lab.store.read('days/2026-10-15.json')
    assert report['review_complete'] is False and report['proposals'] == []
    assert lab.report()['review_complete'] is True
    lab.tick(10)
    assert lab.store.read('days/2026-10-15.json') == report

def test_prior_window_owners_not_presented_as_current_success(lab):
    lab.hours(count=8)
    lab.tick(24 + 8)
    lab.tick(24 + 9)
    report = lab.store.read('days/2026-10-16.json')
    assert report['review_complete'] is True and report['status'] == 'partial'
    assert all(a['status'] == 'not_called' for a in report['agents'][:-1])
    assert report['agents'][-1]['status'] == 'succeeded'
    assert all(a['status'] == 'succeeded' for a in report['reviewed_agents'])
    assert report['local_participation'] == []

def delivered(lab):
    def publisher(date, *, selected):
        assert selected is lab.selected
        with imp.Store(selected).lock(), imp.Store(selected).lock(project=True):
            payload = lab.store.read('web/' + date + '.json')
        return {'status': 'delivered', 'date': date, 'digest': payload['digest']}
    return publisher

def test_before_nine_tick_and_explicit_publish_cannot_deliver(lab):
    result = lab.tick(8, 59, 59, publisher=forbidden)
    assert result['publication']['status'] == 'before_report_time'
    assert not lab.store.exists('days/2026-10-15.json')
    before = len(lab.events)
    result = loop.publish(now=lab.clock(), selected=lab.selected, publisher=forbidden, reconcile=True)
    assert result['status'] == 'before_report_time' and len(lab.events) == before

def test_publisher_outside_both_locks_and_success_never_sent_twice(lab):
    lab.hours()
    attempts = []
    publisher = delivered(lab)
    def send(date, **options):
        attempts.append(date)
        return publisher(date, **options)
    result = lab.tick(9, publisher=send)
    assert result['publication']['status'] == 'delivered'
    lab.tick(10, publisher=send)
    loop.publish(now=lab.clock(), selected=lab.selected, publisher=send, reconcile=True)
    assert attempts == ['2026-10-15']

@pytest.mark.parametrize('failure', ['failed_result', 'exception', 'wrong_digest', 'power_loss'])
def test_unknown_delivery_never_auto_retries_and_explicit_reconcile_uses_same_digest(lab, failure):
    lab.tick(9)
    payload = lab.store.path('web/2026-10-15.json').read_bytes()
    digest = lab.store.read('web/2026-10-15.json')['digest']
    attempts = []

    def failed(date, **options):
        attempts.append((date, lab.store.read('web/' + date + '.json')['digest']))
        if failure == 'power_loss':
            raise PowerLoss()
        if failure == 'exception':
            raise TimeoutError(RAW + SECRET)
        return {'date': date, 'digest': '0' * 64 if failure == 'wrong_digest' else digest,
                'status': 'delivered' if failure == 'wrong_digest' else 'delivery_failed'}

    if failure == 'power_loss':
        with pytest.raises(PowerLoss):
            loop.publish(now=lab.clock(), selected=lab.selected, publisher=failed)
        assert lab.store.read(loop._publication_name('2026-10-15'))['status'] == 'sending'
    else:
        result = loop.publish(now=lab.clock(), selected=lab.selected, publisher=failed)
        assert result['status'] == 'publication_unknown'
    lab.tick(10, publisher=failed)
    assert len(attempts) == 1
    assert lab.store.read(loop._publication_name('2026-10-15'))['status'] == 'publication_unknown'
    result = loop.publish(now=lab.clock(), selected=lab.selected, publisher=delivered(lab), reconcile=True)
    assert result['status'] == 'delivered' and result['digest'] == digest
    assert lab.store.path('web/2026-10-15.json').read_bytes() == payload
    assert SECRET not in json.dumps(lab.store.read(loop._publication_name('2026-10-15')))

def test_nested_reconciliation_while_sender_active_cannot_duplicate_callback(lab):
    lab.tick(9)
    nested = []
    def publisher(date, **options):
        with pytest.raises(loop.LoopError, match='publication_busy'):
            loop.publish(now=lab.clock(), selected=lab.selected,
                         publisher=lambda *args, **kw: nested.append(True), reconcile=True)
        return delivered(lab)(date, **options)
    assert loop.publish(now=lab.clock(), selected=lab.selected, publisher=publisher)['status'] == 'delivered'
    assert nested == []

def test_delivery_success_journal_repairs_sender_crash_without_second_http(lab):
    lab.tick(9)
    digest = lab.store.read('web/2026-10-15.json')['digest']
    def sent_then_crashed(date, **options):
        with lab.store.lock():
            lab.store.write('delivery/' + date + '.json', {'date': date, 'digest': digest, 'status': 'delivered'})
        raise PowerLoss()
    with pytest.raises(PowerLoss):
        loop.publish(now=lab.clock(), selected=lab.selected, publisher=sent_then_crashed)
    result = loop.publish(now=lab.clock(), selected=lab.selected, publisher=forbidden, reconcile=True)
    assert result['status'] == 'delivered' and result['digest'] == digest

def test_prepared_report_recovers_after_crash_using_frozen_journal_without_models(lab, monkeypatch):
    lab.hours()
    actual = imp.Store.write
    def crash_on_day(store, name, value):
        if name == 'days/2026-10-15.json':
            raise PowerLoss()
        return actual(store, name, value)
    with monkeypatch.context() as patch:
        patch.setattr(imp.Store, 'write', crash_on_day)
        with pytest.raises(PowerLoss):
            lab.tick(9)
    journal = lab.store.read(loop._publication_name('2026-10-15'))
    assert journal['status'] == 'prepared' and not lab.store.exists('days/2026-10-15.json')
    before = len(lab.events)
    result = loop.publish(now=lab.clock(), selected=lab.selected, publisher=delivered(lab))
    assert result['status'] == 'delivered' and result['digest'] == journal['digest']
    assert lab.store.read('days/2026-10-15.json') == journal['report']
    assert len(lab.events) == before

def test_reconciliation_refuses_mutated_digest_instead_of_sending_new_report(lab):
    lab.tick(9)
    payload = lab.store.read('web/2026-10-15.json')
    payload['summary'] = '다른 내용으로 바뀐 합성 보고입니다.'
    payload.pop('digest')
    payload['digest'] = contract.digest(payload)
    lab.store.write('web/2026-10-15.json', payload)
    with pytest.raises(loop.LoopError, match='publication_digest_changed'):
        loop.publish(now=lab.clock(), selected=lab.selected, publisher=forbidden, reconcile=True)

def test_actual_delivery_api_can_acquire_its_lock_and_posts_only_public_schema(lab, monkeypatch):
    calls = []
    payloads = []
    actual_delivery = imp.deliver_report
    monkeypatch.setattr(imp, '_inbox_config', lambda path: ('https://synthetic.invalid', SECRET))
    def http(method, origin, path, headers, body, timeout, max_bytes):
        assert origin == 'https://synthetic.invalid'
        assert headers['OAI-Sites-Authorization'] == 'Bearer ' + SECRET
        assert timeout <= 20 and max_bytes <= 262144
        calls.append((method, path))
        if method == 'POST':
            payloads.append(contract.validate_web_report(json.loads(body)))
            return 200, b'{}'
        return 200, encode(payloads[-1])
    def publisher(date, *, selected):
        return actual_delivery(date, selected=selected, transport=http)
    lab.hours()
    result = lab.tick(9, publisher=publisher)
    assert result['publication']['status'] == 'delivered'
    assert calls == [('POST', '/api/reports'), ('GET', '/api/reports/2026-10-15')]
    lab.tick(10, publisher=publisher)
    assert len(calls) == 2
    public = json.dumps(payloads, ensure_ascii=False)
    for sensitive in (SECRET, RAW, str(lab.root), lab.local_config['model'],
                      lab.local_config['endpoint'], 'claude_spent_usd', 'local_participation',
                      'loop_dependencies', 'value_1 = 1'):
        assert sensitive not in public
    assert all(set(a) == {'role', 'provider', 'model', 'status'} for a in payloads[0]['agents'])

def test_operating_cli_tick_reaches_default_publisher_and_no_deliver_is_explicit(lab, monkeypatch, capsys):
    actual_tick, actual_delivery = loop.tick, imp.deliver_report
    calls, payloads = [], []
    monkeypatch.setattr(imp, '_inbox_config', lambda path: ('https://synthetic.invalid', SECRET))
    def transport(method, origin, path, headers, body, timeout, max_bytes):
        calls.append((method, path))
        if method == 'POST':
            payloads.append(json.loads(body))
            return 200, b'{}'
        return 200, encode(payloads[-1])
    def safe_default_delivery(date, *, selected):
        return actual_delivery(date, selected=selected, transport=transport)
    def injected_tick(**options):
        return actual_tick(selected=lab.selected, clock=lab.clock, keys={'ZAI_API_KEY': SECRET},
                           runner=lab.cloud, local_runner=lab.local, quota_transport=lab.quota, **options)
    monkeypatch.setattr(imp, 'deliver_report', safe_default_delivery)
    monkeypatch.setattr(imp, 'http_transport', transport)
    monkeypatch.setattr(loop, 'tick', injected_tick)
    lab.clock.at(9)
    assert loop.main(['tick']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['publication']['status'] == result['health_publication']['status'] == 'delivered'
    assert calls == [('POST', '/api/reports'), ('GET', '/api/reports/2026-10-15'),
                     ('POST', '/api/health'), ('GET', '/api/health')]
    lab.clock.at(10)
    loop.main(['tick', '--no-deliver'])
    result = json.loads(capsys.readouterr().out)
    assert 'publication' not in result and 'health_publication' not in result and len(calls) == 4

def test_status_is_read_only_and_korean_status_explains_next_role_budget_and_report(lab):
    result = loop.status(now=START, selected=lab.selected)
    assert not lab.store.exists(loop.STATE_FILE) and lab.events == []
    assert result['claude_remaining_estimated_usd'] is None
    lab.hours()
    before = lab.store.path(loop.STATE_FILE).read_bytes()
    result = loop.status(now=lab.clock(), selected=lab.selected)
    assert result['claude_remaining_estimated_usd'] == approx(.96)
    assert result['next_role'] == 'coordinator' and result['next_stage'] == 'local_explorer'
    assert result['last_review_at'] == lab.clock().isoformat()
    assert result['next_report_at'] == '2026-10-15T09:00:00+09:00'
    for word in ('추정', '보류', '다음', '검토', '보고'):
        assert word in result['message_ko']
    assert lab.store.path(loop.STATE_FILE).read_bytes() == before

@pytest.mark.parametrize('guard', ['TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY'])
def test_leaf_guard_denies_every_loop_entrypoint(lab, monkeypatch, guard):
    monkeypatch.setenv(guard, '1')
    monkeypatch.setattr(loop, 'load_config', forbidden)
    monkeypatch.setattr(agent_models, 'load_keys', forbidden)
    for action in (loop.tick, loop.status, loop.publish):
        with pytest.raises(imp.ImprovementError):
            action(now=START, selected=lab.selected)
    assert lab.events == [] and not lab.store.exists(loop.STATE_FILE)

def test_tick_preserves_existing_human_state_and_never_grants_unattended_authority(lab, monkeypatch):
    lab.hours()
    pid = lab.report()['proposals'][0]['id']
    originals = {}
    for directory in ('decisions', 'approvals', 'claims', 'executions'):
        name = directory + '/' + pid + '.json'
        lab.store.write(name, {'sentinel': 'existing human record', 'proposal_id': pid})
        originals[name] = lab.store.path(name).read_bytes()
    monkeypatch.setenv('TAVERN_IMPROVEMENT_UNATTENDED', '1')
    lab.tick(9)
    for name, body in originals.items():
        assert lab.store.path(name).read_bytes() == body
    for action in (lambda: imp.approve(pid, lab.root / 'nonexistent.txt', selected=lab.selected),
                   lambda: imp.execute(pid, selected=lab.selected, executor=forbidden)):
        with pytest.raises(imp.ImprovementError, match='Unattended'):
            action()

def test_reported_proposal_remains_eligible_through_original_api_but_execute_needs_approval(lab):
    lab.hours()
    lab.tick(9)
    report = lab.store.read('days/2026-10-15.json')
    for record in report['proposals']:
        assert imp._eligible(lab.store, record['id']) == record
        imp._fresh(record, lab.store)
        with pytest.raises((imp.ImprovementError, FileNotFoundError)):
            imp.execute(record['id'], now=lab.clock(), selected=lab.selected, executor=forbidden)
        assert not lab.store.exists('claims/' + record['id'] + '.json')

def test_exploration_budget_stop_does_not_gate_explicit_human_approval(lab):
    lab.hours()
    record = lab.report()['proposals'][0]
    state = lab.state()
    state['days']['2026-10-15'].update(claude_spent_usd=1, stopped=True,
                                      stop_reason='daily_budget_overrun')
    lab.store.write(loop.STATE_FILE, state)
    instruction = lab.instruction(record)
    result = imp.approve(record['id'], instruction, now=lab.clock(), selected=lab.selected)
    assert result['status'] == 'approved'
    checked, approval = imp._authorization(lab.store, record['id'], lab.clock())
    assert checked == record and approval['consumption'] == 'unconsumed'
    assert lab.spent() == 1 and len(lab.events) == 9

@pytest.mark.parametrize('dependency', ['loop', 'local'])
def test_original_approval_api_rejects_changed_loop_dependencies(lab, dependency):
    """Task 6 integration contract: ordinary approval must invoke loop freshness."""
    lab.hours()
    record = lab.report()['proposals'][0]
    if dependency == 'loop':
        lab.config['daily_budget_usd'] = .9
        lab.save_loop()
    else:
        lab.local_config['temperature'] = .1
        lab.save_local()
    instruction = lab.instruction(record)
    with pytest.raises(imp.ImprovementError):
        imp.approve(record['id'], instruction, now=lab.clock(), selected=lab.selected)
    assert not lab.store.exists('approvals/' + record['id'] + '.json')

def test_loop_authorization_context_binds_controls_and_legacy_stays_unbound(lab):
    lab.hours()
    report = lab.report()
    assert loop.authorization_context(report) == contract.digest({
        'dependencies': report['loop_dependencies'], 'scan_id': report['scan_id'],
        'source_review_binding': report['source_review_binding']})
    assert loop.authorization_context({'scan_id': 'legacy'}) is None
    with pytest.raises(loop.LoopError, match='loop_dependencies_missing'):
        loop.authorization_context({'loop_engine': loop.STATE_VERSION})
    loop.validate_scan_freshness(report, selected=lab.selected)
    lab.local_config['temperature'] = .1
    lab.save_local()
    with pytest.raises(loop.LoopError, match='loop_dependencies_changed'):
        loop.validate_scan_freshness(report, selected=lab.selected)

def test_old_signed_approval_cannot_rebind_identical_proposal_after_control_change(lab):
    """Fresh rediscovery alone must not silently renew an older authorization."""
    lab.hours()
    report = lab.report()
    record = report['proposals'][0]
    instruction = lab.instruction(record)
    imp.approve(record['id'], instruction, now=lab.clock(), selected=lab.selected)
    saved_approval = lab.store.path('approvals/' + record['id'] + '.json').read_bytes()
    lab.config['daily_budget_usd'] = .9
    lab.save_loop()
    lab.hours(start=9, count=9)
    new = lab.store.read('proposals/' + record['id'] + '.json')
    assert new['proposal'] == record and new['scan_id'] != report['scan_id']
    assert lab.store.path('approvals/' + record['id'] + '.json').read_bytes() == saved_approval
    with pytest.raises(imp.ImprovementError):
        imp._authorization(lab.store, record['id'], lab.clock())

def test_v1_runtime_config_pauses_without_conversion_or_model_call(lab):
    lab.local_config.update(version='local-model-config-v1', provider='mlx-lm', api_model='default_model')
    lab.save_local()
    original = lab.local_path.read_bytes()
    result = lab.tick(0, local_runner=forbidden, runner=forbidden, quota_transport=forbidden)
    assert result['status'] == 'paused' and result['reason'] == 'config_invalid'
    assert lab.calls() == 0 and lab.events == []
    assert lab.local_path.read_bytes() == original

def test_v2_migration_invalidates_legacy_loop_fingerprint_and_authorization_context(lab):
    lab.hours()
    state = lab.state()
    old = state['round']['report']
    legacy = dict(lab.local_config, version='local-model-config-v1', provider='mlx-lm', api_model='default_model')
    old['loop_dependencies']['local_config_fingerprint'] = contract.digest(legacy)
    coverage.attach(old, old['source_review'])
    old_context = loop.authorization_context(old)
    state['dependency_digest'] = contract.digest(old['loop_dependencies'])
    lab.store.write(loop.STATE_FILE, state)
    with pytest.raises(loop.LoopError, match='loop_dependencies_changed'):
        loop.validate_scan_freshness(old, selected=lab.selected)
    lab.tick(9)
    current = lab.report()
    assert current['scan_id'] != old['scan_id']
    with pytest.raises(ValueError, match='source_review_unverified'):
        loop.authorization_context(current)
    assert current['loop_dependencies']['local_config_fingerprint'] == local_model.config_digest(lab.local_config)
    assert current['proposals'] == [] and current['review_complete'] is False
    assert lab.local_requests[-1]['sources'][0]['start_line'] == 1
    assert lab.local_requests[-1]['feedback'] == []
    assert lab.store.exists('loop/invalidated/' + old['scan_id'] + '.json')

def test_interrupted_pre_v2_attempt_keeps_journaled_provider_without_replay(lab):
    def crash(*args, **kwargs):
        raise PowerLoss()
    with pytest.raises(PowerLoss):
        lab.tick(0, local_runner=crash)
    state = lab.state()
    state['inflight']['provider'] = 'mlx-lm'
    lab.store.write(loop.STATE_FILE, state)
    lab.tick(1)
    entry = lab.report()['local_participation'][0]
    assert entry['provider'] == 'mlx-lm' and entry['reason'] == 'interrupted_unknown'
    assert lab.calls() == 2 and lab.local_requests == []
    assert [r['role'] for r in lab.cloud_requests] == ['coordinator']
    assert lab.state()['stage_index'] == 2

@pytest.mark.parametrize('provider', ['mlx-lm', 'other-provider'])
def test_loop_refuses_local_runner_with_non_native_provider(lab, provider):
    def forged(role, paths, snapshots, **options):
        return {'provider': provider, 'model': lab.local_config['model'],
                'stage': 'local_explorer', 'owner_role': role, 'status': 'succeeded',
                'called': True, 'reason': RAW + SECRET, 'candidates': [draft(FILES[0], 1, 2)]}
    lab.tick(0, local_runner=forged)
    entry = lab.report()['local_participation'][0]
    assert entry['provider'] == 'mlx-vlm' and entry['reason'] == 'local_response_invalid'
    lab.tick(1)
    assert [r['role'] for r in lab.cloud_requests] == ['coordinator']
    assert_private(lab.state())

def test_saved_local_failure_survives_recovery(lab):
    pending = {}
    def invalid(user, candidates):
        pending.update(lab.state()['inflight'])
        candidates[0]['evidence'][0]['start_line'] = True
        return candidates
    lab.local_transform = invalid
    lab.tick(0)
    state = lab.state()
    failed = state['round']['report']['local_participation'][0]
    saved = deepcopy(state['round']['drafts']['coordinator'])
    state.update(inflight=pending, stage_index=0)
    lab.store.write(loop.STATE_FILE, state)  # Saved-result checkpoint.
    lab.store = imp.Store(lab.selected)
    assert lab.tick(0, 1)['reason'] == 'slot_already_claimed'
    state = lab.state()
    assert lab.calls() == 1 and len(lab.events) == 1
    assert state['round']['drafts']['coordinator'] == saved
    assert state['feedback']['coordinator'][0]['specialist_reason'] == failed['reason']
    for key in ('reason', 'failure_detail', 'call_started_at', 'call_finished_at', 'finished_at'):
        assert state['local_history'][0][key] == lab.slots()[failed['slot']][key] == failed[key]

def test_loop_telemetry_boundary_is_strict_bounded_and_backward_compatible():
    from harness.test_agent_telemetry import sample
    prior = {'role': 'downloader', 'provider': 'zai', 'model': 'fixture', 'status': 'failed'}
    assert 'telemetry' not in loop._safe_participation(prior)
    injected = sample()
    injected['secret'] = SECRET
    injected['requests'][0]['prompt'] = RAW
    injected['request_work'] = {'raw': SECRET}
    safe = loop._safe_participation(dict(prior, telemetry=injected))
    assert safe['telemetry']['logical_requests_observed'] == 1
    assert_private(safe)
    assert 'telemetry' not in loop._safe_participation(dict(prior, telemetry={'version': 'unknown'}))
    assert 'telemetry' not in loop._safe_participation(dict(prior, provider='codex', telemetry=injected))
    injected['tools'] = [{'category': SECRET}]
    assert 'telemetry' not in loop._safe_participation(dict(prior, telemetry=injected))

@pytest.mark.parametrize('failure', ['none', 'cli', 'contract', 'malformed', 'truncated'])
def test_hourly_scan_retains_partial_glm_telemetry_without_public_change(lab, failure):
    from harness.test_agent_telemetry import sample

    def transform(role, result, response, options):
        if role == 'downloader':
            result['telemetry'] = sample()
            result['telemetry']['secret'] = SECRET
            result['telemetry']['outcome'] = 'success'
            if failure == 'cli':
                result['status'] = 'failed'
                result['telemetry']['outcome'] = 'timeout'
            elif failure == 'contract':
                result['response'] = '{"invalid":true}'
            elif failure == 'malformed':
                result['response'] = '{broken ' + RAW + SECRET
            elif failure == 'truncated':
                result['response'] = 'x' * 100000
        return result
    lab.cloud_transform = transform
    lab.hours()
    report = lab.report()
    agent = next(a for a in report['agents'] if a['role'] == 'downloader')
    assert agent['status'] == ('succeeded' if failure == 'none' else 'failed')
    assert agent['telemetry']['logical_requests_observed'] == 1
    if failure == 'none':
        assert 'reason' not in agent and 'error_type' not in agent
    else:
        assert agent['reason'] == {'cli': 'role_execution_failed',
                                   'contract': 'candidate_invalid',
                                   'malformed': 'role_json_invalid',
                                   'truncated': 'role_json_invalid'}[failure]
        assert agent['telemetry']['outcome'] == ('timeout' if failure == 'cli' else 'success')
    assert SECRET not in json.dumps(agent) and 'result' not in agent
    saved = lab.store.read('scans/' + report['scan_id'] + '.json')
    assert saved['agents'][1]['telemetry'] == agent['telemetry']
    without = deepcopy(report)
    for item in without['agents']:
        item.pop('telemetry', None)
    assert contract.canonical_json(contract.build_web_report(report)) == contract.canonical_json(
        contract.build_web_report(without))

@pytest.mark.parametrize('role,failure,reason', [
    ('coordinator', 'malformed', 'role_json_invalid'),
    ('downloader', 'malformed', 'role_json_invalid'),
    ('coordinator', 'edit_type', 'candidate_edit_files_invalid'),
    ('coordinator', 'edit_duplicate', 'candidate_edit_files_duplicate'),
    ('coordinator', 'edit_scope', 'candidate_edit_files_outside_scope'),
    ('coordinator', 'candidate', 'candidate_invalid'),
    ('coordinator', 'context_content', 'role_context_changed'),
    ('coordinator', 'context_mode', 'role_context_changed'),
    ('coordinator', 'identity', 'role_identity_mismatch'),
    ('coordinator', 'envelope', 'role_result_invalid'),
    ('coordinator', 'execution_status', 'role_execution_failed'),
    ('coordinator', 'execution_exception', 'role_execution_failed'),
    ('coordinator', 'interrupt', 'role_interrupted'),
    ('reviewer', 'review', 'review_invalid'),
    ('reviewer', 'malformed', 'role_json_invalid'),
    ('reviewer', 'identity', 'role_identity_mismatch'),
    ('reviewer', 'context_content', 'role_context_changed'),
    ('reviewer', 'execution_status', 'role_execution_failed'),
    ('reviewer', 'execution_exception', 'role_execution_failed'),
    ('reviewer', 'interrupt', 'role_interrupted'),
])
def test_actual_ticks_keep_private_failure_through_next_round_without_public_digest_change(
        lab, role, failure, reason):
    original = (lab.root / FILES[0]).read_bytes()
    private_path = '/private/synthetic-provider-response'

    def corrupt(actual_role, result, response, options):
        if actual_role != role:
            return result
        result.update(reason='candidate_edit_files_duplicate', stage=RAW + SECRET,
                      field=private_path, error_type=RAW + SECRET,
                      diagnostics={'reason': 'role_interrupted', 'raw': RAW + SECRET})
        if failure == 'malformed':
            result['response'] = '{broken ' + RAW + SECRET + private_path
        elif failure.startswith('edit_'):
            response['candidates'][0]['edit_files'] = {
                'edit_type': True,
                'edit_duplicate': [FILES[0], FILES[0]],
                'edit_scope': ['harness/unapproved.py'],
            }[failure]
            result['response'] = json.dumps(response)
        elif failure == 'candidate':
            response['candidates'][0]['evidence'][0]['start_line'] = True
            result['response'] = json.dumps(response)
        elif failure == 'review':
            response['reviews'] = []
            result['response'] = json.dumps(response)
        elif failure.startswith('context_'):
            target = options['workspace'] / FILES[0]
            target.chmod(0o600)
            if failure == 'context_content':
                target.write_text(RAW + SECRET)
                target.chmod(0o400)
        elif failure == 'identity':
            result['model'] = 'unexpected-synthetic-model'
        elif failure == 'envelope':
            return [RAW + SECRET]
        elif failure == 'execution_status':
            result['status'] = RAW + SECRET
        elif failure == 'execution_exception':
            error = type(RAW + SECRET, (RuntimeError,), {})(private_path + SECRET)
            error.reason = 'candidate_edit_files_duplicate'
            raise error
        elif failure == 'interrupt':
            raise KeyboardInterrupt(RAW + SECRET + private_path)
        return result

    lab.cloud_transform = corrupt
    lab.hours()
    state = lab.state()
    report = state['round']['report']
    agent = next(item for item in report['agents'] if item['role'] == role)
    assert agent['status'] != 'succeeded' and agent['reason'] == reason
    detail = agent['failure_detail']
    index = 8 if role == 'reviewer' else 2 * contract.SPECIALIST_ROLES.index(role) + 1
    attempt = next(e for e in state['participation'] if e['stage_index'] == index)
    slot = state['days']['2026-10-15']['slots'][attempt['slot']]
    assert slot['failure_detail'] == attempt['failure_detail'] == detail
    assert attempt['scan_id'] == agent['scan_id'] == report['scan_id']
    assert slot['owner_role'] == agent['owner_role'] == role
    assert attempt['started_at'] == agent['started_at']
    assert attempt['finished_at'] == agent['finished_at']
    status = loop.status(now=lab.clock(), selected=lab.selected)
    assert next(e for e in status['participation'] if e['stage_index'] == index) == attempt
    if failure == 'candidate':
        assert (detail['field'], detail['rule']) == ('evidence.start_line', 'type')
    if failure == 'identity':
        assert detail['cause'] == 'identity_mismatch'
    if failure == 'execution_exception':
        assert detail['cause'] == 'unavailable'
    assert 'error_type' in agent and 'result' not in agent
    if failure == 'execution_exception':
        assert agent['error_type'] == 'Exception'
    if failure == 'interrupt':
        assert agent['interrupted'] is True and agent['error_type'] == 'KeyboardInterrupt'
    saved = lab.store.read('scans/' + report['scan_id'] + '.json')
    assert next(item for item in saved['agents'] if item['role'] == role) == agent
    assert report['review_complete'] is (role != 'reviewer')
    if role == 'reviewer':
        assert all('review' not in record for record in report['proposals'])
    else:
        assert all(record['candidate']['edit_files'] != [FILES[contract.SPECIALIST_ROLES.index(role)]]
                   for record in report['proposals'])
    assert state['stage_index'] == 9 and state['inflight'] is None
    assert lab.calls() == 9 and len(lab.events) == 9
    assert lab.spent() == approx(.2 if role == 'reviewer' else .04)
    if role == 'reviewer':
        assert lab.slots()['2026-10-15T08']['cost_status'] in (
            'reservation_consumed_failed', 'reservation_consumed_unknown')
    assert all(not entry['options']['workspace'].exists() for entry in lab.cloud_requests)
    assert 'TAVERN_IMPROVEMENT_DISCOVERY' not in os.environ
    assert (lab.root / FILES[0]).read_bytes() == original
    for sensitive in (SECRET, RAW, private_path, 'harness/unapproved.py'):
        assert sensitive not in json.dumps(state)

    lab.store = imp.Store(lab.selected)
    next_hour = 11 if role == 'downloader' else 9
    lab.hours(start=9, count=next_hour - 8)
    owner = 'coordinator' if role == 'reviewer' else role
    request = next(item for item in reversed(lab.local_requests) if item['owner_role'] == owner)
    key = 'review_reason' if role == 'reviewer' else 'specialist_reason'
    assert request['feedback'][0][key] == reason
    detail_key = 'review_failure_detail' if role == 'reviewer' else 'specialist_failure_detail'
    assert request['feedback'][0][detail_key] == detail
    assert attempt in lab.state()['participation']
    assert 'draft_digest' in request['feedback'][0]
    assert lab.spent() == approx(.2 if role == 'reviewer' else .04)
    public = lab.store.read('web/2026-10-15.json')
    contract.validate_web_report(public)
    assert all(set(item) == {'role', 'provider', 'model', 'status'} for item in public['agents'])
    assert public['counts']['eligible'] == (0 if role == 'reviewer' else 3)
    day = lab.store.read('days/2026-10-15.json')
    stripped = deepcopy(day)
    for collection in ('agents', 'reviewed_agents'):
        for item in stripped.get(collection, []):
            for field in ('reason', 'error_type', 'interrupted', 'telemetry', 'failure_detail'):
                item.pop(field, None)
    assert contract.canonical_json(public) == contract.canonical_json(contract.build_web_report(stripped))
    for sensitive in (reason, SECRET, RAW, private_path, 'local_participation', 'error_type'):
        assert sensitive not in json.dumps(public)
    frozen = lab.store.path('web/2026-10-15.json').read_bytes()
    lab.tick(next_hour, 1, runner=forbidden, local_runner=forbidden)
    assert lab.store.path('web/2026-10-15.json').read_bytes() == frozen

def test_false_remote_failure_diagnostics_do_not_change_success_or_cost_settlement(lab):
    def forge(role, result, response, options):
        result.update(reason='role_interrupted', error_type=RAW + SECRET,
                      stage='role_json_invalid', field=RAW + SECRET, interrupted=True,
                      diagnostic={'reason': 'candidate_edit_files_duplicate', 'raw': SECRET},
                      failure_detail=dict(diag.sanitize_detail(None), cause='authentication_failed',
                                          errno=True, http_status=10 ** 100))
        return result

    lab.cloud_transform = forge
    lab.hours()
    report = lab.report()
    assert report['status'] == 'scanned' and report['review_complete'] is True
    assert len(report['proposals']) == 4
    assert all(agent['status'] == 'succeeded' and 'reason' not in agent and
               'error_type' not in agent and 'failure_detail' not in agent and not agent.get('interrupted') for agent in report['agents'])
    assert lab.calls() == 9 and lab.spent() == approx(.04)
    assert_private(lab.state())
    assert all(not entry['options']['workspace'].exists() for entry in lab.cloud_requests)

@pytest.mark.parametrize('diagnostic', ['missing', 'forged'])
def test_legacy_cloud_participation_uses_fallback_in_actual_next_round_feedback(lab, monkeypatch, diagnostic):
    actual_call = imp._call_role

    def legacy_call(role, *args, **kwargs):
        participation, parsed = actual_call(role, *args, **kwargs)
        if role == 'coordinator':
            participation['status'] = 'failed'
            participation.pop('reason', None)
            participation.pop('error_type', None)
            if diagnostic == 'forged':
                participation.update(reason={'raw': RAW + SECRET}, error_type=RAW + SECRET,
                                     diagnostic={'reason': 'role_json_invalid', 'line': True})
            return participation, None
        return participation, parsed

    monkeypatch.setattr(imp, '_call_role', legacy_call)
    lab.hours()
    report = lab.report()
    agent = report['agents'][0]
    assert agent['reason'] == 'role_failed'
    assert agent['failure_detail'] == diag.sanitize_detail(None)
    if diagnostic == 'missing':
        assert 'error_type' not in agent
    else:
        assert agent['error_type'] == 'Exception'
    saved = lab.store.read('scans/' + report['scan_id'] + '.json')
    assert saved['agents'][0] == agent
    lab.tick(9)
    assert lab.local_requests[-1]['feedback'][0]['specialist_reason'] == 'role_failed'
    public = lab.store.read('web/2026-10-15.json')
    contract.validate_web_report(public)
    assert 'role_failed' not in json.dumps(public)
    assert_private(lab.state())

class UntrustedDiagnosticString(str):
    pass

@pytest.mark.parametrize('value', [
    None, True, False, 0, 1, -1, 1.5, [], {}, ['role_json_invalid'],
    'unknown', 'candidate_edit_files_typo', RAW + SECRET,
    'role_json_invalid' + 'x' * 65536,
    UntrustedDiagnosticString('role_json_invalid'),
    UntrustedDiagnosticString('ValidationError'),
], ids=lambda value: type(value).__name__)
def test_private_participation_unknown_reason_and_exception_type_have_fixed_fallback(value):
    participation = {'role': 'coordinator', 'provider': 'codex', 'model': 'synthetic',
                     'status': 'failed', 'reason': value, 'error_type': value}
    original = deepcopy(participation)
    safe = loop._safe_participation(participation)
    assert safe['reason'] == 'role_failed' and safe['error_type'] == 'Exception'
    assert set(safe) == {'role', 'provider', 'model', 'status', 'reason', 'error_type',
                         'cost', 'cost_status', 'failure_detail'}
    assert safe['failure_detail'] == diag.sanitize_detail(None)
    assert participation == original

@pytest.mark.parametrize('reason', [None, 'role_json_invalid'])
@pytest.mark.parametrize('position', [
    True, False, -1, 0, 1, 65536, 65537, 2 ** 256, 1.5, '1',
    None, [], {'raw': SECRET}, RAW + SECRET, 'x' * 65537,
], ids=lambda value: type(value).__name__)
def test_untrusted_diagnostic_stage_field_type_and_syntax_positions_are_not_retained(position, reason):
    legacy = {'role': 'coordinator', 'provider': 'codex', 'model': 'synthetic',
              'status': 'failed', 'reason': reason}
    diagnostic = {'reason': 'role_json_invalid', 'stage': RAW + SECRET,
                  'field': RAW + SECRET, 'type': RAW + SECRET,
                  'line': position, 'column': position, 'offset': position}
    forged = dict(legacy, diagnostic=diagnostic, diagnostics=diagnostic,
                  **dict.fromkeys(('stage', 'field', 'type', 'response', 'prompt'), RAW + SECRET),
                  **dict.fromkeys(('line', 'column', 'offset', 'lineno', 'colno', 'pos', 'json_position'), position),
                  result={'reason': 'role_json_invalid', 'raw': SECRET})
    assert loop._safe_participation(forged) == loop._safe_participation(legacy)
    assert loop._safe_participation(forged)['reason'] == (reason or 'role_failed')

@pytest.mark.parametrize('status', ['failed', 'unavailable', 'not_called', 'succeeded'])
def test_legacy_participation_without_diagnostics_remains_compatible(status):
    legacy = {'role': 'coordinator', 'provider': 'codex', 'model': 'synthetic', 'status': status}
    safe = loop._safe_participation(legacy)
    assert safe == dict(legacy, cost=None, cost_status='unknown',
                        **({} if status == 'succeeded' else {'reason': 'role_failed',
                           'failure_detail': diag.sanitize_detail(None)}))
    assert 'error_type' not in safe
    assert 'reason' not in loop._safe_participation(dict(legacy, status='succeeded',
                                                       reason='role_json_invalid', error_type=RAW + SECRET))

def test_discovery_schema_is_not_forwarded_to_codex_local_or_reviewer(lab):
    lab.models['roles']['coordinator']['provider'] = 'codex'
    local_roles, excluded_cloud_roles, native_roles = [], [], []

    def local(role, paths, snapshots, **options):
        assert 'discovery_schema' not in options
        local_roles.append(role)
        return lab.local(role, paths, snapshots, **options)

    def cloud(role, prompt, keys, **options):
        provider = lab.models['roles'][role]['provider']
        if role == 'reviewer' or provider != 'zai':
            assert 'discovery_schema' not in options
            excluded_cloud_roles.append((role, provider))
        else:
            assert 'discovery_schema' in options
            native_roles.append(role)
        return lab.cloud(role, prompt, keys, **options)

    for hour in range(9):
        lab.tick(hour, runner=cloud, local_runner=local)

    assert local_roles == list(contract.SPECIALIST_ROLES)
    assert excluded_cloud_roles == [('coordinator', 'codex'), ('parser', 'codex'),
                                    ('django', 'codex'), ('reviewer', 'claude')]
    assert native_roles == [role for role in contract.SPECIALIST_ROLES
                            if lab.models['roles'][role]['provider'] == 'zai']
    assert lab.calls() == 9 and len(lab.events) == 9
    assert lab.report()['review_complete'] is True
    assert all(agent['status'] == 'succeeded' for agent in lab.report()['agents'])


@pytest.mark.parametrize('mode,expected,cause', [
    ('success', 'succeeded', None), ('missing', 'failed', 'envelope_invalid'),
    ('error', 'failed', 'envelope_invalid'), ('duplicate', 'failed', 'json_invalid'),
    ('unsupported', 'failed', 'cli_failed'), ('candidate', 'failed', 'validation'),
    ('line_range', 'failed', 'validation'),
    ('identity', 'failed', 'identity_mismatch'), ('context', 'failed', 'context_changed'),
])
def test_zai_specialist_native_adapter_through_tick(lab, monkeypatch, mode, expected, cause):
    from harness import improvement_health as health
    lab.hours(count=3)
    seen = []
    def cli(command, **options):
        assert '--json-schema' in command and command[0] == 'claude'
        schema = json.loads(command[command.index('--json-schema') + 1])
        assert schema['required'] == ['candidates']
        seen.append(command)
        lab.clock.at(3, seconds=7)
        body = {'candidates': []}
        if mode == 'candidate':
            body = {'candidates': [draft('outside.py')]}
        if mode == 'line_range':
            body = {'candidates': [draft('downloader/example.py', end=999)]}
        envelope = dict(type='result', subtype='error_max_turns' if mode == 'error' else 'success',
                        is_error=False, result='{}', structured_output=body)
        if mode == 'missing':
            envelope.pop('structured_output')
        text = json.dumps(envelope)
        if mode == 'duplicate':
            text = '{"type":"result","subtype":"success","is_error":false,"structured_output":{"candidates":[],"candidates":[]}}'
        return subprocess.CompletedProcess(command, 2 if mode == 'unsupported' else 0, text, '')
    def adapter(role, prompt, keys, **options):
        assert role == 'downloader' and 'discovery_schema' in options
        result = run_synthetic_loop_adapter(lab, monkeypatch, forbidden, cli,
                                             role, prompt, keys, **options)
        if mode == 'identity':
            result['model'] = 'forged'
        if mode == 'context':
            target = options['workspace'] / 'downloader/example.py'
            target.chmod(0o600)
            target.write_text('changed', encoding='utf-8')
        return result
    lab.tick(3, runner=adapter)
    assert len(seen) == 1
    entry = next(e for e in lab.state()['participation'] if e['role'] == 'downloader')
    assert entry['status'] == expected and entry['stage_index'] == 3
    if cause is not None:
        assert entry['failure_detail']['cause'] == cause
        projected = health.project(lab.state(), lab.clock().isoformat())
        failed = projected['recent_failures'][-1]['attempt']
        assert failed['role'] == 'downloader' and failed['stage_index'] == 3
        assert failed['cause'] == cause and failed['call_finished_at'].endswith('07+09:00')
        if mode == 'line_range':
            assert (failed['field'], failed['rule']) == ('evidence.end_line', 'range')
        lab.hours(start=4, count=6)
        frozen = lab.store.path('web/2026-10-15.json').read_bytes()
        lab.hours(start=10, count=4)
        final = health.project(lab.state(), lab.clock().isoformat())
        original = next(row for row in final['recent_failures'] if row['attempt'] == failed)
        assert original['subsequent_success_at'] is not None
        assert entry in lab.state()['participation']
        assert lab.store.path('web/2026-10-15.json').read_bytes() == frozen


def test_cloud_health_times_bracket_adapter_not_admission_preparation_or_settlement(lab, monkeypatch):
    lab.hours(count=3)
    call = imp._call_role
    def preparation(*args, **options):
        lab.clock.at(3, seconds=2)
        value = call(*args, **options)
        lab.clock.at(3, seconds=9)
        return value
    def runner(*args, **options):
        result = lab.cloud(*args, **options)
        result.update(call_started_at='1900-01-01T00:00:00+09:00',
                      call_finished_at='1900-01-01T00:00:01+09:00')
        lab.clock.at(3, seconds=7)
        return result
    monkeypatch.setattr(imp, '_call_role', preparation)
    lab.tick(3, runner=runner)
    entry = next(e for e in lab.state()['participation'] if e['role'] == 'downloader')
    assert entry['started_at'].endswith('00+09:00')
    assert entry['call_started_at'].endswith('02+09:00')
    assert entry['call_finished_at'].endswith('07+09:00')
    assert entry['finished_at'].endswith('09+09:00')


def test_native_preparation_failure_has_no_invented_call_times_or_fallback(lab, monkeypatch):
    from harness import improvement_schema as schema, improvement_health as health
    lab.hours(count=3)
    def invalid_schema(*args, **options):
        raise ValueError('discovery_schema_invalid')
    monkeypatch.setattr(schema, 'prepare', invalid_schema)
    lab.tick(3, runner=forbidden)
    entry = next(e for e in lab.state()['participation'] if e['role'] == 'downloader')
    assert entry['status'] == 'unavailable'
    assert entry['failure_detail']['phase'] == 'preparation'
    failed = health.project(lab.state(), lab.clock().isoformat())['recent_failures'][-1]['attempt']
    assert failed['call_started_at'] is None and failed['call_finished_at'] is None
    assert lab.calls() == 4 and lab.state()['stage_index'] == 4


@pytest.mark.parametrize('role,mode,cause', [
    ('coordinator', 'words', 'cli_failed'), ('coordinator', 'auth', 'authentication_failed'),
    ('coordinator', 'warning', 'cli_failed'), ('coordinator', 'timeout', 'timeout'),
    ('coordinator', 'settlement', 'cli_failed'),
    ('reviewer', 'exit', 'cli_failed'), ('reviewer', 'spawn', 'spawn_failed'),
])
def test_native_adapter_failure_survives_tick_restart_feedback_and_later_success(lab, monkeypatch, role, mode, cause):
    lab.models['roles']['coordinator']['provider'] = 'codex'
    hour = 8 if role == 'reviewer' else 1
    lab.hours(count=hour)
    cli_calls = []
    def cli(command, **options):
        cli_calls.append('login' if 'login' in command else 'execution')
        if 'login' in command:
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
        lab.clock.at(hour, seconds=7)
        if mode == 'timeout':
            raise subprocess.TimeoutExpired(command, 1, output=RAW + SECRET)
        if mode == 'spawn':
            raise OSError(13, RAW + SECRET)
        return subprocess.CompletedProcess(command, 7,
            RAW + SECRET + ' authentication readonly 401 quota' if mode == 'words' else '',
            'PATH aliases: Read-only file system (os error 30)' if mode == 'warning' else
            'Authentication failed: unauthorized 401' if mode == 'auth' else
            '' if mode == 'words' else RAW + SECRET)
    def adapter(actual_role, prompt, keys, **options):
        assert actual_role == role
        return run_synthetic_loop_adapter(lab, monkeypatch, forbidden, cli,
                                          actual_role, prompt, keys, **options)
    write = imp.Store.write
    def settle(store, name, value):
        if mode == 'settlement' and name.startswith('scans/'):
            raise OSError(28, RAW + SECRET)
        return write(store, name, value)
    with monkeypatch.context() as patch:
        patch.setattr(imp.Store, 'write', settle)
        outcome = lab.tick(hour, runner=adapter)
    assert cli_calls == (['login', 'execution'] if role == 'coordinator' else ['execution'])
    state = lab.state()
    agent = next(a for a in state['round']['report']['agents'] if a['role'] == role)
    detail = agent['failure_detail']
    assert detail['cause'] == cause and detail['phase'] == 'execution'
    assert detail['exit_code'] == (None if mode in ('timeout', 'spawn') else 7)
    assert detail['errno'] == (13 if mode == 'spawn' else None)
    assert outcome['diagnostic']['detail'] == detail
    entry = next(e for e in state['participation'] if e['role'] == role)
    assert entry['failure_detail'] == detail
    assert all(entry[k] == lab.slots()[entry['slot']][k]
               for k in ('failure_detail', 'reason', 'stage_index', 'status'))
    assert entry['finished_at'].endswith('07+09:00')
    assert entry['call_started_at'].endswith('00+09:00')
    assert entry['call_finished_at'] == entry['finished_at']
    lab.store = imp.Store(lab.selected)
    lab.hours(start=hour + 1, count=9 - hour)
    key = 'review_failure_detail' if role == 'reviewer' else 'specialist_failure_detail'
    assert lab.local_requests[-1]['feedback'][0][key] == detail
    assert entry in loop.status(now=lab.clock(), selected=lab.selected)['participation']
    frozen = lab.store.path('web/2026-10-15.json').read_bytes()
    lab.cloud_transform = None
    lab.hours(start=10, count=9)
    assert entry in lab.state()['participation']
    assert any(e['role'] == role and e['status'] == 'succeeded'
               and e['started_at'] > entry['finished_at'] for e in lab.state()['participation'])
    saved = lab.store.read('scans/' + entry['scan_id'] + '.json')
    assert next(a for a in saved['agents'] if a['role'] == role)['failure_detail'] == detail
    assert lab.store.path('web/2026-10-15.json').read_bytes() == frozen
    assert_private(lab.state())
