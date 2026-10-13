"""Browser result gates run offline without installing Playwright or Chromium."""
from copy import deepcopy
import json
import stat
from types import SimpleNamespace

import pytest

from harness.browser_runner import MANIFEST, summarize_playwright
from harness.test_mysql_safety import _run_wrapper, _wrapper_events, _wrapper_sandbox


def passing_report():
    specs = []
    for title in MANIFEST['scenarios']:
        specs.append({'title': title, 'tests': [
            {'projectName': project, 'expectedStatus': 'passed', 'annotations': [],
             'status': 'expected', 'results': [{'status': 'passed'}]}
            for project in MANIFEST['projects']]})
    return {'suites': [{'suites': [{'specs': specs}]}], 'errors': [],
            'stats': {'expected': len(specs) * len(MANIFEST['projects']),
                      'unexpected': 0, 'skipped': 0, 'flaky': 0}}


def test_complete_browser_report_counts_both_viewports():
    report = summarize_playwright(passing_report())
    assert report['status'] == 'passed'
    assert report['passed'] == report['selected'] == 18
    assert report['errors'] == report['skipped'] == report['failures'] == []


@pytest.mark.parametrize('case', [
    'empty', 'missing_scenario', 'missing_mobile', 'duplicate', 'skip', 'xfail',
    'fail_annotation', 'retry', 'actual_failure', 'runner_error', 'inconsistent_stats',
])
def test_browser_gate_rejects_incomplete_and_misleading_green_reports(case):
    raw = deepcopy(passing_report())
    specs = raw['suites'][0]['suites'][0]['specs']
    test = specs[0]['tests'][0]
    if case == 'empty':
        raw['suites'] = []
        raw['stats']['expected'] = 0
    elif case == 'missing_scenario':
        specs.pop()
        raw['stats']['expected'] -= 2
    elif case == 'missing_mobile':
        for spec in specs:
            spec['tests'].pop()
        raw['stats']['expected'] //= 2
    elif case == 'duplicate':
        specs.append(deepcopy(specs[0]))
        raw['stats']['expected'] += 2
    elif case == 'skip':
        test['annotations'] = [{'type': 'skip'}]
    elif case == 'xfail':
        test['expectedStatus'] = 'failed'
        test['results'][0]['status'] = 'failed'
    elif case == 'fail_annotation':
        test['annotations'] = [{'type': 'fail'}]
    elif case == 'retry':
        test['results'].insert(0, {'status': 'failed'})
        test['status'] = 'flaky'
        raw['stats']['flaky'] = 1
    elif case == 'actual_failure':
        test['status'] = 'unexpected'
        test['results'][0]['status'] = 'failed'
        raw['stats']['unexpected'] = 1
    elif case == 'runner_error':
        raw['errors'] = [{'message': 'browser process died'}]
    elif case == 'inconsistent_stats':
        raw['stats']['expected'] = 0
    assert summarize_playwright(raw)['status'] == 'failed'


def test_passing_django_wrapper_cannot_replace_a_missing_browser_result(tmp_path, monkeypatch):
    import django
    import django.conf
    from harness import django_runner, runner

    class WrapperOnlyRunner:
        report = {'status': 'passed', 'passed': 1, 'selected': 1}

        def run_tests(self, labels):
            assert labels == ['harness.browser_tests']
            return 0

    monkeypatch.setattr(django, 'setup', lambda: None)
    monkeypatch.setattr(django.conf, 'settings', SimpleNamespace(DATABASES={
        'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}))
    monkeypatch.setattr(django_runner, 'HarnessRunner', lambda **kwargs: WrapperOnlyRunner())
    monkeypatch.setenv('HARNESS_BROWSER_REPORT_DIR', str(tmp_path))
    with pytest.raises(FileNotFoundError):
        runner.run_django('browser')


@pytest.mark.parametrize('mode', ['check-browser', 'check-site'])
@pytest.mark.parametrize('configured,override', [(False, False), (False, True), (True, False), (True, True)])
def test_browser_wrapper_storage_precedence_and_private_logs(tmp_path, mode, configured, override):
    sandbox = _wrapper_sandbox(tmp_path, 'browser')
    if not configured:
        sandbox.env.pop('HARNESS_STORAGE_CONFIG')
    reports = tmp_path / 'explicit reports' if override else (
        sandbox.artifacts if configured else sandbox.root / 'logs/harness')
    if override:
        sandbox.env['HARNESS_REPORT_DIR'] = str(reports)
    reports.mkdir(parents=True, mode=0o700)
    suite = mode[len('check-'):]
    log = reports / (suite + '-container.log')
    log.write_text('previous public-mode log')
    log.chmod(0o644)
    result = _run_wrapper(sandbox, mode)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((reports / (suite + '-container.json')).read_text())
    assert report['status'] == 'passed' and report['container_removed'] is True
    assert report['checks']['browser']['fixture'] is True
    assert 'browser log' in log.read_text() and 'previous' not in log.read_text()
    assert stat.S_IMODE(reports.stat().st_mode) == 0o700
    for file in (log, reports / (suite + '-container.json')):
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
    events = _wrapper_events(sandbox)
    assert events[0]['kind'] == 'storage'
    children = [event for event in events if event['kind'] == 'harness']
    assert all(event['args'][-1] == str(reports) for event in children)
    assert all(event['tmpdir'] == sandbox.env['TMPDIR'] and
               event['home'] == sandbox.env['HOME'] and
               event['codex_home'] == sandbox.env['CODEX_HOME'] for event in children)
    create = next(event['args'] for event in events if event['args'][0] == 'create')
    assert '--read-only' in create
    assert create[create.index('--tmpfs') + 1] == '/tmp:rw,nosuid,nodev,size=1g'
    assert create[create.index('--publish') + 1] == '127.0.0.1::3000'
    assert create[create.index('--cap-drop') + 1] == 'ALL'
    assert create[create.index('--security-opt') + 1] == 'no-new-privileges'
    mounts = [create[i + 1] for i, argument in enumerate(create) if argument == '--mount']
    assert mounts == ['type=bind,source=' + str(sandbox.root / 'harness/browser/node_modules') +
                      ',target=/opt/browser-sdk/node_modules,readonly']
    if configured:
        assert stat.S_IMODE(sandbox.temporary.stat().st_mode) == 0o700
    else:
        assert not sandbox.temporary.exists()


@pytest.mark.parametrize('failure', ['missing-config', 'malformed', 'artifact-mount', 'temp-mount', 'floor', 'unwritable'])
def test_browser_wrapper_storage_failure_precedes_status_traps_and_docker(tmp_path, failure):
    sandbox = _wrapper_sandbox(tmp_path, 'browser')
    reports = tmp_path / 'explicit reports'
    reports.mkdir(mode=0o700)
    previous = reports / 'browser-container.json'
    previous.write_text('{"status": "passed", "old": true}')
    sandbox.env['HARNESS_REPORT_DIR'] = str(reports)
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
    assert json.loads(previous.read_text()) == {'status': 'passed', 'old': True}
    assert list(reports.iterdir()) == [previous]
    assert not (sandbox.root / 'logs').exists()
    if failure != 'unwritable':
        assert not sandbox.artifacts.exists() and not sandbox.temporary.exists()
    assert not (tmp_path / 'absent-temp-mount').exists()


@pytest.mark.parametrize('remove_exit', ['0', '17'])
def test_browser_wrapper_start_failure_replaces_success_and_always_attempts_cleanup(tmp_path, remove_exit):
    sandbox = _wrapper_sandbox(tmp_path, 'browser')
    sandbox.artifacts.mkdir(mode=0o700)
    report_file = sandbox.artifacts / 'browser-container.json'
    report_file.write_text('{"status": "passed"}')
    sandbox.env.update(FIXTURE_START_EXIT='42', FIXTURE_REMOVE_EXIT=remove_exit)
    result = _run_wrapper(sandbox)
    assert result.returncode == (42 if remove_exit == '0' else 1)
    report = json.loads(report_file.read_text())
    assert report['status'] == 'failed' and report['phase'] == 'server-start'
    assert report['container_removed'] is (remove_exit == '0')
    assert any(event['args'] == ['rm', '--force', 'fixture-container-id']
               for event in _wrapper_events(sandbox))
    assert stat.S_IMODE((sandbox.artifacts / 'browser-container.log').stat().st_mode) == 0o600


@pytest.mark.parametrize('mode', ['check-browser', 'check-site'])
def test_browser_wrapper_failed_check_removes_stale_success_before_tests(tmp_path, mode):
    sandbox = _wrapper_sandbox(tmp_path, 'browser')
    sandbox.artifacts.mkdir(mode=0o700)
    stale = sandbox.artifacts / (mode + '.json')
    stale.write_text('{"status": "passed"}')
    sandbox.env['FIXTURE_TEST_FAILURE'] = '1'
    result = _run_wrapper(sandbox, mode)
    assert result.returncode == 23
    assert not stale.exists()
    suite = mode[len('check-'):]
    report = json.loads((sandbox.artifacts / (suite + '-container.json')).read_text())
    assert report['status'] == 'failed' and 'checks' not in report
    assert report['container_removed'] is True
    check = next(event for event in _wrapper_events(sandbox)
                 if event['kind'] == 'harness' and event['args'][2] == mode)
    assert check['stale'] is False


def test_browser_cleanup_rejects_symlink_log_and_still_removes_container(tmp_path):
    sandbox = _wrapper_sandbox(tmp_path, 'browser')
    sandbox.artifacts.mkdir(mode=0o700)
    unrelated = tmp_path / 'unrelated-user-log'
    unrelated.write_text('preserve user content')
    log = sandbox.artifacts / 'browser-container.log'
    log.symlink_to(unrelated)
    result = _run_wrapper(sandbox)
    assert result.returncode == 1
    assert unrelated.read_text() == 'preserve user content'
    assert log.is_symlink()
    report = json.loads((sandbox.artifacts / 'browser-container.json').read_text())
    assert report['status'] == 'failed' and report['container_removed'] is True
    assert any(event['args'] == ['rm', '--force', 'fixture-container-id']
               for event in _wrapper_events(sandbox))
