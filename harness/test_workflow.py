"""Exercise routing, real file publication and fail-closed gates without model APIs."""
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from harness import agent_models, git_publish, triage, workflow, workspace


@pytest.fixture
def project(tmp_path, monkeypatch):
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
    subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
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
            'checks': {'fixture': {'status': 'passed', 'selected': 1, 'passed': 1, 'skipped': []}}}


def runner_for(calls, mutate=None, verdict='approved'):
    def run(role, task, keys, **options):
        calls.append((role, options['write'], options['workspace']))
        if role == 'reviewer':
            response = {'verdict': verdict, 'summary': 'Reviewed.', 'findings': [] if verdict == 'approved' else
                        [{'file': 'parser_tidy/example.py', 'severity': 'high', 'message': 'Fix it.'}]}
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


def run_fixture(scope=None, **options):
    return workflow.execute('Make the assigned improvement.', scope or ['parser_tidy/example.py'],
                            rules_only=True, keys={}, checker=successful_check, **options)


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
