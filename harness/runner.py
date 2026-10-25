"""Run checks in fresh processes and publish explicit coverage/results as JSON."""
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import secrets
import time
from harness.storage import StorageError, resolve_storage

ROOT = Path(__file__).resolve().parents[1]
DJANGO_TESTS = (
    'test_canonical_id.py', 'test_import_safety.py', 'test_recipe_migration_db.py',
)
EXCLUDED = {
    'parser_tidy/tests/test_baseline_json.py':
        'Local JSON/unpack baselines and historical bug demonstrations; outside the offline gate.',
    'parser_tidy/tests/test_package_parser.py::TestKtosRegression':
        'Requires local ktos unpack data.',
    'parser_tidy/tests/test_package_unresolved.py::TestKtosUnresolvedIntegration':
        'Requires local ktos unpack data.',
}
DEPENDENCIES = ('pytest', 'xdist', 'execnet', 'django', 'django_mysql', 'pymysql', 'rest_framework',
                'mathfilters', 'lupa', 'PIL', 'pandas', 'numpy', 'pytz', 'cryptography')


def write_private_text(path, text, *, storage=None):
    """Recheck storage and pin the parent before creating a private record."""
    storage = storage or resolve_storage(ROOT)
    path = Path(path).absolute()
    storage.ensure_directory(path.parent)
    directory = None
    try:
        directory = storage.fs.open_directory(path.parent)
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
                raise StorageError('Runner report/log must be an owned regular file without hard links.')
            os.fchmod(handle.fileno(), 0o600)
            os.ftruncate(handle.fileno(), 0)
            handle.write(text)
    except OSError:
        raise StorageError('Cannot write private runner report/log; check storage access.') from None
    finally:
        if directory is not None:
            os.close(directory)


def write_report(path, report, *, storage=None):
    write_private_text(path, json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                       storage=storage)


def doctor():
    from harness.fixture_inputs import required_fixture_files
    checks = []
    for name in DEPENDENCIES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            checks.append({'name': name, 'ok': False, 'error': str(exc)})
        else:
            checks.append({'name': name, 'ok': True})
    for name in ('harness/pytest.ini', 'harness/fixtures/minimal_release.json',
                 'harness/fixtures/downloader/revisions.bin',
                 'harness/fixtures/downloader/release.pak',
                 'harness/fixtures/downloader/ipf_patch.json',
                 'harness/fixtures/downloader/ipf_unpack_stub.py',
                 'TavernofSoul/TavernofSoul/settings_harness.py',
                 'TavernofSoul/TavernofSoul/settings_harness_mysql.py',
                 'harness/mysql-init.sql'):
        checks.append({'name': name, 'ok': (ROOT / name).is_file()})
    for path in required_fixture_files():
        checks.append({'name': str(path.relative_to(ROOT)), 'ok': path.is_file()})
    checks.append({'name': 'Python >= 3.8', 'ok': sys.version_info >= (3, 8)})
    try:
        node = subprocess.run(['node', '--version'], capture_output=True, text=True, check=True, timeout=10)
        version = node.stdout.strip()
        checks.append({'name': 'Node.js >= 18', 'ok': int(version.lstrip('v').split('.')[0]) >= 18,
                       'version': version})
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        checks.append({'name': 'Node.js >= 18', 'ok': False, 'error': str(exc)})
    ok = all(check['ok'] for check in checks)
    for check in checks:
        print('{} {}{}'.format('OK' if check['ok'] else 'FAIL', check['name'],
                              ': ' + check['error'] if 'error' in check else ''))
    print('Python: {} ({})'.format(sys.executable, sys.version.split()[0]))
    print('Offline database: SQLite :memory:; JSON: temporary directory; game data: not required')
    if not ok:
        print('Install harness/requirements.txt in an isolated environment; see docs/harness.md.')
    return {'status': 'passed' if ok else 'failed', 'python': sys.executable,
            'python_version': sys.version.split()[0], 'checks': checks}


def __getattr__(name):
    # Preserve the public import without requiring pytest for docs/diagnostics.
    if name == 'PytestResults':
        from harness.pytest_support import PytestResults
        return PytestResults
    raise AttributeError(name)


def run_pytest(group, *, workers=2):
    from harness.pytest_support import run_pytest as run
    return run(group, workers=workers)


def _run_pytest(group, *, basetemp=None, workers=2):
    from harness.pytest_support import _run_pytest as run
    return run(group, basetemp=basetemp, workers=workers)


def run_django(group):
    import django
    django.setup()
    from django.conf import settings
    mysql = group in ('mysql', 'mysql-doctor')
    if mysql:
        from harness.mysql_checks import inspect_database
        database = inspect_database()
        print('MySQL harness: {}'.format(json.dumps(database)), flush=True)
        if group == 'mysql-doctor':
            return {'status': 'passed', 'exit_code': 0, 'database': database}
    elif settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3' or \
            settings.DATABASES['default']['NAME'] != ':memory:':
        raise RuntimeError('Harness requires an in-memory SQLite database')
    from harness.django_runner import HarnessRunner
    runner = HarnessRunner(verbosity=1, interactive=False)
    labels = ['Items.tests'] if group == 'django' else [
        'harness.tests', 'harness.combat_tests', 'harness.contract_tests', 'harness.world_tests',
        'harness.regional_tests', 'harness.equipment_tests']
    if group == 'browser':
        labels = ['harness.browser_tests']
    if group == 'live':
        labels = ['harness.live_tests']
    if mysql:
        labels += ['Items.tests', 'harness.mysql_tests']
    try:
        code = runner.run_tests(labels)
    except Exception as exc:
        if not mysql:
            raise
        import traceback
        traceback.print_exc()
        return {'status': 'failed', 'exit_code': 1, 'database': database, 'errors': [str(exc)]}
    report = runner.report
    report.update(status='passed' if code == 0 else 'failed', exit_code=code)
    if mysql:
        report['database'] = database
    if group == 'live':
        from harness.live_fixture import FIXTURE, verify_snapshot
        report['sources'] = verify_snapshot(Path(os.environ.get('HARNESS_LIVE_FIXTURE', str(FIXTURE))))
    if group == 'browser':
        engine_path = Path(os.environ['HARNESS_BROWSER_REPORT_DIR']) / 'browser-engine.json'
        # Passing the server wrapper alone must never stand in for browser coverage.
        engine = json.loads(engine_path.read_text())
        engine['django'] = report
        engine['status'] = 'passed' if report['status'] == engine['status'] == 'passed' else 'failed'
        return engine
    return report


def child_check(kind, group, path, *, pytest_workers=2):
    from harness.pytest_support import child_check as run
    return run(kind, group, path, pytest_workers=pytest_workers)


def _main(state):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('doctor', 'check', 'check-downloader', 'check-parser',
                                           'check-django', 'check-pipeline', 'doctor-mysql',
                                           'check-mysql', 'doctor-browser', 'check-browser', 'check-site', 'check-live', 'check-docs', '_pytest', '_django'))
    parser.add_argument('group', nargs='?', choices=('downloader', 'parser', 'django', 'pipeline',
                                                    'mysql', 'mysql-doctor', 'browser', 'live'))
    parser.add_argument('--report-dir', type=Path)
    parser.add_argument('--pytest-workers', type=int, choices=(1, 2), default=2,
                        help='Local parser/harness processes; 1 selects serial diagnostics (default: 2).')
    parser.add_argument('--base')
    parser.add_argument('--head')
    parser.add_argument('--changes-file', type=Path)
    args = parser.parse_args()
    try:
        storage = resolve_storage(ROOT)
        report_dir = storage.report_dir(
            explicit=args.report_dir.absolute() if args.report_dir is not None else None,
            local_default=ROOT / 'logs' / 'harness')
        storage.ensure_directory(report_dir)
        if storage.version == 2 and args.command.startswith('check') and not os.environ.get('TAVERN_WORKFLOW_CHILD'):
            # A distinct active run prevents stale logs from another invocation
            # entering a standalone result archive. Overrides remain local-only.
            run_id = str(time.time_ns()) + '-' + secrets.token_hex(3)
            active_run = storage.ensure_directory(storage.artifact_root / 'checks' / run_id)
            if args.report_dir is None and 'HARNESS_REPORT_DIR' not in os.environ:
                report_dir = active_run
            else:
                report_dir = storage.ensure_directory(report_dir / run_id)
            state.update(storage=storage, directory=active_run, reports=report_dir, command=args.command,
                         run_id=run_id)
    except StorageError as exc:
        print('Harness storage: {}'.format(exc), file=sys.stderr)
        return 1
    if args.command == 'check-docs':
        from harness import docs_check
        try:
            changes = (json.loads(args.changes_file.read_text(encoding='utf-8'))['changes']
                       if args.changes_file else docs_check.git_changes(ROOT, args.base, args.head))
            report = docs_check.check(ROOT, changes)
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
            report = {'status': 'failed', 'checks': {'docs': {
                'status': 'failed', 'selected': 0, 'passed': 0, 'skipped': [],
                'failures': [], 'errors': [{'exception_type': 'ValueError', 'reason': 'Missing complete change evidence.'}]}}}
        write_report(report_dir / 'check-docs.json', report, storage=storage)
        return 0 if report['status'] == 'passed' else 1
    if args.command in ('_pytest', '_django'):
        if args.group is None:
            parser.error('Internal checks require a group')
        name = args.group + ('-regressions' if args.command == '_pytest' and args.group == 'django' else '')
        try:
            report = (run_pytest(args.group, workers=args.pytest_workers)
                      if args.command == '_pytest' else run_django(args.group))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            report = {'status': 'failed', 'exit_code': 1, 'errors': [str(exc)]}
        write_report(report_dir / (name + '.json'), report)
        if report.get('skipped'):
            print('FAIL: required checks were skipped; see the JSON report.')
        return 0 if report['status'] == 'passed' else 1
    report = doctor()
    write_report(report_dir / 'doctor.json', report)
    if report['status'] != 'passed' or args.command == 'doctor':
        if args.command != 'doctor':
            write_report(report_dir / (args.command + '.json'), {
                'status': 'failed', 'checks': {'doctor': report},
            })
        return 0 if report['status'] == 'passed' else 1
    specs = []
    if args.command in ('doctor-browser', 'check-browser', 'check-site'):
        from harness.browser_runner import browser_doctor
        browser = browser_doctor()
        write_report(report_dir / 'doctor-browser.json', browser)
        print('Browser: {}'.format(json.dumps(browser)), flush=True)
        if args.command == 'doctor-browser':
            return 0 if browser['status'] == 'passed' else 1
        if browser['status'] != 'passed':
            write_report(report_dir / (args.command + '.json'), {'status': 'failed', 'checks': {'doctor-browser': browser}})
            return 1
        if args.command == 'check-site':
            from harness.browser_runner import run_browser
            results = {region: run_browser('', report_dir, region=region) for region in ('itos', 'ktos')}
            ok = all(result['status'] == 'passed' for result in results.values())
            write_report(report_dir / 'check-site.json', {
                'status': 'passed' if ok else 'failed', 'environment': browser, 'checks': results})
            print('Reports: {}'.format(report_dir))
            return 0 if ok else 1
        specs.append(('_django', 'browser', 'browser'))
    if args.command in ('check', 'check-downloader'):
        specs.append(('_pytest', 'downloader', 'downloader'))
    if args.command in ('check', 'check-parser'):
        specs.append(('_pytest', 'parser', 'parser'))
    if args.command in ('check', 'check-django'):
        specs.extend([('_pytest', 'django', 'django-regressions'), ('_django', 'django', 'django')])
    if args.command in ('check', 'check-pipeline'):
        specs.append(('_django', 'pipeline', 'pipeline'))
    if args.command == 'doctor-mysql':
        specs.append(('_django', 'mysql-doctor', 'mysql-doctor'))
    if args.command == 'check-mysql':
        specs.append(('_django', 'mysql', 'mysql'))
    if args.command == 'check-live':
        specs.append(('_django', 'live', 'live'))
    results = {}
    for kind, group, name in specs:
        print('\nRunning {} ...'.format(name), flush=True)
        path = report_dir / (name + '.json')
        results[name] = child_check(kind, group, path, pytest_workers=args.pytest_workers)
        if group == 'browser':
            results[name]['environment'] = browser
            write_report(path, results[name])
    ok = all(result['status'] == 'passed' for result in results.values())
    write_report(report_dir / (args.command + '.json'), {
        'status': 'passed' if ok else 'failed', 'checks': results,
    })
    for name, result in results.items():
        print('{} {}: {} passed, {} skipped'.format(result['status'].upper(), name,
              result.get('passed', 0), len(result.get('skipped', []))))
        if result.get('database'):
            print('Database: MySQL {}; test schema: {}'.format(
                result['database']['version'], result['database']['test_database']))
    print('Reports: {}'.format(report_dir))
    return 0 if ok else 1


def main():
    state = {}
    interrupted = False
    try:
        code = _main(state)
    except KeyboardInterrupt:
        if not state:
            raise
        interrupted, code = True, 130
    except Exception as exc:
        # Preserve runner exceptions; archive a failed result when a run exists.
        if not state:
            raise
        print('Runner failed: ' + type(exc).__name__, file=sys.stderr)
        state['error_type'] = type(exc).__name__
        code = 1
    if state:
        from harness import archive
        policy, directory = state['storage'], state['directory']
        try:
            path = state['reports'] / (state['command'] + '.json')
            result = json.loads(archive.read_file(policy, path)) if path.exists() else {}
            if state['reports'] != directory:
                # Only this invocation's fresh private output directory is copied.
                for source in state['reports'].iterdir():
                    if source.stem in archive.RESULT_STEMS and source.suffix in ('.json', '.log'):
                        archive.write_file(policy, directory / source.name, archive.read_file(policy, source))
            report = {**result, 'run_id': state['run_id'], 'command': state['command'],
                      'status': 'interrupted' if interrupted else 'passed' if code == 0 else 'failed',
                      'exit_code': code}
            if 'error_type' in state:
                report['error_type'] = state['error_type']
            write_report(directory / 'report.json', report, storage=policy)
            archived = archive.archive_run(policy, directory, 'checks')
        except (Exception, KeyboardInterrupt) as exc:
            archived = {'status': 'pending', 'error_type': type(exc).__name__}
        print(json.dumps({'run_id': state['run_id'], 'archive': archived}))
        if archived['status'] != 'archived':
            code = code or 1
    return code
