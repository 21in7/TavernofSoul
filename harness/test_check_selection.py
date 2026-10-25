"""Intent and fail-closed boundaries for change-scoped CI evidence."""
import copy
import json
import os
import stat

import pytest

from harness import agent_models, check_selection as checks, docs_check, workflow
from harness.test_workflow import (
    docs_creation_umask, isolated_storage, project, run_fixture, runner_for, successful_check,
)


def change(name, status='M', new=None, old_mode='100644', new_mode='100644'):
    return {'status': status, 'old_path': None if status == 'A' else name,
            'new_path': None if status == 'D' else new or name,
            'old_mode': None if status == 'A' else old_mode,
            'new_mode': None if status == 'D' else new_mode}


def evidence(*rows, event='pull_request'):
    return checks.make_plan(docs_check.classify(list(rows)), event)


@pytest.mark.parametrize('name,browser', [
    ('downloader/downloader.py', False), ('downloader/tests/test_retry.py', False),
    *[(name, False) for name in sorted(checks.ORCHESTRATION)],
    ('TavernofSoul/templates/Items/search.html', True),
    ('TavernofSoul/templates/Items/index.html', True),
    ('TavernofSoul/templates/Planner/pvp.html', True),
    ('TavernofSoul/static/js/item-search.js', True),
    ('TavernofSoul/static/js/item-enhancement.js', True),
    ('TavernofSoul/static/js/pvp-calculator.js', True),
])
def test_narrow_code_changes_keep_offline_and_only_relevant_executions(name, browser):
    plan = evidence(change(name))
    assert checks.validate_plan(plan) == {
        'offline': True, 'mysql': False, 'browser': browser, 'live': False, 'docs': False}
    assert plan['paths'] == [{'path': name, 'classification': checks.path_class(name)}]


@pytest.mark.parametrize('name', [
    'AGENTS.md', 'docs/workflow.md', 'docs/harness-design.md', 'docs/data-contracts.md',
    '.github/workflows/harness.yml', 'Makefile', 'harness/check_selection.py',
    'harness/test_check_selection.py', 'harness/runner.py', 'harness/requirements.txt',
    'harness/fixtures/minimal_release.json', 'harness/pytest.ini',
    'downloader/settings.py', 'downloader/tests/conftest.py',
    'parser_tidy/main.py', 'TavernofSoul/ipfparser/importer.py',
    'TavernofSoul/Items/models.py', 'TavernofSoul/Items/migrations/0001_initial.py',
    'TavernofSoul/TavernofSoul/settings.py', 'unknown.py',
    'TavernofSoul/Other/templates/search.html',
    'TavernofSoul/Items/templates/Items/search.html',
    'TavernofSoul/Items/static/Items/search.js',
    'TavernofSoul/templates_x/Items/search.html',
    'TavernofSoul/static_x/js/item-search.js',
    'TavernofSoul/templates/Items/search.js',
    'TavernofSoul/static/js/item-search.html',
    'TavernofSoul/static/js/item-search.json',
])
def test_policy_shared_contracts_and_unverified_paths_keep_all_checks(name):
    plan = evidence(change('downloader/downloader.py'), change(name))
    assert plan['plan'] == {'offline': True, 'mysql': True, 'browser': True,
                            'live': True, 'docs': False}


def test_mixed_prose_and_allowlisted_code_union_without_hiding_other_paths():
    plan = evidence(change('docs/guide.md'), change('downloader/downloader.py'),
                    change('TavernofSoul/static/css/search.css'))
    assert plan['plan'] == {'offline': True, 'mysql': False, 'browser': True,
                            'live': False, 'docs': False}
    assert len(plan['paths']) == 3


@pytest.mark.parametrize('status', ['A', 'M', 'D'])
def test_add_modify_delete_are_classified_with_regular_git_and_local_modes(status):
    for mode in ('100644', 0o600, 0o640, 0o664):
        plan = evidence(change('downloader/downloader.py', status, old_mode=mode, new_mode=mode))
        assert plan['plan']['offline'] and not plan['plan']['mysql']


def test_rename_both_endpoints_and_mixed_unknown_changes():
    narrow = evidence(change('harness/workflow.py', 'R', 'harness/triage.py'))
    assert len(narrow['paths']) == 2 and not narrow['plan']['mysql']
    for old, new in [('downloader/downloader.py', 'parser_tidy/main.py'),
                     ('parser_tidy/main.py', 'downloader/downloader.py'),
                     ('docs/guide.md', 'AGENTS.md')]:
        plan = evidence(change(old, 'R', new))
        assert plan['plan']['mysql'] and plan['plan']['live']


@pytest.mark.parametrize('rows', [
    [], [None], [{}], [change('downloader/downloader.py', 'C')],
    [change('downloader/downloader.py', old_mode='100755')],
    [change('downloader/downloader.py', old_mode='120000', new_mode='120000')],
    [change('downloader/downloader.py', old_mode=0o600, new_mode=0o644)],
    [change('downloader/downloader.py', old_mode=True, new_mode=True)],
    [change('downloader/downloader.py'), change('downloader/downloader.py')],
    [change('downloader/../downloader/downloader.py')],
    [change('downloader/downloader.py', 'R', 'downloader/downloader.py')],
])
def test_empty_malformed_type_permission_or_ambiguous_records_fail_closed(rows):
    # Some malformed values are not accepted by the legacy classifier itself;
    # the planner must still retain every execution when given such evidence.
    plan = checks.make_plan({'mode': 'full', 'reason': 'unknown', 'changes': rows}, 'push')
    assert all(plan['plan'][name] for name in checks.EXECUTIONS + ('live',))


@pytest.mark.parametrize('event', ['workflow_dispatch', 'unknown', ''])
def test_manual_and_unknown_events_never_narrow_even_with_prose(event):
    plan = evidence(change('docs/guide.md'), event=event)
    assert all(plan['plan'][name] for name in checks.EXECUTIONS + ('live',))
    assert not plan['plan']['docs']


def test_docs_uses_original_selection_and_positive_zero_skip_report():
    plan = evidence(change('docs/guide.md'))
    selection = docs_check.classify([change('docs/guide.md')])
    assert plan['selection'] == selection
    group = {'status': 'passed', 'selected': 2, 'passed': 2,
             'skipped': [], 'failures': [], 'errors': []}
    report = {'status': 'passed', 'selection': selection, 'checks': {'docs': group}}
    results = dict.fromkeys(checks.EXECUTIONS, 'skipped')
    checks.verify_evidence(plan, results, 'skipped', report)
    for field, value in [('selected', 0), ('selected', True), ('passed', 1),
                         ('skipped', ['test']), ('errors', ['error']), ('failures', ['failure'])]:
        bad = copy.deepcopy(report)
        bad['checks']['docs'][field] = value
        with pytest.raises(ValueError):
            checks.verify_evidence(plan, results, 'skipped', bad)
    for bad in (None, {}, {**report, 'selection': {}}):
        with pytest.raises(ValueError):
            checks.verify_evidence(plan, results, 'skipped', bad)


@pytest.mark.parametrize('name', checks.EXECUTIONS + ('live',))
@pytest.mark.parametrize('actual', ['failure', 'cancelled', 'neutral', 'queued', '', None])
def test_all_execution_results_must_match_plan_exactly(name, actual):
    plan = evidence(change('downloader/downloader.py'))
    results = {'offline': 'success', 'mysql': 'skipped', 'browser': 'skipped'}
    live = actual if name == 'live' else 'skipped'
    if name != 'live':
        results[name] = actual
    with pytest.raises(ValueError):
        checks.verify_evidence(plan, results, live)


def test_selected_skip_and_unselected_success_both_fail():
    plan = evidence(change('downloader/downloader.py'))
    for results in ({'offline': 'skipped', 'mysql': 'skipped', 'browser': 'skipped'},
                    {'offline': 'success', 'mysql': 'success', 'browser': 'skipped'}, {}):
        with pytest.raises(ValueError):
            checks.verify_evidence(plan, results, 'skipped')
    with pytest.raises(ValueError):
        checks.verify_evidence(evidence(change('harness/runner.py')),
                               dict.fromkeys(checks.EXECUTIONS, 'success'), 'skipped')


@pytest.mark.parametrize('mutation', ['version', 'selection', 'plan', 'reason', 'paths', 'boolean'])
def test_missing_tampered_or_nonboolean_plan_is_rejected(mutation):
    plan = evidence(change('downloader/downloader.py'))
    if mutation == 'boolean':
        plan['plan']['offline'] = 1
    else:
        plan.pop(mutation)
    with pytest.raises(ValueError):
        checks.validate_plan(plan)
    plan = evidence(change('harness/runner.py'))
    plan['plan']['mysql'] = False
    with pytest.raises(ValueError):
        checks.validate_plan(plan)


def test_cli_reuses_complete_event_selection_and_writes_separate_plan(tmp_path, monkeypatch):
    event_path = tmp_path / 'event.json'
    event_path.write_text('{"pull_request": {}}')
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(event_path))
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'pull_request')
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'outputs'))
    selection = docs_check.classify([change('downloader/downloader.py')])
    calls = []
    def select(root, name, event):
        calls.append((name, event))
        return selection
    monkeypatch.setattr(docs_check, 'ci_selection', select)
    args = ['--ci', '--selection-file', str(tmp_path / 'selection.json'),
            '--plan-file', str(tmp_path / 'plan.json')]
    assert checks.main(args) == 0
    assert calls == [('pull_request', {'pull_request': {}})]
    assert json.loads((tmp_path / 'selection.json').read_text()) == selection
    assert checks.validate_plan(json.loads((tmp_path / 'plan.json').read_text()))['mysql'] is False
    event_path.write_text('{malformed')
    assert checks.main(args) == 0
    assert checks.validate_plan(json.loads((tmp_path / 'plan.json').read_text()))['mysql'] is True


@pytest.mark.parametrize('text', ['{"plan":{},"plan":{}}', '{"value":NaN}', '{broken'])
def test_malformed_or_ambiguous_json_is_not_plan_evidence(text):
    with pytest.raises(ValueError):
        checks.load_json(text)


def test_verifier_cli_requires_matching_selection_event_and_successful_selection(tmp_path, monkeypatch):
    plan = evidence(change('downloader/downloader.py'))
    selection_file, plan_file = tmp_path / 'selection.json', tmp_path / 'plan.json'
    selection_file.write_text(json.dumps(plan['selection']))
    plan_file.write_text(json.dumps(plan))
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'pull_request')
    monkeypatch.setenv('SELECTION_RESULT', 'success')
    monkeypatch.setenv('EXECUTION_RESULTS', json.dumps({
        'offline': 'success', 'mysql': 'skipped', 'browser': 'skipped'}))
    monkeypatch.setenv('LIVE_RESULT', 'skipped')
    args = ['--verify', '--selection-file', str(selection_file), '--plan-file', str(plan_file)]
    assert checks.main(args) == 0
    for field, value in [('SELECTION_RESULT', 'failure'), ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
                         ('LIVE_RESULT', ''), ('EXECUTION_RESULTS', '{}')]:
        previous = os.environ[field]
        monkeypatch.setenv(field, value)
        with pytest.raises(ValueError):
            checks.main(args)
        monkeypatch.setenv(field, previous)
    selection_file.write_text(json.dumps(docs_check.classify([change('docs/other.md')])))
    with pytest.raises(ValueError, match='match'):
        checks.main(args)
    selection_file.write_text(json.dumps(plan['selection']))
    plan_file.unlink()
    with pytest.raises(OSError):
        checks.main(args)


def test_shared_contract_prose_cannot_take_the_ordinary_prose_shortcut():
    plan = evidence(change('docs/data-contracts.md'))
    assert plan['selection']['mode'] == 'docs'  # Legacy document contract is unchanged.
    assert checks.validate_plan(plan) == {
        'offline': True, 'mysql': True, 'browser': True, 'live': True, 'docs': False}


def test_actual_parser_edit_ignores_read_only_policy_docs_and_other_domain(project):
    (project / 'docs').mkdir()
    (project / 'docs/guide.md').write_text('# Existing\n')
    scope = ['AGENTS.md', 'docs/guide.md', 'downloader/example.py', 'parser_tidy/example.py']
    normal = runner_for([])
    commands = []
    def edit_only_parser(role, task, keys, **options):
        context = options['workspace']
        preserved = {name: (context / name).read_bytes() for name in scope
                     if name != 'parser_tidy/example.py'}
        result = normal(role, task, keys, **options)
        for name, content in preserved.items():
            (context / name).write_bytes(content)
        return result
    def check(*args):
        commands.append(args[1])
        return successful_check(*args)
    report = run_fixture(scope, runner=edit_only_parser, checker=check)
    assert report['status'] == 'passed', report.get('error')
    assert report['changed_files'] == ['parser_tidy/example.py']
    assert commands == ['doctor', 'check-parser']
    assert report['required_checks'] == ['check-parser']
    assert report['validation_selection']['local_checks'] == ['check-parser']
    assert (project / 'AGENTS.md').read_text() == 'Instructions.\n'
    assert (project / 'downloader/example.py').read_text() == 'existing downloader edit\n'


@pytest.mark.parametrize('name', [
    'AGENTS.md', 'docs/workflow.md', 'docs/harness-design.md', 'docs/data-contracts.md', 'Makefile',
    'harness/workflow.py', 'harness/runner.py', 'harness/check_selection.py',
    'downloader/tests/conftest.py', 'parser_tidy/main.py',
    'TavernofSoul/Items/models.py', 'TavernofSoul/TavernofSoul/settings.py',
    'unknown.py',
])
def test_local_policy_contract_harness_and_unknown_always_require_full(name):
    row = {'status': 'M', 'old_path': name, 'new_path': name,
           'old_mode': 0o644, 'new_mode': 0o644}
    assert workflow.round_checks([row], {'role': 'coordinator', 'required_checks': ['check']},
                                 ['check-parser']) == ['check']


def test_local_mode_unknown_empty_and_recommendation_requirements_are_preserved():
    row = {'status': 'M', 'old_path': 'parser_tidy/example.py',
           'new_path': 'parser_tidy/example.py', 'old_mode': 0o644, 'new_mode': 0o644}
    parser = {'role': 'parser', 'required_checks': ['check-parser', 'check-pipeline']}
    assert workflow.round_checks([row], parser, ['check']) == ['check-parser', 'check-pipeline']
    assert workflow.round_checks([{**row, 'new_mode': 0o600}], parser, ['check-parser']) == ['check']
    for unknown in ([{}], None, {}, ''):
        assert workflow.round_checks(unknown, parser, ['check-parser']) == ['check']
    assert workflow.round_checks([], parser, ['check-parser', 'check-pipeline']) == [
        'check-parser', 'check-pipeline']
    contract = {'role': 'coordinator', 'required_checks': ['check'],
                'reasons': ['possible_contract_impact']}
    assert workflow.round_checks([row], contract, ['check-parser']) == ['check']


def test_local_configured_full_subsumes_area_targets(monkeypatch):
    config = agent_models.load_config()
    config['roles']['parser']['check'] = 'check'
    monkeypatch.setattr(agent_models, 'load_config', lambda: config)
    row = {'status': 'M', 'old_path': 'parser_tidy/example.py',
           'new_path': 'parser_tidy/example.py', 'old_mode': 0o644, 'new_mode': 0o644}
    recommendation = {'role': 'parser', 'required_checks': ['check-parser', 'check-pipeline']}
    assert workflow.round_checks([row], recommendation, ['check']) == ['check']


def test_local_coordinator_fallback_retains_additional_recommended_targets():
    row = {'status': 'M', 'old_path': 'parser_tidy/example.py',
           'new_path': 'parser_tidy/example.py', 'old_mode': 0o644, 'new_mode': 0o644}
    recommendation = {'role': 'coordinator', 'required_checks': ['check', 'check-pipeline'],
                      'reasons': ['missing_typesafe_key']}
    assert workflow.round_checks([row], recommendation, ['check']) == ['check-parser', 'check-pipeline']


def test_actual_common_contract_document_uses_full_and_records_local_evidence(project):
    name = 'docs/data-contracts.md'
    (project / 'docs').mkdir()
    (project / name).write_text('# Existing contract\n')
    commands = []
    judgment = {'status': 'updated', 'files': [name],
                'reason': 'The shared contract description changes and requires full validation.'}
    def check(*args):
        commands.append(args[1])
        return successful_check(*args)
    report = run_fixture([name], runner=runner_for([], documentation=judgment), checker=check)
    assert report['status'] == 'passed', report.get('error')
    assert commands == ['doctor', 'check']
    assert report['validation_selection']['mode'] == 'full'
    assert report['validation_selection']['local_checks'] == ['check']
    assert report['delivery_validation'][0]['validation_digest'] == report['validation_selection']['digest']


def test_repair_reclassifies_actual_changes_and_keeps_fresh_final_evidence(project, docs_creation_umask):
    name = 'docs/guide.md'
    (project / 'docs').mkdir()
    (project / name).write_text('# Before\n')
    expected_mode = 0o666 & ~docs_creation_umask
    assert stat.S_IMODE((project / name).stat().st_mode) == expected_mode
    judgment = {'status': 'updated', 'files': [name], 'reason': 'Prose updated alongside the repair.'}
    normal = runner_for([], documentation=judgment)
    rounds = []
    def edit(role, task, keys, **options):
        code = options['workspace'] / 'parser_tidy/example.py'
        previous = code.read_bytes()
        value = normal(role, task, keys, **options)
        if options['write'] and role == 'parser' and len(rounds) == 0:
            code.write_bytes(previous)
        return value
    def check(candidate, command, report_dir, keys, policy):
        rounds.append(command)
        value = successful_check(candidate, command, report_dir, keys, policy)
        if command == 'check-docs':
            value.update(status='failed', exit_code=1, checks={'docs': {
                'status': 'failed', 'selected': 1, 'passed': 0, 'skipped': [],
                'errors': [{'exception_type': 'ValueError'}]}})
        return value
    report = run_fixture([name, 'parser_tidy/example.py'], runner=edit, checker=check)
    # Unknown context conservatively repairs both tasks. The second actual diff
    # includes parser code, so fresh review requires the actual parser target.
    assert report['status'] == 'passed', report.get('error')
    assert rounds == ['check-docs', 'doctor', 'check-parser']
    assert report['repairs'][0]['target_files'] == [name, 'parser_tidy/example.py']
    assert report['required_checks'] == ['check-parser']
    assert [row['command'] for row in report['delivery_validation']] == ['check-parser']
    assert report['validation_selection']['mode'] == 'full'
    assert [row['command'] for row in report['validation']] == ['check-docs', 'check-parser']
    first, final = report['validation']
    assert first['validation_digest'] != report['validation_selection']['digest']
    assert final['validation_digest'] == report['validation_selection']['digest']
    assert report['delivery_validation'] == [final]
    assert stat.S_IMODE((project / name).stat().st_mode) == expected_mode
