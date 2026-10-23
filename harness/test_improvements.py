"""Offline approval/discovery fixtures; default-scope reads need a full copy.

Other source inputs, authority and HTTP are synthetic.
"""
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from harness import agent_models, git_publish, improvement_report as contract
from harness import improvements as imp, storage, triage, workflow
from harness import review_coverage as coverage
from harness.test_review_coverage import (
    FixtureFS, candidate, add_assessments, capture_result, read_events, stdout,
)


NOW = dt.datetime(2026, 10, 14, 16, 0, tzinfo=dt.timezone.utc)
DATE = '2026-10-15'
RUN_ID = '123456789-abcdef'
FILES = ('AGENTS.md', 'docs/architecture.md', 'docs/harness-design.md',
         'harness/example.py', 'downloader/example.py', 'parser_tidy/example.py',
         'TavernofSoul/example.py', 'parser_tidy/tests/test_import_safety.py')
DOC = {'status': 'not_required', 'files': [],
       'reason': '읽기 전용 분석의 가상 지역 수정 제안으로 구조와 계약 변경이 없어 문서 수정은 필요하지 않습니다.'}




def forbidden(*args, **kwargs):
    pytest.fail('Offline improvement test crossed a model/check/workflow/network boundary')


@pytest.mark.parametrize('targets,reason,message', [
    ('harness/example.py', 'candidate_edit_files_invalid', 'collection outside permitted range'),
    ([], 'candidate_edit_files_invalid', 'collection outside permitted range'),
    ([{}], 'candidate_edit_files_invalid', 'empty or oversized text'),
    ([' harness/example.py'], 'candidate_edit_files_invalid', 'unsafe individual file path'),
    (['harness/example.py'] * 2, 'candidate_edit_files_duplicate', 'duplicate or out-of-scope file'),
    (['harness/outside.py'], 'candidate_edit_files_outside_scope', 'duplicate or out-of-scope file'),
    (['harness/outside.py'] * 2, 'candidate_edit_files_duplicate', 'duplicate or out-of-scope file'),
])
def test_candidate_edit_path_diagnostics_preserve_shared_rejections(targets, reason, message):
    item = candidate()
    item['edit_files'] = targets
    original = copy.deepcopy(item)
    with pytest.raises(contract.ValidationError) as error:
        contract.validate_candidates({'candidates': [item]}, {'harness/example.py': 'one\ntwo\n'})
    assert error.value.reason == reason
    assert str(error.value) == message
    assert item == original


def test_candidate_edit_budget_metadata_does_not_relax_existing_limit():
    item = candidate()
    item['edit_files'] = ['harness/' + 'a' * 195 + str(i) + '.py' for i in range(3)]
    allowed = ['harness/example.py'] + item['edit_files']
    with pytest.raises(contract.ValidationError) as error:
        contract.validate_candidate(item, {'harness/example.py': 'one\ntwo\n'}, allowed)
    assert error.value.reason == 'candidate_edit_files_invalid'
    assert str(error.value) == 'edit file list exceeds one-page character budget'


def test_edit_diagnostics_leave_documentation_and_unknown_failures_unclassified():
    with pytest.raises(contract.ValidationError) as error:
        contract.validate_documentation(dict(DOC, files=['docs/outside.md']), ['docs/architecture.md'])
    assert error.value.reason is None
    item = candidate()
    item['priority'] = 'unknown'
    with pytest.raises(contract.ValidationError) as error:
        contract.validate_candidate(item, {'harness/example.py': 'one\ntwo\n'})
    assert error.value.reason is None
    item['priority'] = 'medium'
    item['edit_files'] = ['harness/unread.py', 'harness/example.py']
    assert contract.validate_candidate(item, {'harness/example.py': 'one\ntwo\n'},
                                       item['edit_files']) == item


@pytest.fixture
def lab(tmp_path, monkeypatch):
    for key in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                'TAVERN_IMPROVEMENT_UNATTENDED', storage.CONFIG_ENV, storage.REPORT_ENV):
        monkeypatch.delenv(key, raising=False)
    config = copy.deepcopy(imp.load_config())
    models = copy.deepcopy(agent_models.load_config())
    root = tmp_path / 'sources'
    root.mkdir(mode=0o700)
    for name in FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('first_value = 1\nsecond_value = 2\n', encoding='utf-8')
        path.chmod(0o644)
    scope = root / 'harness/improvement-scope.txt'
    scope.write_text('\n'.join(FILES) + '\n', encoding='utf-8')
    config_path = root / 'harness/improvement-config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    selected = storage.Storage(root=root,
        artifacts=storage.DirectorySpec(tmp_path / 'artifacts', tmp_path, 0),
        temporary=storage.DirectorySpec(tmp_path / 'contexts', tmp_path, 0),
        config_path=tmp_path / 'synthetic-storage-policy.json', env={}, fs=FixtureFS(tmp_path))
    monkeypatch.setattr(imp, 'ROOT', root)
    monkeypatch.setattr(imp, 'CONFIG', config_path)
    monkeypatch.setattr(imp, 'REPORTS', root / 'logs/harness/improvements')
    monkeypatch.setattr(agent_models, 'load_config', lambda: copy.deepcopy(models))
    monkeypatch.setattr(agent_models, 'load_keys', forbidden)
    monkeypatch.setattr(agent_models, 'run', forbidden)
    monkeypatch.setattr(workflow, 'execute', forbidden)
    monkeypatch.setattr(workflow, 'run_check', forbidden)
    monkeypatch.setattr(triage, 'observe', forbidden)
    monkeypatch.setattr(triage, 'load_policy', lambda: {'max_task_bytes': 24000})
    monkeypatch.setattr(git_publish, 'prepare', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(imp.http.client, 'HTTPSConnection', forbidden)
    return SimpleNamespace(root=root, selected=selected, store=imp.Store(selected),
                           config=config, config_path=config_path, scope=scope, models=models)


class ModelRunner:
    """Real result envelope, deterministic JSON; review IDs come from actual prompts."""
    def __init__(self, lab, candidates=None, transform=None):
        self.lab = lab
        self.candidates = {'coordinator': [candidate()]} if candidates is None else candidates
        self.transform = transform
        self.calls = []
        self.read_results = []

    def __call__(self, role, prompt, keys, **options):
        assert options['write'] is False and options['scoped'] is True
        assert options['timeout'] == self.lab.config['limits']['call_timeout_seconds'] <= 600
        assert os.environ.get('TAVERN_IMPROVEMENT_DISCOVERY') == '1'
        model_root = options['workspace']
        assert self.lab.root not in model_root.parents
        assert model_root not in self.lab.root.parents
        approved = json.loads(re.search(r'Approved readable files \(exact paths\): (.*)\n', prompt).group(1))
        on_disk = sorted(str(p.relative_to(model_root)) for p in model_root.rglob('*') if p.is_file())
        assert on_disk == sorted(p for p in approved if (self.lab.root / p).exists())
        for path in on_disk:
            assert (model_root / path).read_bytes() == (self.lab.root / path).read_bytes()
            assert (model_root / path).stat().st_mode & 0o777 == 0o400
        prior = json.loads(prompt.split('\nPrior candidates: ', 1)[1])
        self.calls.append({'role': role, 'paths': approved, 'prior': prior,
                           'prompt': prompt, 'workspace': model_root, 'options': options})
        if role == 'reviewer':
            response = {'reviews': [dict(candidate_id=p['id'], verdict='eligible',
                                        reason='승인된 실제 줄 범위를 독립적으로 확인한 가상 검토입니다.',
                                        documentation=copy.deepcopy(DOC)) for p in prior],
                        'documentation': copy.deepcopy(DOC)}
            add_assessments(response, options['discovery_review'])
        else:
            response = {'candidates': copy.deepcopy(self.candidates.get(role, []))}
        spec = self.lab.models['roles'][role]
        result = {'role': role, 'provider': spec['provider'], 'model': spec['model'],
                  'status': 'passed', 'response': json.dumps(response, ensure_ascii=False),
                  'cli_estimated_cost_usd': 0.0123}
        result = self.transform(role, result, response, options) if self.transform else result
        if role == 'reviewer':
            capture = options['discovery_review']
            events = read_events(capture, result.get('response', '{}'))
            self.read_results = [copy.deepcopy(event['tool_use_result']['file'])
                                 for event in events if event['type'] == 'user']
            capture.accept(stdout(events))
        return result


def scan(lab, runner=None, **kwargs):
    return imp.discover(runner=runner or ModelRunner(lab), keys={}, now=NOW,
                        selected=lab.selected, **kwargs)


def authorize(lab, *, local_only=False):
    report = scan(lab)
    assert report['status'] == 'scanned' and report['review_complete']
    pid = report['proposals'][0]['id']
    instruction = lab.root.parent / 'user-instruction.txt'
    instruction.write_text('제안 ' + pid + ' 승인. 이 제안의 파일만 변경하세요.', encoding='utf-8')
    instruction.chmod(0o600)
    approved = imp.approve(pid, instruction, local_only, now=NOW, selected=lab.selected)
    assert approved['status'] == 'approved'
    return pid, report['proposals'][0], instruction


def executor_for(calls, status='awaiting_github', error=None):
    def executor(task, files, **options):
        calls.append((task, files, options))
        options['_improvement_guard'](RUN_ID)
        if error:
            raise error
        return {'run_id': RUN_ID, 'status': status,
                'github': {'status': 'awaiting_connector' if status == 'awaiting_github' else 'skipped'}}
    return executor


def test_discovery_exact_role_scope_cross_review_and_no_operating_calls(lab):
    runner = ModelRunner(lab)
    report = scan(lab, runner)
    assert report['status'] == 'scanned' and report['review_complete'] is True
    assert runner.read_results
    for file in runner.read_results:
        # Literal wire expectation for the two LF-terminated Lab source lines.
        assert file['content'] == 'first_value = 1\nsecond_value = 2'
        assert (file['startLine'], file['numLines'], file['totalLines']) == (1, 2, 3)
    assert [c['role'] for c in runner.calls] == list(contract.ROLES)
    shared = ['AGENTS.md', 'docs/architecture.md', 'docs/harness-design.md']
    expected = {
        'coordinator': ['harness/example.py'] + shared,
        'downloader': ['downloader/example.py'] + shared,
        'parser': ['parser_tidy/example.py'] + shared,
        'django': ['TavernofSoul/example.py', 'parser_tidy/tests/test_import_safety.py'] + shared,
        'reviewer': list(FILES),
    }
    for call in runner.calls:
        assert call['paths'] == expected[call['role']]
        assert not call['workspace'].exists()  # isolated contexts are retired
        assert str(lab.root) not in call['prompt']
    assert runner.calls[0]['prior'] == []
    for call in runner.calls[1:-1]:
        assert set(call['prior'][0]) == {'id', 'title', 'issue', 'analogy', 'edit_files'}
    assert 'candidate' in runner.calls[-1]['prior'][0]
    assert 'TAVERN_IMPROVEMENT_DISCOVERY' not in os.environ
    for agent in report['agents']:
        spec = lab.models['roles'][agent['role']]
        assert (agent['provider'], agent['model'], agent['status']) == (spec['provider'], spec['model'], 'succeeded')
        assert agent['cost'] == 0.0123 and agent['cost_status'] == 'cli_estimated_usd'
        assert agent['result']['status'] == 'passed'
        assert agent['elapsed_seconds'] >= 0 and agent['started_at'] and agent['finished_at']
    assert not lab.store.exists('authority.key')
    assert not lab.store.exists('claims/' + report['proposals'][0]['id'] + '.json')
    assert (lab.root / 'harness/example.py').read_text() == 'first_value = 1\nsecond_value = 2\n'
    assert lab.store.path('days/' + DATE + '.json').stat().st_mode & 0o777 == 0o600
    assert lab.store.root.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('failure', ['timeout', 'unavailable', 'failed', 'identity'])
def test_model_failures_keep_actual_metadata_without_false_consensus(lab, failure):
    def transform(role, result, response, options):
        if role != 'reviewer':
            return result
        if failure == 'timeout':
            raise TimeoutError('fixture timeout')
        if failure == 'unavailable':
            raise FileNotFoundError('fixture executable missing')
        result['status'] = 'failed' if failure == 'failed' else 'passed'
        if failure == 'identity':
            result['model'] = 'actual-unexpected-model'
        return result
    runner = ModelRunner(lab, transform=transform)
    report = scan(lab, runner)
    assert len(runner.calls) == 5
    assert report['status'] == 'partial' and report['review_complete'] is False
    agent = report['agents'][-1]
    assert agent['status'] == ('unavailable' if failure in ('timeout', 'unavailable') else 'failed')
    assert agent['error_type']
    if failure == 'identity':
        assert agent['model'] == 'actual-unexpected-model'
        assert agent['result']['model'] == 'actual-unexpected-model'
    if failure == 'failed':
        assert agent['result']['status'] == 'failed' and agent['cost'] == 0.0123
    assert all('review' not in p for p in report['proposals'])
    web = imp.report(DATE, selected=lab.selected)
    assert web['counts']['eligible'] == 0
    assert web['proposals'][0]['review']['verdict'] == 'needs_evidence'
    with pytest.raises(ValueError):
        imp.approve(report['proposals'][0]['id'], lab.root / 'absent', now=NOW, selected=lab.selected)


@pytest.mark.parametrize('bad', [
    'extra_field', 'too_many', 'evidence_path', 'evidence_missing', 'end_range', 'zero_line',
    'reverse_range', 'bool_line', 'edit_scope', 'measured_without_evidence', 'oversized', 'malformed',
    'invalid_type', 'empty', 'control', 'invalid_utf8', 'nested_unknown',
])
def test_bad_specialist_schema_and_evidence_are_not_proposals(lab, bad):
    def transform(role, result, response, options):
        if role != 'coordinator':
            return result
        c = response['candidates'][0]
        if bad == 'extra_field':
            c['approved'] = True
        elif bad == 'too_many':
            response['candidates'] = [candidate(title='개선 ' + str(i)) for i in range(3)]
        elif bad == 'evidence_path':
            c['evidence'][0]['path'] = 'downloader/example.py'
        elif bad == 'evidence_missing':
            c['evidence'][0]['path'] = 'harness/absent.py'
        elif bad == 'end_range':
            c['evidence'][0]['end_line'] = 3
        elif bad == 'zero_line':
            c['evidence'][0]['start_line'] = 0
        elif bad == 'reverse_range':
            c['evidence'][0].update(start_line=2, end_line=1)
        elif bad == 'bool_line':
            c['evidence'][0]['start_line'] = True
        elif bad == 'edit_scope':
            c['edit_files'] = ['downloader/example.py']
        elif bad == 'measured_without_evidence':
            c['benefit']['kind'] = 'measured'
        elif bad == 'oversized':
            c['issue'] = '가' * 1601
        elif bad == 'invalid_type':
            c['issue'] = ['가상 설명']
        elif bad == 'empty':
            c['issue'] = ' \n\t'
        elif bad == 'control':
            c['issue'] = '합성 설명\x00'
        elif bad == 'invalid_utf8':
            c['issue'] = '합성 설명\ud800'
        elif bad == 'nested_unknown':
            c['evidence'][0]['approved'] = True
        result['response'] = '{broken' if bad == 'malformed' else json.dumps(response)
        return result
    pair = [candidate(), candidate(title='두 번째 합성 후보')]
    report = scan(lab, ModelRunner(lab, {'coordinator': pair}, transform=transform))
    assert report['status'] == 'partial'
    assert report['proposals'] == []
    assert report['agents'][0]['status'] == 'failed'
    assert imp.report(DATE, selected=lab.selected)['counts']['eligible'] == 0
    assert imp.daily(runner=forbidden, keys={}, now=NOW,
                     selected=lab.selected)['scan_id'] == report['scan_id']


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'unknown', 'extra_field',
                                  'doc_missing', 'doc_outside', 'doc_omitted', 'doc_vague', 'doc_required'])
def test_incomplete_review_and_documentation_judgments_fail_closed(lab, bad):
    def transform(role, result, response, options):
        if role != 'reviewer':
            return result
        review = response['reviews'][0]
        if bad == 'missing':
            response['reviews'] = []
        elif bad == 'duplicate':
            response['reviews'].append(copy.deepcopy(review))
        elif bad == 'unknown':
            review['candidate_id'] = 'IMP-' + '0' * 16
        elif bad == 'extra_field':
            review['approved'] = True
        elif bad == 'doc_missing':
            review['documentation'] = {'status': 'missing', 'files': ['docs/architecture.md'], 'reason': DOC['reason']}
        elif bad == 'doc_outside':
            review['documentation'] = {'status': 'required', 'files': ['docs/unapproved.md'], 'reason': DOC['reason']}
        elif bad == 'doc_omitted':
            del review['documentation']
        elif bad == 'doc_vague':
            review['documentation']['reason'] = '없음'
        elif bad == 'doc_required':
            review['documentation'] = {'status': 'required', 'files': ['docs/architecture.md'], 'reason': DOC['reason']}
        result['response'] = json.dumps(response)
        return result
    report = scan(lab, ModelRunner(lab, transform=transform))
    assert report['review_complete'] is False and report['status'] == 'partial'
    assert 'review' not in report['proposals'][0]
    assert imp.report(DATE, selected=lab.selected)['counts']['eligible'] == 0


@pytest.mark.parametrize('verdict', ['rejected', 'needs_evidence'])
def test_valid_negative_review_is_visible_but_never_authorizable(lab, verdict):
    def transform(role, result, response, options):
        if role == 'reviewer':
            response['reviews'][0]['verdict'] = verdict
            result['response'] = json.dumps(response)
        return result
    report = scan(lab, ModelRunner(lab, transform=transform))
    assert report['status'] == 'scanned' and report['review_complete']
    proposal = report['proposals'][0]
    assert proposal['review']['verdict'] == verdict
    with pytest.raises(ValueError):
        imp.approve(proposal['id'], lab.root / 'absent', now=NOW, selected=lab.selected)


def test_required_documentation_is_eligible_only_in_exact_edit_scope(lab):
    c = candidate()
    c['edit_files'].append('docs/architecture.md')
    def transform(role, result, response, options):
        if role == 'reviewer':
            doc = {'status': 'required', 'files': ['docs/architecture.md'],
                   'reason': '가상 제안이 구조에 영향을 주므로 승인 범위 안의 설계 문서를 함께 수정해야 합니다.'}
            response['reviews'][0]['documentation'] = doc
            response['documentation'] = doc
            result['response'] = json.dumps(response)
        return result
    report = scan(lab, ModelRunner(lab, {'coordinator': [c]}, transform))
    assert report['review_complete'] and report['proposals'][0]['review']['verdict'] == 'eligible'
    assert report['documentation']['files'] == ['docs/architecture.md']


def test_kst_daily_idempotency_and_next_day_boundary(lab):
    runner = ModelRunner(lab)
    first = imp.daily(runner=runner, keys={}, now=NOW, selected=lab.selected)
    assert first['date'] == DATE and len(runner.calls) == 5
    # UTC date changes while the local Korean date stays the same.
    same_day = NOW + dt.timedelta(hours=9)
    again = imp.daily(runner=forbidden, keys={}, now=same_day, selected=lab.selected)
    assert first == again
    saved = lab.store.read('days/' + DATE + '.json')
    assert saved['scan_id'] == first['scan_id']
    next_day = imp.daily(runner=runner, keys={}, now=NOW + dt.timedelta(days=1), selected=lab.selected)
    assert next_day['date'] == '2026-10-16' and next_day['scan_id'] != first['scan_id']
    assert len(runner.calls) == 10


def test_failed_daily_persists_and_only_manual_scan_retries(lab):
    calls = []
    def failed(*args, **kwargs):
        calls.append(args[0])
        raise TimeoutError('synthetic failure')
    first = imp.daily(runner=failed, keys={}, now=NOW, selected=lab.selected)
    assert first['status'] == 'failed' and len(calls) == 5
    assert imp.daily(runner=forbidden, keys={}, now=NOW, selected=lab.selected) == first
    web = imp.report(DATE, selected=lab.selected)
    assert web['status'] == 'failed' and web['proposals'] == []
    assert '끝나지' in web['summary']
    retried = scan(lab)
    assert retried['status'] == 'scanned' and retried['scan_id'] != first['scan_id']
    assert lab.store.read('scans/' + first['scan_id'] + '.json')['status'] == 'failed'


@pytest.mark.parametrize('decision', ['approve', 'reject'])
def test_stable_ids_rediscovery_does_not_overwrite_human_state(lab, decision):
    pid, original, instruction = authorize(lab)
    if decision == 'reject':
        imp.reject(pid, now=NOW, selected=lab.selected)
    before = {name: lab.store.read(name + '/' + pid + '.json') for name in ('approvals', 'decisions')}
    newer = scan(lab)
    assert newer['proposals'][0] == original
    for name, value in before.items():
        assert lab.store.read(name + '/' + pid + '.json') == value
    state = imp.status(DATE, selected=lab.selected)
    assert state['human_state'][pid]['decisions']['status'] == ('approved' if decision == 'approve' else 'rejected')
    assert instruction.read_text() not in json.dumps(state, ensure_ascii=False)
    if decision == 'reject':
        with pytest.raises(ValueError):
            imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden)


@pytest.mark.parametrize('project_lock', [False, True])
def test_discovery_refuses_overlapping_discovery_workflow_or_cleanup_lock(lab, project_lock):
    with lab.store.lock(project=project_lock):
        with pytest.raises(imp.ImprovementError, match='already running'):
            scan(lab, forbidden)
    assert not lab.store.exists('latest.json')
    assert scan(lab)['status'] == 'scanned'


def test_source_change_during_discovery_invalidates_review(lab):
    def transform(role, result, response, options):
        if role == 'reviewer':
            (lab.root / 'harness/example.py').write_text('user edit during scan\n')
        return result
    report = scan(lab, ModelRunner(lab, transform=transform))
    assert report['status'] == 'partial' and not report['review_complete']
    assert 'source_changed_during_scan' in report['errors']
    assert 'review' not in report['proposals'][0]


@pytest.mark.parametrize('mutation', ['content', 'mode'])
def test_changed_read_only_context_is_model_failure(lab, mutation):
    source = lab.root / 'harness/example.py'
    original_bytes = source.read_bytes()
    original_mode = source.stat().st_mode

    def transform(role, result, response, options):
        if role == 'coordinator':
            path = options['workspace'] / 'harness/example.py'
            path.chmod(0o600)
            if mutation == 'content':
                path.write_text('unauthorized mutation\n')
                path.chmod(0o400)
        return result
    report = scan(lab, ModelRunner(lab, transform=transform))
    assert report['agents'][0]['status'] == 'failed' and not report['proposals']
    assert source.read_bytes() == original_bytes
    assert source.stat().st_mode == original_mode


@pytest.mark.parametrize('setting', [('max_role_calls', 6), ('call_timeout_seconds', 601),
                                      ('max_candidates_per_specialist', 3), ('max_retries', 1),
                                      ('max_reported_proposals', 4)])
def test_unbounded_configuration_rejected_before_models(lab, setting):
    name, value = setting
    config = copy.deepcopy(lab.config)
    config['limits'][name] = value
    lab.config_path.write_text(json.dumps(config))
    with pytest.raises(contract.ValidationError):
        scan(lab, forbidden)


@pytest.mark.parametrize('text', ['{"x":1,"x":2}', '{"x":NaN}', '```json\n{}\n```', '{} trailing', '\ud800'])
def test_strict_json_entry_point_rejects_ambiguous_or_non_utf8_input(text):
    with pytest.raises(contract.ValidationError):
        contract.parse_json(text)


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
@pytest.mark.parametrize('as_bytes', [False, True])
def test_model_envelope_preserves_json_content_with_literal_backticks(newline, as_bytes):
    original = candidate()
    original['issue'] = '합성 문자열의 ```json\n{}\n``` 및 ``` 표시는 데이터입니다.'
    bare = json.dumps({'candidates': [original]}, ensure_ascii=False)
    fenced = ' \t\r\n```json' + newline + bare + newline + '```\r\n\t '
    if as_bytes:
        bare, fenced = bare.encode('utf-8'), fenced.encode('utf-8')
    assert imp._parse_model_response(fenced, 65536) == contract.parse_json(bare)


@pytest.mark.parametrize('fenced_role', ['coordinator', 'reviewer', 'all'])
def test_fenced_model_responses_keep_proposal_and_review_identity(lab, fenced_role):
    bare = scan(lab)
    raw = {}

    def transform(role, result, response, options):
        if fenced_role in (role, 'all'):
            result['response'] = ' \t\n```json\n' + result['response'] + '\n```\r\n '
        raw[role] = copy.deepcopy(result)
        return result

    runner = ModelRunner(lab, transform=transform)
    wrapped = scan(lab, runner)
    assert bare['status'] == wrapped['status'] == 'scanned'
    assert bare['review_complete'] and wrapped['review_complete']
    assert bare['proposals'] == wrapped['proposals']
    assert contract.digest(bare['proposals']) == contract.digest(wrapped['proposals'])
    assert bare['documentation'] == wrapped['documentation']
    assert len(runner.calls) == 5
    for agent in wrapped['agents']:
        assert agent['status'] == 'succeeded'
        assert agent['result'] == raw[agent['role']]
    public = imp.report(DATE, selected=lab.selected)
    assert '```json' not in contract.canonical_json(public).decode('utf-8')
    assert not lab.store.exists('authority.key')
    for directory in ('approvals', 'decisions', 'claims', 'executions'):
        assert not lab.store.exists(directory + '/' + wrapped['proposals'][0]['id'] + '.json')


@pytest.mark.parametrize('role', ['coordinator', 'reviewer'])
@pytest.mark.parametrize('bad', [
    'untagged', 'unknown_tag', 'uppercase_tag', 'tag_space', 'four_backticks',
    'inline', 'cr_only', 'unicode_outer_space', 'prose_before', 'prose_after',
    'multiple', 'unclosed', 'truncated_json', 'trailing_json', 'duplicate',
    'nan', 'infinity', 'overflow', 'invalid_utf8', 'invalid_utf8_bytes',
])
def test_invalid_model_envelope_and_json_keep_partial_failure(lab, role, bad):
    def transform(current, result, response, options):
        if current != role:
            return result
        text = result['response']
        wrapped = '```json\n' + text + '\n```'
        broken_json = {
            'duplicate': '{"x":1,"x":2}', 'nan': '{"x":NaN}',
            'infinity': '{"x":Infinity}', 'overflow': '{"x":1e9999}',
        }
        cases = {
            'untagged': '```\n' + text + '\n```',
            'unknown_tag': wrapped.replace('```json', '```python', 1),
            'uppercase_tag': wrapped.replace('```json', '```JSON', 1),
            'tag_space': wrapped.replace('```json', '```json ', 1),
            'four_backticks': '`' + wrapped + '`',
            'inline': '```json ' + text + '```',
            'cr_only': '```json\r' + text + '\r```',
            'unicode_outer_space': '\u00a0' + wrapped,
            'prose_before': 'Explanation\n' + wrapped,
            'prose_after': wrapped + '\nExplanation',
            'multiple': wrapped + '\n' + wrapped,
            'unclosed': wrapped[:-1],
            'truncated_json': '```json\n' + text[:-1] + '\n```',
            'trailing_json': '```json\n' + text + '\n{}\n```',
            'invalid_utf8': '```json\n"\ud800"\n```',
            'invalid_utf8_bytes': b'```json\n"\xff"\n```',
        }
        if bad in broken_json:
            result['response'] = '```json\n' + broken_json[bad] + '\n```'
        else:
            result['response'] = cases[bad]
        # Exercise the transport parser directly too: metadata retention may
        # independently reject invalid UTF-8 before reaching this boundary.
        with pytest.raises(contract.ValidationError):
            imp._parse_model_response(result['response'], lab.config['limits']['max_response_bytes'])
        return result

    runner = ModelRunner(lab, transform=transform)
    report = scan(lab, runner)
    assert report['status'] == 'partial' and len(runner.calls) == 5
    failed = next(a for a in report['agents'] if a['role'] == role)
    # Invalid Unicode can fail inside the synthetic Read transport before
    # it returns an envelope; that attempt is unavailable, never successful.
    expected = 'unavailable' if role == 'reviewer' and bad == 'invalid_utf8' else 'failed'
    assert failed['status'] == expected and failed['error_type']
    public = imp.report(DATE, selected=lab.selected)
    assert public['counts']['eligible'] == 0
    if role == 'reviewer':
        assert not report['review_complete'] and len(report['proposals']) == 1
        assert 'review' not in report['proposals'][0]
        assert public['proposals'][0]['review']['verdict'] == 'needs_evidence'
    else:
        assert report['review_complete'] and report['proposals'] == []
        assert runner.calls[-1]['prior'] == []
    assert imp.daily(runner=forbidden, keys={}, now=NOW,
                     selected=lab.selected)['scan_id'] == report['scan_id']
    assert not lab.store.exists('authority.key')


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
@pytest.mark.parametrize('as_bytes', [False, True])
def test_original_model_bytes_include_whitespace_and_fence(newline, as_bytes):
    bare = '{"text":"한글"}'
    wrapped = ' \t```json' + newline + bare + newline + '```\r\n '
    raw_size = len(wrapped.encode('utf-8'))
    assert raw_size > len(bare.encode('utf-8'))
    value = wrapped.encode('utf-8') if as_bytes else wrapped
    assert imp._parse_model_response(value, raw_size) == contract.parse_json(bare)
    with pytest.raises(contract.ValidationError):
        imp._parse_model_response(value, raw_size - 1)
    # Plain JSON outer whitespace consumes the same original-byte budget.
    plain = ' \t' + bare + '\r\n '
    with pytest.raises(contract.ValidationError):
        imp._parse_model_response(plain, len(plain.encode('utf-8')) - 1)


@pytest.mark.parametrize('excess', [False, True])
def test_configured_model_byte_limit_applies_before_unwrapping(lab, excess):
    raw_size = 4096
    config = copy.deepcopy(lab.config)
    config['limits']['max_response_bytes'] = raw_size
    lab.config_path.write_text(json.dumps(config))

    def transform(role, result, response, options):
        if role == 'coordinator':
            wrapped = '```json\n' + result['response'] + '\n```'
            padding = raw_size - len(wrapped.encode('utf-8'))
            assert padding > 0
            result['response'] = ' ' * (padding + int(excess)) + wrapped
        return result

    runner = ModelRunner(lab, transform=transform)
    report = scan(lab, runner)
    assert len(runner.calls) == 5
    if excess:
        assert report['status'] == 'partial' and not report['proposals']
        assert report['agents'][0]['status'] == 'failed'
    else:
        assert report['status'] == 'scanned' and report['review_complete']
        assert len(report['proposals']) == 1


@pytest.mark.parametrize('source', ['config', 'public', 'storage'])
def test_model_fence_tolerance_never_changes_other_json_entry_points(lab, source):
    if source == 'config':
        value = lab.config
    elif source == 'public':
        value = contract.build_web_report(private_report())
    else:
        value = {'synthetic': 'private record'}
    bare = contract.canonical_json(value)
    assert contract.parse_json(bare) == value
    fenced = b'```json\n' + bare + b'\n```'
    with pytest.raises(contract.ValidationError):
        contract.parse_json(fenced)
    if source == 'config':
        lab.config_path.write_bytes(fenced)
        with pytest.raises(contract.ValidationError):
            imp.load_config()
    elif source == 'public':
        with pytest.raises(contract.ValidationError):
            contract.validate_web_report(fenced.decode('utf-8'))
    else:
        lab.store.write_bytes('synthetic-transport-record.json', bare)
        assert lab.store.read('synthetic-transport-record.json') == value
        lab.store.write_bytes('synthetic-transport-record.json', fenced)
        with pytest.raises(ValueError):
            lab.store.read('synthetic-transport-record.json')


@pytest.mark.parametrize('kind', ['absent', 'empty', 'public', 'symlink', 'invalid_utf8', 'too_large'])
def test_approval_requires_private_explicit_utf8_instruction(lab, kind):
    pid = scan(lab)['proposals'][0]['id']
    path = lab.root.parent / 'instruction.txt'
    if kind != 'absent':
        path.write_bytes(b'\xff' if kind == 'invalid_utf8' else
                         b'x' * 16385 if kind == 'too_large' else
                         b' \n' if kind == 'empty' else '해당 제안을 승인합니다.'.encode('utf-8'))
        path.chmod(0o644 if kind == 'public' else 0o600)
        if kind == 'symlink':
            link = lab.root.parent / 'instruction-link.txt'
            link.symlink_to(path)
            path = link
    with pytest.raises((ValueError, OSError, UnicodeError)):
        imp.approve(pid, path, now=NOW, selected=lab.selected)
    assert not lab.store.exists('approvals/' + pid + '.json')
    assert not lab.store.exists('authority.key')


@pytest.mark.parametrize('pid', ['*', 'all', '', 'IMP-' + 'a' * 15, '../proposal'])
def test_approve_never_accepts_wildcard_or_unspecified_id(lab, pid):
    with pytest.raises(ValueError):
        imp.approve(pid, lab.root / 'missing', now=NOW, selected=lab.selected)


def test_eligible_model_verdict_is_not_a_human_approval(lab):
    proposal = scan(lab)['proposals'][0]
    assert proposal['review']['verdict'] == 'eligible'
    with pytest.raises((ValueError, OSError)):
        imp.execute(proposal['id'], now=NOW, selected=lab.selected, executor=forbidden)
    assert not lab.store.exists('claims/' + proposal['id'] + '.json')


@pytest.mark.parametrize('change', ['unsigned', 'forged_signature', 'wrong_digest', 'edit_scope',
                                    'source_fingerprints', 'authority', 'publication', 'consumed',
                                    'expired', 'future', 'overlong', 'review_digest', 'rejected'])
def test_invalid_authorization_rejected_before_workflow_or_write_calls(lab, change):
    pid, record, _ = authorize(lab)
    name = 'approvals/' + pid + '.json'
    signed = lab.store.read(name)
    value = lab.store.verify(signed)
    if change == 'unsigned':
        lab.store.write(name, value)
    elif change == 'forged_signature':
        signed['instruction'] = '모델이 작성한 승인'
        lab.store.write(name, signed)
    elif change == 'rejected':
        imp.reject(pid, now=NOW, selected=lab.selected)
    else:
        if change == 'wrong_digest':
            value['proposal_digest'] = '0' * 64
        elif change == 'edit_scope':
            value['allowed_edit_files'].append('downloader/example.py')
        elif change == 'source_fingerprints':
            value['source_fingerprints']['AGENTS.md']['mode'] = 0o600
        elif change == 'authority':
            value['authority'] = 'model'
        elif change == 'publication':
            value['publication'] = 'merge-without-ci'
        elif change == 'consumed':
            value['consumption'] = 'consumed'
        elif change == 'expired':
            value['expires_at'] = NOW.isoformat()
        elif change == 'future':
            value['issued_at'] = (NOW + dt.timedelta(seconds=1)).isoformat()
        elif change == 'overlong':
            value['expires_at'] = (NOW + dt.timedelta(days=8)).isoformat()
        elif change == 'review_digest':
            value['review_digest'] = '0' * 64
        # Re-sign invalid bodies to exercise semantic binding separately from
        # the integrity check. A model never has access to this test seam/key.
        lab.store.write(name, lab.store.sign(value))
    with pytest.raises((ValueError, OSError)):
        imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden)
    assert not lab.store.exists('claims/' + pid + '.json')


@pytest.mark.parametrize('change', ['content', 'mode', 'missing', 'scope_content', 'scope_mode',
                                    'config', 'proposal_digest', 'proposal_edit', 'review', 'scan_review'])
def test_stale_sources_scope_and_proposal_fail_before_claim_or_write(lab, change):
    pid, _, _ = authorize(lab)
    # AGENTS.md is a read dependency, deliberately not an approved edit file.
    source = lab.root / 'AGENTS.md'
    if change == 'content':
        source.write_text('human changed a read dependency\n')
    elif change == 'mode':
        source.chmod(0o600)
    elif change == 'missing':
        source.unlink()
    elif change == 'scope_content':
        lab.scope.write_text('\n'.join(reversed(FILES)) + '\n')
    elif change == 'scope_mode':
        lab.scope.chmod(0o600 if lab.scope.stat().st_mode & 0o777 != 0o600 else 0o644)
    elif change == 'config':
        config = copy.deepcopy(lab.config)
        config['limits']['call_timeout_seconds'] = 599
        lab.config_path.write_text(json.dumps(config))
    else:
        name = 'proposals/' + pid + '.json'
        saved = lab.store.read(name)
        if change == 'proposal_digest':
            saved['proposal']['digest'] = '0' * 64
        elif change == 'proposal_edit':
            saved['proposal']['candidate']['edit_files'].append('downloader/example.py')
        elif change == 'review':
            saved['proposal']['review']['reason'] = 'Modified review after authorization.'
        else:
            scan_name = 'scans/' + saved['scan_id'] + '.json'
            provenance = lab.store.read(scan_name)
            provenance['agents'][-1]['status'] = 'failed'
            lab.store.write(scan_name, provenance)
        lab.store.write(name, saved)
    with pytest.raises((ValueError, OSError)):
        imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden)
    assert not lab.store.exists('claims/' + pid + '.json')


def test_newly_created_previously_missing_dependency_invalidates_approval(lab):
    lab.scope.write_text('\n'.join(FILES + ('harness/missing.py',)) + '\n')
    pid, record, _ = authorize(lab)
    assert record['source_fingerprints']['harness/missing.py']['exists'] is False
    (lab.root / 'harness/missing.py').write_text('new user file\n')
    with pytest.raises(ValueError, match='dependencies changed'):
        imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden)


@pytest.mark.parametrize('flag', ['TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY'])
@pytest.mark.parametrize('action', ['discover', 'daily', 'status', 'report', 'approve', 'reject', 'execute', 'deliver'])
def test_children_cannot_orchestrate_or_access_trusted_operations(lab, monkeypatch, flag, action):
    monkeypatch.setenv(flag, '1')
    pid = 'IMP-' + 'a' * 16
    actions = {
        'discover': lambda: scan(lab, forbidden),
        'daily': lambda: imp.daily(runner=forbidden, keys={}, now=NOW, selected=lab.selected),
        'status': lambda: imp.status(DATE, selected=lab.selected),
        'report': lambda: imp.report(DATE, selected=lab.selected),
        'approve': lambda: imp.approve(pid, lab.root / 'absent', selected=lab.selected),
        'reject': lambda: imp.reject(pid, selected=lab.selected),
        'execute': lambda: imp.execute(pid, selected=lab.selected, executor=forbidden),
        'deliver': lambda: imp.deliver_report(DATE, selected=lab.selected, transport=forbidden),
    }
    with pytest.raises(imp.ImprovementError, match='workers cannot orchestrate'):
        actions[action]()
    assert not lab.store.root.exists()


@pytest.mark.parametrize('action', ['approve', 'reject', 'execute', 'discover'])
def test_unattended_marker_blocks_approval_execution_and_manual_retries(lab, monkeypatch, action):
    pid, _, instruction = authorize(lab)
    monkeypatch.setenv('TAVERN_IMPROVEMENT_UNATTENDED', '1')
    actions = {
        'approve': lambda: imp.approve(pid, instruction, now=NOW, selected=lab.selected),
        'reject': lambda: imp.reject(pid, now=NOW, selected=lab.selected),
        'execute': lambda: imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden),
        'discover': lambda: scan(lab, forbidden),
    }
    with pytest.raises(imp.ImprovementError, match='Unattended'):
        actions[action]()
    # Scheduled reporting retains read-only authority, including a same-day hit.
    assert imp.daily(runner=forbidden, keys={}, now=NOW, selected=lab.selected)['status'] == 'scanned'
    assert not lab.store.exists('claims/' + pid + '.json')


@pytest.mark.parametrize('local_only', [False, True])
@pytest.mark.parametrize('status', ['awaiting_github', 'passed', 'failed', 'interrupted'])
def test_exact_immutable_task_files_publication_and_run_status_reach_workflow(lab, local_only, status):
    pid, record, instruction = authorize(lab, local_only=local_only)
    approval = lab.store.verify(lab.store.read('approvals/' + pid + '.json'))
    assert approval['publication'] == ('local-only' if local_only else imp.PUBLICATION)
    assert approval['allowed_edit_files'] == ['harness/example.py']
    assert approval['source_fingerprints'] == record['source_fingerprints']
    assert approval['instruction'] == instruction.read_text()
    assert dt.datetime.fromisoformat(approval['expires_at']) - NOW == dt.timedelta(days=7)
    calls = []
    outcome = imp.execute(pid, now=NOW, selected=lab.selected,
                          executor=executor_for(calls, status=status))
    assert len(calls) == 1
    task, files, options = calls[0]
    assert files == ['harness/example.py']
    assert task == imp._task(record, approval)
    assert contract.canonical_json(record['candidate']).decode('utf-8') in task
    assert pid in task and record['digest'] in task and instruction.read_text() in task
    assert set(options) == {'no_git', '_improvement_guard'}
    assert options['no_git'] is local_only
    assert outcome['status'] == status and outcome['run_id'] == RUN_ID
    claim = lab.store.verify(lab.store.read('claims/' + pid + '.json'))
    assert claim['status'] == 'consumed' and claim['workflow_status'] == status
    assert claim['task_digest'] == hashlib.sha256(task.encode('utf-8')).hexdigest()
    assert claim['run_id'] == RUN_ID
    assert lab.store.read('executions/' + pid + '.json') == outcome
    assert imp.status(DATE, selected=lab.selected)['human_state'][pid]['executions']['run_id'] == RUN_ID
    with pytest.raises(ValueError, match='claimed'):
        imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden)
    with pytest.raises(ValueError, match='reconciliation'):
        imp.approve(pid, instruction, now=NOW, selected=lab.selected)


@pytest.mark.parametrize('failure', ['exception', 'interrupt', 'no_guard', 'wrong_run', 'guard_twice', 'stale_after_claim'])
def test_claimed_failure_remains_consumed_and_cannot_be_replayed(lab, failure):
    pid, _, _ = authorize(lab)
    write_calls = []
    def executor(task, files, **options):
        guard = options['_improvement_guard']
        if failure == 'stale_after_claim':
            (lab.root / 'AGENTS.md').write_text('changed in handoff window\n')
        if failure != 'no_guard':
            guard(RUN_ID)
        if failure == 'guard_twice':
            guard(RUN_ID)
        if failure not in ('stale_after_claim', 'guard_twice', 'no_guard'):
            write_calls.append(files)
        if failure == 'exception':
            raise RuntimeError('fixture failure')
        if failure == 'interrupt':
            raise KeyboardInterrupt()
        return {'status': 'passed', 'run_id': '987654321-abcdef' if failure == 'wrong_run' else RUN_ID}
    outcome = imp.execute(pid, now=NOW, selected=lab.selected, executor=executor)
    assert outcome['status'] == ('interrupted' if failure == 'interrupt' else 'failed')
    assert outcome['error_type']
    assert lab.store.verify(lab.store.read('claims/' + pid + '.json'))['status'] == 'consumed'
    if failure in ('stale_after_claim', 'guard_twice', 'no_guard'):
        assert write_calls == []
    with pytest.raises(ValueError):
        imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden)


# Task-6 documentation review: this changes publication recovery and signed
# authorization dependencies. The separately assigned docs/improvements.md,
# docs/workflow.md, docs/harness-design.md and ADR0017 must describe these
# contracts. These offline specifications do not claim checks or activation.
MORNING = NOW.astimezone(contract.KST).replace(hour=9, minute=0, second=0, microsecond=0)


def loop_pool(lab, candidates=None):
    """A genuine validated legacy fixture converted to private loop provenance.

    Deliberately seed the previous day, so today's morning starts without a
    daily artifact. Production rounds never materialize a day before 09:00.
    No private runtime config, host policy, network or real model is used.
    """
    from harness import improvement_loop as loop
    value = imp.discover(runner=ModelRunner(lab, candidates), keys={}, now=NOW - dt.timedelta(hours=5),
                         selected=lab.selected)
    dependencies = {key: value[key] for key in
                    ('scope_fingerprint', 'source_fingerprints', 'config_fingerprint')}
    dependencies.update(loop_config_fingerprint=contract.digest({'budget': 1}),
                        local_config_fingerprint=contract.digest({'model': 'synthetic-local'}),
                        agent_config_fingerprint=contract.digest(lab.models),
                        workflow_config_fingerprint=contract.digest({'synthetic': True}),
                        review_protocol=coverage.VERSION)
    value.update(loop_engine=loop.STATE_VERSION, loop_dependencies=dependencies,
                 review_completed_at=NOW.isoformat(), local_participation=[{
                     'provider': 'mlx-vlm', 'model': 'synthetic-local', 'stage': 'local_explorer',
                     'owner_role': 'coordinator', 'status': 'succeeded', 'called': True,
                     'started_at': value['generated_at'], 'finished_at': value['generated_at'],
                     'read_windows': [{'path': 'harness/example.py', 'start_line': 1, 'end_line': 2}],
                     'cost': None, 'cost_status': 'not_metered'}])
    for agent in value['agents']:
        agent.update(started_at=value['generated_at'], finished_at=NOW.isoformat())
    coverage.attach(value, value['source_review'])
    lab.store.write('scans/' + value['scan_id'] + '.json', value)
    loop._save_proposals(lab.store, value)
    state = dict(loop._new_state(), round={'report': value}, completed=[{
        'scan_id': value['scan_id'], 'at': NOW.isoformat(),
        'dependency_digest': contract.digest(dependencies)}])
    loop._import_participation(state, value)
    return loop, value, state, dependencies


def freeze_morning(lab, loop, state, dependencies, now=MORNING):
    with lab.store.lock(), lab.store.lock(project=True):
        return loop._freeze_morning(lab.store, state, now, lab.config, dependencies)


def test_morning_selects_latest_current_review_and_keeps_all_provenance(lab):
    paths = {'coordinator': 'harness/example.py', 'downloader': 'downloader/example.py',
             'parser': 'parser_tidy/example.py', 'django': 'TavernofSoul/example.py'}
    candidates = {r: [candidate(p, '점검 제안 ' + r + str(i)) for i in range(2)]
                  for r, p in paths.items()}
    loop, pool, state, deps = loop_pool(lab, candidates)
    selected = copy.deepcopy(pool)
    selected['scan_id'] = '223456789-abcdef'
    selected['review_completed_at'] = (MORNING - dt.timedelta(minutes=30)).isoformat()
    # A review may finish today after downtime while an owner ran before the
    # window. It must stay privately provable and publicly incomplete.
    selected['agents'][0]['started_at'] = (MORNING - dt.timedelta(days=2)).isoformat()
    coverage.attach(selected, selected['source_review'])
    lab.store.write('scans/' + selected['scan_id'] + '.json', selected)
    loop._save_proposals(lab.store, selected)
    loop._import_participation(state, selected)
    state['completed'].append({'scan_id': selected['scan_id'], 'at': selected['review_completed_at'],
                               'dependency_digest': contract.digest(deps)})
    for scan_id, at, digest in (
            ('323456789-abcdef', MORNING - dt.timedelta(minutes=1), contract.digest({'changed': True})),
            ('423456789-abcdef', MORNING, contract.digest(deps))):
        excluded = copy.deepcopy(pool)
        excluded['scan_id'] = scan_id
        lab.store.write('scans/' + scan_id + '.json', excluded)
        state['completed'].append({'scan_id': scan_id, 'at': at.isoformat(), 'dependency_digest': digest})
    assert freeze_morning(lab, loop, state, deps, MORNING - dt.timedelta(seconds=1)) is None
    journal = freeze_morning(lab, loop, state, deps)
    private = lab.store.read('days/' + DATE + '.json')
    public = imp.status(DATE, selected=lab.selected)['report']
    assert journal['status'] == 'publication_pending'
    assert private['reviewed_scan_id'] == selected['scan_id']
    assert private['reviewed_agents'][0]['status'] == 'succeeded'
    # Another actual round covered this owner inside the window.
    assert public['agents'][0]['status'] == 'succeeded'
    assert public['counts'] == {'candidates': 8, 'reported': 3, 'additional_candidates': 5, 'eligible': 8}
    assert private['local_participation'][0]['model'] == 'synthetic-local'
    assert all(a['provider'] != 'mlx-vlm' for a in public['agents'])
    public_text = json.dumps(public)
    for sensitive in ('local_participation', 'loop_dependencies', 'synthetic-local', 'cost_status'):
        assert sensitive not in public_text
    for record in private['proposals']:
        assert imp._eligible(lab.store, record['id']) == record
        assert lab.store.exists('scans/' + lab.store.read('proposals/' + record['id'] + '.json')['scan_id'] + '.json')
    frozen = lab.store.path('days/' + DATE + '.json').read_bytes()
    state['completed'] = []
    freeze_morning(lab, loop, state, deps, MORNING + dt.timedelta(hours=5))
    assert lab.store.path('days/' + DATE + '.json').read_bytes() == frozen


@pytest.mark.parametrize('changed', ['dependencies', 'review_incomplete', 'outside_window'])
def test_morning_without_current_complete_review_has_no_eligible_cards(lab, changed):
    loop, pool, state, deps = loop_pool(lab)
    if changed == 'dependencies':
        deps = dict(deps, local_config_fingerprint=contract.digest({'new': True}))
    elif changed == 'review_incomplete':
        pool['review_complete'] = False
        lab.store.write('scans/' + pool['scan_id'] + '.json', pool)
    else:
        state['completed'][0]['at'] = (MORNING - dt.timedelta(days=2)).isoformat()
    freeze_morning(lab, loop, state, deps)
    payload = imp.report(DATE, selected=lab.selected)
    assert payload['status'] in ('partial', 'failed')
    assert payload['proposals'] == [] and payload['counts']['eligible'] == 0


def test_preexisting_daily_is_never_overwritten_or_resent_by_loop(lab):
    original = scan(lab)
    day_bytes = lab.store.path('days/' + DATE + '.json').read_bytes()
    web_bytes = lab.store.path('web/' + DATE + '.json').read_bytes()
    loop, pool, state, deps = loop_pool(lab)
    journal = freeze_morning(lab, loop, state, deps)
    assert journal['status'] == 'legacy_preserved'
    assert loop.publish(now=MORNING, selected=lab.selected, publisher=forbidden)['status'] == 'legacy_preserved'
    assert imp.daily(True, runner=forbidden, now=MORNING, selected=lab.selected,
                     transport=forbidden)['delivery']['status'] == 'loop_managed'
    assert lab.store.path('days/' + DATE + '.json').read_bytes() == day_bytes
    assert lab.store.path('web/' + DATE + '.json').read_bytes() == web_bytes
    assert imp.status(DATE, selected=lab.selected)['scan_id'] == original['scan_id']


def test_legacy_manual_scan_cannot_replace_frozen_morning_day(lab):
    loop, pool, state, deps = loop_pool(lab)
    freeze_morning(lab, loop, state, deps)
    before = {name: lab.store.path(name).read_bytes() for name in
              ('days/' + DATE + '.json', 'web/' + DATE + '.json', 'latest.json')}
    manual = imp.discover(runner=ModelRunner(lab), keys={}, now=MORNING + dt.timedelta(hours=1),
                          selected=lab.selected)
    assert manual['status'] == 'scanned'
    assert lab.store.exists('scans/' + manual['scan_id'] + '.json')
    for name, body in before.items():
        assert lab.store.path(name).read_bytes() == body


def test_active_loop_blocks_legacy_daily_model_admission(lab):
    from harness import improvement_loop as loop
    with lab.store.lock():
        lab.store.write(loop.STATE_FILE, loop._new_state())
    with pytest.raises(imp.ImprovementError, match='use tick'):
        imp.daily(True, runner=forbidden, now=MORNING, selected=lab.selected, transport=forbidden)
    assert not lab.store.exists('days/' + DATE + '.json')


def test_actual_sites_publisher_is_outside_locks_and_sends_frozen_digest_once(lab):
    loop, pool, state, deps = loop_pool(lab)
    freeze_morning(lab, loop, state, deps)
    transport, config = InboxTransport(lab), inbox(lab)
    def publisher(date, *, selected):
        # Both flock handles must have been released before this callback.
        with lab.store.lock(), lab.store.lock(project=True):
            assert lab.store.read(loop._publication_name(date))['status'] == 'sending'
        return imp.deliver_report(date, selected=selected, inbox_config=config, transport=transport)
    first = loop.publish(now=MORNING, selected=lab.selected, publisher=publisher)
    assert first['status'] == 'delivered'
    for hour in (1, 3, 6):
        assert loop.publish(now=MORNING + dt.timedelta(hours=hour), selected=lab.selected,
                            publisher=forbidden)['digest'] == first['digest']
    # Even a direct duplicate transport call is suppressed for loop reports.
    assert imp.deliver_report(DATE, selected=lab.selected, transport=forbidden)['status'] == 'delivered'
    assert [item[0] for item in transport.calls] == ['POST', 'GET']


def test_second_sender_cannot_reconcile_during_actual_http_delivery(lab):
    loop, pool, state, deps = loop_pool(lab)
    freeze_morning(lab, loop, state, deps)
    class ConcurrentTransport(InboxTransport):
        def __call__(self, method, *args):
            if method == 'POST':
                with pytest.raises(loop.LoopError, match='publication_busy'):
                    loop.publish(now=MORNING, selected=lab.selected, publisher=forbidden, reconcile=True)
                with pytest.raises(imp.ImprovementError, match='already running'):
                    imp.deliver_report(DATE, selected=lab.selected, transport=forbidden)
            return super().__call__(method, *args)
    transport, path = ConcurrentTransport(lab), inbox(lab)
    def publisher(date, *, selected):
        return imp.deliver_report(date, selected=selected, inbox_config=path, transport=transport)
    assert loop.publish(now=MORNING, selected=lab.selected, publisher=publisher)['status'] == 'delivered'
    assert [c[0] for c in transport.calls] == ['POST', 'GET']


def test_failed_sites_delivery_stops_automatic_retry_without_exposing_remote_body(lab):
    loop, pool, state, deps = loop_pool(lab)
    freeze_morning(lab, loop, state, deps)
    path, transport = inbox(lab), InboxTransport(lab, 'exception')
    def publisher(date, *, selected):
        return imp.deliver_report(date, selected=selected, inbox_config=path, transport=transport)
    first = loop.publish(now=MORNING, selected=lab.selected, publisher=publisher)
    assert first['status'] == 'publication_unknown'
    assert lab.store.read('delivery/' + DATE + '.json')['status'] == 'delivery_failed'
    assert len(transport.calls) == 1
    later = loop.publish(now=MORNING + dt.timedelta(hours=1), selected=lab.selected, publisher=forbidden)
    assert later['status'] == 'publication_unknown' and later['digest'] == first['digest']
    assert 'fixture-service-token' not in json.dumps(lab.store.read('delivery/' + DATE + '.json'))


@pytest.mark.parametrize('after_http', [False, True])
def test_unknown_send_needs_explicit_same_digest_reconciliation(lab, after_http):
    loop, pool, state, deps = loop_pool(lab)
    freeze_morning(lab, loop, state, deps)
    path, seen = inbox(lab), []
    class LostProcess(BaseException):
        pass
    class AmbiguousTransport(InboxTransport):
        def __call__(self, method, *args):
            if (method == 'GET') == after_http:
                raise LostProcess()
            return super().__call__(method, *args)
    failing = AmbiguousTransport(lab)
    def sender(date, *, selected):
        return imp.deliver_report(date, selected=selected, inbox_config=path, transport=failing)
    with pytest.raises(LostProcess):
        loop.publish(now=MORNING, selected=lab.selected, publisher=sender)
    delivery = lab.store.read('delivery/' + DATE + '.json')
    assert delivery['status'] == 'sending'
    # The same sending attempt cannot be replayed even via the legacy API.
    assert imp.deliver_report(DATE, selected=lab.selected, transport=forbidden)['status'] == 'delivery_unknown'
    unknown = loop.publish(now=MORNING, selected=lab.selected, publisher=forbidden)
    assert unknown['status'] == 'publication_unknown'
    transport = InboxTransport(lab)
    def reconcile(date, *, selected):
        seen.append(date)
        return imp.deliver_report(date, selected=selected, inbox_config=path, transport=transport)
    done = loop.publish(now=MORNING, selected=lab.selected, publisher=reconcile, reconcile=True)
    assert done['status'] == 'delivered' and done['digest'] == unknown['digest']
    assert seen == [DATE] and [c[0] for c in transport.calls] == ['POST', 'GET']
    assert lab.store.read('delivery/' + DATE + '.json')['publication_attempt_id'] != delivery['publication_attempt_id']


def test_prepared_journal_recovers_after_day_write_without_new_analysis(lab, monkeypatch):
    loop, pool, state, deps = loop_pool(lab)
    original_write = imp.Store.write
    class LostProcess(BaseException):
        pass
    def interrupted(store, name, value):
        original_write(store, name, value)
        if name == 'days/' + DATE + '.json':
            raise LostProcess()
    monkeypatch.setattr(imp.Store, 'write', interrupted)
    with pytest.raises(LostProcess):
        freeze_morning(lab, loop, state, deps)
    journal = lab.store.read(loop._publication_name(DATE))
    assert journal['status'] == 'prepared'
    monkeypatch.setattr(imp.Store, 'write', original_write)
    path, transport = inbox(lab), InboxTransport(lab)
    def publisher(date, *, selected):
        return imp.deliver_report(date, selected=selected, inbox_config=path, transport=transport)
    result = loop.publish(now=MORNING + dt.timedelta(hours=2), selected=lab.selected, publisher=publisher)
    assert result['status'] == 'delivered' and result['digest'] == journal['digest']
    assert lab.store.read('days/' + DATE + '.json')['generated_at'] == MORNING.isoformat()


def test_signed_loop_approval_cannot_rebind_same_proposal_after_control_change(lab, monkeypatch):
    loop, pool, state, deps = loop_pool(lab)
    checked = []
    def freshness(report, *, selected):
        assert selected is lab.selected
        checked.append(report['scan_id'])
    monkeypatch.setattr(loop, 'validate_scan_freshness', freshness)
    pid = pool['proposals'][0]['id']
    instruction = private_json(lab.root.parent / 'instruction.txt', {'unused': 'fixture'})
    instruction.write_text('제안 ' + pid + ' 승인', encoding='utf-8')
    imp.approve(pid, instruction, now=MORNING, selected=lab.selected)
    name = 'approvals/' + pid + '.json'
    approval_bytes = lab.store.path(name).read_bytes()
    approval = lab.store.verify(lab.store.read(name))
    assert approval['discovery_fingerprint'] == loop.authorization_context(pool)
    assert checked == [pool['scan_id']]
    # Identical candidate and independent verdict rediscovered with changed
    # control settings: source ID and review digest stay equal, authority does not.
    fresh = copy.deepcopy(pool)
    fresh['scan_id'] = '523456789-abcdef'
    fresh['loop_dependencies']['loop_config_fingerprint'] = contract.digest({'budget': .9})
    coverage.attach(fresh, fresh['source_review'])
    lab.store.write('scans/' + fresh['scan_id'] + '.json', fresh)
    loop._save_proposals(lab.store, fresh)
    with pytest.raises(imp.ImprovementError, match='discovery controls changed'):
        imp.execute(pid, now=MORNING, selected=lab.selected, executor=forbidden)
    assert lab.store.path(name).read_bytes() == approval_bytes
    assert not lab.store.exists('claims/' + pid + '.json')


def test_loop_freshness_failure_prevents_human_approval_without_quota_checks(lab, monkeypatch):
    loop, pool, state, deps = loop_pool(lab)
    def changed(*args, **kwargs):
        raise loop.LoopError('loop_dependencies_changed')
    monkeypatch.setattr(loop, 'validate_scan_freshness', changed)
    monkeypatch.setattr(loop, 'fetch_glm_quota', forbidden)
    pid = pool['proposals'][0]['id']
    with pytest.raises(imp.ImprovementError, match='loop_dependencies_changed'):
        imp.approve(pid, lab.root / 'never-read.txt', now=MORNING, selected=lab.selected)
    assert not lab.store.exists('approvals/' + pid + '.json')


def test_new_nonloop_approval_binds_source_review_and_legacy_signatures_fail_closed(lab):
    pid, record, instruction = authorize(lab)
    assert 'discovery_fingerprint' in lab.store.verify(lab.store.read('approvals/' + pid + '.json'))
    checked, approval = imp._authorization(lab.store, pid, NOW)
    assert checked == record
    old = dict(approval)
    old.pop('discovery_fingerprint')
    lab.store.write('approvals/' + pid + '.json', lab.store.sign(old))
    with pytest.raises(imp.ImprovementError):
        imp._authorization(lab.store, pid, NOW)


def test_improvements_tick_cli_explicitly_connects_sites_publisher(monkeypatch, capsys):
    from harness import improvement_loop as loop
    # This models the trusted parent CLI, even inside a leaf validation process.
    for key in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                'TAVERN_IMPROVEMENT_UNATTENDED'):
        monkeypatch.delenv(key, raising=False)
    calls = []
    def fake_tick(**options):
        assert options['deliver'] is True and options['publisher'] is imp.deliver_report
        calls.append(options)
        return {'date': DATE, 'status': 'scanned', 'publication': {'status': 'delivered'}}
    monkeypatch.setattr(loop, 'tick', fake_tick)
    assert imp.main(['tick']) == 0
    assert len(calls) == 1 and json.loads(capsys.readouterr().out)['publication']['status'] == 'delivered'


@pytest.mark.parametrize('damage', ['before_nine', 'wrong_window', 'old_success', 'missing_time',
                                   'local_agent', 'legacy_local_agent'])
def test_morning_projection_rejects_invalid_window_or_fabricated_participation(damage):
    private = private_report(records_for())
    private.update(generated_at=MORNING.isoformat(), report_window={
        'start': (MORNING - dt.timedelta(days=1)).isoformat(), 'end': MORNING.isoformat()})
    for agent in private['agents']:
        agent['finished_at'] = NOW.isoformat()
    if damage == 'before_nine':
        private['generated_at'] = (MORNING - dt.timedelta(seconds=1)).isoformat()
    elif damage == 'wrong_window':
        private['report_window']['start'] = (MORNING - dt.timedelta(hours=1)).isoformat()
    elif damage == 'old_success':
        private['agents'][0]['finished_at'] = (MORNING - dt.timedelta(days=2)).isoformat()
    elif damage == 'missing_time':
        private['agents'][0].pop('finished_at')
    else:
        private['agents'][0]['provider'] = 'mlx-lm' if damage == 'legacy_local_agent' else 'mlx-vlm'
    with pytest.raises(contract.ValidationError):
        contract.build_web_report(private)


def test_explicitly_incomplete_review_cannot_project_as_healthy_empty_scan():
    private = private_report()
    private['review_complete'] = False
    assert contract.build_web_report(private)['status'] == 'partial'


def test_execute_has_no_task_files_or_publication_override(lab):
    pid, _, _ = authorize(lab)
    for kwargs in ({'task': 'arbitrary'}, {'files': ['downloader/example.py']}, {'no_git': True}):
        with pytest.raises(TypeError):
            imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden, **kwargs)
    assert not lab.store.exists('claims/' + pid + '.json')


def test_concurrent_claims_allow_only_one_workflow_handoff(lab):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    pid, _, _ = authorize(lab)
    entered, finish = Event(), Event()
    calls = []
    def executor(task, files, **options):
        calls.append(files)
        options['_improvement_guard'](RUN_ID)
        entered.set()
        assert finish.wait(5), 'test must release the fixture executor'
        return {'status': 'awaiting_github', 'run_id': RUN_ID}
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(imp.execute, pid, now=NOW, selected=lab.selected, executor=executor)
        try:
            assert entered.wait(5), 'first execution must reach its guarded handoff'
            with pytest.raises(ValueError, match=r'^Authorization has already been claimed; automatic replay is forbidden\.$'):
                imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden)
        finally:
            finish.set()
        assert first.result(timeout=5)['status'] == 'awaiting_github'
    assert calls == [['harness/example.py']]
    with pytest.raises(ValueError, match=r'^Authorization has already been claimed; automatic replay is forbidden\.$'):
        imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden)


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contract.canonical_json(value))
    path.chmod(0o600)
    return path


def inbox(lab, **changes):
    return private_json(lab.root / 'logs/harness/improvement-inbox.json',
                        dict({'origin': 'https://fixture.invalid', 'token': 'fixture-service-token'}, **changes))


def test_private_configuration_and_instructions_never_enter_prompts_or_web(lab):
    path = inbox(lab)
    runner = ModelRunner(lab)
    result = scan(lab, runner)
    pid = result['proposals'][0]['id']
    instruction = lab.root.parent / 'private-user.txt'
    instruction.write_text('승인: private-owner-instruction-marker', encoding='utf-8')
    instruction.chmod(0o600)
    imp.approve(pid, instruction, now=NOW, selected=lab.selected)
    for call in runner.calls:
        assert 'fixture-service-token' not in call['prompt']
        assert str(path) not in call['prompt']
        assert 'logs/harness/improvement-inbox.json' not in call['paths']
    public = imp.report(DATE, selected=lab.selected)
    serialized = contract.canonical_json(public).decode('utf-8')
    for secret in ('fixture-service-token', 'private-owner-instruction-marker', str(lab.root),
                   'response', 'scope_input', 'source_fingerprints', 'signature'):
        assert secret not in serialized
    for agent in public['agents']:
        assert set(agent) == {'role', 'provider', 'model', 'status'}
    # An explicit scope override cannot authorize private control inputs.
    lab.scope.write_text('logs/harness/improvement-inbox.json\n')
    assert scan(lab, forbidden)['status'] == 'failed'


@pytest.mark.parametrize('scope', ['../outside.py', '/absolute/file.py', 'harness/*.py',
                                   '.agent-keys.json', 'harness/example.py\nharness/example.py'])
def test_scope_file_rejects_traversal_globs_secrets_and_duplicates(lab, scope):
    lab.scope.write_text(scope + '\n')
    report = scan(lab, forbidden)
    assert report['status'] == 'failed' and not report['review_complete']
    assert all(a['status'] == 'not_called' for a in report['agents'])


def test_explicit_scope_override_is_recorded_without_scope_expansion(lab):
    override = lab.root.parent / 'approved-scope.txt'
    override.write_text('\n'.join(FILES) + '\n')
    override.chmod(0o600)
    result = scan(lab, scope_file=override)
    assert result['scope_override'] is True and result['approved_files'] == list(FILES)
    assert result['scope_fingerprint'] == {'sha256': hashlib.sha256(override.read_bytes()).hexdigest(),
                                           'mode': 0o600, 'paths': list(FILES)}
    assert str(override) not in contract.canonical_json(imp.report(DATE, selected=lab.selected)).decode('utf-8')


def private_report(records=(), status='scanned'):
    return {'date': DATE, 'generated_at': NOW.isoformat(), 'status': status,
            'proposals': list(records), 'agents': [
                {'role': role, 'provider': 'fixture', 'model': 'fixture-model', 'status': 'succeeded'}
                for role in contract.ROLES], 'documentation': copy.deepcopy(DOC),
            'approved_files': list(FILES)}


def records_for(count=1, unsafe=False):
    snapshots = {path: {'exists': True, 'mode': 0o644,
                        'content': b'first_value = 1\nsecond_value = 2\n'} for path in FILES}
    fingerprints = contract.fingerprint_sources(snapshots)
    records = []
    for index in range(count):
        c = candidate(title='점검 제안 ' + str(index))
        if unsafe:
            c['title'] = '<img onerror="alert(1)">점검 ' + str(index)
            c['issue'] = '검토 <script>alert(1)</script> Bearer fixture-secret /home/private/file'
            c['risk'] = 'token=private-token [위험](javascript:alert) <b>확인</b>'
        record = contract.proposal_record(c, fingerprints)
        record['review'] = {'verdict': 'eligible', 'reason': '가상 소스의 근거 줄과 변경 범위를 독립적으로 검토했습니다.',
                            'documentation': copy.deepcopy(DOC)}
        records.append(record)
    return records


def test_safe_bounded_one_page_projection_and_canonical_digest():
    private = private_report(records_for(8, unsafe=True))
    private.update(instruction='never-publish-instruction', raw_response='never-publish-response',
                   prompts='never-publish-prompt', logs='never-publish-log')
    private['agents'][0].update(result={'response': 'never-publish-result'}, cost=99)
    payload = contract.build_web_report(private)
    assert set(payload) == {'version', 'date', 'generated_at', 'status', 'headline', 'summary',
                            'analogy', 'proposals', 'agents', 'counts', 'documentation', 'digest'}
    assert payload['version'] == 'improvement-web-v1'
    assert payload['counts'] == {'candidates': 8, 'reported': 3, 'additional_candidates': 5, 'eligible': 8}
    assert len(payload['proposals']) == 3
    canonical = json.dumps({k: v for k, v in payload.items() if k != 'digest'}, ensure_ascii=False,
                           sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    assert payload['digest'] == hashlib.sha256(canonical).hexdigest()
    assert contract.verify_web_digest(payload, DATE)
    assert not contract.verify_web_digest(payload, '2026-10-16')
    assert contract.validate_web_report(payload) == payload
    assert len(contract.canonical_json(payload)) <= contract.MAX_WEB_BYTES
    serialized = json.dumps(payload, ensure_ascii=False)
    for secret in ('fixture-secret', 'private-token', '/home/private/file', 'never-publish-'):
        assert secret not in serialized
    html, markdown = contract.render_html(payload), contract.render_markdown(payload)
    for rendered in (html, markdown):
        assert '<script>' not in rendered and '<img onerror=' not in rendered
        assert '&lt;img' in rendered and '승인 전 변경 없음' in rendered
        assert '추가 후보 5개' in rendered and '미측정' in rendered
    assert html.count('<article') == 3
    assert '@page' in html and 'A4' in html
    assert len(html) < 40000 and len(markdown) < 20000
    assert all(p['approval_wording'] == '제안 ' + p['id'] + ' 승인' for p in payload['proposals'])
    lowered = contract.build_web_report(private, max_proposals=1)
    assert len(lowered['proposals']) == 1 and lowered['counts']['additional_candidates'] == 7
    assert private['instruction'] == 'never-publish-instruction'


@pytest.mark.parametrize('fenced', [False, True])
def test_long_private_candidates_survive_review_persistence_and_authorized_handoff(lab, fenced):
    first = candidate('downloader/example.py')
    first['issue'] = '가' * 400 + '나' * 19  # Synthetic 419-character reproducer.
    second = candidate('downloader/example.py', title='두 번째 합성 제안')
    second['issue'] = '다' * 279

    def transform(role, result, response, options):
        if fenced:
            result['response'] = '```json\n' + result['response'] + '\n```'
        return result

    runner = ModelRunner(lab, {'downloader': [first, second]}, transform=transform)
    report = scan(lab, runner)
    assert report['status'] == 'scanned' and report['review_complete']
    assert len(report['proposals']) == 2 and len(runner.calls) == 5
    assert [p['candidate'] for p in runner.calls[-1]['prior']] == [first, second]
    for record, original in zip(report['proposals'], (first, second)):
        assert record['candidate'] == original
        saved = lab.store.read('proposals/' + record['id'] + '.json')['proposal']
        assert saved == record == imp._eligible(lab.store, record['id'])
        for directory in ('approvals', 'decisions', 'claims', 'executions'):
            assert not lab.store.exists(directory + '/' + record['id'] + '.json')
    assert not lab.store.exists('authority.key')
    assert imp.daily(runner=forbidden, keys={}, now=NOW,
                     selected=lab.selected)['scan_id'] == report['scan_id']
    public = imp.report(DATE, selected=lab.selected)
    card = next(p for p in public['proposals'] if p['id'] == report['proposals'][0]['id'])
    assert card['issue'] == '가' * 399 + '…' and len(card['issue']) == 400
    assert report['proposals'][0]['candidate']['issue'] == first['issue']
    assert (lab.root / 'downloader/example.py').read_text() == 'first_value = 1\nsecond_value = 2\n'
    # Only an explicit synthetic human instruction permits the later handoff.
    pid = report['proposals'][0]['id']
    instruction = lab.root.parent / 'synthetic-long-proposal-approval.txt'
    instruction.write_text('제안 ' + pid + ' 승인. 지정된 파일만 수정하세요.', encoding='utf-8')
    instruction.chmod(0o600)
    imp.approve(pid, instruction, now=NOW, selected=lab.selected)
    calls = []
    imp.execute(pid, now=NOW, selected=lab.selected, executor=executor_for(calls))
    assert len(calls) == 1
    assert contract.canonical_json(first).decode('utf-8') in calls[0][0]


NARRATIVE_CASES = [
    (('title',), 80), (('analogy',), 200), (('issue',), 400),
    (('evidence', 0, 'summary'), 240), (('benefit', 'text'), 240),
    (('benefit', 'evidence', 0, 'summary'), 240), (('risk',), 240),
    (('validation_plan', 0), 200), (('documentation_impact',), 360),
]


def narrative_slot(value, path):
    for key in path[:-1]:
        value = value[key]
    return value, path[-1]


REVIEW_REASON_PATHS = [
    ('proposals', 0, 'review', 'reason'),
    ('proposals', 0, 'review', 'documentation', 'reason'),
    ('documentation', 'reason'),
]


def review_response(report):
    return {'reviews': [dict(r['review'], candidate_id=r['id']) for r in report['proposals']],
            'documentation': report['documentation']}


@pytest.mark.parametrize('fenced', [False, True])
def test_416_character_review_survives_scan_without_discovery_authority(lab, fenced):
    # Synthetic prose only: reproduce the observed length, never a private response.
    reason = '가' * 360 + '나' * 56
    doc_reason = '다' * 360 + '라' * 56
    top_reason = '마' * 360 + '바' * 56
    before = {p: ((lab.root / p).read_bytes(), (lab.root / p).stat().st_mode) for p in FILES}

    def transform(role, result, response, options):
        if role == 'reviewer':
            response['reviews'][0]['reason'] = reason
            response['reviews'][0]['documentation']['reason'] = doc_reason
            response['documentation']['reason'] = top_reason
        result['response'] = json.dumps(response, ensure_ascii=False)
        if fenced:
            result['response'] = '```json\n' + result['response'] + '\n```'
        return result

    runner = ModelRunner(lab, transform=transform)
    report = scan(lab, runner)
    assert report['status'] == 'scanned' and report['review_complete']
    assert [call['role'] for call in runner.calls] == list(contract.ROLES)
    assert all(a['status'] == 'succeeded' and a['result']['status'] == 'passed'
               for a in report['agents'])
    record = report['proposals'][0]
    assert record['review']['reason'] == reason
    assert record['review']['documentation']['reason'] == doc_reason
    assert report['documentation']['reason'] == top_reason
    assert lab.store.read('scans/' + report['scan_id'] + '.json') == report
    assert lab.store.read('proposals/' + record['id'] + '.json')['proposal'] == record
    assert imp._eligible(lab.store, record['id']) == record
    public = imp.report(DATE, selected=lab.selected)
    assert public['status'] == 'scanned' and public['counts']['eligible'] == 1
    for path, original in zip(REVIEW_REASON_PATHS, (reason, doc_reason, top_reason)):
        owner, key = narrative_slot(public, path)
        assert owner[key] == original[:359] + '…'
    assert before == {p: ((lab.root / p).read_bytes(), (lab.root / p).stat().st_mode) for p in FILES}
    for directory in ('approvals', 'decisions', 'claims', 'executions'):
        assert not lab.store.exists(directory + '/' + record['id'] + '.json')
    assert not lab.store.exists('authority.key')


@pytest.mark.parametrize('path', REVIEW_REASON_PATHS)
def test_review_private_exact_ceiling_and_projection_revalidation(path):
    report = private_report(records_for())
    owner, key = narrative_slot(report, path)
    owner[key] = '가' * 1440
    response = review_response(report)
    assert contract.validate_review(response, report['proposals'], FILES, private=True) == response
    public = contract.build_web_report(report)
    display_owner, display_key = narrative_slot(public, path)
    assert display_owner[display_key] == '가' * 359 + '…'
    assert public['status'] == 'scanned' and public['counts']['eligible'] == 1
    assert owner[key] == '가' * 1440
    owner[key] += '나'
    with pytest.raises(contract.ValidationError):
        contract.validate_review(review_response(report), report['proposals'], FILES, private=True)
    if path[0] == 'documentation':
        with pytest.raises(contract.ValidationError):
            contract.build_web_report(report)
    else:
        # Preserve existing incomplete-review fallback, never invent eligibility.
        public = contract.build_web_report(report)
        assert public['status'] == 'partial' and public['counts']['eligible'] == 0
        assert public['proposals'][0]['review']['verdict'] == 'needs_evidence'
    assert len(owner[key]) == 1441  # Projection must not mutate private input.


@pytest.mark.parametrize('path', REVIEW_REASON_PATHS)
def test_review_ceiling_in_persisted_eligibility_and_authorization(lab, path):
    def transform(role, result, response, options):
        if role == 'reviewer':
            response_path = (('reviews', 0) + path[3:] if path[0] == 'proposals' else path)
            owner, key = narrative_slot(response, response_path)
            owner[key] = '가' * 1440
            result['response'] = json.dumps(response, ensure_ascii=False)
        return result

    report = scan(lab, ModelRunner(lab, transform=transform))
    assert report['status'] == 'scanned' and report['review_complete']
    pid = report['proposals'][0]['id']
    assert imp._eligible(lab.store, pid) == report['proposals'][0]
    instruction = lab.root.parent / 'synthetic-ceiling-approval.txt'
    instruction.write_text('제안 ' + pid + ' 승인. 지정된 파일만 수정하세요.', encoding='utf-8')
    instruction.chmod(0o600)
    imp.approve(pid, instruction, now=NOW, selected=lab.selected)
    record, approval = imp._authorization(lab.store, pid, NOW)
    assert record == report['proposals'][0]
    if path[0] == 'proposals':
        assert '가' * 1440 in imp._task(record, approval)
    owner, key = narrative_slot(report, path)
    owner[key] += '나'
    lab.store.write('scans/' + report['scan_id'] + '.json', report)
    saved = lab.store.read('proposals/' + pid + '.json')
    saved['proposal'] = report['proposals'][0]
    lab.store.write('proposals/' + pid + '.json', saved)
    with pytest.raises(contract.ValidationError):
        imp._eligible(lab.store, pid)
    with pytest.raises(contract.ValidationError):
        imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden)
    assert not lab.store.exists('claims/' + pid + '.json')


@pytest.mark.parametrize('path', REVIEW_REASON_PATHS)
def test_public_review_360_361_bounds_with_recomputed_digest(path):
    payload = contract.build_web_report(private_report(records_for()))
    owner, key = narrative_slot(payload, path)
    owner[key] = '가' * 360
    payload['digest'] = contract.digest({k: v for k, v in payload.items() if k != 'digest'})
    for consume in (contract.validate_web_report, contract.render_html, contract.render_markdown):
        consume(payload)
    owner[key] += '나'
    payload['digest'] = contract.digest({k: v for k, v in payload.items() if k != 'digest'})
    assert contract.verify_web_digest(payload)
    for consume in (contract.validate_web_report, contract.render_html, contract.render_markdown):
        with pytest.raises(contract.ValidationError):
            consume(payload)
    # Explicit public mode also remains strict before any projection.
    report = private_report(records_for())
    private_owner, private_key = narrative_slot(report, path)
    private_owner[private_key] = owner[key]
    with pytest.raises(contract.ValidationError):
        contract.validate_review(review_response(report), report['proposals'], FILES, private=False)


@pytest.mark.parametrize('field', ['reason', 'documentation'])
@pytest.mark.parametrize('change_suffix', [False, True])
def test_full_review_digest_and_explicit_mocked_handoff(lab, field, change_suffix):
    original = '가' * 360 + '나' * 56

    def transform(role, result, response, options):
        if role == 'reviewer':
            review = response['reviews'][0]
            owner = review if field == 'reason' else review['documentation']
            owner['reason'] = original
            result['response'] = json.dumps(response, ensure_ascii=False)
        return result

    report = scan(lab, ModelRunner(lab, transform=transform))
    assert report['status'] == 'scanned' and report['review_complete']
    record = report['proposals'][0]
    pid = record['id']
    public_before = imp.report(DATE, selected=lab.selected)
    instruction = lab.root.parent / 'synthetic-review-approval.txt'
    instruction.write_text('제안 ' + pid + ' 승인. 지정된 파일만 수정하세요.', encoding='utf-8')
    instruction.chmod(0o600)
    imp.approve(pid, instruction, now=NOW, selected=lab.selected)
    approval = lab.store.verify(lab.store.read('approvals/' + pid + '.json'))
    canonical = json.dumps(record['review'], ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode('utf-8')
    assert approval['review_digest'] == hashlib.sha256(canonical).hexdigest()
    calls = []
    if change_suffix:
        owner = record['review'] if field == 'reason' else record['review']['documentation']
        owner['reason'] = original[:-1] + '다'
        lab.store.write('scans/' + report['scan_id'] + '.json', report)
        saved = lab.store.read('proposals/' + pid + '.json')
        saved['proposal'] = record
        lab.store.write('proposals/' + pid + '.json', saved)
        # Editing persisted verdict text cannot reuse the original transport/
        # review binding, even when the visible 360-character card is identical.
        with pytest.raises(imp.ImprovementError, match='source Read evidence'):
            imp._eligible(lab.store, pid)
        assert contract.build_web_report(report) == public_before
        assert approval['review_digest'] != contract.digest(record['review'])
        with pytest.raises(ValueError, match='source Read evidence'):
            imp.execute(pid, now=NOW, selected=lab.selected, executor=executor_for(calls))
        assert not lab.store.exists('claims/' + pid + '.json')
        assert calls == []
    else:
        imp.execute(pid, now=NOW, selected=lab.selected, executor=executor_for(calls))
        assert len(calls) == 1
        assert contract.canonical_json(record['review']).decode('utf-8') in calls[0][0]
        assert original in calls[0][0]


def test_short_review_representation_and_digest_remain_unchanged():
    report = private_report(records_for())
    original = copy.deepcopy(review_response(report))
    assert contract.validate_review(original, report['proposals'], FILES) == original
    assert contract.validate_review(original, report['proposals'], FILES, private=False) == original
    review = report['proposals'][0]['review']
    canonical = json.dumps(review, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode('utf-8')
    assert contract.digest(review) == hashlib.sha256(canonical).hexdigest()
    assert contract.build_web_report(report)['proposals'][0]['review'] == review


@pytest.mark.parametrize('path', REVIEW_REASON_PATHS)
def test_review_redaction_and_whitespace_are_only_display_operations(path):
    report = private_report(records_for())
    reason = '가' * 400 + '\n  합성 검토\tBearer synthetic-review-secret\n끝까지 보존합니다.'
    owner, key = narrative_slot(report, path)
    owner[key] = reason
    before = copy.deepcopy(report)
    assert contract.validate_review(review_response(report), report['proposals'], FILES) == review_response(report)
    public = contract.build_web_report(report)
    assert report == before and owner[key] == reason
    display_owner, display_key = narrative_slot(public, path)
    assert display_owner[display_key] == '가' * 359 + '…'
    assert 'synthetic-review-secret' not in contract.canonical_json(public).decode('utf-8')
    # Exercise visible redaction/whitespace separately from an already-long prefix.
    owner[key] = '합성 검토\n  Bearer synthetic-review-secret\t끝까지 보존합니다.'
    public = contract.build_web_report(report)
    display_owner, display_key = narrative_slot(public, path)
    assert display_owner[display_key] == '합성 검토 [인증 정보는 웹 보고서에서 생략했습니다] 끝까지 보존합니다.'
    assert '\n' in owner[key] and 'synthetic-review-secret' in owner[key]


@pytest.mark.parametrize('location', ['candidate', 'global'])
@pytest.mark.parametrize('bad', ['short_reason', 'unknown_status', 'files_without_required',
                                  'required_without_files', 'non_markdown', 'outside_scope',
                                  'missing_eligible', 'extra_key'])
def test_long_review_keeps_documentation_and_scope_constraints(location, bad):
    report = private_report(records_for())
    response = review_response(report)
    response['reviews'][0]['reason'] = '가' * 416
    doc = (response['documentation'] if location == 'global' else
           response['reviews'][0]['documentation'])
    doc['reason'] = '나' * 1440
    if bad == 'short_reason':
        doc['reason'] = '가' * 11
    elif bad == 'unknown_status':
        doc['status'] = 'updated'  # Implementation-review status is not advisory schema.
    elif bad == 'files_without_required':
        doc['files'] = ['docs/architecture.md']
    elif bad == 'required_without_files':
        doc['status'] = 'required'
    elif bad == 'non_markdown':
        doc.update(status='required', files=['harness/example.py'])
    elif bad == 'outside_scope':
        doc.update(status='required', files=['docs/unapproved.md'])
    elif bad == 'missing_eligible':
        doc.update(status='missing', files=['docs/architecture.md'])
    else:
        doc['approved'] = True
    with pytest.raises(contract.ValidationError):
        contract.validate_review(response, report['proposals'], FILES)


@pytest.mark.parametrize('path,display_limit', NARRATIVE_CASES)
def test_private_prose_exact_ceiling_projection_and_excess(path, display_limit):
    original = candidate()
    original['benefit']['kind'] = 'measured'
    original['benefit']['evidence'] = copy.deepcopy(original['evidence'])
    owner, key = narrative_slot(original, path)
    owner[key] = '가' * (4 * display_limit)
    sources = {'harness/example.py': 'first\nsecond\n'}
    validated = contract.validate_candidate(original, sources)
    assert validated == original
    fingerprints = contract.fingerprint_sources({
        'harness/example.py': {'exists': True, 'mode': 0o644, 'content': b'first\nsecond\n'}})
    review = records_for()[0]['review']
    record = dict(contract.proposal_record(validated, fingerprints), review=review)
    payload = contract.build_web_report(private_report([record]))
    display_owner, display_key = narrative_slot(payload['proposals'][0], path)
    assert display_owner[display_key] == '가' * (display_limit - 1) + '…'
    assert record['candidate'] == original
    assert contract.validate_web_report(payload) == payload
    owner[key] += '나'
    with pytest.raises(contract.ValidationError):
        contract.validate_candidate(original, sources)
    # Revalidation of private display inputs must enforce the same hard ceiling.
    oversized = dict(contract.proposal_record(original, fingerprints), review=review)
    with pytest.raises(contract.ValidationError):
        contract.build_web_report(private_report([oversized]))


@pytest.mark.parametrize('path,display_limit', NARRATIVE_CASES)
def test_oversized_public_prose_rejected_even_with_correct_digest(path, display_limit):
    record = records_for()[0]
    record['candidate']['benefit']['evidence'] = copy.deepcopy(record['candidate']['evidence'])
    record = dict(contract.proposal_record(record['candidate'], record['source_fingerprints']),
                  review=record['review'])
    payload = contract.build_web_report(private_report([record]))
    owner, key = narrative_slot(payload['proposals'][0], path)
    owner[key] = '가' * display_limit
    payload['digest'] = contract.digest({k: v for k, v in payload.items() if k != 'digest'})
    assert contract.validate_web_report(payload) == payload  # Public exact bound.
    owner[key] += '나'
    payload['digest'] = contract.digest({k: v for k, v in payload.items() if k != 'digest'})
    assert contract.verify_web_digest(payload)
    for consume in (contract.validate_web_report, contract.render_html, contract.render_markdown):
        with pytest.raises(contract.ValidationError):
            consume(payload)


def test_private_identity_covers_suffix_hidden_by_public_projection():
    original = records_for()[0]
    short = candidate()
    assert contract.validate_candidate(short, {'harness/example.py': 'first\nsecond\n'}) == short
    expected = {'version': 'improvement-proposal-v1', 'candidate': short,
                'source_fingerprints': original['source_fingerprints']}
    canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode('utf-8')
    short_record = contract.proposal_record(short, original['source_fingerprints'])
    assert short_record['digest'] == hashlib.sha256(canonical).hexdigest()
    assert short_record['id'] == 'IMP-' + short_record['digest'][:16]
    records = []
    for suffix in ('나' * 19, '다' * 19):
        c = candidate()
        c['issue'] = '가' * 400 + suffix
        records.append(dict(contract.proposal_record(c, original['source_fingerprints']),
                            review=original['review']))
    assert records[0]['id'] != records[1]['id']
    assert records[0]['digest'] != records[1]['digest']
    cards = [contract.build_web_report(private_report([r]))['proposals'][0] for r in records]
    assert cards[0]['issue'] == cards[1]['issue'] == '가' * 399 + '…'


def test_independent_review_redaction_never_uses_display_prefix(lab):
    c = candidate()
    # Redaction expands this input; its final safe text and whitespace must survive.
    c['issue'] = '가' * 400 + '\n' + 'Bearer synthetic-token ' * 8 + '\n끝까지 검토합니다.'
    runner = ModelRunner(lab, {'coordinator': [c]})
    report = scan(lab, runner)
    assert report['status'] == 'scanned'
    reviewed = runner.calls[-1]['prior'][0]['candidate']['issue']
    assert 'synthetic-token' not in reviewed
    assert reviewed.count('[인증 정보는 웹 보고서에서 생략했습니다]') == 8
    assert reviewed.endswith('\n끝까지 검토합니다.') and len(reviewed) > 400
    assert report['proposals'][0]['candidate']['issue'] == c['issue']


def test_public_digest_does_not_depend_on_human_state_or_agent_private_logs():
    private = private_report(records_for())
    first = contract.build_web_report(private)
    private['approval'] = {'instruction': 'explicit private approval', 'approved': True}
    private['agents'][0]['result'] = {'raw': 'private logs'}
    assert contract.build_web_report(private) == first
    tampered = copy.deepcopy(first)
    tampered['proposals'][0]['title'] = '변조된 제목'
    assert not contract.verify_web_digest(tampered)
    with pytest.raises(contract.ValidationError):
        contract.render_html(tampered)


@pytest.mark.parametrize('damage', ['reviewer_failed', 'missing_review', 'one_missing_review'])
def test_web_projection_never_invents_consensus_when_review_incomplete(damage):
    private = private_report(records_for(2))
    if damage == 'reviewer_failed':
        private['agents'][-1]['status'] = 'failed'
    elif damage == 'missing_review':
        for record in private['proposals']:
            record.pop('review')
    else:
        private['proposals'][1].pop('review')
    payload = contract.build_web_report(private)
    assert payload['status'] == 'partial' and payload['counts']['eligible'] == 0
    assert all(p['review']['verdict'] == 'needs_evidence' for p in payload['proposals'])


def test_empty_healthy_report_distinguishes_incomplete_scan():
    healthy = contract.build_web_report(private_report())
    broken_private = private_report(status='failed')
    for agent in broken_private['agents']:
        agent['status'] = 'failed'
    broken = contract.build_web_report(broken_private)
    assert healthy['summary'] != broken['summary']
    assert '점검 완료: 보고할 제안이 없습니다.' in contract.render_markdown(healthy)
    assert '개선점이 없음을 의미하지 않습니다.' in contract.render_markdown(broken)


@pytest.mark.parametrize('change', ['content', 'mode', 'existence'])
def test_proposal_identity_covers_all_read_dependencies(change):
    snapshots = {'harness/example.py': {'exists': True, 'mode': 0o644, 'content': b'a\nb\n'},
                 'AGENTS.md': {'exists': True, 'mode': 0o644, 'content': b'instructions\n'}}
    before = contract.proposal_record(candidate(), contract.fingerprint_sources(snapshots))
    other = copy.deepcopy(snapshots)
    if change == 'content':
        other['AGENTS.md']['content'] = b'changed\n'
    elif change == 'mode':
        other['AGENTS.md']['mode'] = 0o600
    else:
        other['AGENTS.md'] = {'exists': False, 'mode': None, 'content': None}
    after = contract.proposal_record(candidate(), contract.fingerprint_sources(other))
    assert before['id'] != after['id'] and before['digest'] != after['digest']
    assert before == contract.proposal_record(candidate(), contract.fingerprint_sources(snapshots))


class InboxTransport:
    def __init__(self, lab, failure=None):
        self.lab, self.failure, self.calls, self.payload = lab, failure, [], None

    def __call__(self, method, origin, path, headers, body, timeout, max_bytes):
        self.calls.append((method, origin, path, dict(headers), body, timeout, max_bytes))
        assert origin == 'https://fixture.invalid'
        assert headers['OAI-Sites-Authorization'] == 'Bearer fixture-service-token'
        assert headers['Content-Type'] == 'application/json'
        assert timeout == self.lab.config['limits']['delivery_timeout_seconds'] <= 20
        assert max_bytes == self.lab.config['limits']['max_delivery_bytes'] <= 262144
        if self.failure == 'exception':
            raise OSError('fixture-service-token must never be printed or retained')
        if self.failure == 'redirect':
            return 302, b'fixture-service-token'
        if self.failure == 'oversize':
            return 200, b'x' * (max_bytes + 1)
        if method == 'POST':
            assert path == '/api/reports'
            self.payload = json.loads(body)
            assert body == contract.canonical_json(self.payload)
            assert contract.validate_web_report(self.payload) == self.payload
            assert self.lab.store.exists('days/' + DATE + '.json')
            return 201, b'{}'
        assert method == 'GET' and path == '/api/reports/' + DATE and body is None
        response = copy.deepcopy(self.payload)
        if self.failure == 'wrong_date':
            response['date'] = '2026-10-16'
        elif self.failure == 'wrong_digest':
            response['summary'] = '변조된 반환 내용'
        elif self.failure == 'different_valid_report':
            response['summary'] = '별도 유효한 보고서지만 전송한 보고서와 다릅니다.'
            response['digest'] = contract.digest({k: v for k, v in response.items() if k != 'digest'})
        elif self.failure == 'bad_json':
            return 200, b'{bad json'
        elif self.failure == 'missing':
            return 404, b'fixture-service-token'
        return 200, contract.canonical_json(response)


def test_delivery_verifies_readback_and_repeated_payload_is_idempotent(lab):
    scan(lab)
    path = inbox(lab)
    transport = InboxTransport(lab)
    first = imp.deliver_report(DATE, inbox_config=path, transport=transport, selected=lab.selected)
    again = imp.deliver_report(DATE, inbox_config=path, transport=transport, selected=lab.selected)
    assert first['status'] == again['status'] == 'delivered'
    assert first['digest'] == again['digest'] == imp.report(DATE, selected=lab.selected)['digest']
    assert [c[0] for c in transport.calls] == ['POST', 'GET', 'POST', 'GET']
    assert transport.calls[0][4] == transport.calls[2][4]
    assert lab.store.read('delivery/' + DATE + '.json')['status'] == 'delivered'


@pytest.mark.parametrize('failure', ['exception', 'redirect', 'oversize', 'wrong_date', 'wrong_digest',
                                    'different_valid_report', 'bad_json', 'missing'])
def test_delivery_failure_keeps_report_and_retry_never_reruns_analysis(lab, failure, capsys):
    runner = ModelRunner(lab)
    first = imp.daily(runner=runner, keys={}, now=NOW, selected=lab.selected)
    inbox(lab)
    before = lab.store.read('web/' + DATE + '.json')
    failing = InboxTransport(lab, failure)
    result = imp.daily(deliver=True, runner=forbidden, keys={}, now=NOW,
                       selected=lab.selected, transport=failing)
    assert result['scan_id'] == first['scan_id']
    assert result['status'] == 'scanned' and result['delivery']['status'] == 'delivery_failed'
    assert lab.store.read('web/' + DATE + '.json') == before
    assert len(runner.calls) == 5
    assert 'fixture-service-token' not in json.dumps(result)
    assert 'fixture-service-token' not in repr(capsys.readouterr())
    successful = InboxTransport(lab)
    retry = imp.daily(deliver=True, runner=forbidden, keys={}, now=NOW,
                      selected=lab.selected, transport=successful)
    assert retry['delivery']['status'] == 'delivered' and retry['scan_id'] == first['scan_id']
    assert lab.store.read('days/' + DATE + '.json')['scan_id'] == first['scan_id']
    assert [c[0] for c in successful.calls] == ['POST', 'GET']


@pytest.mark.parametrize('origin', ['http://fixture.invalid', 'https://user:pass@fixture.invalid',
                                    'https://fixture.invalid/path', 'https://fixture.invalid?token=x',
                                    'https://fixture.invalid/#x', 'https://fixture.invalid:bad',
                                    'https://fixture.invalid\n', '//fixture.invalid'])
def test_delivery_requires_https_origin_without_embedded_credentials(lab, origin):
    scan(lab)
    path = inbox(lab, origin=origin)
    outcome = imp.deliver_report(DATE, inbox_config=path, transport=forbidden, selected=lab.selected)
    assert outcome['status'] == 'delivery_failed'


@pytest.mark.parametrize('damage', ['public_mode', 'symlink', 'hardlink', 'extra_field', 'invalid_token', 'too_large'])
def test_private_inbox_config_is_bounded_nonlinked_and_never_echoed(lab, damage):
    scan(lab)
    path = inbox(lab)
    if damage == 'public_mode':
        path.chmod(0o644)
    elif damage in ('symlink', 'hardlink'):
        target = path.with_name('inbox-copy.json')
        path.rename(target)
        if damage == 'symlink':
            path.symlink_to(target)
        else:
            os.link(target, path)
    elif damage == 'extra_field':
        private_json(path, {'origin': 'https://fixture.invalid', 'token': 'fixture-service-token', 'extra': 'bad'})
    elif damage == 'invalid_token':
        inbox(lab, token='fixture-service-token\r\nInjected: x')
    else:
        path.write_bytes(b'x' * 8193)
    outcome = imp.deliver_report(DATE, inbox_config=path, transport=forbidden, selected=lab.selected)
    assert outcome['status'] == 'delivery_failed'
    assert 'fixture-service-token' not in json.dumps(outcome)
    assert 'fixture-service-token' not in json.dumps(lab.store.read('delivery/' + DATE + '.json'))


def test_delivery_requires_existing_local_report(lab):
    with pytest.raises((ValueError, OSError)):
        imp.deliver_report(DATE, transport=forbidden, selected=lab.selected)


class HTTPResponse:
    def __init__(self, status=200, chunks=(), length=None):
        self.status, self.chunks, self.length, self.read_sizes = status, list(chunks), length, []

    def getheader(self, name):
        assert name == 'Content-Length'
        return self.length

    def read1(self, maximum):
        self.read_sizes.append(maximum)
        return self.chunks.pop(0) if self.chunks else b''


class HTTPSConnection:
    def __init__(self, response):
        self.response, self.closed, self.requests, self.timeouts = response, False, [], []
        self.sock = self

    def request(self, method, path, body, headers):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return self.response

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def close(self):
        self.closed = True


def test_http_transport_enforces_https_without_opening_connection(lab):
    with pytest.raises(ValueError, match='HTTPS'):
        imp.http_transport('GET', 'http://fixture.invalid', '/', {}, None, 2, 16)


@pytest.mark.parametrize('failure', ['redirect', 'declared_length', 'malformed_length', 'stream_length', 'deadline'])
def test_real_http_transport_refuses_redirects_and_bounds_stream_without_network(lab, monkeypatch, failure):
    response = HTTPResponse(status=302 if failure == 'redirect' else 200,
                            chunks=[b'x' * 17] if failure == 'stream_length' else [b'ok'],
                            length='17' if failure == 'declared_length' else
                                   'bogus' if failure == 'malformed_length' else None)
    connection = HTTPSConnection(response)
    constructions = []
    def connect(host, port, timeout):
        constructions.append((host, port, timeout))
        return connection
    monkeypatch.setattr(imp.http.client, 'HTTPSConnection', connect)
    if failure == 'deadline':
        ticks = iter((100.0, 103.0))
        monkeypatch.setattr(imp.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(ValueError):
        imp.http_transport('GET', 'https://fixture.invalid', '/api/reports/' + DATE, {}, None, 2, 16)
    assert constructions == [('fixture.invalid', None, 2)]
    assert len(connection.requests) == 1 and connection.closed
    assert all(1 <= size <= 17 for size in response.read_sizes)


def test_http_transport_returns_bounded_bytes_and_closes_connection(lab, monkeypatch):
    response = HTTPResponse(chunks=[b'{', b'}'], length='2')
    connection = HTTPSConnection(response)
    monkeypatch.setattr(imp.http.client, 'HTTPSConnection', lambda *a, **kw: connection)
    code, content = imp.http_transport('POST', 'https://fixture.invalid', '/api/reports', {}, b'{}', 2, 16)
    assert (code, content) == (200, b'{}') and connection.closed
    assert connection.timeouts and all(0 < value <= 2 for value in connection.timeouts)


def test_eight_candidates_still_use_five_calls_and_only_three_web_cards(lab):
    paths = {'coordinator': 'harness/example.py', 'downloader': 'downloader/example.py',
             'parser': 'parser_tidy/example.py', 'django': 'TavernofSoul/example.py'}
    candidates = {role: [candidate(path, title='점검 ' + role + str(i)) for i in range(2)]
                  for role, path in paths.items()}
    runner = ModelRunner(lab, candidates)
    report = scan(lab, runner)
    assert report['status'] == 'scanned' and len(runner.calls) == 5
    assert len(report['proposals']) == len(runner.calls[-1]['prior']) == 8
    public = imp.report(DATE, selected=lab.selected)
    assert public['counts'] == {'candidates': 8, 'reported': 3, 'additional_candidates': 5, 'eligible': 8}
    assert len(public['proposals']) == 3


@pytest.mark.parametrize('bound', ['file', 'total'])
def test_source_byte_limits_fail_before_any_model_call(lab, bound):
    if bound == 'file':
        (lab.root / 'harness/example.py').write_bytes(b'x' * (lab.config['limits']['max_file_bytes'] + 1))
    else:
        config = copy.deepcopy(lab.config)
        config['limits'].update(max_file_bytes=128, max_source_bytes=128)
        lab.config_path.write_text(json.dumps(config))
    report = scan(lab, forbidden)
    assert report['status'] == 'failed'
    assert all(a['status'] == 'not_called' for a in report['agents'])


def test_oversized_model_response_is_failed_with_bounded_retained_metadata(lab):
    def transform(role, result, response, options):
        if role == 'coordinator':
            result['response'] = 'x' * (lab.config['limits']['max_response_bytes'] + 16384)
        return result
    report = scan(lab, ModelRunner(lab, transform=transform))
    failed = report['agents'][0]
    assert failed['status'] == 'failed' and failed['result_truncated'] is True
    assert 'response' not in failed['result']
    assert report['status'] == 'partial' and not report['proposals']


@pytest.mark.parametrize('kind', ['file_symlink', 'parent_symlink', 'directory'])
def test_source_symlinks_and_nonfiles_are_rejected_without_models(lab, kind):
    path = lab.root / 'harness/example.py'
    if kind == 'file_symlink':
        path.unlink()
        path.symlink_to(lab.root / 'AGENTS.md')
    elif kind == 'parent_symlink':
        directory = lab.root / 'parser_tidy'
        moved = lab.root.parent / 'moved-parser-fixture'
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    else:
        path.unlink()
        path.mkdir()
    report = scan(lab, forbidden)
    assert report['status'] == 'failed' and not report['review_complete']
    assert all(a['status'] == 'not_called' for a in report['agents'])


def test_handoff_guard_rechecks_expiry_before_any_write_enabled_call(lab):
    pid, _, _ = authorize(lab)
    writes = []
    def executor(task, files, **options):
        name = 'approvals/' + pid + '.json'
        approval = lab.store.verify(lab.store.read(name))
        approval['expires_at'] = NOW.isoformat()
        lab.store.write(name, lab.store.sign(approval))
        options['_improvement_guard'](RUN_ID)
        writes.append(files)
        return {'status': 'passed', 'run_id': RUN_ID}
    result = imp.execute(pid, now=NOW, selected=lab.selected, executor=executor)
    assert result['status'] == 'failed' and writes == []
    assert lab.store.verify(lab.store.read('claims/' + pid + '.json'))['status'] == 'consumed'


@pytest.mark.parametrize('failure', ['none', 'cli', 'contract', 'truncated', 'source'])
def test_private_glm_telemetry_survives_scan_failures_and_public_is_identical(lab, failure):
    from harness.test_agent_telemetry import sample

    def transform(role, result, response, options):
        if role == 'downloader':
            result['telemetry'] = sample()
            result['telemetry']['secret'] = 'SENSITIVE_DIAGNOSTIC /host/private'
            if failure == 'cli':
                result['status'] = 'failed'
                result['telemetry']['outcome'] = 'timeout'
            elif failure == 'contract':
                result['response'] = '{"invalid":true}'
            elif failure == 'truncated':
                result['response'] = 'x' * (lab.config['limits']['max_response_bytes'] + 20000)
            elif failure == 'source':
                path = options['workspace'] / 'downloader/example.py'
                path.chmod(0o600)
                path.write_text('changed\n')
        return result

    report = scan(lab, ModelRunner(lab, transform=transform))
    agent = next(a for a in report['agents'] if a['role'] == 'downloader')
    assert agent['status'] == ('succeeded' if failure == 'none' else 'failed')
    value = agent['telemetry']
    assert value['logical_requests_observed'] == 1
    assert value['parent']['context_preparation_ms'] >= 0
    assert (value['parent']['source_verification_ms'] is None) == (failure == 'cli')
    assert 'SENSITIVE_DIAGNOSTIC' not in json.dumps(agent)
    if failure == 'truncated':
        assert agent['result_truncated'] is True
    saved = lab.store.read('scans/' + report['scan_id'] + '.json')
    assert saved['agents'][1]['telemetry'] == value
    without = copy.deepcopy(report)
    for item in without['agents']:
        item.pop('telemetry', None)
    baseline = contract.canonical_json(contract.build_web_report(without))
    injected = copy.deepcopy(report)
    injected['telemetry'] = {'raw': 'TOP_LEVEL_SECRET'}
    for item in injected['agents']:
        item['telemetry'] = {'raw': 'PROMPT_SECRET', 'endpoint': 'https://private'}
        item['result'] = {'stdout': 'RAW_SECRET'}
    assert contract.canonical_json(contract.build_web_report(injected)) == baseline
    assert contract.canonical_json(contract.build_web_report(report)) == baseline


def call_diagnostic_role(lab, runner, role='coordinator'):
    """Exercise the real boundary with approved synthetic source snapshots."""
    paths = imp.role_scope(role, FILES, lab.config)
    snapshots = imp.snapshot_sources(paths, lab.config['limits'], lab.selected)
    return imp._call_role(role, paths, snapshots, lab.config, [], {}, runner, lab.selected)


@pytest.mark.parametrize('failure,reason', [
    ('malformed', 'role_json_invalid'),
    ('edit_type', 'candidate_edit_files_invalid'),
    ('edit_item_type', 'candidate_edit_files_invalid'),
    ('edit_duplicate', 'candidate_edit_files_duplicate'),
    ('edit_scope', 'candidate_edit_files_outside_scope'),
    ('candidate', 'candidate_invalid'),
    ('review', 'review_invalid'),
    ('envelope', 'role_result_invalid'),
    ('identity_role', 'role_identity_mismatch'),
    ('identity_provider', 'role_identity_mismatch'),
    ('identity_model', 'role_identity_mismatch'),
    ('execution_status', 'role_execution_failed'),
    ('execution_exception', 'role_execution_failed'),
    ('context_content', 'role_context_changed'),
    ('context_mode', 'role_context_changed'),
])
def test_role_failure_comes_from_actual_boundary_not_result_diagnostics(lab, failure, reason):
    marker = 'SYNTHETIC_UNTRUSTED_FAILURE /private/provider-path'
    observed = []

    def corrupt(role, result, response, options):
        observed.append(options['workspace'])
        # Even a known code in remote metadata cannot override the failed step.
        result.update(reason='candidate_edit_files_duplicate', stage=marker,
                      field=marker, error_type=marker,
                      diagnostics={'reason': 'role_interrupted', 'raw': marker})
        if failure == 'malformed':
            result['response'] = '{broken ' + marker
        elif failure.startswith('edit_'):
            response['candidates'][0]['edit_files'] = {
                'edit_type': 'harness/example.py', 'edit_item_type': [True],
                'edit_duplicate': ['harness/example.py'] * 2,
                'edit_scope': ['harness/not-approved.py'],
            }[failure]
            result['response'] = json.dumps(response)
        elif failure == 'candidate':
            response['candidates'][0]['priority'] = marker
            result['response'] = json.dumps(response)
        elif failure == 'review':
            result['response'] = '{"reviews":[],"documentation":{}}'
        elif failure == 'envelope':
            return [marker]
        elif failure.startswith('identity_'):
            result[failure.split('_', 1)[1]] = 'unexpected-fixture-identity'
        elif failure == 'execution_status':
            result['status'] = marker
        elif failure == 'execution_exception':
            # Exception class names, as well as messages, can carry free text.
            raise type(marker, (RuntimeError,), {})(marker)
        elif failure.startswith('context_'):
            target = options['workspace'] / 'harness/example.py'
            target.chmod(0o600)
            if failure == 'context_content':
                target.write_text(marker)
                target.chmod(0o400)
        return result

    runner = ModelRunner(lab, transform=corrupt)
    agent, parsed = call_diagnostic_role(lab, runner, 'reviewer' if failure == 'review' else 'coordinator')
    assert parsed is None and agent['status'] != 'succeeded'
    assert agent['reason'] == reason
    assert agent['error_type'] == ('Exception' if failure == 'execution_exception' else
                                   'ValidationError' if failure in (
                                       'malformed', 'edit_type', 'edit_item_type',
                                       'edit_duplicate', 'edit_scope', 'candidate', 'review') else
                                   'ImprovementError')
    # Legacy result retention is separate; new diagnostics contain fixed codes only.
    assert marker not in json.dumps({k: agent[k] for k in ('reason', 'error_type')})
    assert len(runner.calls) == 1 and all(not path.exists() for path in observed)
    assert 'TAVERN_IMPROVEMENT_DISCOVERY' not in os.environ
    assert (lab.root / 'harness/example.py').read_text().startswith('first_value = 1')
    if failure == 'execution_status':
        assert agent['cost'] == .0123 and agent['cost_status'] == 'cli_estimated_usd'


class DiagnosticString(str):
    """A provider-controlled str subclass has no fixed-code authority."""


@pytest.mark.parametrize('reason,expected', [
    ('candidate_edit_files_invalid', 'candidate_edit_files_invalid'),
    ('candidate_edit_files_duplicate', 'candidate_edit_files_duplicate'),
    ('candidate_edit_files_outside_scope', 'candidate_edit_files_outside_scope'),
    ('review_invalid', 'candidate_invalid'),
    ('role_json_invalid', 'candidate_invalid'),
    ('candidate_edit_files_typo', 'candidate_invalid'),
    ('SECRET /private/exception-reason', 'candidate_invalid'),
    ('x' * 65537, 'candidate_invalid'),
    (DiagnosticString('candidate_edit_files_duplicate'), 'candidate_invalid'),
    (None, 'candidate_invalid'), (True, 'candidate_invalid'),
    (1, 'candidate_invalid'), ([], 'candidate_invalid'),
    ({'reason': 'candidate_edit_files_duplicate'}, 'candidate_invalid'),
], ids=['invalid_edits', 'duplicate_edits', 'outside_edits', 'review_code', 'json_code',
        'unknown_code', 'secret', 'oversized', 'str_subclass', 'null', 'bool', 'integer',
        'list', 'mapping'])
def test_candidate_exception_metadata_is_revalidated_at_call_boundary(lab, monkeypatch, reason, expected):
    error = contract.ValidationError('SECRET /private/validation-message')
    # Bypass constructor sanitization to test the adapter's own trust boundary.
    error.reason = reason
    error.stage = 'role_json_invalid'
    error.field = 'SECRET /private/field'

    def reject(*args, **kwargs):
        raise error

    monkeypatch.setattr(contract, 'validate_candidates', reject)
    agent, parsed = call_diagnostic_role(lab, ModelRunner(lab))
    assert parsed is None and agent['status'] == 'failed'
    assert agent['reason'] == expected and agent['error_type'] == 'ValidationError'
    assert not any(key in agent for key in ('stage', 'field', 'diagnostic', 'line', 'column'))


@pytest.mark.parametrize('kind', ['ordinary', 'subclass'])
def test_only_shared_validation_error_can_supply_edit_failure_code(lab, monkeypatch, kind):
    error_class = RuntimeError if kind == 'ordinary' else type('DerivedValidation', (contract.ValidationError,), {})
    error = error_class('SECRET /private/error')
    error.reason = 'candidate_edit_files_duplicate'

    def reject(*args, **kwargs):
        raise error

    monkeypatch.setattr(contract, 'validate_candidates', reject)
    agent, parsed = call_diagnostic_role(lab, ModelRunner(lab))
    assert parsed is None and agent['reason'] == 'candidate_invalid'
    assert agent['error_type'] == 'Exception'


@pytest.mark.parametrize('failure', ['preparation', 'cleanup', 'interrupt', 'success'])
def test_diagnostic_boundary_preserves_preparation_cleanup_interrupt_and_success(lab, monkeypatch, failure):
    runner = ModelRunner(lab)
    contexts = []
    previous_guard = 'synthetic-previous-discovery-guard'
    monkeypatch.setenv('TAVERN_IMPROVEMENT_DISCOVERY', previous_guard)
    actual_directory = lab.selected.temporary_directory

    @contextmanager
    def failing_cleanup(*args, **kwargs):
        with actual_directory(*args, **kwargs) as context:
            contexts.append(context)
            yield context
        raise RuntimeError('SECRET /private/cleanup')

    if failure == 'preparation':
        def unavailable():
            raise RuntimeError('SECRET /private/config')
        monkeypatch.setattr(agent_models, 'load_config', unavailable)
    elif failure == 'cleanup':
        monkeypatch.setattr(type(lab.selected), 'temporary_directory',
                            lambda self, *args, **kwargs: failing_cleanup(*args, **kwargs))
    elif failure == 'interrupt':
        def interrupt(role, result, response, options):
            raise KeyboardInterrupt('SECRET /private/interrupt')
        runner.transform = interrupt

    agent, parsed = call_diagnostic_role(lab, runner)
    assert os.environ['TAVERN_IMPROVEMENT_DISCOVERY'] == previous_guard
    assert all(not entry['workspace'].exists() for entry in runner.calls)
    assert all(not context.exists() for context in contexts)
    assert len(runner.calls) == (0 if failure == 'preparation' else 1)
    if failure == 'success':
        assert agent['status'] == 'succeeded' and parsed == [candidate()]
        assert 'reason' not in agent and 'error_type' not in agent
        assert agent['cost'] == .0123 and agent['cost_status'] == 'cli_estimated_usd'
    else:
        assert parsed is None
        assert agent['reason'] == {'preparation': 'role_preparation_failed',
                                   'cleanup': 'role_context_cleanup_failed',
                                   'interrupt': 'role_interrupted'}[failure]
        assert agent['error_type'] == ('KeyboardInterrupt' if failure == 'interrupt' else 'Exception')
        assert agent.get('interrupted', False) is (failure == 'interrupt')
        assert 'SECRET' not in json.dumps({k: agent[k] for k in ('reason', 'error_type')})


def test_empty_discovery_with_only_shared_docs_for_owner_is_incomplete(lab):
    # Removing the program from the synthetic approval must not permit shared
    # documentation to masquerade as that owner's completed code inspection.
    paths = [p for p in FILES if not p.startswith('downloader/')]
    lab.scope.write_text('\n'.join(paths) + '\n', encoding='utf-8')
    runner = ModelRunner(lab, candidates={})
    private = scan(lab, runner)
    assert private['status'] == 'partial' and not private['review_complete']
    assert [c['role'] for c in runner.calls] == list(contract.SPECIALIST_ROLES)
    reviewer = private['agents'][-1]
    assert reviewer['role'] == 'reviewer' and reviewer['status'] == 'unavailable'
    assert reviewer['reason'] == 'source_review_unverified'
    public = imp.report(DATE, selected=lab.selected)
    assert public['counts']['eligible'] == 0 and public['proposals'] == []
    assert '점검 미완료' in public['headline']
    assert '개선점 없음' in public['summary']
    assert not lab.store.exists('authority.key')
