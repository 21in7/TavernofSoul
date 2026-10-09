"""GitHub delivery gates and real checkout preservation, without network calls."""
import copy
import json
from pathlib import Path
import subprocess

import pytest

from harness import agent_models, git_publish as delivery, workflow, workspace

BASE, TREE, NEW_TREE, HEAD, MERGE, TEST_MERGE = [char * 40 for char in 'abcdef']
DETAILS = {'commit_message': 'Correct fixture behavior', 'pr_title': 'Correct fixture behavior',
           'pr_body': 'Preserve the task scope. Validation: offline checks passed.'}


def git(root, *args):
    return subprocess.run(['git', *args], cwd=str(root), check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    git(root, 'init', '--template=', '-q')
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
              'review': {'verdict': 'approved'}, 'validation': [{'status': 'passed'}]}
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
    delivery.accept(ledger, {'ref': 'refs/heads/' + ledger['branch'], 'object': {'sha': HEAD}})
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
    assert delivery.request(ledger) is None
    assert json.loads((prepared['directory'] / 'report.json').read_text())['status'] == 'passed'


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
