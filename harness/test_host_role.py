"""Strict standalone helpers and parse-time make guards; fixture recipes only."""
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest

from harness import host_role


@pytest.fixture(autouse=True)
def isolated_storage_environment(monkeypatch):
    monkeypatch.delenv('HARNESS_STORAGE_CONFIG', raising=False)
    monkeypatch.delenv('HARNESS_REPORT_DIR', raising=False)


@pytest.fixture
def marker(tmp_path):
    path = tmp_path / 'logs/harness/host-role'
    path.parent.mkdir(parents=True)
    return path


@pytest.mark.parametrize('body', [None, b'development', b'development\n'])
def test_development_entry(marker, tmp_path, body):
    if body is not None:
        marker.write_bytes(body)
    host_role.require_development(tmp_path)


def test_production_entry(marker, tmp_path):
    marker.write_text('production\n')
    assert host_role.host_role(tmp_path) == 'production'
    with pytest.raises(ValueError, match='Production'):
        host_role.require_development(tmp_path)


@pytest.mark.parametrize('body', [b'', b' production\n', b'production\n\n', b'unknown',
                                  b'\xff', b'x' * 33])
def test_malformed_marker(marker, tmp_path, body):
    marker.write_bytes(body)
    with pytest.raises(ValueError, match='host-role'):
        host_role.require_development(tmp_path)


@pytest.mark.parametrize('kind', ['symlink', 'dangling', 'directory', 'fifo', 'hardlink'])
def test_unsafe_marker(marker, tmp_path, kind):
    other = tmp_path / 'other'
    if kind != 'dangling':
        other.write_text('development\n')
    if kind in ('symlink', 'dangling'):
        marker.symlink_to(other)
    elif kind == 'directory':
        marker.mkdir()
    elif kind == 'fifo':
        os.mkfifo(str(marker))
    else:
        os.link(str(other), str(marker))
    with pytest.raises(ValueError):
        host_role.require_development(tmp_path)


def test_io_error_is_not_missing(monkeypatch, tmp_path):
    def denied(*args, **kwargs):
        raise PermissionError()
    monkeypatch.setattr(host_role, 'read_file', denied)
    with pytest.raises(ValueError, match='safely'):
        host_role.require_development(tmp_path)


def test_parent_symlink_is_refused(tmp_path):
    other = tmp_path / 'other'
    other.mkdir()
    (tmp_path / 'logs').symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError):
        host_role.require_development(tmp_path)


# Make entry points have a separate parse-time contract from the strict helper above.
PROTECTED = ['agent-workflow', 'agent-git-request', 'agent-git-accept', 'agent-git-resume',
             'agent-git-cleanup', 'agent-git-next', 'agent-git-next-file', 'agent-git-accept-file',
             'agent-git-proof-build', 'agent-git-external-merge', 'agent-worktree-park', 'agent-git-reconcile']
UNPROTECTED = ['check', 'agent-workflow-status', 'agent-workflow-plan',
               'agent-workflow-demo', 'agent-git-doctor', 'storage-status', 'storage-doctor',
               'deploy']


def fake_python(tmp_path):
    """Record argv only: never import or dispatch any real harness command."""
    script = tmp_path / 'fake-python'
    script.write_text('#!{}\n'.format(os.sys.executable) +
                      'import json, os, sys\n' +
                      'fd = os.open({!r}, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)\n'.format(
                          str(tmp_path / 'recipes')) +
                      'try: os.write(fd, (json.dumps(sys.argv[1:]) + "\\n").encode("utf-8"))\n'
                      'finally: os.close(fd)\n')
    script.chmod(0o700)
    return script


def make(tmp_path, goals=(), options=(), minimum=None):
    makefile = Path(__file__).resolve().parent.parent / 'Makefile'
    arguments = ['PYTHON=' + str(fake_python(tmp_path)), 'PYTEST_WORKERS=2',
                 'TASK_FILE=task.txt', 'FILES_FILE=files.txt', 'RUN_ID=fixture-run',
                 'REQUEST_ID=fixture-request', 'RESPONSE_FILE=response.json',
                 'REQUEST_FILE=request.json', 'RESPONSE_SHA256=' + 'a' * 64,
                 'PR_NUMBER=1', 'INPUT_DIR=proof', 'PROOF_FILE=proof.json',
                 'EVIDENCE_FILE=evidence.json', 'EVIDENCE_SHA256=' + 'a' * 64,
                 'COMMIT=' + 'b' * 40]
    if minimum is not None:
        arguments.append('MINIMUM_WRITE_SECONDS=' + minimum)
    return subprocess.run(['make', '--no-print-directory', '-C', str(tmp_path),
                           '-f', str(makefile), *options, *arguments, *goals],
                          env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=15, shell=False)


def recipes(tmp_path):
    path = tmp_path / 'recipes'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def expected_words(goal, minimum='300'):
    """Public recipe argv, including the #124 local write minimum."""
    run = ['--run-id', 'fixture-run']
    parent = ['-m', 'harness.parent_commands', goal] + run
    minimum_args = ['--minimum-write-seconds', minimum]
    return {
        'agent-workflow': ['-m', 'harness.workflow', 'run', '--task-file', 'task.txt',
                           '--files-file', 'files.txt'],
        'agent-git-request': ['-m', 'harness.git_publish', 'request'] + run,
        'agent-git-resume': ['-m', 'harness.git_publish', 'resume'] + run,
        'agent-git-cleanup': ['-m', 'harness.git_publish', 'cleanup'] + run,
        'agent-git-accept': ['-m', 'harness.git_publish', 'accept'] + run +
                            ['--request-id', 'fixture-request', '--response-file', 'response.json'],
        'agent-git-next': parent + minimum_args,
        'agent-git-next-file': parent + ['--request-file', 'request.json', '--sha256', 'a' * 64] +
                               minimum_args,
        'agent-git-accept-file': parent + ['--request-id', 'fixture-request', '--response-file',
                                         'response.json', '--sha256', 'a' * 64] + minimum_args,
        'agent-git-reconcile': parent + ['--request-id', 'fixture-request', '--evidence-file',
                                       'evidence.json', '--evidence-sha256', 'a' * 64] + minimum_args,
        'agent-git-proof-build': parent + ['--pr-number', '1', '--input-dir', 'proof',
                                         '--sha256', 'a' * 64],
        'agent-git-external-merge': parent + ['--pr-number', '1', '--proof-file', 'proof.json',
                                            '--sha256', 'a' * 64],
        'agent-worktree-park': parent,
    }[goal]


def assert_parse_refusal(result, tmp_path):
    assert result.returncode != 0
    assert b'Production host:' in result.stderr
    assert result.stdout == b''
    assert not (tmp_path / 'recipes').exists()


@pytest.mark.parametrize('goal', PROTECTED)
@pytest.mark.parametrize('options', [[], ['-n'], ['--dry-run'], ['-j8']])
@pytest.mark.parametrize('body', ['production', 'production\n'])
def test_each_production_goal_is_refused_at_parse_time(tmp_path, marker, goal, options, body):
    marker.write_text(body)
    assert_parse_refusal(make(tmp_path, [goal], options), tmp_path)


@pytest.mark.parametrize('body', [None, 'development', 'development\n'])
@pytest.mark.parametrize('parallel', [[], ['-j8']])
def test_development_and_missing_allow_all_protected_goals(tmp_path, marker, body, parallel):
    if body is not None:
        marker.write_text(body)
    result = make(tmp_path, PROTECTED, parallel)
    assert result.returncode == 0, result.stderr
    assert sorted(recipes(tmp_path)) == sorted(expected_words(goal) for goal in PROTECTED)


@pytest.mark.parametrize('body', [None, 'development\n'])
@pytest.mark.parametrize('option', ['-n', '--dry-run'])
@pytest.mark.parametrize('minimum', [None, '12.5'])
@pytest.mark.parametrize('goal', PROTECTED)
def test_dry_run_contains_only_original_recipe(tmp_path, marker, body, option, minimum, goal):
    if body is not None:
        marker.write_text(body)
    result = make(tmp_path, [goal], [option], minimum)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.decode('utf-8').splitlines()
    assert len(lines) == 1
    assert shlex.split(lines[0]) == [str(tmp_path / 'fake-python')] + expected_words(
        goal, minimum or '300')
    assert not (tmp_path / 'recipes').exists()


@pytest.mark.parametrize('parallel', [[], ['-j8']])
@pytest.mark.parametrize('dry_run', [[], ['-n'], ['--dry-run']])
@pytest.mark.parametrize('mode', ['protected', 'mixed-first', 'mixed-last'])
def test_production_multi_goal_rejects_entire_invocation(
        tmp_path, marker, parallel, dry_run, mode):
    marker.write_text('production\n')
    goals = list(PROTECTED)
    if mode != 'protected':
        # Even help/check listed first cannot execute before the parse-time error.
        others = ['help'] + UNPROTECTED
        goals = others + goals if mode == 'mixed-first' else goals + others
    assert_parse_refusal(make(tmp_path, goals, ['-k'] + parallel + dry_run), tmp_path)


@pytest.mark.parametrize('role', ['missing', 'development', 'production', 'unknown',
                                  'directory', 'fifo'])
@pytest.mark.parametrize('parallel', [[], ['-j8']])
def test_unprotected_goals_never_consult_or_reject_marker(tmp_path, marker, role, parallel):
    if role == 'directory':
        marker.mkdir()
    elif role == 'fifo':
        os.mkfifo(str(marker))
    elif role != 'missing':
        marker.write_text(role + '\n')
    result = make(tmp_path, ['help'] + UNPROTECTED, parallel)
    assert result.returncode == 0, result.stderr
    seen = recipes(tmp_path)
    assert len(seen) == len(UNPROTECTED)
    assert ['-m', 'harness', 'check', '--pytest-workers', '2'] in seen
    assert ['-m', 'harness.deploy', '--commit', 'b' * 40] in seen
    assert all(row[1] != 'harness.host_role' for row in seen)
    assert b'Manual ff-only deployment' in result.stdout


@pytest.mark.parametrize('role', ['production', 'unknown', 'directory', 'fifo'])
def test_default_help_does_not_consult_marker(tmp_path, marker, role):
    if role == 'directory':
        marker.mkdir()
    elif role == 'fifo':
        os.mkfifo(str(marker))
    else:
        marker.write_text(role + '\n')
    result = make(tmp_path)
    assert result.returncode == 0, result.stderr
    assert b'Manual ff-only deployment' in result.stdout
    assert not (tmp_path / 'recipes').exists()
