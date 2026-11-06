"""Trusted-parent commands. JSON on stdout is private parent consumption.

No connector, retry, reconciliation or CI resume lives here. External UI squash
cleanup uses saved GET proof, native journal APIs and one archive attempt.
"""
import argparse
import base64
from contextlib import contextmanager, ExitStack, redirect_stderr, redirect_stdout
import fcntl
import math
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys

from harness import git_cleanup, git_publish as native, git_transport as transport

VERSION = 'parent-commands-v1'
COMMANDS = ('agent-git-next', 'agent-git-accept-file', 'agent-worktree-park', 'storage-path',
            'archive-verify', 'agent-git-external-merge', 'agent-git-proof-build', 'agent-git-next-file')
MAX_WIRE = transport.INLINE_BYTES * 6 + 16384
PROCESS_TIMEOUT = 120


class Stop(ValueError):
    """A fixed public reason code; never exception text from a private source."""


def require(condition, code):
    if not condition:
        raise Stop(code)


def result_for(command, run):
    result = {'version': VERSION, 'command': command,
            'run': run if isinstance(run, str) and native.RUN_ID.fullmatch(run) else None,
            'status': 'failed', 'stage': 'authorization', 'code': None,
            'executed': False, 'native_exit_code': None,
            'side_effects': {'transport_invoked': False, 'native_invoked': False, 'created': [], 'removed': []},
            'next_action': {'action': 'stop', 'approval_required': True,
                            'reason': 'Review retained evidence through the approved recovery procedure; no automatic retry.'}}
    if command == 'archive-verify':
        result['side_effects'].update(read_only=True, archive_transfer_invoked=False, writes=False)
    if command == 'agent-git-external-merge':
        result['completed_stages'] = []
    return result


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


def response_snapshot(selected, path, sha256):
    """One no-follow open; subsequent work owns immutable bounded memory bytes.

    This is intentionally separate from attached internal journal/attempt reads.
    No post-read path stat, parent re-open, or response re-open is permitted.
    """
    from harness.storage import _absolute
    require(isinstance(sha256, str) and transport.HEX.fullmatch(sha256), 'invalid_response_sha256')
    path = _absolute(path, 'Private response')
    parent = selected.fs.open_directory(path.parent)
    try:
        transport.private(os.fstat(parent), directory=True)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            initial = os.fstat(fd)
            transport.private(initial)
            require(0 <= initial.st_size <= transport.MAX_RESPONSE, 'input_too_large')
            with os.fdopen(os.dup(fd), 'rb') as handle:
                raw = handle.read(transport.MAX_RESPONSE + 1)
            require(len(raw) <= transport.MAX_RESPONSE, 'input_too_large')
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    require(transport.digest(raw) == sha256, 'response_digest_mismatch')
    require(len(raw) == initial.st_size, 'input_size_changed')
    return raw


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
    selected, directory, ledger = context(run)
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
    try:
        descriptor = save_next_file(selected, directory, run, saved, result)
        verified = result_for('agent-git-next-file', run)
        next_file(verified, run, descriptor['path'], descriptor['sha256'])
        result['request_file'] = descriptor
    except (Exception, KeyboardInterrupt):
        # Accept already completed. Keep its receipt/result; never ask to accept
        # the response again just because the additive export could not finish.
        result.update(status='needs_reconciliation', code='next_file_write_failed',
                      native_result_retained=True)
        result['next_action'] = {'action': 'stop', 'approval_required': True,
                                 'reason': 'Native result retained; inspect the export failure. Do not reaccept or redispatch.'}


def git_next(result, run):
    result['stage'] = 'validate_run'
    selected, directory, ledger = context(run)
    external_not_owned(selected, directory)
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


def new_file(directory_fd, name, owned=None, created=None):
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    try:
        if created is not None:
            created()
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
    raw = response_snapshot(selected, response_file, sha256)
    external_not_owned(selected, directory)
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
            selected.check_ready()
            selected.validate_run_directory(directory, local_default=native.local_reports())
            attempt_marker(selected, directory, run, request, sha256, result, create=True)
            result['stage'] = 'native_accept'
            envelope, code = accept_process(run, request, frame, stdout, stderr, result)
            frame.seek(0)
            require(transport.stdin_response(frame) == raw and frame.read(1) == b'', 'frame_changed')
            finish(result, run, envelope, code, operation('accept', run, request), sha256)


def durable_output(selected, directory, name, raw, result):
    """Exclusive output; record even an incomplete file and never overwrite it."""
    selected.check_ready()
    selected.validate_run_directory(directory, local_default=native.local_reports())
    path = selected.record_path(directory, name, local_default=native.local_reports())
    partial = {'path': str(path), 'complete': False}

    def created():
        result['executed'] = True
        result['side_effects']['created'].append(str(path))
        if 'partial_outputs' in result:
            result['partial_outputs'].append(partial)

    fd = selected.fs.open_directory(directory)
    try:
        transport.private(os.fstat(fd), directory=True)
        with new_file(fd, name, created=created) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            require(handle.read(len(raw) + 1) == raw, 'output_readback_mismatch')
            before = os.fstat(handle.fileno())
            transport.private(before)
            attached(selected, path, fd, handle.fileno(), before, private_parent=True)
            os.fsync(fd)
    finally:
        os.close(fd)
    descriptor = {'path': str(path), 'bytes': len(raw), 'sha256': transport.digest(raw),
                  'encoding': 'utf-8-json'}
    partial.update(descriptor, complete=True)
    return descriptor


def next_document(run, directory, saved):
    head, envelope, payload = saved
    request = payload['request']
    poll = payload.get('poll_after_seconds', 0)
    require(type(poll) in (int, float) and math.isfinite(poll) and poll >= 0, 'poll_interval_invalid')
    raw = transport.encode(request)
    return {'version': 'parent-next-file-v1', 'run_id': run, 'request_id': request['request_id'],
            'operation_id': head['operation_id'], 'journal_sha256': head['journal_sha256'],
            'request_sha256': transport.digest(raw),
            'request': request if len(raw) <= transport.INLINE_BYTES else None,
            'poll_after_seconds': poll,
            'result_file': {'version': 'parent-result-file-v1', 'path': str(
                directory / 'transport' / (head['operation_id'] + '.stdout')),
                'bytes': envelope['bytes'], 'sha256': envelope['sha256'], 'encoding': 'utf-8-json'}}


def save_next_file(selected, directory, run, saved, result):
    document = next_document(run, directory, saved)
    name = 'parent-next-' + document['request_id'] + '.json'
    return dict(durable_output(selected, directory, name, transport.encode(document), result),
                version='parent-next-file-v1', run_id=run, request_id=document['request_id'])


def next_file(result, run, request_file, sha256):
    """Verify the saved exact request; this reader grants no dispatch permission."""
    result['stage'] = 'validate_next_file'
    result['side_effects'].update(read_only=True, writes=False)
    selected, directory, ledger = context(run)
    external_not_owned(selected, directory)
    saved, completes = evidence(run, ledger)
    require(saved is not None, 'next_file_requires_transport_receipt')
    request = saved[2].get('request')
    require(isinstance(request, dict) and isinstance(request.get('request_id'), str) and
            transport.HEX.fullmatch(request['request_id']), 'next_file_requires_pending_request')
    request_id = request['request_id']
    accept_request(result, saved, request_id)
    premerge(ledger)
    require(operation('accept', run, request_id) not in completes, 'request_already_accepted')
    attempt_marker(selected, directory, run, request_id, None, result)
    expected_path = selected.record_path(directory, 'parent-next-' + request_id + '.json',
                                         local_default=native.local_reports())
    # Keep the caller spelling: Path normalization must not hide traversal.
    require(str(request_file) == str(expected_path), 'next_file_path_mismatch')
    raw = response_snapshot(selected, request_file, sha256)
    document = transport.parse(raw)
    require(isinstance(document, dict) and
            transport.encode(document) == transport.encode(next_document(run, directory, saved)),
            'next_file_identity_mismatch')
    # evidence rereads actual immutable stdout; caller descriptors are never opened.
    _, current_directory, current = context(run)
    fresh, _ = evidence(run, current)
    require(current_directory == directory and current == ledger and fresh == saved, 'next_file_state_changed')
    external_not_owned(selected, directory)
    attempt_marker(selected, directory, run, request_id, None, result)
    result.update(status='ready', stage='complete', code='exact_request_verified',
                  poll_after_seconds=document['poll_after_seconds'], redispatch_authorized=False,
                  native_receipt={key: saved[0][key] for key in
                                  ('operation_id', 'sha256', 'journal_sha256', 'native_exit_code')})
    followup = {'command': 'agent-git-accept-file', 'required_arguments': {
        'run_id': run, 'request_id': request_id,
        'response_file': '<owned 0600 JSON file in a private directory>',
        'sha256': '<sha256 of exact saved response bytes>'}}
    result['next_action'] = {'action': 'use_verified_request_once', 'trusted_parent_only': True,
                             'redispatch_authorized': False, 'tool': request['tool'],
                             'request_id': request_id, 'then': followup}
    if document['request'] is not None:
        result['exact_request'] = request
        result['next_action']['arguments'] = request['arguments']
    else:
        result['exact_request_file'] = dict(document['result_file'], run_id=run,
                                             request_id=request_id, operation_id=document['operation_id'],
                                             request_sha256=document['request_sha256'],
                                             request_from='verified_native.request')
        result['next_action'].update(descriptor=result['exact_request_file'],
                                     arguments_from='verified_native.request.arguments')


def proof_build(result, run, pr_number, input_dir, sha256):
    """Build from saved GET snapshots using the unmodified pure native gates."""
    result['stage'] = 'proof_manifest'
    result['proof_build'] = {'version': 'parent-proof-build-v1', 'complete': False}
    selected, directory, ledger = context(run)
    external_not_owned(selected, directory)
    require(type(pr_number) is int and pr_number > 0, 'external_arguments_invalid')
    bundle = Path(input_dir)
    require(str(bundle) == str(input_dir) and bundle.parent == directory and
            bundle.name.startswith('proof-input-') and bundle.name != 'proof-input-',
            'proof_input_path_mismatch')
    manifest_raw = response_snapshot(selected, bundle / 'manifest.json', sha256)
    manifest = transport.parse(manifest_raw)
    require(isinstance(manifest, dict) and set(manifest) == {
        'version', 'run_id', 'pr_number', 'journal_sha256', 'approval_sha256', 'merge_sha', 'responses'} and
        manifest['version'] == 'parent-proof-input-v1' and manifest['run_id'] == run and
        type(manifest['pr_number']) is int and manifest['pr_number'] == pr_number and
        isinstance(manifest['merge_sha'], str) and len(manifest['merge_sha']) == 40 and
        all(c in '0123456789abcdef' for c in manifest['merge_sha']), 'proof_manifest_invalid')

    def current_identity():
        values = []
        for name in ('github.json', 'github-approved.json'):
            path = selected.record_path(directory, name, local_default=native.local_reports())
            with private_input(selected, path, transport.MAX_RESULT) as (raw, _):
                values.append(transport.digest(raw))
        return values

    initial = current_identity()
    require(initial == [manifest['journal_sha256'], manifest['approval_sha256']],
            'proof_manifest_identity_mismatch')
    rows = manifest['responses']
    require(isinstance(rows, list) and len(rows) <= 500, 'proof_response_limit')
    responses, urls, files = [], set(), set()
    total = len(manifest_raw)
    prefix = 'https://api.github.com/repos/' + ledger['config']['repository']
    result['stage'] = 'proof_responses'
    for row in rows:
        require(isinstance(row, dict) and set(row) == {
            'method', 'url', 'status', 'complete', 'file', 'bytes', 'sha256'}, 'proof_response_invalid')
        url, name = row['url'], row['file']
        require(row['method'] == 'GET' and type(row['status']) is int and row['status'] == 200 and
                row['complete'] is True, 'proof_response_incomplete')
        require(isinstance(url, str) and (url == prefix or url.startswith(prefix + '/')) and
                url not in urls, 'proof_response_url_mismatch')
        require(isinstance(name, str) and name not in ('', '.', '..', 'manifest.json') and
                '/' not in name and '\\' not in name and name not in files, 'proof_response_path_invalid')
        require(type(row['bytes']) is int and 0 < row['bytes'] <= transport.MAX_RESPONSE,
                'proof_response_size_invalid')
        total += row['bytes']
        require(total <= transport.MAX_RESULT, 'proof_bundle_too_large')
        raw = response_snapshot(selected, bundle / name, row['sha256'])
        require(len(raw) == row['bytes'], 'proof_response_size_mismatch')
        body = transport.parse(raw)
        require(isinstance(body, (dict, list)), 'invalid_response')
        responses.append({key: row[key] for key in ('method', 'url', 'status', 'complete')})
        responses[-1]['body'] = body
        urls.add(url)
        files.add(name)
    native.validate_journal(directory, ledger, selected=selected)
    saved, _ = evidence(run, ledger)
    require(saved is not None, 'external_transport_required')
    proof = {'version': 'external-merge-proof-v1', 'run_id': run, 'pr_number': pr_number,
             'repository': ledger['config']['repository'],
             'base': {'ref': ledger['config']['base'], 'sha': ledger['base_sha']},
             'head': {'ref': ledger['branch'], 'sha': ledger['head_sha']},
             'merge_sha': manifest['merge_sha'], 'responses': responses}
    checks_prefix = prefix + '/commits/' + ledger['head_sha'] + '/check-runs?filter=latest&per_page=100&page='
    head_pages = [row for row in responses if row['url'].startswith(checks_prefix)]
    # Native head checks require numeric page order even if saved GETs arrived
    # out of order. Reject alternate URL spellings rather than normalize them.
    for row in head_pages:
        page = row['url'][len(checks_prefix):]
        require(1 <= len(page) <= 3 and page.isascii() and page.isdigit() and 1 <= int(page) <= 100 and
                str(int(page)) == page, 'proof_response_url_mismatch')
    checks = {'version': 'external-merge-checks-v1', 'run_id': run, 'pr_number': pr_number,
              'repository': ledger['config']['repository'], 'head_sha': ledger['head_sha'],
              'responses': sorted(head_pages, key=lambda row: int(row['url'][len(checks_prefix):]))}
    result['stage'] = 'validate_proof'
    try:
        native.external_merge_proof(ledger, proof, pr_number)
        native.external_head_checks(ledger, checks, proof)
    except native.ExternalProofError as exc:
        if exc.next_get:
            result['proof_build']['missing_get'] = exc.next_get
            result['next_action'] = {'action': 'collect_get', 'trusted_parent_only': True,
                                     'approval_required': False, **exc.next_get,
                                     'then': {'command': 'agent-git-proof-build',
                                              'required_arguments': {'run_id': run, 'pr_number': pr_number,
                                                  'input_dir': str(bundle),
                                                  'sha256': '<sha256 of updated manifest bytes>'},
                                              'reason': 'Save the actual GET and updated manifest; no outputs were created.'}}
        raise Stop(str(exc)) from None
    proof_raw, checks_raw = transport.encode(proof), transport.encode(checks)
    require(max(len(proof_raw), len(checks_raw)) <= transport.MAX_RESPONSE, 'proof_output_too_large')
    _, current_directory, current = context(run)
    require(current_directory == directory and current == ledger and current_identity() == initial,
            'proof_state_changed')
    external_not_owned(selected, directory)
    fresh, _ = evidence(run, current)
    require(fresh == saved, 'proof_state_changed')
    names = ('parent-proof.json', 'parent-checks.json')
    for name in names:
        path = selected.record_path(directory, name, local_default=native.local_reports())
        require(not path.exists() and not path.is_symlink(), 'proof_output_exists')
    result.update(stage='save_proof', executed=True)
    result['partial_outputs'] = []
    proof_file = durable_output(selected, directory, names[0], proof_raw, result)
    checks_file = durable_output(selected, directory, names[1], checks_raw, result)
    result.pop('partial_outputs')
    result.update(status='ready', stage='complete', code='proof_built', proof_file=proof_file, checks_file=checks_file)
    result['proof_build']['complete'] = True
    result['next_action'] = {'action': 'invoke_external_merge', 'trusted_parent_only': True,
                             'command': 'agent-git-external-merge', 'required_arguments': {
                                 'run_id': run, 'pr_number': pr_number,
                                 'proof_file': proof_file['path'], 'sha256': proof_file['sha256'],
                                 'checks_file': checks_file['path'], 'checks_sha256': checks_file['sha256']}}


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


def archive_verify(result, run):
    from harness import archive
    result['stage'] = 'resolve'
    require(isinstance(run, str) and native.RUN_ID.fullmatch(run), 'invalid_run_id')
    selected = native.storage_policy()
    selected.check_ready()
    directory = selected.find_run(run)
    require(directory.name == run, 'run_identity_mismatch')
    result.update(stage='verify_archive', executed=True)
    try:
        verified = archive.verify_run_archive(selected, directory)
    except archive.ArchiveReadbackError as exc:
        result.update(stage=exc.stage, code=exc.code)
        raise Stop(exc.code) from None
    result.update(verified, status='verified', stage='complete', code='archive_verified')
    result['next_action'] = {'action': 'return_archive_evidence', 'approval_required': False,
                             'reason': 'Retain this readback evidence; no transfer, retry or delivery action is authorized.'}


def external_not_owned(selected, directory):
    path = selected.record_path(directory, 'external-merge.json', local_default=native.local_reports())
    require(not path.exists() and not path.is_symlink(), 'external_merge_owns_journal')


class ExternalMerge:
    """Verified UI squash cleanup; transport history is never repaired or replayed."""
    NAME = 'external-merge.json'

    def __init__(self, result, run, pr_number, proof_file, proof_sha256, resume,
                 checks_file=None, checks_sha256=None):
        self.result, self.run, self.pr = result, run, pr_number
        self.proof_file, self.proof_hash, self.resume = proof_file, proof_sha256, resume
        self.checks_file, self.checks_hash = checks_file, checks_sha256
        self.checks_value = None
        self.state = None
        self.effects = result['side_effects']
        self.effects.update(created_locks=[], journal_writes=False, park_invoked=False,
                            cleanup_invoked=False, archive_transfer_invoked=False)
        result['completed_stages'] = []

    def read(self, name, optional=False):
        path = self.selected.record_path(self.directory, name, local_default=native.local_reports())
        try:
            with private_input(self.selected, path, transport.MAX_RESULT) as (raw, _):
                return transport.parse(raw), transport.digest(raw)
        except FileNotFoundError:
            if optional:
                return None, None
            raise Stop('external_record_missing') from None

    def guard(self):
        self.selected.check_ready()
        self.selected.validate_run_directory(self.directory, local_default=native.local_reports())
        for check in self.lock_checks:
            check()

    @contextmanager
    def locks(self):
        # Reuse the park lock's no-follow creation and inode/mode preservation.
        from harness.worktree_park import _lock, Stop as ParkStop
        self.selected.fs.create_directory(self.selected.project_lock_path.parent)
        try:
            with ExitStack() as stack:
                self.lock_checks = [stack.enter_context(_lock(
                    self.selected, self.selected.project_lock_path, self.effects))]
                path = self.selected.record_path(self.directory, 'github.lock', local_default=native.local_reports())
                self.lock_checks.append(stack.enter_context(_lock(self.selected, path, self.effects)))
                self.guard()
                yield
                self.guard()
        except ParkStop as exc:
            # Preserve the park API's fixed codes without exposing OS diagnostics.
            raise Stop(str(exc)) from None
        finally:
            self.lock_checks = []

    def persist(self):
        self.guard()
        path = self.selected.record_path(self.directory, self.NAME, local_default=native.local_reports())
        self.result['executed'] = True
        git_cleanup.durable_json(path, self.state)
        self.result['completed_stages'] = list(self.state['completed'])

    def done(self, stage):
        if stage not in self.state['completed']:
            self.state['completed'].append(stage)
            self.persist()

    def transport_inventory(self):
        """Pin every historical receipt and parent attempt, including old IDs."""
        found = {}
        try:
            records = transport.Records(self.run, create=False)
        except FileNotFoundError:
            raise Stop('external_transport_required') from None
        try:
            names = set(os.listdir(records.fd))
            require(len(names) <= transport.MAX_OPERATIONS * 6 and
                    not names & {'inflight.json', 'head.next'}, 'inflight_requires_reconciliation')
            for name in sorted(names - {'claim'}):
                found['transport/' + name] = transport.digest(records.read(name, transport.MAX_RESULT))
        finally:
            records.close()
        fd = self.selected.fs.open_directory(self.directory)
        try:
            names = os.listdir(fd)
        finally:
            os.close(fd)
        for name in sorted(name for name in names if name.startswith('parent-accept-')):
            require(name.endswith('.json') and transport.HEX.fullmatch(name[14:-5]),
                    'unknown_accept_attempt')
            _, found[name] = self.read(name)
        return found

    @staticmethod
    def report_identity(report):
        # These four fields are owned by native.save; everything else is fixed.
        return transport.digest(transport.encode({key: value for key, value in report.items()
                                                  if key not in ('github', 'status', 'current', 'events')}))

    def reload(self):
        self.ledger, self.journal_hash = self.read('github.json')
        self.report, self.report_hash = self.read('report.json')
        self.approval, self.approval_hash = self.read('github-approved.json')
        native.validate_journal(self.directory, self.ledger, selected=self.selected)
        require(git_cleanup.enabled(self.report, self.ledger['config']), 'side_effects_disabled')
        if self.state is not None:
            require(self.approval_hash == self.state['approval_sha256'] and
                    self.report_identity(self.report) == self.state['report_identity_sha256'],
                    'external_approval_changed')
            require(self.transport_inventory() == self.state['transport'], 'external_transport_changed')
            transition = self.state.get('journal_transition')
            if transition:
                require(self.journal_hash == transition['post'], 'external_journal_transition_unknown')
                require(self.report.get('github') == native.summary(self.ledger),
                        'external_native_save_incomplete')
                require(self.report.get('status') == ('passed' if native.cleanup_complete(self.ledger)
                                                     else 'awaiting_github'), 'external_native_save_incomplete')
                self.state['journal_sha256'] = self.journal_hash
                self.state['report_sha256'] = self.report_hash
                self.state.setdefault('journal_history', []).append({**transition, 'post_report': self.report_hash})
                del self.state['journal_transition']
                self.persist()
            require(self.journal_hash == self.state['journal_sha256'] and
                    self.report_hash == self.state['report_sha256'], 'external_journal_or_report_changed')

    def save_native(self, ledger):
        self.guard()
        require(self.read('github.json')[1] == self.state['journal_sha256'], 'external_journal_changed')
        require(self.read('report.json')[1] == self.state['report_sha256'], 'external_report_changed')
        # native durable_json's exact encoding; an interrupted save is accepted
        # only when BOTH the expected journal and native report are observable.
        post = transport.digest((json.dumps(ledger, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        self.state['journal_transition'] = {'pre': self.state['journal_sha256'], 'post': post,
            'pre_report': self.state['report_sha256'], 'stage': self.result['stage']}
        self.persist()
        self.effects['journal_writes'] = True
        self.effects['native_invoked'] = True
        native.save(self.directory, ledger)
        require(self.read('github.json')[1] == post, 'external_native_save_incomplete')
        report, report_hash = self.read('report.json')
        require(report.get('github') == native.summary(ledger), 'external_native_save_incomplete')
        self.state.setdefault('journal_history', []).append({**self.state['journal_transition'],
                                                            'post_report': report_hash})
        self.state['journal_sha256'] = post
        self.state['report_sha256'] = report_hash
        del self.state['journal_transition']
        self.ledger = ledger
        self.persist()

    def verify_park(self):
        from harness import worktree_park as park
        saved, digest = self.read(park.STATE, optional=True)
        require(digest == self.state['park_sha256'], 'external_park_changed')
        git = git_cleanup.Git(native.ROOT)
        if git.ref('HEAD') == self.proof_value['merge_sha']:
            self.synced_checkout(self.proof())
        if saved is None:
            require(self.state.get('checkout') == 'already_synced' and
                    not (self.directory / park.SNAPSHOTS).exists() and
                    not (self.directory / park.SNAPSHOTS).is_symlink(), 'external_park_incomplete')
            return
        # Snapshot verification does not require a pre-merge publication state.
        verifier = park._Park(native.ROOT, self.directory, self.selected,
                              git_cleanup.Git(native.ROOT), self.result, self.lock_checks)
        verifier.files, verifier.limit = self.approval['files'], self.approval['max_file_bytes']
        verifier.approval_hash, verifier.head = self.approval_hash, self.ledger['base_sha']
        verifier.snapshots(saved)
        require(saved.get('version') == 'worktree-park-v1' and saved.get('run_id') == self.run and
                saved.get('approval_sha256') == self.approval_hash and
                saved.get('head') == self.ledger['base_sha'] and saved.get('files') == verifier.files and
                saved.get('phase') == 'parked' and
                saved.get('checkpoints') == {name: 'restored' for name in verifier.files},
                'external_park_incomplete')
        cleanup_state, _ = self.read('cleanup.json', optional=True)
        before_sync = not cleanup_state or (not cleanup_state.get('external_attempts', {}).get('sync') and
                                           cleanup_state.get('sync', {}).get('status') != 'complete')
        if before_sync and git.ref('HEAD') != self.proof_value['merge_sha']:
            verifier.ledger = self.ledger
            verifier.source_state(parked=True)

    def proof(self):
        try:
            candidate = native.external_merge_proof(self.ledger, self.proof_value, self.pr)
            if self.checks_value is not None:
                native.external_head_checks(self.ledger, self.checks_value, self.proof_value)
            return candidate
        except native.ExternalProofError as exc:
            if exc.next_get:
                self.result['next_action'] = {'action': 'collect_get', 'approval_required': False,
                                              **exc.next_get, 'then': self.invocation()}
            raise Stop(str(exc)) from None

    def invocation(self):
        arguments = {
            'run_id': self.run, 'pr_number': self.pr, 'proof_file': str(self.proof_file),
            'sha256': self.proof_hash, 'resume': self.resume or self.state is not None}
        if self.checks_file is not None:
            arguments.update(checks_file=str(self.checks_file), checks_sha256=self.checks_hash)
        return {'command': 'agent-git-external-merge', 'required_arguments': arguments}

    def synced_checkout(self, candidate, *, repair_mode=False):
        cleanup = git_cleanup.Cleanup(native.ROOT, self.directory, candidate,
            self.report, self.approval, storage_guard=self.guard)
        try:
            require(not cleanup.state.get('events') or
                    cleanup.state.get('external_order') == 'external-merge-v1',
                    'external_cleanup_checkpoint_conflict')
            tip = cleanup.git.remote('refs/heads/' + candidate['config']['base'])
            cleanup.external_synced(tip, repair_mode=repair_mode)
        except git_cleanup.Pending as exc:
            raise Stop(str(exc)) from None

    def completed_attempts(self, completes):
        # With no pending ID, every retained parent attempt must be accounted
        # for by a completed native accept with the exact same response bytes.
        for name in self.transport_inventory():
            if not name.startswith('parent-accept-'):
                continue
            value, _ = self.read(name)
            request = value.get('request_id') if isinstance(value, dict) else None
            require(isinstance(request, str) and transport.HEX.fullmatch(request),
                    'accept_attempt_identity_mismatch')
            op = operation('accept', self.run, request)
            require(value.get('version') == 'parent-accept-attempt-v1' and value.get('run_id') == self.run and
                    name == 'parent-accept-' + op + '.json' and op in completes and
                    value.get('response_sha256') == completes[op].get('response_sha256'),
                    'accept_attempt_requires_reconciliation')

    def run_command(self):
        self.result['stage'] = 'proof_file'
        require(type(self.pr) is int and self.pr > 0 and isinstance(self.proof_hash, str) and
                transport.HEX.fullmatch(self.proof_hash), 'external_arguments_invalid')
        self.selected, self.directory, self.ledger = context(self.run)
        self.lock_checks = []
        raw = response_snapshot(self.selected, self.proof_file, self.proof_hash)
        self.proof_value = transport.parse(raw)
        require((self.checks_file is None) == (self.checks_hash is None), 'external_checks_arguments_required')
        require(self.ledger.get('status') != 'awaiting_ci' or self.checks_file is not None,
                'external_checks_required')
        if self.checks_file is not None:
            self.result['stage'] = 'checks_file'
            raw_checks = response_snapshot(self.selected, self.checks_file, self.checks_hash)
            self.checks_value = transport.parse(raw_checks)
        self.result['stage'] = 'proof'
        self.proof()  # Missing GETs return before locks, Git or durable writes.
        with self.locks():
            self.state, _ = self.read(self.NAME, optional=True)
            if self.state is not None:
                if not self.resume:
                    self.result['next_action'] = {'action': 'explicit_resume', 'approval_required': True,
                                                  **self.invocation()}
                require(self.resume, 'external_explicit_resume_required')
                require(self.state.get('version') == 'external-merge-v1' and
                        self.state.get('run_id') == self.run and self.state.get('pr_number') == self.pr and
                        self.state.get('proof_sha256') == self.proof_hash and
                        self.state.get('proof_file', str(self.proof_file)) == str(self.proof_file) and
                        self.state.get('checks_sha256') == self.checks_hash and
                        self.state.get('checks_file') == (str(self.checks_file) if self.checks_file is not None else None),
                        'external_resume_identity_mismatch')
                self.result['completed_stages'] = list(self.state['completed'])
            else:
                require(not self.resume, 'external_resume_checkpoint_missing')
            self.reload()
            candidate = self.proof()  # Missing/failed reads cause no Git or journal writes.
            require(self.ledger.get('status') != 'awaiting_ci' or self.checks_value is not None,
                    'external_checks_required')
            if self.state is None:
                awaiting_ci = self.ledger.get('status') == 'awaiting_ci'
                known_unsent = (self.ledger.get('step') == 'merge' and
                        self.ledger.get('status') == 'awaiting_connector' and
                        self.ledger.get('pending_write') is True and
                        isinstance(self.ledger.get('pending_request_id'), str) and
                        transport.HEX.fullmatch(self.ledger['pending_request_id']))
                require(not self.ledger.get('merge_sha') and (known_unsent or (awaiting_ci and
                        self.ledger.get('step') in ('pr', 'head_checks', 'merge_checks', 'statuses', 'final_pr') and
                        self.ledger.get('pending_request_id') is None and
                        (self.ledger.get('pending_write') is None or self.ledger.get('pending_write') is False))),
                        'external_pending_merge_required')
                request_id = self.ledger.get('pending_request_id')
                # Receipts for the operation which EMITTED this merge are
                # historical; only accept(current pending ID) denotes sending it.
                saved, completes = evidence(self.run, self.ledger)
                require(saved is not None, 'external_transport_required')
                request = saved[2].get('request')
                if known_unsent:
                    require(saved[0]['native_exit_code'] == 0, 'external_transport_required')
                    require(isinstance(request, dict) and request.get('tool') == native.TOOLS['merge_pull_request'] and
                            request.get('arguments') == {'repository_full_name': self.ledger['config']['repository'],
                                'pr_number': self.pr, 'expected_head_sha': self.ledger['head_sha'],
                                'merge_method': 'squash'}, 'external_pending_request_mismatch')
                    require(operation('accept', self.run, request_id) not in completes,
                            'external_pending_merge_sent')
                    attempt_marker(self.selected, self.directory, self.run, request_id, None, self.result)
                else:
                    require(request is None and saved[2].get('github', {}).get('status',
                            saved[2].get('status')) == 'awaiting_ci', 'external_pending_request_mismatch')
                    self.completed_attempts(completes)
                self.state = {'version': 'external-merge-v1', 'run_id': self.run, 'pr_number': self.pr,
                    'proof_sha256': self.proof_hash, 'proof_file': str(self.proof_file),
                    'checks_sha256': self.checks_hash,
                    'checks_file': str(self.checks_file) if self.checks_file is not None else None,
                    'approval_sha256': self.approval_hash,
                    'report_identity_sha256': self.report_identity(self.report),
                    'original_report_sha256': self.report_hash, 'report_sha256': self.report_hash,
                    'original_journal_sha256': self.journal_hash, 'journal_sha256': self.journal_hash,
                    'journal_history': [], 'transport': self.transport_inventory(), 'completed': ['proof'],
                    'discard': {'request_id': request_id, 'merge_sha': candidate['merge_sha'],
                                'proof_sha256': self.proof_hash,
                                'status': 'unsent_discarded' if known_unsent else 'no_request'}}
                self.persist()
            require(self.state['discard']['merge_sha'] == candidate['merge_sha'], 'external_merge_mismatch')
            self.done('discard' if self.state['discard']['status'] == 'unsent_discarded' else 'no_request')
            need_park = 'native_cleanup' not in self.state['completed'] and not self.ledger.get('merge_sha')
            installed = git_cleanup.Git(native.ROOT).ref('HEAD') == candidate['merge_sha']
            require(self.state.get('checkout') != 'already_synced' or installed, 'external_checkout_changed')
            if installed and ('already_synced' in self.state['completed'] or (
                    'park' not in self.state['completed'] and 'native_cleanup' not in self.state['completed'])):
                self.result['stage'] = 'already_synced'
                self.synced_checkout(candidate, repair_mode='already_synced' not in self.state['completed'])
                if 'already_synced' not in self.state['completed']:
                    if 'park_sha256' not in self.state:
                        self.state['park_sha256'] = self.read('worktree-park.json', optional=True)[1]
                    self.state['checkout'] = 'already_synced'
                    self.verify_park()
                    self.done('already_synced')
                need_park = False

        if need_park:
            # park owns the same source -> GitHub locks. Never call it while
            # holding those locks (a separate flock fd would deadlock).
            from harness.worktree_park import park
            self.result['stage'] = 'park'
            self.effects['park_invoked'] = True
            parked = park(self.run)
            self.result['park'] = {key: parked[key] for key in ('status', 'stage', 'code')}
            self.effects['park'] = parked['side_effects']
            self.result['executed'] |= parked['executed']
            require(parked['status'] == 'parked', 'external_park_failed')

        with self.locks():
            self.reload()
            candidate = self.proof()
            if need_park:
                self.state['park_sha256'] = self.read('worktree-park.json')[1]
                self.done('park')
            self.verify_park()
            if 'native_cleanup' not in self.state['completed']:
                self.result['stage'] = 'native_cleanup'
                if not self.ledger.get('merge_sha'):
                    # native begin_cleanup already ran on this proved copy;
                    # no agent merge response or transport receipt is forged.
                    self.save_native(candidate)
                require(self.ledger.get('merge_sha') == candidate['merge_sha'], 'external_merge_mismatch')
                self.done('native_cleanup')
            self.result['merge'] = {'status': 'merged', 'sha': self.ledger['merge_sha'], 'source': 'user_ui'}
            self.result['stage'] = 'cleanup'
            cleanup = git_cleanup.Cleanup(native.ROOT, self.directory, self.ledger,
                self.report, self.approval, storage_guard=self.guard)
            if 'cleanup' in self.state['completed'] or (
                    cleanup.state.get('status') == 'complete' and native.cleanup_complete(self.ledger)):
                require(cleanup.state.get('status') == 'complete' and native.cleanup_complete(self.ledger),
                        'external_cleanup_evidence_changed')
                self.verify_cleanup(cleanup)
                self.done('cleanup')
            else:
                self.effects['cleanup_invoked'] = True
                self.result['executed'] = True
                try:
                    cleaned = cleanup.run_external()
                except git_cleanup.Pending as exc:
                    self.result['completed_stages'].extend(key for key in (
                        'sync', 'remote', 'prune', 'local', 'completion') if cleanup.state.get(
                            key, {}).get('status') in ('complete', 'deleted', 'absent'))
                    self.result['cleanup'] = {'status': 'pending', 'code': str(exc)}
                    self.result['next_action'] = {'action': 'explicit_resume_or_stop', 'approval_required': True,
                        **self.invocation(), 'reason': 'Review actual state; unknown writes are never replayed.'}
                    raise Stop(str(exc)) from None
                self.ledger['cleanup'] = {key: cleaned[key] for key in (
                    'version', 'status', 'remote', 'prune', 'sync', 'local', 'completion')}
                self.ledger.update(status='merged', step='done')
                self.save_native(self.ledger)
                self.done('cleanup')
            self.result['cleanup'] = {'status': 'complete'}
            self.result['stage'] = 'archive'
            attempt_archive = 'archive_attempted' not in self.state
            if attempt_archive:
                # Do not take the archive/store mutex under the source locks.
                existing = any(self.read(name, optional=True)[0] is not None for name in (
                    'archive-state.json', 'archive-transfer.json', 'archive-frozen.json'))
                payload = self.directory / 'archive-payload'
                attempt_archive = not (existing or payload.exists() or payload.is_symlink())
                self.state['archive_attempted'] = True
                self.persist()

        self.archive_phase(attempt_archive, cleanup)

    def archive_phase(self, attempt_archive, cleanup):
        from harness import archive
        if attempt_archive:
            self.effects['archive_transfer_invoked'] = True
            self.result['executed'] = True
            # Intent is durable even if archive raises or the process dies.
            try:
                archive.archive_run(self.selected, self.directory)
            except (Exception, KeyboardInterrupt):
                pass
        self.result['stage'] = 'archive_verify'
        self.result['executed'] = True
        self.effects['archive_readback_invoked'] = True
        try:
            verified = archive.verify_run_archive(self.selected, self.directory)
            archive.verify_current_result(self.selected, self.directory, 'workflows',
                archive.terminal_report(self.selected, self.directory, 'workflows'),
                self.directory / 'archive-payload')
        except Exception:
            self.result['archive'] = {'status': 'pending'}
            self.result['next_action'] = {'action': 'stop', 'approval_required': True,
                'reason': 'Separate approval for existing archive recovery is required; do not repeat archive_run.',
                'readback': {'command': 'archive-verify', 'required_arguments': {'run_id': self.run}},
                'after_recovery': self.invocation()}
            raise Stop('external_archive_pending') from None
        with self.locks():
            self.reload()
            self.verify_cleanup(cleanup)
            self.done('archive')
            self.done('archive_verify')
        self.result.update(status='verified', stage='complete', code='external_merge_verified',
                           archive={'status': 'verified', **verified})
        self.result['next_action'] = {'action': 'stop', 'approval_required': False,
                                     'reason': 'UI merge, cleanup and archive readback verified.'}

    def verify_cleanup(self, cleanup):
        git = cleanup.git
        cleanup.proof()
        git_cleanup.validate_origin(git, self.ledger['config']['repository'])
        cleanup.prune_refspec()
        cleanup.external_index()
        tip = git.remote('refs/heads/' + self.ledger['config']['base'])
        require(tip == self.ledger['merge_sha'] and git.ref('HEAD') == tip and
                git.text('symbolic-ref', '-q', 'HEAD', allow=(0, 1)) ==
                'refs/heads/' + self.ledger['config']['base'] and not git_cleanup.status(git),
                'external_checkout_changed')
        cleanup.inspect(tip)
        cleanup.external_files()
        for ref in ('refs/heads/', 'refs/remotes/origin/'):
            require(git.ref(ref + self.ledger['branch']) is None, 'external_ref_reappeared')
        require(git.remote('refs/heads/' + self.ledger['branch']) is None, 'external_ref_reappeared')


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
            elif command == 'agent-git-next-file':
                next_file(result, run, kwargs['request_file'], kwargs['sha256'])
            elif command == 'agent-git-proof-build':
                proof_build(result, run, kwargs['pr_number'], kwargs['input_dir'], kwargs['sha256'])
            elif command == 'agent-worktree-park':
                from harness.worktree_park import park
                result = park(run)
                result.setdefault('native_exit_code', None)
            elif command == 'storage-path':
                storage_path(result, run=run, **kwargs)
            elif command == 'archive-verify':
                archive_verify(result, run)
            elif command == 'agent-git-external-merge':
                ExternalMerge(result, run, kwargs['pr_number'], kwargs['proof_file'],
                              kwargs['sha256'], kwargs.get('resume', False),
                              kwargs.get('checks_file'), kwargs.get('checks_sha256')).run_command()
            else:
                raise Stop('invalid_command')
    except (Stop, transport.TransportError) as exc:
        # TransportError messages are fixed protocol codes, not private paths.
        result['code'] = str(exc)
        if command == 'agent-git-external-merge' and (result['executed'] or result.get('completed_stages')):
            result['status'] = 'needs_reconciliation'
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
    if command != 'agent-git-external-merge' and result['code'] not in ('native_result', 'next_file_write_failed') and result['status'] not in ('ready', 'parked', 'awaiting_approval', 'verified') and not (
            command == 'agent-git-proof-build' and result['code'] == 'external_get_required' and
            result['next_action'].get('action') == 'collect_get'):
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
        if command == 'agent-git-next-file':
            item.add_argument('--request-file', required=True)
            item.add_argument('--sha256', type=hex_argument, required=True)
        if command == 'agent-git-proof-build':
            item.add_argument('--pr-number', type=int, required=True)
            item.add_argument('--input-dir', required=True)
            item.add_argument('--sha256', type=hex_argument, required=True)
        if command == 'agent-git-external-merge':
            item.add_argument('--pr-number', type=int, required=True)
            item.add_argument('--proof-file', required=True)
            item.add_argument('--sha256', type=hex_argument, required=True)
            item.add_argument('--checks-file')
            item.add_argument('--checks-sha256', type=hex_argument)
            item.add_argument('--resume', action='store_true')
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
