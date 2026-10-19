"""Trusted-parent, evidence-bound completion outbox; no execution authority.

Morning reports and their publication journals are never opened for writing.
The GitHub caller must release project/journal locks before entering Store.lock.
All HTTP uses the existing private inbox transport; only allowlisted payloads
cross that boundary. Recovery never renews or consumes an approval.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat

from harness import git_publish as github, improvements as imp, storage, workflow
from harness import improvement_report as contract

VERSION = 'improvement-completion-v1'
MAX_BYTES = 16384
REPOSITORY = '21in7/TavernofSoul'
FIELDS = {'version', 'proposal_id', 'status', 'pr_url', 'merge_sha', 'completed_at', 'digest'}
STATES = {'ready', 'sending', 'unknown', 'conflict', 'delivered'}
REASONS = {'prepared', 'post_started', 'post_failed', 'server_conflict', 'readback_mismatch',
           'verified_readback', 'readback_absent', 'delivery_unverified', 'delivery_timeout',
           'delivery_interrupted'}


def validate_payload(value):
    """Exact wire object, including independently recomputed canonical digest."""
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('Invalid completion fields.')
    imp._proposal_id(value['proposal_id'])
    if (value['version'] != VERSION or value['status'] != 'completed' or
            not isinstance(value['pr_url'], str) or not re.fullmatch(
                r'https://github\.com/21in7/TavernofSoul/pull/[1-9][0-9]*', value['pr_url'])):
        raise ValueError('Invalid completion identity.')
    github.valid_sha(value['merge_sha'])
    timestamp = value['completed_at']
    if not isinstance(timestamp, str):
        raise ValueError('Invalid completion time.')
    instant = dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if instant.utcoffset() != dt.timedelta(0) or 'T' not in timestamp:
        raise ValueError('Completion time must be UTC with timezone.')
    body = {k: v for k, v in value.items() if k != 'digest'}
    if value['digest'] != contract.digest(body) or len(contract.canonical_json(value)) > MAX_BYTES:
        raise ValueError('Invalid completion digest or size.')
    return value


def _disabled():
    return any(os.environ.get(name) for name in (
        'TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
        'TAVERN_IMPROVEMENT_UNATTENDED')) or os.environ.get('READ_ONLY') == '1' or os.environ.get('GIT') == '0'


def _claims(store, run_id):
    """Only exact private claim filenames and signed run associations are authority.

    Unrelated normal runs do not open the authority key or inbox configuration.
    Directory descriptors prevent symlink traversal even during enumeration.
    """
    directory = store.path('claims')
    try:
        fd = store.policy.fs.open_directory(directory)
    except FileNotFoundError:
        return []
    try:
        names = os.listdir(fd)
    finally:
        os.close(fd)
    if len(names) > 4096:
        raise ValueError('Claim collection exceeds its bound.')
    linked = []
    for name in sorted(names):
        if not re.fullmatch(r'IMP-[0-9a-f]{16}\.json', name):
            raise ValueError('Invalid private claim name.')
        raw = store.read('claims/' + name)
        if raw.get('run_id') != run_id:
            continue
        claim = store.verify(raw)
        if claim.get('proposal_id') != name[:-5]:
            raise ValueError('Claim identity differs from its private record.')
        linked.append(claim)
    return linked


def _run_records(store, run_id):
    selected = store.policy
    # Completion is intentionally stricter than legacy workflow lookup: the
    # currently selected root must contain this run. Never try another root.
    root = selected.workflow_root(local_default=github.local_reports())
    directory = root / run_id
    selected.check_ready()
    fd = selected.fs.open_directory(directory)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Completion requires a private owned run directory.')
    finally:
        os.close(fd)
    selected.validate_run_directory(directory, local_default=github.local_reports())
    def read(name):
        path = selected.record_path(directory, name, local_default=github.local_reports())
        return imp._json_file(path)
    return directory, read('report.json'), read('github.json'), read('github-approved.json')


def _evidence(store, run_id, claims):
    directory, report, ledger, publication = _run_records(store, run_id)
    cfg = github.validate_config(ledger['config'])
    if (cfg != github.load_config() or cfg['enabled'] is not True or cfg['repository'] != REPOSITORY or
            report.get('run_id') != run_id or report.get('status') != 'passed' or
            report.get('read_only') is not False or report.get('simulated') is not False or
            report.get('no_git') is not False or report.get('github_enabled') is not True):
        raise ValueError('Run is not a completed publishing workflow.')
    github.validate_journal(directory, ledger, selected=store.policy)
    if (ledger.get('status') != 'merged' or ledger.get('step') != 'done' or
            ledger.get('merge_status') != 'merged' or not github.cleanup_complete(ledger)):
        raise ValueError('Merge and cleanup are incomplete.')
    github.valid_sha(ledger['merge_sha'])
    github.valid_sha(ledger['head_sha'])
    number = ledger.get('pr_number')
    if type(number) is not int or number <= 0:
        raise ValueError('Invalid completed PR number.')
    if ledger.get('pr_url') != 'https://github.com/' + REPOSITORY + '/pull/' + str(number):
        raise ValueError('Completed PR URL differs from its repository and number.')
    expected = {name: 'success' for name in github.REQUIRED}
    proof = ledger.get('cleanup_proof', {})
    if (ledger.get('checks') != expected or proof.get('verified') is not True or
            proof.get('head_sha') != ledger['head_sha'] or proof.get('merge_sha') != ledger['merge_sha'] or
            proof.get('checks') != expected or report.get('github') != github.summary(ledger)):
        raise ValueError('Pinned CI and verified cleanup proof are required.')
    changed, scope = report['changed_files'], report['scope']
    contract.validate_scope_paths(scope)
    if (not changed or len(set(changed)) != len(changed) or set(changed) - set(scope) or
            set(report.get('applied', [])) != set(changed) or
            set(publication['files']) != set(changed)):
        raise ValueError('Actual publication differs from the applied scope.')
    review = workflow.parse_review(json.dumps(report['review']), scope, changed)
    if review['verdict'] != 'approved':
        raise ValueError('Actual implementation review was not approved.')
    checks = report.get('delivery_validation')
    required = report.get('required_checks')
    if (not isinstance(checks, list) or not checks or not isinstance(required, list) or not required or
            len(set(required)) != len(required) or
            set(required) - set(workflow.CHECKS) or
            set(item['command'] for item in checks) != set(required) or len(checks) != len(required) or
            any(item.get('status') != 'passed' or type(item.get('exit_code')) is not int or
                item['exit_code'] != 0 or
                not workflow.failure_feedback.check_groups_passed(item.get('checks')) for item in checks)):
        raise ValueError('Actual final validation evidence is incomplete.')
    authorized = set()
    for claim in claims:
        pid = imp._proposal_id(claim['proposal_id'])
        record = imp._eligible(store, pid)  # persisted review only; NEVER _fresh/_authorization
        approval = store.verify(store.read('approvals/' + pid + '.json'))
        decision = store.read('decisions/' + pid + '.json')
        context = imp._discovery_context(store, record)
        fields = {'version', 'authority', 'proposal_id', 'proposal_digest', 'review_digest',
                  'source_fingerprints', 'allowed_edit_files', 'publication', 'instruction',
                  'issued_at', 'expires_at', 'authorization_id', 'consumption'}
        if context is not None:
            fields.add('discovery_fingerprint')
        claim_fields = {'version', 'proposal_id', 'authorization_id', 'proposal_digest',
                        'task_digest', 'status', 'at', 'run_id', 'claim_id'}
        if claim.get('status') == 'consumed':
            claim_fields.add('workflow_status')
        if (set(claim) != claim_fields or claim['version'] != 'improvement-claim-v1' or
                claim['run_id'] != run_id or claim['status'] not in ('running', 'consumed') or
                (claim['status'] == 'consumed' and claim['workflow_status'] not in (
                    'awaiting_github', 'awaiting_ci', 'cleanup_pending', 'needs_reconciliation',
                    'passed', 'failed', 'interrupted')) or
                not re.fullmatch(r'[0-9a-f]{48}', claim['claim_id']) or
                not re.fullmatch(r'[0-9a-f]{64}', claim['task_digest']) or
                set(approval) != fields or approval['version'] != 'improvement-approval-v1' or
                approval['authority'] != 'trusted-parent' or approval['proposal_id'] != pid or
                approval['proposal_digest'] != record['digest'] or claim['proposal_digest'] != record['digest'] or
                approval['review_digest'] != contract.digest(record['review']) or
                approval['source_fingerprints'] != record['source_fingerprints'] or
                approval['allowed_edit_files'] != record['candidate']['edit_files'] or
                approval.get('discovery_fingerprint') != context or
                approval['publication'] != imp.PUBLICATION or approval['consumption'] != 'unconsumed' or
                not isinstance(approval['instruction'], str) or not approval['instruction'].strip() or
                not re.fullmatch(r'[0-9a-f]{48}', approval['authorization_id']) or
                claim['authorization_id'] != approval['authorization_id'] or
                decision.get('status') != 'approved' or
                decision.get('authorization_id') != approval['authorization_id']):
            raise ValueError('Signed claim and approval do not bind this exact completed proposal.')
        allowed = contract.validate_scope_paths(approval['allowed_edit_files'])
        issued = dt.datetime.fromisoformat(approval['issued_at'])
        expires = dt.datetime.fromisoformat(approval['expires_at'])
        claimed = dt.datetime.fromisoformat(claim['at'])
        if (any(value.utcoffset() is None for value in (issued, expires, claimed)) or
                not issued <= claimed < expires or expires - issued > dt.timedelta(days=7)):
            raise ValueError('Claim was not made within the signed approval interval.')
        if set(allowed) - set(scope) or not set(allowed).intersection(changed):
            raise ValueError('Proposal scope has no reviewed applied change in this run.')
        # One claim's task is directly comparable. Multiple independently signed
        # run associations support an explicitly authorized bundle, without
        # inventing a combined task format or granting bundle approval authority.
        if len(claims) == 1:
            task_digest = hashlib.sha256(imp._task(record, approval).encode('utf-8')).hexdigest()
            if report.get('task_sha256') != claim['task_digest'] or task_digest != claim['task_digest']:
                raise ValueError('Workflow task differs from the claimed task.')
        authorized.update(allowed)
    if set(scope) != authorized or set(changed) - authorized:
        raise ValueError('Workflow scope exceeds the signed approvals.')
    return ledger


def _public(record):
    payload = record['payload']
    return dict({key: payload[key] for key in ('proposal_id', 'digest', 'pr_url')},
                status=record['state'], reason=record['reason'])


def _record(store, run_id, claim, ledger, now):
    name = 'completions/' + run_id + '/' + claim['proposal_id'] + '.json'
    if store.exists(name):
        record = store.read(name)
        if (set(record) != {'version', 'run_id', 'authorization_id', 'claim_id', 'payload', 'state', 'reason'} or
                record['version'] != 'completion-outbox-v1' or record['run_id'] != run_id or
                record['authorization_id'] != claim['authorization_id'] or record['claim_id'] != claim['claim_id'] or
                record['state'] not in STATES or record['reason'] not in REASONS):
            raise ValueError('Completion journal identity changed.')
        payload = validate_payload(record['payload'])
        if (payload['proposal_id'] != claim['proposal_id'] or payload['pr_url'] != ledger['pr_url'] or
                payload['merge_sha'] != ledger['merge_sha']):
            raise ValueError('Frozen completion differs from its completed run.')
    else:
        payload = {'version': VERSION, 'proposal_id': claim['proposal_id'], 'status': 'completed',
                   'pr_url': ledger['pr_url'], 'merge_sha': ledger['merge_sha'],
                   'completed_at': imp._now(now).astimezone(dt.timezone.utc).isoformat()}
        payload['digest'] = contract.digest(payload)
        validate_payload(payload)
        record = {'version': 'completion-outbox-v1', 'run_id': run_id,
                  'authorization_id': claim['authorization_id'], 'claim_id': claim['claim_id'],
                  'payload': payload, 'state': 'ready', 'reason': 'prepared'}
        store.write(name, record)  # canonical payload + journal, atomic/fsync/private BEFORE HTTP
    return name, record


def _deliver(store, name, record, transport, inbox_config, timeout, reconcile):
    def persist(state, reason):
        record.update(state=state, reason=reason)
        store.write(name, record)
    if record['state'] in ('delivered', 'conflict'):
        return _public(record)
    try:
        origin, token = imp._inbox_config(inbox_config)
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
                   'OAI-Sites-Authorization': 'Bearer ' + token}
        send = transport or imp.http_transport
        def request(method):
            path = '/api/completions'
            body = None
            if method == 'GET':
                path += '/' + record['payload']['proposal_id']
            else:
                body = contract.canonical_json(record['payload'])
            status, raw = send(method, origin, path, headers, body, timeout, MAX_BYTES)
            if type(status) is not int or not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
                raise ValueError('Invalid bounded completion response.')
            return status, raw
        def readback():
            code, raw = request('GET')
            if code == 404:
                return 'absent'
            if code != 200:
                raise ValueError('Completion readback failed.')
            received = validate_payload(contract.parse_json(raw, MAX_BYTES))
            if received != record['payload']:
                persist('conflict', 'readback_mismatch')
                return 'conflict'
            persist('delivered', 'verified_readback')
            return 'delivered'
        if record['state'] != 'ready' or reconcile:
            result = readback()
            if result != 'absent':
                return _public(record)
            if not reconcile:
                persist('unknown', 'readback_absent')
                return _public(record)
        persist('sending', 'post_started')  # unknown on process death; automatic recovery GET only
        code, _ = request('POST')
        if code == 409:
            persist('conflict', 'server_conflict')
        elif code not in (200, 201):
            persist('unknown', 'post_failed')
        elif readback() == 'absent':
            persist('unknown', 'readback_absent')
    except (Exception, KeyboardInterrupt) as exc:
        # Never persist raw response/exception/header/config values. Sending is
        # already durable even if this checkpoint itself cannot be written.
        reason = ('delivery_interrupted' if isinstance(exc, KeyboardInterrupt) else
                  'delivery_timeout' if isinstance(exc, TimeoutError) else 'delivery_unverified')
        persist('unknown', reason)
    return _public(record)


def complete_run(run_id, *, selected=None, transport=None, inbox_config=None, now=None, reconcile=False):
    """Resume only this run's completion; fail separately from workflow success."""
    if _disabled():
        return {'status': 'disabled', 'completions': []}
    try:
        if not isinstance(run_id, str) or not storage.RUN_ID.fullmatch(run_id):
            raise ValueError('Invalid completion run ID.')
        store = imp.Store(selected)
        # Avoid creating even an improvement lock for unrelated normal work.
        if not _claims(store, run_id):
            return {'status': 'not_applicable', 'completions': []}
        with store.lock():
            claims = _claims(store, run_id)
            if not claims:
                return {'status': 'not_applicable', 'completions': []}
            ledger = _evidence(store, run_id, claims)
            records = [_record(store, run_id, claim, ledger, now) for claim in claims]
            # Delivered runs never read credentials/configuration or use HTTP.
            if all(record['state'] in ('delivered', 'conflict') for _, record in records):
                results = [_public(record) for _, record in records]
            else:
                timeout = min(imp.load_config()['limits']['delivery_timeout_seconds'], 30)
                if type(timeout) is not int or timeout <= 0:
                    raise ValueError('Invalid completion timeout.')
                config_path = inbox_config or imp.ROOT / 'logs/harness/improvement-inbox.json'
                results = [_deliver(store, name, record, transport, config_path, timeout, reconcile)
                           for name, record in records]
            return {'status': 'delivered' if all(r['status'] == 'delivered' for r in results) else 'pending',
                    'completions': results}
    except (Exception, KeyboardInterrupt):
        return {'status': 'blocked', 'reason': 'completion_evidence_or_storage_invalid', 'completions': []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--reconcile', action='store_true')
    args = parser.parse_args(argv)
    result = complete_run(args.run_id, reconcile=args.reconcile)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['status'] in ('delivered', 'not_applicable') else 1


if __name__ == '__main__':
    raise SystemExit(main())
