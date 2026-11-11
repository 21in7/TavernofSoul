"""Offline reconciliation of a completed failed write, exclusively for parent.

No HTTP, connector, subprocess, retry, CLI publisher accept or deadline renewal.
An exclusive intent survives every uncertain exit; only a fully verified new
receipt can advance transport head. This is not general journal repair.
"""
import copy
import os
import time
from contextlib import ExitStack
from urllib.parse import quote

from harness import git_publish as native, git_transport as transport

VERSION = 'git-reconcile-evidence-v1'


def require(value, code='reconcile_chain_mismatch'):
    if not value:
        raise transport.TransportError(code)


def operation(run, request):
    return transport.digest(transport.encode([run, 'reconcile', request]))


def tool_digest(request):
    return transport.digest(transport.encode({'tool': request['tool'], 'arguments': request['arguments']}))


def original(records, previous, ledger):
    """Find the original ID in immutable native output, never in caller targets."""
    from harness import parent_commands as parent
    request_id = previous['request_id']
    candidates = []
    for name in os.listdir(records.fd):
        if not name.endswith('.complete.json'):
            continue
        receipt = records.optional(name)
        parent.receipt_identity(receipt, records.directory.name)
        require(name == receipt['operation_id'] + '.complete.json')
        raw = records.read(receipt['operation_id'] + '.stdout')
        require(len(raw) == receipt['bytes'] and transport.digest(raw) == receipt['sha256'])
        payload = transport.parse(raw)
        job = payload.get('request')
        if isinstance(job, dict) and job.get('request_id') == request_id:
            require(receipt['native_exit_code'] == 0 and payload.get('run_id') == ledger['run_id'] and
                    receipt['ended_at'] <= previous['started_at'])
            require(isinstance(payload.get('github'), dict) and all(
                payload['github'].get(key) == ledger[key] for key in ('branch', 'base_sha', 'head_sha')),
                'original_target_mismatch')
            candidates.append((receipt['operation_id'], job))
    require(len(candidates) == 1, 'original_request_unproven')
    source, job = candidates[0]
    require(set(job) == {'tool', 'arguments', 'request_id'} and isinstance(job['arguments'], dict),
            'original_request_unproven')
    require(ledger['step'] in ('branch', 'create_pr'), 'unsupported_reconcile_type')
    expected = native.publication_request(ledger)
    require(expected == {key: job[key] for key in ('tool', 'arguments')}, 'original_request_mismatch')
    return source, job


def target(ledger):
    return {'repository': ledger['config']['repository'],
            'base': {'ref': ledger['config']['base'], 'sha': ledger['base_sha']},
            'head': {'ref': ledger['branch'], 'sha': ledger['head_sha']}}


def observe(ledger, bundle):
    """Return decision, proven native data, and an exact missing GET, if any."""
    repo = ledger['config']['repository']
    prefix = 'https://api.github.com/repos/' + repo
    rows = bundle['responses']
    require(isinstance(rows, list) and len(rows) <= 102, 'invalid_reconcile_responses')
    table = {}
    for row in rows:
        require(isinstance(row, dict) and set(row) == {
            'method', 'url', 'status', 'complete', 'page', 'coverage', 'body'} and
            row['method'] == 'GET' and isinstance(row['url'], str) and
            row['url'] not in table and type(row['status']) is int and
            type(row['complete']) is bool and (row['page'] is None or type(row['page']) is int),
            'invalid_reconcile_response')
        table[row['url']] = row
    used = set()

    def get(path, page=None):
        url = prefix + path
        used.add(url)
        row = table.get(url)
        if row is None:
            return None, url
        if (not row['complete'] or row['page'] != page or
                row['coverage'] != ('page' if page else 'object')):
            return None, None
        return row, None

    ref, missing = get('/git/ref/heads/' + ledger['branch'])
    if ref is None:
        return 'unknown', None, missing
    if ref['status'] == 404:
        # A complete exact-ref 404, not a failed list/permissions lookup.
        body = ref['body']
        if isinstance(body, dict) and body.get('message') == 'Not Found':
            repository, missing = get('')
            if repository is None:
                return 'unknown', None, missing
            # GitHub may hide an inaccessible private repository behind 404.
            if (repository['status'] == 200 and isinstance(repository['body'], dict) and
                    repository['body'].get('full_name') == repo):
                return 'absent', None, None
        return 'unknown', None, None
    if ref['status'] != 200:
        return 'unknown', None, None
    body = ref['body']
    if (not isinstance(body, dict) or not isinstance(body.get('object'), dict) or
            not isinstance(body.get('ref'), str) or
            not all(isinstance(body['object'].get(key), str) for key in ('type', 'sha'))):
        return 'unknown', None, None
    if (body.get('ref') != 'refs/heads/' + ledger['branch'] or
            body['object'].get('type') != 'commit' or body['object'].get('sha') != ledger['head_sha']):
        return 'mismatch', None, None
    if ledger['step'] == 'branch':
        require(set(table) == used, 'unexpected_reconcile_get')
        return 'matched', body, None
    candidates = []
    head = quote(repo.split('/')[0] + ':' + ledger['branch'], safe='')
    for page in range(1, 101):
        row, missing = get('/pulls?state=all&head=' + head + '&per_page=100&page=' + str(page), page)
        if row is None:
            return 'unknown', None, missing
        items = row['body']
        if row['status'] != 200 or not isinstance(items, list) or len(items) > 100:
            return 'unknown', None, None
        for item in items:
            if not isinstance(item, dict) or type(item.get('number')) is not int or item['number'] <= 0:
                return 'unknown', None, None
        candidates.extend(items)
        if len(items) < 100:
            break
    else:
        return 'unknown', None, None
    if not candidates:
        return 'absent', None, None
    if len(candidates) != 1:
        return 'mismatch', None, None
    number = candidates[0]['number']
    row, missing = get('/pulls/' + str(number))
    if row is None:
        return 'unknown', None, missing
    data = row['body']
    if row['status'] != 200 or not isinstance(data, dict):
        return 'unknown', None, None
    if not {'number', 'head', 'base', 'state', 'draft', 'merged', 'title', 'body',
            'maintainer_can_modify'} <= set(data):
        return 'unknown', None, None
    require(set(table) == used, 'unexpected_reconcile_get')
    # Never convert a UI merge into an agent merge receipt.
    if data.get('merged') is True:
        return 'unknown', None, 'external-merge'
    try:
        native.check_pr(ledger, data)
    except (ValueError, TypeError, KeyError):
        return 'mismatch', None, None
    args = native.publication_request(ledger)['arguments']
    if (data.get('number') != number or data.get('merged') is not False or
            any(data.get(key) != args[key] for key in ('title', 'body', 'draft', 'maintainer_can_modify'))):
        return 'mismatch', None, None
    # The query's candidate must identify the same PR and pinned refs as detail.
    candidate = candidates[0]
    for key in ('head', 'base'):
        left, right = candidate.get(key), data.get(key)
        if (not isinstance(left, dict) or not isinstance(right, dict) or
                not isinstance(left.get('repo'), dict) or not isinstance(right.get('repo'), dict)):
            return 'unknown', None, None
        if (any(left.get(k) != right.get(k) for k in ('ref', 'sha')) or
                left['repo'].get('full_name') != right['repo'].get('full_name')):
            return 'mismatch', None, None
    # List responses need not contain detail-only maintainer_can_modify or every
    # incidental repository field. UI metadata still must match the original
    # request in the authoritative detail, and list metadata must agree with it.
    for key in ('state', 'draft', 'title', 'body'):
        if key not in candidate:
            return 'unknown', None, None
        if candidate[key] != data[key]:
            return 'mismatch', None, None
    if 'maintainer_can_modify' in candidate and candidate['maintainer_can_modify'] != data['maintainer_can_modify']:
        return 'mismatch', None, None
    return 'matched', data, None


def inventory(records):
    """Pin all old transport bytes and parent attempts, including diagnostics."""
    names = set(os.listdir(records.fd)) - {'claim', 'head.json'}
    require(len(names) < transport.MAX_OPERATIONS * 6, 'receipt_limit')
    require(not names & {'inflight.json', 'head.next'}, 'inflight_requires_reconciliation')
    found = {name: transport.digest(records.read(name)) for name in sorted(names)}
    for name in os.listdir(records.run_fd):
        if name.startswith('parent-accept-'):
            require(name.endswith('.json') and transport.HEX.fullmatch(name[14:-5]), 'unknown_accept_attempt')
            found['../' + name] = transport.digest(records.read(name, run=True))
    return found


def validate_history(records):
    """Check every preserved native input/output before freezing their hashes."""
    for name in os.listdir(records.fd):
        if not name.endswith('.complete.json'):
            continue
        receipt = records.optional(name)
        transport.envelope(records, receipt)
        records.read(receipt['operation_id'] + '.stderr')
        if receipt['operation'] in ('accept', 'reconcile'):
            require(transport.digest(records.read(receipt['operation_id'] + '.response.json',
                                                  transport.MAX_RESPONSE)) == receipt['response_sha256'])


def validate_bundle(records, previous, ledger, raw, approval_hash, journal_hash):
    bundle = transport.parse(raw)
    source, job = original(records, previous, ledger)
    required = {'version', 'run_id', 'request_id', 'target', 'tool_arguments_sha256',
                'approval_sha256', 'journal_sha256', 'previous_receipt_sha256', 'responses'}
    require(isinstance(bundle, dict) and set(bundle) == required and bundle['version'] == VERSION,
            'invalid_reconcile_evidence')
    require(bundle['run_id'] == ledger['run_id'] and bundle['request_id'] == previous['request_id'] and
            bundle['target'] == target(ledger) and bundle['tool_arguments_sha256'] == tool_digest(job) and
            bundle['approval_sha256'] == approval_hash and bundle['journal_sha256'] == journal_hash and
            bundle['previous_receipt_sha256'] == transport.digest(
                records.read(previous['operation_id'] + '.complete.json')), 'reconcile_binding_mismatch')
    return bundle, source, job


def verify(records, complete):
    """Shared by transport, parent, readers, park and external-merge evidence."""
    from harness import parent_commands as parent
    parent.receipt_identity(complete, records.directory.name)
    run, request = complete['run_id'], complete['request_id']
    op = operation(run, request)
    require(complete['operation'] == 'reconcile' and complete['operation_id'] == op and
            complete['native_exit_code'] == 0)
    begin_raw = records.read(op + '.begin.json')
    require(transport.digest(begin_raw) == complete['begin_sha256'])
    begin = transport.parse(begin_raw)
    require(isinstance(begin, dict) and all(begin.get(k) == complete.get(k) for k in
            ('run_id', 'operation', 'operation_id', 'request_id', 'response_sha256', 'started_at', 'link')))
    link = begin['link']
    require(isinstance(link, dict) and set(link) == {
        'previous_operation_id', 'previous_receipt_sha256', 'request_operation_id',
        'tool_arguments_sha256', 'approval_sha256', 'evidence_sha256', 'snapshot_sha256', 'history'})
    require(isinstance(link['history'], dict) and all(
        isinstance(value, str) and transport.HEX.fullmatch(value)
        for key, value in link.items() if key != 'history'))
    previous = records.optional(link['previous_operation_id'] + '.complete.json')
    require(isinstance(previous, dict) and previous['operation'] == 'accept' and
            previous['request_id'] == request and previous['native_exit_code'] != 0)
    require(transport.digest(records.read(previous['operation_id'] + '.complete.json')) ==
            link['previous_receipt_sha256'])
    snapshot = records.read(op + '.before.json')
    require(transport.digest(snapshot) == link['snapshot_sha256'])
    before = transport.parse(snapshot)
    before_raw = before['journal'].encode('utf-8')
    ledger = transport.parse(before_raw)
    require(transport.digest(before_raw) == begin['journal_sha256'] == previous['journal_sha256'])
    require(transport.digest(records.read('github-approved.json', run=True)) == link['approval_sha256'])
    raw = records.read(op + '.response.json', transport.MAX_RESPONSE)
    require(transport.digest(raw) == complete['response_sha256'] == link['evidence_sha256'])
    bundle, source, job = validate_bundle(records, previous, ledger, raw,
                                         link['approval_sha256'], begin['journal_sha256'])
    require(source == link['request_operation_id'] and tool_digest(job) == link['tool_arguments_sha256'])
    for name, expected in link['history'].items():
        in_run = name.startswith('../parent-accept-')
        leaf = name[3:] if in_run else name
        require('/' not in leaf and leaf not in ('head.json', 'claim', 'inflight.json', 'head.next'))
        if in_run:
            require(leaf.endswith('.json') and transport.HEX.fullmatch(leaf[14:-5]))
        else:
            stem, separator, suffix = leaf.partition('.')
            require(separator and transport.HEX.fullmatch(stem) and suffix in (
                'begin.json', 'complete.json', 'response.json', 'before.json', 'stdout', 'stderr'))
        require(transport.digest(records.read(leaf, run=in_run)) == expected)
    decision, data, missing = observe(ledger, bundle)
    require(decision == 'matched' and missing is None)
    output = records.read(op + '.stdout')
    require(records.read(op + '.stderr') == b'')
    require(len(output) == complete['bytes'] and transport.digest(output) == complete['sha256'])
    payload = transport.parse(output)
    after_raw = payload['reconciliation']['journal'].encode('utf-8')
    after = transport.parse(after_raw)
    marker = {'operation_id': op, 'link_sha256': transport.digest(transport.encode(link))}
    require(transport.digest(after_raw) == complete['journal_sha256'] and
            after.get('reconciliations', {}).get(request) == marker and
            payload.get('run_id') == run and payload.get('github') == native.summary(after))
    current, _ = transport.journal(records)
    require(current.get('reconciliations', {}).get(request) == marker)
    expected = copy.deepcopy(ledger)
    native.accept(expected, data)  # Pure validator/state transition; never legacy CLI.
    event = expected['events'][-1]
    event['time'] = after['events'][-1]['time']
    expected.setdefault('reconciliations', {})[request] = marker
    if payload.get('request') is not None:
        job = payload['request']
        require({k: job[k] for k in ('tool', 'arguments')} == native.publication_request(expected) and
                transport.HEX.fullmatch(job['request_id']))
        expected['pending_request_id'] = job['request_id']
        expected['pending_write'] = job['tool'] != native.TOOLS['fetch']
    else:
        expected['status'] = 'awaiting_ci' if expected.get('pr_number') else 'failed'
        expected['error'] = 'Reconciled observation retained; publication time is insufficient.'
    require(after == expected)
    parent.receipt_identity(previous, run)


def reconcile(result, run, request, evidence_file, evidence_sha256):
    from harness import parent_commands as parent
    from harness.worktree_park import _lock, Stop as ParkStop
    parent.require(isinstance(request, str) and transport.HEX.fullmatch(request), 'invalid_request_id')
    selected, directory, ledger = parent.context(run)
    raw = parent.response_snapshot(selected, evidence_file, evidence_sha256)
    parent.external_not_owned(selected, directory)
    result.update(stage='inspect', status='needs_reconciliation', decision='unknown')
    # Preflight precedes lock creation. Input never reopens after its snapshot.
    saved, completes = parent.evidence(run, ledger)
    op = operation(run, request)
    parent.require(op not in (completes or {}), 'already_reconciled')
    parent.require(saved is not None, 'reconcile_requires_completed_error')
    parent.require(saved[0]['operation'] == 'accept' and saved[0]['request_id'] == request and
                   saved[0]['native_exit_code'] != 0 and ledger.get('pending_request_id') == request and
                   ledger.get('pending_write') is True and ledger.get('status') == 'needs_reconciliation' and
                   not ledger.get('merge_sha') and not ledger.get('pr_number'), 'reconcile_requires_completed_error')
    parent.minimum_write_seconds(result['minimum_write_seconds'])
    parent.deadline_gate(result, ledger)  # Validates the deadline; permits elapsed observations.
    parent.native_lock_preflight(selected, directory)
    records = transport.Records(run, create=False)
    try:
        # Same source -> GitHub order as native and park. Transport claim is
        # nonblocking and no connector/network wait exists inside this operation.
        with ExitStack() as stack:
            effects = result['side_effects']
            effects.setdefault('created_locks', [])
            checks = [stack.enter_context(_lock(selected, selected.project_lock_path, effects)),
                      stack.enter_context(_lock(selected, directory / 'github.lock', effects))]
            stack.enter_context(records.claim())
            selected, directory, current = parent.context(run)
            parent.external_not_owned(selected, directory)
            native.validate_journal(directory, current, selected=selected)
            parent.require(native.load_config()['enabled'], 'side_effects_disabled')
            ledger, journal_hash = transport.journal(records)
            parent.require(ledger == current and transport.verify_head(records, journal_hash) == saved[0],
                           'reconcile_state_changed')
            approval_hash = transport.digest(records.read('github-approved.json', run=True))
            bundle, source, job = validate_bundle(records, saved[0], ledger, raw, approval_hash, journal_hash)
            decision, data, missing = observe(ledger, bundle)
            result['decision'] = decision
            if decision != 'matched':
                result['code'] = 'reconcile_' + decision
                if missing == 'external-merge':
                    result['required_route'] = ['agent-git-proof-build', 'agent-git-external-merge']
                elif missing:
                    result['next_action'] = {'action': 'collect_get', 'trusted_parent_only': True,
                                             'method': 'GET', 'url': missing,
                                             'reason': 'Save exact private evidence; no automatic query or retry.'}
                return
            validate_history(records)
            snapshot = transport.encode({'journal': records.read('github.json', run=True).decode('utf-8'),
                                         'report': records.read('report.json', run=True).decode('utf-8')})
            parent.require(len(snapshot) <= transport.MAX_RESULT, 'record_too_large')
            link = {'previous_operation_id': saved[0]['operation_id'],
                    'previous_receipt_sha256': bundle['previous_receipt_sha256'],
                    'request_operation_id': source, 'tool_arguments_sha256': tool_digest(job),
                    'approval_sha256': approval_hash, 'evidence_sha256': evidence_sha256,
                    'snapshot_sha256': transport.digest(snapshot),
                    'history': inventory(records)}
            begin = {'run_id': run, 'operation': 'reconcile', 'operation_id': op, 'request_id': request,
                     'response_sha256': evidence_sha256, 'journal_sha256': journal_hash,
                     'started_at': time.time(), 'link': link}
            for check in checks:
                check()
            result.update(executed=True, stage='reconcile_intent')
            effects.update(transport_invoked=True, native_invoked=False, journal_writes=False,
                           read_only=False, writes=True)

            def write(name, content):
                records.write(name, content, created=lambda: effects['created'].append(
                    str(directory / 'transport' / name)))
                parent.require(records.read(name) == content, 'reconcile_readback_mismatch')

            write('inflight.json', transport.encode(begin))
            write(op + '.begin.json', transport.encode(begin))
            write(op + '.before.json', snapshot)
            write(op + '.response.json', raw)
            after = copy.deepcopy(ledger)
            result['stage'] = 'native_reconcile'
            effects['native_invoked'] = True
            native.accept(after, data)
            after.setdefault('reconciliations', {})[request] = {
                'operation_id': op, 'link_sha256': transport.digest(transport.encode(link))}

            def time_available():
                parent.deadline_gate(result, after)
                remaining = result['publish_remaining_seconds']
                return remaining > 0 and (after['step'] != 'create_pr' or
                                          remaining >= result['minimum_write_seconds'])

            def stop_publication():
                after.pop('pending_request_id', None)
                after.pop('pending_write', None)
                after.update(status='awaiting_ci' if after.get('pr_number') else 'failed',
                             error='Reconciled observation retained; publication time is insufficient.')

            def save():
                effects['journal_writes'] = True
                native.save(directory, after)
                report = transport.parse(records.read('report.json', run=True))
                prior = transport.parse(transport.parse(snapshot)['report'].encode('utf-8'))
                parent.require(isinstance(report, dict) and report.get('github') == native.summary(after) and
                    report.get('status') == {'failed': 'failed', 'awaiting_ci': 'awaiting_ci'}.get(
                        after['status'], 'awaiting_github') and
                    parent.ExternalMerge.report_identity(report) == parent.ExternalMerge.report_identity(prior) and
                    report.get('events', [])[:len(prior.get('events', []))] == prior.get('events', []),
                    'reconcile_report_readback_mismatch')
                parent.require(transport.journal(records)[0] == after, 'reconcile_journal_readback_mismatch')

            following = native.request(after) if time_available() else None
            if following is None:
                stop_publication()
            for check in checks:
                check()
            save()
            # Time spent validating/fsyncing cannot grant a late next dispatch.
            if following is not None and not time_available():
                following = None
                stop_publication()
                save()
            final, after_hash = transport.journal(records)
            parent.require(final == after, 'reconcile_journal_readback_mismatch')
            output = transport.encode({'run_id': run, 'github': native.summary(after), 'request': following,
                                       'reconciliation': {'operation_id': op, 'journal': records.read(
                                           'github.json', run=True).decode('utf-8')}})
            parent.require(len(output) <= transport.MAX_RESULT, 'native_output_too_large')
            write(op + '.stdout', output)
            write(op + '.stderr', b'')
            complete = {**begin, 'journal_sha256': after_hash, 'bytes': len(output),
                        'begin_sha256': transport.digest(transport.encode(begin)),
                        'sha256': transport.digest(output), 'native_exit_code': 0, 'ended_at': time.time()}
            result['stage'] = 'reconcile_complete'
            write(op + '.complete.json', transport.encode(complete))
            verify(records, complete)
            for check in checks:
                check()
            records.head(complete)
            records.ready()
            os.unlink('inflight.json', dir_fd=records.fd)
            effects['removed'].append(str(directory / 'transport' / 'inflight.json'))
            os.fsync(records.fd)
            envelope = transport.envelope(records, complete)
        # Existing exporter enforces deadline again, including time lost here.
        parent.finish(result, run, envelope, 0, op, evidence_sha256)
        result['reconcile_operation_id'] = op
    except ParkStop as exc:
        raise parent.Stop(str(exc)) from None
    finally:
        records.close()
