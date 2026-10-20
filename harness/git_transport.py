"""Private, single-call transport for the trusted parent's native GitHub journal.

No connector lives here. Recovery deliberately uses the original publisher CLI:
an existing receipt or uncertain dispatch is never an instruction to retry.
"""
import argparse
import base64
import contextlib
import fcntl
import hashlib
import io
import json
import os
import re
import stat
import sys
import time

from harness import git_publish as native

INLINE_BYTES = 32768
CHUNK_BYTES = 12288
MAX_RESPONSE = 8 * 1024 * 1024
MAX_RESULT = 32 * 1024 * 1024
MAX_OPERATIONS = 4096
VERSION = 'git-transport-v1'
READY = 'transport-input-ready-v1'
HEX = re.compile(r'^[a-f0-9]{64}$')


class TransportError(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def parse(raw):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise TransportError('invalid_json')
            obj[key] = value
        return obj

    def invalid(_):
        raise TransportError('invalid_json')

    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError):
        raise TransportError('invalid_json') from None


def trusted_parent():
    if any(os.environ.get(key) for key in (
            'TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
            'TAVERN_IMPROVEMENT_UNATTENDED')):
        raise TransportError('trusted_parent_required')


def private(info, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != os.geteuid() or
            stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600) or
            (not directory and info.st_nlink != 1)):
        raise TransportError('unsafe_private_record')


class Records:
    """Pinned no-follow descriptors; no caller-controlled record paths."""
    def __init__(self, run_id, create=True):
        trusted_parent()
        self.selected = native.storage_policy()
        self.selected.check_ready()
        self.directory = native.directory_for(run_id, selected=self.selected)
        self.selected.validate_run_directory(self.directory, local_default=native.local_reports())
        self.run_fd = self.selected.fs.open_directory(self.directory)
        try:
            private(os.fstat(self.run_fd), True)
            # This is an output boundary, including the configured storage probe.
            if create:
                self.selected.ensure_directory(self.directory / 'transport')
                os.fsync(self.run_fd)
            self.fd = os.open('transport', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=self.run_fd)
            try:
                private(os.fstat(self.fd), True)
            except BaseException:
                os.close(self.fd)
                raise
        except BaseException:
            os.close(self.run_fd)
            raise

    def close(self):
        os.close(self.fd)
        os.close(self.run_fd)

    def ready(self):
        self.selected.check_ready()
        self.selected.validate_run_directory(self.directory, local_default=native.local_reports())
        # Check attachment as well as all ancestors on every read/write boundary.
        fresh = self.selected.fs.open_directory(self.directory / 'transport')
        try:
            private(os.fstat(fresh), True)
            a, b = os.fstat(self.fd), os.fstat(fresh)
            if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
                raise TransportError('private_directory_changed')
        finally:
            os.close(fresh)
        run = self.selected.fs.open_directory(self.directory)
        try:
            private(os.fstat(run), True)
            a, b = os.fstat(self.run_fd), os.fstat(run)
            if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
                raise TransportError('private_directory_changed')
        finally:
            os.close(run)

    def read(self, name, limit=MAX_RESULT, run=False):
        self.ready()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=self.run_fd if run else self.fd)
        with os.fdopen(fd, 'rb') as handle:
            before = os.fstat(handle.fileno())
            private(before)
            if before.st_size > limit:
                raise TransportError('record_too_large')
            raw = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
            private(after)
            if (len(raw) != before.st_size or len(raw) > limit or
                    (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise TransportError('record_changed')
            return raw

    def optional(self, name):
        try:
            return parse(self.read(name))
        except FileNotFoundError:
            return None

    def write(self, name, raw):
        self.ready()
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.fd)
        with os.fdopen(fd, 'wb') as handle:
            os.fchmod(handle.fileno(), 0o600)
            private(os.fstat(handle.fileno()))
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(self.fd)

    def head(self, value):
        # Only our head pointer is replaceable. Receipts and payloads are immutable.
        self.optional('head.json')
        self.write('head.next', encode(value))
        self.ready()
        os.replace('head.next', 'head.json', src_dir_fd=self.fd, dst_dir_fd=self.fd)
        os.fsync(self.fd)

    @contextlib.contextmanager
    def claim(self):
        self.ready()
        fd = os.open('claim', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=self.fd)
        try:
            private(os.fstat(fd))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise TransportError('transport_busy') from None
            # Extra serialization is outermost and nonblocking. Native project ->
            # GitHub locks are untouched; no native caller acquires this claim.
            if self.optional('inflight.json') is not None:
                raise TransportError('needs_reconciliation')
            yield
        finally:
            os.close(fd)


class Capture(io.StringIO):
    def __init__(self):
        super().__init__()
        self.size = 0

    def write(self, text):
        self.size += len(text.encode('utf-8'))
        if self.size > MAX_RESULT:
            raise TransportError('native_output_too_large')
        return super().write(text)


def journal(records):
    raw = records.read('github.json', run=True)
    data = parse(raw)
    if data.get('run_id') != records.directory.name:
        raise TransportError('run_id_mismatch')
    return data, digest(raw)


def verify_head(records, identity):
    head = records.optional('head.json')
    if head is not None:
        complete = records.optional(head['operation_id'] + '.complete.json')
        if (complete is None or complete != head or head['journal_sha256'] != identity):
            raise TransportError('needs_reconciliation')
    return head


def envelope(records, complete):
    raw = records.read(complete['operation_id'] + '.stdout')
    if len(raw) != complete['bytes'] or digest(raw) != complete['sha256']:
        raise TransportError('result_digest_mismatch')
    result = {key: complete[key] for key in
              ('operation_id', 'bytes', 'sha256', 'native_exit_code', 'started_at', 'ended_at')}
    result['version'] = VERSION
    if len(raw) <= INLINE_BYTES:
        result['inline'] = raw.decode('utf-8')
    else:
        result['chunks'] = {'bytes': CHUNK_BYTES,
                            'count': (len(raw) + CHUNK_BYTES - 1) // CHUNK_BYTES,
                            'encoding': 'base64'}
    return result


def transact(command, run_id, request_id=None, response=None):
    """Return a verified envelope, retaining the exact native stdout and exit code."""
    trusted_parent()
    if command not in ('request', 'accept') or not native.RUN_ID.fullmatch(run_id or ''):
        raise TransportError('invalid_operation')
    if command == 'accept':
        if not isinstance(request_id, str) or not HEX.fullmatch(request_id):
            raise TransportError('invalid_request_id')
        if not isinstance(response, bytes) or len(response) > MAX_RESPONSE:
            raise TransportError('response_too_large')
        if not isinstance(parse(response), (dict, list)):
            raise TransportError('invalid_response')
    elif request_id is not None or response is not None:
        raise TransportError('unexpected_input')
    operation = digest(encode([run_id, command, request_id]))
    records = Records(run_id)
    try:
        with records.claim():
            names = os.listdir(records.fd)
            if (len(names) > MAX_OPERATIONS * 6 or
                    sum(name.endswith('.begin.json') for name in names) >= MAX_OPERATIONS):
                raise TransportError('receipt_limit')
            if records.optional(operation + '.begin.json') is not None:
                raise TransportError('needs_reconciliation')
            ledger, identity = journal(records)
            verify_head(records, identity)
            if command == 'accept' and ledger.get('pending_request_id') != request_id:
                raise TransportError('stale_request_id')
            if command == 'request' and ledger.get('pending_request_id'):
                raise TransportError('pending_request_requires_reconciliation')
            begin = {'run_id': run_id, 'operation': command, 'operation_id': operation,
                     'request_id': request_id, 'response_sha256': digest(response) if response is not None else None,
                     'journal_sha256': identity, 'started_at': time.time()}
            # Durable uncertainty marker precedes response save and native entry.
            records.write('inflight.json', encode(begin))
            records.write(operation + '.begin.json', encode(begin))
            args = [command, '--run-id', run_id]
            if command == 'accept':
                name = operation + '.response.json'
                records.write(name, response)
                if records.read(name, MAX_RESPONSE) != response:
                    raise TransportError('response_readback_mismatch')
                args += ['--request-id', request_id, '--response-file',
                         str(records.directory / 'transport' / name)]
        # The durable inflight claim alone excludes every new operation now.
        # Release our flock before native project -> GitHub locking, completion
        # hooks and archive I/O; no extra lock spans any network wait.
        captured = Capture()
        diagnostic = Capture()
        try:
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(diagnostic):
                code = native.main(args)
        finally:
            # Keep partial output on interruption too; inflight remains and
            # no complete receipt or next request is manufactured.
            raw = captured.getvalue().encode('utf-8')
            records.write(operation + '.stdout', raw)
            records.write(operation + '.stderr', diagnostic.getvalue().encode('utf-8'))
        # Never synthesize native success, even for intermediate cleanup or
        # archive-pending. Malformed stdout leaves inflight for reconciliation.
        if type(code) is not int or not isinstance(parse(raw), dict):
            raise TransportError('native_result_invalid')
        _, after = journal(records)
        complete = {**begin, 'journal_sha256': after, 'bytes': len(raw),
                    'sha256': digest(raw), 'native_exit_code': code, 'ended_at': time.time()}
        records.write(operation + '.complete.json', encode(complete))
        records.head(complete)
        result = envelope(records, complete)
        records.ready()
        os.unlink('inflight.json', dir_fd=records.fd)
        os.fsync(records.fd)
        return result
    finally:
        records.close()


def chunk(run_id, operation_id, index):
    if not isinstance(operation_id, str) or not HEX.fullmatch(operation_id) or type(index) is not int or index < 0:
        raise TransportError('invalid_chunk')
    records = Records(run_id, create=False)
    try:
        if records.optional('inflight.json') is not None:
            raise TransportError('needs_reconciliation')
        _, identity = journal(records)
        head = verify_head(records, identity)
        if head is None or head['operation_id'] != operation_id:
            raise TransportError('stale_result')
        raw = records.read(operation_id + '.stdout')
        if len(raw) != head['bytes'] or digest(raw) != head['sha256']:
            raise TransportError('result_digest_mismatch')
        count = (len(raw) + CHUNK_BYTES - 1) // CHUNK_BYTES
        if len(raw) <= INLINE_BYTES or index >= count:
            raise TransportError('invalid_chunk')
        offset = index * CHUNK_BYTES
        part = raw[offset:offset + CHUNK_BYTES]
        return {'version': VERSION, 'operation_id': operation_id, 'index': index,
                'offset': offset, 'bytes': len(part), 'total_bytes': len(raw),
                'sha256': head['sha256'], 'data': base64.b64encode(part).decode('ascii')}
    finally:
        records.close()


def stdin_response(stream):
    """Bounded line framing works with exec_command's no-echo PTY stdin as well.

    No EOF or shell parsing is needed. Each base64 line is <= 2048 characters;
    a single dot line terminates the frame (including for non-PTY callers).
    """
    encoded = bytearray()
    limit = ((MAX_RESPONSE + 2) // 3) * 4
    while True:
        line = stream.readline(2051)
        if line in (b'.\n', b'.\r\n'):
            break
        if not line or len(line) > 2050 or not line.endswith(b'\n'):
            raise TransportError('invalid_stdin_frame')
        value = line.rstrip(b'\r\n')
        if not value or len(value) > 2048 or len(encoded) + len(value) > limit:
            raise TransportError('response_too_large')
        encoded.extend(value)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise TransportError('invalid_base64') from None
    if len(raw) > MAX_RESPONSE:
        raise TransportError('response_too_large')
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('request', 'accept', 'chunk'))
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--request-id')
    parser.add_argument('--stdin-base64', action='store_true')
    parser.add_argument('--operation-id')
    parser.add_argument('--index', type=int)
    args = parser.parse_args(argv)
    try:
        trusted_parent()
        if args.command == 'chunk':
            if args.request_id or args.stdin_base64 or args.index is None:
                raise TransportError('unexpected_input')
            result = chunk(args.run_id, args.operation_id, args.index)
        else:
            if args.operation_id is not None or args.index is not None or (args.command == 'accept') != args.stdin_base64:
                raise TransportError('unexpected_input')
            raw = None
            if args.stdin_base64:
                print(READY, flush=True)
                raw = stdin_response(sys.stdin.buffer)
            result = transact(args.command, args.run_id, args.request_id, raw)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return result.get('native_exit_code', 0)
    except (ValueError, OSError, KeyError, TypeError, RecursionError):
        # Diagnostics never expose paths, native bodies or connector arguments.
        print(json.dumps({'version': VERSION, 'status': 'needs_reconciliation',
                          'error': 'transport_refused'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
