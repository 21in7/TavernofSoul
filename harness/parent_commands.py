"""A1 trusted-parent commands. JSON on stdout is private parent consumption.

No connector, retry, reconciliation, CI resume, merge or archive implementation
lives here. Native journals/receipts are read-only except through native entry.
"""
import argparse
import base64
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import fcntl
import math
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys

from harness import git_cleanup, git_publish as native, git_transport as transport

VERSION = 'parent-commands-v1'
COMMANDS = ('agent-git-next', 'agent-git-accept-file', 'agent-worktree-park', 'storage-path')
MAX_WIRE = transport.INLINE_BYTES * 6 + 16384
PROCESS_TIMEOUT = 120


class Stop(ValueError):
    """A fixed public reason code; never exception text from a private source."""


def require(condition, code):
    if not condition:
        raise Stop(code)


def result_for(command, run):
    return {'version': VERSION, 'command': command,
            'run': run if isinstance(run, str) and native.RUN_ID.fullmatch(run) else None,
            'status': 'failed', 'stage': 'authorization', 'code': None,
            'executed': False, 'native_exit_code': None,
            'side_effects': {'transport_invoked': False, 'native_invoked': False, 'created': [], 'removed': []},
            'next_action': {'action': 'stop', 'approval_required': True,
                            'reason': 'Review retained evidence through the approved recovery procedure; no automatic retry.'}}


def authorize():
    transport.trusted_parent()
    require(os.environ.get('READ_ONLY') != '1' and os.environ.get('GIT') != '0' and
            not any(os.environ.get(key) for key in ('TAVERN_WORKFLOW_DEMO', 'TAVERN_NO_GIT')),
            'side_effects_disabled')


def identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_nlink, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def attached(selected, path, parent, fd, before, private_parent=False):
    fresh = selected.fs.open_directory(path.parent)
    try:
        a, b = os.fstat(parent), os.fstat(fresh)
        require((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino), 'input_directory_changed')
        if private_parent:
            transport.private(a, directory=True)
            transport.private(b, directory=True)
    finally:
        os.close(fresh)
    require(identity(before) == identity(os.fstat(fd)) ==
            identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)),
            'input_changed')


@contextmanager
def private_input(selected, path, limit, private_parent=False):
    # Validate the original spelling before Path normalizes it.
    from harness.storage import _absolute
    path = _absolute(path, 'Private input')
    parent = selected.fs.open_directory(path.parent)
    fd = None
    try:
        if private_parent:
            transport.private(os.fstat(parent), directory=True)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(fd)
        transport.private(before)
        require(before.st_size <= limit, 'input_too_large')
        with os.fdopen(os.dup(fd), 'rb') as handle:
            raw = handle.read(limit + 1)
        require(len(raw) == before.st_size and len(raw) <= limit, 'input_size_changed')
        check = lambda: attached(selected, path, parent, fd, before, private_parent)
        check()
        yield raw, check
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def context(run):
    require(isinstance(run, str) and native.RUN_ID.fullmatch(run), 'invalid_run_id')
    selected = native.storage_policy()
    selected.check_ready()
    directory = native.directory_for(run, selected=selected)
    selected.validate_run_directory(directory, local_default=native.local_reports())
    fd = selected.fs.open_directory(directory)
    try:
        transport.private(os.fstat(fd), directory=True)
    finally:
        os.close(fd)
    values = []
    for name in ('github.json', 'report.json'):
        path = selected.record_path(directory, name, local_default=native.local_reports())
        with private_input(selected, path, transport.MAX_RESULT) as (raw, _):
            value = transport.parse(raw)
        require(isinstance(value, dict) and value.get('run_id') == run, 'run_identity_mismatch')
        values.append(value)
    ledger, report = values
    require(isinstance(ledger.get('config'), dict) and not report.get('demo') and
            git_cleanup.enabled(report, ledger['config']),
            'side_effects_disabled')
    return selected, directory, ledger


def operation(command, run, request=None):
    return transport.digest(transport.encode([run, command, request]))


def receipt_identity(value, run):
    require(isinstance(value, dict) and value.get('run_id') == run and
            value.get('operation') in ('request', 'accept'), 'receipt_identity_mismatch')
    request = value.get('request_id')
    require((value['operation'] == 'request' and request is None and value.get('response_sha256') is None) or
            (value['operation'] == 'accept' and isinstance(request, str) and transport.HEX.fullmatch(request) and
             isinstance(value.get('response_sha256'), str) and transport.HEX.fullmatch(value['response_sha256'])),
            'receipt_request_mismatch')
    require(value.get('operation_id') == operation(value['operation'], run, request) and
            isinstance(value.get('journal_sha256'), str) and transport.HEX.fullmatch(value['journal_sha256']) and
            type(value.get('started_at')) in (int, float) and math.isfinite(value['started_at']),
            'receipt_identity_mismatch')


def evidence(run, ledger):
    """Read existing receipts, never create a transport directory or a request.

    A completed request is evidence of possible connector dispatch, not permission
    to export it again. The native claim remains the final race authority.
    """
    try:
        records = transport.Records(run, create=False)
    except FileNotFoundError:
        require(not ledger.get('pending_request_id') and not ledger.get('pending_write'),
                'legacy_pending_requires_reconciliation')
        return None, None
    try:
        names = set(os.listdir(records.fd))
        require(len(names) <= transport.MAX_OPERATIONS * 6, 'receipt_limit')
        require('inflight.json' not in names and 'head.next' not in names, 'inflight_requires_reconciliation')
        ids = set()
        suffixes = ('.begin.json', '.complete.json', '.stdout', '.stderr', '.response.json')
        for name in names - {'head.json', 'claim'}:
            suffix = next((s for s in suffixes if name.endswith(s)), None)
            require(suffix is not None and transport.HEX.fullmatch(name[:-len(suffix)]), 'unknown_transport_record')
            ids.add(name[:-len(suffix)])
        require(len(ids) <= transport.MAX_OPERATIONS, 'receipt_limit')
        completes = {}
        for op in sorted(ids):
            begin, complete = records.optional(op + '.begin.json'), records.optional(op + '.complete.json')
            require(begin is not None and complete is not None, 'incomplete_receipt')
            receipt_identity(begin, run)
            receipt_identity(complete, run)
            require(begin['operation_id'] == op and all(begin.get(key) == complete.get(key) for key in
                    ('operation', 'request_id', 'response_sha256', 'started_at')),
                    'receipt_identity_mismatch')
            require(type(complete.get('bytes')) is int and 0 < complete['bytes'] <= transport.MAX_RESULT and
                    isinstance(complete.get('sha256'), str) and transport.HEX.fullmatch(complete['sha256']) and
                    type(complete.get('native_exit_code')) is int and complete['native_exit_code'] >= 0 and
                    type(complete.get('ended_at')) in (int, float) and math.isfinite(complete['ended_at']) and
                    complete['ended_at'] >= complete['started_at'], 'invalid_complete_receipt')
            completes[op] = complete
        _, journal_hash = transport.journal(records)
        head = records.optional('head.json')
        if not completes:
            require(head is None and not ledger.get('pending_request_id') and not ledger.get('pending_write'),
                    'legacy_transport_mismatch')
            return None, None
        require(operation('request', run) in completes and isinstance(head, dict), 'transport_head_missing')
        receipt_identity(head, run)
        require(head == completes.get(head['operation_id']) and head['journal_sha256'] == journal_hash and
                all(row['ended_at'] <= head['ended_at'] for row in completes.values()),
                'transport_head_mismatch')
        # Reuse native checks after validating every path-bearing identity.
        require(transport.verify_head(records, journal_hash) == head, 'transport_head_mismatch')
        envelope = transport.envelope(records, head)
        raw = records.read(head['operation_id'] + '.stdout')
        payload = transport.parse(raw)
        require(isinstance(payload, dict), 'native_result_invalid')
        failed_without_run = (payload.get('run_id') is None and payload.get('status') == 'failed' and
                              head['native_exit_code'] != 0 and 'request' not in payload)
        require(payload.get('run_id') == run or failed_without_run, 'native_run_mismatch')
        request = payload.get('request')
        # Native response validation failures retain the accepted pending ID.
        # This terminal receipt proves failure, never a dispatchable request.
        status = payload.get('github', {}).get('status', payload.get('status'))
        terminal_pending = (request is None and status in ('failed', 'needs_reconciliation', 'awaiting_ci') and
                            status == ledger.get('status') and head['operation'] == 'accept' and
                            ledger.get('pending_request_id') == head['request_id'] and
                            ('pending_write' not in ledger or type(ledger['pending_write']) is bool))
        require(failed_without_run or terminal_pending or (request is None and not ledger.get('pending_request_id') and
                                      not ledger.get('pending_write')) or
                (isinstance(request, dict) and isinstance(request.get('request_id'), str) and
                 transport.HEX.fullmatch(request['request_id']) and
                 request['request_id'] == ledger.get('pending_request_id')), 'pending_request_mismatch')
        if isinstance(request, dict) and 'pending_write' in ledger:
            require(type(ledger['pending_write']) is bool and request.get('tool') in native.TOOLS.values() and
                    ledger['pending_write'] == (request['tool'] != native.TOOLS['fetch']),
                    'pending_write_mismatch')
        if head['operation'] == 'accept':
            response = records.read(head['operation_id'] + '.response.json', transport.MAX_RESPONSE)
            require(transport.digest(response) == head['response_sha256'], 'receipt_response_mismatch')
        return (head, envelope, payload), completes
    finally:
        records.close()


def premerge(ledger):
    require(not ledger.get('merge_sha') and ledger.get('step') not in ('merge', 'done', 'cleanup_execute') and
            not str(ledger.get('step', '')).startswith('cleanup_'), 'a2_or_merge_requires_approval')
    require(ledger.get('status') in ('awaiting_connector', 'waiting_for_ci'),
            'native_state_requires_reconciliation')


def accept_request(result, saved, request_id):
    """A pending ID alone cannot authorize continuing a failed native result."""
    head, _, payload = saved
    status = payload.get('github', {}).get('status', payload.get('status'))
    if head['native_exit_code'] != 0 or status not in ('awaiting_connector', 'waiting_for_ci'):
        result['native_exit_code'] = head['native_exit_code']
        result['status'] = status if status in ('failed', 'needs_reconciliation', 'awaiting_ci') else (
            'failed' if head['native_exit_code'] else 'needs_reconciliation')
        raise Stop('native_result_requires_stop')
    request = payload.get('request')
    require(isinstance(request, dict) and request.get('request_id') == request_id and
            request.get('tool') in native.TOOLS.values() and isinstance(request.get('arguments'), dict),
            'pending_request_mismatch')
    require(request['tool'] != native.TOOLS['merge_pull_request'], 'a2_or_merge_requires_approval')


def native_lock_preflight(selected, directory):
    """Do not let native open_lock chmod an incompatible existing cron lock.

    Missing locks are left to native's no-follow creation path. Existing locks
    are probed without create/chmod/unlink; native still owns final locking.
    """
    paths = (selected.project_lock_path,
             selected.record_path(directory, 'github.lock', local_default=native.local_reports()))
    handles = []
    try:
        for path in paths:
            try:
                parent = selected.fs.open_directory(path.parent)
            except FileNotFoundError:
                continue
            try:
                try:
                    fd = os.open(path.name, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=parent)
                except FileNotFoundError:
                    continue
                handles.append(fd)
                info = os.fstat(fd)
                require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1,
                        'unsafe_native_lock')
                require(stat.S_IMODE(info.st_mode) == 0o600, 'native_lock_mode_requires_approval')
                require(identity(info) == identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)),
                        'native_lock_changed')
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise Stop('native_lock_busy') from None
            finally:
                os.close(parent)
    finally:
        for fd in reversed(handles):
            os.close(fd)


def decode_envelope(run, envelope, code):
    require(isinstance(envelope, dict) and envelope.get('version') == transport.VERSION and
            isinstance(envelope.get('operation_id'), str) and transport.HEX.fullmatch(envelope['operation_id']) and
            isinstance(envelope.get('sha256'), str) and transport.HEX.fullmatch(envelope['sha256']) and
            type(envelope.get('bytes')) is int and 0 < envelope['bytes'] <= transport.MAX_RESULT and
            type(envelope.get('native_exit_code')) is int and envelope['native_exit_code'] == code,
            'transport_envelope_invalid')
    if 'inline' in envelope:
        require(isinstance(envelope['inline'], str) and envelope['bytes'] <= transport.INLINE_BYTES and
                'chunks' not in envelope, 'inline_invalid')
        raw = envelope['inline'].encode('utf-8')
    else:
        chunks = envelope.get('chunks')
        count = (envelope['bytes'] + transport.CHUNK_BYTES - 1) // transport.CHUNK_BYTES
        require(envelope['bytes'] > transport.INLINE_BYTES and isinstance(chunks, dict) and
                chunks == {'bytes': transport.CHUNK_BYTES, 'count': count, 'encoding': 'base64'},
                'chunk_metadata_invalid')
        parts = []
        for index in range(count):
            part = transport.chunk(run, envelope['operation_id'], index)
            size = min(transport.CHUNK_BYTES, envelope['bytes'] - index * transport.CHUNK_BYTES)
            require(isinstance(part, dict) and part.get('version') == transport.VERSION and
                    part.get('operation_id') == envelope['operation_id'] and part.get('index') == index and
                    part.get('offset') == index * transport.CHUNK_BYTES and part.get('bytes') == size and
                    part.get('total_bytes') == envelope['bytes'] and part.get('sha256') == envelope['sha256'] and
                    isinstance(part.get('data'), str) and len(part['data']) <= 16384, 'chunk_invalid')
            data = base64.b64decode(part['data'], validate=True)
            require(len(data) == size and base64.b64encode(data).decode('ascii') == part['data'], 'chunk_size_invalid')
            parts.append(data)
        raw = b''.join(parts)
    require(len(raw) == envelope['bytes'] and transport.digest(raw) == envelope['sha256'], 'payload_digest_invalid')
    payload = transport.parse(raw)
    require(isinstance(payload, dict), 'native_result_invalid')
    transport.encode(payload)  # Reject escaped lone surrogates before public serialization.
    return payload


def finish(result, run, envelope, code, expected_operation, response_sha256=None):
    result['stage'] = 'verify_result'
    result['native_exit_code'] = code
    payload = decode_envelope(run, envelope, code)
    _, directory, ledger = context(run)
    saved, _ = evidence(run, ledger)
    require(saved is not None and saved[1] == envelope and saved[2] == payload, 'receipt_result_mismatch')
    require(saved[0]['operation_id'] == expected_operation and
            saved[0]['response_sha256'] == response_sha256, 'receipt_input_mismatch')
    result['side_effects']['native_invoked'] = True
    result.update(native=payload, transport=envelope)
    status = payload.get('github', {}).get('status', payload.get('status'))
    result.update(status=status or 'needs_reconciliation', stage='complete', code='native_result')
    if envelope['bytes'] > transport.INLINE_BYTES:
        descriptor = {'version': 'parent-result-file-v1', 'path': str(
            directory / 'transport' / (envelope['operation_id'] + '.stdout')),
            'bytes': envelope['bytes'], 'sha256': envelope['sha256'], 'encoding': 'utf-8-json'}
        result.pop('native')
        result['result_file'] = descriptor
    request = payload.get('request')
    if status in ('failed', 'needs_reconciliation', 'awaiting_ci') or code != 0:
        if code != 0 and status not in ('failed', 'needs_reconciliation', 'awaiting_ci'):
            result['status'] = 'failed'
        result['next_action']['reason'] = 'Native result retained; A1 has no retry, CI resume or reconciliation command.'
        return
    require(status in ('awaiting_connector', 'waiting_for_ci') and isinstance(request, dict),
            'a2_or_unknown_result')
    require(request.get('tool') in native.TOOLS.values() and isinstance(request.get('arguments'), dict),
            'request_tool_invalid')
    if request['tool'] == native.TOOLS['merge_pull_request']:
        result.update(status='awaiting_approval', code='stop_before_merge')
        result['next_action']['reason'] = 'Stop before merge; separate user approval and recovery coordination are required.'
        return
    result['next_action'] = {'action': 'call_connector', 'trusted_parent_only': True,
                             'tool': request['tool'], 'arguments': request['arguments'],
                             'request_id': request['request_id'],
                             'then': {'command': 'agent-git-accept-file',
                                      'required_arguments': {'run_id': run, 'request_id': request['request_id'],
                                                             'response_file': '<owned 0600 JSON file in a private directory>',
                                                             'sha256': '<sha256 of exact saved response bytes>'}}}
    if envelope['bytes'] > transport.INLINE_BYTES:
        # Reuse immutable native stdout, without rewriting a receipt or adding a
        # second large payload. Parent must verify this descriptor before use.
        descriptor = result['result_file']
        followup = result['next_action']['then']
        result['next_action'] = {'action': 'read_private_result_file', 'descriptor': descriptor,
                                 'then': {'action': 'call_connector_once', 'trusted_parent_only': True,
                                          'tool': request['tool'], 'request_id': request['request_id'],
                                          'arguments_from': 'verified_native.request.arguments',
                                          'then': followup}}


def git_next(result, run):
    result['stage'] = 'validate_run'
    selected, directory, ledger = context(run)
    result.update(stage='inspect', status='needs_reconciliation')
    saved, _ = evidence(run, ledger)
    if saved is not None:
        head, _, payload = saved
        status = payload.get('github', {}).get('status', payload.get('status'))
        result['native_exit_code'] = head['native_exit_code']
        result['status'] = status if status in ('failed', 'needs_reconciliation', 'awaiting_ci') else 'needs_reconciliation'
        raise Stop('existing_result_no_redispatch')
    premerge(ledger)
    native_lock_preflight(selected, directory)
    result.update(stage='native_request', status='needs_reconciliation', executed=True)
    result['side_effects'].update(transport_invoked=True, native_invoked=None)
    envelope = transport.transact('request', run)
    finish(result, run, envelope, envelope.get('native_exit_code'), operation('request', run))


@contextmanager
def scratch(selected, directory, effects):
    """An owned, pinned one-call directory; never remove native evidence."""
    selected.check_ready()
    parent = selected.fs.open_directory(directory)
    fd = None
    name = '.parent-input-' + secrets.token_hex(16)
    created = False
    owned = {}
    try:
        transport.private(os.fstat(parent), directory=True)
        os.mkdir(name, 0o700, dir_fd=parent)
        created = True
        effects['created'].append(name)
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        transport.private(os.fstat(fd), directory=True)
        os.fsync(parent)
        yield fd, owned
    finally:
        try:
            if fd is not None:
                # Only our fixed files are eligible, through the pinned directory.
                for file, expected in owned.items():
                    try:
                        info = os.stat(file, dir_fd=fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    require((info.st_dev, info.st_ino) == expected and stat.S_ISREG(info.st_mode) and
                            info.st_uid == os.geteuid(), 'temporary_file_changed')
                    os.unlink(file, dir_fd=fd)
                os.fsync(fd)
                pinned, current = os.fstat(fd), os.stat(name, dir_fd=parent, follow_symlinks=False)
                require((pinned.st_dev, pinned.st_ino) == (current.st_dev, current.st_ino), 'temporary_directory_changed')
            if created:
                os.rmdir(name, dir_fd=parent)
                effects['removed'].append(name)
                os.fsync(parent)
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent)


def new_file(directory_fd, name, owned=None):
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    try:
        if owned is not None:
            info = os.fstat(fd)
            owned[name] = (info.st_dev, info.st_ino)
        os.fchmod(fd, 0o600)
        transport.private(os.fstat(fd))
        return os.fdopen(fd, 'w+b')
    except BaseException:
        os.close(fd)
        raise


def frame_file(handle, raw):
    encoded = base64.b64encode(raw)
    for offset in range(0, len(encoded), 2048):
        handle.write(encoded[offset:offset + 2048] + b'\n')
    handle.write(b'.\n')
    handle.flush()
    os.fsync(handle.fileno())
    handle.seek(0)
    require(transport.stdin_response(handle) == raw and handle.read(1) == b'', 'frame_readback_mismatch')
    handle.seek(0)


def accept_process(run, request, frame, stdout, stderr, result):
    args = [sys.executable, '-m', 'harness.git_transport', 'accept', '--run-id', run,
            '--request-id', request, '--stdin-base64']
    child = subprocess.Popen(args, stdin=frame, stdout=stdout, stderr=stderr, shell=False, close_fds=True)
    result['executed'] = True
    result['side_effects'].update(transport_invoked=True, native_invoked=None)
    try:
        code = child.wait(timeout=PROCESS_TIMEOUT)
    except (subprocess.TimeoutExpired, KeyboardInterrupt, OSError):
        # A failed wait is not proof of exit. Reap if possible, retain the
        # attempt marker in all cases, and never authorize another accept.
        try:
            child.kill()
        except OSError:
            pass
        try:
            child.wait(timeout=PROCESS_TIMEOUT)
        except (subprocess.TimeoutExpired, KeyboardInterrupt, OSError):
            pass
        raise Stop('child_exit_unknown') from None
    require(type(code) is int and code >= 0, 'child_exit_unknown')
    result['transport_exit_code'] = code
    require(os.fstat(stdout.fileno()).st_size <= MAX_WIRE and
            os.fstat(stderr.fileno()).st_size <= MAX_WIRE, 'transport_output_too_large')
    stdout.seek(0)
    raw = stdout.read(MAX_WIRE + 1)
    ready, separator, rest = raw.partition(b'\n')
    require(separator and ready == transport.READY.encode('ascii'), 'ready_mismatch')
    # parse rejects duplicate keys, extra READY lines, trailing JSON and bad UTF-8.
    envelope = transport.parse(rest)
    require(isinstance(envelope, dict), 'transport_envelope_invalid')
    if envelope.get('error') == 'transport_refused':
        raise Stop('transport_refused')
    return envelope, code


def attempt_marker(selected, directory, run, request, sha256, result, create=False):
    """Own uncertainty evidence, including child failure before native claim.

    Never overwrite this marker or any native receipt. A partial stdin frame can
    fail before native creates inflight, so native receipts alone are insufficient
    to authorize a second accept after a child was started.
    """
    name = 'parent-accept-' + operation('accept', run, request) + '.json'
    path = selected.record_path(directory, name, local_default=native.local_reports())
    try:
        with private_input(selected, path, 4096) as (raw, _):
            prior = transport.parse(raw)
        require(isinstance(prior, dict) and prior.get('version') == 'parent-accept-attempt-v1' and
                prior.get('run_id') == run and prior.get('request_id') == request and
                isinstance(prior.get('response_sha256'), str) and transport.HEX.fullmatch(prior['response_sha256']),
                'accept_attempt_identity_mismatch')
        raise Stop('accept_attempt_requires_reconciliation')
    except FileNotFoundError:
        if not create:
            return
    selected.check_ready()
    parent = selected.fs.open_directory(directory)
    try:
        with new_file(parent, name) as handle:
            result['side_effects']['created'].append(name)
            handle.write(transport.encode({'version': 'parent-accept-attempt-v1', 'run_id': run,
                                           'request_id': request, 'response_sha256': sha256}))
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(parent)
    finally:
        os.close(parent)


def accept_file(result, run, request, response_file, sha256):
    require(isinstance(request, str) and transport.HEX.fullmatch(request), 'invalid_request_id')
    require(isinstance(sha256, str) and transport.HEX.fullmatch(sha256), 'invalid_response_sha256')
    result['stage'] = 'validate_input'
    selected, directory, ledger = context(run)
    with private_input(selected, response_file, transport.MAX_RESPONSE, private_parent=True) as (raw, check):
        require(transport.digest(raw) == sha256, 'response_digest_mismatch')
        require(isinstance(transport.parse(raw), (dict, list)), 'invalid_response')
        result.update(stage='inspect', status='needs_reconciliation')
        saved, completes = evidence(run, ledger)
        require(saved is not None, 'accept_requires_transport_receipt')
        existing = completes.get(operation('accept', run, request))
        if existing is not None:
            raise Stop('duplicate_response' if existing['response_sha256'] == sha256 else 'conflicting_response')
        require(ledger.get('pending_request_id') == request, 'stale_request_id')
        accept_request(result, saved, request)
        premerge(ledger)
        native_lock_preflight(selected, directory)
        attempt_marker(selected, directory, run, request, sha256, result)
        result.update(stage='frame', status='needs_reconciliation')
        with scratch(selected, directory, result['side_effects']) as (fd, owned):
            with new_file(fd, 'frame', owned) as frame, new_file(fd, 'stdout', owned) as stdout, new_file(fd, 'stderr', owned) as stderr:
                frame_file(frame, raw)
                os.fsync(fd)
                check()
                selected.check_ready()
                selected.validate_run_directory(directory, local_default=native.local_reports())
                attempt_marker(selected, directory, run, request, sha256, result, create=True)
                result['stage'] = 'native_accept'
                envelope, code = accept_process(run, request, frame, stdout, stderr, result)
                check()
                frame.seek(0)
                require(transport.stdin_response(frame) == raw and frame.read(1) == b'', 'frame_changed')
                finish(result, run, envelope, code, operation('accept', run, request), sha256)


def storage_path(result, target, category=None, report_dir=None, prepare=False, run=None):
    result['stage'] = 'resolve'
    require(run is None or isinstance(run, str) and native.RUN_ID.fullmatch(run), 'invalid_run_id')
    require(target in ('reports', 'workflows', 'artifacts', 'temporary', 'context'), 'invalid_storage_target')
    require(target in ('reports', 'workflows') or (category is None and report_dir is None and run is None),
            'unexpected_storage_arguments')
    selected = native.storage_policy()
    selected.check_ready()
    if target in ('reports', 'workflows'):
        require(target != 'workflows' or category in (None, 'workflows'), 'invalid_workflow_category')
        path = selected.report_dir('workflows' if target == 'workflows' else category, explicit=report_dir)
        if run:
            path = path / run
            selected._check_ready(target=path)
    else:
        path = {'artifacts': selected.artifact_root, 'temporary': selected.temp_root,
                'context': selected.context_root}[target]
        if path is not None:
            selected._check_ready(target=path)
    if prepare and path is not None:
        result['stage'] = 'prepare'
        # Track every possibly created ancestor, including resolver setup roots,
        # even when a later writeability probe fails. Never guess archive fields.
        missing = set()
        candidates = [path] + ([selected.artifacts.path, selected.temporary.path] if selected.configured else [])
        for candidate in candidates:
            for item in (candidate, *candidate.parents):
                try:
                    selected.fs.lstat(item)
                    break
                except FileNotFoundError:
                    missing.add(item)
        result['executed'] = True
        try:
            path = selected.ensure_directory(path)
        finally:
            for item in sorted(missing, key=str):
                try:
                    selected.fs.lstat(item)
                except FileNotFoundError:
                    continue
                result['side_effects']['created'].append(str(item))
    result.update(status='ready', stage='complete', code='prepared' if prepare else 'resolved',
                  path=str(path) if path is not None else None, prepared=prepare)
    result['next_action'] = {'action': 'return_path', 'path': result['path'], 'approval_required': False}


def execute(command, run=None, **kwargs):
    result = result_for(command, run)
    try:
        # Capture unexpected native diagnostics; stdout remains exactly one JSON.
        with redirect_stdout(transport.Capture()), redirect_stderr(transport.Capture()):
            authorize()
            if command == 'agent-git-next':
                git_next(result, run)
            elif command == 'agent-git-accept-file':
                accept_file(result, run, kwargs['request_id'], kwargs['response_file'], kwargs['sha256'])
            elif command == 'agent-worktree-park':
                from harness.worktree_park import park
                result = park(run)
                result.setdefault('native_exit_code', None)
            elif command == 'storage-path':
                storage_path(result, run=run, **kwargs)
            else:
                raise Stop('invalid_command')
    except (Stop, transport.TransportError) as exc:
        # TransportError messages are fixed protocol codes, not private paths.
        result['code'] = str(exc)
        if result['status'] not in ('failed', 'awaiting_ci', 'needs_reconciliation'):
            result['status'] = 'needs_reconciliation'
        if command in ('agent-git-next', 'agent-git-accept-file') and result['stage'] != 'authorization':
            result['status'] = result['status'] if result['status'] in ('failed', 'awaiting_ci') else 'needs_reconciliation'
        result.pop('native', None)
        result.pop('transport', None)
        result.pop('result_file', None)
    except KeyboardInterrupt:
        result.update(status='needs_reconciliation', code='interrupted')
        result.pop('native', None)
        result.pop('transport', None)
        result.pop('result_file', None)
    except Exception:
        uncertain = result['executed'] or result['status'] == 'needs_reconciliation'
        result.update(status='needs_reconciliation' if uncertain else 'failed', code='validation_or_io_failed')
        result.pop('native', None)
        result.pop('transport', None)
        result.pop('result_file', None)
    if result['code'] != 'native_result' and result['status'] not in ('ready', 'parked', 'awaiting_approval'):
        result['next_action'] = result_for(command, run)['next_action']
    return result


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Stop('invalid_arguments')


def run_argument(value):
    if not native.RUN_ID.fullmatch(value):
        raise argparse.ArgumentTypeError('invalid_run_id')
    return value


def hex_argument(value):
    if not transport.HEX.fullmatch(value):
        raise argparse.ArgumentTypeError('invalid_hex_identity')
    return value


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = Parser(description=__doc__, add_help=False, allow_abbrev=False)
    sub = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    for command in COMMANDS:
        item = sub.add_parser(command, add_help=False, allow_abbrev=False)
        item.add_argument('--run-id', type=run_argument, required=command != 'storage-path')
        if command == 'agent-git-accept-file':
            item.add_argument('--request-id', type=hex_argument, required=True)
            item.add_argument('--response-file', required=True)
            item.add_argument('--sha256', type=hex_argument, required=True)
        if command == 'storage-path':
            item.add_argument('--target', choices=('reports', 'workflows', 'artifacts', 'temporary', 'context'), default='reports')
            item.add_argument('--category')
            item.add_argument('--report-dir')
            item.add_argument('--prepare', action='store_true')
    try:
        args = vars(parser.parse_args(argv))
        command, run = args.pop('command'), args.pop('run_id')
        result = execute(command, run, **args)
    except Stop:
        command = argv[0] if argv and argv[0] in COMMANDS else None
        result = result_for(command, None)
        result.update(stage='arguments', code='invalid_arguments')
    print(transport.encode(result).decode('utf-8'))
    if result['status'] in ('failed', 'needs_reconciliation'):
        return result['native_exit_code'] or (2 if result['stage'] == 'arguments' else 1)
    return result['native_exit_code'] or 0


if __name__ == '__main__':
    raise SystemExit(main())
