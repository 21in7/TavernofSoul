"""Run the real Chromium suite and reject missing or incomplete browser coverage."""
import json
import os
from pathlib import Path
import subprocess
import uuid

BROWSER = Path(__file__).resolve().parent / 'browser'
MANIFEST = json.loads((BROWSER / 'manifest.json').read_text())


def browser_doctor():
    try:
        result = subprocess.run(['node', str(BROWSER / 'doctor.js')], cwd=str(BROWSER),
                                capture_output=True, text=True, timeout=25)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
        return {'status': 'failed', 'errors': [str(exc)],
                'prepare': 'npm ci --prefix harness/browser; see docs/harness.md for native/container setup'}


def summarize_playwright(raw, manifest=MANIFEST):
    required = {(project, title) for project in manifest['projects'] for title in manifest['scenarios']}
    entries = []

    def visit(suite):
        for spec in suite.get('specs', []):
            for test in spec.get('tests', []):
                entries.append((spec['title'], test))
        for child in suite.get('suites', []):
            visit(child)

    for suite in raw.get('suites', []):
        visit(suite)
    actual = {(test.get('projectName'), title) for title, test in entries}
    errors = list(raw.get('errors', []))
    if actual != required or len(entries) != len(required):
        errors.append({'coverage': 'Required browser scenarios are missing, duplicated or unexpected',
                       'missing': sorted(required - actual), 'unexpected': sorted(actual - required)})
    passed, skipped, failures = 0, [], []
    for title, test in entries:
        entry = {'test': title, 'project': test.get('projectName')}
        attempts = test.get('results', [])
        forbidden = any(a.get('type') in ('skip', 'fixme', 'fail') for a in test.get('annotations', []))
        if test.get('expectedStatus') != 'passed' or forbidden or \
                any(a.get('status') == 'skipped' for a in attempts):
            skipped.append(entry)
        elif test.get('status') != 'expected' or len(attempts) != 1 or \
                attempts[0].get('status') != 'passed':
            entry['results'] = attempts
            failures.append(entry)
        else:
            passed += 1
    stats = raw.get('stats', {})
    if stats.get('expected') != passed or any(stats.get(key, 0) for key in ('unexpected', 'skipped', 'flaky')):
        errors.append({'coverage': 'Playwright statistics do not describe a complete passing run', 'stats': stats})
    return {'runner': 'playwright', 'selected': len(entries), 'passed': passed,
            'skipped': skipped, 'failures': failures, 'errors': errors,
            'status': 'failed' if errors or skipped or failures else 'passed'}


def run_browser(base_url, report_dir, region=None):
    from harness.runner import write_report
    suite = 'site-' + region if region else 'browser'
    artifacts = Path(report_dir) / suite / uuid.uuid4().hex
    artifacts.mkdir(parents=True)
    env = dict(os.environ, HARNESS_BROWSER_BASE_URL=base_url,
               HARNESS_BROWSER_ARTIFACT_DIR=str(artifacts))
    if region:
        if region not in ('itos', 'ktos'):
            raise ValueError('Only configured public site regions are supported')
        env['HARNESS_SITE_REGION'] = region
    for key in ('PW_TEST_CONNECT_WS_ENDPOINT', 'PWDEBUG', 'PLAYWRIGHT_HTML_OPEN'):
        env.pop(key, None)
    report = {'runner': 'playwright', 'status': 'failed', 'passed': 0, 'errors': []}
    try:
        result = subprocess.run(['node', str(BROWSER / 'node_modules/@playwright/test/cli.js'),
                                 'test', '--config', str(BROWSER / ('site.config.js' if region else 'playwright.config.js'))],
                                cwd=str(BROWSER), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, timeout=330)
        (artifacts / 'runner.log').write_text(result.stdout)
        print(result.stdout, end='', flush=True)
        raw = json.loads((artifacts / 'playwright.json').read_text())
        manifest = json.loads((BROWSER / 'site-manifest.json').read_text()) if region else MANIFEST
        report = summarize_playwright(raw, manifest)
        report['exit_code'] = result.returncode
        if result.returncode:
            report['status'] = 'failed'
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        report['errors'].append(str(exc))
        if isinstance(exc, subprocess.TimeoutExpired):
            output = exc.stdout or b''
            (artifacts / 'runner.log').write_text(output.decode(errors='replace') if isinstance(output, bytes) else output)
    report['artifacts'] = str(artifacts)
    write_report(Path(report_dir) / (suite + '-engine.json'), report)
    return report
