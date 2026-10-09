"""Browser result gates run offline without installing Playwright or Chromium."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from harness.browser_runner import MANIFEST, summarize_playwright


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
