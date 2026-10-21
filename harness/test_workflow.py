"""Exercise routing, real file publication and fail-closed gates without model APIs."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess

import pytest

from harness import agent_models, git_publish, storage, triage, workflow, workspace


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch):
    # Even tests using the real source snapshot must not consume the operator's
    # private config or touch real mounts. Configured tests inject a fake seam.
    monkeypatch.delenv(storage.CONFIG_ENV, raising=False)
    monkeypatch.delenv(storage.REPORT_ENV, raising=False)
    original_root = workflow.ROOT
    resolve = storage.resolve_storage
    def isolated_resolve(project_root=None, *, env=None, fs=None):
        root = original_root if project_root is None else Path(project_root)
        if root == original_root:
            return storage.Storage(root=root, env={}, fs=fs or storage.FileSystem())
        return resolve(root, env=env, fs=fs)
    monkeypatch.setattr(storage, 'resolve_storage', isolated_resolve)


@pytest.fixture
def project(tmp_path, monkeypatch):
    # Synthetic projects choose their own modes; do not inherit parent controls.
    for key in list(os.environ):
        if key.startswith(('GIT_', 'SSH_', 'GCM_')) or key in (
                'GIT', 'READ_ONLY', 'GH_TOKEN', 'GITHUB_TOKEN', 'EMAIL'):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / 'git-home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home))
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_TERMINAL_PROMPT', '0')
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', 'file')
    root = tmp_path / 'project'
    root.mkdir()
    for name, text in {
        'AGENTS.md': 'Instructions.\n', '.gitignore': '/logs/\n.agent-keys.json\n.env\n',
        'harness/pytest.ini': '[pytest]\naddopts =\n',
        'downloader/AGENTS.md': 'Downloader.\n', 'parser_tidy/AGENTS.md': 'Parser.\n',
        'TavernofSoul/AGENTS.md': 'Django.\n',
        'downloader/example.py': 'existing downloader edit\n',
        'parser_tidy/example.py': 'existing parser edit\n',
        'TavernofSoul/example.py': 'existing Django edit\n',
    }.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
    subprocess.run(['git', 'init', '--template=', '-q', str(root)], check=True, capture_output=True)
    subprocess.run(['git', 'symbolic-ref', 'HEAD', 'refs/heads/master'], cwd=str(root),
                   check=True, capture_output=True)
    monkeypatch.setattr(workflow, 'ROOT', root)
    monkeypatch.setattr(workflow, 'REPORTS', root / 'logs/harness/workflows')
    monkeypatch.setattr(agent_models, 'KEY_FILE', root / '.agent-keys.json')
    monkeypatch.delenv('TAVERN_WORKFLOW_CHILD', raising=False)
    for name in agent_models.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(agent_models, 'connection_status', lambda *a: {'status': 'ready'})
    config = git_publish.load_config()
    monkeypatch.setattr(git_publish, 'load_config', lambda: {**config, 'enabled': False})
    monkeypatch.setattr(agent_models, 'run', lambda *a, **kw: pytest.fail('Real model started'))
    monkeypatch.setattr(triage.jev_client, 'evaluate', lambda *a, **kw: pytest.fail('Real Jev called'))
    return root


def successful_check(candidate, command, report_dir, keys, policy):
    return {'command': command, 'status': 'passed', 'source': 'fixture',
            'exit_code': 0,
            'checks': {'fixture': {'status': 'passed', 'selected': 1, 'passed': 1, 'skipped': []}}}


def runner_for(calls, mutate=None, verdict='approved', documentation=None):
    def run(role, task, keys, **options):
        calls.append((role, options['write'], options['workspace']))
        if role == 'reviewer':
            response = {'verdict': verdict, 'summary': 'Reviewed.', 'findings': [] if verdict == 'approved' else
                        [{'file': 'parser_tidy/example.py', 'severity': 'high', 'message': 'Fix it.'}],
                        'documentation': documentation if documentation is not None else
                        {'status': 'not_required', 'files': [],
                         'reason': 'The synthetic local edit preserves structure, contracts and '
                                   'harness policy; no design or usage document changes are needed.'}}
        elif role == 'git':
            response = {'commit_message': 'Fix assigned parser behavior', 'pr_title': 'Fix parser behavior',
                        'pr_body': 'Correct the assigned behavior. Validation: fixture check passed.'}
        elif task.startswith('Plan this development task'):
            owners = json.loads(re.search(r'Owners: (.*)\nTask:', task).group(1))
            response = {'tasks': [{'role': owner, 'task': 'Implement.', 'files': [name]}
                                  for name, owner in owners.items()]}
        else:
            files = json.loads(re.search(r'Allowed edit files \(exact paths\): (.*)\n', task).group(1))
            if options['write']:
                for name in files:
                    path = options['workspace'] / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('validated edit\n', encoding='utf-8')
            response = 'Implemented.' if options['write'] else 'Analyzed without edits.'
            if mutate:
                mutate(options['workspace'])
        spec = agent_models.load_config()['roles'][role]
        return {'role': role, 'provider': spec['provider'], 'model': spec['model'],
                'status': 'passed', 'response': json.dumps(response) if isinstance(response, dict) else response}
    return run


def run_fixture(scope=None, checker=successful_check, **options):
    return workflow.execute('Make the assigned improvement.', scope or ['parser_tidy/example.py'],
                            rules_only=True, keys={}, checker=checker, **options)


def test_cross_area_routes_to_configured_specialists_and_publishes_after_gates(project):
    calls = []
    scope = ['downloader/example.py', 'parser_tidy/example.py', 'TavernofSoul/example.py']
    report = run_fixture(scope, runner=runner_for(calls))
    assert report['status'] == 'passed', report.get('error')
    assert [role for role, _, _ in calls] == ['coordinator', 'django', 'downloader', 'parser', 'reviewer']
    assert [write for _, write, _ in calls] == [False, True, True, True, False]
    assert all(path != project for _, _, path in calls)
    assert report['required_checks'] == ['check']
    assert sorted(report['applied']) == sorted(scope)
    assert all((project / name).read_text() == 'validated edit\n' for name in scope)
    backup = Path(report['report']).parent / 'backup'
    assert (backup / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'
    events = report['events']
    assert {event['phase'] for event in events} == set(workflow.PHASES)
    assert any(event['phase'] == 'implement' and event['role'] == 'downloader' and
               event['provider'] == 'zai' and event['model'] == 'glm-5.3-flash' for event in events)
    assert next(i for i, event in enumerate(events) if event['phase'] == 'apply') > \
        max(i for i, event in enumerate(events) if event['phase'] == 'validate')
    assert Path(report['report']).stat().st_mode & 0o777 == 0o600


def test_direct_jev_route_skips_planner_and_preserves_required_checks(project, monkeypatch):
    decision = {'status': 'passed', 'source': 'fixture', 'recommendation':
                {'role': 'parser', 'required_checks': ['check-parser']}}
    monkeypatch.setattr(triage, 'observe', lambda *a, **kw: decision)
    calls = []
    report = run_fixture(runner=runner_for(calls))
    assert report['status'] == 'passed'
    assert [role for role, _, _ in calls] == ['parser', 'reviewer']
    assert report['required_checks'] == ['check-parser']
    assert report['review']['documentation']['status'] == 'not_required'


def test_jev_failure_uses_codex_planning_and_full_check(project):
    calls = []
    report = workflow.execute('Improve parsing.', ['parser_tidy/example.py'], keys={},
                              runner=runner_for(calls), checker=successful_check)
    assert report['triage']['fallback_reason'] == 'missing_typesafe_key'
    assert calls[0][0] == 'coordinator' and calls[1][0] == 'parser'
    assert report['required_checks'] == ['check'] and report['status'] == 'passed'


def enable_github(project, monkeypatch):
    cfg = git_publish.load_config()
    monkeypatch.setattr(git_publish, 'load_config', lambda: {**cfg, 'enabled': True})
    subprocess.run(['git', 'remote', 'add', 'origin', 'https://github.com/21in7/TavernofSoul.git'],
                   cwd=str(project), check=True, capture_output=True)


def test_workflow_hands_github_to_parent_only_after_review_checks_and_apply(project, monkeypatch):
    enable_github(project, monkeypatch)
    calls = []
    report = run_fixture(runner=runner_for(calls))
    assert report['status'] == 'awaiting_github', report.get('error')
    assert [role for role, _, _ in calls] == ['coordinator', 'parser', 'reviewer', 'git']
    assert calls[-1][1] is False
    assert report['applied'] == ['parser_tidy/example.py']
    assert report['current']['phase'] == 'github' and report['current']['stage'] == 8
    assert report['github']['status'] == 'awaiting_connector'
    ledger = json.loads((Path(report['report']).parent / 'github.json').read_text())
    assert set(ledger['files']) == {'parser_tidy/example.py'}
    assert ledger['step'] == 'repository' and 'pr_number' not in ledger
    assert calls[-1][2] == Path(report['model_workspace'])


def test_parent_read_only_is_isolated_before_synthetic_github_preparation(request, monkeypatch):
    monkeypatch.setenv('READ_ONLY', '1')
    # Request project lazily so the inherited control is present during setup.
    project = request.getfixturevalue('project')
    assert 'READ_ONLY' not in os.environ
    enable_github(project, monkeypatch)
    calls, checks = [], []
    name = 'parser_tidy/example.py'
    def checker(candidate, command, report_dir, keys, policy):
        checks.append(command)
        if command == 'check':
            assert (candidate / name).read_text() == 'validated edit\n'
            assert (project / name).read_text() == 'existing parser edit\n'
        return successful_check(candidate, command, report_dir, keys, policy)
    report = run_fixture(runner=runner_for(calls), checker=checker)
    assert report['status'] == 'awaiting_github', report.get('error')
    assert checks == ['doctor', 'check']
    assert [role for role, _, _ in calls] == ['coordinator', 'parser', 'reviewer', 'git']
    assert calls[-1][1] is False
    assert report['review']['verdict'] == 'approved'
    assert report['applied'] == [name]
    assert (project / name).read_text() == 'validated edit\n'
    assert report['github']['status'] == 'awaiting_connector'
    directory = Path(report['report']).parent
    assert project in directory.parents
    journal = json.loads((directory / 'github.json').read_text())
    assert journal['status'] == 'awaiting_connector' and journal['step'] == 'repository'
    assert set(journal['files']) == {name}
    assert journal['files'][name]['after']['content'] == 'validated edit\n'
    assert 'pr_number' not in journal


@pytest.mark.parametrize('mode', ['read_only', 'no_git'])
def test_explicit_local_or_read_only_request_skips_git_model_and_delivery(project, monkeypatch, mode):
    enable_github(project, monkeypatch)
    calls = []
    report = run_fixture(runner=runner_for(calls), **{mode: True})
    assert report['status'] == 'passed'
    assert not any(role == 'git' for role, _, _ in calls)
    assert report['github']['status'] == 'skipped'
    assert not (Path(report['report']).parent / 'github.json').exists()


@pytest.mark.parametrize('kind', ['write', 'extra_fields'])
def test_git_model_cannot_modify_reviewed_source_or_request_extra_fields(project, monkeypatch, kind):
    enable_github(project, monkeypatch)
    normal = runner_for([])
    def bad(role, task, keys, **options):
        result = normal(role, task, keys, **options)
        if role == 'git':
            if kind == 'write':
                (options['workspace'] / 'parser_tidy/example.py').write_text('unreviewed edit')
            else:
                metadata = json.loads(result['response'])
                result['response'] = json.dumps({**metadata, 'repository': 'unapproved/repo'})
        return result
    report = run_fixture(runner=bad)
    assert report['status'] == 'failed'
    assert (project / 'parser_tidy/example.py').read_text() == 'validated edit\n'
    assert not (Path(report['report']).parent / 'github.json').exists()


def test_repaired_task_uses_final_successful_round_for_github_delivery(project, monkeypatch):
    enable_github(project, monkeypatch)
    checks = []
    def fail_once(candidate, command, report_dir, keys, policy):
        result = successful_check(candidate, command, report_dir, keys, policy)
        if command != 'doctor':
            checks.append(command)
            if len(checks) == 1:
                result['status'] = 'failed'
        return result
    report = workflow.execute('Repair this parser behavior.', ['parser_tidy/example.py'],
                              rules_only=True, keys={}, runner=runner_for([]), checker=fail_once)
    assert report['status'] == 'awaiting_github', report.get('error')
    assert report['round'] == 2
    assert report['validation'][0]['status'] == 'failed'
    assert all(item['status'] == 'passed' for item in report['delivery_validation'])
    assert report['github']['status'] == 'awaiting_connector'


@pytest.mark.parametrize('path', ['.agent-keys.json', '.env', '.env.local', '.git/config',
                                  'TavernofSoul/itos/3.8/lib/a.py', 'ktos_unpack/a.ies',
                                  'TavernofSoul/TavernofSoul/itos.ini', 'harness/node_modules/a.js',
                                  '../outside.py', 'parser_tidy'])
def test_protected_or_directory_scope_is_rejected_before_agents(project, path):
    with pytest.raises(ValueError):
        workflow.execute('Change a file.', [path], runner=lambda *a, **kw: pytest.fail('Agent started'))


def test_symlink_scope_and_ancestors_are_rejected(project, tmp_path):
    target = tmp_path / 'outside.py'
    target.write_text('Keep.\n')
    (project / 'parser_tidy/link.py').symlink_to(target)
    (project / 'linked').symlink_to(tmp_path, target_is_directory=True)
    for name in ('parser_tidy/link.py', 'linked/outside.py'):
        with pytest.raises(ValueError, match='Symlinks'):
            workflow.scoped_files(project, [name])


def test_copy_excludes_credentials_runtime_environments_and_preserves_user_content(project):
    policy = workflow.load_policy()
    for name in ('.agent-keys.json', 'TavernofSoul/ktest/3.8/runtime.py',
                 'TavernofSoul/TavernofSoul/ktos.ini', 'ktos_unpack/local.ies'):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('private data')
    candidate = project / 'logs/candidate'
    baseline = workspace.copy_validation_sources(project, candidate, ['parser_tidy/example.py'], policy)
    assert 'harness/pytest.ini' in baseline
    assert (candidate / 'harness/pytest.ini').read_text() == '[pytest]\naddopts =\n'
    assert baseline['parser_tidy/example.py']['sha256'] == workspace.fingerprint(
        project / 'parser_tidy/example.py', policy['max_file_bytes'])['sha256']
    assert (candidate / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'
    assert not any((candidate / name).exists() for name in ('.agent-keys.json', 'ktos_unpack', 'TavernofSoul/ktest'))


@pytest.mark.parametrize('edit', ['extra_file', 'symlink', 'reviewer_write', 'planner_write', 'failed_agent'])
def test_failed_or_out_of_scope_agents_cannot_modify_originals(project, edit):
    calls = []
    normal = runner_for(calls)
    def bad(role, task, keys, **options):
        result = normal(role, task, keys, **options)
        candidate = options['workspace']
        if edit == 'extra_file' and options['write']:
            (candidate / 'downloader').mkdir(exist_ok=True)
            (candidate / 'downloader/example.py').write_text('unexpected')
        if edit == 'symlink' and options['write']:
            (candidate / 'parser_tidy/example.py').unlink()
            (candidate / 'parser_tidy/example.py').symlink_to(project / 'parser_tidy/example.py')
        if edit == 'reviewer_write' and role == 'reviewer':
            (candidate / 'parser_tidy/example.py').write_text('reviewer edited')
        if edit == 'planner_write' and task.startswith('Plan this development task'):
            (candidate / 'parser_tidy/example.py').write_text('planner edited')
        if edit == 'failed_agent' and options['write']:
            result['status'] = 'failed'
        return result
    report = run_fixture(runner=bad)
    assert report['status'] == 'failed' and report['applied'] == []
    assert (project / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'


@pytest.mark.parametrize('plan', [
    {'tasks': []},
    {'tasks': [{'role': 'reviewer', 'task': 'Edit.', 'files': ['parser_tidy/example.py']}]},
    {'tasks': [{'role': 'parser', 'task': 'Edit.', 'files': ['parser_tidy/extra.py']}]},
    {'tasks': [{'role': 'parser', 'task': 'Edit.', 'files': ['parser_tidy/example.py']}] * 2},
    {'tasks': [{'role': 'parser', 'task': 'Edit.', 'files': ['parser_tidy/example.py', 'parser_tidy/example.py']}]},
])
def test_planner_cannot_expand_scope_duplicate_tasks_or_change_owner(plan):
    with pytest.raises(ValueError):
        workflow.parse_plan(json.dumps(plan), ['parser_tidy/example.py'], workflow.load_policy())


@pytest.mark.parametrize('response', ['Looks good.', '{}', '{"verdict":"approved","findings":[]}',
                                    '{"verdict":"changes_requested","findings":[],"summary":"No."}',
                                    '{"verdict":"approved","findings":[{}],"summary":"Yes."}'])
def test_reviewer_success_text_is_not_an_approval(response):
    with pytest.raises(ValueError):
        workflow.parse_review(response, ['parser_tidy/example.py'])


def test_review_rejection_retries_only_up_to_bound_and_never_publishes(project):
    calls = []
    report = run_fixture(runner=runner_for(calls, verdict='changes_requested'))
    assert report['status'] == 'failed'
    assert [role for role, _, _ in calls].count('parser') == workflow.load_policy()['max_rounds']
    assert report['validation'] == [] and report['applied'] == []
    assert (project / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'


def test_check_failure_repairs_and_requires_new_review_before_publication(project):
    calls, checks = [], []
    def fail_once(candidate, command, report_dir, keys, policy):
        result = successful_check(candidate, command, report_dir, keys, policy)
        if command != 'doctor':
            checks.append(command)
            result['status'] = 'failed' if len(checks) == 1 else 'passed'
        return result
    report = workflow.execute('Fix.', ['parser_tidy/example.py'], rules_only=True, keys={},
                              runner=runner_for(calls), checker=fail_once)
    assert report['status'] == 'passed' and report['round'] == 2
    assert [role for role, _, _ in calls] == ['coordinator', 'parser', 'reviewer', 'parser', 'reviewer']
    assert [check['status'] for check in report['validation']] == ['failed', 'passed']


def test_permanent_check_failure_preserves_originals(project):
    def failed(candidate, command, report_dir, keys, policy):
        result = successful_check(candidate, command, report_dir, keys, policy)
        if command != 'doctor':
            result['status'] = 'failed'
        return result
    report = workflow.execute('Fix.', ['parser_tidy/example.py'], rules_only=True, keys={},
                              runner=runner_for([]), checker=failed)
    assert report['status'] == 'failed' and report['applied'] == []
    assert (project / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'


def test_concurrent_original_change_prevents_publication_without_erasing_it(project):
    def concurrent(candidate, command, report_dir, keys, policy):
        if command != 'doctor':
            (project / 'parser_tidy/example.py').write_text('new edit from user\n')
        return successful_check(candidate, command, report_dir, keys, policy)
    report = workflow.execute('Fix.', ['parser_tidy/example.py'], rules_only=True, keys={},
                              runner=runner_for([]), checker=concurrent)
    assert report['status'] == 'failed' and 'Original sources changed' in report['error']
    assert (project / 'parser_tidy/example.py').read_text() == 'new edit from user\n'


def test_checks_that_change_candidate_sources_fail_before_publication(project):
    def changes_source(candidate, command, report_dir, keys, policy):
        if command != 'doctor':
            (candidate / 'parser_tidy/example.py').write_text('changed by tests')
        return successful_check(candidate, command, report_dir, keys, policy)
    report = workflow.execute('Fix.', ['parser_tidy/example.py'], rules_only=True, keys={},
                              runner=runner_for([]), checker=changes_source)
    assert report['status'] == 'failed' and report['applied'] == []


def test_read_only_workflow_runs_real_roles_but_never_enables_edit_tools(project):
    calls = []
    report = run_fixture(runner=runner_for(calls), read_only=True)
    assert report['status'] == 'passed' and not report['changed_files'] and not report['applied']
    assert not any(write for _, write, _ in calls)
    assert report['review']['documentation']['status'] == 'not_required'


@pytest.mark.parametrize('kind', ['passed', 'skipped', 'empty', 'missing', 'crashed',
                                  'invalid_json', 'non_object', 'invalid_group', 'bool_count'])
def test_check_exit_zero_requires_complete_structured_coverage(project, monkeypatch, kind):
    report_dir = project / 'logs/check'
    def fake(command, **kwargs):
        report_dir.mkdir(parents=True, exist_ok=True)
        if kind != 'missing':
            group = {'status': 'passed', 'selected': 1, 'passed': 1, 'skipped': []}
            if kind == 'skipped':
                group.update(passed=0, skipped=[{'test': 'required', 'reason': 'xfail'}])
            if kind == 'empty':
                group.update(selected=0, passed=0)
            if kind == 'bool_count':
                group.update(selected=True, passed=True)
            data = {'status': 'passed', 'checks': {'parser': [] if kind == 'invalid_group' else group}}
            if kind == 'non_object':
                data = []
            (report_dir / 'check.json').write_text('invalid' if kind == 'invalid_json' else json.dumps(data))
        assert '--report-dir' in command and kwargs['cwd'] == str(project)
        assert 'OPENAI_API_KEY' not in kwargs['env']
        assert 'PYTHONPATH' not in kwargs['env']
        return subprocess.CompletedProcess(command, 1 if kind == 'crashed' else 0, 'Output.', '')
    monkeypatch.setenv('OPENAI_API_KEY', 'not-for-checks')
    monkeypatch.setenv('PYTHONPATH', '/not/the/candidate')
    monkeypatch.setattr(workflow.subprocess, 'run', fake)
    result = workflow.run_check(project, 'check', report_dir, {}, workflow.load_policy())
    assert (result['status'] == 'passed') == (kind == 'passed')


def test_publication_rolls_back_only_its_own_partial_changes(project, monkeypatch):
    policy = workflow.load_policy()
    scope = ['parser_tidy/example.py', 'downloader/example.py']
    candidate = project / 'logs/candidate'
    baseline = workspace.copy_validation_sources(project, candidate, scope, policy)
    for name in scope:
        (candidate / name).write_text('new candidate\n')
    validated = workspace.manifest(candidate, policy)
    real_replace, calls = workspace.replace_file, []
    def fail_second(source, target, mode):
        calls.append(target)
        if len(calls) == 2:
            raise OSError('Disk write failed')
        real_replace(source, target, mode)
    monkeypatch.setattr(workspace, 'replace_file', fail_second)
    with pytest.raises(OSError):
        workspace.publish(project, candidate, baseline, validated, sorted(scope), scope,
                          project / 'logs/backup', policy)
    assert (project / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'
    assert (project / 'downloader/example.py').read_text() == 'existing downloader edit\n'


def test_preview_and_demo_never_call_real_agents_or_modify_sources(project, capsys):
    assert workflow.main(['plan', '--file', 'parser_tidy/example.py']) == 0
    assert '"agent_started": false' in capsys.readouterr().out
    assert workflow.main(['demo']) == 0
    report = json.loads(next(workflow.REPORTS.glob('*/report.json')).read_text())
    assert report['simulated'] and report['status'] == 'demonstrated' and report['applied'] == []
    assert report['review']['documentation']['status'] == 'not_required'
    assert all(not event.get('agent_started') for event in report['events'])
    assert not (project / 'harness/fixtures/workflow/example.txt').exists()
    assert workflow.main(['status']) == 0
    assert workflow.main(['status', '--run-id', '../bad']) == 1


def test_workflow_workers_cannot_recursively_start_orchestration(project, monkeypatch):
    monkeypatch.setenv('TAVERN_WORKFLOW_CHILD', '1')
    with pytest.raises(ValueError, match='must not start another'):
        run_fixture(runner=runner_for([]))


def test_missing_review_key_prevents_implementation_calls(project, monkeypatch):
    monkeypatch.setattr(agent_models, 'connection_status', lambda provider, keys:
                        {'status': 'not_configured' if provider == 'claude' else 'ready'})
    calls = []
    report = run_fixture(runner=runner_for(calls))
    assert report['status'] == 'failed' and calls == []


def test_secrets_in_task_responses_and_events_are_redacted(project, monkeypatch):
    keys = {'ANTHROPIC_API_KEY': 'test-secret-value'}
    monkeypatch.setattr(agent_models, 'load_keys', lambda: keys)
    normal = runner_for([])
    def secret_response(role, task, received, **options):
        assert keys['ANTHROPIC_API_KEY'] not in task
        result = normal(role, task, received, **options)
        if options['write']:
            result['response'] = keys['ANTHROPIC_API_KEY']
        return result
    report = workflow.execute('Fix ' + keys['ANTHROPIC_API_KEY'], ['parser_tidy/example.py'],
                              keys=keys, rules_only=True, runner=secret_response, checker=successful_check)
    assert report['status'] == 'passed'
    assert keys['ANTHROPIC_API_KEY'] not in json.dumps(report)
    assert keys['ANTHROPIC_API_KEY'] not in Path(report['report']).read_text()


def test_cli_workspace_and_plugin_paths_do_not_point_at_original_sources(project):
    command = agent_models.command_for('parser', write=True, workspace=project)
    assert command[command.index('--cd') + 1] == str(project)
    assert 'agents.enabled=false' in command
    reviewer = agent_models.command_for('reviewer', workspace=project)
    assert reviewer[reviewer.index('--plugin-dir') + 1] == str(project / 'harness/compaction')
    assert 'Do not delegate' in agent_models.task_prompt('parser', 'Assigned task.', workspace=project)
    assert 'TAVERN_WORKFLOW_CHILD=1' in agent_models.task_prompt('parser', 'Assigned task.', workspace=project)


def test_native_cli_generated_typings_are_artifacts_and_never_publishable(project):
    policy = workflow.load_policy()
    before = workspace.manifest(project, policy)
    path = project / workspace.PLUGIN_TYPES / 'claude-code/index.d.ts'
    path.parent.mkdir(parents=True)
    path.write_text('declare const generated: string;')
    assert workspace.manifest(project, policy) == before
    assert workspace.protected(path.relative_to(project).as_posix())
    with pytest.raises(ValueError, match='Protected'):
        workflow.scoped_files(project, [path.relative_to(project).as_posix()])
    other = project / 'harness/other/types/generated.d.ts'
    other.parent.mkdir(parents=True)
    other.write_text('declare const unexpected: string;')
    with pytest.raises(ValueError, match='outside'):
        workspace.enforce_scope(before, workspace.manifest(project, policy), [], read_only=True)


def test_workflow_exception_saves_failed_state_instead_of_leaving_running(project):
    def unexpected(*args, **kwargs):
        raise RuntimeError('Unexpected provider failure')
    report = run_fixture(runner=unexpected)
    assert report['status'] == 'failed' and report['error_type'] == 'RuntimeError'
    saved = json.loads(Path(report['report']).read_text())
    assert saved['status'] == 'failed'


def test_status_identifies_a_dead_process_without_rewriting_its_record(project, monkeypatch, capsys):
    report = run_fixture(runner=runner_for([]), read_only=True)
    path = Path(report['report'])
    report['status'] = 'running'
    agent_models.private_json(path, report)
    def gone(*args):
        raise ProcessLookupError()
    monkeypatch.setattr(workflow.os, 'kill', gone)
    assert workflow.main(['status']) == 1
    assert '"status": "abandoned"' in capsys.readouterr().out
    assert json.loads(path.read_text())['status'] == 'running'


def test_source_snapshot_can_run_actual_offline_harness_checks(tmp_path):
    # Exercise the repository copy and a real check together, so a missing ignored
    # fixture/configuration cannot be hidden by a mocked checker or root-only tests.
    policy = workflow.load_policy()
    candidate = tmp_path / 'candidate'
    workspace.copy_validation_sources(agent_models.ROOT, candidate, ['downloader/downloader.py'], policy)
    for command in ('doctor', 'check-downloader'):
        result = workflow.run_check(candidate, command, tmp_path / command, {}, policy)
        assert result['status'] == 'passed', Path(result['log']).read_text()
    assert result['checks']['downloader']['selected'] == result['checks']['downloader']['passed'] > 0
    assert not result['checks']['downloader']['skipped']


def test_model_copy_contains_only_approved_files_without_git_discovery(project, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, 'source_names', lambda *args: pytest.fail('Discovered extra source'))
    scope = ['parser_tidy/example.py', 'parser_tidy/new.py']
    candidate = tmp_path / 'model'
    baseline = workspace.copy_sources(project, candidate, scope, workflow.load_policy())
    assert set(baseline) == {'parser_tidy/example.py'}
    assert workspace.manifest(candidate, workflow.load_policy()) == baseline
    assert not (candidate / 'AGENTS.md').exists()
    assert not (candidate / 'harness/pytest.ini').exists()
    assert not (candidate / 'downloader/example.py').exists()
    assert not (candidate / 'parser_tidy/new.py').exists()


def test_model_copy_does_not_import_host_git_templates(project, tmp_path, monkeypatch):
    template = tmp_path / 'host-git-template'
    (template / 'hooks').mkdir(parents=True)
    (template / 'hooks/pre-commit').write_text('UNAPPROVED-HOST-TEMPLATE')
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'init.templateDir')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', str(template))
    candidate = tmp_path / 'model'
    workspace.copy_sources(project, candidate, ['parser_tidy/example.py'], workflow.load_policy())
    assert not (candidate / '.git/hooks/pre-commit').exists()


def test_workflow_separates_model_reads_from_local_validation_and_does_not_send_logs(project):
    calls, prompts, contexts, checks = [], [], [], []
    normal = runner_for(calls)
    marker = 'UNAPPROVED-SOURCE-CANARY'
    (project / 'downloader/example.py').write_text(marker)

    def restricted(role, task, keys, **options):
        context = options['workspace']
        assert options['scoped'] is True
        assert not str(context).startswith(str(project) + '/')
        assert set(workspace.manifest(context, workflow.load_policy())) == {'parser_tidy/example.py'}
        assert marker not in task and 'downloader/example.py' not in task
        contexts.append(context)
        prompts.append(task)
        return normal(role, task, keys, **options)

    def local(candidate, command, report_dir, keys, policy):
        assert (candidate / 'downloader/example.py').read_text() == marker
        assert candidate not in contexts
        result = successful_check(candidate, command, report_dir, keys, policy)
        if command != 'doctor':
            assert (candidate / 'parser_tidy/example.py').read_text() == 'validated edit\n'
            checks.append(command)
            if len(checks) == 1:
                result.update(status='failed', log=str(candidate / 'downloader/example.py'))
                result['checks']['fixture']['failures'] = [{'source': marker}]
        return result

    report = workflow.execute('Fix approved parser file.', ['parser_tidy/example.py'], keys={},
                              rules_only=True, runner=restricted, checker=local)
    assert report['status'] == 'passed', report.get('error')
    assert report['round'] == 2
    assert report['model_read_scope'] == ['parser_tidy/example.py']
    assert report['model_workspace'] != report['workspace']
    context_report = json.loads(Path(report['model_context_manifest']).read_text())
    assert set(context_report['copied_files']) == {'parser_tidy/example.py'}
    assert marker in json.dumps(report['validation'])  # Private local diagnostics are retained.
    assert all(marker not in prompt for prompt in prompts)


def test_sync_scope_propagates_reversions_and_deletions_without_copying_extra_files(project, tmp_path):
    policy = workflow.load_policy()
    scope = ['parser_tidy/example.py', 'parser_tidy/new.py']
    candidate, context = tmp_path / 'local', tmp_path / 'model'
    workspace.copy_validation_sources(project, candidate, scope, policy)
    baseline = workspace.copy_sources(candidate, context, scope, policy)
    (context / scope[0]).write_text('first edit')
    (context / scope[1]).write_text('new source')
    workspace.sync_scope(context, candidate, baseline, scope, policy)
    (context / scope[0]).write_text('existing parser edit\n')
    (context / scope[1]).unlink()
    workspace.sync_scope(context, candidate, baseline, scope, policy)
    assert (candidate / scope[0]).read_text() == 'existing parser edit\n'
    assert not (candidate / scope[1]).exists()
    assert (candidate / 'downloader/example.py').read_text() == 'existing downloader edit\n'


@pytest.mark.parametrize('invalid, category', [
    ('{"tasks":[', 'json_syntax'),
    ('{"tasks":[]}', 'plan_schema'),
    ('{"tasks":[{"role":"parser","task":"Implement.","files":["parser_tidy/example.py"]}]', 'json_syntax'),
    ('{"tasks":[{"role":"parser","task":"Fix "PRIVATE-UNESCAPED-CODE" slices.",'
     '"files":["parser_tidy/example.py"]}]}', 'json_syntax'),
])
def test_plan_parse_failure_repairs_only_coordinator_with_trusted_guidance(project, invalid, category):
    calls, prompts = [], []
    normal = runner_for(calls)
    def repair(role, task, keys, **options):
        prompts.append((role, task))
        result = normal(role, task, keys, **options)
        if task.startswith('Plan this development task') and len(calls) == 1:
            result['response'] = invalid
        return result
    report = run_fixture(runner=repair)
    assert report['status'] == 'passed', report.get('error')
    assert [role for role, _, _ in calls] == ['coordinator', 'coordinator', 'parser', 'reviewer']
    assert report['plan_recovered'] is True
    assert report['plan_attempts'][0]['diagnostic']['category'] == category
    if category == 'json_syntax':
        with pytest.raises(json.JSONDecodeError) as caught:
            json.loads(invalid)
        assert report['plan_attempts'][0]['diagnostic'] == {
            'category': category, 'line': caught.value.lineno,
            'column': caught.value.colno, 'position': caught.value.pos}
    second = prompts[1][1]
    assert second.startswith('Plan this development task')
    assert 'Owners: {"parser_tidy/example.py": "parser"}\nTask:' in second
    assert 'fresh short complete valid JSON object' in second
    assert 'Correctly escape task strings' in second
    assert '\n' + invalid not in second
    assert 'PRIVATE-UNESCAPED-CODE' not in second
    assert any(event['state'] == 'recovered' for event in report['events'])


@pytest.mark.parametrize('cap', [1, 2, 3])
def test_repeated_malformed_plan_never_implements_applies_or_publishes(project, monkeypatch, cap):
    policy = workflow.load_policy()
    monkeypatch.setattr(workflow, 'load_policy', lambda: {**policy, 'max_plan_attempts': cap})
    calls, prompts = [], []
    normal = runner_for(calls)
    def malformed(role, task, keys, **options):
        prompts.append(task)
        result = normal(role, task, keys, **options)
        result['response'] = '{"tasks": "PRIVATE-INVALID-RESPONSE"'
        return result
    report = run_fixture(runner=malformed)
    assert report['status'] == 'failed' and report['applied'] == []
    assert len(calls) == cap and all(role == 'coordinator' for role, _, _ in calls)
    assert len(report['plan_attempts']) == cap and report['validation'] == []
    assert 'Plan attempts exhausted' in report['error']
    assert all('PRIVATE-INVALID-RESPONSE' not in prompt for prompt in prompts)
    assert (project / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'
    assert not any(event['phase'] in ('implement', 'apply', 'github') for event in report['events'])


@pytest.mark.parametrize('value', [0, 4, True, 1.0, '2', None])
def test_plan_attempt_policy_bounds_are_strict_and_independent(project, monkeypatch, value):
    policy = workflow.load_policy()
    config = project / 'workflow-policy.json'
    config.write_text(json.dumps({**policy, 'max_plan_attempts': value}))
    monkeypatch.setattr(workflow, 'CONFIG', config)
    with pytest.raises(ValueError, match='max_plan_attempts'):
        workflow.load_policy()
    config.write_text(json.dumps({**policy, 'max_plan_attempts': 3, 'max_rounds': 1}))
    assert workflow.load_policy()['max_plan_attempts'] == 3


@pytest.mark.parametrize('kind', ['owner', 'scope', 'planner_write', 'cli_failure'])
def test_unsafe_planner_failures_are_fatal_without_repair(project, kind):
    calls = []
    normal = runner_for(calls)
    def unsafe(role, task, keys, **options):
        result = normal(role, task, keys, **options)
        if kind in ('owner', 'scope'):
            result['response'] = json.dumps({'tasks': [{'role': 'downloader' if kind == 'owner' else 'parser',
                'task': 'Edit.', 'files': ['parser_tidy/outside.py' if kind == 'scope' else 'parser_tidy/example.py']}]})
        elif kind == 'planner_write':
            (options['workspace'] / 'parser_tidy/example.py').write_text('planner edit')
        else:
            result['status'] = 'failed'
        return result
    report = run_fixture(runner=unsafe)
    assert report['status'] == 'failed' and report['applied'] == []
    assert len(calls) == 1 and calls[0][0] == 'coordinator'
    assert (project / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'


SLICE_SOURCE = 'def test_slice_newline():\n    text = "abc\\n"\n    assert text[:3] == "abc\\n"\n'


def scoped_repair_runner(calls, prompts, fix=True, unchanged=False):
    normal = runner_for(calls)
    attempts = []
    def run(role, task, keys, **options):
        prompts.append((role, task))
        result = normal(role, task, keys, **options)
        if options['write']:
            names = json.loads(re.search(r'Allowed edit files \(exact paths\): (.*)\n', task).group(1))
            if 'parser_tidy/example.py' in names:
                attempts.append(task)
                source = SLICE_SOURCE
                if fix and len(attempts) > 1:
                    source = source.replace('text[:3]', 'text[:4]')
                if unchanged:
                    source = SLICE_SOURCE
                (options['workspace'] / 'parser_tidy/example.py').write_text(source)
        return result
    return run


def slice_check(checks, fail_always=False):
    def check(candidate, command, report_dir, keys, policy):
        result = successful_check(candidate, command, report_dir, keys, policy)
        if command != 'doctor':
            checks.append(command)
            if fail_always or 'text[:3]' in (candidate / 'parser_tidy/example.py').read_text():
                result['status'] = 'failed'
                result['checks']['fixture']['failures'] = [{
                    'test': 'parser_tidy/example.py::test_slice_newline[PRIVATE-PARAM]',
                    'reason': str(candidate / 'parser_tidy/example.py') + ':3: in test_slice_newline\n'
                              'E   AssertionError: PRIVATE-RUNTIME-VALUE\n' +
                              str(candidate / 'parser_tidy/example.py') + ':3: AssertionError',
                    'longrepr': 'UNAPPROVED-SOURCE-CANARY', 'log': '/outside/SECRET-LOG'}]
        return result
    return check


def test_assertion_excerpt_routes_to_exact_task_without_downloader_or_same_owner_retry(project):
    (project / 'parser_tidy/other.py').write_text('another user edit\n')
    calls, prompts, checks = [], [], []
    scope = ['parser_tidy/example.py', 'parser_tidy/other.py', 'downloader/example.py']
    report = workflow.execute('Fix scoped behavior.', scope, rules_only=True, keys={},
                              runner=scoped_repair_runner(calls, prompts), checker=slice_check(checks))
    assert report['status'] == 'passed', report.get('error')
    assert [role for role, _, _ in calls] == \
        ['coordinator', 'downloader', 'parser', 'parser', 'reviewer', 'parser', 'reviewer']
    repair_prompts = [prompt for role, prompt in prompts if 'Required correction;' in prompt]
    assert len(repair_prompts) == 1
    assert '3:     assert text[:3] == ' in repair_prompts[0]
    assert 'test_slice_newline' in repair_prompts[0] and 'AssertionError' in repair_prompts[0]
    assert 'Allowed edit files (exact paths): ["parser_tidy/example.py"]' in repair_prompts[0]
    assert checks == report['required_checks'] * 2
    assert report['repairs'][0]['target_files'] == ['parser_tidy/example.py']
    assert report['repairs'][0]['assignments'][0]['sent'] is True
    for _, prompt in prompts:
        assert all(marker not in prompt for marker in
                   ('PRIVATE-PARAM', 'PRIVATE-RUNTIME-VALUE', 'UNAPPROVED-SOURCE-CANARY', 'SECRET-LOG'))
    assert 'PRIVATE-RUNTIME-VALUE' in json.dumps(report['validation'])
    assert 'text[:4]' in (project / 'parser_tidy/example.py').read_text()


def test_reviewer_findings_only_repair_the_task_owning_each_finding(project):
    (project / 'parser_tidy/other.py').write_text('separate user edit\n')
    calls, prompts, reviews = [], [], []
    normal = runner_for(calls)
    def review_once(role, task, keys, **options):
        prompts.append((role, task))
        result = normal(role, task, keys, **options)
        if role == 'reviewer':
            reviews.append(task)
            if len(reviews) == 1:
                result['response'] = json.dumps({'verdict': 'changes_requested',
                    'documentation': json.loads(result['response'])['documentation'],
                    'summary': 'NOT-FOR-REPAIR-SUMMARY', 'findings': [
                        {'file': 'parser_tidy/other.py', 'severity': 'high', 'message': 'OWN-FINDING'}]})
        return result
    report = run_fixture(['parser_tidy/example.py', 'parser_tidy/other.py', 'downloader/example.py'],
                         runner=review_once)
    assert report['status'] == 'passed', report.get('error')
    repairs = [prompt for _, prompt in prompts if 'Required correction;' in prompt]
    assert len(repairs) == 1 and 'OWN-FINDING' in repairs[0]
    assert 'Allowed edit files (exact paths): ["parser_tidy/other.py"]' in repairs[0]
    assert 'NOT-FOR-REPAIR-SUMMARY' not in repairs[0]
    assert len(reviews) == 2


def test_repeated_same_failure_records_no_source_progress_and_preserves_user_edit(project):
    calls, prompts, checks = [], [], []
    (project / 'parser_tidy/example.py').write_text(SLICE_SOURCE)
    report = workflow.execute('Fix newline assertion.', ['parser_tidy/example.py'], rules_only=True, keys={},
        runner=scoped_repair_runner(calls, prompts, fix=False, unchanged=True),
        checker=slice_check(checks, fail_always=True))
    assert report['status'] == 'failed' and report['repair_failure'] == 'no_progress'
    assert report['applied'] == [] and len(checks) == 2
    first, last = report['repairs']
    assert first['assignments'][0]['failure_fingerprint'] == last['assignments'][0]['failure_fingerprint']
    assert last['assignments'][0]['same_failure_recurred'] is True
    assert last['assignments'][0]['preceding_attempt_source_changed'] is False
    assert last['assignments'][0]['sent'] is False
    assert all(not attempt['source_changed'] for attempt in report['implementation_attempts'])
    assert any('preceding implementation attempt made no assigned source change' in prompt
               for _, prompt in prompts)
    assert any(event['state'] == 'no_progress' for event in report['events'])
    assert (project / 'parser_tidy/example.py').read_text() == SLICE_SOURCE


def test_last_failure_with_source_changes_reports_exhausted_repair(project):
    calls, prompts, checks, attempts = [], [], [], []
    normal = scoped_repair_runner(calls, prompts, fix=False)
    def changing(role, task, keys, **options):
        result = normal(role, task, keys, **options)
        if options['write']:
            attempts.append(task)
            (options['workspace'] / 'parser_tidy/example.py').write_text(
                SLICE_SOURCE + '# correction attempt {}\n'.format(len(attempts)))
        return result
    report = workflow.execute('Fix.', ['parser_tidy/example.py'], rules_only=True, keys={},
                              runner=changing, checker=slice_check(checks, fail_always=True))
    assert report['status'] == 'failed' and report['repair_failure'] == 'exhausted_repair'
    assert report['repairs'][-1]['assignments'][0]['same_failure_recurred'] is True
    assert all(attempt['source_changed'] for attempt in report['implementation_attempts'])
    assert report['applied'] == []
    assert (project / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'


@pytest.mark.parametrize('malformed', [None, 'PRIVATE-MALFORMED',
    {'fixture': {'errors': [{'frames': [{'file': '/outside/parser_tidy/example.py', 'line': 3}],
                            'test': 'parser_tidy/example.py::test[PRIVATE-PARAM]',
                            'exception_type': 'PRIVATE-TYPE', 'reason': 'PRIVATE-MESSAGE'}]}},
    {'fixture': {'failures': [{'file': 'parser_tidy/../downloader/example.py', 'line': True,
                             'reason': ['PRIVATE-MESSAGE'], 'longrepr': {'secret': 'PRIVATE-LONGREPR'}}]}}])
def test_malformed_and_unapproved_diagnostics_never_leak_into_any_prompt(project, malformed):
    calls, prompts, checks = [], [], []
    normal = runner_for(calls)
    def capture(role, task, keys, **options):
        prompts.append(task)
        return normal(role, task, keys, **options)
    def fail_once(candidate, command, report_dir, keys, policy):
        result = successful_check(candidate, command, report_dir, keys, policy)
        if command != 'doctor':
            checks.append(command)
            if len(checks) == 1:
                result.update(status='failed', checks=malformed, log='/outside/PRIVATE-LOG')
        return result
    report = workflow.execute('Fix.', ['parser_tidy/example.py'], rules_only=True, keys={},
                              runner=capture, checker=fail_once)
    assert report['status'] == 'passed', report.get('error')
    assert report['repairs'][0]['fallback'] is True
    assert all('PRIVATE-' not in prompt and '/outside' not in prompt and
               'downloader/example.py' not in prompt for prompt in prompts)
    assert checks == report['required_checks'] * 2


@pytest.mark.parametrize('category', ['skipped', 'errors'])
def test_failure_categories_override_success_and_fallback_keeps_all_original_checks(project, monkeypatch, category):
    monkeypatch.setattr(triage, 'observe', lambda *a, **kw: {'status': 'passed', 'source': 'fixture',
        'recommendation': {'role': 'parser', 'required_checks': ['check-parser', 'check-pipeline']}})
    checks, calls, prompts = [], [], []
    normal = runner_for(calls)
    def capture(role, task, keys, **options):
        prompts.append(task)
        return normal(role, task, keys, **options)
    def fail_once(candidate, command, report_dir, keys, policy):
        result = successful_check(candidate, command, report_dir, keys, policy)
        if command != 'doctor':
            checks.append(command)
            if len(checks) == 1:
                # Untrusted 'passed' must not conceal skipped/error outcomes.
                result['checks']['fixture'][category] = [{'reason': 'PRIVATE-UNATTRIBUTED'}]
        return result
    report = workflow.execute('Fix.', ['parser_tidy/example.py'], rules_only=True, keys={},
                              runner=capture, checker=fail_once)
    assert report['status'] == 'passed', report.get('error')
    assert checks == ['check-parser', 'check-pipeline'] * 2
    assert report['repairs'][0]['fallback'] is True
    assert report['validation'][0]['status'] == 'failed'
    assert any('unavailable' in prompt and 'unattributed' in prompt for prompt in prompts)
    assert all('PRIVATE-UNATTRIBUTED' not in prompt for prompt in prompts)


@pytest.mark.parametrize('failure', ['review', 'check'])
def test_read_only_failures_never_enable_writes_or_retry_repairs(project, failure):
    calls = []
    report = workflow.execute('Analyze.', ['parser_tidy/example.py'], rules_only=True, keys={}, read_only=True,
        runner=runner_for(calls, verdict='changes_requested' if failure == 'review' else 'approved'),
        checker=slice_check([], fail_always=True) if failure == 'check' else successful_check)
    assert report['status'] == 'failed' and report['round'] == 1 and report['applied'] == []
    assert [role for role, _, _ in calls] == ['coordinator', 'parser', 'reviewer']
    assert not any(write for _, write, _ in calls)
    assert all(not item['sent'] for record in report['repairs'] for item in record['assignments'])
    assert (project / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'


def test_approved_excerpt_still_redacts_registered_secret_before_prompt(project):
    secret = 'SECRET-IN-APPROVED-SOURCE'
    calls, prompts = [], []
    normal = runner_for(calls)
    def capture(role, task, keys, **options):
        assert secret not in task
        prompts.append(task)
        result = normal(role, task, keys, **options)
        if options['write']:
            (options['workspace'] / 'parser_tidy/example.py').write_text(SLICE_SOURCE + '# ' + secret + '\n')
        return result
    report = workflow.execute('Fix.', ['parser_tidy/example.py'], rules_only=True,
        keys={'OPENAI_API_KEY': secret}, runner=capture, checker=slice_check([], fail_always=True))
    assert report['status'] == 'failed'
    assert any('[REDACTED]' in prompt and 'Required correction;' in prompt for prompt in prompts)
    assert secret not in json.dumps(report)


@pytest.mark.parametrize('documentation', [
    None, {}, [], 'updated',
    {'status': 'unknown', 'files': [], 'reason': 'Local change.'},
    {'status': 'not_required', 'files': [], 'reason': ' \t\n'},
    {'status': 'not_required', 'files': [], 'reason': False},
    {'status': 'not_required', 'files': [], 'reason': 'Local change.', 'extra': True},
    {'status': 'not_required', 'files': [], 'extra': 'missing reason'},
    {'status': 'not_required', 'reason': 'Missing files.'},
    {'status': 'not_required', 'files': {}, 'reason': 'Local change.'},
    {'status': 'not_required', 'files': ['docs/design.md'], 'reason': 'Local change.'},
    {'status': 'updated', 'files': [], 'reason': 'Changed docs.'},
    {'status': 'updated', 'files': ['docs/outside.md'], 'reason': 'Changed docs.'},
    {'status': 'updated', 'files': ['parser_tidy/example.py'], 'reason': 'Changed docs.'},
    {'status': 'updated', 'files': ['docs/design.md'], 'reason': 'Unchanged docs.'},
    {'status': 'updated', 'files': ['docs/design.md'] * 2, 'reason': 'Changed docs.'},
    {'status': 'updated', 'files': [None], 'reason': 'Changed docs.'},
    {'status': 'updated', 'files': [{}], 'reason': 'Changed docs.'},
    {'status': 'missing', 'files': [], 'reason': 'Design required.'},
])
def test_invalid_documentation_fails_before_checks_apply_or_git(project, monkeypatch, documentation):
    enable_github(project, monkeypatch)
    doc = project / 'docs/design.md'
    doc.parent.mkdir()
    doc.write_text('existing design\n')
    calls, checks = [], []
    normal = runner_for(calls)
    def invalid(role, task, keys, **options):
        # Use a changed document for the duplicate case, so duplicate rejection
        # cannot be masked by the unchanged-file gate.
        before = (options['workspace'] / 'docs/design.md').read_text()
        result = normal(role, task, keys, **options)
        duplicated = isinstance(documentation, dict) and documentation.get('files') == ['docs/design.md'] * 2
        if not duplicated:
            (options['workspace'] / 'docs/design.md').write_text(before)
        if role == 'reviewer':
            review = json.loads(result['response'])
            if documentation is None:
                review.pop('documentation')
            else:
                review['documentation'] = documentation
            result['response'] = json.dumps(review)
        return result
    def capture_check(*args):
        checks.append(args[1])
        return successful_check(*args)
    report = run_fixture(['parser_tidy/example.py', 'docs/design.md'], runner=invalid,
                         checker=capture_check)
    assert report['status'] == 'failed' and report['round'] == 1
    assert checks == [] and report['validation'] == [] and report['applied'] == []
    assert not any(role == 'git' for role, _, _ in calls)
    assert not (Path(report['report']).parent / 'github.json').exists()
    assert doc.read_text() == 'existing design\n'
    assert (project / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'


@pytest.mark.parametrize('verdict, findings', [
    ('approved', [{'file': 'parser_tidy/example.py', 'severity': 'high', 'message': 'Needs docs.'}]),
    ('changes_requested', []),
    ('changes_requested', [{'file': 'docs/outside.md', 'severity': 'high', 'message': 'Needs docs.'}]),
])
def test_missing_documentation_requires_consistent_scoped_findings(verdict, findings):
    response = {'verdict': verdict, 'summary': 'Design is missing.', 'findings': findings,
                'documentation': {'status': 'missing', 'files': [], 'reason': 'New isolation boundary.'}}
    with pytest.raises(ValueError):
        workflow.parse_review(json.dumps(response), ['parser_tidy/example.py'])


@pytest.mark.parametrize('read_only, cap', [(False, 1), (False, 2), (False, 3), (True, 2)])
def test_out_of_scope_required_document_never_expands_scope_or_delivers(project, monkeypatch,
                                                                      read_only, cap):
    enable_github(project, monkeypatch)
    policy = workflow.load_policy()
    monkeypatch.setattr(workflow, 'load_policy', lambda: {**policy, 'max_rounds': cap})
    calls = []
    missing = {'status': 'missing', 'files': [],
               'reason': 'The new isolation boundary needs docs/harness-design.md; it is outside scope.'}
    report = run_fixture(runner=runner_for(calls, verdict='changes_requested', documentation=missing),
                         read_only=read_only)
    assert report['status'] == 'failed' and report['applied'] == [] and report['validation'] == []
    assert report['review']['documentation'] == missing
    assert [role for role, _, _ in calls].count('reviewer') == (1 if read_only else cap)
    assert not any(role == 'git' for role, _, _ in calls)
    assert not (Path(report['report']).parent / 'github.json').exists()
    context_manifest = workflow.json.loads(Path(report['model_context_manifest']).read_text())
    assert context_manifest['approved_files'] == ['parser_tidy/example.py']
    assert set(context_manifest['copied_files']) == {'parser_tidy/example.py'}
    assert not Path(report['model_workspace']).exists()
    assert all(record['target_files'] == ['parser_tidy/example.py'] for record in report['repairs'])
    assert (project / 'parser_tidy/example.py').read_text() == 'existing parser edit\n'


@pytest.mark.parametrize('existing', [False, True])
def test_changed_document_passes_review_validation_apply_and_is_retained_in_report(project, monkeypatch, existing):
    enable_github(project, monkeypatch)
    name = 'docs/design.md'
    if existing:
        (project / 'docs').mkdir()
        (project / name).write_text('previous design\n')
    judgment = {'status': 'updated', 'files': [name],
                'reason': 'The design records the changed validation responsibility.'}
    calls, checks = [], []
    def checker(candidate, command, report_dir, keys, policy):
        checks.append(command)
        if command != 'doctor':
            assert (candidate / name).read_text() == 'validated edit\n'
            if existing:
                assert (project / name).read_text() == 'previous design\n'
            else:
                assert not (project / name).exists()
        return successful_check(candidate, command, report_dir, keys, policy)
    report = run_fixture(['parser_tidy/example.py', name],
                         runner=runner_for(calls, documentation=judgment), checker=checker)
    assert report['status'] == 'awaiting_github', report.get('error')
    assert checks == ['doctor', 'check'] and set(report['applied']) == {name, 'parser_tidy/example.py'}
    assert (project / name).read_text() == 'validated edit\n'
    assert json.loads(Path(report['report']).read_text())['review']['documentation'] == judgment
    assert calls[-1][0] == 'git' and calls[-1][1] is False
    journal = json.loads((Path(report['report']).parent / 'github.json').read_text())
    assert set(journal['files']) == {name, 'parser_tidy/example.py'}
    phases = [(event['phase'], event['state']) for event in report['events']]
    assert phases.index(('review', 'approved')) < phases.index(('validate', 'passed')) < \
        phases.index(('apply', 'passed'))


def test_not_required_with_concrete_reason_allows_an_unchanged_scoped_document(project):
    name = 'docs/design.md'
    (project / 'docs').mkdir()
    (project / name).write_text('existing design\n')
    judgment = {'status': 'not_required', 'files': [],
                'reason': 'Only a local display typo changes; the documented API and isolation stay the same.'}
    calls = []
    normal = runner_for(calls, documentation=judgment)
    def preserve_doc(role, task, keys, **options):
        before = (options['workspace'] / name).read_text()
        result = normal(role, task, keys, **options)
        (options['workspace'] / name).write_text(before)
        return result
    report = run_fixture([name, 'parser_tidy/example.py'], runner=preserve_doc)
    assert report['status'] == 'passed', report.get('error')
    assert report['review']['documentation'] == judgment
    assert report['applied'] == ['parser_tidy/example.py']
    assert (project / name).read_text() == 'existing design\n'


def test_documentation_finding_repairs_only_its_task_then_requires_fresh_review(project):
    scope = ['docs/design.md', 'docs/other.md', 'parser_tidy/example.py']
    calls, reviews, checks, doc_attempts = [], [], [], []
    complete = 'Boundary: models read approved files; full verification is local.\n'
    normal = runner_for(calls)
    def repair(role, task, keys, **options):
        result = normal(role, task, keys, **options)
        if options['write']:
            files = json.loads(re.search(r'Allowed edit files \(exact paths\): (.*)\n', task).group(1))
            if 'docs/design.md' in files:
                doc_attempts.append(files)
                (options['workspace'] / 'docs/design.md').write_text(
                    'Boundary: TODO\n' if len(doc_attempts) == 1 else complete)
        if role == 'reviewer':
            reviews.append(task)
            review = json.loads(result['response'])
            review['documentation'] = {'status': 'updated', 'files': ['docs/design.md'],
                                      'reason': 'The design now describes the validation boundary.'}
            if (options['workspace'] / 'docs/design.md').read_text() != complete:
                review.update(verdict='changes_requested', findings=[
                    {'file': 'docs/design.md', 'severity': 'high', 'message': 'Explain the boundary.'}])
                review['documentation'].update(status='missing', reason='The boundary explanation is absent.')
            result['response'] = json.dumps(review)
        return result
    def checker(*args):
        checks.append(args[1])
        return successful_check(*args)
    report = run_fixture(scope, runner=repair, checker=checker)
    assert report['status'] == 'passed', report.get('error')
    assert report['round'] == 2 and len(reviews) == 2 and checks == ['doctor', 'check']
    assert doc_attempts == [['docs/design.md']] * 2
    assert (project / 'docs/design.md').read_text() == complete
    repair_record = report['repairs'][0]
    assert repair_record['target_files'] == ['docs/design.md']
    assert repair_record['target_tasks'] == [0] and repair_record['assignments'][0]['sent']
    assert [role for role, _, _ in calls] == [
        'coordinator', 'coordinator', 'coordinator', 'parser', 'reviewer', 'coordinator', 'reviewer']
    assert report['review']['documentation']['status'] == 'updated'


def test_github_enabled_apply_never_persists_overall_passed_before_delivery(project, monkeypatch):
    enable_github(project, monkeypatch)
    delegate = runner_for([])
    observed = []
    def runner(role, task, keys, **options):
        if role == 'git':
            reports = list(workflow.REPORTS.glob('*/report.json'))
            assert len(reports) == 1
            saved = json.loads(reports[0].read_text())
            observed.append(saved['status'])
            assert saved['status'] == 'running'
        return delegate(role, task, keys, **options)
    report = workflow.execute('Fix parser behavior', ['parser_tidy/example.py'],
                              rules_only=True, runner=runner, checker=successful_check, keys={})
    assert observed == ['running']
    assert report['status'] == 'awaiting_github'


def test_status_exposes_legacy_merge_cleanup_boundary_without_rewriting(project, monkeypatch, capsys):
    directory = workflow.REPORTS / '123456-abcdef'
    directory.mkdir(parents=True)
    report = {'run_id': directory.name, 'status': 'passed', 'github': {
        'status': 'merged', 'step': 'done', 'merge_sha': 'a' * 40}}
    agent_models.private_json(directory / 'report.json', report)
    assert workflow.main(['status', '--run-id', directory.name]) == 1
    shown = json.loads(capsys.readouterr().out)
    assert shown['status'] == 'cleanup_pending'
    assert shown['github']['merge_sha'] == 'a' * 40
    assert shown['github']['cleanup']['proof']['reason'] == 'legacy_cleanup_required'
    assert json.loads((directory / 'report.json').read_text()) == report


class WorkflowStorageFS(storage.FileSystem):
    """Only the declared tmp_path directory is a mount; never inspect host mounts."""
    def __init__(self, mount):
        self.mount = mount
        self.ready = True

    def mount_ready(self, path):
        return self.ready and path == self.mount

    def free_bytes(self, path):
        return 10 ** 9


@pytest.fixture
def configured_storage(project, tmp_path, monkeypatch):
    mount = tmp_path / 'fake-mount'
    mount.mkdir()
    fs = WorkflowStorageFS(mount)
    config = project / 'logs/harness/storage-local.json'
    document = {'version': 1,
                'artifacts': {'path': str(mount / 'artifacts'), 'required_mount': str(mount),
                              'min_free_bytes': 1000},
                'temporary': {'path': str(mount / 'temporary'), 'required_mount': str(mount),
                              'min_free_bytes': 1000}}
    agent_models.private_json(config, document)
    selected = storage.resolve_storage(project, env={}, fs=fs)
    resolve = storage.resolve_storage
    def fake_mount_resolve(project_root=None, *, env=None, fs=None):
        return resolve(project_root, env=env, fs=fs or selected.fs)
    monkeypatch.setattr(storage, 'resolve_storage', fake_mount_resolve)
    monkeypatch.setattr(workflow, 'storage_policy', lambda: selected)
    return selected


@pytest.mark.parametrize('outcome', ['success', 'awaiting_github', 'failed_review',
                                     'checker_exception', 'interrupted'])
def test_owned_model_context_cleanup_preserves_permanent_evidence(
        project, configured_storage, monkeypatch, outcome):
    selected = configured_storage
    sibling = selected.mkdtemp(prefix='unrelated-context-', purpose='context')
    marker = sibling / 'keep.txt'
    marker.write_text('unrelated temporary context\n')
    if outcome == 'awaiting_github':
        enable_github(project, monkeypatch)
    if outcome == 'failed_review':
        policy = workflow.load_policy()
        monkeypatch.setattr(workflow, 'load_policy', lambda: {**policy, 'max_rounds': 1})
    observed = []
    def inspect_sources(model_workspace):
        model_workspace = Path(model_workspace)
        assert model_workspace.exists()
        assert set(workspace.manifest(model_workspace, workflow.load_policy())) == {
            'parser_tidy/example.py'}
        observed.append(model_workspace)
    def checker(candidate, command, report_dir, keys, policy):
        if command == 'doctor' and outcome == 'checker_exception':
            raise RuntimeError('isolated checker failure')
        if command == 'doctor' and outcome == 'interrupted':
            raise KeyboardInterrupt('isolated interruption')
        return successful_check(candidate, command, report_dir, keys, policy)
    calls = []
    verdict = 'changes_requested' if outcome == 'failed_review' else 'approved'
    report = run_fixture(runner=runner_for(calls, mutate=inspect_sources, verdict=verdict),
                         checker=checker)
    expected = {'success': 'passed', 'awaiting_github': 'awaiting_github',
                'failed_review': 'failed', 'checker_exception': 'failed',
                'interrupted': 'interrupted'}
    assert report['status'] == expected[outcome]
    assert report['model_context_cleanup'] == {'status': 'passed'}
    assert not Path(report['model_workspace']).exists()
    if outcome in {'success', 'awaiting_github', 'failed_review'}:
        assert observed
        assert all(not model_workspace.exists() for model_workspace in observed)
    permanent_report = Path(report['report'])
    permanent_workspace = Path(report['workspace'])
    permanent_manifest = Path(report['model_context_manifest'])
    assert selected.artifact_root in permanent_report.parents
    assert permanent_report.is_file() and permanent_workspace.is_dir()
    assert (permanent_workspace / 'parser_tidy/example.py').is_file()
    manifest = workflow.json.loads(permanent_manifest.read_text())
    assert manifest['approved_files'] == ['parser_tidy/example.py']
    assert set(manifest['copied_files']) == {'parser_tidy/example.py'}
    assert workflow.json.loads(permanent_report.read_text())['status'] == expected[outcome]
    assert marker.read_text() == 'unrelated temporary context\n'
    # A fresh invocation must reacquire the same stable local project lock.
    following = run_fixture(runner=runner_for([]))
    assert following['status'] == 'passed'
    assert not Path(following['model_workspace']).exists()
    assert permanent_report.is_file() and permanent_workspace.is_dir()
    assert permanent_manifest.is_file() and marker.is_file()


def test_context_cleanup_failure_is_saved_and_releases_project_lock(
        project, configured_storage, monkeypatch):
    selected = configured_storage
    sibling = selected.mkdtemp(prefix='unrelated-context-', purpose='context')
    marker = sibling / 'keep.txt'
    marker.write_text('keep sibling\n')
    real_temporary_directory = type(selected).temporary_directory
    managers = []
    @workflow.contextlib.contextmanager
    def failing_cleanup(self, *args, **kwargs):
        manager = real_temporary_directory(self, *args, **kwargs)
        owned = manager.__enter__()
        # Retain the manager so finalization cannot mask the injected failure.
        managers.append(manager)
        try:
            yield owned
        finally:
            raise OSError('isolated context cleanup failure')
    monkeypatch.setattr(type(selected), 'temporary_directory', failing_cleanup)
    try:
        report = run_fixture(runner=runner_for([]))
        assert report['status'] == 'failed'
        cleanup = report['model_context_cleanup']
        assert cleanup['status'] == 'failed' and cleanup['error_type'] == 'OSError'
        assert cleanup['error'] == 'isolated context cleanup failure'
        assert Path(report['model_workspace']).is_dir()
        permanent_report = Path(report['report'])
        assert workflow.json.loads(permanent_report.read_text())['status'] == 'failed'
        assert workflow.json.loads(permanent_report.read_text())['model_context_cleanup'] == cleanup
        assert Path(report['workspace']).is_dir()
        assert Path(report['model_context_manifest']).is_file()
        assert marker.read_text() == 'keep sibling\n'
        monkeypatch.setattr(type(selected), 'temporary_directory', real_temporary_directory)
        following = run_fixture(runner=runner_for([]))
        assert following['status'] == 'passed'
        assert not Path(following['model_workspace']).exists()
        assert permanent_report.is_file() and Path(report['workspace']).is_dir()
        assert Path(report['model_context_manifest']).is_file() and marker.is_file()
    finally:
        for manager in managers:
            manager.__exit__(None, None, None)


def test_report_persistence_failure_still_cleans_context_and_releases_lock(
        project, configured_storage, monkeypatch):
    selected = configured_storage
    sibling = selected.mkdtemp(prefix='unrelated-context-', purpose='context')
    marker = sibling / 'keep.txt'
    marker.write_text('keep sibling\n')
    real_save = workflow.Progress.save
    fail_save = False
    contexts = []
    real_temporary_directory = type(selected).temporary_directory
    @workflow.contextlib.contextmanager
    def observed_context(self, *args, **kwargs):
        with real_temporary_directory(self, *args, **kwargs) as owned:
            contexts.append(owned)
            yield owned
    def save(progress):
        if fail_save:
            raise OSError('isolated report persistence failure')
        return real_save(progress)
    candidates = []
    def checker(candidate, command, report_dir, keys, policy):
        nonlocal fail_save
        candidates.append(candidate)
        fail_save = True
        raise RuntimeError('isolated checker failure')
    monkeypatch.setattr(type(selected), 'temporary_directory', observed_context)
    monkeypatch.setattr(workflow.Progress, 'save', save)
    with pytest.raises(OSError, match='isolated report persistence failure'):
        run_fixture(runner=runner_for([]), checker=checker)
    assert contexts and all(not context.exists() for context in contexts)
    assert candidates and all(candidate.is_dir() for candidate in candidates)
    assert (candidates[0].parent / 'report.json').is_file()
    assert (candidates[0].parent / 'model-context.json').is_file()
    assert marker.read_text() == 'keep sibling\n'
    fail_save = False
    following = run_fixture(runner=runner_for([]))
    assert following['status'] == 'passed'
    assert not Path(following['model_workspace']).exists()


def test_configured_workflow_places_all_new_artifacts_and_context_privately(
        project, configured_storage, monkeypatch):
    selected = configured_storage
    enable_github(project, monkeypatch)
    seen = []
    def checker(candidate, command, report_dir, keys, policy):
        assert selected.artifact_root in candidate.parents
        assert selected.artifact_root in report_dir.parents
        assert report_dir.stat().st_mode & 0o777 == 0o700
        seen.append(report_dir)
        return successful_check(candidate, command, report_dir, keys, policy)
    normal = runner_for([])
    def runner(role, task, keys, **options):
        context = options['workspace']
        assert selected.temp_root in context.parents
        assert project not in context.parents and context not in project.parents
        assert context.stat().st_mode & 0o777 == 0o700
        assert set(workspace.manifest(context, workflow.load_policy())) == {'parser_tidy/example.py'}
        assert not (context / 'logs/harness/storage-local.json').exists()
        assert str(selected.config_path) not in task
        return normal(role, task, keys, **options)
    report = run_fixture(runner=runner, checker=checker)
    assert report['status'] == 'awaiting_github', report.get('error')
    directory = Path(report['report']).parent
    assert directory.parent == selected.artifact_root / 'workflows'
    assert json.loads((directory.parent / 'latest.json').read_text()) == {'run_id': directory.name}
    for name in ('baseline.json', 'model-context.json', 'report.json', 'events.jsonl',
                 'github.json', 'github-approved.json'):
        assert (directory / name).stat().st_mode & 0o777 == 0o600
    for name in ('workspace', 'backup', 'prepare', 'checks-1/check'):
        assert (directory / name).stat().st_mode & 0o777 == 0o700
    assert seen == [directory / 'prepare', directory / 'checks-1/check']
    assert selected.project_lock_path == project / 'logs/harness/workflows/.lock'
    assert not list(workflow.REPORTS.glob('*/report.json'))


def storage_report(directory, status='passed', time_ns=1000, **extra):
    report = {'run_id': directory.name, 'status': status,
              'workspace': str(directory / 'workspace'), **extra}
    agent_models.private_json(directory / 'report.json', report)
    os.utime(directory / 'report.json', ns=(time_ns, time_ns))
    return report


def test_configured_status_finds_legacy_and_new_latest_without_rewriting(
        project, configured_storage, capsys):
    selected = configured_storage
    selected.prepare()
    old = workflow.REPORTS / '100-abcdef'
    new = selected.workflow_root() / '200-abcdef'
    old_report = storage_report(old, time_ns=3000)
    storage_report(new, time_ns=2000)
    old_bytes = (old / 'report.json').read_bytes()
    assert workflow.main(['status', '--run-id', old.name]) == 0
    assert json.loads(capsys.readouterr().out)['run_id'] == old.name
    assert workflow.main(['status']) == 0
    assert json.loads(capsys.readouterr().out)['run_id'] == old.name
    assert (old / 'report.json').read_bytes() == old_bytes
    assert json.loads(old_bytes)['workspace'] == old_report['workspace']
    os.utime(new / 'report.json', ns=(4000, 4000))
    assert workflow.main(['status']) == 0
    assert json.loads(capsys.readouterr().out)['run_id'] == new.name


@pytest.mark.parametrize('explicit', [True, False])
def test_status_rejects_duplicate_run_ids_across_storage_roots(
        project, configured_storage, capsys, explicit):
    selected = configured_storage
    selected.prepare()
    run_id = '100-abcdef'
    storage_report(workflow.REPORTS / run_id)
    storage_report(selected.workflow_root() / run_id)
    assert workflow.main(['status'] + (['--run-id', run_id] if explicit else [])) == 1
    assert 'Workflow failed: StorageError' in capsys.readouterr().err


@pytest.mark.parametrize('kind', ['run_symlink', 'report_symlink', 'pointer_escape',
                                 'wrong_record_id', 'invalid_pid', 'invalid_github', 'duplicate_metadata'])
def test_status_rejects_unsafe_paths_and_metadata(project, configured_storage, tmp_path,
                                                 capsys, kind):
    selected = configured_storage
    selected.prepare()
    root = selected.ensure_directory(selected.workflow_root())
    directory = root / '100-abcdef'
    storage_report(directory)
    if kind == 'run_symlink':
        outside = tmp_path / 'outside'
        directory.rename(outside)
        directory.symlink_to(outside, target_is_directory=True)
    elif kind == 'report_symlink':
        outside = tmp_path / 'outside.json'
        (directory / 'report.json').rename(outside)
        (directory / 'report.json').symlink_to(outside)
    elif kind == 'pointer_escape':
        agent_models.private_json(root / 'latest.json', {'run_id': '../100-abcdef'})
    elif kind == 'wrong_record_id':
        agent_models.private_json(directory / 'report.json', {'run_id': '200-abcdef', 'status': 'passed'})
    elif kind == 'invalid_pid':
        storage_report(directory, status='running', pid=-1)
    elif kind == 'duplicate_metadata':
        (directory / 'report.json').write_text(
            '{"run_id":"100-abcdef","status":"failed","status":"passed"}')
    else:
        storage_report(directory, github=[])
    options = ['status'] if kind == 'pointer_escape' else ['status', '--run-id', directory.name]
    assert workflow.main(options) == 1
    assert 'Workflow failed:' in capsys.readouterr().err


def test_workflow_stable_local_lock_serializes_configured_runs(project, configured_storage):
    import fcntl
    selected = configured_storage
    selected.fs.create_directory(selected.project_lock_path.parent)
    with selected.project_lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='Another workflow'):
            run_fixture(runner=lambda *a, **kw: pytest.fail('Model started despite project lock'))
    assert not list(selected.workflow_root().glob('*/report.json'))
    assert storage.Storage(root=project, env={}).project_lock_path == selected.project_lock_path
    assert selected.project_lock_path.stat().st_mode & 0o777 == 0o600
    assert not (selected.workflow_root() / '.lock').exists()


def test_missing_mount_fails_before_workflow_directories_or_models(project, configured_storage):
    selected = configured_storage
    selected.fs.ready = False
    with pytest.raises(storage.StorageError, match='mount is absent'):
        run_fixture(runner=lambda *a, **kw: pytest.fail('Model started without mount'))
    assert not selected.artifact_root.exists()
    assert not selected.temp_root.exists()
    assert not workflow.REPORTS.exists()


def test_trusted_validation_receives_disjoint_private_policy_and_child_only_tmp(
        project, configured_storage, monkeypatch):
    selected = configured_storage
    directory = selected.ensure_directory(selected.workflow_root() / '100-abcdef')
    candidate = selected.ensure_directory(directory / 'workspace')
    report_dir = directory / 'checks-1/check'
    before = {name: os.environ.get(name) for name in ('TMPDIR', 'TMP', 'TEMP', storage.CONFIG_ENV)}
    observed = []
    def fake(command, **options):
        env = options['env']
        config = Path(env[storage.CONFIG_ENV])
        assert candidate not in config.parents
        assert config != selected.config_path
        assert config.stat().st_mode & 0o777 == 0o600
        child = storage.resolve_storage(candidate, env=env, fs=selected.fs)
        child.check_ready()
        assert child.artifact_root == report_dir
        assert child.temp_root.parent == selected.temp_root
        assert env['TMPDIR'] == env['TMP'] == env['TEMP'] == str(child.temp_root)
        assert child.credential_runtime_root == candidate / 'logs/harness/agents/runtime'
        assert child.credential_temp_root == Path('/tmp')
        observed.append(child.temp_root)
        agent_models.private_json(report_dir / 'check.json', {
            'status': 'passed', 'checks': successful_check(None, None, None, None, None)['checks']})
        return subprocess.CompletedProcess(command, 0, 'checked', '')
    monkeypatch.setattr(workflow.subprocess, 'run', fake)
    result = workflow.run_check(candidate, 'check', report_dir, {}, workflow.load_policy())
    assert result['status'] == 'passed'
    assert observed and not observed[0].exists()
    assert {name: os.environ.get(name) for name in before} == before
    assert Path(result['log']).stat().st_mode & 0o777 == 0o600


def test_explicit_private_config_cannot_enter_approved_source_context(project, configured_storage,
                                                                    monkeypatch):
    config = project / 'harness/private-storage.json'
    config.write_bytes(configured_storage.config_path.read_bytes())
    monkeypatch.setenv(storage.CONFIG_ENV, str(config))
    with pytest.raises(ValueError, match='Private storage config'):
        workflow.scoped_files(project, ['harness/private-storage.json'])


def test_model_environment_does_not_inherit_actionable_storage_paths(project, monkeypatch):
    # Integration contract for the agent_models owner: validation's explicit
    # private policy must never become a model subprocess environment setting.
    monkeypatch.setenv(storage.CONFIG_ENV, str(project / 'private-storage.json'))
    monkeypatch.setenv(storage.REPORT_ENV, str(project / 'private-reports'))
    env = agent_models.child_environment('codex', {})
    assert storage.CONFIG_ENV not in env
    assert storage.REPORT_ENV not in env


def test_workflow_report_override_retains_shared_lookup_and_local_lock(
        project, configured_storage, tmp_path, capsys):
    selected = configured_storage
    selected.env[storage.REPORT_ENV] = str(tmp_path / 'chosen-reports')
    report = run_fixture(runner=runner_for([]))
    assert report['status'] == 'passed', report.get('error')
    directory = Path(report['report']).parent
    assert directory.parent == tmp_path / 'chosen-reports'
    assert selected.find_run(report['run_id'], local_default=workflow.REPORTS) == directory
    assert selected.project_lock_path == project / 'logs/harness/workflows/.lock'
    assert selected.temp_root in Path(report['model_workspace']).parents
    capsys.readouterr()
    assert workflow.main(['status']) == 0
    assert json.loads(capsys.readouterr().out)['run_id'] == report['run_id']


def test_root_only_test_seam_keeps_local_reports_inside_isolated_project(project, monkeypatch):
    monkeypatch.setattr(workflow, 'REPORTS', workflow._DEFAULT_REPORTS)
    assert workflow.local_reports() == project / 'logs/harness/workflows'
    report = run_fixture(runner=runner_for([]))
    assert report['status'] == 'passed'
    assert Path(report['report']).parent.parent == project / 'logs/harness/workflows'
    assert Path(report['model_workspace']).parent.parent == Path('/tmp')


# Improvement entrypoint regressions intentionally avoid the Git-initializing
# project fixture. Existing explicit-user workflow cases above remain intact.
@pytest.fixture
def improvement_guard_project(tmp_path, monkeypatch):
    root = tmp_path / 'guard-sources'
    (root / 'parser_tidy').mkdir(parents=True)
    (root / 'parser_tidy/example.py').write_text('existing user edit\n', encoding='utf-8')
    selected = storage.Storage(root=root, env={})
    monkeypatch.setattr(workflow, 'ROOT', root)
    monkeypatch.setattr(workflow, 'REPORTS', root / 'logs/harness/workflows')
    monkeypatch.setattr(workflow, 'storage_policy', lambda: selected)
    monkeypatch.setattr(workflow, 'load_policy', lambda: {'version': 'workflow-v1'})
    monkeypatch.setattr(triage, 'load_policy', lambda: {'max_task_bytes': 24000, 'max_files': 128})
    monkeypatch.setattr(git_publish, 'load_config', lambda: {'enabled': False})
    for flag in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY', 'TAVERN_IMPROVEMENT_UNATTENDED'):
        monkeypatch.delenv(flag, raising=False)
    return root, selected


@pytest.mark.parametrize('flag,read_only', [
    ('TAVERN_WORKFLOW_CHILD', False), ('TAVERN_WORKFLOW_CHILD', True),
    ('TAVERN_IMPROVEMENT_DISCOVERY', False), ('TAVERN_IMPROVEMENT_DISCOVERY', True),
    ('TAVERN_IMPROVEMENT_UNATTENDED', False),
])
def test_improvement_environment_rejects_before_config_storage_checks_or_models(monkeypatch, flag, read_only):
    for marker in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY', 'TAVERN_IMPROVEMENT_UNATTENDED'):
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv(flag, '1')
    def forbidden(*args, **kwargs):
        pytest.fail('Untrusted improvement caller reached workflow preparation')
    monkeypatch.setattr(workflow, 'load_policy', forbidden)
    monkeypatch.setattr(workflow, 'storage_policy', forbidden)
    with pytest.raises(ValueError, match='workers|discovery'):
        workflow.execute('Try an unapproved edit.', ['parser_tidy/example.py'], read_only=read_only,
                         keys={}, runner=forbidden, checker=forbidden, _improvement_guard=forbidden)


def test_improvement_guard_runs_under_project_lock_before_source_copy_or_checks(
        improvement_guard_project, monkeypatch):
    import fcntl
    root, selected = improvement_guard_project
    events = []
    class AuthorizationRejected(ValueError):
        pass
    def forbidden(*args, **kwargs):
        pytest.fail('Rejected authority reached source copy/check/model')
    monkeypatch.setattr(workspace, 'copy_validation_sources', forbidden)
    def guard(run_id):
        events.append(run_id)
        assert storage.RUN_ID.fullmatch(run_id)
        assert not (selected.workflow_root() / run_id).exists()
        with selected.project_lock_path.open('a') as competing:
            with pytest.raises(BlockingIOError):
                fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise AuthorizationRejected('expired approval')
    with pytest.raises(AuthorizationRejected, match='expired approval'):
        workflow.execute('Approved immutable task.', ['parser_tidy/example.py'], keys={},
                         runner=forbidden, checker=forbidden, _improvement_guard=guard)
    assert len(events) == 1
    assert (root / 'parser_tidy/example.py').read_text() == 'existing user edit\n'
    assert not (selected.workflow_root() / events[0]).exists()
    with selected.project_lock_path.open('a') as released:
        fcntl.flock(released, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize('guarded', [False, True])
def test_guard_is_optional_for_explicit_user_work_and_retains_run_identity(
        improvement_guard_project, monkeypatch, guarded):
    root, selected = improvement_guard_project
    events = []
    def stop_after_gate(*args, **kwargs):
        events.append(('copy', None))
        raise ValueError('fixture stops before any model or check')
    def forbidden(*args, **kwargs):
        pytest.fail('Fixture must stop before a model or check')
    monkeypatch.setattr(workspace, 'copy_validation_sources', stop_after_gate)
    def guard(run_id):
        events.append(('guard', run_id))
    options = {'_improvement_guard': guard} if guarded else {}
    report = workflow.execute('Explicit user development request.', ['parser_tidy/example.py'],
                              keys={}, runner=forbidden, checker=forbidden, **options)
    assert report['status'] == 'failed' and report['error'] == 'fixture stops before any model or check'
    assert [event[0] for event in events] == (['guard', 'copy'] if guarded else ['copy'])
    if guarded:
        assert events[0][1] == report['run_id']
    assert report['applied'] == [] and report['validation'] == []
    assert (root / 'parser_tidy/example.py').read_text() == 'existing user edit\n'
    assert not (root / 'logs/harness/improvements').exists()


def test_workflow_and_cleanup_lock_is_shared_with_improvement_discovery(
        improvement_guard_project, monkeypatch):
    from harness import improvements
    root, selected = improvement_guard_project
    monkeypatch.setattr(improvements, 'ROOT', root)
    monkeypatch.setattr(improvements, 'REPORTS', root / 'logs/harness/improvements')
    store = improvements.Store(selected)
    def forbidden(*args, **kwargs):
        pytest.fail('Overlapping improvement lock allowed workflow preparation')
    monkeypatch.setattr(workspace, 'copy_validation_sources', forbidden)
    with store.lock(project=True):
        with pytest.raises(ValueError, match='Another workflow'):
            workflow.execute('Explicit request during analysis.', ['parser_tidy/example.py'],
                             keys={}, runner=forbidden, checker=forbidden)


@pytest.fixture(params=[0o002, 0o022, 0o077])
def docs_creation_umask(request):
    previous = os.umask(request.param)
    try:
        yield request.param
    finally:
        os.umask(previous)


def test_actual_docs_only_with_code_read_scope_skips_dependency_doctor(project, docs_creation_umask):
    name = 'docs/guide.md'
    (project / 'docs').mkdir()
    (project / name).write_text('# Before\n')
    expected_mode = 0o666 & ~docs_creation_umask
    assert stat.S_IMODE((project / name).stat().st_mode) == expected_mode
    judgment = {'status': 'updated', 'files': [name], 'reason': 'Only the prose explanation changes.'}
    normal = runner_for([], documentation=judgment)
    commands = []
    def edit_docs(role, task, keys, **options):
        code = options['workspace'] / 'parser_tidy/example.py'
        before = code.read_bytes()
        result = normal(role, task, keys, **options)
        code.write_bytes(before)
        return result
    def check(candidate, command, report_dir, keys, policy):
        commands.append(command)
        assert command == 'check-docs'
        return workflow.run_check(candidate, command, report_dir, keys, policy)
    report = run_fixture([name, 'parser_tidy/example.py'], runner=edit_docs, checker=check)
    assert report['status'] == 'passed', report.get('error')
    assert commands == ['check-docs'] and report['required_checks'] == commands
    assert report['changed_files'] == [name]
    assert report['validation_selection']['changes'][0]['old_mode'] == expected_mode
    assert report['validation_selection']['changes'][0]['new_mode'] == expected_mode
    assert stat.S_IMODE((project / name).stat().st_mode) == expected_mode
    assert report['delivery_validation'][0]['validation_digest'] == report['validation_selection']['digest']
    assert report['delivery_validation'][0]['checks']['docs']['selected'] > 0
    assert 'environment' not in report


def test_repair_reclassifies_actual_changes_and_keeps_fresh_final_evidence(project, docs_creation_umask):
    name = 'docs/guide.md'
    (project / 'docs').mkdir()
    (project / name).write_text('# Before\n')
    expected_mode = 0o666 & ~docs_creation_umask
    assert stat.S_IMODE((project / name).stat().st_mode) == expected_mode
    judgment = {'status': 'updated', 'files': [name], 'reason': 'Prose updated alongside the repair.'}
    normal = runner_for([], documentation=judgment)
    rounds = []
    def edit(role, task, keys, **options):
        code = options['workspace'] / 'parser_tidy/example.py'
        previous = code.read_bytes()
        value = normal(role, task, keys, **options)
        if options['write'] and role == 'parser' and len(rounds) == 0:
            code.write_bytes(previous)
        return value
    def check(candidate, command, report_dir, keys, policy):
        rounds.append(command)
        value = successful_check(candidate, command, report_dir, keys, policy)
        if command == 'check-docs':
            value.update(status='failed', exit_code=1, checks={'docs': {
                'status': 'failed', 'selected': 1, 'passed': 0, 'skipped': [],
                'errors': [{'exception_type': 'ValueError'}]}})
        return value
    report = run_fixture([name, 'parser_tidy/example.py'], runner=edit, checker=check)
    # Unknown context conservatively repairs both tasks. The second actual diff
    # includes code, so its new review is followed by the original full gate.
    assert report['status'] == 'passed', report.get('error')
    assert rounds == ['check-docs', 'doctor', 'check']
    assert report['repairs'][0]['target_files'] == [name, 'parser_tidy/example.py']
    assert report['required_checks'] == ['check']
    assert [row['command'] for row in report['delivery_validation']] == ['check']
    assert report['validation_selection']['mode'] == 'full'
    assert [row['command'] for row in report['validation']] == ['check-docs', 'check']
    first, final = report['validation']
    assert first['validation_digest'] != report['validation_selection']['digest']
    assert final['validation_digest'] == report['validation_selection']['digest']
    assert report['delivery_validation'] == [final]
    assert stat.S_IMODE((project / name).stat().st_mode) == expected_mode


def test_terminal_archive_runs_after_project_lock_release_and_keeps_passed(project, configured_storage, monkeypatch):
    import fcntl
    from harness import archive
    selected = configured_storage
    selected.version = 2
    selected.fs.local_filesystem = lambda path: True
    observed = []
    def archive_after_unlock(policy, directory, kind='workflows'):
        with selected.project_lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        saved = json.loads((directory / 'report.json').read_text())
        assert saved['status'] == 'passed'
        assert saved['model_context_cleanup']['status'] == 'passed'
        observed.append(saved)
        return {'status': 'pending', 'run_id': directory.name}
    monkeypatch.setattr(archive, 'archive_run', archive_after_unlock)
    report = run_fixture(runner=runner_for([]))
    assert len(observed) == 1
    assert report['status'] == 'passed' and report['archive']['status'] == 'pending'
    assert report['applied'] == ['parser_tidy/example.py']
