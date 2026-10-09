"""Offline checks for provider isolation, billing selection, and failed probes."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from harness import agent_models as models


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


def test_codex_doctor_is_private_local_and_cleans_up(codex_login, local_keys, monkeypatch, capsys):
    parent_env = dict(os.environ)
    roots = []
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        assert 'login' in command and 'input' not in options
        assert options['timeout'] == 20
        return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', 'fixture-access-secret')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    assert models.main(['doctor', '--provider', 'codex']) == 0
    assert len(roots) == 1 and not roots[0].exists()
    output = capsys.readouterr().out
    assert 'fixture-access-secret' not in output
    assert 'chatgpt' in output
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
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
        assert (Path(options['env']['CODEX_HOME']) / 'auth.json').read_text() == 'private-refreshed-auth'
        assert 'private user instructions' not in options['input'].lower()
        assert options['cwd'] == str(workspace)
        policy = next(value for value in command if value.startswith('permissions.harness-scoped.filesystem='))
        assert json.dumps(str(workspace)) + '=' + json.dumps('write' if write else 'read') in policy
        assert '":root"="deny"' in policy and '":minimal"="read"' in policy
        return codex_completed(command, stderr='remote-warning fixture-refresh-secret')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('parser', 'Use approved sources.', local_keys, write=write,
                        workspace=workspace, scoped=True)
    assert report['status'] == 'passed'
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
            raise subprocess.TimeoutExpired(command, options['timeout'], output=sensitive, stderr=sensitive)
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


@pytest.mark.parametrize('failure,category', [
    ('api', 'authentication_failed'), ('aliases', 'path_aliases_read_only'), ('timeout', 'timeout'),
])
def test_codex_doctor_failure_diagnostics_are_structured(codex_login, local_keys, monkeypatch, capsys,
                                                        failure, category):
    roots = []
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 20, output='fixture-access-secret')
        message = ('Logged in using API key: fixture-access-secret' if failure == 'api' else
                   'PATH aliases: Read-only file system (os error 30) fixture-access-secret')
        # Initialization warnings must fail safely even when the CLI exits zero.
        return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT' if failure == 'aliases'
                                           else message, message if failure == 'aliases' else '')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    assert models.main(['doctor', '--provider', 'codex']) == 1
    output = capsys.readouterr().out
    assert category in output and 'fixture-access-secret' not in output
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


@pytest.mark.parametrize('output', ['remote body fixture-access-secret',
                                   '{"type":"turn.failed","message":"fixture-access-secret"}',
                                   'null', '[]',
                                   '{"type":"item.completed","item":"fixture-access-secret"}',
                                   '{"type":"item.completed","item":{"type":"agent_message","text":5}}\n'
                                   '{"type":"turn.completed"}'])
def test_codex_invalid_responses_never_become_diagnostics(codex_login, local_keys, monkeypatch, output):
    roots = []
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT' if 'login' in command
                                           else output, 'fixture-refresh-secret')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('parser', 'Task.', local_keys, workspace=codex_login['workspace'], scoped=True)
    assert report['diagnostic'] == {'stage': 'execution', 'category': 'invalid_response'}
    assert 'fixture-access-secret' not in json.dumps(report)
    assert 'fixture-refresh-secret' not in json.dumps(report)
    assert all(not root.exists() for root in roots)


def test_codex_smoke_mismatch_does_not_save_untrusted_response(codex_login, local_keys, monkeypatch):
    roots = []
    def cli(command, **options):
        roots.append(inspect_codex_runtime(command, options, codex_login))
        if 'login' in command:
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
        return codex_completed(command, 'remote fixture-access-secret')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('coordinator', '', local_keys, smoke=True)
    assert report['status'] == 'failed'
    assert report['diagnostic']['category'] == 'probe_mismatch'
    assert 'response' not in report and 'fixture-access-secret' not in json.dumps(report)
    assert all(not root.exists() for root in roots)


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


@pytest.mark.parametrize('doctor', [False, True])
def test_codex_cleanup_failure_is_never_reported_as_ready(codex_login, local_keys, monkeypatch, doctor):
    real_directory = models.tempfile.TemporaryDirectory
    class CleanupFailure(real_directory):
        def __exit__(self, *args):
            super().__exit__(*args)
            raise PermissionError('fixture-access-secret')
    monkeypatch.setattr(models.tempfile, 'TemporaryDirectory', CleanupFailure)
    def cli(command, **options):
        inspect_codex_runtime(command, options, codex_login)
        if 'login' in command:
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
        nonce = options['input'].split('exactly ')[1].split('.')[0]
        return codex_completed(command, nonce)
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = (models.connection_status('codex', local_keys) if doctor else
              models.run('coordinator', '', local_keys, smoke=True))
    assert report['status'] == ('not_configured' if doctor else 'failed')
    assert report['diagnostic'] == {'stage': 'runtime', 'category': 'runtime_unavailable'}
    assert 'response' not in report and 'fixture-access-secret' not in json.dumps(report)
    assert list(codex_login['base'].iterdir()) == []


def test_codex_zero_exit_alias_failure_does_not_accept_a_completed_turn(codex_login, local_keys, monkeypatch):
    def cli(command, **options):
        inspect_codex_runtime(command, options, codex_login)
        if 'login' in command:
            return subprocess.CompletedProcess(command, 0, 'Logged in using ChatGPT', '')
        nonce = options['input'].split('exactly ')[1].split('.')[0]
        return codex_completed(command, nonce, 'PATH aliases: Read-only file system (os error 30)')
    monkeypatch.setattr(models.subprocess, 'run', cli)
    report = models.run('coordinator', '', local_keys, smoke=True)
    assert report['status'] == 'failed'
    assert report['diagnostic'] == {'stage': 'execution', 'category': 'path_aliases_read_only'}
    assert list(codex_login['base'].iterdir()) == []
