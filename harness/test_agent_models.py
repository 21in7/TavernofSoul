"""Offline checks for provider isolation, billing selection, and failed probes."""
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from harness import agent_models as models
from harness import compaction, storage, triage
from harness import review_coverage as coverage
from harness.test_review_coverage import read_events, stdout, with_rate_limit_events


PATH_ALIASES_WARNING = 'PATH aliases: Read-only file system (os error 30)'


@pytest.mark.parametrize('mode', [
    'verified', 'no_read', 'failed_read', 'oversize', 'forged', 'failed_result', 'exit_failure'])
@pytest.mark.parametrize('notice_mode', ['none', 'valid', 'malformed', 'oversize'])
def test_discovery_only_stream_transport_and_secret_sanitization(
        local_keys, tmp_path, monkeypatch, mode, notice_mode):
    snapshots = {'AGENTS.md': {'exists': True, 'mode': 0o644, 'content': b'bounded document\n'},
                 'harness/example.py': {'exists': True, 'mode': 0o644, 'content': b'value = 1\n'}}
    owners = {r: ['harness/example.py'] for r in coverage.contract.SPECIALIST_ROLES}
    windows = coverage.plan(list(snapshots), snapshots, [], owners, ['AGENTS.md'])
    capture = coverage.Capture(tmp_path, snapshots, windows)
    calls = []
    def synthetic(command, prompt, cwd, env, timeout):
        calls.append(command)
        assert command[command.index('--output-format') + 1] == 'stream-json'
        assert '--verbose' in command
        assert command[command.index('--tools') + 1] == 'Read'
        assert command[command.index('--max-budget-usd') + 1] == '0.2'
        assert env['TAVERN_WORKFLOW_CHILD'] == '1'
        events = read_events(capture, '{"model_text":"safe response"}')
        if mode == 'no_read':
            events = events[-1:]
        elif mode == 'failed_read':
            events[1]['message']['content'][0]['is_error'] = True
        elif mode == 'forged':
            events[-1]['result'] = stdout(events)
            events = events[-1:]
        elif mode == 'oversize':
            events[0]['message']['content'].append({'type': 'text', 'text': 'x' * coverage.MAX_STDOUT})
        elif mode == 'failed_result':
            events[-1].update(is_error=True, subtype='error_max_budget_usd')
        events[-1]['total_cost_usd'] = .27
        if notice_mode != 'none':
            events = with_rate_limit_events(events)
            for event in events:
                if event['type'] == 'rate_limit_event':
                    event['rate_limit_info'].update(total_cost_usd=999, provider='PRIVATE_RATE_PROVIDER')
            if notice_mode == 'malformed':
                events[-1]['rate_limit_info']['status'] = True
            elif notice_mode == 'oversize':
                events[-1]['rate_limit_info']['errorCode'] = 'PRIVATE_RATE_METADATA' * 8192
        return subprocess.CompletedProcess(command, 7 if mode == 'exit_failure' else 0, stdout(events),
                                           local_keys['ANTHROPIC_API_KEY'] + ' /private/host diagnostic')
    # Isolate CLI discovery as well as transport from the host's Claude installation.
    monkeypatch.setattr(models.shutil, 'which', lambda cli: '/fake/' + cli)
    monkeypatch.setattr(models, '_review_subprocess', synthetic)
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **k: pytest.fail('ordinary subprocess used'))
    report = models.run('reviewer', 'bounded inspection', local_keys, timeout=17,
                        compaction=False, workspace=tmp_path, scoped=True, max_budget_usd=.2,
                        discovery_review=capture)
    assert len(calls) == 1
    if mode == 'exit_failure':
        assert 'cli_estimated_cost_usd' not in report
    else:
        assert report['cli_estimated_cost_usd'] == .27
    verified = mode == 'verified' and notice_mode in ('none', 'valid')
    assert report['provider'] == 'claude'
    assert report['status'] == ('passed' if verified else 'failed')
    assert (capture.receipts is not None) is verified
    if verified:
        assert report['response'] == '{"model_text":"safe response"}'
    assert '/private/host' not in json.dumps(report)
    assert all(secret not in json.dumps(report) for secret in local_keys.values())
    for private in ('PRIVATE_RATE_METADATA', 'PRIVATE_RATE_PROVIDER', 'private-session',
                    'rate_limit_info', 'errorCode'):
        assert private not in json.dumps(report)
        assert private not in json.dumps(capture.receipts)
    if not verified:
        assert report['error'] == 'source_review_transport_failed'


def test_discovery_capture_is_unavailable_to_other_roles_or_unscoped_calls(tmp_path, local_keys):
    capture = coverage.Capture(tmp_path, {}, [])
    for options in ({'role': 'downloader', 'scoped': True}, {'role': 'reviewer', 'scoped': False}):
        with pytest.raises(ValueError, match='source_review_transport_invalid'):
            models.run(task='fixture', keys=local_keys, workspace=tmp_path,
                       discovery_review=capture, **options)


def test_ordinary_reviewer_command_and_json_parser_stay_unchanged():
    command = models.command_for('reviewer', compaction=False)
    assert command[command.index('--output-format') + 1] == 'json'
    assert '--verbose' not in command
    assert command[command.index('--tools') + 1] == 'Read,Glob,Grep'
    assert models.response_text('claude', '{"result":"ordinary","total_cost_usd":0.1}') == ('ordinary', .1)


@pytest.mark.parametrize('channel,limit', [('stdout', coverage.MAX_STDOUT), ('stderr', coverage.MAX_STDERR)])
def test_private_pipe_collector_stops_oversize_before_retaining_unbounded_output(monkeypatch, channel, limit):
    class Pipe:
        def __init__(self, number):
            self.number, self.closed = number, False
        def fileno(self):
            return self.number
        def close(self):
            self.closed = True
    class Process:
        def __init__(self):
            self.stdin, self.stdout, self.stderr = Pipe(101), Pipe(102), Pipe(103)
            self.returncode, self.pid = None, 123456
        def poll(self):
            return self.returncode
        def wait(self, timeout=None):
            self.returncode = 0
            return 0
    class Selector:
        def __init__(self):
            self.mapping = {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def register(self, pipe, event):
            self.mapping[pipe] = event
        def unregister(self, pipe):
            self.mapping.pop(pipe)
        def get_map(self):
            return self.mapping
        def select(self, timeout):
            return [(SimpleNamespace(fileobj=next(iter(self.mapping))), 0)]
    process, killed, read_bytes = Process(), [], []
    descriptor = getattr(process, channel).number
    def read(fd, size):
        if fd != descriptor:
            return b''
        read_bytes.append(size)
        return b'x' * size
    with monkeypatch.context() as patch:
        patch.setattr(models.subprocess, 'Popen', lambda *a, **k: process)
        patch.setattr(models.selectors, 'DefaultSelector', Selector)
        patch.setattr(models.os, 'set_blocking', lambda *a: None)
        patch.setattr(models.os, 'write', lambda fd, data: len(data))
        patch.setattr(models.os, 'read', read)
        patch.setattr(models.os, 'killpg', lambda pid, sig: killed.append(pid))
        with pytest.raises(ValueError, match='source_review_transport_failed'):
            models._review_subprocess(['synthetic'], 'prompt', '.', {}, 10)
    assert killed == [process.pid]
    assert sum(read_bytes) <= limit + 4096
    assert all(pipe.closed for pipe in (process.stdin, process.stdout, process.stderr))


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Keep legacy tests' trusted source ROOT without reading its private storage config."""
    source_root = models.ROOT
    project = tmp_path / 'storage-project'
    project.mkdir()
    resolve = storage.resolve_storage

    def isolated(root=None, **kwargs):
        return resolve(project if root is None or root == source_root else root, **kwargs)

    monkeypatch.setattr(storage, 'resolve_storage', isolated)
    monkeypatch.delenv('HARNESS_STORAGE_CONFIG', raising=False)
    monkeypatch.delenv('HARNESS_REPORT_DIR', raising=False)
    return project


@pytest.fixture
def local_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(models, 'KEY_FILE', tmp_path / '.agent-keys.json')
    monkeypatch.setattr(models, 'REPORTS', tmp_path / 'reports')
    for name in models.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    return {'ANTHROPIC_API_KEY': 'test-claude-private', 'ZAI_API_KEY': 'test-zai-private'}


def test_keys_are_private_and_not_interpreted_as_shell(local_keys, monkeypatch):
    models.private_json(models.KEY_FILE, local_keys)
    assert models.KEY_FILE.stat().st_mode & 0o777 == 0o600
    assert models.load_keys() == local_keys
    monkeypatch.setenv('ZAI_API_KEY', '$(this-is-a-literal-key)')
    assert models.load_keys()['ZAI_API_KEY'] == '$(this-is-a-literal-key)'
    assert models.load_keys(include_environment=False) == local_keys
    models.KEY_FILE.chmod(0o644)
    with pytest.raises(ValueError, match='private'):
        models.load_keys()


def test_symlink_key_file_is_rejected(local_keys, tmp_path):
    target = tmp_path / 'target.json'
    models.private_json(target, local_keys)
    models.KEY_FILE.symlink_to(target)
    with pytest.raises(ValueError, match='private'):
        models.load_keys()


def test_configuration_does_not_save_other_environment_keys(local_keys, monkeypatch):
    models.private_json(models.KEY_FILE, {'ANTHROPIC_API_KEY': local_keys['ANTHROPIC_API_KEY']})
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'other-project-key')
    monkeypatch.setattr(models.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(models.getpass, 'getpass', lambda prompt: local_keys['ZAI_API_KEY'])
    models.configure('zai')
    assert models.load_keys(include_environment=False) == local_keys


@pytest.mark.parametrize('provider', ['codex', 'claude', 'zai'])
def test_inherited_credentials_and_provider_switches_are_isolated(provider, local_keys, monkeypatch):
    for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY',
                 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN',
                 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'ZAI_API_KEY',
                 'TYPESAFE_API_KEY', 'GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN',
                 'GITHUB_ENTERPRISE_TOKEN'):
        monkeypatch.setenv(name, 'unrelated-secret-or-setting')
    env = models.child_environment(provider, local_keys)
    assert 'OPENAI_API_KEY' not in env and 'CODEX_API_KEY' not in env
    assert 'CLAUDE_CODE_OAUTH_TOKEN' not in env
    assert 'TYPESAFE_API_KEY' not in env
    assert not {'GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN'} & set(env)
    assert 'CLAUDE_CODE_USE_BEDROCK' not in env and 'CLAUDE_CODE_USE_VERTEX' not in env
    if provider == 'codex':
        assert 'ANTHROPIC_API_KEY' not in env and 'ANTHROPIC_AUTH_TOKEN' not in env
    elif provider == 'claude':
        assert env['ANTHROPIC_API_KEY'] == local_keys['ANTHROPIC_API_KEY']
        assert env['ANTHROPIC_BASE_URL'] == 'https://api.anthropic.com'
        assert 'ANTHROPIC_AUTH_TOKEN' not in env
    else:
        assert env['ANTHROPIC_AUTH_TOKEN'] == local_keys['ZAI_API_KEY']
        assert env['ANTHROPIC_BASE_URL'] == 'https://api.z.ai/api/anthropic'
        assert 'ANTHROPIC_API_KEY' not in env
        assert env['ANTHROPIC_DEFAULT_HAIKU_MODEL'] == 'glm-5.3-flash'


def test_codex_api_login_is_rejected_without_exposing_its_key(local_keys, codex_login, monkeypatch):
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, 'Logged in using API key: secret', ''))
    status = models.connection_status('codex', local_keys)
    assert status['status'] == 'not_configured'
    assert 'secret' not in json.dumps(status)
    command = models.command_for('parser')
    assert 'forced_login_method="chatgpt"' in command
    assert '--sandbox' not in command
    policy = next(value for value in command if value.startswith('permissions.harness-scoped.filesystem='))
    assert json.dumps(str(models.ROOT)) + '="read"' in policy


def test_missing_api_key_prevents_any_model_call(local_keys, monkeypatch):
    monkeypatch.setattr(models.shutil, 'which', lambda cli: '/fake/' + cli)
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw: pytest.fail('Model called without a key'))
    report = models.run('reviewer', 'Review this', {})
    assert report['status'] == 'failed'
    assert 'API key' in report['error']


@pytest.mark.parametrize('role', ['reviewer', 'escalation'])
def test_review_roles_cannot_enable_writes(role):
    with pytest.raises(ValueError, match='read-only'):
        models.command_for(role, write=True)
    command = models.command_for(role, smoke=True)
    assert command[command.index('--tools') + 1] == ''
    assert command[command.index('--max-budget-usd') + 1] == '0.25'


@pytest.mark.parametrize('role, default', [('reviewer', 2), ('escalation', 5)])
@pytest.mark.parametrize('budget', [0.03, 0.20])
def test_budget_override_changes_only_the_claude_cli_cap(role, default, budget, monkeypatch):
    config = models.load_config()
    before = json.dumps(config, sort_keys=True)
    monkeypatch.setattr(models, 'load_config', lambda: config)
    ordinary = models.command_for(role)
    explicit_default = models.command_for(role, max_budget_usd=None)
    limited = models.command_for(role, max_budget_usd=budget)
    position = ordinary.index('--max-budget-usd') + 1
    assert ordinary[position] == str(default)
    assert explicit_default == ordinary
    expected = ordinary[:]
    expected[position] = str(budget)
    assert limited == expected
    assert models.command_for(role, max_budget_usd=default) == ordinary
    assert models.command_for(role) == ordinary
    assert json.dumps(config, sort_keys=True) == before


@pytest.mark.parametrize('budget', [True, False, float('nan'), float('inf'), -float('inf'),
                                   0, -0.0, -0.01, '0.2', [], {}, 10 ** 1000,
                                   2.0000000000000004])
def test_invalid_budget_is_rejected_before_prompt_runtime_or_execution(budget, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid override reached prompt, credentials, storage or CLI')
    monkeypatch.setattr(models, 'task_prompt', forbidden)
    monkeypatch.setattr(models, 'connection_status', forbidden)
    monkeypatch.setattr(models, 'child_environment', forbidden)
    monkeypatch.setattr(models.storage, 'resolve_storage', forbidden)
    monkeypatch.setattr(models.subprocess, 'run', forbidden)
    with pytest.raises(ValueError, match='Budget override'):
        models.command_for('reviewer', max_budget_usd=budget)
    with pytest.raises(ValueError, match='Budget override'):
        models.run('reviewer', 'Review', {}, max_budget_usd=budget)


@pytest.mark.parametrize('provider', ['codex', 'zai', 'typesafe', 'mlx-lm'])
def test_budget_override_cannot_be_silently_ignored_by_another_provider(provider, monkeypatch):
    config = models.load_config()
    config['roles']['reviewer']['provider'] = provider
    monkeypatch.setattr(models, 'load_config', lambda: config)
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw: pytest.fail('Provider called'))
    with pytest.raises(ValueError, match='Claude provider'):
        models.command_for('reviewer', max_budget_usd=0.2)
    with pytest.raises(ValueError, match='Claude provider'):
        models.run('reviewer', 'Review', {}, max_budget_usd=0.2)


@pytest.mark.parametrize('configured', [None, True, '2', 0, -1, float('nan'), float('inf')])
def test_override_requires_a_valid_configured_upper_bound(configured, monkeypatch):
    config = models.load_config()
    config['roles']['reviewer']['max_budget_usd'] = configured
    monkeypatch.setattr(models, 'load_config', lambda: config)
    with pytest.raises(ValueError, match='configured Claude limit'):
        models.command_for('reviewer', max_budget_usd=0.2)


def test_override_preserves_smoke_and_read_only_boundaries(monkeypatch):
    command = models.command_for('reviewer', smoke=True, max_budget_usd=0.20)
    assert command[command.index('--max-budget-usd') + 1] == '0.2'
    assert command[command.index('--tools') + 1] == ''
    with pytest.raises(ValueError, match='increase'):
        models.command_for('reviewer', smoke=True, max_budget_usd=0.30)
    with pytest.raises(ValueError, match='read-only'):
        models.command_for('reviewer', write=True, max_budget_usd=0.20)
    config = models.load_config()
    config['roles']['reviewer']['max_budget_usd'] = 0.10
    monkeypatch.setattr(models, 'load_config', lambda: config)
    with pytest.raises(ValueError, match='increase'):
        models.command_for('reviewer', smoke=True, max_budget_usd=0.20)


@pytest.mark.parametrize('budget, expected', [(0.20, '0.2'), (0.03, '0.03'), (None, '2')])
@pytest.mark.parametrize('outcome', ['success', 'unknown_cost', 'failure', 'timeout'])
def test_run_passes_budget_to_actual_cli_without_retry_or_cost_fabrication(
        budget, expected, outcome, local_keys, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(models.shutil, 'which', lambda cli: '/fake/' + cli)

    def fake_cli(command, **kwargs):
        calls.append(command)
        assert command.count('--max-budget-usd') == 1
        assert command[command.index('--max-budget-usd') + 1] == expected
        assert command[command.index('--model') + 1] == 'claude-sonnet-5-5'
        assert command[command.index('--effort') + 1] == 'medium'
        assert '--restricted' in command
        assert command[command.index('--tools') + 1] == 'Read,Glob,Grep'
        assert kwargs['cwd'] == str(tmp_path)
        assert kwargs['timeout'] == 17
        assert kwargs['env']['ANTHROPIC_API_KEY'] == local_keys['ANTHROPIC_API_KEY']
        assert kwargs['env']['ANTHROPIC_BASE_URL'] == 'https://api.anthropic.com'
        assert kwargs['env']['TAVERN_WORKFLOW_CHILD'] == '1'
        assert 'ANTHROPIC_AUTH_TOKEN' not in kwargs['env']
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired(command, 17)
        if outcome == 'failure':
            return subprocess.CompletedProcess(command, 1, '', '')
        body = {'is_error': False, 'result': 'Reviewed'}
        if outcome == 'success':
            # The CLI estimate can exceed admission: retain it without clamping.
            body['total_cost_usd'] = 0.26
        return subprocess.CompletedProcess(command, 0, json.dumps(body), '')

    monkeypatch.setattr(models.subprocess, 'run', fake_cli)
    result = models.run('reviewer', 'Review approved files', local_keys, timeout=17,
                        compaction=False, workspace=tmp_path, scoped=True, max_budget_usd=budget)
    assert len(calls) == 1
    assert result['status'] == ('passed' if outcome in ('success', 'unknown_cost') else 'failed')
    if outcome == 'success':
        assert result['cli_estimated_cost_usd'] == 0.26
    else:
        assert 'cli_estimated_cost_usd' not in result
    assert all(key not in json.dumps(result) for key in local_keys.values())


def test_valid_override_does_not_bypass_storage_readiness(local_keys, tmp_path, monkeypatch):
    class UnavailableStorage:
        def check_ready(self):
            raise storage.StorageError('Storage unavailable.')

    monkeypatch.setattr(models.storage, 'resolve_storage', lambda *a, **kw: UnavailableStorage())
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw: pytest.fail('Storage gate bypassed'))
    result = models.run('reviewer', 'Review', local_keys, compaction=False,
                        workspace=tmp_path, scoped=True, max_budget_usd=0.20)
    assert result['status'] == 'failed'
    assert result['diagnostic'] == {'stage': 'storage', 'category': 'storage_unavailable'}
    assert 'cli_estimated_cost_usd' not in result


def test_git_role_uses_medium_codex_and_cannot_write():
    command = models.command_for('git')
    assert command[command.index('--model') + 1] == 'gpt-6.1-sol'
    assert 'model_reasoning_effort="medium"' in command
    with pytest.raises(ValueError, match='read-only'):
        models.command_for('git', write=True)


@pytest.mark.parametrize('output', [
    '{"is_error": true, "result": "invalid key"}',
    '{"is_error": false, "subtype": "error_max_budget_usd", "result": "budget exhausted"}',
    '{"is_error": false, "result": ""}',
    'not-json',
])
def test_zero_exit_is_not_enough_for_a_successful_model_run(output, local_keys, monkeypatch):
    monkeypatch.setattr(models.shutil, 'which', lambda cli: '/fake/' + cli)
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, output, ''))
    assert models.run('reviewer', 'Review', local_keys)['status'] == 'failed'


def test_cli_failures_redact_registered_credentials(local_keys, monkeypatch):
    monkeypatch.setattr(models.shutil, 'which', lambda cli: '/fake/' + cli)
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 1, local_keys['ZAI_API_KEY'],
                                                    local_keys['ANTHROPIC_API_KEY']))
    report = models.run('downloader', 'Read downloader code', local_keys)
    assert report['status'] == 'failed'
    assert all(key not in json.dumps(report) for key in local_keys.values())


def test_real_cli_protocol_is_used_for_a_smoke(local_keys, monkeypatch):
    monkeypatch.setattr(models.shutil, 'which', lambda cli: '/fake/' + cli)
    def fake_cli(command, **kwargs):
        assert kwargs['env']['ANTHROPIC_AUTH_TOKEN'] == local_keys['ZAI_API_KEY']
        assert command[command.index('--tools') + 1] == ''
        nonce = kwargs['input'].split('exactly ')[1].split('.')[0]
        return subprocess.CompletedProcess(command, 0, json.dumps({'is_error': False, 'result': nonce}), '')
    monkeypatch.setattr(models.subprocess, 'run', fake_cli)
    assert models.run('downloader', '', local_keys, smoke=True)['status'] == 'passed'


def test_codex_incomplete_or_failed_events_do_not_pass():
    message = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'ok'}}
    for tail in ({'type': 'turn.failed'}, {'type': 'error'}, {'type': 'thread.started'}):
        with pytest.raises(ValueError):
            models.response_text('codex', json.dumps(message) + '\n' + json.dumps(tail))
    assert models.response_text('codex', json.dumps(message) + '\n' +
                                '{"type":"turn.completed"}') == ('ok', None)


def test_zai_claude_cli_estimate_is_not_reported_as_dollar_spend():
    output = '{"is_error":false,"result":"ok","total_cost_usd":15}'
    assert models.response_text('zai', output) == ('ok', None)
    assert models.response_text('claude', output) == ('ok', 15)


def test_smoke_rejects_a_successful_unrelated_response(local_keys, monkeypatch):
    monkeypatch.setattr(models.shutil, 'which', lambda cli: '/fake/' + cli)
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, '{"is_error":false,"result":"other"}', ''))
    report = models.run('reviewer', '', local_keys, smoke=True)
    assert report['status'] == 'failed'
    assert 'probe' in report['error']


def test_doctor_and_dry_run_never_make_inference_requests(local_keys, monkeypatch, capsys):
    models.private_json(models.KEY_FILE, local_keys)
    monkeypatch.setattr(models.shutil, 'which', lambda cli: '/fake/' + cli)
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw: pytest.fail('Unexpected CLI request'))
    assert models.main(['doctor', '--provider', 'zai']) == 0
    assert models.main(['run', '--role', 'reviewer', '--dry-run']) == 0
    output = capsys.readouterr().out
    assert all(key not in output for key in local_keys.values())


def test_private_key_file_is_ignored_by_git():
    result = subprocess.run(['git', 'check-ignore', '--no-index', '.agent-keys.json'],
                            cwd=str(models.ROOT), capture_output=True, text=True)
    assert result.returncode == 0


def test_typesafe_configuration_preserves_existing_provider_keys(local_keys, monkeypatch):
    models.private_json(models.KEY_FILE, local_keys)
    monkeypatch.setattr(models.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(models.getpass, 'getpass', lambda prompt: 'test-typesafe-private')
    assert models.main(['configure', '--provider', 'typesafe']) == 0
    assert models.load_keys(include_environment=False) == dict(local_keys, TYPESAFE_API_KEY='test-typesafe-private')
    assert models.KEY_FILE.stat().st_mode & 0o777 == 0o600


def test_typesafe_doctor_is_local_and_does_not_launch_a_cli(local_keys, monkeypatch, capsys):
    models.private_json(models.KEY_FILE, local_keys)
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw: pytest.fail('Doctor called a CLI'))
    assert models.main(['doctor', '--provider', 'typesafe']) == 1
    assert 'not_configured' in capsys.readouterr().out
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-typesafe-private')
    assert models.main(['doctor', '--provider', 'typesafe']) == 0
    assert 'test-typesafe-private' not in capsys.readouterr().out


def test_typesafe_cannot_be_used_as_a_chat_cli_smoke(local_keys, monkeypatch, capsys):
    monkeypatch.setattr(models, 'run', lambda *a, **kw: pytest.fail('TypeSafe was used as a CLI model'))
    with pytest.raises(SystemExit) as error:
        models.main(['smoke', '--provider', 'typesafe'])
    assert error.value.code == 2
    assert 'harness.triage' in capsys.readouterr().err


@pytest.mark.parametrize('write', [False, True])
def test_scoped_codex_limits_reads_and_never_overrides_profile_with_legacy_sandbox(tmp_path, write):
    workspace = tmp_path / 'sources'
    workspace.mkdir()
    (workspace / 'approved.py').write_text('user_edit = True\n', encoding='utf-8')
    auth_home = tmp_path / 'original-codex-home'
    # Standalone binaries may live inside the original authentication home.
    cli = auth_home / 'packages' / 'release' / 'bin' / 'codex'
    shell = auth_home / 'packages' / 'release' / 'codex-resources' / 'zsh' / 'bin' / 'zsh'
    runtime = workspace / 'private-runtime'
    command = models.command_for('parser', workspace=workspace, write=write, scoped=True,
                                 codex_cli=str(cli), codex_shell=str(shell),
                                 runtime_root=runtime, auth_home=auth_home)
    assert not (workspace / '.git').exists()
    assert command.count('--skip-git-repo-check') == 1
    assert command[command.index('exec') + 1] == '--skip-git-repo-check'
    assert command[command.index('--cd') + 1] == str(workspace)
    assert '--strict-config' in command
    assert '--sandbox' not in command
    assert 'default_permissions="harness-scoped"' in command
    policy = next(value for value in command if value.startswith('permissions.harness-scoped.filesystem='))
    assert '":root"="deny"' in policy
    assert '":minimal"="read"' in policy
    assert '":tmpdir"="write"' not in policy and '":slash_tmp"="write"' not in policy
    assert json.dumps(str(workspace)) + '=' + json.dumps('write' if write else 'read') in policy
    assert json.dumps(str(runtime)) + '="deny"' in policy
    assert json.dumps(str(cli)) + '="read"' in policy
    assert json.dumps(str(shell)) + '="read"' in policy
    # A directory deny here masks the executable exceptions on Linux. Root deny
    # protects everything else; do not grant a containing directory either.
    for directory in (auth_home, cli.parent, shell.parent, tmp_path):
        assert json.dumps(str(directory)) + '=' not in policy
    assert policy.count('="read"') == (3 if write else 4)
    assert policy.count('="write"') == (1 if write else 0)
    assert policy.count('="deny"') == 2
    assert 'permissions.harness-scoped.network.enabled=false' in command
    assert 'web_search="disabled"' in command
    assert 'project_doc_max_bytes=0' in command
    assert 'features.skip_host_skill_discovery=true' in command


@pytest.mark.parametrize('write', [False, True])
@pytest.mark.parametrize('layout', ['same', 'ancestor', 'workspace_alias', 'auth_alias', 'dotdot'])
def test_codex_rejects_resolved_workspaces_containing_original_auth_home(tmp_path, write, layout):
    auth_home = tmp_path / 'original-codex-home'
    auth_home.mkdir()
    workspace = auth_home if layout == 'same' else tmp_path
    if layout == 'workspace_alias':
        workspace = tmp_path / 'sources-alias'
        workspace.symlink_to(auth_home, target_is_directory=True)
    elif layout == 'auth_alias':
        alias = tmp_path / 'auth-alias'
        alias.symlink_to(auth_home, target_is_directory=True)
        auth_home = alias
        workspace = tmp_path / 'original-codex-home'
    elif layout == 'dotdot':
        child = auth_home / 'child'
        child.mkdir()
        workspace = child / '..'
    with pytest.raises(models.CodexFailure) as error:
        models.command_for('parser', workspace=workspace, write=write, scoped=True,
                           codex_cli=str(auth_home / 'bin' / 'codex'), auth_home=auth_home)
    assert error.value.diagnostic == {'stage': 'runtime', 'category': 'unsafe_workspace'}
    assert str(auth_home) not in str(error.value)


@pytest.mark.parametrize('layout', ['same', 'ancestor', 'alias'])
def test_unsafe_codex_workspace_never_reaches_model_execution(codex_login, local_keys, tmp_path,
                                                            monkeypatch, layout):
    workspace = codex_login['source'] if layout == 'same' else tmp_path
    if layout == 'alias':
        workspace = tmp_path / 'source-alias'
        workspace.symlink_to(codex_login['source'], target_is_directory=True)
    roots = []
    def cli(command, **options):
        assert 'login' in command, 'Unsafe workspace reached model execution'
        roots.append(inspect_codex_runtime(command, options, codex_login))
        return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('parser', 'Read approved sources.', local_keys, workspace=workspace, scoped=True)
    assert report['status'] == 'failed'
    assert report['diagnostic'] == {'stage': 'runtime', 'category': 'unsafe_workspace'}
    assert 'response' not in report and 'stderr' not in report
    assert len(roots) == 1 and not roots[0].exists()
    assert 'fixture-access-secret' not in json.dumps(report)
    assert_codex_source_unchanged(codex_login)


@pytest.mark.parametrize('role', ['downloader', 'reviewer'])
def test_scoped_claude_confines_tools_and_keeps_hook_runtime_outside_context(tmp_path, role):
    command = models.command_for(role, workspace=tmp_path, scoped=True)
    assert '--restricted' in command
    assert command[command.index('--plugin-dir') + 1] == str(models.ROOT / 'harness/compaction')
    assert str(tmp_path / 'harness/compaction') not in command
    assert command[command.index('--tools') + 1] == 'Read,Glob,Grep'
    assert '--add-dir' not in command


def test_scoped_prompt_does_not_read_unapproved_instructions(tmp_path, monkeypatch):
    monkeypatch.setattr(models.Path, 'read_text', lambda *args, **kwargs: pytest.fail('Read extra instructions'))
    # load_config needs its trusted runner configuration, which is not project context.
    monkeypatch.setattr(models, 'load_config', lambda: {'roles': {'parser': {}}})
    prompt = models.task_prompt('parser', 'Review approved sources.', workspace=tmp_path, scoped=True)
    assert 'Review approved sources.' in prompt and 'orchestrator owns validation' in prompt
    assert 'Read docs/architecture.md' not in prompt


def test_scoped_run_disables_inherited_memories_and_session_policy(local_keys, tmp_path, monkeypatch):
    monkeypatch.setenv('CODEX_PERMISSION_PROFILE', 'unrelated-host-policy')
    monkeypatch.setattr(models, 'connection_status', lambda *args: {'status': 'ready'})
    def cli(command, **options):
        assert '--restricted' in command
        assert 'CODEX_PERMISSION_PROFILE' not in options['env']
        assert options['env']['CLAUDE_CODE_DISABLE_CLAUDE_MDS'] == '1'
        assert options['env']['CLAUDE_CODE_DISABLE_AUTO_MEMORY'] == '1'
        assert 'TAVERN_WORKFLOW_CHILD' in options['env']
        assert 'Instructions.' not in options['input']
        return subprocess.CompletedProcess(command, 0, '{"result":"Scoped review done."}', '')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('reviewer', 'Review.', local_keys, workspace=tmp_path, scoped=True)
    assert report['status'] == 'passed'


@pytest.fixture
def codex_login(tmp_path, monkeypatch):
    """A read-only login and standalone executable tree; never use host credentials."""
    source = tmp_path / 'existing-codex-home'
    source.mkdir(mode=0o700)
    files = {
        'auth.json': json.dumps({'auth_mode': 'chatgpt', 'tokens': {
            'access_token': 'fixture-access-secret', 'refresh_token': 'fixture-refresh-secret'}}),
        'config.toml': 'model = "user-model"\n',
        'AGENTS.md': 'Private user instructions must not be loaded.',
        'other-auth.json': '{"secret":"other-credential-secret"}',
    }
    for name, content in files.items():
        (source / name).write_text(content, encoding='utf-8')
        (source / name).chmod(0o400)
    source.chmod(0o500)
    cli = tmp_path / 'release' / 'bin' / 'codex'
    shell = tmp_path / 'release' / 'codex-resources' / 'zsh' / 'bin' / 'zsh'
    for executable in (cli, shell):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text('#!/bin/sh\n', encoding='utf-8')
        executable.chmod(0o700)
    launcher = tmp_path / 'codex-launcher'
    launcher.symlink_to(cli)
    base = tmp_path / 'runtime-base'
    base.mkdir(mode=0o700)
    # Execution tests need a source-only sibling, not the parent containing the
    # original login. The latter is intentionally rejected as unsafe_workspace.
    workspace = tmp_path / 'approved-sources'
    workspace.mkdir()
    (workspace / 'approved.py').write_text('user_edit = True\n', encoding='utf-8')
    # Do not let tempfile selection or inherited login locations reach the host.
    monkeypatch.setattr(models.tempfile, 'tempdir', str(base))
    monkeypatch.setattr(storage.Storage, 'credential_temp_root', property(lambda self: base))
    monkeypatch.setenv('CODEX_HOME', str(source))
    monkeypatch.setenv('TMPDIR', str(source))
    monkeypatch.setenv('TMP', str(source))
    monkeypatch.setenv('TEMP', str(source))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(source))
    monkeypatch.setenv('XDG_CACHE_HOME', str(source))
    monkeypatch.setenv('XDG_DATA_HOME', str(source))
    monkeypatch.setenv('XDG_STATE_HOME', str(source))
    monkeypatch.setenv('SHELL', '/unavailable/host/shell')
    monkeypatch.setenv('CODEX_PERMISSION_PROFILE', 'host-policy')
    monkeypatch.setenv('OPENAI_API_KEY', 'inherited-openai-secret')
    monkeypatch.setenv('CODEX_API_KEY', 'inherited-codex-secret')
    monkeypatch.setattr(models.shutil, 'which', lambda name: str(launcher) if name == 'codex' else None)
    monkeypatch.setattr(models, 'load_config', lambda: {
        'providers': {'codex': {'cli': 'codex'}},
        'roles': {role: {'provider': 'codex', 'model': 'fixture-model', 'effort': 'high'}
                  for role in ('parser', 'coordinator')},
    })
    return {'source': source, 'files': files, 'cli': cli, 'shell': shell, 'base': base,
            'workspace': workspace}


def assert_codex_source_unchanged(fixture):
    assert fixture['source'].stat().st_mode & 0o777 == 0o500
    assert {path.name for path in fixture['source'].iterdir()} == set(fixture['files'])
    for name, content in fixture['files'].items():
        path = fixture['source'] / name
        assert path.read_text(encoding='utf-8') == content
        assert path.stat().st_mode & 0o777 == 0o400


def inspect_codex_runtime(command, options, fixture):
    env = options['env']
    home = Path(env['CODEX_HOME'])
    root = home.parent
    assert command[0] == str(fixture['cli'])
    assert env['SHELL'] == str(fixture['shell'])
    assert root.parent == fixture['base']
    assert root.stat().st_mode & 0o777 == 0o700
    assert home.stat().st_mode & 0o777 == 0o700
    assert (home / 'auth.json').stat().st_mode & 0o777 == 0o600
    assert not (home / 'auth.json').samefile(fixture['source'] / 'auth.json')
    assert env.get('HOME') == os.environ.get('HOME')
    assert env['TMP'] == env['TEMP'] == env['TMPDIR']
    for name in ('TMPDIR', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME'):
        path = Path(env[name])
        assert path.parent == root
        assert path.stat().st_mode & 0o777 == 0o700
    assert 'CODEX_PERMISSION_PROFILE' not in env
    assert 'OPENAI_API_KEY' not in env and 'CODEX_API_KEY' not in env
    assert 'forced_login_method="chatgpt"' in command
    assert 'cli_auth_credentials_store="file"' in command
    if 'login' in command:
        assert command[-2:] == ['login', 'status']
        assert {path.name for path in home.iterdir()} == {'auth.json'}
        assert (home / 'auth.json').read_text() == fixture['files']['auth.json']
    else:
        assert '--strict-config' in command and '--ignore-user-config' in command
        # The isolated runtime has no host trust records and this fixture has no
        # Git metadata, just like the workflow's approved-source context.
        assert command.count('--skip-git-repo-check') == 1
        assert command[command.index('--cd') + 1] == options['cwd']
        assert '--ephemeral' in command and '--sandbox' not in command
        policy = next(value for value in command if value.startswith('permissions.harness-scoped.filesystem='))
        assert json.dumps(str(root)) + '="deny"' in policy
        assert json.dumps(str(fixture['cli'])) + '="read"' in policy
        assert json.dumps(str(fixture['shell'])) + '="read"' in policy
        assert json.dumps(str(fixture['source'])) + '="deny"' not in policy
        assert json.dumps(str(fixture['source'])) + '="read"' not in policy
        assert json.dumps(str(fixture['source'])) + '="write"' not in policy
        assert json.dumps(str(fixture['base'])) + '="read"' not in policy
        assert json.dumps(str(fixture['base'])) + '="write"' not in policy
        assert json.dumps(str(fixture['cli'].parent)) + '="read"' not in policy
        assert 'permissions.harness-scoped.network.enabled=false' in command
        assert 'project_doc_max_bytes=0' in command
        assert 'features.skip_host_skill_discovery=true' in command
        assert 'features.plugins=false' in command and 'agents.enabled=false' in command
        assert options['env']['TAVERN_WORKFLOW_CHILD'] == '1'
    return root


def codex_completed(command, response='Approved sources updated.', stderr=''):
    output = '\n'.join(json.dumps(event) for event in (
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': response}},
        {'type': 'turn.completed'},
    ))
    return subprocess.CompletedProcess(command, 0, output, stderr)


@pytest.mark.parametrize('warning', [False, True])
@pytest.mark.parametrize('status_stream', ['stdout', 'stderr'])
def test_codex_doctor_is_private_local_and_cleans_up(codex_login, local_keys, monkeypatch, capsys,
                                                   warning, status_stream):
    parent_env = dict(os.environ)
    roots = []
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        assert 'login' in command and 'input' not in options
        assert options['timeout'] == 20
        status = 'Logged in using ChatGPT'
        stderr = (PATH_ALIASES_WARNING + '\n' if warning else '') + 'fixture-access-secret'
        return subprocess.CompletedProcess(command, 0, status if status_stream == 'stdout' else '',
                                           stderr + ('\n' + status if status_stream == 'stderr' else ''))
    monkeypatch.setattr(models.subprocess, 'run', cli)
    assert models.main(['doctor', '--provider', 'codex']) == 0
    assert len(roots) == 1 and not roots[0].exists()
    output = capsys.readouterr().out
    assert 'fixture-access-secret' not in output
    assert 'chatgpt' in output
    report = json.loads((models.REPORTS / 'doctor-codex.json').read_text(encoding='utf-8'))
    assert report['checks'][0]['warnings'] == ([{'stage': 'authentication',
                                              'category': 'path_aliases_read_only'}] if warning else [])
    assert PATH_ALIASES_WARNING not in output and PATH_ALIASES_WARNING not in json.dumps(report)
    assert 'fixture-access-secret' not in json.dumps(report)
    assert report['checks'][0]['status'] == 'ready'
    assert os.environ == parent_env
    assert_codex_source_unchanged(codex_login)


@pytest.mark.parametrize('write', [False, True])
def test_codex_scoped_login_and_execution_share_runtime(codex_login, local_keys, tmp_path, monkeypatch, write):
    workspace = tmp_path / 'approved'
    workspace.mkdir()
    (workspace / 'approved.py').write_text('user_edit = True\n')
    parent_env = dict(os.environ)
    roots = []
    def cli(command, **options):
        root = inspect_codex_runtime(command, options, codex_login)
        roots.append(root)
        if 'login' in command:
            # Simulate a CLI credential refresh, which must remain in the private copy.
            (Path(options['env']['CODEX_HOME']) / 'auth.json').write_text('private-refreshed-auth')
            (Path(options['env']['TMPDIR']) / 'path-alias').write_text('private-runtime-write')
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT',
                                               PATH_ALIASES_WARNING + ' fixture-access-secret')
        assert (Path(options['env']['CODEX_HOME']) / 'auth.json').read_text() == 'private-refreshed-auth'
        assert 'private user instructions' not in options['input'].lower()
        assert options['cwd'] == str(workspace)
        policy = next(value for value in command if value.startswith('permissions.harness-scoped.filesystem='))
        assert json.dumps(str(workspace)) + '=' + json.dumps('write' if write else 'read') in policy
        assert '":root"="deny"' in policy and '":minimal"="read"' in policy
        return codex_completed(command, stderr=PATH_ALIASES_WARNING +
                               ' remote-warning fixture-refresh-secret')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('parser', 'Use approved sources.', local_keys, write=write,
                        workspace=workspace, scoped=True)
    assert report['status'] == 'passed'
    assert report['warnings'] == [{'stage': stage, 'category': 'path_aliases_read_only'}
                                   for stage in ('authentication', 'execution')]
    assert all(value not in json.dumps(report) for value in (
        PATH_ALIASES_WARNING, 'fixture-access-secret', 'fixture-refresh-secret'))
    assert 'stderr' not in report and 'remote-warning' not in json.dumps(report)
    assert len(roots) == 2 and roots[0] == roots[1] and not roots[0].exists()
    assert os.environ == parent_env
    assert (workspace / 'approved.py').read_text() == 'user_edit = True\n'
    assert_codex_source_unchanged(codex_login)


def test_codex_doctor_smoke_and_direct_runs_have_separate_runtimes(codex_login, local_keys, monkeypatch):
    workspace = codex_login['workspace']
    assert not (workspace / '.git').exists()
    roots = []
    def cli(command, **options):
        root = inspect_codex_runtime(command, options, codex_login)
        if 'login' in command:
            assert all(not previous.exists() for previous in roots)
            roots.append(root)
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
        assert root == roots[-1]
        nonce = options['input'].split('exactly ')[1].split('.')[0]
        return codex_completed(command, nonce)
    monkeypatch.setattr(models.subprocess, 'run', cli)
    assert models.connection_status('codex', local_keys)['status'] == 'ready'
    assert models.run('coordinator', '', local_keys, smoke=True)['status'] == 'passed'
    assert models.run('parser', '', local_keys, smoke=True, workspace=workspace, scoped=True)['status'] == 'passed'
    assert len(set(roots)) == 3 and all(not root.exists() for root in roots)
    assert_codex_source_unchanged(codex_login)


@pytest.mark.parametrize('stage', ['authentication', 'execution'])
@pytest.mark.parametrize('failure,category', [
    ('aliases', 'path_aliases_read_only'), ('auth', 'authentication_failed'),
    ('timeout', 'timeout'), ('spawn', 'cli_failed'), ('unknown_profile', 'cli_failed'),
])
def test_codex_failures_are_safe_cleaned_and_never_retried(codex_login, local_keys,
                                                         monkeypatch, stage, failure, category):
    roots = []
    commands = []
    sensitive = 'fixture-access-secret fixture-refresh-secret unregistered-remote-body'
    def cli(command, **options):
        commands.append(command)
        roots.append(inspect_codex_runtime(command, options, codex_login))
        current = 'authentication' if 'login' in command else 'execution'
        if current != stage:
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, options['timeout'], output=sensitive,
                                            stderr=PATH_ALIASES_WARNING + ' ' + sensitive)
        if failure == 'spawn':
            raise OSError(sensitive)
        message = {'aliases': 'PATH aliases: Read-only file system (os error 30)',
                   'auth': 'Authentication failed: unauthorized 401',
                   'unknown_profile': 'unknown variant harness-scoped'}[failure]
        return subprocess.CompletedProcess(command, 1, sensitive, message + ' ' + sensitive)
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('parser', 'Read only approved.', local_keys, timeout=7,
                        workspace=codex_login['workspace'], scoped=True)
    assert report['status'] == 'failed'
    assert report['diagnostic'] == {'stage': stage, 'category': category}
    assert len(commands) == (1 if stage == 'authentication' else 2)
    assert all(not root.exists() for root in roots)
    assert all(value not in json.dumps(report) for value in sensitive.split())
    assert 'stderr' not in report and 'response' not in report
    if stage == 'execution':
        assert '--sandbox' not in commands[-1]
        assert 'permissions.harness-scoped.network.enabled=false' in commands[-1]
    assert_codex_source_unchanged(codex_login)


@pytest.mark.parametrize('warning', [False, True])
@pytest.mark.parametrize('failure,category', [
    ('api', 'authentication_failed'), ('missing', 'authentication_failed'),
    ('failed', 'authentication_failed'), ('ambiguous', 'authentication_failed'),
    ('prefix', 'authentication_failed'), ('timeout', 'timeout'),
])
def test_codex_doctor_failure_diagnostics_are_structured(codex_login, local_keys, monkeypatch, capsys,
                                                        failure, category, warning):
    roots = []
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 20, output='fixture-access-secret',
                                            stderr=PATH_ALIASES_WARNING if warning else '')
        statuses = {
            'api': 'Logged in using API key: fixture-access-secret',
            'missing': '',
            'failed': 'Not logged in: fixture-access-secret',
            'ambiguous': 'Logged in using ChatGPT\nLogged in using API key: fixture-access-secret',
            'prefix': 'Logged in using ChatGPT but not a valid status: fixture-access-secret',
        }
        return subprocess.CompletedProcess(command, 0, statuses[failure],
                                           (PATH_ALIASES_WARNING + '\n' if warning else '') +
                                           'fixture-refresh-secret')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    assert models.main(['doctor', '--provider', 'codex']) == 1
    output = capsys.readouterr().out
    assert category in output and 'fixture-access-secret' not in output
    report = json.loads((models.REPORTS / 'doctor-codex.json').read_text(encoding='utf-8'))
    assert report['checks'][0]['status'] == 'not_configured'
    assert report['checks'][0]['diagnostic'] == {'stage': 'authentication', 'category': category}
    assert all(value not in json.dumps(report) for value in (
        PATH_ALIASES_WARNING, 'fixture-access-secret', 'fixture-refresh-secret'))
    assert len(roots) == 1 and not roots[0].exists()
    assert_codex_source_unchanged(codex_login)


@pytest.mark.parametrize('invalid_auth', ['missing', 'symlink', 'directory', 'fifo', 'empty'])
def test_codex_auth_copy_rejects_unsafe_sources_without_fallback(codex_login, local_keys, monkeypatch,
                                                              invalid_auth):
    source = codex_login['source']
    source.chmod(0o700)
    auth = source / 'auth.json'
    auth.unlink()
    if invalid_auth == 'symlink':
        auth.symlink_to(source / 'other-auth.json')
    elif invalid_auth == 'directory':
        auth.mkdir()
    elif invalid_auth == 'fifo':
        os.mkfifo(auth)
    elif invalid_auth == 'empty':
        auth.touch(mode=0o400)
    source.chmod(0o500)
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw: pytest.fail('Unsafe auth used by CLI'))
    status = models.connection_status('codex', local_keys)
    assert status['status'] == 'not_configured'
    assert status['diagnostic'] == {'stage': 'authentication', 'category': 'auth_file_unavailable'}
    report = models.run('coordinator', '', local_keys, smoke=True)
    assert report['status'] == 'failed' and report['diagnostic'] == status['diagnostic']
    assert list(codex_login['base'].iterdir()) == []
    assert (source / 'other-auth.json').read_text() == codex_login['files']['other-auth.json']


def test_codex_runtime_creation_failure_does_not_use_real_home(codex_login, local_keys, monkeypatch):
    def unavailable(*args, **kwargs):
        raise PermissionError('private-path fixture-access-secret')
    monkeypatch.setattr(models.tempfile, 'TemporaryDirectory', unavailable)
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw: pytest.fail('Fell back to host runtime'))
    status = models.connection_status('codex', local_keys)
    assert status['diagnostic'] == {'stage': 'runtime', 'category': 'runtime_unavailable'}
    assert 'fixture-access-secret' not in json.dumps(status)
    assert_codex_source_unchanged(codex_login)


@pytest.mark.parametrize('warning', [False, True])
@pytest.mark.parametrize('output', [
    '', '   \n', 'remote body fixture-access-secret', 'null', '[]',
    '{"type":"item.completed","item":"fixture-access-secret"}',
    '{"type":"item.completed","item":{"type":"agent_message","text":5}}\n'
    '{"type":"turn.completed"}',
    '{"type":"item.completed","item":{"type":"agent_message","text":" "}}\n'
    '{"type":"turn.completed"}',
    '{"type":"item.completed","item":{"type":"agent_message","text":"fixture-access-secret"}}',
    '{"type":"turn.completed"}',
    '{"type":"item.completed","item":{"type":"agent_message","text":"fixture-access-secret"}}\n'
    '{"type":"turn.completed"}\nnot-json',
    *('\n'.join(json.dumps(event) for event in (
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'fixture-access-secret'}},
        {'type': 'turn.completed'}, {'type': failure, 'message': 'fixture-refresh-secret'},
    )) for failure in ('turn.failed', 'error')),
])
def test_codex_invalid_responses_never_become_diagnostics(codex_login, local_keys, monkeypatch,
                                                         output, warning):
    roots = []
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        stderr = (PATH_ALIASES_WARNING + '\n' if warning else '') + 'fixture-refresh-secret'
        return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT' if 'login' in command
                                           else output, stderr)
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('parser', 'Task.', local_keys, workspace=codex_login['workspace'], scoped=True)
    assert report['status'] == 'failed'
    assert report['diagnostic'] == {'stage': 'execution', 'category': 'invalid_response'}
    assert report['warnings'] == ([{'stage': stage, 'category': 'path_aliases_read_only'}
                                   for stage in ('authentication', 'execution')] if warning else [])
    assert all(value not in json.dumps(report) for value in (
        PATH_ALIASES_WARNING, 'fixture-access-secret', 'fixture-refresh-secret'))
    assert 'response' not in report and 'stdout' not in report and 'stderr' not in report
    assert len(roots) == 2 and all(not root.exists() for root in roots)
    assert_codex_source_unchanged(codex_login)


@pytest.mark.parametrize('warning', [False, True])
def test_codex_smoke_mismatch_does_not_save_untrusted_response(codex_login, local_keys, monkeypatch,
                                                             warning):
    roots = []
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        stderr = (PATH_ALIASES_WARNING + '\n' if warning else '') + 'fixture-refresh-secret'
        if 'login' in command:
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', stderr)
        return codex_completed(command, 'remote fixture-access-secret', stderr)
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('coordinator', '', local_keys, smoke=True)
    assert report['status'] == 'failed'
    assert report['diagnostic'] == {'stage': 'execution', 'category': 'probe_mismatch'}
    assert all(value not in json.dumps(report) for value in (
        PATH_ALIASES_WARNING, 'fixture-access-secret', 'fixture-refresh-secret'))
    assert 'response' not in report and 'stdout' not in report and 'stderr' not in report
    assert len(roots) == 2 and all(not root.exists() for root in roots)
    assert_codex_source_unchanged(codex_login)


def test_codex_auth_defaults_to_existing_home_without_changing_parent(codex_login, local_keys,
                                                                   tmp_path, monkeypatch):
    home = tmp_path / 'user-home'
    home.mkdir()
    (home / '.codex').symlink_to(codex_login['source'], target_is_directory=True)
    monkeypatch.delenv('CODEX_HOME')
    monkeypatch.setenv('HOME', str(home))
    roots = []
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        assert options['env']['HOME'] == str(home)
        return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    assert models.connection_status('codex', local_keys)['status'] == 'ready'
    assert 'CODEX_HOME' not in os.environ and os.environ['HOME'] == str(home)
    assert all(not root.exists() for root in roots)
    assert_codex_source_unchanged(codex_login)


def test_overlapping_codex_calls_do_not_share_auth_or_temp_paths(codex_login, local_keys):
    parent_env = dict(os.environ)
    with models.codex_runtime(local_keys, 'codex') as first:
        first_auth = Path(first['env']['CODEX_HOME']) / 'auth.json'
        first_auth.write_text('first-call-only')
        with models.codex_runtime(local_keys, 'codex') as second:
            assert first['root'] != second['root']
            assert first['env']['TMPDIR'] != second['env']['TMPDIR']
            assert (Path(second['env']['CODEX_HOME']) / 'auth.json').read_text() == codex_login['files']['auth.json']
        assert not second['root'].exists() and first['root'].exists()
        assert first_auth.read_text() == 'first-call-only'
    assert not first['root'].exists()
    assert os.environ == parent_env
    assert_codex_source_unchanged(codex_login)


@pytest.mark.parametrize('warning', [False, True])
@pytest.mark.parametrize('doctor', [False, True])
def test_codex_cleanup_failure_is_never_reported_as_ready(codex_login, local_keys, monkeypatch, doctor,
                                                         warning):
    real_directory = models.tempfile.TemporaryDirectory
    class CleanupFailure(real_directory):
        def __exit__(self, *args):
            super().__exit__(*args)
            raise PermissionError('fixture-access-secret')
    monkeypatch.setattr(models.tempfile, 'TemporaryDirectory', CleanupFailure)
    def cli(command, **options):
        inspect_codex_runtime(command, options, codex_login)
        stderr = PATH_ALIASES_WARNING + ' fixture-refresh-secret' if warning else ''
        if 'login' in command:
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', stderr)
        nonce = options['input'].split('exactly ')[1].split('.')[0]
        return codex_completed(command, nonce, stderr)
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = (models.connection_status('codex', local_keys) if doctor else
              models.run('coordinator', '', local_keys, smoke=True))
    assert report['status'] == ('not_configured' if doctor else 'failed')
    assert report['diagnostic'] == {'stage': 'runtime', 'category': 'runtime_unavailable'}
    assert 'response' not in report
    assert all(value not in json.dumps(report) for value in (
        PATH_ALIASES_WARNING, 'fixture-access-secret', 'fixture-refresh-secret'))
    assert list(codex_login['base'].iterdir()) == []


@pytest.mark.parametrize('authentication_warning,execution_warning', [
    (False, False), (True, False), (False, True), (True, True),
])
@pytest.mark.parametrize('smoke', [False, True])
def test_codex_valid_completed_turn_preserves_warnings(codex_login, local_keys, monkeypatch,
                                                      authentication_warning, execution_warning, smoke):
    roots = []
    parent_env = dict(os.environ)
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        if 'login' in command:
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT',
                                               PATH_ALIASES_WARNING + ' fixture-access-secret'
                                               if authentication_warning else '')
        response = (options['input'].split('exactly ')[1].split('.')[0] if smoke else
                    'Approved sources updated.')
        return codex_completed(command, response, PATH_ALIASES_WARNING + ' fixture-refresh-secret'
                               if execution_warning else '')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('parser', 'Task.', local_keys, smoke=smoke,
                        workspace=codex_login['workspace'], scoped=True)
    assert report['status'] == 'passed' and report['exit_code'] == 0
    assert 'diagnostic' not in report
    if smoke:
        assert report['response'].startswith('TAVERN_MODEL_OK_')
    else:
        assert report['response'] == 'Approved sources updated.'
    assert report['warnings'] == [
        {'stage': stage, 'category': 'path_aliases_read_only'}
        for stage, present in (('authentication', authentication_warning), ('execution', execution_warning))
        if present
    ]
    models.private_json(models.REPORTS / 'warning-run.json', report)
    saved = json.loads((models.REPORTS / 'warning-run.json').read_text(encoding='utf-8'))
    assert saved == report
    assert (models.REPORTS / 'warning-run.json').stat().st_mode & 0o777 == 0o600
    assert all(value not in json.dumps(saved) for value in (
        PATH_ALIASES_WARNING, 'fixture-access-secret', 'fixture-refresh-secret'))
    assert 'stdout' not in report and 'stderr' not in report
    assert len(roots) == 2 and roots[0] == roots[1] and not roots[0].exists()
    assert os.environ == parent_env
    assert_codex_source_unchanged(codex_login)


@pytest.mark.parametrize('stage', ['authentication', 'execution'])
def test_codex_nonzero_with_warning_and_success_output_still_fails(codex_login, local_keys,
                                                                  monkeypatch, stage):
    roots = []
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        current = 'authentication' if 'login' in command else 'execution'
        if current == 'authentication':
            result = subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
        else:
            nonce = options['input'].split('exactly ')[1].split('.')[0]
            result = codex_completed(command, nonce)
        if current == stage:
            return subprocess.CompletedProcess(command, 1, result.stdout,
                                               PATH_ALIASES_WARNING + ' fixture-access-secret')
        return result
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('parser', '', local_keys, smoke=True,
                        workspace=codex_login['workspace'], scoped=True)
    assert report['status'] == 'failed'
    assert report['diagnostic'] == {'stage': stage, 'category': 'path_aliases_read_only'}
    assert 'response' not in report and 'stdout' not in report and 'stderr' not in report
    assert all(value not in json.dumps(report) for value in (PATH_ALIASES_WARNING, 'fixture-access-secret'))
    assert len(roots) == (1 if stage == 'authentication' else 2)
    assert all(not root.exists() for root in roots)
    assert_codex_source_unchanged(codex_login)


class ReportStorageFS(storage.FileSystem):
    """Real disposable directories, fake mount readiness and capacity only."""
    def __init__(self, mount):
        self.mount = mount
        self.ready = True
        self.free = 10000
        self.created = []
        self.probes = []
        self.writable = True

    def mount_ready(self, path):
        return self.ready and path == self.mount

    def free_bytes(self, path):
        return self.free

    def create_directory(self, path):
        self.created.append(path)
        super().create_directory(path)

    def probe(self, path):
        self.probes.append(path)
        if not self.writable:
            raise PermissionError('fixture-storage-secret')
        super().probe(path)


@pytest.fixture
def external_reports(isolated_storage, tmp_path, monkeypatch):
    project = isolated_storage
    mount = tmp_path / 'fake-report-mount'
    mount.mkdir()
    document = {'version': 1, 'artifacts': {
        'path': str(mount / 'artifacts'), 'required_mount': str(mount), 'min_free_bytes': 1000},
        'temporary': {'path': str(mount / 'temporary'),
                      'required_mount': str(mount), 'min_free_bytes': 1000}}
    config = project / 'logs/harness/storage-local.json'
    config.parent.mkdir(parents=True, mode=0o700)
    config.write_text(json.dumps(document), encoding='utf-8')
    config.chmod(0o600)
    fs = ReportStorageFS(mount)
    monkeypatch.setattr(storage, 'FileSystem', lambda: fs)
    monkeypatch.setattr(models, 'ROOT', project)
    monkeypatch.setattr(triage, 'ROOT', project)
    return storage.resolve_storage(project), fs


def invoke_report_cli(module, tmp_path, monkeypatch, report_dir=None):
    """Exercise CLI path selection and output, with all paid/diagnostic work stubbed."""
    if module is models:
        monkeypatch.setattr(models, 'connection_status',
                            lambda *args: {'provider': 'zai', 'status': 'ready'})
        argv = ['doctor', '--provider', 'zai']
    elif module is triage:
        task = tmp_path / 'triage-task.txt'
        task.write_text('Inspect an approved source.', encoding='utf-8')
        monkeypatch.setattr(triage, 'load_policy', lambda: {'max_task_bytes': 1000})
        monkeypatch.setattr(triage, 'observe', lambda *args: {'status': 'passed', 'api_called': False})
        argv = ['recommend', '--task-file', str(task)]
    else:
        monkeypatch.setattr(compaction, 'probe', lambda **kwargs: {'status': 'passed'})
        argv = ['demo']
    if report_dir is not None:
        argv += ['--report-dir', str(report_dir)]
    return module.main(argv)


@pytest.mark.parametrize('module,category', [
    (models, 'agents'), (triage, 'triage'), (compaction, 'compaction'),
])
@pytest.mark.parametrize('override', ['configured', 'environment', 'explicit'])
def test_report_clis_use_shared_precedence_and_private_output(external_reports, local_keys,
                                                            tmp_path, monkeypatch, module,
                                                            category, override):
    policy, fs = external_reports
    environment = policy.artifact_root / 'environment-reports'
    explicit = policy.artifact_root / 'explicit-reports'
    if override != 'configured':
        monkeypatch.setenv('HARNESS_REPORT_DIR', str(environment))
    parent_env = dict(os.environ)
    assert invoke_report_cli(module, tmp_path, monkeypatch,
                             explicit if override == 'explicit' else None) == 0
    expected = {'configured': policy.artifact_root / category,
                'environment': environment, 'explicit': explicit}[override]
    paths = list(expected.glob('*.json'))
    assert len(paths) == 1
    assert paths[0].stat().st_mode & 0o777 == 0o600
    assert expected.stat().st_mode & 0o777 == 0o700
    assert policy.temp_root.stat().st_mode & 0o777 == 0o700
    assert fs.probes and os.environ == parent_env
    assert not (models.ROOT / 'logs/harness/agents/runtime').exists()
    assert not models.REPORTS.exists()


def test_report_resolution_tracks_current_root_and_reports_without_cached_config(
        isolated_storage, tmp_path, monkeypatch):
    root = tmp_path / 'other-project'
    root.mkdir()
    monkeypatch.setattr(models, 'ROOT', root)
    policy, directory = models.report_directory()
    assert policy.root == root and directory == root / 'logs/harness/agents'
    assert not directory.exists()
    reports = tmp_path / 'isolated-reports'
    monkeypatch.setattr(models, 'REPORTS', reports)
    assert models.report_directory()[1] == reports
    monkeypatch.setenv('HARNESS_REPORT_DIR', str(tmp_path / 'environment-reports'))
    assert models.report_directory()[1] == tmp_path / 'environment-reports'
    assert models.report_directory(tmp_path / 'explicit-reports')[1] == tmp_path / 'explicit-reports'


@pytest.mark.parametrize('module,category', [
    (models, 'agents'), (triage, 'triage'), (compaction, 'compaction'),
])
@pytest.mark.parametrize('override_reports', [False, True])
def test_local_report_clis_remain_isolated_with_root_and_reports_monkeypatches(
        isolated_storage, local_keys, tmp_path, monkeypatch, module, category, override_reports):
    monkeypatch.setattr(models, 'ROOT', isolated_storage)
    monkeypatch.setattr(triage, 'ROOT', isolated_storage)
    expected = (tmp_path / 'custom-local-reports' if override_reports else
                isolated_storage / 'logs/harness' / category)
    monkeypatch.setattr(module, 'REPORTS', expected if override_reports else module._DEFAULT_REPORTS)
    assert invoke_report_cli(module, tmp_path, monkeypatch) == 0
    assert len(list(expected.glob('*.json'))) == 1
    assert expected.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('provider', ['codex', 'claude', 'zai'])
@pytest.mark.parametrize('enabled', [False, True])
def test_model_children_do_not_inherit_storage_overrides(external_reports, local_keys,
                                                       monkeypatch, provider, enabled):
    policy, _ = external_reports
    monkeypatch.setenv(storage.CONFIG_ENV, str(models.ROOT / 'logs/harness/storage-local.json'))
    monkeypatch.setenv(storage.REPORT_ENV, str(policy.artifact_root / 'override'))
    parent_env = dict(os.environ)

    env = models.child_environment(provider, local_keys, compaction=enabled)

    assert storage.CONFIG_ENV not in env
    assert storage.REPORT_ENV not in env
    assert os.environ == parent_env


def test_external_reports_never_select_provider_or_diagnostic_state(external_reports, local_keys,
                                                                  tmp_path, monkeypatch):
    policy, fs = external_reports
    monkeypatch.setenv(storage.CONFIG_ENV, str(models.ROOT / 'logs/harness/storage-local.json'))
    monkeypatch.setenv('HARNESS_REPORT_DIR', str(policy.artifact_root / 'override'))
    monkeypatch.setenv('TMPDIR', str(policy.temp_root))
    monkeypatch.setenv('TMP', str(policy.temp_root))
    monkeypatch.setenv('TEMP', str(policy.temp_root))
    parent_env = dict(os.environ)
    for provider in ('claude', 'zai'):
        env = models.child_environment(provider, local_keys)
        runtime = Path(env['CLAUDE_CONFIG_DIR'])
        assert runtime == models.ROOT / 'logs/harness/agents/runtime' / provider
        assert runtime.stat().st_mode & 0o777 == 0o700
        assert env['TMPDIR'] == env['TMP'] == env['TEMP'] == str(runtime / 'tmp')
        assert (runtime / 'tmp').stat().st_mode & 0o777 == 0o700
        for name in ('HOME', 'CODEX_HOME'):
            assert env.get(name) == parent_env.get(name)
    env = compaction.diagnostic_environment()
    assert storage.CONFIG_ENV not in env
    assert storage.REPORT_ENV not in env
    runtime = Path(env['CLAUDE_CONFIG_DIR'])
    assert runtime == models.ROOT / 'logs/harness/compaction/runtime'
    assert runtime.stat().st_mode & 0o777 == 0o700
    assert env['TMPDIR'] == env['TMP'] == env['TEMP'] == str(runtime / 'tmp')
    assert not set(models.KEY_NAMES) & set(env)
    models.private_json(models.KEY_FILE, local_keys)
    assert models.KEY_FILE.stat().st_mode & 0o777 == 0o600
    assert models.KEY_FILE.parent == tmp_path
    assert os.environ == parent_env
    assert not policy.artifact_root.exists() and not policy.temp_root.exists()
    assert not fs.probes


def test_external_reports_keep_codex_auth_and_child_temp_local(external_reports, codex_login,
                                                            local_keys, monkeypatch):
    policy, _ = external_reports
    # Even an inherited/cached external tempfile default must not place auth there.
    monkeypatch.setattr(models.tempfile, 'tempdir', str(policy.temp_root))
    monkeypatch.setenv('TMPDIR', str(policy.temp_root))
    parent_env = dict(os.environ)
    roots = []

    def cli(command, **options):
        root = inspect_codex_runtime(command, options, codex_login)
        assert policy.temp_root not in root.parents
        assert policy.artifact_root not in root.parents
        roots.append(root)
        if 'login' in command:
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
        return codex_completed(command, 'Approved source inspected.')

    monkeypatch.setattr(models.subprocess, 'run', cli)
    assert models.main(['doctor', '--provider', 'codex']) == 0
    assert (policy.artifact_root / 'agents/doctor-codex.json').is_file()
    report = models.run('parser', 'Inspect source.', local_keys,
                        workspace=codex_login['workspace'], scoped=True)
    assert report['status'] == 'passed'
    assert all(not root.exists() for root in roots)
    assert os.environ == parent_env
    assert_codex_source_unchanged(codex_login)


@pytest.mark.parametrize('module', [models, triage, compaction])
@pytest.mark.parametrize('failure', ['missing_mount', 'below_floor', 'unwritable', 'missing_config',
                                   'malformed_config'])
def test_report_storage_failures_prevent_cli_activity_and_fallback(external_reports, local_keys,
                                                                 tmp_path, monkeypatch, capsys,
                                                                 module, failure):
    policy, fs = external_reports
    if failure == 'missing_mount':
        fs.ready = False
    elif failure == 'below_floor':
        fs.free = 999
    elif failure == 'unwritable':
        fs.writable = False
    elif failure == 'missing_config':
        monkeypatch.setenv('HARNESS_STORAGE_CONFIG', str(tmp_path / 'missing-private-config.json'))
    else:
        policy.config_path.write_text('{fixture-storage-secret', encoding='utf-8')
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw: pytest.fail('CLI ran before readiness'))
    monkeypatch.setattr(models, 'connection_status', lambda *a: pytest.fail('Auth ran before readiness'))
    monkeypatch.setattr(triage, 'observe', lambda *a: pytest.fail('Triage ran before readiness'))
    monkeypatch.setattr(compaction, 'probe', lambda **kw: pytest.fail('Probe ran before readiness'))
    if module is models:
        argv = ['doctor', '--provider', 'zai']
    elif module is triage:
        argv = ['recommend', '--task-file', str(tmp_path / 'not-read.txt')]
    else:
        argv = ['demo']
    parent_env = dict(os.environ)
    assert module.main(argv) == 1
    output = capsys.readouterr()
    assert 'storage unavailable' in output.err.lower()
    assert 'fixture-storage-secret' not in output.err + output.out
    assert not list(policy.artifact_root.glob('**/*.json'))
    assert not models.REPORTS.exists()
    assert os.environ == parent_env
    if failure != 'unwritable':
        assert not fs.created and not policy.artifact_root.exists() and not policy.temp_root.exists()


def test_direct_codex_storage_failure_never_copies_auth_or_runs_cli(external_reports, codex_login,
                                                                 local_keys, monkeypatch):
    policy, fs = external_reports
    fs.ready = False
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw: pytest.fail('CLI ran with absent mount'))
    report = models.run('parser', 'Inspect source.', local_keys,
                        workspace=codex_login['workspace'], scoped=True)
    assert report['status'] == 'failed'
    assert report['diagnostic'] == {'stage': 'storage', 'category': 'storage_unavailable'}
    assert 'required mount is absent' in report['error']
    assert not fs.created and not list(codex_login['base'].iterdir())
    assert not policy.artifact_root.exists()
    assert_codex_source_unchanged(codex_login)


def test_local_runtime_symlinks_and_public_modes_are_rejected(external_reports, local_keys,
                                                           tmp_path, monkeypatch):
    runtime = models.ROOT / 'logs/harness/agents/runtime'
    runtime.mkdir(parents=True, mode=0o700)
    unrelated = tmp_path / 'unrelated-state'
    unrelated.mkdir(mode=0o755)
    unrelated.chmod(0o755)
    (runtime / 'claude').symlink_to(unrelated, target_is_directory=True)
    with pytest.raises(ValueError, match='private local credential runtime'):
        models.child_environment('claude', local_keys)
    assert not list(unrelated.iterdir()) and unrelated.stat().st_mode & 0o777 == 0o755
    (runtime / 'claude').unlink()
    (runtime / 'claude').mkdir(mode=0o755)
    (runtime / 'claude').chmod(0o755)
    with pytest.raises(ValueError, match='0700'):
        models.child_environment('claude', local_keys)
    assert (runtime / 'claude').stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize('failure,outcome', [
    ('none', 'success'), ('child', 'child_failed'), ('timeout', 'timeout'),
    ('spawn', 'spawn_failed'), ('interrupt', 'interrupted'), ('json', 'invalid_response')])
def test_zai_private_spans_survive_every_cli_exit(local_keys, monkeypatch, tmp_path, failure, outcome):
    from harness import agent_telemetry as t
    from harness.test_agent_telemetry import batch, span
    created, calls = [], []
    real_collector = t.Collector

    def create(timeout):
        c = real_collector(timeout)
        # Exercise lifecycle integration without binding any listener in this fixture.
        c.start = lambda: c
        c.endpoint = 'http://127.0.0.1:123/private/v1/traces'
        created.append(c)
        return c

    monkeypatch.setattr(t, 'Collector', create)
    monkeypatch.setattr(models, 'connection_status', lambda *a: {'status': 'ready'})
    monkeypatch.setattr(models, 'child_environment', lambda *a, **kw: {'HTTPS_PROXY': 'model-proxy'})

    def child(command, **options):
        calls.append(command)
        assert options['env']['OTEL_TRACES_EXPORTER'] == 'otlp'
        assert options['env']['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] == '1'
        assert options['env']['HTTPS_PROXY'] == 'model-proxy'
        c = created[0]
        start = c.launch_ns // 1000000 + 1
        c.ingest(batch(span(1, start=start, ttft_ms=80, first_content_ms=82, attempt=1)))
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 7, output='NO_NEW_RAW_RETENTION')
        if failure == 'spawn':
            raise OSError('fixture spawn failure')
        if failure == 'interrupt':
            raise KeyboardInterrupt()
        output = 'malformed' if failure == 'json' else json.dumps({
            'result': 'ok', 'duration_ms': 123, 'duration_api_ms': 100,
            'num_turns': 2, 'usage': {
                'input_tokens': 4, 'output_tokens': True,
                'cache_read_input_tokens': 12, 'cache_creation_input_tokens': 7}})
        return subprocess.CompletedProcess(command, 1 if failure == 'child' else 0, output, '')

    monkeypatch.setattr(models.subprocess, 'run', child)
    report = models.run('downloader', 'fixture', local_keys, compaction=False,
                        scoped=True, workspace=tmp_path, timeout=7)
    assert len(calls) == 1 and created[0].stop.is_set()
    assert report['status'] == ('passed' if failure == 'none' else 'failed')
    value = report['telemetry']
    assert value['outcome'] == outcome and value['logical_requests_observed'] == 1
    assert value['first_request_ttft_ms'] == 80 and value['completeness'] == 'partial'
    assert 'NO_NEW_RAW_RETENTION' not in json.dumps(report)
    if failure in ('none', 'child'):
        assert value['cli']['num_turns'] == 2 and value['cli']['output_tokens'] is None
        assert value['cli']['input_tokens'] == 4
        assert value['cli']['cache_read_tokens'] == 12
        assert value['cli']['cache_creation_tokens'] == 7


def test_zai_collector_setup_failure_does_not_fail_successful_model(local_keys, monkeypatch, tmp_path):
    from harness import agent_telemetry as t
    monkeypatch.setattr(models, 'connection_status', lambda *a: {'status': 'ready'})
    monkeypatch.setattr(models, 'child_environment', lambda *a, **kw: {'OTEL_EXPORTER_OTLP_ENDPOINT': 'SECRET'})

    def broken(timeout):
        raise OSError('SECRET')
    monkeypatch.setattr(t, 'Collector', broken)
    calls = []

    def child(command, **options):
        calls.append(command)
        assert options['env']['OTEL_TRACES_EXPORTER'] == 'none'
        assert 'SECRET' not in json.dumps(options['env'])
        return subprocess.CompletedProcess(command, 0, '{"result":"ok"}', '')
    monkeypatch.setattr(models.subprocess, 'run', child)
    report = models.run('downloader', 'fixture', local_keys, compaction=False,
                        scoped=True, workspace=tmp_path)
    assert report['status'] == 'passed' and len(calls) == 1
    assert report['telemetry']['setup_failed']
    assert report['telemetry']['logical_requests_observed'] is None


def test_claude_has_no_new_collector_or_telemetry(local_keys, monkeypatch, tmp_path):
    from harness import agent_telemetry as t
    monkeypatch.setattr(t, 'Collector', lambda *a: pytest.fail('Claude enabled GLM collector'))
    monkeypatch.setattr(models, 'connection_status', lambda *a: {'status': 'ready'})
    monkeypatch.setattr(models, 'child_environment', lambda *a, **kw: {})
    monkeypatch.setattr(models.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, '{"result":"ok"}', ''))
    report = models.run('reviewer', 'fixture', local_keys, compaction=False,
                        scoped=True, workspace=tmp_path)
    assert report['status'] == 'passed' and 'telemetry' not in report


def test_codex_never_starts_glm_collector(codex_login, local_keys, monkeypatch):
    from harness import agent_telemetry as t
    monkeypatch.setattr(t, 'Collector', lambda *a: pytest.fail('Codex enabled GLM collector'))

    def child(command, **options):
        output = ('Logged in using ChatGPT' if 'login' in command else
                  '{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n'
                  '{"type":"turn.completed"}\n')
        return subprocess.CompletedProcess(command, 0, output, '')
    monkeypatch.setattr(models.subprocess, 'run', child)
    report = models.run('parser', 'fixture', local_keys, compaction=False,
                        workspace=codex_login['workspace'], scoped=True)
    assert report['status'] == 'passed' and 'telemetry' not in report


@pytest.mark.parametrize('failure', ['none', 'timeout', 'spawn'])
def test_zai_real_listener_is_closed_on_mocked_child_exit(local_keys, monkeypatch, tmp_path, failure):
    from harness import agent_telemetry as t
    from harness.test_agent_telemetry import batch, span, request
    real = t.Collector
    collectors = []

    def create(timeout):
        c = real(timeout)
        collectors.append(c)
        return c
    monkeypatch.setattr(t, 'Collector', create)
    monkeypatch.setattr(models, 'connection_status', lambda *a: {'status': 'ready'})
    monkeypatch.setattr(models, 'child_environment', lambda *a, **kw: {})

    def child(command, **options):
        c = collectors[0]
        if failure != 'spawn':
            body = batch(span(1, start=c.launch_ns // 1000000 + 1, ttft_ms=10, attempt=1))
            assert b'200 OK' in request(c, body)
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 7)
        if failure == 'spawn':
            raise OSError('fixture spawn failure')
        return subprocess.CompletedProcess(command, 0, '{"result":"ok"}', '')
    monkeypatch.setattr(models.subprocess, 'run', child)
    result = models.run('downloader', 'fixture', local_keys, compaction=False,
                        workspace=tmp_path, scoped=True, timeout=7)
    c = collectors[0]
    assert c.server.fileno() == -1 and not c.thread.is_alive()
    assert result['status'] == ('passed' if failure == 'none' else 'failed')
    assert result['telemetry']['logical_requests_observed'] == (None if failure == 'spawn' else 1)
