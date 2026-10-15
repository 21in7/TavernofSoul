"""Offline approval/discovery boundaries with fixtures and an exact default-scope read.

The default-scope regression reads exact project sources in the executor's full
local verification copy. Other added source inputs, authority and HTTP are
synthetic. Size contracts are documented in docs/improvements.md and ADR 0015.
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
from types import SimpleNamespace

import pytest

from harness import agent_models, git_publish, improvement_report as contract
from harness import improvements as imp, storage, triage, workflow


NOW = dt.datetime(2026, 10, 14, 16, 0, tzinfo=dt.timezone.utc)
DATE = '2026-10-15'
RUN_ID = '123456789-abcdef'
FILES = ('AGENTS.md', 'docs/architecture.md', 'docs/harness-design.md',
         'harness/example.py', 'downloader/example.py', 'parser_tidy/example.py',
         'TavernofSoul/example.py', 'parser_tidy/tests/test_import_safety.py')
DOC = {'status': 'not_required', 'files': [],
       'reason': '읽기 전용 분석의 가상 지역 수정 제안으로 구조와 계약 변경이 없어 문서 수정은 필요하지 않습니다.'}


def candidate(path='harness/example.py', title='중복 점검 줄이기'):
    return {'title': title, 'priority': 'medium',
            'analogy': '정비사가 같은 나사를 두 번 살피는 점검표를 정리합니다.',
            'issue': '동일한 점검을 반복할 가능성을 검토해야 합니다.',
            'evidence': [{'path': path, 'start_line': 1, 'end_line': 2,
                          'summary': '점검 순서가 두 줄에 나뉘어 있습니다.'}],
            'benefit': {'kind': 'estimated', 'text': '미측정: 점검표를 읽는 부담 감소 예상.', 'evidence': []},
            'risk': '점검 누락 가능성을 별도 검토해야 합니다.', 'edit_files': [path],
            'validation_plan': ['해당 파일의 합성 입력으로 중복과 누락을 확인합니다.'],
            'documentation_impact': '지역 동작 보존 제안이며 구조와 권한 정책의 변경은 없습니다.'}


def forbidden(*args, **kwargs):
    pytest.fail('Offline improvement test crossed a model/check/workflow/network boundary')


@pytest.fixture
def offline_source_limits(monkeypatch):
    """Read shipped config only; never resolve operational storage or credentials."""
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(imp, 'ROOT', root)
    monkeypatch.setattr(imp, 'CONFIG', root / 'harness/improvement-config.json')
    for target, name in ((agent_models, 'load_keys'), (agent_models, 'run'),
                         (workflow, 'execute'), (workflow, 'run_check'),
                         (triage, 'observe'), (git_publish, 'prepare'),
                         (storage, 'resolve_storage'), (subprocess, 'run'),
                         (subprocess, 'Popen'), (imp.http.client, 'HTTPSConnection')):
        monkeypatch.setattr(target, name, forbidden)
    config = imp.load_config()
    assert config['limits']['max_file_bytes'] == 131072
    assert config['limits']['max_source_bytes'] == 1572864
    assert config['limits']['max_context_bytes'] == 2097152
    for key in ('max_source_bytes', 'max_context_bytes'):
        assert config['limits'][key] == contract.LIMIT_CEILINGS[key]
    return config


def test_default_project_scope_fits_configured_source_limits(offline_source_limits, tmp_path, monkeypatch):
    """Run locally in the full validation copy, never a scoped model context."""
    config = offline_source_limits
    scope, _ = imp._read_file(imp.ROOT / config['scope_file'], 65536)
    paths = contract.validate_scope_paths(scope.decode('utf-8').splitlines(),
                                          config['limits']['max_scope_files'])
    assert len(paths) == 37
    snapshots = imp.snapshot_sources(paths, config['limits'])
    fingerprints = contract.fingerprint_sources(snapshots)
    assert set(snapshots) == set(fingerprints) == set(paths)
    for path, snapshot in snapshots.items():
        assert snapshot['exists'], 'Default scope source is missing: ' + path
        content = snapshot['content']
        assert len(content) <= config['limits']['max_file_bytes']
        assert fingerprints[path] == {'exists': True, 'mode': snapshot['mode'],
                                      'size': len(content),
                                      'sha256': hashlib.sha256(content).hexdigest()}
    assert sum(item['size'] for item in fingerprints.values()) <= config['limits']['max_source_bytes']
    sources = {p: item['content'].decode('utf-8') for p, item in snapshots.items()}
    validated = contract.validate_candidate(candidate('AGENTS.md'), sources, paths)
    # Proposal construction revalidates stored source fingerprints as well.
    assert contract.proposal_record(validated, fingerprints)['source_fingerprints'] == fingerprints
    records = []
    for index in range(len(contract.SPECIALIST_ROLES) * config['limits']['max_candidates_per_specialist']):
        item = contract.validate_candidate(candidate('AGENTS.md', title='점검 제안 ' + str(index)), sources)
        records.append(contract.proposal_record(item, fingerprints))
    # Check the full reviewer context with all eight candidate slots using a
    # Python envelope only. The real snapshot is never offered to a model.
    root = tmp_path / 'sources'
    root.mkdir()
    monkeypatch.setattr(imp, 'ROOT', root)
    selected = source_limit_storage(root, tmp_path)
    spec = {'provider': 'fixture', 'model': 'fixture-model'}
    monkeypatch.setattr(agent_models, 'load_config', lambda: {'roles': {'reviewer': spec}})
    context_sizes = []

    def capture_only(role, prompt, keys, **options):
        assert role == 'reviewer' and keys == {}
        assert options['write'] is False and options['scoped'] is True
        context_sizes.append(sum(len(item['content']) for item in snapshots.values()) +
                             len(prompt.encode('utf-8')))
        response = {'reviews': [dict(candidate_id=record['id'], verdict='eligible',
                                    reason='합성 후보 envelope로 실제 소스의 context 한도만 검사합니다.',
                                    documentation=DOC) for record in records],
                    'documentation': DOC}
        return dict(spec, role=role, status='passed', response=json.dumps(response, ensure_ascii=False))

    participation, review = imp._call_role('reviewer', paths, snapshots, config,
                                          records, {}, capture_only, selected)
    assert participation['status'] == 'succeeded'
    assert len(context_sizes) == 1 and context_sizes[0] <= config['limits']['max_context_bytes']
    assert len(review['reviews']) == len(records)


@pytest.mark.parametrize('source_bytes', [1048577, 1572864])
def test_large_source_snapshots_and_fingerprints_fit_new_ceiling(
        offline_source_limits, tmp_path, monkeypatch, source_bytes):
    limits = offline_source_limits['limits']
    root = tmp_path / 'sources'
    root.mkdir()
    monkeypatch.setattr(imp, 'ROOT', root)
    expected = {}
    remaining = source_bytes
    while remaining:
        name = 'source-{:02d}.txt'.format(len(expected))
        size = min(remaining, limits['max_file_bytes'])
        content = b'x\n' * (size // 2) + b'x' * (size % 2)
        (root / name).write_bytes(content)
        expected[name] = {'exists': True, 'mode': (root / name).stat().st_mode & 0o7777,
                          'content': content}
        remaining -= len(content)
    snapshots = imp.snapshot_sources(list(expected), limits)
    assert snapshots == expected and source_bytes > 1048576
    fingerprints = contract.fingerprint_sources(snapshots)
    assert sum(item['size'] for item in fingerprints.values()) == source_bytes
    sources = {p: item['content'].decode('utf-8') for p, item in snapshots.items()}
    validated = contract.validate_candidate(candidate(next(iter(expected))), sources)
    proposal = contract.proposal_record(validated, fingerprints)
    assert proposal['source_fingerprints'] == fingerprints
    lowered = dict(limits, max_source_bytes=1048576)
    with pytest.raises(imp.ImprovementError, match='total byte limit'):
        imp.snapshot_sources(list(expected), lowered)

    if source_bytes == limits['max_source_bytes']:
        extra = {'exists': True, 'mode': 0o644, 'content': b'x'}
        (root / 'overflow.txt').write_bytes(extra['content'])
        oversized = {**snapshots, 'overflow.txt': extra}
        with pytest.raises(imp.ImprovementError, match='total byte limit'):
            imp.snapshot_sources(list(oversized), limits)
        with pytest.raises(contract.ValidationError, match='total bound'):
            contract.fingerprint_sources(oversized)
        oversized_fingerprints = {**fingerprints, **contract.fingerprint_sources({'overflow.txt': extra})}
        with pytest.raises(contract.ValidationError, match='total bound'):
            contract.proposal_record(proposal['candidate'], oversized_fingerprints)
        with pytest.raises(contract.ValidationError, match='byte bounds'):
            contract.validate_candidate(validated, {**sources, 'overflow.txt': 'x'})


@pytest.mark.parametrize('setting', ['max_source_bytes', 'max_context_bytes'])
def test_source_and_context_configuration_cannot_exceed_hard_ceilings(offline_source_limits, setting):
    config = copy.deepcopy(offline_source_limits)
    config['limits'][setting] += 1
    with pytest.raises(contract.ValidationError):
        contract.validate_config(config)


class FixtureFS(storage.FileSystem):
    """Only this test's temporary directory acts as a mount; no host probes."""
    def __init__(self, mount):
        self.mount = mount

    def mount_ready(self, path):
        return path == self.mount

    def free_bytes(self, path):
        assert path == self.mount
        return 2 ** 40


def source_limit_storage(root, tmp_path):
    return storage.Storage(root=root,
        artifacts=storage.DirectorySpec(tmp_path / 'artifacts', tmp_path, 0),
        temporary=storage.DirectorySpec(tmp_path / 'contexts', tmp_path, 0),
        config_path=tmp_path / 'synthetic-storage-policy.json', env={}, fs=FixtureFS(tmp_path))


@pytest.mark.parametrize('overflow', [0, 1])
def test_context_byte_ceiling_includes_sources_and_prompt_without_models(
        offline_source_limits, tmp_path, monkeypatch, overflow):
    config = offline_source_limits
    limits = config['limits']
    root = tmp_path / 'sources'
    root.mkdir()
    monkeypatch.setattr(imp, 'ROOT', root)
    snapshots = {'source-{:02d}.txt'.format(i):
                 {'exists': True, 'mode': 0o644, 'content': b'x' * limits['max_file_bytes']}
                 for i in range(limits['max_source_bytes'] // limits['max_file_bytes'])}
    source_bytes = sum(len(item['content']) for item in snapshots.values())
    assert source_bytes == limits['max_source_bytes'] > 1048576
    selected = source_limit_storage(root, tmp_path)
    spec = {'provider': 'fixture', 'model': 'fixture-model'}
    monkeypatch.setattr(agent_models, 'load_config', lambda: {'roles': {'reviewer': spec}})
    prompt_sizes = []

    def capture_only(role, prompt, keys, **options):
        # Pure Python envelope; no model, credentials, network or workflow.
        assert options['write'] is False and options['scoped'] is True and keys == {}
        prompt_sizes.append(len(prompt.encode('utf-8')))
        return dict(spec, role=role, status='passed', response=json.dumps(
            {'reviews': [], 'documentation': DOC}, ensure_ascii=False))

    monkeypatch.setattr(imp, 'REVIEW_PROMPT', '')
    participation, _ = imp._call_role('reviewer', list(snapshots), snapshots,
                                     config, [], {}, capture_only, selected)
    assert participation['status'] == 'succeeded'
    padding = limits['max_context_bytes'] - source_bytes - prompt_sizes[0]
    assert padding > 0
    # Non-ASCII padding catches accidental character counts in a byte contract.
    monkeypatch.setattr(imp, 'REVIEW_PROMPT', '가' * (padding // 3) + 'x' * (padding % 3 + overflow))
    prompt_sizes.clear()
    participation, review = imp._call_role('reviewer', list(snapshots), snapshots,
                                          config, [], {}, capture_only, selected)
    if overflow:
        assert prompt_sizes == [] and review is None
        assert participation['status'] == 'unavailable'
        assert participation['error_type'] == 'ImprovementError'
    else:
        assert participation['status'] == 'succeeded'
        assert source_bytes + prompt_sizes[0] == limits['max_context_bytes']
        assert review['reviews'] == []


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
        path.write_text('fixture first line\nfixture second line\n', encoding='utf-8')
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
        else:
            response = {'candidates': copy.deepcopy(self.candidates.get(role, []))}
        spec = self.lab.models['roles'][role]
        result = {'role': role, 'provider': spec['provider'], 'model': spec['model'],
                  'status': 'passed', 'response': json.dumps(response, ensure_ascii=False),
                  'cli_estimated_cost_usd': 0.0123}
        return self.transform(role, result, response, options) if self.transform else result


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
    assert [c['role'] for c in runner.calls] == list(contract.ROLES)
    shared = ['AGENTS.md', 'docs/architecture.md', 'docs/harness-design.md']
    expected = {
        'coordinator': shared + ['harness/example.py'],
        'downloader': shared + ['downloader/example.py'],
        'parser': shared + ['parser_tidy/example.py'],
        'django': shared + ['TavernofSoul/example.py', 'parser_tidy/tests/test_import_safety.py'],
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
    assert (lab.root / 'harness/example.py').read_text() == 'fixture first line\nfixture second line\n'
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
            c['issue'] = '가' * 401
        result['response'] = '{broken' if bad == 'malformed' else json.dumps(response)
        return result
    report = scan(lab, ModelRunner(lab, transform=transform))
    assert report['status'] == 'partial'
    assert report['proposals'] == []
    assert report['agents'][0]['status'] == 'failed'
    assert imp.report(DATE, selected=lab.selected)['counts']['eligible'] == 0


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
    assert (lab.root / 'harness/example.py').read_text().startswith('fixture')


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
def test_strict_json_rejects_ambiguous_or_non_utf8_model_response(text):
    with pytest.raises(contract.ValidationError):
        contract.parse_json(text)


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
            with pytest.raises(ValueError, match='already running'):
                imp.execute(pid, now=NOW, selected=lab.selected, executor=forbidden)
        finally:
            finish.set()
        assert first.result(timeout=5)['status'] == 'awaiting_github'
    assert calls == [['harness/example.py']]
    with pytest.raises(ValueError, match='claimed'):
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
                        'content': b'fixture first line\nfixture second line\n'} for path in FILES}
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
