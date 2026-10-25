"""A green check must not hide skips, collection errors, or an empty suite."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_runner_storage(tmp_path, monkeypatch):
    """Runner tests never select the checkout's private storage or ambient NFS."""
    from harness import runner
    project = tmp_path / 'project'
    project.mkdir(mode=0o700)
    monkeypatch.setattr(runner, 'ROOT', project)
    monkeypatch.delenv('HARNESS_STORAGE_CONFIG', raising=False)
    monkeypatch.delenv('HARNESS_REPORT_DIR', raising=False)
    return project


@pytest.fixture
def configured_runner_storage(isolated_runner_storage, tmp_path, monkeypatch):
    from harness import runner, storage

    class FakeFS(storage.FileSystem):
        ready = True
        free = 10000
        writable = True

        def mount_ready(self, path):
            return self.ready and path == mount

        def free_bytes(self, path):
            return self.free

        def probe(self, path):
            if not self.writable:
                raise PermissionError('private detail must not enter errors')
            super().probe(path)

    mount = tmp_path / 'mount'
    mount.mkdir(mode=0o700)
    fs = FakeFS()
    config = isolated_runner_storage / 'logs/harness/storage-local.json'
    config.parent.mkdir(parents=True, mode=0o700)
    config.write_text(json.dumps({
        'version': 1,
        'artifacts': {'path': str(mount / 'artifacts'), 'required_mount': str(mount),
                      'min_free_bytes': 1000},
        'temporary': {'path': str(mount / 'temporary'), 'required_mount': str(mount),
                      'min_free_bytes': 1000},
    }))
    config.chmod(0o600)
    monkeypatch.setattr(runner, 'resolve_storage',
                        lambda root: storage.resolve_storage(root, fs=fs))
    return runner.resolve_storage(isolated_runner_storage), fs, config


def test_required_fixtures_are_not_hidden_from_a_git_checkout():
    from harness.fixture_inputs import required_fixture_files
    paths = [str(path.relative_to(ROOT)) for path in required_fixture_files()]
    result = subprocess.run(['git', 'check-ignore', '--no-index', '--verbose', '--non-matching',
                             '-z', '--stdin'], cwd=str(ROOT), input='\0'.join(paths) + '\0',
                            capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    # Git also reports matching negations; those explicitly include the fixture.
    fields = result.stdout.split('\0')[:-1]
    assert len(fields) == len(paths) * 4, result.stdout
    ignored = [fields[index + 3] for index in range(0, len(fields), 4)
               if fields[index + 2] and not fields[index + 2].startswith('!')]
    assert not ignored, 'Required source fixtures are ignored: ' + ', '.join(ignored)


@pytest.mark.parametrize('source,passed,skipped,errors', [
    ('def test_ok(): assert True', True, 0, 0),
    ('import pytest\ndef test_skip(): pytest.skip("missing input")', False, 1, 0),
    ('import pytest\n@pytest.mark.xfail(reason="known bug")\ndef test_bug(): assert False', False, 1, 0),
    ('# No tests collected', False, 0, 0),
    ('import missing_harness_dependency_123', False, 0, 1),
])
def test_pytest_gate_in_a_fresh_process(tmp_path, source, passed, skipped, errors):
    test_file = tmp_path / 'test_example.py'
    test_file.write_text(source, encoding='utf-8')
    report_file = tmp_path / 'report.json'
    script = '''
import json, sys, pytest
from pathlib import Path
from harness.runner import PytestResults
plugin = PytestResults()
code = int(pytest.main(['-c', sys.argv[3], '-p', 'no:cacheprovider', sys.argv[1]], plugins=[plugin]))
Path(sys.argv[2]).write_text(json.dumps(plugin.report))
raise SystemExit(code)
'''
    result = subprocess.run([sys.executable, '-c', script, str(test_file), str(report_file),
                             str(ROOT / 'harness' / 'pytest.ini')],
                            capture_output=True, text=True)
    report = json.loads(report_file.read_text())
    assert (result.returncode == 0) == passed, result.stdout + result.stderr
    assert len(report['skipped']) == skipped
    assert len(report['errors']) == errors


@pytest.mark.parametrize('case,passed', [('pass', True), ('skip', False),
                                       ('empty', False), ('expected_failure', False)])
def test_django_gate_rejects_incomplete_suite(case, passed):
    from harness.django_runner import HarnessRunner

    class Example(unittest.TestCase):
        def runTest(self):
            if case == 'skip':
                self.skipTest('missing input')
            if case == 'expected_failure':
                self.fail('known bug')

    if case == 'expected_failure':
        Example.runTest = unittest.expectedFailure(Example.runTest)
    suite = unittest.TestSuite([] if case == 'empty' else [Example()])
    runner = HarnessRunner(verbosity=0, interactive=False)
    result = runner.run_suite(suite)
    assert result.wasSuccessful() == passed
    assert bool(runner.report['errors']) == (not passed)


def test_environment_failure_replaces_previous_success(tmp_path, monkeypatch):
    from harness import runner
    report_file = tmp_path / 'check.json'
    report_file.write_text('{"status": "passed"}')
    monkeypatch.setattr(sys, 'argv', ['harness', 'check', '--report-dir', str(tmp_path)])
    monkeypatch.setattr(runner, 'doctor', lambda: {'status': 'failed', 'checks': []})
    assert runner.main() == 1
    report = json.loads(report_file.read_text())
    assert report['status'] == 'failed'
    assert report['checks']['doctor']['status'] == 'failed'


@pytest.mark.parametrize('configured,environment,explicit', [
    (False, False, False), (False, True, False), (False, True, True),
    (True, False, False), (True, True, False), (True, True, True),
])
def test_runner_report_precedence(tmp_path, monkeypatch, isolated_runner_storage,
                                  configured_runner_storage, configured, environment, explicit):
    from harness import runner
    policy, _, config = configured_runner_storage
    if not configured:
        config.unlink()
    env_reports = tmp_path / 'environment-reports'
    cli_reports = tmp_path / 'explicit-reports'
    if environment:
        monkeypatch.setenv('HARNESS_REPORT_DIR', str(env_reports))
    argv = ['harness', 'doctor']
    if explicit:
        argv += ['--report-dir', str(cli_reports)]
        # Even an invalid lower-priority report override must not win.
        monkeypatch.setenv('HARNESS_REPORT_DIR', 'relative-invalid')
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(runner, 'doctor', lambda: {'status': 'passed', 'checks': []})
    assert runner.main() == 0
    expected = (cli_reports if explicit else env_reports if environment else
                policy.artifact_root if configured else isolated_runner_storage / 'logs/harness')
    assert json.loads((expected / 'doctor.json').read_text())['status'] == 'passed'
    assert stat.S_IMODE((expected / 'doctor.json').stat().st_mode) == 0o600
    assert stat.S_IMODE(expected.stat().st_mode) == 0o700
    if explicit:
        assert not env_reports.exists()


def test_report_cli_relative_path_keeps_compatibility(tmp_path, monkeypatch):
    from harness import runner
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['harness', 'doctor', '--report-dir', 'relative-reports'])
    monkeypatch.setattr(runner, 'doctor', lambda: {'status': 'passed'})
    assert runner.main() == 0
    assert (tmp_path / 'relative-reports/doctor.json').is_file()


def test_local_existing_report_directory_is_not_chmodded(tmp_path):
    from harness import runner
    directory = tmp_path / 'existing-reports'
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    path = directory / 'result.json'
    path.write_text('old')
    path.chmod(0o644)
    runner.write_report(path, {'status': 'passed'})
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize('case', ['missing', 'invalid', 'relative-path', 'absent-mount',
                                 'low-space', 'unwritable'])
def test_storage_failure_precedes_doctor_reports_and_subprocesses(
        tmp_path, monkeypatch, configured_runner_storage, capsys, case):
    from harness import runner
    policy, fs, config = configured_runner_storage
    if case == 'missing':
        monkeypatch.setenv('HARNESS_STORAGE_CONFIG', str(tmp_path / 'missing.json'))
    elif case == 'invalid':
        config.write_text('{broken private input')
    elif case == 'relative-path':
        data = json.loads(config.read_text())
        data['temporary']['path'] = 'relative'
        config.write_text(json.dumps(data))
    elif case == 'absent-mount':
        fs.ready = False
    elif case == 'low-space':
        fs.free = 999
    else:
        fs.writable = False

    def forbidden(*args, **kwargs):
        raise AssertionError('Storage failure must precede doctor/subprocess launch')

    reports = tmp_path / 'new-reports'
    monkeypatch.setattr(runner, 'doctor', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(sys, 'argv', ['harness', 'check', '--report-dir', str(reports)])
    assert runner.main() == 1
    assert not reports.exists()
    assert 'Harness storage:' in capsys.readouterr().err
    if case != 'unwritable':
        assert not policy.artifact_root.exists()
        assert not policy.temp_root.exists()


def test_configured_child_uses_private_work_and_scoped_temp(
        tmp_path, monkeypatch, configured_runner_storage):
    from harness import runner
    policy, _, _ = configured_runner_storage
    monkeypatch.setenv('HOME', str(tmp_path / 'local-home'))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'local-codex'))
    monkeypatch.setenv('TMPDIR', str(tmp_path / 'original-tmp'))
    monkeypatch.setenv('PYTEST_ADDOPTS', '--unsafe-option')
    monkeypatch.setenv('PYTEST_PLUGINS', 'unexpected-plugin')
    original = dict(os.environ)
    unrelated = policy.temp_root / 'retain-this'
    path = policy.artifact_root / 'parser.json'
    seen = {}

    def run(command, **kwargs):
        env = kwargs['env']
        work = Path(env['HARNESS_WORK_DIR'])
        child_tmp = Path(env['TMPDIR'])
        assert work.parent == policy.temp_root
        assert child_tmp == work / 'tmp'
        assert env['TEMP'] == env['TMP'] == str(child_tmp)
        assert env['HOME'] == original['HOME']
        assert env['CODEX_HOME'] == original['CODEX_HOME']
        assert 'PYTEST_ADDOPTS' not in env and 'PYTEST_PLUGINS' not in env
        assert env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'
        for directory in (policy.artifact_root, policy.temp_root, work, child_tmp):
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        unrelated.mkdir(mode=0o700)
        (unrelated / 'sentinel').write_text('preserve')
        (child_tmp / 'scratch').write_text('disposable')
        seen['work'] = work
        assert command[-2:] == ['--report-dir', str(path.parent)]
        runner.write_report(path, {'status': 'passed', 'passed': 1})
        return subprocess.CompletedProcess(command, 0, stdout='child output\n')

    monkeypatch.setattr(subprocess, 'run', run)
    assert runner.child_check('_pytest', 'parser', path)['status'] == 'passed'
    assert not seen['work'].exists()
    assert (unrelated / 'sentinel').read_text() == 'preserve'
    assert dict(os.environ) == original
    for record in (path, path.with_suffix('.log')):
        assert stat.S_IMODE(record.stat().st_mode) == 0o600
    assert path.with_suffix('.log').read_text() == 'child output\n'


def test_child_without_config_preserves_tempfile_and_child_environment(tmp_path, monkeypatch):
    from harness import runner
    local_temp = tmp_path / 'legacy-tempfile'
    local_temp.mkdir(mode=0o700)
    monkeypatch.setattr(tempfile, 'tempdir', str(local_temp))
    monkeypatch.setenv('TMPDIR', 'unchanged-inherited-value')
    path = tmp_path / 'reports/downloader.json'
    work_dirs = []

    def run(command, **kwargs):
        work = Path(kwargs['env']['HARNESS_WORK_DIR'])
        work_dirs.append(work)
        assert work.parent == local_temp
        assert kwargs['env']['TMPDIR'] == 'unchanged-inherited-value'
        assert not (work / 'tmp').exists()
        runner.write_report(path, {'status': 'passed'})
        return subprocess.CompletedProcess(command, 0, stdout='')

    monkeypatch.setattr(subprocess, 'run', run)
    assert runner.child_check('_pytest', 'downloader', path)['status'] == 'passed'
    assert work_dirs and not work_dirs[0].exists()


@pytest.mark.parametrize('crash', [False, True])
def test_configured_pytest_basetemp_is_disposable_and_private(
        monkeypatch, configured_runner_storage, crash):
    from harness import runner
    policy, _, _ = configured_runner_storage
    seen = []
    test_directory = runner.ROOT / 'harness'
    test_directory.mkdir()
    (test_directory / 'test_synthetic.py').write_text('def test_placeholder(): pass\n')

    def pytest_main(args, plugins):
        basetemp = Path(args[args.index('--basetemp') + 1])
        assert basetemp.parent.parent == policy.temp_root
        assert stat.S_IMODE(basetemp.parent.stat().st_mode) == 0o700
        assert not basetemp.exists()
        basetemp.mkdir(mode=0o700)
        (basetemp / 'scratch').write_text('disposable')
        seen.append(basetemp.parent)
        assert '-p' in args and 'no:cacheprovider' in args
        assert args[args.index('-n') + 1] == '2'
        assert '--dist=load' in args and '--max-worker-restart=0' in args
        assert 'xdist.plugin' in args and 'harness.pytest_support' in args
        assert any(arg.startswith('--deselect=') for arg in args)
        if crash:
            raise RuntimeError('fake pytest crash')
        plugins[0].report.update(selected=1, passed=1)
        return 0

    monkeypatch.setattr(pytest, 'main', pytest_main)
    if crash:
        with pytest.raises(RuntimeError, match='fake pytest crash'):
            runner.run_pytest('parser')
    else:
        # Storage lifecycle stubs do not supply actual collection/phase evidence.
        # Counter-only fake success must now fail the gate.
        assert runner.run_pytest('parser')['status'] == 'failed'
    assert len(seen) == 1 and not seen[0].exists()
    assert policy.temp_root.is_dir()


def test_local_pytest_preserves_default_basetemp(monkeypatch):
    from harness import runner

    def pytest_main(args, plugins):
        assert '--basetemp' not in args
        assert '-n' not in args and 'xdist.plugin' not in args
        plugins[0].report.update(selected=1, passed=1)
        return 0

    monkeypatch.setattr(pytest, 'main', pytest_main)
    assert runner.run_pytest('downloader')['status'] == 'failed'


@pytest.mark.parametrize('operation', ['child', 'pytest', 'write'])
def test_mount_failure_blocks_direct_runner_operations(
        monkeypatch, configured_runner_storage, operation):
    from harness import runner, storage
    policy, fs, _ = configured_runner_storage
    fs.ready = False

    def forbidden(*args, **kwargs):
        raise AssertionError('Unready storage must prevent validation')

    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(pytest, 'main', forbidden)
    with pytest.raises(storage.StorageError, match='mount is absent'):
        if operation == 'child':
            runner.child_check('_pytest', 'parser', policy.artifact_root / 'parser.json')
        elif operation == 'pytest':
            runner.run_pytest('parser')
        else:
            runner.write_report(policy.artifact_root / 'doctor.json', {'status': 'passed'})
    assert not policy.artifact_root.exists()
    assert not policy.temp_root.exists()


@pytest.mark.parametrize('returncode,write_success', [(0, False), (9, False), (9, True)])
def test_child_crash_or_missing_report_cannot_reuse_success(
        tmp_path, monkeypatch, returncode, write_success):
    from harness import runner
    path = tmp_path / 'parser.json'
    runner.write_report(path, {'status': 'passed'})

    def run(command, **kwargs):
        assert not path.exists()
        if write_success:
            runner.write_report(path, {'status': 'passed'})
        return subprocess.CompletedProcess(command, returncode, stdout='')

    monkeypatch.setattr(subprocess, 'run', run)
    report = runner.child_check('_pytest', 'parser', path)
    assert report['status'] == 'failed'
    if returncode:
        assert report['exit_code'] == returncode


def test_child_launch_exception_cleans_only_its_work(monkeypatch, configured_runner_storage):
    from harness import runner
    policy, _, _ = configured_runner_storage
    seen = []

    def run(command, **kwargs):
        seen.append(Path(kwargs['env']['HARNESS_WORK_DIR']))
        raise OSError('fake launch failure')

    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(OSError, match='fake launch failure'):
        runner.child_check('_pytest', 'parser', policy.artifact_root / 'parser.json')
    assert seen and not seen[0].exists()
    assert policy.temp_root.is_dir()


@pytest.mark.parametrize('link', ['symlink', 'hardlink'])
def test_private_writer_rejects_linked_records(tmp_path, link):
    from harness import runner, storage
    target = tmp_path / 'unrelated'
    target.write_text('keep this')
    target.chmod(0o644)
    report = tmp_path / 'doctor.json'
    if link == 'symlink':
        report.symlink_to(target)
    else:
        os.link(target, report)
    with pytest.raises(storage.StorageError):
        runner.write_report(report, {'status': 'passed'})
    assert target.read_text() == 'keep this'
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_runner_resolves_only_current_project_root(tmp_path, monkeypatch, isolated_runner_storage):
    from harness import runner, storage
    other = tmp_path / 'other-project/logs/harness'
    other.mkdir(parents=True)
    (other / 'storage-local.json').write_text('invalid unrelated config')
    seen = []

    def resolve(root):
        seen.append(root)
        return storage.resolve_storage(root, env={})

    monkeypatch.setattr(runner, 'resolve_storage', resolve)
    monkeypatch.setattr(runner, 'doctor', lambda: {'status': 'passed'})
    monkeypatch.setattr(sys, 'argv', ['harness', 'doctor'])
    assert runner.main() == 0
    assert seen and set(seen) == {isolated_runner_storage}
    assert (isolated_runner_storage / 'logs/harness/doctor.json').is_file()


def test_stdlib_only_docs_and_environment_diagnostics_do_not_import_pytest(tmp_path):
    changes = tmp_path / 'changes.json'
    changes.write_text(json.dumps({'changes': []}))
    script = '''
import importlib.abc, json, subprocess, sys
from pathlib import Path
class NoTestDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('pytest', 'xdist', 'execnet'):
            raise ModuleNotFoundError('synthetic stdlib-only environment')
sys.meta_path.insert(0, NoTestDependencies())
from harness import runner
assert 'harness.pytest_support' not in sys.modules
root = Path(sys.argv[1])
source_root = Path(sys.argv[2])
runner.ROOT = root
sys.argv = ['harness', 'check-docs', '--changes-file', str(root / 'changes.json'),
            '--report-dir', str(root / 'reports')]
assert runner.main() in (0, 1)
assert (root / 'reports/check-docs.json').is_file()
# Keep the environment diagnosis local; do not launch Node or read real storage.
runner.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout='v18.0.0')
runner.ROOT = source_root
report = runner.doctor()
assert report['status'] == 'failed'
assert any(c['name'] == 'pytest' and not c['ok'] for c in report['checks'])
assert 'harness.pytest_support' not in sys.modules
assert 'pytest' not in sys.modules
'''
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT)
    env.pop('HARNESS_STORAGE_CONFIG', None)
    env.pop('HARNESS_REPORT_DIR', None)
    result = subprocess.run([sys.executable, '-S', '-c', script, str(tmp_path), str(ROOT)],
                            cwd=str(tmp_path), env=env, capture_output=True, text=True,
                            timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
