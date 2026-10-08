"""Run checks in fresh processes and publish explicit coverage/results as JSON."""
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from harness.fixture_inputs import required_fixture_files

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
DEPENDENCIES = ('pytest', 'django', 'django_mysql', 'pymysql', 'rest_framework',
                'mathfilters', 'lupa', 'PIL', 'pandas', 'numpy', 'pytz', 'cryptography')


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8')


def doctor():
    checks = []
    for name in DEPENDENCIES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            checks.append({'name': name, 'ok': False, 'error': str(exc)})
        else:
            checks.append({'name': name, 'ok': True})
    for name in ('harness/fixtures/minimal_release.json',
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


class PytestResults:
    def __init__(self):
        self.report = {'runner': 'pytest', 'selected': 0, 'passed': 0,
                       'failures': [], 'errors': [], 'skipped': [], 'deselected': []}

    def pytest_collection_finish(self, session):
        self.report['selected'] = len(session.items)

    def pytest_deselected(self, items):
        self.report['deselected'].extend(item.nodeid for item in items)

    def pytest_collectreport(self, report):
        if report.failed:
            self.report['errors'].append({'test': report.nodeid, 'reason': str(report.longrepr)})
        elif report.skipped:
            self.report['skipped'].append({'test': report.nodeid, 'reason': str(report.longrepr)})

    def pytest_runtest_logreport(self, report):
        entry = {'test': report.nodeid, 'reason': str(report.longrepr)}
        if report.skipped or hasattr(report, 'wasxfail'):
            self.report['skipped'].append(entry)
        elif report.failed:
            self.report['failures' if report.when == 'call' else 'errors'].append(entry)
        elif report.when == 'call' and report.passed:
            self.report['passed'] += 1

    def pytest_sessionfinish(self, session, exitstatus):
        if self.report['skipped'] or not self.report['selected']:
            session.exitstatus = 1


def run_pytest(group):
    import pytest
    plugin = PytestResults()
    test_dir = ROOT / 'parser_tidy' / 'tests'
    if group == 'downloader':
        paths = [str(ROOT / 'downloader' / 'tests')]
    elif group == 'parser':
        paths = [str(path) for path in sorted(test_dir.glob('test_*.py'))
                 if path.name not in DJANGO_TESTS + ('test_baseline_json.py',)]
        paths.extend(str(path) for path in sorted((ROOT / 'harness').glob('test_*.py')))
    else:
        paths = [str(test_dir / name) for name in DJANGO_TESTS]
    args = ['-c', str(ROOT / 'harness' / 'pytest.ini'), '--rootdir', str(ROOT),
            '-ra', '--tb=short', '-p', 'no:cacheprovider'] + paths
    if group == 'parser':
        args += ['--deselect=' + name for name in EXCLUDED if '::' in name]
        plugin.report['excluded'] = EXCLUDED
    code = int(pytest.main(args, plugins=[plugin]))
    plugin.report.update(status='passed' if code == 0 else 'failed', exit_code=code)
    return plugin.report


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


def child_check(kind, group, path):
    with tempfile.TemporaryDirectory(prefix='tavern-harness-') as work_dir:
        env = dict(os.environ)
        env['HARNESS_WORK_DIR'] = work_dir
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
        result = subprocess.run([sys.executable, '-m', 'harness', kind, group,
                                 '--report-dir', str(path.parent)], cwd=str(ROOT), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log_path = path.with_suffix('.log')
        log_path.write_text(result.stdout, encoding='utf-8')
        if result.returncode:
            print(result.stdout, end='')
    if not path.exists():
        write_report(path, {'status': 'failed', 'exit_code': result.returncode,
                            'errors': ['Check process ended without a result report.']})
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        report = {'status': 'failed', 'exit_code': 1,
                  'errors': ['Cannot read the check result: {}'.format(exc)]}
    if result.returncode:
        report.update(status='failed', exit_code=result.returncode)
    report['log'] = str(log_path)
    write_report(path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('doctor', 'check', 'check-downloader', 'check-parser',
                                           'check-django', 'check-pipeline', 'doctor-mysql',
                                           'check-mysql', 'doctor-browser', 'check-browser', 'check-site', 'check-live', '_pytest', '_django'))
    parser.add_argument('group', nargs='?', choices=('downloader', 'parser', 'django', 'pipeline',
                                                    'mysql', 'mysql-doctor', 'browser', 'live'))
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'logs' / 'harness')
    args = parser.parse_args()
    report_dir = args.report_dir.resolve()
    if args.command in ('_pytest', '_django'):
        if args.group is None:
            parser.error('Internal checks require a group')
        name = args.group + ('-regressions' if args.command == '_pytest' and args.group == 'django' else '')
        try:
            report = run_pytest(args.group) if args.command == '_pytest' else run_django(args.group)
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
        # A previous successful report must never mask a crashed process.
        path = report_dir / (name + '.json')
        if path.exists():
            path.unlink()
        results[name] = child_check(kind, group, path)
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
