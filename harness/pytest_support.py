"""Explicit pytest/xdist plugins and fail-closed local suite accounting.

Imported lazily by runner: docs-only commands must work with the stdlib alone.
The module plugin bootstraps workers; the controller's object plugin owns verdicts.
"""
from contextlib import contextmanager, nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import subprocess
import sys

import pytest


def worker_count(value):
    if type(value) is not int or value not in (1, 2):
        raise ValueError('Local pytest workers must be 1 (serial) or 2.')
    return value


class PytestResults:
    def __init__(self, workers=1):
        self.workers = worker_count(workers)
        self.report = {'runner': 'pytest', 'selected': 0, 'passed': 0,
                       'failures': [], 'errors': [], 'skipped': [], 'deselected': []}
        self.collections = {}
        self.ready = set()
        self.finished = {}
        self.phases = {}
        self.ids = []
        self.durations = {}
        self.timing_complete = True
        self.finalized = False

    def error(self, reason):
        self.report['errors'].append({'test': '', 'reason': reason})

    def pytest_collection_finish(self, session):
        if self.workers == 1:
            self.ids = [item.nodeid for item in session.items]

    def pytest_deselected(self, items):
        self.report['deselected'].extend(item.nodeid for item in items)

    def pytest_collectreport(self, report):
        if report.failed:
            self.report['errors'].append({'test': report.nodeid, 'reason': str(report.longrepr)})
        elif report.skipped:
            self.report['skipped'].append({'test': report.nodeid, 'reason': str(report.longrepr)})

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodeready(self, node):
        name = node.gateway.id
        if name in self.ready:
            self.error('Duplicate worker startup evidence.')
        self.ready.add(name)

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node, ids):
        name = node.gateway.id
        if name in self.collections or not self.valid_ids(ids):
            self.error('Malformed or duplicate worker collection evidence.')
        else:
            self.collections[name] = list(ids)

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error):
        name = node.gateway.id
        if name in self.finished:
            self.error('Duplicate worker completion evidence.')
        output = getattr(node, 'workeroutput', {})
        evidence = output.get('harness_collection') if isinstance(output, dict) else None
        self.finished[name] = evidence
        if (error or not isinstance(evidence, dict) or
                type(evidence.get('exitstatus')) is not int or evidence['exitstatus'] != 0 or
                type(output.get('exitstatus')) is not int or output['exitstatus'] != 0):
            self.error('Worker crashed, exited nonzero, or omitted completion evidence.')

    @staticmethod
    def valid_ids(ids):
        return (isinstance(ids, list) and all(isinstance(i, str) and i for i in ids)
                and len(set(ids)) == len(ids))

    def pytest_runtest_logreport(self, report):
        nodeid, when, outcome = report.nodeid, report.when, report.outcome
        worker = getattr(report, 'worker_id', None)
        if (not isinstance(nodeid, str) or not nodeid or
                when not in ('setup', 'call', 'teardown') or
                outcome not in ('passed', 'failed', 'skipped')):
            self.error('Malformed test phase evidence.')
            return
        self.phases.setdefault(nodeid, []).append((when, outcome, worker,
                                                  hasattr(report, 'wasxfail')))
        duration = report.duration
        if type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0:
            # Timing is diagnostic and must never decide a test verdict.
            self.timing_complete = False
        else:
            self.durations[nodeid] = self.durations.get(nodeid, 0.0) + duration
        entry = {'test': nodeid, 'reason': str(report.longrepr)}
        if report.skipped or hasattr(report, 'wasxfail'):
            self.report['skipped'].append(entry)
        elif report.failed:
            self.report['failures' if when == 'call' else 'errors'].append(entry)

    def finalize(self, exitstatus):
        if self.finalized:
            return self.report
        self.finalized = True
        if self.workers > 1:
            names = set(self.collections)
            complete = len(names) == self.workers and names == self.ready
            collections = list(self.collections.values())
            if not complete or not collections or any(ids != collections[0] for ids in collections):
                self.error('Missing or mismatched complete worker collections (including order).')
            else:
                self.ids = collections[0]
                if names != set(self.finished):
                    self.error('Missing or unexpected worker completion evidence.')
                deselected = None
                for name in sorted(names):
                    evidence = self.finished.get(name)
                    if (not isinstance(evidence, dict) or
                            evidence.get('ids') != self.collections[name] or
                            not self.valid_ids(evidence.get('deselected'))):
                        self.error('Malformed or incomplete worker collection completion evidence.')
                        complete = False
                        continue
                    if deselected is None:
                        deselected = evidence['deselected']
                    elif deselected != evidence['deselected']:
                        self.error('Worker deselection evidence differs.')
                        complete = False
                if complete:
                    self.report['deselected'] = deselected or []
        if not self.valid_ids(self.ids):
            self.error('Malformed or duplicate selected IDs.')
            self.ids = []
        self.report['selected'] = len(self.ids)
        self.report['collection_sha256'] = self.id_digest(self.ids)
        selected = set(self.ids)
        if (not self.valid_ids(self.report['deselected']) or
                selected.intersection(self.report['deselected'])):
            self.error('Malformed, duplicate, or overlapping deselection evidence.')
        if set(self.phases) - selected:
            self.error('Result received for an unselected test ID.')
        passed = []
        blocked = {e['test'] for key in ('failures', 'errors', 'skipped') for e in self.report[key]}
        for nodeid in self.ids:
            phases = self.phases.get(nodeid, [])
            whens = [p[0] for p in phases]
            owners = {p[2] for p in phases}
            valid_owner = (len(owners) == 1 and
                           (owners <= self.ready if self.workers > 1 else owners == {None}))
            ordered = whens in (['setup', 'call', 'teardown'], ['setup', 'teardown'])
            if not ordered or not valid_owner:
                self.error('Missing, duplicate, unordered, or cross-worker phases for ' + nodeid)
            elif whens == ['setup', 'call', 'teardown'] and all(
                    p[1] == 'passed' and not p[3] for p in phases):
                passed.append(nodeid)
            elif nodeid not in blocked:
                self.error('Incomplete passing phase evidence for ' + nodeid)
        self.report['passed_sha256'] = self.id_digest(passed)
        self.report['passed'] = len(passed)
        self.report['timing'] = {
            'phase_timing_complete': self.timing_complete,
            'test_elapsed_seconds_sum': sum(self.durations.values()),
            'slowest_tests': [{'test': name, 'elapsed_seconds': duration}
                              for name, duration in sorted(self.durations.items(),
                                  key=lambda pair: (-pair[1], pair[0]))[:20]],
        }
        ok = (int(exitstatus) == 0 and bool(self.ids) and len(passed) == len(self.ids)
              and not any(self.report[key] for key in ('failures', 'errors', 'skipped')))
        self.report.update(status='passed' if ok else 'failed',
                           exit_code=int(exitstatus) if int(exitstatus) else 0 if ok else 1)
        return self.report

    @staticmethod
    def id_digest(ids):
        # Compare complete ordered IDs without adding unbounded ID lists to JSON.
        return hashlib.sha256(json.dumps(ids, ensure_ascii=True,
                                         separators=(',', ':')).encode('ascii')).hexdigest()

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        self.finalize(exitstatus)
        session.exitstatus = self.report['exit_code']


class WorkerCollection:
    """Workers report collection only; partial execution has no global verdict."""
    def __init__(self):
        self.ids = []
        self.deselected = []

    def pytest_collection_finish(self, session):
        self.ids = [item.nodeid for item in session.items]

    def pytest_deselected(self, items):
        self.deselected.extend(item.nodeid for item in items)

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self, session, exitstatus):
        session.config.workeroutput['harness_collection'] = {
            'ids': self.ids, 'deselected': self.deselected, 'exitstatus': int(exitstatus)}


def pytest_configure(config):
    if hasattr(config, 'workerinput'):
        config.pluginmanager.register(WorkerCollection(), 'harness-worker-collection')


@pytest.hookimpl(trylast=True)
def pytest_sessionstart(session):
    config = session.config
    if hasattr(config, 'workerinput'):
        # xdist gives each local worker its own basetemp below the controller's.
        # Do not change persistent storage, model context or credential settings.
        work = config._tmp_path_factory.getbasetemp() / 'work'
        work.mkdir(mode=0o700)
        local_tmp = work / 'tmp'
        local_tmp.mkdir(mode=0o700)
        os.environ.update(HARNESS_WORK_DIR=str(work), TMPDIR=str(local_tmp),
                          TMP=str(local_tmp), TEMP=str(local_tmp))
        tempfile.tempdir = str(local_tmp)
        os.chdir(str(work))


@contextmanager
def isolated_plugin_environment():
    keys = ('PYTEST_DISABLE_PLUGIN_AUTOLOAD', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS')
    original = {key: os.environ.get(key) for key in keys}
    try:
        os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        for key in keys[1:]:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_suite(paths, *, root, ini, workers=1, basetemp=None, deselect=(), excluded=None):
    """Run a fixed local plan; no caller-provided pytest/plugin/execnet options."""
    workers = worker_count(workers)
    plugin = PytestResults(workers)
    # Treat every supplied path as a path, never as an additional pytest option.
    paths = [str(Path(path).absolute()) for path in paths]
    if not paths:
        plugin.error('No explicit test paths selected.')
        return plugin.finalize(1)
    args = ['-c', str(Path(ini).absolute()), '--rootdir', str(Path(root).absolute()), '-ra', '--tb=short',
            '-o', 'addopts=', '-o', 'tmp_path_retention_policy=failed',
            '-p', 'no:cacheprovider', '-p', 'harness.pytest_support']
    if workers > 1:
        args += ['-p', 'xdist.plugin', '-n', str(workers), '--dist=load',
                 '--max-worker-restart=0']
    if basetemp is not None:
        args += ['--basetemp', str(Path(basetemp).absolute())]
    args += ['--deselect=' + name for name in deselect]
    args += paths
    with isolated_plugin_environment():
        started = time.perf_counter()
        code = int(pytest.main(args, plugins=[plugin]))
        elapsed = time.perf_counter() - started
    report = plugin.finalize(code)
    # A later plugin/pytest failure cannot be hidden by earlier sessionfinish.
    if code:
        report.update(status='failed', exit_code=code)
    report.setdefault('timing', {})['pytest_elapsed_seconds'] = elapsed
    report['workers'] = workers
    if excluded is not None:
        report['excluded'] = excluded
    return report


def run_pytest(group, *, workers=2):
    from harness import runner
    worker_count(workers)
    started = time.perf_counter()
    storage = runner.resolve_storage(runner.ROOT)
    storage.prepare()
    temporary = (storage.temporary_directory(prefix='tavern-harness-pytest-')
                 if storage.configured else nullcontext(None))
    with temporary as work_dir:
        report = _run_pytest(group, workers=workers,
                             basetemp=work_dir / 'pytest' if work_dir else None)
        cleanup_started = time.perf_counter()
    report['timing']['pytest_cleanup_elapsed_seconds'] = (
        time.perf_counter() - cleanup_started if storage.configured else 0.0)
    report['timing']['pytest_group_elapsed_seconds'] = time.perf_counter() - started
    return report


def _run_pytest(group, *, basetemp=None, workers=2):
    from harness import runner
    worker_count(workers)
    root, excluded = runner.ROOT, runner.EXCLUDED
    test_dir = root / 'parser_tidy' / 'tests'
    if group == 'downloader':
        paths = [root / 'downloader' / 'tests']
    elif group == 'parser':
        paths = [path for path in sorted(test_dir.glob('test_*.py'))
                 if path.name not in runner.DJANGO_TESTS + ('test_baseline_json.py',)]
        paths.extend(sorted((root / 'harness').glob('test_*.py')))
    else:
        paths = [test_dir / name for name in runner.DJANGO_TESTS]
    return run_suite(paths, root=root, ini=root / 'harness' / 'pytest.ini',
                     workers=workers if group == 'parser' else 1, basetemp=basetemp,
                     deselect=[name for name in excluded if '::' in name] if group == 'parser' else (),
                     excluded=excluded if group == 'parser' else None)


def child_check(kind, group, path, *, pytest_workers=2):
    from harness import runner
    ROOT = runner.ROOT
    resolve_storage = runner.resolve_storage
    write_private_text = runner.write_private_text
    write_report = runner.write_report
    StorageError = runner.StorageError
    worker_count(pytest_workers)
    started = time.perf_counter()
    storage = resolve_storage(ROOT)
    path = Path(path).absolute()
    storage.ensure_directory(path.parent)
    # Also protect direct callers from a previous success masking a crash.
    if path.is_symlink():
        raise StorageError('Unsafe runner result path: symlink.')
    path.unlink(missing_ok=True)
    with storage.temporary_directory(prefix='tavern-harness-') as work_dir:
        env = dict(os.environ)
        env['HARNESS_WORK_DIR'] = str(work_dir)
        if storage.configured:
            child_tmp = storage.ensure_directory(work_dir / 'tmp')
            # This environment belongs only to the validation child. Authentication
            # runtimes retain their separate local policy; never change os.environ.
            env.update(TMPDIR=str(child_tmp), TMP=str(child_tmp), TEMP=str(child_tmp))
        if group == 'browser':
            env['HARNESS_BROWSER_REPORT_DIR'] = str(path.parent)
            (path.parent / 'browser-engine.json').unlink(missing_ok=True)
        env['DJANGO_SETTINGS_MODULE'] = ('TavernofSoul.settings_harness_mysql'
                                         if group in ('mysql', 'mysql-doctor')
                                         else 'TavernofSoul.settings_harness')
        env['PYTHONPATH'] = os.pathsep.join(str(path) for path in
                                          (ROOT, ROOT / 'TavernofSoul', ROOT / 'parser_tidy'))
        env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        env.pop('PYTEST_ADDOPTS', None)
        env.pop('PYTEST_PLUGINS', None)
        storage.check_ready()
        options = ['--pytest-workers', str(pytest_workers)] if kind == '_pytest' and group == 'parser' else []
        child_started = time.perf_counter()
        result = subprocess.run([sys.executable, '-m', 'harness', kind, group] + options +
                                ['--report-dir', str(path.parent)], cwd=str(ROOT), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        child_elapsed = time.perf_counter() - child_started
        log_path = path.with_suffix('.log')
        write_private_text(log_path, result.stdout, storage=storage)
        if result.returncode:
            print(result.stdout, end='')
        cleanup_started = time.perf_counter()
    cleanup_elapsed = time.perf_counter() - cleanup_started
    if not path.exists():
        write_report(path, {'status': 'failed', 'exit_code': result.returncode,
                            'errors': ['Check process ended without a result report.']}, storage=storage)
    if path.is_symlink():
        raise StorageError('Unsafe runner result path: symlink.')
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        report = {'status': 'failed', 'exit_code': 1,
                  'errors': ['Cannot read the check result: {}'.format(exc)]}
    if result.returncode:
        report.update(status='failed', exit_code=result.returncode)
    report['log'] = str(log_path)
    report.setdefault('timing', {}).update(
        child_elapsed_seconds=child_elapsed, cleanup_elapsed_seconds=cleanup_elapsed,
        group_elapsed_seconds=time.perf_counter() - started)
    write_report(path, report, storage=storage)
    return report

