"""Offline plugin behavior is required; Claude Code's native engine is an extra check."""
import json
import re
import shutil
import subprocess

import pytest

from harness import agent_models, compaction


def test_pinned_vendor_files_are_present_and_unchanged():
    assert compaction.verify_vendor()['commit'] == 'e3f262a7f4d42bd8dd32ced30d26176f7cb545b0'


def test_all_node_compaction_tests_run_without_skips():
    node = shutil.which('node')
    assert node, 'Node.js >= 18 is required by the harness.'
    result = subprocess.run([node, str(compaction.PLUGIN / 'tests/compaction.test.mjs')],
                            env=compaction.diagnostic_environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    counts = {name: int(value) for name, value in re.findall(
        r'^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$', result.stdout, re.MULTILINE)}
    assert counts['tests'] == counts['pass'] and counts['tests'] > 0
    assert all(counts[name] == 0 for name in ('fail', 'cancelled', 'skipped', 'todo'))


def test_keyless_demo_reports_fake_transport_and_no_agent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(compaction, 'REPORTS', tmp_path / 'reports')
    monkeypatch.setattr(agent_models, 'KEY_FILE', tmp_path / 'no-key-file.json')
    for name in agent_models.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert compaction.main(['demo']) == 0
    report_file = next(compaction.REPORTS.glob('*.json'))
    report = json.loads(report_file.read_text())
    assert report_file.stat().st_mode & 0o777 == 0o600
    assert report['source'] == 'fixture' and report['outcome'] == 'history_pruned'
    assert report['text_preserved'] and not report['api_called'] and not report['agent_started']
    assert 'offline-demo-key' not in capsys.readouterr().out


def test_live_probe_requires_explicit_opt_in():
    with pytest.raises(SystemExit):
        compaction.main(['smoke'])


def test_live_probe_without_key_never_starts_node(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_models, 'KEY_FILE', tmp_path / 'no-key-file.json')
    for name in agent_models.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(compaction.subprocess, 'run', lambda *a, **kw: pytest.fail('Probe called Node without a key'))
    with pytest.raises(ValueError, match='not registered'):
        compaction.probe(live=True)


@pytest.mark.parametrize('role', ['downloader', 'reviewer', 'escalation'])
def test_compaction_is_enabled_for_claude_code_roles_with_existing_permissions(role):
    command = agent_models.command_for(role)
    assert '--plugin-dir' in command and str(compaction.PLUGIN) in command
    assert '--bare' not in command and '--safe-mode' not in command
    assert command[command.index('--setting-sources') + 1] == ''
    assert command[command.index('--mcp-config') + 1] == '{"mcpServers":{}}'
    assert command[command.index('--permission-mode') + 1] == 'dontAsk'
    disabled = agent_models.command_for(role, compaction=False)
    assert '--plugin-dir' not in disabled
    assert '--bare' in disabled or '--safe-mode' in disabled


@pytest.mark.parametrize('role', ['coordinator', 'parser', 'django'])
def test_codex_roles_do_not_receive_the_claude_plugin(role):
    assert '--plugin-dir' not in agent_models.command_for(role)
    assert '--plugin-dir' not in agent_models.command_for(role, compaction=True)


@pytest.mark.parametrize('provider', ['claude', 'zai'])
def test_only_selected_claude_code_processes_receive_the_compaction_key(provider, monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'unrelated-inherited-key')
    keys = {'ANTHROPIC_API_KEY': 'test-claude', 'ZAI_API_KEY': 'test-zai', 'TYPESAFE_API_KEY': 'test-typesafe'}
    assert 'TYPESAFE_API_KEY' not in agent_models.child_environment(provider, keys)
    env = agent_models.child_environment(provider, keys, compaction=True)
    assert env['TYPESAFE_API_KEY'] == 'test-typesafe'
    assert 'TYPESAFE_API_KEY' not in agent_models.child_environment('codex', keys, compaction=True)


def test_regular_model_smoke_stays_minimal_unless_compaction_is_requested():
    assert '--plugin-dir' not in agent_models.command_for('reviewer', smoke=True)
    assert '--plugin-dir' in agent_models.command_for('reviewer', smoke=True, compaction=True)


def test_plugin_refusal_is_reported_without_claiming_compaction_ran(monkeypatch):
    monkeypatch.setattr(agent_models.shutil, 'which', lambda cli: '/fake/' + cli)
    monkeypatch.setattr(agent_models.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(
        a, 0, '{"is_error":false,"result":"ok"}', 'fast-jev-compaction hooks module not loaded: managed policy'))
    report = agent_models.run('reviewer', 'Review', {'ANTHROPIC_API_KEY': 'test-claude'})
    assert report['status'] == 'passed'
    assert report['compaction'] == {'requested': True, 'key_registered': False, 'status': 'unavailable'}
