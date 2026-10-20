"""GitHub delivery gates and real checkout preservation, without network calls."""
import copy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import shutil

import pytest

from harness import agent_models, git_publish as delivery, storage, workflow, workspace

BASE, TREE, NEW_TREE, HEAD, MERGE, TEST_MERGE = [char * 40 for char in 'abcdef']
DETAILS = {'commit_message': 'Correct fixture behavior', 'pr_title': 'Correct fixture behavior',
           'pr_body': 'Preserve the task scope. Validation: offline checks passed.'}


@pytest.fixture(autouse=True)
def isolated_storage_environment(monkeypatch):
    # Tests must never consult a host's explicitly selected private storage.
    monkeypatch.delenv(storage.CONFIG_ENV, raising=False)
    monkeypatch.delenv(storage.REPORT_ENV, raising=False)


def git(root, *args):
    return subprocess.run(['git', *args], cwd=str(root), check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith(('GIT_', 'SSH_', 'GCM_')) or key in (
                'READ_ONLY', 'GIT', 'TAVERN_WORKFLOW_CHILD', 'GH_TOKEN', 'GITHUB_TOKEN', 'EMAIL'):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / 'git-home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home))
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_TERMINAL_PROMPT', '0')
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', 'file')
    root = tmp_path / 'project'
    root.mkdir()
    git(root, 'init', '--template=', '-q')
    git(root, 'symbolic-ref', 'HEAD', 'refs/heads/master')
    git(root, 'remote', 'add', 'origin', 'https://github.com/21in7/TavernofSoul.git')
    for name, content in {'edit.py': 'before\n', 'delete.py': 'delete before\n',
                          'unrelated.py': 'user change\n', '.gitignore': '/logs/\n'}.items():
        (root / name).write_text(content)
    git(root, 'add', 'unrelated.py')
    index_before = (root / '.git/index').read_bytes()
    status_before = git(root, 'diff', '--cached', '--binary')
    policy = workflow.load_policy()
    directory = root / 'logs/harness/workflows/123456-abcdef'
    candidate = directory / 'workspace'
    scope = ['edit.py', 'delete.py', 'new.py']
    baseline = workspace.copy_validation_sources(root, candidate, scope, policy)
    (candidate / 'edit.py').write_text('after\n')
    (candidate / 'edit.py').chmod(0o755)
    (candidate / 'delete.py').unlink()
    (candidate / 'new.py').write_text('새 파일\n')
    (candidate / 'new.py').chmod(0o755)
    validated = workspace.manifest(candidate, policy)
    changes = workspace.changed(baseline, validated)
    workspace.publish(root, candidate, baseline, validated, changes, scope, directory / 'backup', policy)
    report = {'run_id': directory.name, 'scope': scope, 'workspace': str(candidate),
              'read_only': False, 'simulated': False, 'changed_files': changes,
              'review': {'verdict': 'approved'}, 'validation': [{
                  'command': 'check', 'status': 'passed', 'exit_code': 0,
                  'checks': {'offline': {'status': 'passed', 'selected': 1, 'passed': 1,
                                         'skipped': [], 'errors': [], 'failures': []}}}]}
    agent_models.private_json(directory / 'report.json', report)
    delivery.prepare(root, directory, report, baseline, validated, changes, policy, DETAILS)
    ledger = json.loads((directory / 'github.json').read_text())
    monkeypatch.setattr(delivery, 'ROOT', root)
    monkeypatch.setattr(delivery, 'REPORTS', directory.parent)
    return {'root': root, 'directory': directory, 'ledger': ledger, 'baseline': baseline,
            'validated': validated, 'changes': changes, 'report': report, 'policy': policy,
            'index_before': index_before, 'staged_before': status_before}


def to_tree(ledger, corrupt=None):
    delivery.accept(ledger, {'full_name': ledger['config']['repository'], 'archived': False,
                            'permissions': {'push': True}, 'allow_squash_merge': True})
    delivery.accept(ledger, {'ref': 'refs/heads/master', 'object': {'type': 'commit', 'sha': BASE}})
    delivery.accept(ledger, {'sha': BASE, 'tree': {'sha': TREE}})
    rows = [{'path': name, 'type': 'blob', **entry['before']} for name, entry in ledger['files'].items()
            if entry['before']]
    if corrupt:
        corrupt(rows)
    delivery.accept(ledger, {'sha': TREE, 'truncated': False, 'tree': rows})


def to_pr(ledger):
    to_tree(ledger)
    delivery.accept(ledger, {'sha': NEW_TREE})
    delivery.accept(ledger, {'sha': HEAD})
    delivery.accept(ledger, {'ref': 'refs/heads/' + ledger['branch'],
                            'object': {'type': 'commit', 'sha': HEAD}})
    delivery.accept(ledger, {'structuredContent': {'pull_request': {'number': 11, 'url': 'unused'}}})


def pr_data(ledger, **extra):
    repo = {'full_name': ledger['config']['repository']}
    return {'head': {'ref': ledger['branch'], 'sha': HEAD, 'repo': repo},
            'base': {'ref': 'master', 'sha': BASE, 'repo': repo}, 'draft': False,
            'state': 'open', 'merged': False, 'mergeable': True,
            'mergeable_state': 'clean', 'merge_commit_sha': None, **extra}


def rows_for(ledger, sha=HEAD, **extra):
    return [{'id': i + 1, 'name': name, 'head_sha': sha, 'app': {'slug': 'github-actions'},
             'status': 'completed', 'conclusion': 'success', **extra}
            for i, name in enumerate(ledger['config']['required_checks'])]


def check_response(rows):
    return {'check_runs': rows, 'total_count': len(rows)}


@pytest.fixture
def ci_ledger():
    """Fixed connector journal: no Git, configuration reads or network needed."""
    return {'config': {'version': 'github-v1', 'enabled': True,
                       'repository': '21in7/TavernofSoul', 'base': 'master',
                       'merge_method': 'squash', 'check_app': 'github-actions',
                       'required_checks': ['Offline harness (SQLite)', 'MySQL harness',
                                           'Chromium browser harness'], 'wait_seconds': 1800},
            'step': 'pr', 'status': 'awaiting_connector', 'events': [],
            'base_sha': BASE, 'head_sha': HEAD, 'branch': 'codex/123456-abcdef',
            'pr_number': 11, 'deadline': 10 ** 20}


def docs_rows_for(sha=HEAD, suite=101, first_id=1):
    # REST ordering observed in docs CI: skips are visible before the final gates.
    names = ['Offline execution (SQLite)', 'MySQL execution', 'Chromium browser execution',
             'Select actual change validation', 'Offline harness (SQLite)',
             'MySQL harness', 'Chromium browser harness']
    return [{'id': first_id + i, 'name': name, 'head_sha': sha,
             'app': {'slug': 'github-actions'}, 'check_suite': {'id': suite},
             'status': 'completed', 'conclusion': 'skipped' if i < 3 else 'success'}
            for i, name in enumerate(names)]


def test_docs_skips_wait_for_real_gates_then_merge_and_fresh_cleanup(ci_ledger):
    ledger = ci_ledger
    for phase in ('missing', 'selection_pending', 'queued', 'in_progress'):
        delivery.accept(ledger, pr_data(ledger))
        rows = docs_rows_for()
        if phase == 'missing':
            rows = rows[:3]
        elif phase == 'selection_pending':
            rows = rows[:4]
            rows[3].update(status='in_progress', conclusion=None)
        else:
            for row in rows[4:]:
                row.update(status=phase, conclusion=None)
        delivery.accept(ledger, check_response(rows))
        assert ledger['step'] == 'pr' and ledger['status'] == 'waiting_for_ci'
        assert not ledger.get('merge_sha')
        assert delivery.request(ledger)['arguments']['url'].endswith('/pulls/11')
    delivery.accept(ledger, pr_data(ledger))
    delivery.accept(ledger, check_response(docs_rows_for()))
    assert ledger['step'] == 'statuses' and ledger['check_sha'] == HEAD
    assert set(ledger['checks'].values()) == {'success'}
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    assert ledger['step'] == 'final_pr'
    delivery.accept(ledger, pr_data(ledger))
    assert delivery.request(ledger)['arguments']['expected_head_sha'] == HEAD
    delivery.accept(ledger, {'merged': True, 'sha': MERGE})
    assert ledger['step'] == 'cleanup_pr' and ledger['cleanup_proof'] == {}
    delivery.accept(ledger, cleanup_pr_data(ledger))
    # Fresh checks are collected again, including all pages, before proof exists.
    rows = docs_rows_for(suite=202, first_id=101)
    delivery.accept(ledger, {'check_runs': rows[:3], 'total_count': len(rows)})
    assert ledger['step'] == 'cleanup_checks' and ledger['cleanup_page'] == 2
    assert 'checks' not in ledger['cleanup_proof']
    assert delivery.request(ledger)['arguments']['url'].endswith('page=2')
    delivery.accept(ledger, {'check_runs': rows[3:], 'total_count': len(rows)})
    assert ledger['step'] == 'cleanup_statuses'
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    delivery.accept(ledger, {'full_name': ledger['config']['repository'], 'default_branch': 'master'})
    delivery.accept(ledger, [])
    delivery.accept(ledger, [])
    assert ledger['step'] == 'cleanup_execute' and ledger['cleanup_proof']['verified'] is True
    assert ledger['cleanup_proof']['check_sha'] == HEAD and ledger['merge_sha'] == MERGE
    # Verified API proof permits the existing parent cleanup, not a fixture claim
    # that branch transport/deletion or operational cleanup has happened.
    assert not delivery.cleanup_complete(ledger)


@pytest.mark.parametrize('head_only', [False, True])
def test_docs_pagination_and_test_merge_priority(ci_ledger, head_only):
    ledger = ci_ledger
    delivery.accept(ledger, pr_data(ledger, merge_commit_sha=TEST_MERGE))
    head = docs_rows_for() if head_only else []
    delivery.accept(ledger, check_response(head))
    assert TEST_MERGE in delivery.request(ledger)['arguments']['url']
    rows = [] if head_only else docs_rows_for(sha=TEST_MERGE)
    if rows:
        delivery.accept(ledger, {'check_runs': rows[:3], 'total_count': len(rows)})
        assert ledger['step'] == 'merge_checks' and ledger['page'] == 2
        delivery.accept(ledger, {'check_runs': rows[3:], 'total_count': len(rows)})
    else:
        delivery.accept(ledger, check_response([]))
    assert ledger['step'] == 'statuses'
    assert ledger['check_sha'] == (HEAD if head_only else TEST_MERGE)
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    assert TEST_MERGE in delivery.request(ledger)['arguments']['url']
    delivery.accept(ledger, {'sha': TEST_MERGE, 'total_count': 0})
    delivery.accept(ledger, pr_data(ledger, merge_commit_sha=TEST_MERGE))
    assert ledger['step'] == 'merge'


@pytest.mark.parametrize('phase', ['pre_merge', 'cleanup'])
def test_docs_head_success_cannot_fill_test_merge_gates(ci_ledger, phase):
    ledger = ci_ledger
    if phase == 'pre_merge':
        delivery.accept(ledger, pr_data(ledger, merge_commit_sha=TEST_MERGE))
    else:
        ledger.update(step='merge', test_merge_sha=TEST_MERGE)
        delivery.accept(ledger, {'merged': True, 'sha': MERGE})
        delivery.accept(ledger, cleanup_pr_data(ledger))
    delivery.accept(ledger, check_response(docs_rows_for()))
    assert TEST_MERGE in delivery.request(ledger)['arguments']['url']
    rows = docs_rows_for(sha=TEST_MERGE)[:3]
    if phase == 'pre_merge':
        delivery.accept(ledger, check_response(rows))
        assert ledger['step'] == 'pr' and ledger['status'] == 'waiting_for_ci'
    else:
        with pytest.raises(ValueError, match='Fresh pinned CI'):
            delivery.accept(ledger, check_response(rows))
        assert ledger['merge_sha'] == MERGE and not delivery.cleanup_complete(ledger)
        assert 'checks' not in ledger['cleanup_proof']


@pytest.mark.parametrize('head_only', [False, True])
def test_docs_cleanup_retains_test_merge_priority_and_both_statuses(ci_ledger, head_only):
    ledger = ci_ledger
    ledger.update(step='merge', test_merge_sha=TEST_MERGE)
    delivery.accept(ledger, {'merged': True, 'sha': MERGE})
    delivery.accept(ledger, cleanup_pr_data(ledger))
    delivery.accept(ledger, check_response(docs_rows_for()))
    delivery.accept(ledger, check_response([] if head_only else docs_rows_for(sha=TEST_MERGE)))
    assert ledger['cleanup_proof']['check_sha'] == (HEAD if head_only else TEST_MERGE)
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    assert TEST_MERGE in delivery.request(ledger)['arguments']['url']
    delivery.accept(ledger, {'sha': TEST_MERGE, 'total_count': 0})
    assert ledger['step'] == 'cleanup_repository' and ledger['merge_sha'] == MERGE


@pytest.mark.parametrize('target,conclusion', [
    *[(4, value) for value in ('skipped', 'neutral', 'failure', 'cancelled',
                               'timed_out', 'action_required')],
    (3, 'failure'), (0, 'failure'), (0, 'neutral'), (0, 'cancelled'),
])
def test_docs_real_non_success_is_never_hidden(ci_ledger, target, conclusion):
    rows = docs_rows_for()
    rows[target]['conclusion'] = conclusion
    delivery.accept(ci_ledger, pr_data(ci_ledger))
    with pytest.raises(ValueError, match='CI failed'):
        delivery.accept(ci_ledger, check_response(rows))
    assert ci_ledger['step'] != 'merge'


def test_docs_unknown_skip_fails_even_before_gates_arrive(ci_ledger):
    rows = docs_rows_for()[:3]
    rows.append({**rows[0], 'id': 99, 'name': 'Unexpected execution'})
    with pytest.raises(ValueError, match='CI failed'):
        delivery.checks_gate(rows, ci_ledger['config'], HEAD)


@pytest.mark.parametrize('kind', [
    'required_missing', 'selection_missing', 'selection_pending', 'selection_wrong_app',
    'required_wrong_app', 'heavy_wrong_app',
    'extra_pending', 'heavy_missing', 'suite_mismatch', 'mixed_required_suites',
    'old_suite_pending', 'latest_required_pending',
    'latest_selection_pending', 'latest_heavy_pending',
])
def test_docs_incomplete_or_mixed_evidence_waits(ci_ledger, kind):
    rows = docs_rows_for()
    if kind == 'required_missing':
        rows.pop()
    elif kind == 'selection_missing':
        rows.pop(3)
    elif kind == 'selection_pending':
        rows[3].update(status='in_progress', conclusion=None)
    elif kind.endswith('_wrong_app'):
        index = {'selection_wrong_app': 3, 'required_wrong_app': 4, 'heavy_wrong_app': 0}[kind]
        rows[index]['app'] = {'slug': 'other-app'}
    elif kind == 'extra_pending':
        rows.append({**rows[3], 'id': 99, 'name': 'Extra job', 'status': 'queued', 'conclusion': None})
    elif kind == 'heavy_missing':
        rows.pop(2)
    elif kind == 'suite_mismatch':
        rows[3]['check_suite'] = {'id': 202}
    elif kind == 'mixed_required_suites':
        for i, row in enumerate(rows[4:]):
            row['check_suite'] = {'id': 202 + i}
    elif kind == 'old_suite_pending':
        # A newer success in another suite must not repair this skip's suite.
        old = copy.deepcopy(rows[4])
        rows[4].update(status='in_progress', conclusion=None)
        rows.append({**old, 'id': 99, 'check_suite': {'id': 202}})
    else:
        index = {'latest_required_pending': 4, 'latest_selection_pending': 3,
                 'latest_heavy_pending': 0}[kind]
        rows.append({**rows[index], 'id': 99, 'status': 'queued', 'conclusion': None})
    delivery.accept(ci_ledger, pr_data(ci_ledger))
    delivery.accept(ci_ledger, check_response(list(reversed(rows))))
    assert ci_ledger['step'] == 'pr' and ci_ledger['status'] == 'waiting_for_ci'


@pytest.mark.parametrize('target,suite', [
    *[(0, value) for value in (None, {}, [], 'invalid', {'id': True}, {'id': '101'},
                               {'id': 0}, {'id': -1}, {'id': None}, {'id': []})],
    (3, {'id': True}), (4, {'id': True}),
])
def test_docs_malformed_suite_never_proves_exception(ci_ledger, target, suite):
    rows = docs_rows_for()
    rows[target]['check_suite'] = suite
    assert delivery.checks_gate(rows, ci_ledger['config'], HEAD)[0] is False


def test_docs_missing_suite_never_proves_exception(ci_ledger):
    rows = docs_rows_for()
    for row in rows:
        row.pop('check_suite')
    assert delivery.checks_gate(rows, ci_ledger['config'], HEAD)[0] is False


@pytest.mark.parametrize('target', [3, 4])
@pytest.mark.parametrize('suite', [None, {'id': True}, {'id': '101'}])
def test_docs_latest_success_with_invalid_suite_cannot_reuse_old_proof(ci_ledger, target, suite):
    rows = docs_rows_for()
    # The original suite is complete, but the current result cannot be assigned
    # to a suite. Its older success must not supply the missing metadata.
    rows.append({**rows[target], 'id': 99, 'check_suite': suite})
    delivery.accept(ci_ledger, pr_data(ci_ledger))
    delivery.accept(ci_ledger, check_response(list(reversed(rows))))
    assert ci_ledger['status'] == 'waiting_for_ci' and ci_ledger['step'] == 'pr'
    assert not ci_ledger.get('merge_sha')


@pytest.mark.parametrize('target', [0, 3, 4])
def test_docs_stale_sha_is_rejected(ci_ledger, target):
    rows = docs_rows_for()
    rows[target]['head_sha'] = TEST_MERGE
    with pytest.raises(ValueError, match='stale'):
        delivery.checks_gate(rows, ci_ledger['config'], HEAD)


@pytest.mark.parametrize('target', [0, 3, 4])
def test_docs_latest_failure_wins_across_suites(ci_ledger, target):
    rows = docs_rows_for()
    rows.append({**rows[target], 'id': 99, 'check_suite': {'id': 202}, 'conclusion': 'failure'})
    with pytest.raises(ValueError, match='CI failed'):
        delivery.checks_gate(list(reversed(rows)), ci_ledger['config'], HEAD)


def test_docs_suite_latest_pending_cannot_use_older_success(ci_ledger):
    rows = docs_rows_for()
    # Global success is newer still, but the skip's own suite now has pending CI.
    rows += [{**rows[4], 'id': 50, 'status': 'queued', 'conclusion': None},
             {**rows[4], 'id': 99, 'check_suite': {'id': 202}}]
    assert delivery.checks_gate(list(reversed(rows)), ci_ledger['config'], HEAD)[0] is False


def test_docs_suite_latest_failure_cannot_use_other_suite_success(ci_ledger):
    rows = docs_rows_for()
    rows += [{**rows[4], 'id': 50, 'conclusion': 'failure'},
             {**rows[4], 'id': 99, 'check_suite': {'id': 202}}]
    with pytest.raises(ValueError, match='CI failed'):
        delivery.checks_gate(list(reversed(rows)), ci_ledger['config'], HEAD)


def test_docs_two_complete_suites_do_not_require_interleaved_names_to_match(ci_ledger):
    first, second = docs_rows_for(), docs_rows_for(suite=202, first_id=101)
    # Push and PR suites are independently complete; latest names can interleave.
    first[0]['id'] = 201
    first[3]['id'] = 202
    assert delivery.checks_gate(first + second, ci_ledger['config'], HEAD)[0] is True


def test_full_and_legacy_ci_remain_successful_without_suite_proof(ci_ledger):
    legacy = rows_for(ci_ledger)
    assert delivery.checks_gate(legacy, ci_ledger['config'], HEAD)[0] is True
    full = docs_rows_for()
    for row in full:
        row['conclusion'] = 'success'
        row.pop('check_suite')
    assert delivery.checks_gate(full, ci_ledger['config'], HEAD)[0] is True


@pytest.mark.parametrize('kind', ['pending', 'malformed_suite', 'latest_malformed_suite',
                                 'failure', 'wrong_sha'])
def test_docs_cleanup_rejects_incomplete_fresh_proof_and_keeps_merge(ci_ledger, kind):
    ledger = ci_ledger
    # Pre-merge success must never substitute for the new cleanup read.
    delivery.accept(ledger, pr_data(ledger))
    delivery.accept(ledger, check_response(docs_rows_for()))
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    delivery.accept(ledger, pr_data(ledger))
    delivery.accept(ledger, {'merged': True, 'sha': MERGE})
    delivery.accept(ledger, cleanup_pr_data(ledger))
    rows = docs_rows_for()
    if kind == 'pending':
        rows[4].update(status='in_progress', conclusion=None)
    elif kind == 'malformed_suite':
        rows[3]['check_suite'] = {'id': True}
    elif kind == 'latest_malformed_suite':
        rows.append({**rows[3], 'id': 99, 'check_suite': {'id': True}})
    elif kind == 'failure':
        rows[0]['conclusion'] = 'failure'
    else:
        rows[3]['head_sha'] = TEST_MERGE
    with pytest.raises(ValueError):
        delivery.accept(ledger, check_response(rows))
    assert ledger['merge_sha'] == MERGE and ledger['merge_status'] == 'merged'
    assert not delivery.cleanup_complete(ledger) and 'checks' not in ledger['cleanup_proof']


def test_docs_cleanup_resume_collects_new_proof_after_early_skips(ci_ledger):
    ledger = ci_ledger
    ledger['step'] = 'merge'
    delivery.accept(ledger, {'merged': True, 'sha': MERGE})
    delivery.accept(ledger, cleanup_pr_data(ledger))
    # main accepts into a copy and retains the original journal on failure.
    with pytest.raises(ValueError, match='Fresh pinned CI'):
        delivery.accept(copy.deepcopy(ledger), check_response(docs_rows_for()[:3]))
    assert ledger['merge_sha'] == MERGE and not delivery.cleanup_complete(ledger)
    assert 'checks' not in ledger['cleanup_proof']
    # The existing resume boundary starts a completely fresh proof collection.
    delivery.begin_cleanup(ledger)
    assert ledger['cleanup_proof'] == {} and ledger['merge_sha'] == MERGE
    delivery.accept(ledger, cleanup_pr_data(ledger))
    delivery.accept(ledger, check_response(docs_rows_for(suite=303, first_id=201)))
    assert ledger['step'] == 'cleanup_statuses'
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    delivery.accept(ledger, {'full_name': ledger['config']['repository'], 'default_branch': 'master'})
    delivery.accept(ledger, [])
    delivery.accept(ledger, [])
    assert ledger['step'] == 'cleanup_execute' and ledger['cleanup_proof']['verified'] is True
    assert ledger['merge_sha'] == MERGE and not delivery.cleanup_complete(ledger)


def test_delivery_requests_only_task_changes_and_preserves_real_index(prepared):
    item, ledger = prepared, prepared['ledger']
    to_tree(ledger)
    job = delivery.request(ledger)
    assert job['tool'] == delivery.TOOLS['create_tree']
    elements = {row['path']: row for row in job['arguments']['tree_elements']}
    assert set(elements) == {'edit.py', 'delete.py', 'new.py'}
    assert elements['edit.py']['mode'] == '100755' and elements['edit.py']['content'] == 'after\n'
    assert elements['delete.py']['sha'] is None
    assert elements['new.py']['content'] == '새 파일\n'
    assert elements['new.py']['mode'] == '100755'
    assert job['arguments']['base_tree_sha'] == TREE
    assert (item['root'] / '.git/index').read_bytes() == item['index_before']
    assert git(item['root'], 'diff', '--cached', '--binary') == item['staged_before']
    assert (item['root'] / 'unrelated.py').read_text() == 'user change\n'
    assert (item['directory'] / 'github.json').stat().st_mode & 0o777 == 0o600


def test_full_connector_flow_requires_ci_and_pins_merge_head(prepared):
    ledger = prepared['ledger']
    to_pr(ledger)
    assert ledger['pr_url'] == 'https://github.com/21in7/TavernofSoul/pull/11'
    delivery.accept(ledger, pr_data(ledger))
    delivery.accept(ledger, check_response(rows_for(ledger)))
    assert ledger['step'] == 'statuses'
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0, 'state': 'pending'})
    delivery.accept(ledger, pr_data(ledger))
    job = delivery.request(ledger)
    assert job['tool'] == delivery.TOOLS['merge_pull_request']
    assert job['arguments']['expected_head_sha'] == HEAD
    assert job['arguments']['merge_method'] == 'squash'
    delivery.accept(ledger, {'merged': True, 'sha': MERGE})
    delivery.save(prepared['directory'], ledger)
    job = delivery.request(ledger)
    assert job['tool'] == delivery.TOOLS['fetch']
    assert job['arguments']['url'].endswith('/pulls/11')
    assert ledger['merge_status'] == 'merged' and ledger['merge_sha'] == MERGE
    assert ledger['step'] == 'cleanup_pr'
    assert json.loads((prepared['directory'] / 'report.json').read_text())['status'] == 'awaiting_github'


def test_native_branch_snapshot_requires_a_pinned_ref_read_before_pr(prepared):
    ledger = prepared['ledger']
    to_tree(ledger)
    delivery.accept(ledger, {'sha': NEW_TREE})
    delivery.accept(ledger, {'sha': HEAD})
    delivery.request(ledger)
    delivery.accept(ledger, {'structuredContent': {'branch': ledger['branch']}})
    assert ledger['step'] == 'branch_ref' and not ledger.get('pending_write')
    job = delivery.request(ledger)
    assert job['tool'] == delivery.TOOLS['fetch']
    assert job['arguments']['url'].endswith('/git/ref/heads/' + ledger['branch'])
    assert ledger['pending_write'] is False
    delivery.accept(ledger, {'ref': 'refs/heads/' + ledger['branch'],
                            'object': {'type': 'commit', 'sha': HEAD}})
    assert delivery.request(ledger)['tool'] == delivery.TOOLS['create_pull_request']


@pytest.mark.parametrize('change', [
    {'ref': 'refs/heads/wrong'}, {'object': {'sha': BASE}}, {'object': None},
    {'branch': 'codex/other'},
])
def test_native_branch_confirmation_rejects_moved_or_missing_head(prepared, change):
    ledger = prepared['ledger']
    to_tree(ledger)
    delivery.accept(ledger, {'sha': NEW_TREE})
    delivery.accept(ledger, {'sha': HEAD})
    delivery.accept(ledger, {'branch': ledger['branch']})
    response = {'ref': 'refs/heads/' + ledger['branch'],
                'object': {'type': 'commit', 'sha': HEAD}}
    if 'branch' in change:
        response = change
    else:
        response.update(change)
    with pytest.raises(ValueError):
        delivery.accept(ledger, response)
    assert ledger['step'] == 'branch_ref'


def native_branch_cli(prepared, capsys):
    ledger = prepared['ledger']
    to_tree(ledger)
    delivery.accept(ledger, {'sha': NEW_TREE})
    delivery.accept(ledger, {'sha': HEAD})
    agent_models.private_json(prepared['directory'] / 'github.json', ledger)
    assert delivery.main(['request', '--run-id', ledger['run_id']]) == 0
    return json.loads(capsys.readouterr().out)['request']


def native_branch_reply(prepared, capsys, job, data, code=0):
    assert delivery.main(['accept', '--run-id', prepared['ledger']['run_id'],
                          '--request-id', job['request_id'], '--response-json', json.dumps(data)]) == code
    return json.loads(capsys.readouterr().out)


def test_native_branch_cli_confirms_head_before_requesting_pr(prepared, capsys):
    ledger = prepared['ledger']
    write = native_branch_cli(prepared, capsys)
    output = native_branch_reply(prepared, capsys, write, {'branch': ledger['branch']})
    query = output['request']
    assert query['tool'] == delivery.TOOLS['fetch']
    assert query['request_id'] != write['request_id']
    saved = json.loads((prepared['directory'] / 'github.json').read_text())
    assert saved['step'] == 'branch_ref' and saved['pending_write'] is False
    assert saved['pending_request_id'] == query['request_id']
    assert json.loads((prepared['directory'] / 'report.json').read_text())['status'] == 'awaiting_github'
    output = native_branch_reply(prepared, capsys, query,
                                 {'ref': 'refs/heads/' + ledger['branch'],
                                  'object': {'type': 'commit', 'sha': HEAD}})
    assert output['request']['tool'] == delivery.TOOLS['create_pull_request']
    saved = json.loads((prepared['directory'] / 'github.json').read_text())
    assert saved['step'] == 'create_pr' and saved['pending_write'] is True


@pytest.mark.parametrize('response', [{'branch': 'wrong'}, {'branch': None}, {}])
def test_native_branch_cli_keeps_ambiguous_write_nonce_for_late_confirmation(prepared, capsys, response):
    ledger = prepared['ledger']
    write = native_branch_cli(prepared, capsys)
    output = native_branch_reply(prepared, capsys, write, response, code=1)
    assert output['github']['status'] == 'needs_reconciliation' and output['request'] is None
    saved = json.loads((prepared['directory'] / 'github.json').read_text())
    assert saved['step'] == 'branch' and saved['pending_write'] is True
    assert saved['status'] == 'needs_reconciliation'
    assert saved['pending_request_id'] == write['request_id']
    assert json.loads((prepared['directory'] / 'report.json').read_text())['status'] == 'needs_reconciliation'
    output = native_branch_reply(prepared, capsys, write, {'branch': ledger['branch']})
    assert output['github']['step'] == 'branch_ref'
    assert output['request']['tool'] == delivery.TOOLS['fetch']


@pytest.mark.parametrize('change', [
    {'ref': 'refs/heads/wrong'}, {'object': {'type': 'commit', 'sha': BASE}},
    {'omit_ref': True}, {'object': {'type': 'commit'}},
    {'object': {'type': 'tree', 'sha': HEAD}}, {'object': {'type': 'tag', 'sha': HEAD}},
    {'object': {'type': 'blob', 'sha': HEAD}}, {'object': {'sha': HEAD}}, {'object': None},
])
def test_native_branch_cli_journals_unverified_refs_without_reissuing_write(prepared, capsys, change):
    ledger = prepared['ledger']
    write = native_branch_cli(prepared, capsys)
    output = native_branch_reply(prepared, capsys, write, {'branch': ledger['branch']})
    query = output['request']
    response = {'ref': 'refs/heads/' + ledger['branch'], 'object': {'type': 'commit', 'sha': HEAD}}
    if change.get('omit_ref'):
        response.pop('ref')
    else:
        response.update(change)
    output = native_branch_reply(prepared, capsys, query, response, code=1)
    assert output['github']['status'] == 'failed' and output['request'] is None
    saved = json.loads((prepared['directory'] / 'github.json').read_text())
    assert saved['step'] == 'branch_ref' and saved['pending_write'] is False
    assert saved['status'] == 'failed'
    assert saved['pending_request_id'] == query['request_id']
    assert json.loads((prepared['directory'] / 'report.json').read_text())['status'] == 'failed'


def test_native_branch_cli_rejects_old_read_nonce_and_accepts_current_ref(prepared, capsys):
    ledger = prepared['ledger']
    write = native_branch_cli(prepared, capsys)
    first = native_branch_reply(prepared, capsys, write, {'branch': ledger['branch']})['request']
    assert delivery.main(['request', '--run-id', ledger['run_id']]) == 0
    current = json.loads(capsys.readouterr().out)['request']
    assert current['request_id'] != first['request_id']
    ref = {'ref': 'refs/heads/' + ledger['branch'], 'object': {'type': 'commit', 'sha': HEAD}}
    native_branch_reply(prepared, capsys, first, ref, code=1)
    saved = json.loads((prepared['directory'] / 'github.json').read_text())
    assert saved['pending_request_id'] == current['request_id'] and saved['pending_write'] is False
    output = native_branch_reply(prepared, capsys, current, ref)
    assert output['request']['tool'] == delivery.TOOLS['create_pull_request']


@pytest.mark.parametrize('corruption', ['sha', 'mode', 'missing', 'new_exists'])
def test_remote_dirty_or_untracked_baseline_stops_before_any_write(prepared, corruption):
    def corrupt(rows):
        if corruption == 'sha':
            rows[0]['sha'] = '0' * 40
        elif corruption == 'mode':
            rows[0]['mode'] = '100755'
        elif corruption == 'missing':
            rows.clear()
        else:
            rows.append({'path': 'new.py', 'sha': HEAD, 'mode': '100644', 'type': 'blob'})
    with pytest.raises(ValueError, match='baseline differs'):
        to_tree(prepared['ledger'], corrupt)
    assert prepared['ledger']['step'] == 'base_tree'
    assert not prepared['ledger'].get('head_sha')


@pytest.mark.parametrize('conclusion', ['failure', 'skipped', 'neutral', 'cancelled', 'timed_out', 'action_required'])
def test_no_merge_for_unsuccessful_ci(prepared, conclusion):
    ledger = prepared['ledger']
    to_pr(ledger)
    delivery.accept(ledger, pr_data(ledger))
    with pytest.raises(ValueError, match='CI failed'):
        delivery.accept(ledger, check_response(rows_for(ledger, conclusion=conclusion)))
    assert ledger['step'] != 'merge'


@pytest.mark.parametrize('kind', ['missing', 'wrong_app', 'in_progress', 'extra_pending', 'empty'])
def test_required_checks_cannot_be_bypassed(prepared, kind):
    ledger = prepared['ledger']
    to_pr(ledger)
    delivery.accept(ledger, pr_data(ledger, mergeable_state='blocked'))
    rows = rows_for(ledger)
    if kind == 'missing':
        rows.pop()
    elif kind == 'wrong_app':
        rows[0]['app'] = {'slug': 'other-app'}
    elif kind == 'in_progress':
        rows[0].update(status='in_progress', conclusion=None)
    elif kind == 'extra_pending':
        rows.append({**rows[0], 'id': 99, 'name': 'Additional workflow', 'status': 'queued', 'conclusion': None})
    else:
        rows = []
    delivery.accept(ledger, check_response(rows))
    assert ledger['status'] == 'waiting_for_ci' and ledger['step'] == 'pr'
    assert delivery.request(ledger)['tool'] == delivery.TOOLS['fetch']


def test_merge_commit_checks_take_precedence_and_cover_all_pages(prepared):
    ledger = prepared['ledger']
    to_pr(ledger)
    delivery.accept(ledger, pr_data(ledger, merge_commit_sha=TEST_MERGE))
    delivery.accept(ledger, check_response(rows_for(ledger)))
    assert TEST_MERGE in delivery.request(ledger)['arguments']['url']
    rows = rows_for(ledger, sha=TEST_MERGE)
    delivery.accept(ledger, {'check_runs': rows[:1], 'total_count': 3})
    assert ledger['page'] == 2 and ledger['step'] == 'merge_checks'
    delivery.accept(ledger, {'check_runs': rows[1:], 'total_count': 3})
    assert ledger['check_sha'] == TEST_MERGE and ledger['step'] == 'statuses'


def test_latest_recheck_failure_wins_over_old_success(prepared):
    ledger = prepared['ledger']
    rows = rows_for(ledger)
    rows.append({**rows[0], 'id': 99, 'conclusion': 'failure'})
    with pytest.raises(ValueError, match='CI failed'):
        delivery.checks_gate(rows, ledger['config'], HEAD)


@pytest.mark.parametrize('kind', ['head', 'base', 'repository', 'draft', 'conflict', 'closed'])
def test_changed_pr_stops_merge(prepared, kind):
    ledger = prepared['ledger']
    to_pr(ledger)
    data = copy.deepcopy(pr_data(ledger))
    if kind in ('head', 'base'):
        data[kind]['sha'] = '0' * 40
    elif kind == 'repository':
        data['head']['repo']['full_name'] = 'other/repo'
    elif kind == 'draft':
        data['draft'] = True
    elif kind == 'conflict':
        data['mergeable_state'] = 'dirty'
    else:
        data['state'] = 'closed'
    with pytest.raises(ValueError):
        delivery.accept(ledger, data)
    assert ledger['step'] != 'merge'


def test_review_and_validation_are_required_before_publication(prepared):
    item = prepared
    report = {**item['report'], 'review': {'verdict': 'changes_requested'}}
    with pytest.raises(ValueError, match='Approved review'):
        delivery.prepare(item['root'], item['directory'], report, item['baseline'], item['validated'],
                         item['changes'], item['policy'], DETAILS)
    report.update(review={'verdict': 'approved'}, validation=[{'status': 'failed'}])
    with pytest.raises(ValueError, match='Approved review'):
        delivery.prepare(item['root'], item['directory'], report, item['baseline'], item['validated'],
                         item['changes'], item['policy'], DETAILS)


@pytest.mark.parametrize('kind', ['empty', 'skipped', 'zero_selected', 'missing_passed', 'nonzero_exit'])
def test_publication_rejects_status_only_or_incomplete_local_coverage(prepared, kind):
    item = prepared
    report = copy.deepcopy(item['report'])
    check = report['validation'][0]
    group = check['checks']['offline']
    if kind == 'empty':
        check['checks'] = {}
    elif kind == 'skipped':
        group['skipped'] = ['required case']
    elif kind == 'zero_selected':
        group.update(selected=0, passed=0)
    elif kind == 'missing_passed':
        group.pop('passed')
    else:
        check['exit_code'] = 1
    with pytest.raises(ValueError, match='successful local checks'):
        delivery.prepare(item['root'], item['directory'], report, item['baseline'], item['validated'],
                         item['changes'], item['policy'], DETAILS)


def test_deadline_keeps_pr_and_resume_does_not_repeat_publication(prepared, monkeypatch, capsys):
    ledger = prepared['ledger']
    to_pr(ledger)
    ledger['deadline'] = 0
    assert delivery.request(ledger) is None and ledger['status'] == 'awaiting_ci'
    delivery.save(prepared['directory'], ledger)
    assert delivery.main(['resume', '--run-id', ledger['run_id']]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['github']['pr_number'] == 11 and output['github']['status'] == 'awaiting_connector'
    assert output['request']['tool'] == delivery.TOOLS['fetch']
    assert output['request']['arguments']['url'].endswith('/pulls/11')


def test_cli_correlates_responses_and_rejects_replay(prepared, capsys):
    run_id = prepared['ledger']['run_id']
    assert delivery.main(['request', '--run-id', run_id]) == 0
    first = json.loads(capsys.readouterr().out)
    payload = json.dumps({'structuredContent': {'content': json.dumps({
        'full_name': '21in7/TavernofSoul', 'archived': False,
        'permissions': {'push': True}, 'allow_squash_merge': True})}})
    args = ['accept', '--run-id', run_id, '--request-id', first['request']['request_id'],
            '--response-json', payload]
    assert delivery.main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second['github']['step'] == 'base_ref'
    assert delivery.main(args) == 1
    capsys.readouterr()
    saved = json.loads((prepared['directory'] / 'github.json').read_text())
    assert saved['step'] == 'base_ref'


def test_metadata_cannot_control_repository_or_commands():
    assert delivery.metadata(json.dumps(DETAILS)) == DETAILS
    for data in ({**DETAILS, 'repository': 'other/repo'}, {**DETAILS, 'pr_title': 'two\nlines'},
                 {**DETAILS, 'pr_body': ''}, {**DETAILS, 'commit_message': 'x' * 2001}):
        with pytest.raises(ValueError):
            delivery.metadata(json.dumps(data))


@pytest.mark.parametrize('field,value', [('required_checks', []), ('required_checks', [{}]),
                                       ('wait_seconds', True), ('wait_seconds', 1801),
                                       ('base', '../master'), ('base', '-master'),
                                       ('merge_method', 'rebase'), ('repository', 'https://github.com/x/y')])
def test_invalid_delivery_policy_is_rejected(field, value):
    cfg = delivery.load_config()
    cfg[field] = value
    with pytest.raises(ValueError):
        delivery.validate_config(cfg)


def test_failed_connector_result_cannot_advance_delivery(prepared, capsys):
    run_id = prepared['ledger']['run_id']
    delivery.main(['request', '--run-id', run_id])
    job = json.loads(capsys.readouterr().out)['request']
    assert delivery.main(['accept', '--run-id', run_id, '--request-id', job['request_id'],
                          '--response-json', '{"isError":true}']) == 1
    output = json.loads(capsys.readouterr().out)
    assert output['github']['status'] == 'failed' and output['request'] is None
    assert json.loads((prepared['directory'] / 'report.json').read_text())['status'] == 'failed'


@pytest.mark.parametrize('kind', ['extra_file', 'hash', 'protected', 'branch', 'matching_hash', 'mode', 'permissions'])
def test_tampered_journal_cannot_generate_connector_requests(prepared, capsys, kind):
    ledger = prepared['ledger']
    if kind == 'extra_file':
        ledger['files']['outside.py'] = ledger['files']['edit.py']
    elif kind == 'hash':
        ledger['files']['edit.py']['after']['content'] = 'different content'
    elif kind == 'protected':
        ledger['files']['.agent-keys.json'] = ledger['files'].pop('edit.py')
    elif kind == 'matching_hash':
        ledger['files']['edit.py']['after'].update(content='changed', sha=delivery.blob_sha(b'changed'))
    elif kind == 'mode':
        ledger['files']['edit.py']['after']['mode'] = '100644'
    elif kind == 'permissions':
        pass
    else:
        ledger['branch'] = 'master'
    agent_models.private_json(prepared['directory'] / 'github.json', ledger)
    if kind == 'permissions':
        (prepared['directory'] / 'github.json').chmod(0o644)
    assert delivery.main(['request', '--run-id', ledger['run_id']]) == 1
    assert 'request' not in json.loads(capsys.readouterr().out)


class DeliveryStorageFS(storage.FileSystem):
    """Only the fixture mount exists; no host mount table or network is used."""
    def __init__(self, mount):
        self.mount = mount
        self.ready = True
        self.free = 1024 * 1024
        self.writable = True

    def mount_ready(self, path):
        return self.ready and path == self.mount

    def free_bytes(self, path):
        assert path == self.mount
        return self.free

    def probe(self, path):
        if not self.writable:
            raise PermissionError('synthetic private probe failure')
        return super().probe(path)


@pytest.fixture
def configured_delivery(prepared, tmp_path, monkeypatch):
    mount = tmp_path / 'delivery-mount'
    mount.mkdir()
    fs = DeliveryStorageFS(mount)
    config = {'version': 1, 'artifacts': {
        'path': str(mount / 'artifacts'), 'required_mount': str(mount), 'min_free_bytes': 4096},
        'temporary': {
            'path': str(mount / 'temporary'), 'required_mount': str(mount), 'min_free_bytes': 4096}}
    agent_models.private_json(prepared['root'] / 'logs/harness/storage-local.json', config)
    # Resolve against the patched caller ROOT at operation time, with a fake FS.
    monkeypatch.setattr(delivery, 'storage_policy', lambda: storage.resolve_storage(
        delivery.ROOT, env={}, fs=fs))
    monkeypatch.setattr(workflow, 'ROOT', prepared['root'])
    monkeypatch.setattr(workflow, 'REPORTS', prepared['directory'].parent)
    monkeypatch.setattr(workflow, 'storage_policy', lambda: storage.resolve_storage(
        workflow.ROOT, env={}, fs=fs))
    return {**prepared, 'fs': fs, 'storage': delivery.storage_policy()}


def journal_at(item, placement):
    """Build an independent synthetic new journal; never rebase legacy approval."""
    if placement == 'legacy':
        return item['directory'], copy.deepcopy(item['ledger'])
    selected = item['storage']
    parent = selected.ensure_directory(selected.artifact_root / 'workflows')
    directory = parent / '654321-fedcba'
    shutil.copytree(item['directory'], directory)
    report = json.loads((directory / 'report.json').read_text())
    report.update(run_id=directory.name, workspace=str(directory / 'workspace'))
    approval = json.loads((directory / 'github-approved.json').read_text())
    approval.update(run_id=directory.name, workspace=report['workspace'])
    ledger = copy.deepcopy(item['ledger'])
    ledger.update(run_id=directory.name, branch='codex/' + directory.name)
    agent_models.private_json(directory / 'report.json', report)
    agent_models.private_json(directory / 'github-approved.json', approval)
    agent_models.private_json(directory / 'github.json', ledger)
    return directory, ledger


@pytest.mark.parametrize('placement', ['legacy', 'configured'])
@pytest.mark.parametrize('command', ['request', 'accept', 'resume', 'cleanup'])
def test_storage_cli_locates_journals_without_rewriting_approval(
        configured_delivery, capsys, placement, command):
    item = configured_delivery
    historical_approval = (item['directory'] / 'github-approved.json').read_bytes()
    directory, ledger = journal_at(item, placement)
    approval_before = (directory / 'github-approved.json').read_bytes()
    workspace_before = json.loads((directory / 'report.json').read_text())['workspace']
    args = [command, '--run-id', ledger['run_id']]
    if command == 'accept':
        assert delivery.main(['request', '--run-id', ledger['run_id']]) == 0
        job = json.loads(capsys.readouterr().out)['request']
        args += ['--request-id', job['request_id'], '--response-json', json.dumps({
            'full_name': ledger['config']['repository'], 'archived': False,
            'permissions': {'push': True}, 'allow_squash_merge': True})]
    elif command == 'resume':
        to_pr(ledger)
        ledger['deadline'] = 0
        assert delivery.request(ledger) is None
        agent_models.private_json(directory / 'github.json', ledger)
    elif command == 'cleanup':
        start_cleanup(ledger)
        ledger.update(step='done', status='merged')
        agent_models.private_json(directory / 'github.json', ledger)
    assert delivery.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['request']['tool'] == delivery.TOOLS['fetch']
    if command == 'cleanup':
        assert output['github']['step'] == 'cleanup_pr'
        assert output['github']['merge_sha'] == MERGE
    elif command == 'resume':
        assert output['request']['arguments']['url'].endswith('/pulls/11')
    assert delivery.directory_for(ledger['run_id']) == directory
    assert (directory / 'github-approved.json').read_bytes() == approval_before
    assert (item['directory'] / 'github-approved.json').read_bytes() == historical_approval
    assert json.loads((directory / 'report.json').read_text())['workspace'] == workspace_before
    assert (directory / 'github.json').stat().st_mode & 0o777 == 0o600
    assert (directory / 'github.lock').stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    local_lock = item['root'] / 'logs/harness/workflows/.lock'
    assert local_lock.stat().st_mode & 0o777 == 0o600
    assert not (item['storage'].artifact_root / 'workflows/.lock').exists()
    if placement == 'legacy':
        assert not (item['storage'].artifact_root / 'workflows' / ledger['run_id']).exists()


@pytest.mark.parametrize('command', ['request', 'accept', 'resume', 'cleanup'])
def test_duplicate_storage_ids_fail_before_locks_or_journal_writes(configured_delivery, capsys, command):
    item = configured_delivery
    parent = item['storage'].ensure_directory(item['storage'].artifact_root / 'workflows')
    shutil.copytree(item['directory'], parent / item['directory'].name)
    journal_before = (item['directory'] / 'github.json').read_bytes()
    assert delivery.main([command, '--run-id', item['directory'].name]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output['error_type'] == 'StorageError' and 'Ambiguous' in output['error']
    assert (item['directory'] / 'github.json').read_bytes() == journal_before
    assert not (item['directory'] / 'github.lock').exists()


@pytest.mark.parametrize('run_id', ['../123456-abcdef', '/123456-abcdef', '123456-ABCDEF', ''])
def test_storage_invalid_run_ids_fail_without_writes(prepared, capsys, run_id):
    assert delivery.main(['request', '--run-id', run_id]) == 1
    assert 'request' not in json.loads(capsys.readouterr().out)
    assert not (prepared['directory'] / 'github.lock').exists()


@pytest.mark.parametrize('placement', ['legacy', 'configured'])
@pytest.mark.parametrize('unsafe', ['run', 'root', 'report.json', 'github.json',
                                    'github-approved.json', 'github.lock', 'events.jsonl',
                                    'workspace', 'backup'])
def test_storage_symlink_paths_fail_closed(configured_delivery, capsys, placement, unsafe):
    item = configured_delivery
    directory, ledger = journal_at(item, placement)
    if unsafe == 'run':
        path = directory
    elif unsafe == 'root':
        path = directory.parent
    else:
        path = directory / unsafe
    target = path.with_name(path.name + '-original')
    if path.exists():
        path.rename(target)
    else:
        target.write_text('do not alter\n')
    path.symlink_to(target, target_is_directory=target.is_dir())
    target_before = target.read_bytes() if target.is_file() else None
    assert delivery.main(['request', '--run-id', ledger['run_id']]) == 1
    assert 'request' not in json.loads(capsys.readouterr().out)
    if target_before is not None:
        assert target.read_bytes() == target_before


@pytest.mark.parametrize('failure', ['absent_mount', 'below_floor', 'unwritable'])
def test_configured_storage_failure_never_falls_back_to_legacy_journal(configured_delivery, capsys, failure):
    item = configured_delivery
    if failure == 'absent_mount':
        item['fs'].ready = False
    elif failure == 'below_floor':
        item['fs'].free = 0
    else:
        item['fs'].writable = False
    before = (item['directory'] / 'github.json').read_bytes()
    assert delivery.main(['request', '--run-id', item['directory'].name]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output['error_type'] == 'StorageError' and output['error']
    assert (item['directory'] / 'github.json').read_bytes() == before
    assert not (item['directory'] / 'github.lock').exists()
    assert not (item['directory'].parent / '.lock').exists()
    if failure != 'unwritable':
        assert not item['storage'].artifact_root.exists()
        assert not item['storage'].temp_root.exists()


def test_explicit_missing_storage_config_reports_safe_error(prepared, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(storage.CONFIG_ENV, str(tmp_path / 'missing-private-config.json'))
    assert delivery.main(['request', '--run-id', prepared['directory'].name]) == 1
    output = json.loads(capsys.readouterr().out)
    assert 'Explicit HARNESS_STORAGE_CONFIG is missing' in output['error']
    assert str(tmp_path) not in output['error']
    assert not (prepared['directory'] / 'github.lock').exists()


@pytest.mark.parametrize('placement', ['legacy', 'configured'])
def test_workflow_and_delivery_share_local_lock_across_storage_changes(
        configured_delivery, capsys, placement):
    item = configured_delivery
    directory, ledger = journal_at(item, placement)
    selected = item['storage']
    legacy_policy = storage.Storage(root=item['root'], env={})
    assert workflow.storage_policy().project_lock_path == selected.project_lock_path
    assert legacy_policy.project_lock_path == selected.project_lock_path
    before = (directory / 'github.json').read_bytes()
    with legacy_policy.project_lock_path.open('a') as controller:
        fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A controller that started with local defaults keeps this same inode.
        assert delivery.storage_policy().project_lock_path == legacy_policy.project_lock_path
        assert delivery.main(['request', '--run-id', ledger['run_id']]) == 1
        assert 'request' not in json.loads(capsys.readouterr().out)
    assert (directory / 'github.json').read_bytes() == before
    assert not (directory / 'github.lock').exists()


@pytest.mark.parametrize('placement', ['legacy', 'configured'])
def test_per_journal_lock_remains_alongside_selected_journal(configured_delivery, capsys, placement):
    directory, ledger = journal_at(configured_delivery, placement)
    with (directory / 'github.lock').open('a') as controller:
        fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = (directory / 'github.json').read_bytes()
        assert delivery.main(['request', '--run-id', ledger['run_id']]) == 1
        assert 'request' not in json.loads(capsys.readouterr().out)
        assert (directory / 'github.json').read_bytes() == before


@pytest.mark.parametrize('placement', ['legacy', 'configured'])
def test_cleanup_execution_receives_selected_journal_and_storage_guard(
        configured_delivery, monkeypatch, capsys, placement):
    item = configured_delivery
    directory, ledger = journal_at(item, placement)
    approval_before = (directory / 'github-approved.json').read_bytes()
    start_cleanup(ledger)
    cleanup_to_branches(ledger)
    delivery.accept(ledger, [])
    assert ledger['step'] == 'cleanup_open_prs'
    agent_models.private_json(directory / 'github.json', ledger)
    assert delivery.main(['request', '--run-id', ledger['run_id']]) == 0
    job = json.loads(capsys.readouterr().out)['request']
    received = []
    def cleanup(root, selected_directory, accepted, report, approval, *, storage_guard):
        storage_guard()
        assert accepted['cleanup_proof']['verified'] is True
        assert accepted['head_sha'] == HEAD and accepted['merge_sha'] == MERGE
        received.append((root, selected_directory, approval['workspace']))
        return {'version': 'cleanup-v1', 'status': 'complete',
                'remote': {'status': 'absent'}, 'local': {'status': 'absent'},
                'prune': {'status': 'complete'}, 'sync': {'status': 'complete'},
                'completion': {'status': 'complete'}}
    # No Git cleanup transport runs: only the verified boundary is observed.
    monkeypatch.setattr(delivery.git_cleanup, 'execute', cleanup)
    assert delivery.main(['accept', '--run-id', ledger['run_id'],
                          '--request-id', job['request_id'], '--response-json', '[]']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['github']['cleanup']['status'] == 'complete'
    assert received == [(item['root'], directory, str(directory / 'workspace'))]
    assert (directory / 'github-approved.json').read_bytes() == approval_before


def test_cleanup_rechecks_storage_before_durable_checkpoint(configured_delivery):
    item = configured_delivery
    directory, ledger = journal_at(item, 'configured')
    approval = json.loads((directory / 'github-approved.json').read_text())
    report = json.loads((directory / 'report.json').read_text())
    def guard():
        item['storage'].record_path(directory, 'cleanup.json', local_default=delivery.local_reports())
    cleanup = delivery.git_cleanup.Cleanup(item['root'], directory, ledger, report, approval,
                                          storage_guard=guard)
    cleanup.checkpoint('proof', 'pending', 'synthetic_test')
    checkpoint_before = (directory / 'cleanup.json').read_bytes()
    item['fs'].ready = False
    with pytest.raises(storage.StorageError, match='mount is absent'):
        cleanup.checkpoint('proof', 'pending', 'synthetic_after_unmount')
    assert (directory / 'cleanup.json').read_bytes() == checkpoint_before
    delivery.execute_cleanup(directory, ledger)
    assert ledger['status'] == 'cleanup_pending'
    assert (directory / 'cleanup.json').read_bytes() == checkpoint_before


@pytest.mark.parametrize('placement', ['legacy', 'configured'])
def test_storage_workspace_escape_is_rejected_without_rewriting_approval(
        configured_delivery, capsys, placement):
    directory, ledger = journal_at(configured_delivery, placement)
    report = json.loads((directory / 'report.json').read_text())
    approval = json.loads((directory / 'github-approved.json').read_text())
    report['workspace'] = approval['workspace'] = str(directory.parent / 'outside-workspace')
    agent_models.private_json(directory / 'report.json', report)
    agent_models.private_json(directory / 'github-approved.json', approval)
    before = (directory / 'github-approved.json').read_bytes()
    assert delivery.main(['request', '--run-id', ledger['run_id']]) == 1
    assert 'request' not in json.loads(capsys.readouterr().out)
    assert (directory / 'github-approved.json').read_bytes() == before


def test_configured_journal_preserves_ci_and_expected_merge_sha(configured_delivery, capsys):
    directory, ledger = journal_at(configured_delivery, 'configured')
    to_pr(ledger)
    delivery.accept(ledger, pr_data(ledger))
    delivery.accept(ledger, check_response(rows_for(ledger)))
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0, 'state': 'pending'})
    delivery.accept(ledger, pr_data(ledger))
    agent_models.private_json(directory / 'github.json', ledger)
    assert delivery.main(['request', '--run-id', ledger['run_id']]) == 0
    job = json.loads(capsys.readouterr().out)['request']
    assert job['tool'] == delivery.TOOLS['merge_pull_request']
    assert job['arguments']['expected_head_sha'] == HEAD
    assert job['arguments']['merge_method'] == 'squash'
    assert set(ledger['checks']) == delivery.REQUIRED
    assert set(ledger['checks'].values()) == {'success'}


def test_root_only_seam_and_report_override_do_not_hide_local_history(prepared, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(delivery, 'REPORTS', delivery._DEFAULT_REPORTS)
    monkeypatch.setenv(storage.REPORT_ENV, str(tmp_path / 'new-reports'))
    assert delivery.directory_for(prepared['directory'].name) == prepared['directory']
    assert delivery.main(['request', '--run-id', prepared['directory'].name]) == 0
    assert json.loads(capsys.readouterr().out)['request']['tool'] == delivery.TOOLS['fetch']
    assert not (tmp_path / 'new-reports').exists()


def test_pending_repository_rules_and_unknown_mergeability_keep_pr_open(prepared):
    ledger = prepared['ledger']
    to_pr(ledger)
    delivery.accept(ledger, pr_data(ledger, mergeable_state='blocked'))
    delivery.accept(ledger, check_response(rows_for(ledger)))
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    delivery.accept(ledger, pr_data(ledger, mergeable=None, mergeable_state='unknown'))
    assert ledger['status'] == 'waiting_for_ci' and ledger['step'] == 'pr'


@pytest.mark.parametrize('kind', ['stale', 'truncated', 'status_failure', 'merge_failure'])
def test_incomplete_or_unsuccessful_remote_validation_stops_delivery(prepared, kind):
    ledger = prepared['ledger']
    if kind == 'truncated':
        ledger.update(step='base_tree', base_tree=TREE, tree_queue=[{'sha': TREE, 'prefix': ''}])
        with pytest.raises(ValueError):
            delivery.accept(ledger, {'sha': TREE, 'truncated': True, 'tree': []})
        return
    to_pr(ledger)
    delivery.accept(ledger, pr_data(ledger))
    rows = rows_for(ledger)
    if kind == 'stale':
        rows[0]['head_sha'] = '0' * 40
        with pytest.raises(ValueError):
            delivery.accept(ledger, check_response(rows))
        return
    delivery.accept(ledger, check_response(rows))
    if kind == 'status_failure':
        with pytest.raises(ValueError):
            delivery.accept(ledger, {'sha': HEAD, 'total_count': 1, 'state': 'failure'})
        return
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    delivery.accept(ledger, pr_data(ledger))
    with pytest.raises(ValueError):
        delivery.accept(ledger, {'merged': False})
    assert ledger['status'] != 'merged'


def test_baseline_fetches_only_directories_containing_task_files(prepared):
    ledger = prepared['ledger']
    entry = ledger['files']['edit.py']
    ledger['files'] = {'harness/edit.py': entry}
    delivery.accept(ledger, {'full_name': ledger['config']['repository'], 'archived': False,
                            'permissions': {'push': True}, 'allow_squash_merge': True})
    delivery.accept(ledger, {'ref': 'refs/heads/master', 'object': {'type': 'commit', 'sha': BASE}})
    delivery.accept(ledger, {'sha': BASE, 'tree': {'sha': TREE}})
    job = delivery.request(ledger)
    assert job['arguments']['url'].endswith('/git/trees/' + TREE)
    assert 'recursive' not in job['arguments']['url']
    delivery.accept(ledger, {'sha': TREE, 'truncated': False, 'tree': [
        {'path': 'harness', 'type': 'tree', 'sha': NEW_TREE, 'mode': '040000'},
        {'path': 'large_game_data', 'type': 'tree', 'sha': MERGE, 'mode': '040000'}]})
    assert delivery.request(ledger)['arguments']['url'].endswith('/git/trees/' + NEW_TREE)
    delivery.accept(ledger, {'sha': NEW_TREE, 'truncated': False, 'tree': [
        {'path': 'edit.py', 'type': 'blob', **entry['before']},
        {'path': 'unrelated.py', 'type': 'blob', 'sha': MERGE, 'mode': '100644'}]})
    assert ledger['step'] == 'tree'
    assert set(ledger['remote_entries']) == {'harness/edit.py'}


@pytest.mark.parametrize('step', ['pr', 'head_checks', 'statuses', 'final_pr'])
def test_same_poll_step_uses_new_nonce_and_rejects_old_response(prepared, capsys, step):
    ledger = prepared['ledger']
    to_pr(ledger)
    ledger.update(step=step, page=1, status_queue=[HEAD])
    first = delivery.request(ledger)
    # Complete an intervening response and return to the same read step.
    ledger.pop('pending_request_id')
    ledger.pop('pending_write')
    second = delivery.request(ledger)
    assert first['tool'] == second['tool'] and first['arguments'] == second['arguments']
    assert first['request_id'] != second['request_id']
    agent_models.private_json(prepared['directory'] / 'github.json', ledger)
    assert delivery.main(['accept', '--run-id', ledger['run_id'], '--request-id', first['request_id'],
                          '--response-json', json.dumps(pr_data(ledger))]) == 1
    capsys.readouterr()
    saved = json.loads((prepared['directory'] / 'github.json').read_text())
    assert saved['pending_request_id'] == second['request_id'] and saved['step'] == step


def test_duplicate_pages_cannot_hide_a_failed_check(prepared):
    ledger = prepared['ledger']
    to_pr(ledger)
    delivery.accept(ledger, pr_data(ledger))
    rows = rows_for(ledger)
    delivery.accept(ledger, {'check_runs': rows[:2], 'total_count': 3})
    with pytest.raises(ValueError, match='Duplicate'):
        delivery.accept(ledger, {'check_runs': rows[1:2], 'total_count': 3})
    assert ledger['step'] == 'head_checks'


@pytest.mark.parametrize('failing_sha', [HEAD, TEST_MERGE])
def test_head_and_test_merge_statuses_both_block_failure(prepared, failing_sha):
    ledger = prepared['ledger']
    to_pr(ledger)
    delivery.accept(ledger, pr_data(ledger, merge_commit_sha=TEST_MERGE))
    delivery.accept(ledger, check_response(rows_for(ledger)))
    delivery.accept(ledger, check_response(rows_for(ledger, sha=TEST_MERGE)))
    assert '/commits/' + HEAD + '/status' in delivery.request(ledger)['arguments']['url']
    if failing_sha == TEST_MERGE:
        delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
        assert TEST_MERGE in delivery.request(ledger)['arguments']['url']
    with pytest.raises(ValueError, match='status failed'):
        delivery.accept(ledger, {'sha': failing_sha, 'total_count': 1, 'state': 'failure'})


def test_changed_test_merge_sha_requires_fresh_ci_before_merge(prepared):
    ledger = prepared['ledger']
    to_pr(ledger)
    delivery.accept(ledger, pr_data(ledger, merge_commit_sha=TEST_MERGE))
    delivery.accept(ledger, check_response(rows_for(ledger)))
    delivery.accept(ledger, check_response(rows_for(ledger, sha=TEST_MERGE)))
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    delivery.accept(ledger, {'sha': TEST_MERGE, 'total_count': 0})
    delivery.accept(ledger, pr_data(ledger, merge_commit_sha=NEW_TREE))
    assert ledger['step'] == 'pr' and ledger['status'] == 'waiting_for_ci'


def test_pending_write_cannot_be_dispatched_twice_and_late_response_can_confirm_it(prepared, capsys):
    ledger = prepared['ledger']
    to_tree(ledger)
    agent_models.private_json(prepared['directory'] / 'github.json', ledger)
    assert delivery.main(['request', '--run-id', ledger['run_id']]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first['request']['tool'] == delivery.TOOLS['create_tree']
    assert delivery.main(['request', '--run-id', ledger['run_id']]) == 1
    blocked = json.loads(capsys.readouterr().out)
    assert blocked['request'] is None and blocked['github']['status'] == 'needs_reconciliation'
    assert delivery.main(['accept', '--run-id', ledger['run_id'],
                          '--request-id', first['request']['request_id'],
                          '--response-json', json.dumps({'sha': NEW_TREE})]) == 0
    confirmed = json.loads(capsys.readouterr().out)
    assert confirmed['github']['step'] == 'commit'
    assert confirmed['request']['tool'] == delivery.TOOLS['create_commit']


@pytest.mark.parametrize('write', [False, True])
def test_response_file_failure_is_journaled_and_never_reissues_a_write(prepared, capsys, write):
    ledger = prepared['ledger']
    if write:
        to_tree(ledger)
    agent_models.private_json(prepared['directory'] / 'github.json', ledger)
    delivery.main(['request', '--run-id', ledger['run_id']])
    first = json.loads(capsys.readouterr().out)
    assert delivery.main(['accept', '--run-id', ledger['run_id'],
                          '--request-id', first['request']['request_id'],
                          '--response-file', str(prepared['directory'] / 'missing-response.json')]) == 1
    output = json.loads(capsys.readouterr().out)
    expected = 'needs_reconciliation' if write else 'failed'
    assert output['github']['status'] == expected and output['request'] is None
    assert json.loads((prepared['directory'] / 'report.json').read_text())['status'] == expected


@pytest.mark.parametrize('object_value', [None, [], 1, 'invalid'])
def test_malformed_branch_response_preserves_nonce_and_records_ambiguous_write(prepared, capsys, object_value):
    ledger = prepared['ledger']
    to_tree(ledger)
    delivery.accept(ledger, {'sha': NEW_TREE})
    delivery.accept(ledger, {'sha': HEAD})
    agent_models.private_json(prepared['directory'] / 'github.json', ledger)
    delivery.main(['request', '--run-id', ledger['run_id']])
    job = json.loads(capsys.readouterr().out)['request']
    assert job['tool'] == delivery.TOOLS['create_branch']
    result = {'ref': 'refs/heads/' + ledger['branch'], 'object': object_value}
    assert delivery.main(['accept', '--run-id', ledger['run_id'], '--request-id', job['request_id'],
                          '--response-json', json.dumps(result)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output['github']['status'] == 'needs_reconciliation' and output['request'] is None
    saved = json.loads((prepared['directory'] / 'github.json').read_text())
    assert saved['step'] == 'branch' and saved['pending_request_id'] == job['request_id']
    assert saved['pending_write'] is True


@pytest.mark.parametrize('kind', ['permissions', 'ref', 'tree_entry', 'head', 'base_repo', 'check_app'])
def test_other_malformed_nested_objects_fail_closed(prepared, kind):
    ledger = prepared['ledger']
    if kind == 'permissions':
        data = {'full_name': ledger['config']['repository'], 'archived': False,
                'permissions': None, 'allow_squash_merge': True}
    elif kind == 'ref':
        ledger['step'] = 'base_ref'
        data = {'ref': 'refs/heads/master', 'object': None}
    elif kind == 'tree_entry':
        ledger.update(step='base_tree', tree_queue=[{'sha': TREE, 'prefix': ''}])
        data = {'sha': TREE, 'truncated': False, 'tree': [None]}
    else:
        to_pr(ledger)
        data = pr_data(ledger)
        if kind == 'head':
            data['head'] = None
        elif kind == 'base_repo':
            data['base']['repo'] = None
        else:
            delivery.accept(ledger, data)
            rows = rows_for(ledger)
            rows[0]['app'] = None
            data = check_response(rows)
    with pytest.raises(ValueError, match='malformed object'):
        delivery.accept(ledger, data)


def start_cleanup(ledger):
    to_pr(ledger)
    ledger.update(step='merge')
    delivery.accept(ledger, {'merged': True, 'sha': MERGE})


def cleanup_pr_data(ledger, **extra):
    return pr_data(ledger, number=11, state='closed', merged=True,
                   merge_commit_sha=MERGE, **extra)


def cleanup_to_repository(ledger):
    delivery.accept(ledger, cleanup_pr_data(ledger))
    delivery.accept(ledger, check_response(rows_for(ledger)))
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    assert ledger['step'] == 'cleanup_repository'


def cleanup_to_branches(ledger):
    cleanup_to_repository(ledger)
    delivery.accept(ledger, {'full_name': ledger['config']['repository'], 'default_branch': 'master'})
    assert ledger['step'] == 'cleanup_branches'


@pytest.mark.parametrize('data', [
    {'full_name': 'other/repository', 'default_branch': 'master'},
    {'full_name': '21in7/TavernofSoul'},
    {'full_name': '21in7/TavernofSoul', 'default_branch': 'codex/123456-abcdef'},
])
def test_cleanup_requires_fresh_repository_and_preserves_default_branch(prepared, data):
    ledger = prepared['ledger']
    start_cleanup(ledger)
    cleanup_to_repository(ledger)
    assert delivery.request(ledger)['arguments']['url'] == \
        'https://api.github.com/repos/' + ledger['config']['repository']
    with pytest.raises(ValueError):
        delivery.accept(ledger, data)
    assert ledger['merge_sha'] == MERGE and ledger['step'] == 'cleanup_repository'


@pytest.mark.parametrize('name', ['report.json', 'github-approved.json'])
def test_cleanup_input_read_failure_keeps_confirmed_merge_pending(prepared, name):
    ledger = prepared['ledger']
    start_cleanup(ledger)
    ledger['step'] = 'cleanup_execute'
    (prepared['directory'] / name).write_text('{invalid')
    delivery.execute_cleanup(prepared['directory'], ledger)
    assert ledger['merge_sha'] == MERGE and ledger['merge_status'] == 'merged'
    assert ledger['status'] == ledger['cleanup']['status'] == 'cleanup_pending'
    assert not delivery.cleanup_complete(ledger)


def test_post_merge_base_advancement_is_normal_and_identity_is_pinned(prepared):
    ledger = prepared['ledger']
    start_cleanup(ledger)
    data = cleanup_pr_data(ledger)
    data['base']['sha'] = MERGE
    delivery.accept(ledger, data)
    assert ledger['step'] == 'cleanup_checks'
    assert ledger['cleanup_proof']['merge_sha'] == MERGE


@pytest.mark.parametrize('field', ['head_sha', 'head_ref', 'head_repo', 'base_ref', 'base_repo', 'merge_sha', 'merged'])
def test_post_merge_identity_changes_fail_closed(prepared, field):
    ledger = prepared['ledger']
    start_cleanup(ledger)
    data = cleanup_pr_data(ledger)
    if field == 'merge_sha':
        data['merge_commit_sha'] = HEAD
    elif field == 'merged':
        data['merged'] = False
    else:
        part, key = field.split('_')
        data[part][{'sha': 'sha', 'ref': 'ref', 'repo': 'repo'}[key]] = \
            {'full_name': 'other/repo'} if key == 'repo' else (BASE if key == 'sha' else 'other')
    with pytest.raises(ValueError):
        delivery.accept(ledger, data)
    assert ledger['merge_sha'] == MERGE


@pytest.mark.parametrize('data', [{}, {'items': []}, {'items': [], 'complete': True}, {'isError': True}])
def test_empty_or_failed_collection_does_not_prove_ref_absence(prepared, data):
    ledger = prepared['ledger']
    start_cleanup(ledger)
    cleanup_to_branches(ledger)
    with pytest.raises(ValueError):
        delivery.accept(ledger, data)
    assert ledger['step'] == 'cleanup_branches'
    assert 'branch' not in ledger['cleanup_proof']


def test_array_collections_and_exact_open_pr_query_coverage(prepared):
    ledger = prepared['ledger']
    start_cleanup(ledger)
    cleanup_to_branches(ledger)
    first = [{'name': 'other' + str(i)} for i in range(100)]
    delivery.accept(ledger, first)
    assert delivery.request(ledger)['arguments']['url'].endswith('page=2')
    delivery.accept(ledger, [{'name': ledger['branch'], 'protected': False, 'commit': {'sha': HEAD}}])
    job = delivery.request(ledger)
    assert 'state=open&head=21in7%3Acodex%2F' in job['arguments']['url']
    delivery.accept(ledger, [])
    assert ledger['step'] == 'cleanup_execute' and ledger['cleanup_proof']['verified'] is True


def test_legacy_merged_passed_requires_explicit_cleanup_and_never_remerges(prepared, capsys):
    ledger = prepared['ledger']
    to_pr(ledger)
    ledger.update(status='merged', step='done', merge_sha=MERGE)
    agent_models.private_json(prepared['directory'] / 'github.json', ledger)
    report = {**prepared['report'], 'status': 'passed'}
    agent_models.private_json(prepared['directory'] / 'report.json', report)
    assert delivery.main(['resume', '--run-id', ledger['run_id']]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['request']['tool'] == delivery.TOOLS['fetch']
    assert output['github']['step'] == 'cleanup_pr'
    assert json.loads((prepared['directory'] / 'report.json').read_text())['status'] == 'awaiting_github'


def test_cleanup_read_error_preserves_merge_and_returns_non_success(prepared, capsys):
    ledger = prepared['ledger']
    start_cleanup(ledger)
    delivery.save(prepared['directory'], ledger)
    assert delivery.main(['request', '--run-id', ledger['run_id']]) == 0
    job = json.loads(capsys.readouterr().out)['request']
    assert delivery.main(['accept', '--run-id', ledger['run_id'], '--request-id', job['request_id'],
                          '--response-json', json.dumps({'isError': True})]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output['request'] is None and output['github']['merge_sha'] == MERGE
    assert output['github']['status'] == 'cleanup_pending'
    assert json.loads((prepared['directory'] / 'report.json').read_text())['status'] == 'cleanup_pending'
    assert delivery.main(['resume', '--run-id', ledger['run_id']]) == 0
    assert json.loads(capsys.readouterr().out)['request']['tool'] == delivery.TOOLS['fetch']


def test_cleanup_pagination_limit_and_duplicate_branch_names_fail_closed(prepared):
    ledger = prepared['ledger']
    start_cleanup(ledger)
    cleanup_to_branches(ledger)
    ledger['cleanup_page'] = 100
    with pytest.raises(ValueError, match='pagination limit'):
        delivery.accept(ledger, [{'name': 'other' + str(i)} for i in range(100)])
    ledger.update(cleanup_page=1, cleanup_rows=[])
    with pytest.raises(ValueError, match='Ambiguous'):
        delivery.accept(ledger, [{'name': 'duplicate'}, {'name': 'duplicate'}])


def test_post_merge_test_merge_ci_gate_is_retained(prepared):
    ledger = prepared['ledger']
    start_cleanup(ledger)
    ledger['test_merge_sha'] = TEST_MERGE
    delivery.accept(ledger, cleanup_pr_data(ledger))
    delivery.accept(ledger, check_response([]))
    assert TEST_MERGE in delivery.request(ledger)['arguments']['url']
    delivery.accept(ledger, check_response(rows_for(ledger, sha=TEST_MERGE)))
    assert ledger['cleanup_proof']['check_sha'] == TEST_MERGE
    delivery.accept(ledger, {'sha': HEAD, 'total_count': 0})
    delivery.accept(ledger, {'sha': TEST_MERGE, 'total_count': 0})
    delivery.accept(ledger, {'full_name': ledger['config']['repository'], 'default_branch': 'master'})
    assert ledger['step'] == 'cleanup_branches'
