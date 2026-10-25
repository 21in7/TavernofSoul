"""Small Python 3.8 stdlib execution plans over complete docs_check evidence.

CI execution plans, local make target selection and suite skip proof share this policy.
Unknown paths and evidence always retain the full CI plan.
"""
import argparse
import json
import os
from pathlib import Path

from harness import docs_check

EXECUTIONS = ('offline', 'mysql', 'browser')
# Existing triage contract path; automatic selection must retain its full gate.
FULL_PATHS = frozenset({'docs/data-contracts.md'})
# These modules orchestrate work; none is a shared test runner or game contract.
ORCHESTRATION = frozenset({
    'harness/workflow.py', 'harness/test_workflow.py',
    'harness/git_publish.py', 'harness/test_git_publish.py',
    'harness/git_cleanup.py', 'harness/triage.py',
})
DOWNLOADER = frozenset({'downloader/downloader.py'})
UI_ROOTS = ('TavernofSoul/templates/', 'TavernofSoul/static/')
STATIC_SUFFIXES = {'.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico'}


def change_paths(changes):
    """Validate every record, both rename endpoints and all permission bits."""
    if not isinstance(changes, list) or not changes:
        return None
    seen, paths = set(), []
    for row in changes:
        if not isinstance(row, dict) or set(row) != {
                'status', 'old_path', 'new_path', 'old_mode', 'new_mode'}:
            return None
        status = row['status']
        if not isinstance(status, str) or status not in ('A', 'M', 'D', 'R'):
            return None
        old, new = row['old_path'], row['new_path']
        a, b = row['old_mode'], row['new_mode']
        def regular(value):
            return type(value) is int and 0 <= value <= 0o777 and not value & 0o111
        expected = {'A': (None, '100644'), 'D': ('100644', None),
                    'M': ('100644', '100644'), 'R': ('100644', '100644')}[status]
        local = ((status == 'A' and a is None and regular(b)) or
                 (status == 'D' and regular(a) and b is None) or
                 (status in ('M', 'R') and regular(a) and regular(b) and a == b))
        if not local and (a, b) != expected:
            return None
        if ((status == 'A' and (old is not None or new is None)) or
                (status == 'D' and (new is not None or old is None)) or
                (status == 'M' and (old is None or old != new)) or
                (status == 'R' and (old is None or new is None or old == new))):
            return None
        endpoints = []
        for name in (old, new):
            if name is None:
                continue
            if (not isinstance(name, str) or not name or '\\' in name or
                    any(ord(c) < 32 for c in name) or
                    any(p in ('', '.', '..') for p in name.split('/'))):
                return None
            if name not in endpoints:
                endpoints.append(name)
        for name in endpoints:
            if name in seen:
                return None
            seen.add(name)
            paths.append(name)
    return paths


def path_class(name):
    if name in FULL_PATHS:
        return 'full'
    if docs_check.prose(name):
        return 'prose'
    if name in DOWNLOADER:
        return 'downloader'
    # Only Python unit tests in the existing downloader regression directory.
    if (name.startswith('downloader/tests/test_') and name.count('/') == 2 and
            name.endswith('.py')):
        return 'downloader'
    if name in ORCHESTRATION:
        return 'orchestration'
    if name.startswith(UI_ROOTS[0]) and name.endswith('.html'):
        return 'ui'
    if name.startswith(UI_ROOTS[1]) and Path(name).suffix.lower() in STATIC_SUFFIXES:
        return 'ui'
    return 'full'


def make_plan(selection, event_name):
    """Keep docs_check's selection/report schema intact inside a separate plan."""
    paths = change_paths(selection.get('changes')) if isinstance(selection, dict) else None
    reasons = [{'path': name, 'classification': path_class(name)} for name in paths or []]
    classes = {row['classification'] for row in reasons}
    plan = dict.fromkeys(EXECUTIONS + ('live',), True)
    plan['docs'] = False
    reason = 'unknown_or_incomplete_evidence'
    if event_name not in ('push', 'pull_request'):
        reason = 'manual_or_unknown_event'
    elif paths and docs_check.classify(selection['changes']) == selection:
        if classes == {'prose'}:
            plan = dict.fromkeys(plan, False)
            plan['docs'] = True
            reason = 'regular_prose_only'
        elif classes <= {'prose', 'downloader', 'orchestration', 'ui'}:
            plan.update(mysql=False, browser='ui' in classes, live=False)
            reason = 'explicit_offline_and_ui_allowlist'
        else:
            reason = 'policy_shared_contract_dependency_or_unknown_path'
    return {'version': 'check-selection-v1', 'event_name': event_name,
            'selection': selection, 'plan': plan, 'reason': reason, 'paths': reasons}


def validate_plan(evidence):
    if not isinstance(evidence, dict) or set(evidence) != {
            'version', 'event_name', 'selection', 'plan', 'reason', 'paths'}:
        raise ValueError('Missing or malformed execution plan.')
    selection = evidence['selection']
    if (not isinstance(evidence['event_name'], str) or not isinstance(selection, dict) or
            set(selection) != {'mode', 'reason', 'changes'} or
            selection.get('mode') not in ('docs', 'full') or
            not isinstance(selection.get('reason'), str) or
            not isinstance(selection.get('changes'), list)):
        raise ValueError('Malformed change selection.')
    try:
        canonical = docs_check.classify(selection['changes'])
    except (TypeError, ValueError):
        raise ValueError('Malformed change records.') from None
    if selection != canonical and selection != {
            'mode': 'full', 'reason': 'unavailable_complete_git_evidence', 'changes': []}:
        raise ValueError('Selection is not complete classifier evidence.')
    plan = evidence['plan']
    if (not isinstance(plan, dict) or set(plan) != set(EXECUTIONS + ('live', 'docs')) or
            any(type(value) is not bool for value in plan.values()) or
            evidence != make_plan(selection, evidence['event_name'])):
        raise ValueError('Execution plan contradicts complete change classification.')
    if plan['live'] and not plan['offline']:
        raise ValueError('Live requires offline execution.')
    return plan


def verify_evidence(evidence, results, live_result, report=None):
    """Every required gate verifies the entire plan, including the live step."""
    plan = validate_plan(evidence)
    if not isinstance(results, dict) or set(results) != set(EXECUTIONS):
        raise ValueError('Incomplete execution results.')
    for name in EXECUTIONS:
        expected = 'success' if plan[name] else 'skipped'
        if results[name] != expected:
            raise ValueError('Execution {} must be {}.'.format(name, expected))
    if live_result != ('success' if plan['live'] else 'skipped'):
        raise ValueError('Live sample execution contradicts the plan.')
    if plan['docs']:
        selection = evidence['selection']
        groups = report.get('checks') if isinstance(report, dict) else None
        if not (isinstance(report, dict) and selection.get('mode') == 'docs' and selection.get('changes') and
                report.get('selection') == selection and report.get('status') == 'passed' and
                isinstance(groups, dict) and groups and all(
                    isinstance(g, dict) and g.get('status') == 'passed' and
                    type(g.get('selected')) is int and g['selected'] > 0 and
                    type(g.get('passed')) is int and g['passed'] == g['selected'] and
                    g.get('skipped') == [] and g.get('failures') == [] and
                    g.get('errors') == [] for g in groups.values())):
            raise ValueError('Required documentation evidence is incomplete.')


def local_checks(changes, recommendation, previous, *, owner, role_check, path_rules):
    """Local targets follow actual writes, never the broader model read scope.

    CI's offline-only orchestration exception does not narrow local harness work.
    An empty/read-only or malformed diff retains the original conservative plan.
    """
    selection = docs_check.classify(changes)
    paths = change_paths(changes)
    if paths and any(name in FULL_PATHS for name in paths):
        return ['check']
    if selection['mode'] == 'docs':
        return ['check-docs']
    if paths is None:
        return previous if isinstance(changes, list) and not changes else ['check']
    code = [name for name in paths if not docs_check.prose(name)]
    # Existing shared/contract rules, plus explicit validation dependencies.
    if any(owner(name) == 'coordinator' or
           Path(name).name in ('AGENTS.md', 'conftest.py', 'requirements.txt',
                               'pytest.ini', 'setup.py', 'pyproject.toml') or
           'settings' in Path(name).stem or '/fixtures/' in name or
           Path(name).suffix not in ('.py', '.html', '.css', '.js') for name in code):
        return ['check']
    rules = path_rules(code)
    if rules['requires_review'] or rules['requires_planning']:
        return ['check']
    # Domain recommendations retain their extra tests. Coordinator planning or
    # key/transport fallback alone is not evidence of changed shared contracts.
    required = set(rules['required_checks'])
    required.update(role_check(owner(name)) for name in code)
    if (recommendation['role'] != 'coordinator' or
            'possible_contract_impact' in recommendation.get('reasons', [])):
        required.update(recommendation['required_checks'])
    else:
        required.update(name for name in recommendation['required_checks'] if name != 'check')
    return ['check'] if 'check' in required else sorted(required)


def ci_skips_proven(skipped, latest, suites, required, selection, executions, suite_id):
    """Prove docs or partial skips through the artifact-validating required gates.

    GitHub check-runs do not carry the artifact itself. All three required jobs
    validate its complete plan and every execution (including offline's live
    step). Their success in this exact suite attests the planned skips; a skip
    alone, or gates from another suite, can never do so.
    """
    success_names = required | {selection}

    def successful(rows):
        return all(rows.get(name, {}).get('status') == 'completed' and
                   rows[name].get('conclusion') == 'success' and
                   suite_id(rows[name]) is not None for name in success_names)

    def complete(rows):
        if not successful(rows) or not all(
                rows.get(name, {}).get('status') == 'completed' and
                rows[name].get('conclusion') in ('success', 'skipped')
                for name in executions):
            return False
        outcomes = {name: rows[name]['conclusion'] for name in executions}
        # Supported plans: docs, full, offline-only, offline + browser.
        if outcomes['Offline execution (SQLite)'] == 'skipped':
            return set(outcomes.values()) == {'skipped'}
        return (outcomes['MySQL execution'] == 'skipped' or
                set(outcomes.values()) == {'success'})

    cohorts = [suites.get(suite_id(row), {}) for row in skipped]
    # Another suite's newer success cannot hide this execution's real failure.
    for cohort in cohorts:
        if any(row.get('status') == 'completed' and row.get('conclusion') != 'success' and
               not (row['name'] in executions and row.get('conclusion') == 'skipped')
               for row in cohort.values()):
            raise ValueError('CI failed, skipped, neutral or cancelled; PR remains unmerged.')
    # Current evidence must itself belong to complete suites. In particular a
    # newer pending or malformed-suite success cannot borrow older gate proof.
    current = [latest.get(name, {}) for name in success_names | executions]
    return (successful(latest) and all(complete(cohort) for cohort in cohorts) and
            all(suite_id(row) is not None and
                complete(suites.get(suite_id(row), {})) for row in current))


def ci_executions_complete(latest, executions, selection):
    # Legacy required-only suites remain compatible; partial evidence must be complete.
    names = executions | {selection}
    return not (set(latest) & names) or names <= set(latest)


def load_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate evidence field.')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Non-finite evidence number.')
    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ci', action='store_true')
    parser.add_argument('--selection-file', type=Path, required=True)
    parser.add_argument('--plan-file', type=Path, required=True)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--docs-report', type=Path)
    args = parser.parse_args(argv)
    if args.verify:
        evidence = load_json(args.plan_file.read_text(encoding='utf-8'))
        validate_plan(evidence)
        if evidence.get('selection') != load_json(args.selection_file.read_text(encoding='utf-8')):
            raise ValueError('Selection artifact does not match the plan.')
        if evidence.get('event_name') != os.environ.get('GITHUB_EVENT_NAME'):
            raise ValueError('Execution plan belongs to another event.')
        if os.environ['SELECTION_RESULT'] != 'success':
            raise ValueError('Change selection or documentation validation failed.')
        report = (load_json(args.docs_report.read_text(encoding='utf-8'))
                  if args.docs_report and args.docs_report.exists() else None)
        verify_evidence(evidence, load_json(os.environ['EXECUTION_RESULTS']),
                        os.environ['LIVE_RESULT'], report)
        return 0
    if not args.ci:
        parser.error('Choose --ci or --verify.')
    event_name = os.environ.get('GITHUB_EVENT_NAME', '')
    try:
        event = load_json(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
        selection = docs_check.ci_selection(Path(__file__).absolute().parents[1], event_name, event)
    except (OSError, ValueError, KeyError):
        selection = {'mode': 'full', 'reason': 'unavailable_complete_git_evidence', 'changes': []}
    evidence = make_plan(selection, event_name)
    validate_plan(evidence)
    args.selection_file.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    args.plan_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as handle:
            for name, value in evidence['plan'].items():
                handle.write('{}={}\n'.format('docs_only' if name == 'docs' else name,
                                               'true' if value else 'false'))
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
