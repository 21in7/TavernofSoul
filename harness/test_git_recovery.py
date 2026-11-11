"""Synthetic offline regressions; only the orchestrator executes this file.

No observed identifiers, logs, receipts or connector response bytes are copied.
The isolated park fixture supplies a synthetic approval and local Git baseline.
"""
import copy
import os
from types import SimpleNamespace

import pytest

from harness import git_publish as native, git_transport as transport, parent_commands as parent
from harness import git_recovery as recovery, worktree_park as parking
from harness.test_git_publish import to_tree, pr_data, rows_for, HEAD, NEW_TREE, MERGE
from harness.test_worktree_park import parked_repo, isolated_parent_context
from harness.test_git_transport import durable

ERROR = transport.encode({'isError': True, 'content': [{'type': 'text', 'text': 'Synthetic catalog refusal'}]})


def saved(path, raw):
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


def image(directory):
    return {p.name: p.read_bytes() for p in (directory / 'transport').iterdir() if p.name != 'claim'}


@pytest.fixture
def recovery_case(parked_repo, monkeypatch, request):
    repo = parked_repo
    for key in ('TAVERN_WORKFLOW_DEMO', 'TAVERN_NO_GIT'):
        monkeypatch.delenv(key, raising=False)
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(recovery.time, 'time', lambda: clock.now)
    ledger, directory = copy.deepcopy(repo['ledger']), repo['directory']
    to_tree(ledger)
    ledger['base_sha'] = repo['head']
    native.accept(ledger, {'sha': NEW_TREE})
    native.accept(ledger, {'sha': HEAD})
    step = getattr(request, 'param', 'branch')
    ref = {'ref': 'refs/heads/' + ledger['branch'], 'object': {'type': 'commit', 'sha': HEAD}}
    if step == 'create_pr':
        native.accept(ledger, ref)
    ledger['deadline'] = 1600.0
    native.save(directory, ledger)
    first = parent.execute('agent-git-next', directory.name)
    assert first['code'] == 'native_result', first
    job = first['native']['request']
    request_id = job['request_id']
    op = parent.operation('accept', directory.name, request_id)
    # Model a completed accept-file attempt and its immutable native error.
    durable(directory / ('parent-accept-' + op + '.json'), {
        'version': 'parent-accept-attempt-v1', 'run_id': directory.name,
        'request_id': request_id, 'response_sha256': transport.digest(ERROR)})
    failed = transport.transact('accept', directory.name, request_id, ERROR)
    assert failed['native_exit_code'] == 1
    ledger = transport.parse((directory / 'github.json').read_bytes())
    assert ledger['status'] == 'needs_reconciliation' and ledger['pending_request_id'] == request_id
    private = directory / 'synthetic-evidence'
    private.mkdir(mode=0o700)
    # A separately approved same-ID success response remains preserved. GET is
    # still mandatory; this success alone cannot replace the original response.
    success = saved(private / 'success.json', transport.encode({'branch': ledger['branch']}))
    prefix = 'https://api.github.com/repos/' + ledger['config']['repository']
    rows = []

    def get(path, body, page=None):
        rows.append({'method': 'GET', 'url': prefix + path, 'status': 200, 'complete': True,
                     'page': page, 'coverage': 'page' if page else 'object', 'body': body})

    get('/git/ref/heads/' + ledger['branch'], ref)
    detail = pr_data(ledger, number=37, title=ledger['metadata']['pr_title'],
                     body=ledger['metadata']['pr_body'], maintainer_can_modify=False)
    detail['base']['sha'] = ledger['base_sha']
    if step == 'create_pr':
        from urllib.parse import quote
        head = quote(ledger['config']['repository'].split('/')[0] + ':' + ledger['branch'], safe='')
        get('/pulls?state=all&head=' + head + '&per_page=100&page=1', [copy.deepcopy(detail)], 1)
        get('/pulls/37', detail)
    bundle = {'version': recovery.VERSION, 'run_id': directory.name, 'request_id': request_id,
              'target': recovery.target(ledger), 'tool_arguments_sha256': recovery.tool_digest(job),
              'approval_sha256': transport.digest((directory / 'github-approved.json').read_bytes()),
              'journal_sha256': transport.digest((directory / 'github.json').read_bytes()),
              'previous_receipt_sha256': transport.digest((directory / 'transport' / (op + '.complete.json')).read_bytes()),
              'responses': rows}
    evidence = private / 'evidence.json'
    case = SimpleNamespace(**locals())

    def invoke(bundle_override=None, request_override=None):
        raw = transport.encode(bundle if bundle_override is None else bundle_override)
        saved(evidence, raw)
        return parent.execute('agent-git-reconcile', directory.name,
                              request_id=request_override or request_id,
                              evidence_file=str(evidence), evidence_sha256=transport.digest(raw))

    case.invoke = invoke
    case.before = image(directory)
    return case


@pytest.mark.parametrize('recovery_case', ['branch', 'create_pr'], indirect=True)
def test_completed_error_links_observed_exact_result_without_legacy_accept(recovery_case, monkeypatch):
    case = recovery_case
    monkeypatch.setattr(native, 'main', lambda *a: pytest.fail('Legacy CLI must not execute'))
    result = case.invoke()
    assert result['decision'] == 'matched' and result['code'] == 'native_result', result
    assert result['next_action']['action'] == 'call_connector'
    assert result['next_action']['tool'] == native.TOOLS['create_pull_request' if case.step == 'branch' else 'fetch']
    assert result['native']['request']['request_id'] != case.request_id
    for name, raw in case.before.items():
        if name != 'head.json':
            assert (case.directory / 'transport' / name).read_bytes() == raw
    assert transport.parse(case.success.read_bytes()) == {'branch': case.ledger['branch']}
    # Old response identity remains an error; no wrapper reaccept bypass.
    conflict = parent.execute('agent-git-accept-file', case.directory.name, request_id=case.request_id,
                             response_file=str(case.success), sha256=transport.digest(case.success.read_bytes()))
    assert conflict['code'] == 'conflicting_response' and conflict['executed'] is False
    reader = parent.execute('agent-git-next-file', case.directory.name,
                            request_file=result['request_file']['path'], sha256=result['request_file']['sha256'])
    assert reader['code'] == 'exact_request_verified'


@pytest.mark.parametrize('fault,decision', [
    ('absent', 'absent'), ('sha', 'mismatch'), ('ref', 'mismatch'), ('forbidden', 'unknown'),
    ('error', 'unknown'), ('incomplete', 'unknown'), ('missing', 'unknown')])
def test_ref_observations_never_retry_or_turn_query_failure_into_absence(recovery_case, fault, decision):
    case = recovery_case
    row = case.bundle['responses'][0]
    if fault == 'absent':
        row.update(status=404, body={'message': 'Not Found'})
        case.bundle['responses'].append({'method': 'GET', 'url': case.prefix, 'status': 200,
            'complete': True, 'page': None, 'coverage': 'object',
            'body': {'full_name': case.ledger['config']['repository']}})
    elif fault in ('forbidden', 'error'):
        row.update(status=403 if fault == 'forbidden' else 500, body={'message': 'Synthetic failure'})
    elif fault == 'sha':
        row['body']['object']['sha'] = 'e' * 40
    elif fault == 'ref':
        row['body']['ref'] += '-other'
    elif fault == 'incomplete':
        row['complete'] = False
    else:
        case.bundle['responses'] = []
    result = case.invoke()
    assert result['decision'] == decision and result['executed'] is False, result
    assert image(case.directory) == case.before
    if fault == 'missing':
        assert result['next_action']['action'] == 'collect_get'
        assert result['next_action']['url'] == row['url']
    else:
        assert result['next_action']['action'] == 'stop'


@pytest.mark.parametrize('recovery_case', ['create_pr'], indirect=True)
@pytest.mark.parametrize('fault,decision', [('absent', 'absent'), ('multiple', 'mismatch'),
    ('incomplete', 'unknown'), ('forbidden', 'unknown'), ('metadata', 'mismatch'),
    ('head', 'mismatch'), ('base', 'mismatch'), ('closed', 'mismatch'), ('merged', 'unknown')])
def test_ui_pr_requires_unique_all_state_pages_and_full_exact_semantics(recovery_case, fault, decision):
    case = recovery_case
    collection, detail = case.bundle['responses'][1:]
    if fault == 'absent':
        collection['body'] = []
        case.bundle['responses'].pop()
    elif fault == 'multiple':
        collection['body'] *= 2
    elif fault == 'incomplete':
        collection['body'] *= 100
        case.bundle['responses'].pop()
    elif fault == 'forbidden':
        collection.update(status=403, body=[])
    elif fault == 'metadata':
        detail['body']['body'] = 'Unapproved UI edit'
    elif fault in ('head', 'base'):
        detail['body'][fault]['sha'] = 'e' * 40
    else:
        detail['body']['state'] = 'closed'
        detail['body']['merged'] = fault == 'merged'
    result = case.invoke()
    assert result['decision'] == decision and result['executed'] is False, result
    assert image(case.directory) == case.before
    if fault == 'incomplete':
        assert result['next_action']['url'].endswith('page=2')


@pytest.mark.parametrize('recovery_case', ['create_pr'], indirect=True)
def test_pr_list_identity_uses_pinned_fields_and_detail_validates_ui_metadata(recovery_case):
    case = recovery_case
    candidate = case.bundle['responses'][1]['body'][0]
    candidate.pop('maintainer_can_modify')  # A detail-only REST field.
    candidate['head']['repo']['description'] = 'Incidental synthetic repository metadata'
    result = case.invoke()
    assert result['code'] == 'native_result' and result['decision'] == 'matched', result


@pytest.mark.parametrize('recovery_case', ['branch', 'create_pr'], indirect=True)
@pytest.mark.parametrize('remaining', [-1, 0, 299.999, 300, 300.001])
def test_no_deadline_renewal_exact_minimum_and_expired_observation(recovery_case, remaining):
    case = recovery_case
    case.clock.now = 1600 - remaining
    result = case.invoke()
    assert result['decision'] == 'matched' and result['code'] == 'native_result', result
    ledger = transport.parse((case.directory / 'github.json').read_bytes())
    assert ledger['deadline'] == 1600 and 'minimum_write_seconds' not in ledger
    if remaining <= 0 or (case.step == 'branch' and remaining < 300):
        assert ledger['status'] == ('awaiting_ci' if case.step == 'create_pr' else 'failed')
        assert ledger.get('pending_request_id') is None and result['next_action']['action'] == 'stop'
        assert result['native'].get('request') is None and 'request_file' not in result
    else:
        assert result['next_action']['action'] == 'call_connector'
    before = image(case.directory)
    case.clock.now += 2000
    repeated = case.invoke()
    assert repeated['code'] == 'already_reconciled' and repeated['executed'] is False
    assert image(case.directory) == before and 'request_file' not in repeated


@pytest.mark.parametrize('different', [False, True])
def test_reentry_preserves_first_evidence_and_never_reexports_next_request(recovery_case, different):
    case = recovery_case
    assert case.invoke()['decision'] == 'matched'
    before = image(case.directory)
    if different:
        case.bundle['responses'][0]['body']['object']['sha'] = 'e' * 40
    again = case.invoke()
    assert again['code'] == 'already_reconciled' and again['executed'] is False
    assert image(case.directory) == before and 'native' not in again and 'request_file' not in again


@pytest.mark.parametrize('fault', ['target', 'tool_arguments_sha256', 'approval_sha256',
    'journal_sha256', 'previous_receipt_sha256', 'request_id', 'stale', 'journal', 'receipt',
    'approval', 'tool', 'arguments', 'inflight', 'orphan', 'external'])
def test_tamper_unknown_dispatch_and_legacy_edits_stop(recovery_case, fault):
    case = recovery_case
    request_override = None
    if fault == 'target':
        case.bundle['target']['repository'] = 'example/other'
    elif fault in case.bundle and fault != 'responses':
        case.bundle[fault] = '0' * 64
    elif fault == 'stale':
        request_override = '0' * 64
    elif fault in ('journal', 'approval'):
        name = 'github.json' if fault == 'journal' else 'github-approved.json'
        path = case.directory / name
        path.write_bytes(path.read_bytes() + b' ')
    elif fault == 'receipt':
        path = case.directory / 'transport' / (case.op + '.complete.json')
        value = transport.parse(path.read_bytes())
        value['response_sha256'] = '0' * 64
        durable(path, value)
    elif fault in ('tool', 'arguments'):
        path = case.directory / 'transport' / (case.first['transport']['operation_id'] + '.stdout')
        value = transport.parse(path.read_bytes())
        value['request'][fault] = 'unknown' if fault == 'tool' else {'branch_name': 'other'}
        path.write_bytes(transport.encode(value))
    elif fault == 'external':
        durable(case.directory / 'external-merge.json', {})
    else:
        name = 'inflight.json' if fault == 'inflight' else '0' * 64 + '.begin.json'
        durable(case.directory / 'transport' / name, {})
    before = image(case.directory)
    result = case.invoke(request_override=request_override)
    assert result['executed'] is False and result['next_action']['action'] == 'stop', result
    assert image(case.directory) == before


@pytest.mark.parametrize('boundary', ['.begin.json', '.before.json', '.response.json', '.stdout', '.complete.json', 'save', 'head'])
@pytest.mark.parametrize('interrupt', [False, True])
def test_durable_intent_partial_io_never_reruns_native_or_fakes_completion(recovery_case, monkeypatch, boundary, interrupt):
    case = recovery_case
    real_write, real_save, real_head = transport.Records.write, native.save, transport.Records.head

    def fail():
        raise KeyboardInterrupt() if interrupt else OSError('synthetic partial IO')

    def write(self, name, raw, **kwargs):
        if name.endswith(boundary):
            real_write(self, name, raw[:max(1, len(raw) // 2)], **kwargs)
            fail()
        return real_write(self, name, raw, **kwargs)

    def save(*args):
        real_save(*args)
        fail()

    def head(*args):
        real_head(*args)
        fail()

    monkeypatch.setattr(transport.Records, 'write', write)
    if boundary == 'save':
        monkeypatch.setattr(native, 'save', save)
    if boundary == 'head':
        monkeypatch.setattr(transport.Records, 'head', head)
    result = case.invoke()
    assert result['executed'] is True and result['status'] == 'needs_reconciliation', result
    assert (case.directory / 'transport/inflight.json').exists()
    before = image(case.directory)
    monkeypatch.setattr(native, 'accept', lambda *a: pytest.fail('No native replay after uncertain intent'))
    again = case.invoke()
    assert again['executed'] is False and again['next_action']['action'] == 'stop'
    assert image(case.directory) == before
    for name, raw in case.before.items():
        if name != 'head.json':
            assert (case.directory / 'transport' / name).read_bytes() == raw


@pytest.mark.parametrize('fault', ['response', 'snapshot', 'diagnostic', 'link'])
def test_shared_readers_reject_corruption_after_success(recovery_case, fault):
    case = recovery_case
    result = case.invoke()
    assert result['code'] == 'native_result'
    op = recovery.operation(case.directory.name, case.request_id)
    name = {'response': op + '.response.json', 'snapshot': op + '.before.json',
            'diagnostic': case.op + '.stderr', 'link': op + '.begin.json'}[fault]
    path = case.directory / 'transport' / name
    path.write_bytes(path.read_bytes() + b' ')
    reader = parent.execute('agent-git-next-file', case.directory.name,
                            request_file=result['request_file']['path'], sha256=result['request_file']['sha256'])
    assert reader['next_action']['action'] == 'stop' and 'exact_request' not in reader
    # Direct native transport also validates old reconcile receipts.
    with pytest.raises(ValueError):
        transport.transact('accept', case.directory.name, result['native']['request']['request_id'], b'{}')


def test_input_is_one_snapshot_even_when_path_replaced_after_read(recovery_case, monkeypatch):
    case = recovery_case
    real = parent.response_snapshot

    def snapshot(selected, path, sha):
        raw = real(selected, path, sha)
        if str(path) == str(case.evidence):
            case.evidence.unlink()
            saved(case.evidence, b'{}')
        return raw

    monkeypatch.setattr(parent, 'response_snapshot', snapshot)
    result = case.invoke()
    assert result['code'] == 'native_result' and case.evidence.read_bytes() == b'{}'


def test_time_lost_in_native_save_stops_next_write_and_preserves_observation(recovery_case, monkeypatch):
    case = recovery_case
    real = native.save

    def save(*args):
        real(*args)
        case.clock.now = 1700

    monkeypatch.setattr(native, 'save', save)
    result = case.invoke()
    assert result['code'] == 'native_result' and result['decision'] == 'matched'
    assert result['status'] == 'failed' and result['next_action']['action'] == 'stop'
    assert result['native']['request'] is None
    assert transport.parse((case.directory / 'github.json').read_bytes())['deadline'] == 1600


def test_partial_native_save_cannot_manufacture_complete_receipt(recovery_case, monkeypatch):
    case = recovery_case
    before_report = (case.directory / 'report.json').read_bytes()

    def partial_save(directory, ledger):
        durable(directory / 'github.json', ledger)  # Simulate only the first durable native write.

    monkeypatch.setattr(native, 'save', partial_save)
    result = case.invoke()
    assert result['code'] == 'reconcile_report_readback_mismatch' and result['executed'] is True
    op = recovery.operation(case.directory.name, case.request_id)
    assert not (case.directory / 'transport' / (op + '.complete.json')).exists()
    assert (case.directory / 'transport/inflight.json').exists()
    assert (case.directory / 'report.json').read_bytes() == before_report


@pytest.mark.parametrize('repository_status', [None, 403, 404, 500])
def test_ref_404_without_repository_access_is_unknown(recovery_case, repository_status):
    case = recovery_case
    case.bundle['responses'][0].update(status=404, body={'message': 'Not Found'})
    if repository_status is not None:
        case.bundle['responses'].append({'method': 'GET', 'url': case.prefix, 'status': repository_status,
            'complete': True, 'page': None, 'coverage': 'object', 'body': {'message': 'Not Found'}})
    result = case.invoke()
    assert result['decision'] == 'unknown' and result['executed'] is False
    assert image(case.directory) == case.before
    if repository_status is None:
        assert result['next_action']['url'] == case.prefix


@pytest.mark.parametrize('extra', [[], ['--minimum-write-seconds', 'nan'], ['--request-id', 'not-hex']])
def test_reconcile_cli_argument_errors_are_one_versioned_json(capsys, extra):
    assert parent.main(['agent-git-reconcile', '--run-id', '123456-abcdef'] + extra) == 2
    captured = capsys.readouterr()
    result = transport.parse(captured.out.encode('utf-8'))
    assert result['version'] == 'parent-commands-v1' and result['code'] == 'invalid_arguments'
    assert result['executed'] is False and captured.err == ''


@pytest.mark.parametrize('fault', ['symlink', 'hardlink', 'mode', 'directory_mode', 'hash',
                                  'truncated', 'duplicate_key', 'utf8'])
def test_private_evidence_boundary_has_no_side_effects(recovery_case, fault):
    case = recovery_case
    raw = transport.encode(case.bundle)
    path = saved(case.evidence, raw)
    sha = transport.digest(raw)
    if fault == 'symlink':
        other = path.with_name('other.json')
        path.rename(other)
        path.symlink_to(other)
    elif fault == 'hardlink':
        os.link(path, path.with_name('alias.json'))
    elif fault == 'mode':
        path.chmod(0o644)
    elif fault == 'directory_mode':
        path.parent.chmod(0o755)
    elif fault == 'hash':
        sha = '0' * 64
    else:
        raw = {'truncated': b'{', 'duplicate_key': b'{"version":1,"version":2}', 'utf8': b'\xff'}[fault]
        saved(path, raw)
        sha = transport.digest(raw)
    result = parent.execute('agent-git-reconcile', case.directory.name, request_id=case.request_id,
                            evidence_file=str(path), evidence_sha256=sha)
    assert result['executed'] is False and result['next_action']['action'] == 'stop'
    assert image(case.directory) == case.before


@pytest.mark.parametrize('recovery_case', ['create_pr'], indirect=True)
@pytest.mark.parametrize('expired', [False, True])
def test_reconciled_chain_through_ci_park_ui_proof_and_external_cleanup(recovery_case, monkeypatch, expired):
    case = recovery_case
    if expired:
        case.clock.now = 1700
    result = case.invoke()
    assert result['decision'] == 'matched'
    linked = image(case.directory)

    # Use the real accept-file parser, private frame, attempt marker, transport
    # and native gates. Replace only subprocess dispatch with an in-process seam.
    def accept_process(run, request, frame, stdout, stderr, result):
        result['executed'] = True
        result['side_effects'].update(transport_invoked=True, native_invoked=True)
        envelope = transport.transact('accept', run, request, transport.stdin_response(frame))
        return envelope, envelope['native_exit_code']

    monkeypatch.setattr(parent, 'accept_process', accept_process)
    if not expired:
        detail = copy.deepcopy(case.detail)
        checks = {'check_runs': rows_for(case.ledger), 'total_count': len(native.REQUIRED)}
        for body in (detail, checks, {'sha': HEAD, 'total_count': 0}, detail):
            raw = transport.encode(body)
            path = saved(case.private / 'ci-response.json', raw)
            result = parent.execute('agent-git-accept-file', case.directory.name,
                                    request_id=result['native']['request']['request_id'],
                                    response_file=str(path), sha256=transport.digest(raw))
        assert result['code'] == 'stop_before_merge', result
        assert result['native']['request']['arguments']['expected_head_sha'] == HEAD
        assert set(result['native']['github']['checks'].values()) == {'success'}
    else:
        assert result['status'] == 'awaiting_ci' and result['native']['request'] is None
    parked = parking.park(case.directory.name)
    assert parked['status'] == 'parked', parked
    for name, raw in linked.items():
        if name != 'head.json':
            assert (case.directory / 'transport' / name).read_bytes() == raw

    ledger = transport.parse((case.directory / 'github.json').read_bytes())
    merged = copy.deepcopy(case.detail)
    merged.update(state='closed', merged=True, merge_commit_sha=MERGE)
    rows = []

    def get(path, body):
        row = {'method': 'GET', 'url': case.prefix + path, 'status': 200, 'complete': True, 'body': body}
        rows.append(row)
        return row

    get('/pulls/37', merged)
    for sha in (HEAD, MERGE):
        get('/git/commits/' + sha, {'sha': sha, 'tree': {'sha': NEW_TREE},
                                   'parents': [{'sha': ledger['base_sha']}]})
    check_row = get('/commits/' + HEAD + '/check-runs?filter=latest&per_page=100&page=1',
                    {'check_runs': rows_for(ledger), 'total_count': len(native.REQUIRED)})
    get('/commits/' + HEAD + '/status', {'sha': HEAD, 'total_count': 0, 'statuses': []})
    get('', {'full_name': ledger['config']['repository'], 'default_branch': 'master'})
    get('/branches?per_page=100&page=1', [{'name': ledger['branch'], 'protected': False, 'commit': {'sha': HEAD}}])
    from urllib.parse import quote
    head = quote(ledger['config']['repository'].split('/')[0] + ':' + ledger['branch'], safe='')
    get('/pulls?state=open&head=' + head + '&per_page=100&page=1', [])
    proof = {'version': 'external-merge-proof-v1', 'run_id': case.directory.name, 'pr_number': 37,
             **recovery.target(ledger), 'merge_sha': MERGE, 'responses': rows}
    proof_raw = transport.encode(proof)
    proof_file = saved(case.private / 'ui-proof.json', proof_raw)
    kwargs = {}
    if expired:
        checks = {'version': 'external-merge-checks-v1', 'run_id': case.directory.name, 'pr_number': 37,
                  'repository': ledger['config']['repository'], 'head_sha': HEAD, 'responses': [check_row]}
        raw = transport.encode(checks)
        kwargs = {'checks_file': str(saved(case.private / 'checks.json', raw)), 'checks_sha256': transport.digest(raw)}
    native.external_merge_proof(ledger, proof, 37)  # Real native GET/CI/provenance gates.
    history = image(case.directory)
    cleanup_calls = []

    class OfflineCleanup:
        def __init__(self, *args, **kwargs):
            self.state = {}

        def run_external(self):
            cleanup_calls.append('synthetic cleanup')
            return {'version': 'cleanup-v1', 'status': 'complete',
                    **{key: {'status': 'deleted'} for key in ('remote', 'local')},
                    **{key: {'status': 'complete'} for key in ('sync', 'prune', 'completion')}}

    def archive_seam(self, attempted, cleanup):
        # No remote Git, archive transfer or operating completion pipeline.
        assert attempted and native.cleanup_complete(self.ledger)
        assert 'cleanup' in self.state['completed']
        self.result.update(status='verified', code='external_merge_verified', stage='complete')

    monkeypatch.setattr(parent.git_cleanup, 'Cleanup', OfflineCleanup)
    monkeypatch.setattr(parent.ExternalMerge, 'archive_phase', archive_seam)
    external = parent.execute('agent-git-external-merge', case.directory.name, pr_number=37,
                              proof_file=str(proof_file), sha256=transport.digest(proof_raw), **kwargs)
    assert external['code'] == 'external_merge_verified', external
    assert cleanup_calls == ['synthetic cleanup'] and image(case.directory) == history
    assert native.cleanup_complete(transport.parse((case.directory / 'github.json').read_bytes()))
