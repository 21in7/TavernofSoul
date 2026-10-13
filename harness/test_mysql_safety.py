"""Reject unsafe MySQL targets and report a missing environment as a failure."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from harness.mysql_checks import validate_grants
from harness.mysql_config import database_config

ENVIRONMENT = {
    'HARNESS_MYSQL_HOST': '127.0.0.1', 'HARNESS_MYSQL_PORT': '13306',
    'HARNESS_MYSQL_USER': 'tavern_harness', 'HARNESS_MYSQL_PASSWORD': 'fixture-only',
}
GRANTS = [
    "GRANT USAGE ON *.* TO `tavern_harness`@`%`",
    r"GRANT ALL PRIVILEGES ON `tavern\_harness`.* TO `tavern_harness`@`%`",
    r"GRANT ALL PRIVILEGES ON `test\_tavern\_harness`.* TO `tavern_harness`@`%`",
]
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('key,value', [
    ('HARNESS_MYSQL_HOST', ''), ('HARNESS_MYSQL_HOST', 'db.production'),
    ('HARNESS_MYSQL_HOST', 'localhost'), ('HARNESS_MYSQL_PORT', ''),
    ('HARNESS_MYSQL_PORT', '3306'), ('HARNESS_MYSQL_PORT', '0'),
    ('HARNESS_MYSQL_PORT', '65536'), ('HARNESS_MYSQL_PORT', 'invalid'),
    ('HARNESS_MYSQL_USER', 'root'), ('HARNESS_MYSQL_PASSWORD', ''),
])
def test_unsafe_connection_configuration_is_rejected(key, value):
    with pytest.raises(RuntimeError):
        database_config(dict(ENVIRONMENT, **{key: value}))


@pytest.mark.parametrize('grant', [
    "GRANT ALL PRIVILEGES ON *.* TO `tavern_harness`@`%`",
    "GRANT ALL PRIVILEGES ON `ktos`.* TO `tavern_harness`@`%`",
    "GRANT ALL PRIVILEGES ON `tavern_harness`.* TO `tavern_harness`@`%`",
    GRANTS[1] + ' WITH GRANT OPTION',
    "GRANT `admin`@`%` TO `tavern_harness`@`%`",
])
def test_broad_or_wildcard_privileges_are_rejected(grant):
    with pytest.raises(RuntimeError):
        validate_grants(GRANTS + [grant])


def test_both_literal_schema_grants_are_required():
    validate_grants(GRANTS)
    with pytest.raises(RuntimeError):
        validate_grants(GRANTS[:-1])


@pytest.mark.parametrize('command', ['check-mysql', 'doctor-mysql'])
def test_missing_mysql_environment_cannot_reuse_success_or_fall_back_to_sqlite(tmp_path, monkeypatch, command):
    from harness import runner
    artifacts = tmp_path / 'artifacts'
    temporary = tmp_path / 'temporary'
    artifacts.mkdir(mode=0o700)
    temporary.mkdir(mode=0o700)
    local_mount = tmp_path.resolve()
    while not os.path.ismount(local_mount):
        local_mount = local_mount.parent
    config_path = tmp_path / 'storage-local.json'
    with os.fdopen(os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as config_file:
        json.dump({
            'version': 1,
            'artifacts': {
                'path': str(artifacts.resolve()),
                'required_mount': str(local_mount),
                'min_free_bytes': 0,
            },
            'temporary': {
                'path': str(temporary.resolve()),
                'required_mount': str(local_mount),
                'min_free_bytes': 0,
            },
        }, config_file)
    monkeypatch.setenv('HARNESS_STORAGE_CONFIG', str(config_path.resolve()))
    monkeypatch.delenv('HARNESS_REPORT_DIR', raising=False)
    for key in ENVIRONMENT:
        monkeypatch.delenv(key, raising=False)
    # Even an inherited regional settings module must be replaced by the launcher.
    monkeypatch.setenv('DJANGO_SETTINGS_MODULE', 'TavernofSoul.settings_ktos')
    group = 'mysql' if command == 'check-mysql' else 'mysql-doctor'
    (tmp_path / (group + '.json')).write_text('{"status": "passed", "passed": 999}')
    (tmp_path / (command + '.json')).write_text('{"status": "passed"}')
    monkeypatch.setattr(runner, 'doctor', lambda: {'status': 'passed', 'checks': []})
    monkeypatch.setattr(sys, 'argv', ['harness', command, '--report-dir', str(tmp_path)])
    assert runner.main() == 1
    report = json.loads((tmp_path / (command + '.json')).read_text())
    assert report['status'] == 'failed'
    check = report['checks'][group]
    assert check['status'] == 'failed'
    assert 'HARNESS_MYSQL_HOST' in check['errors'][0]
    assert not check.get('passed')


def _wrapper_sandbox(tmp_path, kind):
    """Copy only approved code; all other input and processes are synthetic.

    Browser tests share this seam. No real doctor, Docker, mount, credentials,
    network, host config or inherited storage settings enter the subprocess.
    """
    root = tmp_path / 'project with spaces'
    harness = root / 'harness'
    harness.mkdir(parents=True)
    for name in (kind + '.sh', 'storage.py', 'runner.py'):
        shutil.copyfile(ROOT / 'harness' / name, harness / name)
    (harness / '__init__.py').write_text('')
    (harness / 'fixture_inputs.py').write_text('def required_fixture_files(): return []\n')
    (harness / 'mysql-init.sql').write_text('-- disposable fixture only\n')
    browser = harness / 'browser'
    (browser / 'node_modules/playwright').mkdir(parents=True)
    (browser / 'node_modules/playwright/cli.js').write_text('// fixture\n')
    (browser / 'container-image.txt').write_text('fixture-browser@sha256:fixture\n')
    mount = tmp_path / 'fake mount'
    mount.mkdir()
    artifacts, temporary = mount / 'artifacts', mount / 'temporary'
    config = tmp_path / 'storage.json'
    config.write_text(json.dumps({
        'version': 1,
        'artifacts': {'path': str(artifacts), 'required_mount': str(mount), 'min_free_bytes': 64},
        'temporary': {'path': str(temporary), 'required_mount': str(mount), 'min_free_bytes': 64},
    }))
    events = tmp_path / 'events.jsonl'
    python = tmp_path / 'fixture-python'
    python.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
def event(kind, args, **extra):
    with open(os.environ['FIXTURE_EVENTS'], 'a') as handle:
        handle.write(json.dumps(dict(kind=kind, args=args, **extra)) + '\\n')
from harness import storage
class FakeFS(storage.FileSystem):
    def mount_ready(self, path):
        return (str(path) == os.environ['FIXTURE_MOUNT'] and
                os.environ.get('FIXTURE_MOUNT_ABSENT') != '1')
    def free_bytes(self, path):
        return int(os.environ.get('FIXTURE_FREE_BYTES', '4096'))
    def probe(self, path):
        if os.environ.get('FIXTURE_UNWRITABLE') == '1':
            raise PermissionError('fixture only')
        return super().probe(path)
storage.FileSystem = FakeFS
args = sys.argv[1:]
if args[:2] == ['-m', 'harness.storage']:
    event('storage', args)
    raise SystemExit(storage.main(args[2:]))
elif args[:2] == ['-m', 'harness']:
    from harness.runner import write_report
    directory = Path(args[args.index('--report-dir') + 1])
    output = directory / (args[2] + '.json')
    event('harness', args, stale=output.exists(), tmpdir=os.environ.get('TMPDIR'),
          home=os.environ.get('HOME'), codex_home=os.environ.get('CODEX_HOME'))
    if args[2] != 'doctor' and os.environ.get('FIXTURE_TEST_FAILURE') == '1':
        raise SystemExit(23)
    write_report(output, {'status': 'passed', 'fixture': True})
elif args[0] == '-':
    sys.argv = ['-'] + args[1:]
    exec(compile(sys.stdin.read(), '<wrapper fixture stdin>', 'exec'), {'__name__': '__main__'})
elif args[0] == '-c':
    exec(args[1])
else:
    raise SystemExit('unexpected Python invocation')
''')
    python.chmod(0o755)
    docker = tmp_path / 'fixture-docker'
    docker.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
with open(os.environ['FIXTURE_EVENTS'], 'a') as handle:
    handle.write(json.dumps({'kind': 'docker', 'args': sys.argv[1:]}) + '\\n')
command = sys.argv[1]
if command == 'create': print('fixture-container-id')
elif command == 'start': raise SystemExit(int(os.environ.get('FIXTURE_START_EXIT', '0')))
elif command == 'logs': print('Listening on fixture; browser log')
elif command == 'port': print('127.0.0.1:13306')
elif command == 'inspect': print('true')
elif command == 'rm': raise SystemExit(int(os.environ.get('FIXTURE_REMOVE_EXIT', '0')))
elif command == 'exec': pass
else: raise SystemExit(99)
''')
    docker.chmod(0o755)
    # No ambient env: in particular do not expose a developer's storage/auth config.
    env = {'PATH': os.defpath, 'HARNESS_STORAGE_CONFIG': str(config),
           'HARNESS_DOCKER': str(docker), 'FIXTURE_EVENTS': str(events),
           'FIXTURE_MOUNT': str(mount), 'HOME': str(tmp_path / 'local-home'),
           'CODEX_HOME': str(tmp_path / 'local-codex'), 'TMPDIR': str(tmp_path / 'local-temp')}
    return SimpleNamespace(root=root, config=config, mount=mount, artifacts=artifacts,
                           temporary=temporary, events=events, python=python, env=env, kind=kind)


def _run_wrapper(sandbox, mode=None):
    command = ['bash', str(sandbox.root / 'harness' / (sandbox.kind + '.sh')), str(sandbox.python)]
    if mode is not None:
        command.append(mode)
    return subprocess.run(command, env=sandbox.env, capture_output=True, text=True, timeout=15)


def _wrapper_events(sandbox):
    return [json.loads(line) for line in sandbox.events.read_text().splitlines()]


def test_container_start_failure_cleans_up_and_replaces_previous_success(tmp_path):
    sandbox = _wrapper_sandbox(tmp_path, 'mysql')
    reports = tmp_path / 'override'
    reports.mkdir(mode=0o700)
    report_file = reports / 'mysql-container.json'
    report_file.write_text('{"status": "passed"}')
    sandbox.env.update(HARNESS_REPORT_DIR=str(reports), FIXTURE_START_EXIT='42')
    result = _run_wrapper(sandbox)
    assert result.returncode == 42, result.stdout + result.stderr
    assert ['rm', '--force', 'fixture-container-id'] in [event['args'] for event in _wrapper_events(sandbox)]
    report = json.loads(report_file.read_text())
    assert report['status'] == 'failed'
    assert report['phase'] == 'server-start'
    assert report['container_removed'] is True
    assert report['exit_code'] == 42
    assert stat.S_IMODE(report_file.stat().st_mode) == 0o600


@pytest.mark.parametrize('configured,override', [(False, False), (False, True), (True, False), (True, True)])
def test_mysql_wrapper_storage_precedence_and_disposable_database(tmp_path, configured, override):
    sandbox = _wrapper_sandbox(tmp_path, 'mysql')
    if not configured:
        sandbox.env.pop('HARNESS_STORAGE_CONFIG')
    reports = tmp_path / 'explicit reports' if override else (
        sandbox.artifacts if configured else sandbox.root / 'logs/harness')
    if override:
        sandbox.env['HARNESS_REPORT_DIR'] = str(reports)
    result = _run_wrapper(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((reports / 'mysql-container.json').read_text())
    assert report['status'] == 'passed' and report['container_removed'] is True
    assert stat.S_IMODE(reports.stat().st_mode) == 0o700
    assert stat.S_IMODE((reports / 'mysql-container.json').stat().st_mode) == 0o600
    events = _wrapper_events(sandbox)
    assert events[0]['kind'] == 'storage'
    children = [event for event in events if event['kind'] == 'harness']
    assert all(event['args'][-1] == str(reports) for event in children)
    for event in children:
        assert event['tmpdir'] == sandbox.env['TMPDIR']
        assert event['home'] == sandbox.env['HOME']
        assert event['codex_home'] == sandbox.env['CODEX_HOME']
    create = next(event['args'] for event in events if event['args'][0] == 'create')
    assert create[create.index('--tmpfs') + 1] == '/var/lib/mysql:rw,nosuid,nodev,size=1g'
    assert create[create.index('--publish') + 1] == '127.0.0.1::3306'
    assert '--mount' not in create and '--volume' not in create
    if configured:
        assert stat.S_IMODE(sandbox.temporary.stat().st_mode) == 0o700
    else:
        assert not sandbox.artifacts.exists() and not sandbox.temporary.exists()


@pytest.mark.parametrize('failure', ['missing-config', 'malformed', 'artifact-mount', 'temp-mount', 'floor', 'unwritable'])
def test_mysql_wrapper_storage_failure_precedes_status_traps_and_docker(tmp_path, failure):
    sandbox = _wrapper_sandbox(tmp_path, 'mysql')
    override = tmp_path / 'explicit reports'
    sandbox.env['HARNESS_REPORT_DIR'] = str(override)
    if failure == 'missing-config':
        sandbox.config.unlink()
    elif failure == 'malformed':
        sandbox.config.write_text('{invalid fixture')
    elif failure == 'artifact-mount':
        sandbox.env['FIXTURE_MOUNT_ABSENT'] = '1'
    elif failure == 'temp-mount':
        data = json.loads(sandbox.config.read_text())
        data['temporary']['required_mount'] = str(tmp_path / 'absent-temp-mount')
        data['temporary']['path'] = str(tmp_path / 'absent-temp-mount/private')
        sandbox.config.write_text(json.dumps(data))
    elif failure == 'floor':
        sandbox.env['FIXTURE_FREE_BYTES'] = '0'
    else:
        sandbox.env['FIXTURE_UNWRITABLE'] = '1'
    result = _run_wrapper(sandbox)
    assert result.returncode != 0 and '"error"' in result.stderr
    assert [event['kind'] for event in _wrapper_events(sandbox)] == ['storage']
    assert not override.exists() and not (sandbox.root / 'logs').exists()
    if failure != 'unwritable':
        assert not sandbox.artifacts.exists() and not sandbox.temporary.exists()
    assert not (tmp_path / 'absent-temp-mount').exists()


@pytest.mark.parametrize('remove_exit', ['0', '17'])
def test_mysql_wrapper_failed_check_removes_stale_success_and_cleans_container(tmp_path, remove_exit):
    sandbox = _wrapper_sandbox(tmp_path, 'mysql')
    sandbox.artifacts.mkdir(mode=0o700)
    stale = sandbox.artifacts / 'check-mysql.json'
    stale.write_text('{"status": "passed"}')
    sandbox.env.update(FIXTURE_TEST_FAILURE='1', FIXTURE_REMOVE_EXIT=remove_exit)
    result = _run_wrapper(sandbox)
    assert result.returncode == (23 if remove_exit == '0' else 1)
    assert not stale.exists()
    report = json.loads((sandbox.artifacts / 'mysql-container.json').read_text())
    assert report['status'] == 'failed' and 'checks' not in report
    assert report['container_removed'] is (remove_exit == '0')
    assert any(event['args'][0] == 'rm' for event in _wrapper_events(sandbox))
