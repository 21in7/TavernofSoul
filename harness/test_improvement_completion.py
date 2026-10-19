"""Offline completion contract/recovery tests; no models, Git, checks or sockets.

Signed records and real Store durability/journal validation are exercised here.
The existing structured coverage predicate is an explicit seam: its own schema
regressions belong to the workflow tests, while a false result must deny delivery.
"""
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from harness import agent_models, git_publish as github, improvement_completion as completion
from harness import improvement_report as contract, improvements as imp, storage, workflow, workspace
from harness.test_improvements import candidate

RUN = '123456789-abcdef'
OTHER_RUN = '123456790-abcdef'
NOW = dt.datetime(2026, 10, 19, 1, tzinfo=dt.timezone.utc)
DOC = {'status': 'not_required', 'files': [], 'reason': 'Synthetic local behavior change only.'}
GROUPS = {'fixture': {'status': 'passed', 'coverage': 'complete'}}
CFG = {'version': 'github-v1', 'enabled': True, 'repository': '21in7/TavernofSoul',
       'base': 'master', 'merge_method': 'squash', 'required_checks': sorted(github.REQUIRED),
       'check_app': 'github-actions', 'wait_seconds': 1800}


def forbidden(*args, **kwargs):
    pytest.fail('Completion crossed an offline/authority boundary')


@pytest.fixture
def completed(tmp_path, monkeypatch):
    for key in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                'TAVERN_IMPROVEMENT_UNATTENDED', 'READ_ONLY', 'GIT', storage.CONFIG_ENV, storage.REPORT_ENV):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / 'project'
    root.mkdir(mode=0o700)
    selected = storage.Storage(root=root, env={})
    for module in (imp, github, workflow):
        monkeypatch.setattr(module, 'ROOT', root)
        monkeypatch.setattr(module, 'REPORTS', root / 'logs/harness' / (
            'improvements' if module is imp else 'workflows'))
    monkeypatch.setattr(github, 'load_config', lambda: copy.deepcopy(CFG))
    monkeypatch.setattr(github, 'origin_matches', lambda where, repo: where == root and repo == CFG['repository'])
    monkeypatch.setattr(github, 'storage_policy', lambda: selected)
    monkeypatch.setattr(imp, 'load_config', lambda: {'limits': {'delivery_timeout_seconds': 12}})
    monkeypatch.setattr(imp, '_authorization', forbidden)
    monkeypatch.setattr(imp, '_fresh', forbidden)
    monkeypatch.setattr(agent_models, 'run', forbidden)
    monkeypatch.setattr(agent_models, 'load_keys', forbidden)
    monkeypatch.setattr(workflow, 'execute', forbidden)
    monkeypatch.setattr(workflow, 'run_check', forbidden)
    monkeypatch.setattr(workflow.failure_feedback, 'check_groups_passed', lambda value: value == GROUPS)
    monkeypatch.setattr(github.subprocess, 'run', forbidden)
    monkeypatch.setattr(github.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(imp.http.client, 'HTTPSConnection', forbidden)
    store = imp.Store(selected)
    directory = selected.ensure_directory(selected.workflow_root(local_default=github.local_reports()) / RUN)
    path = 'harness/example.py'
    for category, data in (('backup', b'before\n'), ('workspace', b'after\n')):
        target = directory / category / path
        target.parent.mkdir(parents=True, mode=0o700)
        target.write_bytes(data)
        target.chmod(0o644)
    fingerprints = contract.fingerprint_sources({path: {'exists': True, 'mode': 0o644, 'content': b'before\n'}})
    proposal = contract.proposal_record(candidate(), fingerprints)
    proposal['review'] = {'verdict': 'eligible', 'reason': 'Independent synthetic review.', 'documentation': DOC}
    pid = proposal['id']
    approval = {'version': 'improvement-approval-v1', 'authority': 'trusted-parent',
                'proposal_id': pid, 'proposal_digest': proposal['digest'],
                'review_digest': contract.digest(proposal['review']), 'source_fingerprints': fingerprints,
                'allowed_edit_files': [path], 'publication': imp.PUBLICATION,
                'instruction': 'Private original instruction must never cross the wire.',
                'issued_at': (NOW - dt.timedelta(days=20)).isoformat(),
                'expires_at': (NOW - dt.timedelta(days=13)).isoformat(),
                'authorization_id': 'a' * 48, 'consumption': 'unconsumed'}
    task_digest = hashlib.sha256(imp._task(proposal, approval).encode('utf-8')).hexdigest()
    claim = {'version': 'improvement-claim-v1', 'proposal_id': pid, 'proposal_digest': proposal['digest'],
             'authorization_id': approval['authorization_id'], 'task_digest': task_digest,
             'status': 'consumed', 'at': approval['issued_at'], 'run_id': RUN,
             'claim_id': 'b' * 48, 'workflow_status': 'awaiting_github'}
    with store.lock():
        store.write('proposals/' + pid + '.json', {'proposal': proposal, 'scan_id': OTHER_RUN,
                    'review_complete': True, 'status': 'scanned'})
        store.write('scans/' + OTHER_RUN + '.json', {'proposals': [proposal], 'review_complete': True,
                    'agents': [{'role': 'reviewer', 'status': 'succeeded'}],
                    'documentation': DOC, 'approved_files': [path]})
        store.write('approvals/' + pid + '.json', store.sign(approval, create=True))
        store.write('claims/' + pid + '.json', store.sign(claim))
        store.write('decisions/' + pid + '.json', {'status': 'approved', 'authorization_id': 'a' * 48})
        for name in ('days/2026-10-19.json', 'web/2026-10-19.json', 'publication/2026-10-19.json'):
            store.write(name, {'frozen': name, 'digest': 'unchanged'})
    before = workspace.fingerprint(directory / 'backup' / path, 4096)
    after = workspace.fingerprint(directory / 'workspace' / path, 4096)
    ledger = {'version': 'github-v1', 'run_id': RUN, 'config': copy.deepcopy(CFG),
              'metadata': {'commit_message': 'Fixture', 'pr_title': 'Fixture', 'pr_body': 'Fixture'},
              'branch': 'codex/' + RUN, 'status': 'merged', 'step': 'done', 'head_sha': 'c' * 40,
              'merge_sha': 'd' * 40, 'merge_status': 'merged', 'pr_number': 47,
              'pr_url': 'https://github.com/21in7/TavernofSoul/pull/47',
              'checks': {name: 'success' for name in github.REQUIRED},
              'cleanup': {'version': 'cleanup-v1', 'status': 'complete',
                          'remote': {'status': 'deleted'}, 'local': {'status': 'absent'},
                          'prune': {'status': 'complete'}, 'sync': {'status': 'complete'},
                          'completion': {'status': 'complete'}},
              'files': {path: {'before': {'sha': github.blob_sha(b'before\n'), 'mode': '100644'},
                               'after': {'sha': github.blob_sha(b'after\n'), 'mode': '100644', 'content': 'after\n'}}}}
    ledger['cleanup_proof'] = {'verified': True, 'head_sha': ledger['head_sha'],
                               'merge_sha': ledger['merge_sha'], 'checks': ledger['checks']}
    report = {'run_id': RUN, 'status': 'passed', 'read_only': False, 'simulated': False,
              'no_git': False, 'github_enabled': True, 'scope': [path], 'changed_files': [path],
              'applied': [path], 'workspace': str(directory / 'workspace'), 'task_sha256': task_digest,
              'review': {'verdict': 'approved', 'summary': 'Reviewed.', 'findings': [], 'documentation': DOC},
              'required_checks': ['check'], 'delivery_validation': [
                  {'command': 'check', 'status': 'passed', 'exit_code': 0, 'checks': GROUPS}]}
    report['github'] = github.summary(ledger)
    publication = {'config': CFG, 'run_id': RUN, 'workspace': report['workspace'], 'max_file_bytes': 4096,
                   'files': {path: {'before': before, 'after': after}}}
    for name, value in (('report.json', report), ('github.json', ledger), ('github-approved.json', publication)):
        agent_models.private_json(directory / name, value)
    inbox = root / 'inbox.json'
    agent_models.private_json(inbox, {'origin': 'https://fixture.invalid', 'token': 'fixture-secret'})
    return SimpleNamespace(root=root, selected=selected, directory=directory, store=store,
                           pid=pid, claim=claim, approval=approval, proposal=proposal,
                           ledger=ledger, report=report, inbox=inbox)


def run(lab, transport=forbidden, **kwargs):
    return completion.complete_run(RUN, selected=lab.selected, inbox_config=lab.inbox,
                                   transport=transport, now=kwargs.pop('now', NOW), **kwargs)


def saved(lab):
    return lab.store.read('completions/' + RUN + '/' + lab.pid + '.json')


def rewrite_run(lab):
    lab.report['github'] = github.summary(lab.ledger)
    for name, value in (('report.json', lab.report), ('github.json', lab.ledger)):
        agent_models.private_json(lab.directory / name, value)


class Sites:
    """Immutable atomic-create behavior plus bounded synthetic failure modes."""
    def __init__(self, lab, failure=None):
        self.lab, self.failure, self.calls, self.objects = lab, failure, [], {}

    def __call__(self, method, origin, path, headers, body, timeout, max_bytes):
        self.calls.append(method)
        assert origin == 'https://fixture.invalid'
        assert headers['OAI-Sites-Authorization'] == 'Bearer fixture-secret'
        assert 0 < timeout <= 12 and max_bytes == 16384
        if method == 'POST':
            payload = json.loads(body)
            assert path == '/api/completions'
            assert body == contract.canonical_json(payload)
            local = self.lab.store.read('completions/' + RUN + '/' + payload['proposal_id'] + '.json')
            assert local['state'] == 'sending' and local['payload'] == payload
            if self.failure == 'post_failed':
                return 503, b'private body'
            if self.failure == 'timeout':
                raise TimeoutError('fixture-secret raw private message')
            if self.failure == 'interrupt':
                raise KeyboardInterrupt()
            if payload['proposal_id'] in self.objects and self.objects[payload['proposal_id']] != payload:
                return 409, b'conflict'
            self.objects[payload['proposal_id']] = payload
            return 200, b'{}'
        assert method == 'GET' and path.startswith('/api/completions/IMP-') and body is None
        pid = path.rsplit('/', 1)[-1]
        if self.failure == 'readback_timeout':
            raise TimeoutError('fixture-secret')
        if pid not in self.objects or self.failure == 'absent':
            return 404, b'{}'
        value = copy.deepcopy(self.objects[pid])
        if self.failure == 'mismatch':
            value['merge_sha'] = 'f' * 40
            value['digest'] = contract.digest({k: v for k, v in value.items() if k != 'digest'})
        if self.failure == 'extra_field':
            value['private_instruction'] = 'fixture-secret'
        if self.failure == 'bad_digest':
            value['digest'] = '0' * 64
        if self.failure == 'wrapper':
            value = {'completion': value}
        if self.failure == 'duplicate':
            return 200, b'{"version":"improvement-completion-v1",' + contract.canonical_json(value)[1:]
        if self.failure == 'redirect':
            return 302, b'private body'
        if self.failure == 'oversize':
            return 200, b'x' * 16385
        return 200, contract.canonical_json(value)


def test_exact_wire_private_durable_frozen_and_idempotent(completed, monkeypatch):
    lab = completed
    frozen = {name: lab.store.path(name).read_bytes() for name in (
        'days/2026-10-19.json', 'web/2026-10-19.json', 'publication/2026-10-19.json',
        'claims/' + lab.pid + '.json', 'approvals/' + lab.pid + '.json')}
    original_report = (lab.directory / 'report.json').read_bytes()
    sites = Sites(lab)
    assert run(lab, sites)['status'] == 'delivered'
    payload = saved(lab)['payload']
    assert completion.validate_payload(payload) == payload
    assert set(payload) == completion.FIELDS
    assert payload['completed_at'] == NOW.isoformat()
    assert payload['proposal_id'] == lab.pid and payload['pr_url'] == lab.ledger['pr_url']
    assert payload['digest'] == hashlib.sha256(contract.canonical_json(
        {k: v for k, v in payload.items() if k != 'digest'})).hexdigest()
    public = json.dumps(payload)
    for private in ('instruction', 'fixture-secret', str(lab.root), 'source', 'prompt', 'diff', 'log'):
        assert private not in public
    outbox = lab.store.path('completions/' + RUN + '/' + lab.pid + '.json')
    assert outbox.stat().st_mode & 0o777 == 0o600
    assert outbox.read_bytes() == contract.canonical_json(saved(lab)) + b'\n'
    assert sites.calls == ['POST', 'GET']
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    monkeypatch.setattr(imp, 'load_config', forbidden)
    assert run(lab)['status'] == 'delivered'
    assert saved(lab)['payload'] == payload
    assert original_report == (lab.directory / 'report.json').read_bytes()
    assert all(lab.store.path(name).read_bytes() == content for name, content in frozen.items())
    # The source is deliberately different and the approval expired 13 days ago.
    assert lab.proposal['source_fingerprints'] != contract.fingerprint_sources({
        'harness/example.py': {'exists': True, 'mode': 0o644, 'content': b'after\n'}})


@pytest.mark.parametrize('marker,value', [('TAVERN_WORKFLOW_CHILD', '1'),
    ('TAVERN_IMPROVEMENT_DISCOVERY', '1'), ('TAVERN_IMPROVEMENT_UNATTENDED', '1'),
    ('READ_ONLY', '1'), ('GIT', '0')])
def test_parent_only_no_credentials(completed, monkeypatch, marker, value):
    monkeypatch.setenv(marker, value)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    assert run(completed)['status'] == 'disabled'


def test_unrelated_run_no_key_or_credentials(completed, monkeypatch):
    monkeypatch.setattr(imp.Store, 'key', forbidden)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    result = completion.complete_run(OTHER_RUN, selected=completed.selected, transport=forbidden)
    assert result == {'status': 'not_applicable', 'completions': []}


def test_run_with_no_claim_directory_is_noop(completed, monkeypatch):
    lab = completed
    lab.store.path('claims/' + lab.pid + '.json').unlink()
    lab.store.path('claims').rmdir()
    monkeypatch.setattr(imp.Store, 'key', forbidden)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    assert run(lab) == {'status': 'not_applicable', 'completions': []}


def test_running_signed_claim_can_recover_after_parent_interrupt(completed):
    claim = dict(completed.claim, status='running')
    claim.pop('workflow_status')
    completed.store.write('claims/' + completed.pid + '.json', completed.store.sign(claim))
    assert run(completed, Sites(completed))['status'] == 'delivered'


@pytest.mark.parametrize('fault', ['signature', 'approval_signature', 'wrong_proposal', 'authorization',
    'rejected', 'claimed', 'task', 'local_only', 'scope', 'review', 'validation', 'skipped_local',
    'missing_ci', 'skipped_ci', 'merge_only', 'cleanup', 'proof', 'head', 'merge', 'url', 'report_run',
    'read_only', 'simulated', 'no_git', 'not_applied', 'source_snapshot', 'claim_interval', 'proof_ci',
    'missing_required', 'exit_code', 'boolean_exit', 'proposal_digest', 'review_digest'])
def test_incomplete_or_unbound_evidence_never_posts(completed, monkeypatch, fault):
    lab = completed
    if fault in ('signature', 'wrong_proposal', 'authorization', 'claimed', 'claim_interval'):
        claim = dict(lab.claim)
        if fault == 'wrong_proposal':
            claim['proposal_id'] = 'IMP-' + '0' * 16
        elif fault == 'authorization':
            claim['authorization_id'] = 'f' * 48
        elif fault == 'claimed':
            claim['status'] = 'claimed'
        elif fault == 'claim_interval':
            claim['at'] = NOW.isoformat()
        raw = lab.store.sign(claim)
        if fault == 'signature':
            raw['run_id'] = OTHER_RUN
            lab.store.write('claims/' + lab.pid + '.json', raw)
            raw['run_id'] = RUN
            raw['signature'] = '0' * 64
        lab.store.write('claims/' + lab.pid + '.json', raw)
    elif fault in ('approval_signature', 'local_only'):
        approval = dict(lab.approval, publication='local-only' if fault == 'local_only' else imp.PUBLICATION)
        raw = lab.store.sign(approval)
        if fault == 'approval_signature':
            raw['instruction'] = 'tampered'
        lab.store.write('approvals/' + lab.pid + '.json', raw)
    elif fault == 'rejected':
        lab.store.write('decisions/' + lab.pid + '.json', {'status': 'rejected'})
    elif fault == 'scope':
        lab.report['scope'].append('harness/unapproved.py')
    elif fault == 'review':
        lab.report['review']['verdict'] = 'changes_requested'
    elif fault == 'validation':
        lab.report['delivery_validation'] = []
    elif fault == 'skipped_local':
        lab.report['delivery_validation'][0]['checks'] = {'fixture': {'status': 'skipped'}}
    elif fault == 'missing_ci':
        lab.ledger['checks'] = {}
    elif fault == 'skipped_ci':
        lab.ledger['checks'] = {name: 'skipped' for name in github.REQUIRED}
    elif fault == 'merge_only':
        lab.ledger['step'] = 'cleanup_execute'
    elif fault == 'cleanup':
        lab.ledger['cleanup']['completion']['status'] = 'pending'
    elif fault == 'proof':
        lab.ledger['cleanup_proof']['verified'] = False
    elif fault == 'head':
        lab.ledger['cleanup_proof']['head_sha'] = 'e' * 40
    elif fault == 'merge':
        lab.ledger['cleanup_proof']['merge_sha'] = 'e' * 40
    elif fault == 'url':
        lab.ledger['pr_url'] += '0'
    elif fault == 'report_run':
        lab.report['run_id'] = OTHER_RUN
    elif fault in ('read_only', 'simulated', 'no_git'):
        lab.report[fault] = True
    elif fault == 'not_applied':
        lab.report['applied'] = []
    elif fault == 'source_snapshot':
        (lab.directory / 'workspace/harness/example.py').write_text('tampered\n')
    elif fault == 'task':
        lab.report['task_sha256'] = '0' * 64
    elif fault == 'proof_ci':
        lab.ledger['cleanup_proof']['checks'] = {}
    elif fault == 'missing_required':
        lab.report['required_checks'] = ['check', 'check-parser']
    elif fault == 'exit_code':
        lab.report['delivery_validation'][0]['exit_code'] = 1
    elif fault == 'boolean_exit':
        lab.report['delivery_validation'][0]['exit_code'] = False
    elif fault == 'proposal_digest':
        raw = lab.store.read('proposals/' + lab.pid + '.json')
        raw['proposal']['candidate']['title'] = 'Changed private proposal'
        lab.store.write('proposals/' + lab.pid + '.json', raw)
    elif fault == 'review_digest':
        approval = dict(lab.approval, review_digest='0' * 64)
        lab.store.write('approvals/' + lab.pid + '.json', lab.store.sign(approval))
    rewrite_run(lab)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    assert run(lab)['status'] == 'blocked'
    assert not lab.store.path('completions').exists()


@pytest.mark.parametrize('failure,state', [('post_failed', 'unknown'), ('timeout', 'unknown'),
    ('interrupt', 'unknown'), ('readback_timeout', 'unknown'), ('mismatch', 'conflict'),
    ('extra_field', 'unknown'), ('oversize', 'unknown'), ('absent', 'unknown'), ('bad_digest', 'unknown'),
    ('wrapper', 'unknown'), ('duplicate', 'unknown'), ('redirect', 'unknown')])
def test_failed_delivery_preserves_success_and_frozen_journal(completed, failure, state):
    lab = completed
    before = (lab.directory / 'report.json').read_bytes()
    sites = Sites(lab, failure)
    assert run(lab, sites)['status'] == 'pending'
    record = saved(lab)
    assert record['state'] == state
    assert 'fixture-secret' not in json.dumps(record)
    assert (lab.directory / 'report.json').read_bytes() == before
    assert lab.report['status'] == 'passed' and lab.ledger['merge_sha'] == 'd' * 40
    assert github.cleanup_complete(lab.ledger)


def test_unknown_get_only_then_matching_readback_recovers(completed):
    lab = completed
    sites = Sites(lab, 'timeout')
    run(lab, sites)
    original = saved(lab)['payload']
    sites.failure = None
    sites.calls.clear()
    assert run(lab, sites)['completions'][0]['status'] == 'unknown'
    assert sites.calls == ['GET']
    sites.objects[lab.pid] = original
    sites.calls.clear()
    assert run(lab, sites, now=NOW + dt.timedelta(days=5))['status'] == 'delivered'
    assert sites.calls == ['GET'] and saved(lab)['payload'] == original


@pytest.mark.parametrize('state', ['ready', 'sending', 'unknown'])
def test_partial_progress_explicit_same_digest_retry(completed, state):
    lab = completed
    sites = Sites(lab, 'timeout')
    run(lab, sites)
    name = 'completions/' + RUN + '/' + lab.pid + '.json'
    record = saved(lab)
    record['state'] = state
    lab.store.write(name, record)
    sites.failure = None
    sites.calls.clear()
    assert run(lab, sites, reconcile=True, now=NOW + dt.timedelta(days=6))['status'] == 'delivered'
    assert sites.calls == ['GET', 'POST', 'GET']
    assert saved(lab)['payload'] == record['payload']


def test_crash_leaves_sending_and_automatic_resume_only_gets(completed):
    class ProcessDeath(BaseException):
        pass
    def crash(*args):
        assert saved(completed)['state'] == 'sending'
        raise ProcessDeath()
    with pytest.raises(ProcessDeath):
        run(completed, crash)
    payload = saved(completed)['payload']
    assert saved(completed)['state'] == 'sending'
    sites = Sites(completed)
    assert run(completed, sites)['completions'][0]['status'] == 'unknown'
    assert sites.calls == ['GET'] and saved(completed)['payload'] == payload


def test_post_conflict_is_terminal_and_never_overwrites(completed):
    sites = Sites(completed)
    sites.objects[completed.pid] = {'existing': 'different immutable digest'}
    assert run(completed, sites)['completions'][0]['status'] == 'conflict'
    assert sites.calls == ['POST']
    assert run(completed, forbidden, reconcile=True)['completions'][0]['status'] == 'conflict'


def test_explicit_conflicting_digest_never_posts_or_overwrites(completed):
    lab = completed
    sites = Sites(lab, 'timeout')
    run(lab, sites)
    payload = saved(lab)['payload']
    conflicting = dict(payload, completed_at=(NOW - dt.timedelta(seconds=1)).isoformat())
    conflicting['digest'] = contract.digest({k: v for k, v in conflicting.items() if k != 'digest'})
    sites.objects[lab.pid] = conflicting
    sites.failure = None
    sites.calls.clear()
    assert run(lab, sites, reconcile=True)['completions'][0]['status'] == 'conflict'
    assert sites.calls == ['GET'] and saved(lab)['payload'] == payload
    assert run(lab, forbidden, reconcile=True)['completions'][0]['status'] == 'conflict'


@pytest.mark.parametrize('tamper_second', [False, True])
def test_multiple_signed_claims_each_verified(completed, tamper_second):
    lab = completed
    second = contract.proposal_record(dict(lab.proposal['candidate'], title='Second explicitly bundled proposal'),
                                      lab.proposal['source_fingerprints'])
    second['review'] = lab.proposal['review']
    pid = second['id']
    scan = lab.store.read('scans/' + OTHER_RUN + '.json')
    scan['proposals'].append(second)
    lab.store.write('scans/' + OTHER_RUN + '.json', scan)
    lab.store.write('proposals/' + pid + '.json', {'proposal': second, 'scan_id': OTHER_RUN,
                    'review_complete': True, 'status': 'scanned'})
    approval = dict(lab.approval, proposal_id=pid, proposal_digest=second['digest'], authorization_id='e' * 48)
    claim = dict(lab.claim, proposal_id=pid, proposal_digest=second['digest'],
                 authorization_id='e' * 48, claim_id='f' * 48)
    lab.store.write('approvals/' + pid + '.json', lab.store.sign(approval))
    signed = lab.store.sign(claim)
    if tamper_second:
        signed['task_digest'] = '0' * 64
    lab.store.write('claims/' + pid + '.json', signed)
    lab.store.write('decisions/' + pid + '.json', {'status': 'approved', 'authorization_id': 'e' * 48})
    sites = Sites(lab)
    result = run(lab, sites)
    if tamper_second:
        assert result['status'] == 'blocked' and sites.calls == []
        return
    assert result['status'] == 'delivered'
    assert {row['proposal_id'] for row in result['completions']} == {pid, lab.pid}
    assert sites.calls == ['POST', 'GET', 'POST', 'GET']


@pytest.mark.parametrize('command', ['request', 'accept', 'resume', 'cleanup'])
def test_automatic_hook_after_final_save_and_both_locks_released(completed, monkeypatch, capsys, command):
    lab = completed
    sites = Sites(lab)
    real = completion.complete_run
    def after_locks(run_id, *, selected):
        assert run_id == RUN and selected is lab.selected
        for path in (selected.project_lock_path, lab.directory / 'github.lock'):
            with github.open_lock(selected, path) as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert imp._json_file(lab.directory / 'report.json')['status'] == 'passed'
        return real(run_id, selected=selected, transport=sites, inbox_config=lab.inbox, now=NOW)
    monkeypatch.setattr(completion, 'complete_run', after_locks)
    # Parent's real proof/cleanup logic is covered by existing GitHub regressions;
    # emulate reaching the same terminal state from each permitted CLI command.
    monkeypatch.setattr(github, 'begin_cleanup', lambda ledger: None)
    if command == 'accept':
        lab.ledger['pending_request_id'] = 'fixture-request'
        monkeypatch.setattr(github, 'accept', lambda ledger, response: ledger.pop('pending_request_id'))
        rewrite_run(lab)
    args = [command, '--run-id', RUN]
    if command == 'accept':
        args += ['--request-id', 'fixture-request', '--response-json', '{}']
    assert github.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['completion']['status'] == 'delivered'
    assert sites.objects[lab.pid] == saved(lab)['payload']


def test_completion_hook_failure_does_not_replace_git_success(completed, monkeypatch, capsys):
    monkeypatch.setattr(completion, 'complete_run', lambda *args, **kwargs: (_ for _ in ()).throw(ValueError()))
    assert github.main(['request', '--run-id', RUN]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['completion']['status'] == 'blocked' and output['github']['merge_status'] == 'merged'
    assert imp._json_file(completed.directory / 'report.json')['status'] == 'passed'


def test_selected_root_missing_does_not_fall_back_to_local_run(completed, monkeypatch):
    lab = completed
    override = lab.root / 'selected-reports'
    override.mkdir(mode=0o700)
    selected = storage.Storage(root=lab.root, env={storage.REPORT_ENV: str(override)})
    # Retain exactly the same private claims while selecting a different workflow root.
    def selected_store(self, chosen=None):
        self.policy, self.root = selected, lab.store.root
    monkeypatch.setattr(imp.Store, '__init__', selected_store)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    assert run(lab)['status'] == 'blocked'
    assert (lab.directory / 'report.json').exists()


@pytest.mark.parametrize('name', ['report.json', 'github.json', 'github-approved.json'])
@pytest.mark.parametrize('fault', ['mode', 'symlink', 'hardlink'])
def test_private_run_records_fail_closed(completed, monkeypatch, name, fault):
    lab = completed
    path = lab.directory / name
    if fault == 'mode':
        path.chmod(0o644)
    else:
        other = lab.directory / ('saved-' + name)
        path.rename(other)
        if fault == 'symlink':
            path.symlink_to(other)
        else:
            os.link(other, path)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    assert run(lab)['status'] == 'blocked'


def test_selected_run_symlink_is_not_followed(completed, monkeypatch):
    lab = completed
    moved = lab.directory.with_name(OTHER_RUN)
    lab.directory.rename(moved)
    lab.directory.symlink_to(moved, target_is_directory=True)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    assert run(lab)['status'] == 'blocked'


def test_frozen_outbox_tamper_is_not_recreated(completed):
    lab = completed
    run(lab, Sites(lab, 'timeout'))
    name = 'completions/' + RUN + '/' + lab.pid + '.json'
    record = saved(lab)
    record['payload']['completed_at'] = NOW.replace(tzinfo=None).isoformat()
    lab.store.write(name, record)
    before = lab.store.path(name).read_bytes()
    assert run(lab, forbidden, reconcile=True)['status'] == 'blocked'
    assert lab.store.path(name).read_bytes() == before


@pytest.mark.parametrize('fault', ['extra', 'version', 'id', 'url', 'sha', 'time', 'digest'])
def test_strict_wire_rejects_malformed_fields(completed, fault):
    sites = Sites(completed)
    run(completed, sites)
    payload = copy.deepcopy(saved(completed)['payload'])
    if fault == 'extra':
        payload['instruction'] = 'private'
    else:
        key, value = {'version': ('version', 'web-v1'), 'id': ('proposal_id', 'IMP-' + 'A' * 16),
                      'url': ('pr_url', 'https://github.com/other/repo/pull/47'),
                      'sha': ('merge_sha', 'D' * 40), 'time': ('completed_at', '2026-10-19T01:00:00'),
                      'digest': ('digest', '0' * 64)}[fault]
        payload[key] = value
    if fault != 'digest':
        payload['digest'] = contract.digest({k: v for k, v in payload.items() if k != 'digest'})
    with pytest.raises(ValueError):
        completion.validate_payload(payload)
