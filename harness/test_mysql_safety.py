"""Reject unsafe MySQL targets and report a missing environment as a failure."""
import json
from pathlib import Path
import subprocess
import sys

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


def test_container_start_failure_cleans_up_and_replaces_previous_success(tmp_path, monkeypatch):
    docker = tmp_path / 'docker'
    removed = tmp_path / 'removed'
    docker.write_text('#!' + sys.executable + '\n' + '''
import os, sys
from pathlib import Path
if sys.argv[1] == 'create':
    print('fixture-container-id')
elif sys.argv[1] == 'start':
    raise SystemExit(42)
elif sys.argv[1] == 'rm':
    Path(os.environ['REMOVAL_LOG']).write_text(sys.argv[-1])
else:
    raise SystemExit(99)
''')
    docker.chmod(0o755)
    report_file = tmp_path / 'mysql-container.json'
    report_file.write_text('{"status": "passed"}')
    monkeypatch.setenv('HARNESS_DOCKER', str(docker))
    monkeypatch.setenv('HARNESS_REPORT_DIR', str(tmp_path))
    monkeypatch.setenv('REMOVAL_LOG', str(removed))
    result = subprocess.run(['bash', str(ROOT / 'harness/mysql.sh'), sys.executable],
                            capture_output=True, text=True)
    assert result.returncode == 42, result.stdout + result.stderr
    assert removed.read_text() == 'fixture-container-id'
    report = json.loads(report_file.read_text())
    assert report['status'] == 'failed'
    assert report['phase'] == 'server-start'
    assert report['container_removed'] is True
    assert report['exit_code'] == 42
