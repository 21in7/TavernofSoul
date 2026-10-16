"""Offline behavioral contracts for hourly research and immutable KST reports.

Only synthetic sources, an aware fake clock, modeled CLI results, injected HTTP
and isolated temporary storage are used. No model, subprocess, check, scheduler,
credential lookup or operating pipeline is permitted. Tests are specifications,
not evidence of execution or host/model readiness.

Documentation review: these tests preserve the engine API and authority boundary;
they add no production policy. The engine's new scheduling/accounting/recovery
contracts require the separately assigned documentation work in AGENTS.md,
docs/{architecture,harness-design,harness,improvements,workflow,agent-models,
local-models}.md and docs/adr/{0017-budgeted-continuous-improvement,README}.md.
In particular, document conservative interrupted reservations, failed sender
reconciliation, skipped owner slots and the distinction between private local
drafts and actual public role participation. This file cannot update those docs.
"""

import copy
import datetime as dt
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess

import pytest

from harness import agent_models, improvement_loop as loop
from harness import improvement_report as contract
from harness import improvements as imp, local_model, storage, workflow


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


def shipped(name):
    # Exact approved configuration inputs only; never resolve private host policy.
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
        # The caller has claimed the slot before contacting the quota endpoint.
        state = self.state()
        slot = self.clock().strftime('%Y-%m-%dT%H')
        assert state['days'][self.clock().date().isoformat()]['slots'][slot]['status'] == 'claimed'
        self.quotas.append(slot)
        return 200, encode(quota_body(self.clock()))

    def local(self, role, paths, snapshots, **options):
        self.active_owner = role
        self.events.append(('local_explorer', role))
        self.assert_reserved('mlx-lm')
        assert paths == imp.role_scope(role, FILES, self.discovery)
        return local_model.run(role, paths, snapshots, transport=self.local_http, **options)

    def local_http(self, config, body):
        assert os.environ.get('TAVERN_IMPROVEMENT_DISCOVERY') == '1'
        assert len(body) <= 24576 and config['limits']['timeout_seconds'] <= 180
        request = json.loads(body)
        assert set(request) == {'model', 'stream', 'max_tokens', 'temperature',
                                'chat_template_kwargs', 'messages'}
        assert request['model'] == 'default_model' and request['stream'] is False
        assert request['max_tokens'] <= 3072
        assert request['chat_template_kwargs'] == {'enable_thinking': False}
        assert [m['role'] for m in request['messages']] == ['system', 'user']
        user = json.loads(request['messages'][1]['content'])
        assert user['owner_role'] == self.active_owner
        self.local_requests.append(copy.deepcopy(user))
        self.wire_requests.append(body)
        source = user['sources'][0]
        candidates = [draft(source['path'], source['start_line'], source['end_line'],
                            '로컬 ' + self.active_owner + ' 점검 후보')]
        if self.local_transform:
            candidates = self.local_transform(user, candidates)
        content = json.dumps({'candidates': candidates}, ensure_ascii=False)
        envelope = {'model': 'default_model', 'choices': [
            {'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}]}
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
        assert sorted(str(p.relative_to(context)) for p in context.rglob('*') if p.is_file()) == sorted(paths)
        for path in paths:
            assert (context / path).read_bytes() == (self.root / path).read_bytes()
            assert (context / path).stat().st_mode & 0o777 == 0o400
        self.events.append(('independent_reviewer' if role == 'reviewer' else 'specialist', role))
        self.cloud_requests.append({'role': role, 'prompt': prompt, 'options': options})
        if role == 'reviewer':
            assert 0 < options['max_budget_usd'] <= .2
            prior = json.loads(prompt.split('\nPrior candidates: ', 1)[1])
            response = {'reviews': [dict(candidate_id=r['id'], verdict='eligible',
                                        reason=REVIEW_REASON, documentation=copy.deepcopy(DOC))
                                    for r in prior], 'documentation': copy.deepcopy(DOC)}
        else:
            assert 'max_budget_usd' not in options
            context = json.loads(prompt.rsplit('\n', 1)[1])
            candidates = copy.deepcopy(context['local_drafts'])
            for c in candidates:
                c['issue'] = '담당자 보완: ' + c['issue']
            response = {'candidates': candidates}
        result = dict(role=role, provider=spec['provider'], model=spec['model'],
                      status='passed', response=json.dumps(response, ensure_ascii=False),
                      diagnostics=RAW)
        if role == 'reviewer':
            result['cli_estimated_cost_usd'] = .04
        return self.cloud_transform(role, result, response, options) if self.cloud_transform else result

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
    monkeypatch.setattr(agent_models, 'load_config', lambda: copy.deepcopy(lab.models))
    monkeypatch.setattr(workflow, 'load_policy', lambda: copy.deepcopy(lab.policy))
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
    assert all(a['provider'] != 'mlx-lm' and 'result' not in a for a in report['agents'])
    assert len(report['local_participation']) == 4
    for local in report['local_participation']:
        assert local['provider'] == 'mlx-lm' and local['model'] == lab.local_config['model']
        assert local['stage'] == 'local_explorer' and local['called'] is True
        assert local['cost'] is None and local['cost_status'] == 'not_metered'
        assert local['read_windows'] and 'request' not in local and 'response' not in local
    for record in report['proposals']:
        saved = lab.store.read('proposals/' + record['id'] + '.json')
        assert saved['proposal'] == record and saved['scan_id'] == report['scan_id']
        assert imp._eligible(lab.store, record['id']) == record
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.04)
    assert lab.quotas == ['2026-10-15T03']
    assert 'TAVERN_IMPROVEMENT_DISCOVERY' not in os.environ
    for entry in lab.cloud_requests:
        assert not entry['options']['workspace'].exists()
    for directory in ('decisions', 'approvals', 'claims', 'executions'):
        assert not lab.store.path(directory).exists()


def test_same_slot_restart_and_clock_rollback_never_replay(lab):
    lab.tick(0)
    first = lab.store.path(loop.STATE_FILE).read_bytes()
    lab.store = imp.Store(lab.selected)  # discard all in-memory handles
    for minute in (0, 1, 59):
        assert lab.tick(0, minute)['reason'] == 'slot_already_claimed'
        assert lab.store.path(loop.STATE_FILE).read_bytes() == first
    lab.tick(1)
    after = lab.store.path(loop.STATE_FILE).read_bytes()
    assert lab.tick(0, 59)['reason'] == 'clock_rollback'
    assert lab.store.path(loop.STATE_FILE).read_bytes() == after
    assert len(lab.events) == 2 and lab.ledger()['calls'] == 2


def test_hourly_opportunities_never_exceed_twenty_four_in_kst_day(lab):
    # Two candidates per owner exercise the full eight-record pool as well.
    lab.local_transform = lambda user, cs: cs + [dict(copy.deepcopy(cs[0]), title=cs[0]['title'] + ' 두번째')]
    for hour in range(24):
        before = len(lab.events)
        lab.tick(hour)
        assert len(lab.events) - before == 1
        assert lab.tick(hour, 59)['reason'] == 'slot_already_claimed'
    assert len(lab.events) == lab.ledger()['calls'] == 24
    assert len(lab.ledger()['slots']) == 24
    for entry in lab.state()['completed']:
        report = lab.store.read('scans/' + entry['scan_id'] + '.json')
        assert len(report['proposals']) == 8
    lab.tick(24)
    assert lab.ledger()['calls'] == 1 and len(lab.events) == 25


def test_lower_day_cap_blocks_new_slot_but_morning_still_finalizes(lab):
    lab.config['max_calls_per_day'] = 1
    lab.save_loop()
    lab.tick(0)
    assert lab.tick(1)['reason'] == 'daily_call_limit'
    result = lab.tick(9)
    assert result['reason'] == 'daily_call_limit' and len(lab.events) == 1
    report = lab.store.read('days/2026-10-15.json')
    assert report['review_complete'] is False and report['proposals'] == []
    assert report['status'] == 'partial'


@pytest.mark.parametrize('project', [False, True])
def test_contending_lock_does_not_claim_or_report_a_scan(lab, project):
    with lab.store.lock(project=project):
        result = lab.tick(9)
    assert result['status'] == 'paused'
    assert result['reason'] == 'lock_storage_or_runtime_unavailable'
    assert lab.events == [] and not lab.store.exists(loop.STATE_FILE)
    assert not lab.store.exists('days/2026-10-15.json')
    # A lock rejection did not start this slot; a later invocation may claim it.
    assert lab.tick(9)['calls_today'] == 1


def test_reentrant_tick_inside_model_cannot_double_admit(lab):
    actual = lab.local
    reentered = []

    def local(*args, **kwargs):
        reentered.append(lab.tick())
        return actual(*args, **kwargs)

    lab.tick(0, local_runner=local)
    assert reentered[0]['reason'] == 'lock_storage_or_runtime_unavailable'
    assert len(lab.events) == 1 and lab.ledger()['calls'] == 1


def test_project_lock_is_shared_even_with_different_artifact_policy(lab):
    other = storage.Storage(root=lab.root,
        artifacts=storage.DirectorySpec(lab.root.parent / 'other-artifacts', lab.root.parent, 0),
        temporary=storage.DirectorySpec(lab.root.parent / 'other-contexts', lab.root.parent, 0),
        config_path=lab.root.parent / 'other-policy.json', env={}, fs=FixtureFS(lab.root.parent))
    with lab.store.lock(project=True):
        result = lab.tick(9, selected=other)
    assert result['reason'] == 'lock_storage_or_runtime_unavailable'
    assert lab.events == [] and not imp.Store(other).exists(loop.STATE_FILE)


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
    assert result['reason'] == 'lock_storage_or_runtime_unavailable'
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
    assert lab.state()['round']['report']['review_complete'] is False
    if finish_hour == 24:
        for date in ('2026-10-15', '2026-10-16'):
            assert lab.ledger(date)['calls'] == 1 and lab.ledger(date)['stopped']
        assert lab.tick(25)['reason'] == reason and len(lab.events) == 1


def test_slot_claim_precedes_configuration_failure_and_is_not_retried(lab):
    lab.local_path.unlink()
    result = lab.tick(0)
    assert result['reason'] == 'config_unavailable'
    assert lab.ledger()['calls'] == 0 and lab.events == []
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
    config = copy.deepcopy(lab.config)
    config[name] = value
    with pytest.raises(loop.LoopError):
        loop.validate_config(config)


def test_configuration_requires_explicit_fields_and_cross_field_bounds(lab):
    config = copy.deepcopy(lab.config)
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
    # A later query must not invent or refresh an inactive window's reset.
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
    body['data']['limits'].append(copy.deepcopy(model))
    assert loop.validate_quota(body, START)['reason'] == 'quota_malformed'


@pytest.mark.parametrize('kind', ['TOKENS_LIMIT', 'CREDIT_LIMIT'])
def test_glm_zero_idle_admits_only_the_current_specialist_and_keeps_unknown_reset(lab, kind):
    lab.hours(count=3)
    requests = []

    def transport(key, timeout, max_bytes):
        assert key == SECRET
        requests.append(lab.clock())
        assert lab.ledger()['slots']['2026-10-15T03']['status'] == 'claimed'
        body = quota_body(lab.clock(), kind=kind, percentage=0)
        body.update(code=200, success=True)
        body['data']['limits'][1]['nextResetTime'] = None
        return 200, encode(body)

    result = lab.tick(3, quota_transport=transport)
    assert result['calls_today'] == 4 and lab.state()['stage_index'] == 4
    assert lab.events[-1] == ('specialist', 'downloader') and len(lab.events) == 4
    quota = lab.ledger()['slots']['2026-10-15T03']['quota']
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
    body['data']['limits'] = [model, copy.deepcopy(model)]
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
    assert lab.ledger()['calls'] == 3
    assert lab.tick(3, 59)['reason'] == 'slot_already_claimed'
    assert len(calls) == (0 if failure == 'missing_key' else 1)
    retained = json.dumps(lab.state(), ensure_ascii=False) + json.dumps(result)
    assert SECRET not in retained and RAW not in retained
    # Next distinct slot re-queries current usage; the old 1% is not cached.
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
            assert code == 200  # redirect bodies are never followed or read
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
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.2)
    slot = lab.ledger()['slots']['2026-10-15T08']
    assert slot['cost_status'] in ('reservation_consumed_unknown', 'reservation_consumed_failed')
    reviewer = lab.state()['round']['report']['agents'][-1]
    if mode != 'failed_known':
        assert reviewer['cost'] is None and reviewer['cost_status'] == 'unknown'
    assert SECRET not in json.dumps(lab.state()) and RAW not in json.dumps(lab.state())
    assert lab.tick(8, 1)['reason'] == 'slot_already_claimed'
    lab.store = imp.Store(lab.selected)
    lab.tick(9)
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.2)


def test_remaining_budget_is_passed_as_downward_override_and_settled(lab):
    lab.hours(count=8)
    state = lab.state()
    state['days']['2026-10-15']['claude_spent_usd'] = .93
    lab.store.write(loop.STATE_FILE, state)
    lab.tick(8)
    request = lab.cloud_requests[-1]
    assert request['options']['max_budget_usd'] == pytest.approx(.07)
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.97)
    assert lab.models['roles']['reviewer']['max_budget_usd'] == 2


def test_loop_cap_never_increases_smaller_existing_reviewer_budget(lab):
    lab.models['roles']['reviewer']['max_budget_usd'] = .05
    lab.hours()
    assert lab.cloud_requests[-1]['options']['max_budget_usd'] == .05
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.04)


def test_exhausted_budget_holds_reviewer_and_later_stages_but_not_morning(lab):
    lab.hours(count=8)
    state = lab.state()
    state['days']['2026-10-15']['claude_spent_usd'] = 1
    lab.store.write(loop.STATE_FILE, state)
    assert lab.tick(8)['reason'] == 'daily_budget_limit'
    for hour in (9, 10, 11):
        assert lab.tick(hour)['reason'] == 'daily_budget_limit'
        assert lab.state()['stage_index'] == 8
    assert len(lab.events) == 8 and lab.ledger()['calls'] == 8
    assert len(lab.local_requests) == 4 and len(lab.cloud_requests) == 4
    assert lab.state()['inflight'] is None
    assert lab.store.read('days/2026-10-15.json')['status'] == 'partial'
    assert lab.store.read('days/2026-10-15.json')['proposals'] == []


def test_actual_cost_over_reservation_is_recorded_and_stops_day(lab):
    lab.hours(count=8)
    lab.cloud_transform = lambda role, result, response, options: dict(result, cli_estimated_cost_usd=.27)
    result = lab.tick(8)
    assert result['reason'] == 'daily_budget_overrun'
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.27)
    assert lab.ledger()['slots']['2026-10-15T08']['budget_overrun'] is True
    lab.tick(9)
    assert len(lab.events) == 9 and lab.ledger()['calls'] == 9
    assert lab.store.exists('days/2026-10-15.json')


def test_overrun_persisted_before_interruption_is_never_reduced_to_reservation(lab, monkeypatch):
    lab.hours(count=8)
    lab.cloud_transform = lambda role, result, response, options: dict(result, cli_estimated_cost_usd=.27)
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
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.27)
    lab.tick(8, 1)
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.27)
    reviewer = lab.state()['round']['report']['agents'][-1]
    assert reviewer['cost'] == pytest.approx(.27) and reviewer['status'] == 'failed'
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
    assert lab.ledger()['calls'] == 8 and lab.ledger()['claude_spent_usd'] == 0
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
    assert lab.ledger()['calls'] == 9 and lab.ledger()['claude_spent_usd'] == pytest.approx(.2)
    lab.store = imp.Store(lab.selected)
    assert lab.tick(8, 1)['reason'] == 'slot_already_claimed'
    recovered = lab.state()
    assert recovered['inflight'] is None and recovered['stage_index'] == 9
    assert recovered['round']['report']['agents'][-1]['reason'] == 'interrupted_unknown'
    assert recovered['round']['report']['agents'][-1]['cost'] is None
    lab.tick(9)
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.2)
    assert lab.ledger()['calls'] == 10
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
        assert lab.ledger(date)['claude_spent_usd'] == pytest.approx(.2)
        assert lab.ledger(date)['stopped'] is True
    lab.tick(25)
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.2) and lab.ledger()['calls'] == 1


def test_interrupted_local_cursor_is_durable_and_paired_owner_is_skipped(lab):
    def crash(*args, **kwargs):
        lab.assert_reserved('mlx-lm')
        raise PowerLoss()

    with pytest.raises(PowerLoss):
        lab.tick(0, local_runner=crash)
    assert lab.state()['cursors']['coordinator'] == {'file_index': 0, 'line': 3}
    lab.store = imp.Store(lab.selected)
    assert lab.tick(1)['reason'] == 'local_draft_unavailable'
    assert lab.cloud_requests == [] and lab.ledger()['calls'] == 1
    local = lab.state()['round']['report']['local_participation'][0]
    assert local['status'] == 'failed' and local['reason'] == 'interrupted_unknown'
    lab.hours(start=2, count=8)
    request = lab.local_requests[-1]
    assert request['owner_role'] == 'coordinator'
    assert request['sources'][0]['start_line'] == 3
    assert request['feedback'][0]['specialist_reason'] == 'local_interrupted_unknown'


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
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.04)
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
    assert lab.ledger()['calls'] == 6
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(cost)
    assert lab.ledger()['legacy_seen'] == [old['scan_id']]
    lab.store = imp.Store(lab.selected)
    lab.tick(10, publisher=forbidden)
    assert lab.ledger()['calls'] == 7
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(cost)
    assert lab.store.path('days/2026-10-15.json').read_bytes() == body
    assert lab.store.read(loop._publication_name('2026-10-15'))['status'] == 'legacy_preserved'


def test_additional_same_day_legacy_activity_is_imported_once_and_loop_scans_are_excluded(lab):
    first = legacy(lab, cost=.03)
    lab.tick(0)
    second = copy.deepcopy(first)
    second['scan_id'] = '123456790-abcdef'
    second['agents'][-1]['cost'] = .02
    lab.store.write('scans/' + second['scan_id'] + '.json', second)
    already_accounted = dict(copy.deepcopy(second), scan_id='123456791-abcdef',
                             loop_engine=loop.STATE_VERSION)
    lab.store.write('scans/' + already_accounted['scan_id'] + '.json', already_accounted)
    lab.tick(1)
    assert lab.ledger()['calls'] == 12  # two real legacy groups of five plus two tick calls
    assert lab.ledger()['claude_spent_usd'] == pytest.approx(.05)
    assert lab.ledger()['legacy_seen'] == [first['scan_id'], second['scan_id']]
    lab.store = imp.Store(lab.selected)
    lab.tick(2)
    assert lab.ledger()['calls'] == 13 and lab.ledger()['claude_spent_usd'] == pytest.approx(.05)


@pytest.mark.parametrize('complete,cost,status', [(False, .0434664, 'cli_estimated_usd'),
                                               (True, None, 'unknown')])
def test_unknown_legacy_activity_consumes_day_budget_conservatively(lab, complete, cost, status):
    legacy(lab, complete, cost, status)
    lab.tick(0)
    day = lab.ledger()
    assert day['claude_spent_usd'] == pytest.approx(1)
    assert day['legacy_cost_status'] == 'unknown_consumed'
    if not complete:
        assert day['calls'] >= 24 and lab.events == []


def test_owner_cursor_rotates_contiguous_original_line_windows_across_restarts(lab):
    lab.hours(count=10)  # next round coordinator sees original lines 3..4
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


def test_long_single_line_is_explicit_skip_without_http_slicing_or_specialist(lab):
    (lab.root / FILES[0]).write_text('x' * 30000 + '\nvalue = 2\n', encoding='utf-8')
    result = lab.tick(0)
    assert result['reason'] == 'line_too_long' and lab.local_requests == []
    assert lab.ledger()['calls'] == 0
    participation = lab.state()['round']['report']['local_participation'][0]
    assert participation['called'] is False and participation['status'] == 'skipped'
    assert participation['skipped_lines'] == [{'path': FILES[0], 'start_line': 1, 'end_line': 1,
                                              'reason': 'line_too_long'}]
    assert lab.state()['cursors']['coordinator'] == {'file_index': 0, 'line': 2}
    assert lab.tick(1)['reason'] == 'local_draft_unavailable'
    assert lab.cloud_requests == []


@pytest.mark.parametrize('failure', ['empty', 'timeout', 'outside_evidence', 'outside_benefit', 'basename', 'too_many'])
def test_failed_local_draft_skips_only_paired_owner_and_retains_truthful_participation(lab, failure):
    def transform(user, cs):
        if user['owner_role'] != 'coordinator':
            return cs
        if failure == 'timeout':
            raise TimeoutError(RAW + SECRET)
        if failure == 'empty':
            return []
        if failure == 'too_many':
            return [dict(copy.deepcopy(cs[0]), title='합성 후보 ' + str(i)) for i in range(3)]
        if failure == 'outside_evidence':
            cs[0]['evidence'][0]['end_line'] = 3
        elif failure == 'outside_benefit':
            cs[0]['benefit']['evidence'] = [dict(cs[0]['evidence'][0], start_line=3, end_line=3)]
        else:
            cs[0]['evidence'][0]['path'] = 'example.py'
        return cs

    lab.local_transform = transform
    lab.tick(0)
    failed = lab.state()['round']['report']['local_participation'][0]
    assert failed['status'] == 'failed' and failed['called'] is True
    result = lab.tick(1)
    assert result['reason'] == 'local_draft_unavailable'
    owner = lab.state()['round']['report']['agents'][0]
    assert owner['status'] == 'not_called' and owner['provider'] is None and owner['cost'] is None
    assert lab.cloud_requests == [] and lab.ledger()['calls'] == 1
    lab.hours(start=2, count=7)
    assert lab.state()['round']['report']['status'] == 'partial'
    assert all(c['role'] != 'coordinator' for c in lab.cloud_requests)
    lab.tick(9)
    public = lab.store.read('web/2026-10-15.json')
    assert public['agents'][0]['status'] == 'not_called'
    assert public['status'] == 'partial' and public['counts']['candidates'] == 3
    assert all(a['provider'] != 'mlx-lm' for a in public['agents'])
    assert SECRET not in json.dumps(lab.state()) and RAW not in json.dumps(lab.state())


def test_engine_revalidates_evidence_against_prepared_window_even_if_injected_runner_lies(lab):
    def forged(role, paths, snapshots, **options):
        return {'provider': 'mlx-lm', 'model': lab.local_config['model'],
                'stage': 'local_explorer', 'owner_role': role, 'status': 'succeeded',
                'called': True, 'reason': 'ok',
                'read_windows': [{'path': FILES[0], 'start_line': 1, 'end_line': 6}],
                'candidates': [draft(FILES[0], 3, 4)]}

    lab.tick(0, local_runner=forged)
    local = lab.state()['round']['report']['local_participation'][0]
    assert local['status'] == 'failed'
    assert local['read_windows'] == [{'path': FILES[0], 'start_line': 1, 'end_line': 2}]
    assert lab.state()['round']['drafts']['coordinator']['candidates'] == []
    assert lab.tick(1)['reason'] == 'local_draft_unavailable'
    assert lab.cloud_requests == []


def test_all_empty_locals_skip_independent_reviewer_instead_of_fabricating_success(lab):
    lab.local_transform = lambda user, cs: []
    lab.hours()
    report = lab.state()['round']['report']
    assert len(lab.events) == 4 and lab.cloud_requests == []
    assert report['review_complete'] is False and report['status'] == 'failed'
    assert report['agents'][-1]['reason'] == 'specialist_pool_unavailable'
    assert lab.state()['stage_index'] == 9
    lab.tick(9)
    assert lab.events[-1] == ('local_explorer', 'coordinator')


def test_refined_issue_same_draft_digest_and_review_reason_reach_next_actual_http_prompt(lab):
    lab.hours()
    report = lab.state()['round']['report']
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
    assert feedback['specialist_reason'] == 'specialist_failed'
    assert feedback['title'] == '로컬 coordinator 점검 후보'
    assert 'candidate_id' not in feedback
    assert RAW not in json.dumps(feedback) and SECRET not in json.dumps(feedback)


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
    report = lab.state()['round']['report']
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
    assert lab.state()['round']['report']['review_complete'] is True
    for record in lab.state()['round']['report']['proposals']:
        with pytest.raises(imp.ImprovementError):
            imp._eligible(lab.store, record['id'])
    lab.tick(9)
    public = lab.store.read('web/2026-10-15.json')
    assert public['counts']['candidates'] == 4 and public['counts']['eligible'] == 0


@pytest.mark.parametrize('change', ['source', 'mode', 'scope', 'loop_config', 'local_config', 'agent_config', 'workflow_config'])
def test_dependency_change_invalidates_pool_feedback_and_resets_owner_cursor(lab, change):
    lab.hours()
    old = copy.deepcopy(lab.state()['round']['report'])
    if change == 'source':
        (lab.root / FILES[0]).write_text('changed = 1\nchanged = 2\n', encoding='utf-8')
    elif change == 'mode':
        (lab.root / FILES[0]).chmod(0o640)
    elif change == 'scope':
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
    # Scope mutation intentionally bypasses the runner's fixed-fixture assertion.
    local_runner = lab.local
    if change == 'scope':
        def local_runner(role, paths, snapshots, **options):
            lab.active_owner = role
            return local_model.run(role, paths, snapshots, transport=lab.local_http, **options)
    lab.tick(9, local_runner=local_runner)
    state = lab.state()
    assert state['completed'] == []
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


def test_source_change_during_call_cannot_complete_current_review(lab):
    lab.hours(count=8)
    def mutate(role, result, response, options):
        (lab.root / FILES[0]).write_text('changed = 1\nchanged = 2\n', encoding='utf-8')
        return result
    lab.cloud_transform = mutate
    lab.tick(8)
    report = lab.state()['round']['report']
    assert report['review_complete'] is False
    assert 'dependencies_changed_during_call' in report['errors']
    assert all('review' not in r for r in report['proposals'])
    assert lab.state()['completed'] == []


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
    assert report['local_participation'] == []  # old local success is outside window


def test_latest_review_in_half_open_window_selected_and_priority_projection_is_bounded(lab):
    lab.hours(start=8, count=9)  # complete at 16:00; first day's 09:00 is partial
    first = lab.state()['completed'][-1]['scan_id']
    lab.hours(start=17, count=9)  # second review at next day's 01:00
    second = lab.state()['completed'][-1]['scan_id']
    assert second != first
    lab.tick(33)
    report = lab.store.read('days/2026-10-16.json')
    assert report['reviewed_scan_id'] == second
    assert report['date'] == '2026-10-16' and report['review_complete'] is True
    assert len({r['id'] for r in report['proposals']}) == len(report['proposals']) <= 8


def test_review_finishing_exactly_nine_is_excluded_from_that_mornings_report(lab):
    lab.hours(start=1, count=9)  # reviewer is called at 09:00 AFTER the freeze
    report = lab.store.read('days/2026-10-15.json')
    assert report['review_complete'] is False and report['proposals'] == []
    assert lab.state()['round']['report']['review_complete'] is True
    lab.tick(10)
    assert lab.store.read('days/2026-10-15.json') == report


def test_prior_window_owners_not_presented_as_current_success(lab):
    lab.hours(count=8)
    # This review completes in tomorrow's report window; its owners do not.
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
        # The real implementation obtains Store.lock; an outer held lock fails.
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
        calls.append(method)
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
    monkeypatch.setattr(loop, 'tick', injected_tick)
    lab.clock.at(9)
    assert loop.main(['tick']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['publication']['status'] == 'delivered' and calls == ['POST', 'GET']
    lab.clock.at(10)
    loop.main(['tick', '--no-deliver'])
    result = json.loads(capsys.readouterr().out)
    assert 'publication' not in result and calls == ['POST', 'GET']


def test_status_is_read_only_and_korean_status_explains_next_role_budget_and_report(lab):
    result = loop.status(now=START, selected=lab.selected)
    assert not lab.store.exists(loop.STATE_FILE) and lab.events == []
    assert result['claude_remaining_estimated_usd'] is None
    lab.hours()
    before = lab.store.path(loop.STATE_FILE).read_bytes()
    result = loop.status(now=lab.clock(), selected=lab.selected)
    assert result['claude_remaining_estimated_usd'] == pytest.approx(.96)
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
    pid = lab.state()['round']['report']['proposals'][0]['id']
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
    record = lab.state()['round']['report']['proposals'][0]
    state = lab.state()
    state['days']['2026-10-15'].update(claude_spent_usd=1, stopped=True,
                                      stop_reason='daily_budget_overrun')
    lab.store.write(loop.STATE_FILE, state)
    instruction = lab.root.parent / 'synthetic-user-instruction.txt'
    instruction.write_text('제안 ' + record['id'] + ' 승인', encoding='utf-8')
    instruction.chmod(0o600)
    result = imp.approve(record['id'], instruction, now=lab.clock(), selected=lab.selected)
    assert result['status'] == 'approved'
    checked, approval = imp._authorization(lab.store, record['id'], lab.clock())
    assert checked == record and approval['consumption'] == 'unconsumed'
    assert lab.ledger()['claude_spent_usd'] == 1 and len(lab.events) == 9


@pytest.mark.parametrize('dependency', ['loop', 'local'])
def test_original_approval_api_rejects_changed_loop_dependencies(lab, dependency):
    """Task 6 integration contract: ordinary approval must invoke loop freshness."""
    lab.hours()
    record = lab.state()['round']['report']['proposals'][0]
    if dependency == 'loop':
        lab.config['daily_budget_usd'] = .9
        lab.save_loop()
    else:
        lab.local_config['temperature'] = .1
        lab.save_local()
    instruction = lab.root.parent / 'synthetic-user-instruction.txt'
    instruction.write_text('제안 ' + record['id'] + ' 승인', encoding='utf-8')
    instruction.chmod(0o600)
    with pytest.raises(imp.ImprovementError):
        imp.approve(record['id'], instruction, now=lab.clock(), selected=lab.selected)
    assert not lab.store.exists('approvals/' + record['id'] + '.json')


def test_loop_authorization_context_binds_controls_and_legacy_stays_unbound(lab):
    lab.hours()
    report = lab.state()['round']['report']
    assert loop.authorization_context(report) == contract.digest(report['loop_dependencies'])
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
    report = lab.state()['round']['report']
    record = report['proposals'][0]
    instruction = lab.root.parent / 'synthetic-user-instruction.txt'
    instruction.write_text('제안 ' + record['id'] + ' 승인', encoding='utf-8')
    instruction.chmod(0o600)
    imp.approve(record['id'], instruction, now=lab.clock(), selected=lab.selected)
    saved_approval = lab.store.path('approvals/' + record['id'] + '.json').read_bytes()
    lab.config['daily_budget_usd'] = .9
    lab.save_loop()
    lab.hours(start=9, count=9)  # fingerprint reset repeats SAME lines and candidates
    new = lab.store.read('proposals/' + record['id'] + '.json')
    assert new['proposal'] == record and new['scan_id'] != report['scan_id']
    assert lab.store.path('approvals/' + record['id'] + '.json').read_bytes() == saved_approval
    with pytest.raises(imp.ImprovementError):
        imp._authorization(lab.store, record['id'], lab.clock())
