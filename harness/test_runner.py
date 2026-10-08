"""A green check must not hide skips, collection errors, or an empty suite."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

import pytest

ROOT = Path(__file__).resolve().parents[1]


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
