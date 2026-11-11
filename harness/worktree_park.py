"""Trusted-parent, pre-merge parking; never publication or post-merge cleanup.

Only park(run_id) is the public entry point. The parent command adapter owns CLI
argument parsing. Native approval, backup and journal files are read-only here.
An interrupted park requires explicit reconciliation, never automatic replay.
"""
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import os
from pathlib import Path
import secrets
import stat

from harness import git_cleanup, git_publish as native, git_transport, workspace

VERSION = 'parent-commands-v1'
STATE = 'worktree-park.json'
SNAPSHOTS = 'worktree-park-after'
MAX_RECORD = 32 * 1024 * 1024


class Stop(ValueError):
    """A public reason code, never source text or command output."""


def _require(condition, code):
    if not condition:
        raise Stop(code)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_nlink,
            info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _owned(info, private=False, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    _require(kind(info.st_mode) and info.st_uid == os.geteuid() and
             (directory or info.st_nlink == 1), 'unsafe_file')
    if private:
        _require(stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600),
                 'unsafe_private_record')


def _read(selected, path, limit, private=False):
    """Bounded no-follow read with inode/content-change detection."""
    try:
        parent = selected.fs.open_directory(path.parent)
    except FileNotFoundError:
        return None, None
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=parent)
        except FileNotFoundError:
            return None, None
        try:
            before = os.fstat(fd)
            _owned(before, private=private)
            _require(before.st_size <= limit, 'file_too_large')
            chunks, count = [], 0
            while True:
                chunk = os.read(fd, min(65536, limit + 1 - count))
                if not chunk:
                    break
                chunks.append(chunk)
                count += len(chunk)
                _require(count <= limit, 'file_too_large')
            after = os.fstat(fd)
            attached = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            _require(_identity(before) == _identity(after) == _identity(attached),
                     'file_changed_during_read')
            raw = b''.join(chunks)
            return raw, {'sha256': hashlib.sha256(raw).hexdigest(),
                         'mode': stat.S_IMODE(before.st_mode)}
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def _record(selected, directory, name):
    path = selected.record_path(directory, name, local_default=native.local_reports())
    raw, _ = _read(selected, path, MAX_RECORD, private=True)
    _require(raw is not None, 'missing_record')
    value = git_transport.parse(raw)
    _require(isinstance(value, dict), 'invalid_record_object')
    return value, hashlib.sha256(raw).hexdigest()


@contextmanager
def _lock(selected, path, effects):
    """Native no-follow/open_lock creation contract, without existing chmod.

    open_lock itself always fchmods existing files. An exclusive create followed
    by an unchanged existing-file open preserves cron's historical inode/mode,
    including when another creator wins the race. No unlink or lock replacement.
    """
    selected.check_ready()
    parent = selected.fs.open_directory(path.parent)
    try:
        flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            fd = os.open(path.name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
            effects['created_locks'].append(path.name)
            try:
                os.fsync(parent)
            except BaseException:
                os.close(fd)
                raise
        except FileExistsError:
            fd = os.open(path.name, flags, dir_fd=parent)
        try:
            info = os.fstat(fd)
            _owned(info)
            attached = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            _require(_identity(info) == _identity(attached), 'lock_attachment_changed')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Stop('lock_busy') from None

            def check():
                current_parent = selected.fs.open_directory(path.parent)
                try:
                    old, new = os.fstat(parent), os.fstat(current_parent)
                    _require((old.st_dev, old.st_ino) == (new.st_dev, new.st_ino),
                             'lock_attachment_changed')
                finally:
                    os.close(current_parent)
                attached = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                _require((info.st_dev, info.st_ino, info.st_uid, info.st_nlink, info.st_mode) ==
                         (attached.st_dev, attached.st_ino, attached.st_uid,
                          attached.st_nlink, attached.st_mode), 'lock_attachment_changed')

            check()
            yield check
            check()
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def _fingerprint(item):
    if item is None:
        return
    _require(isinstance(item, dict) and set(item) == {'sha256', 'mode'} and
             isinstance(item['sha256'], str) and git_transport.HEX.fullmatch(item['sha256']) and
             type(item['mode']) is int and 0 <= item['mode'] <= 0o777,
             'invalid_approval_fingerprint')


def _names(values):
    _require(isinstance(values, list) and all(isinstance(v, str) for v in values) and
             len(values) == len(set(values)), 'invalid_scope')
    return set(values)


class _Park:
    def __init__(self, root, directory, selected, git, result, lock_guards):
        self.root, self.directory, self.selected = root, directory, selected
        self.git, self.result = git, result
        self.effects = result['side_effects']
        self.lock_guards = lock_guards

    def ready(self):
        self.selected.check_ready()
        self.selected.validate_run_directory(self.directory, local_default=native.local_reports())
        for check in self.lock_guards:
            check()

    def load(self):
        self.ledger, self.ledger_hash = _record(self.selected, self.directory, 'github.json')
        self.report, self.report_hash = _record(self.selected, self.directory, 'report.json')
        self.approval, self.approval_hash = _record(self.selected, self.directory, 'github-approved.json')
        report, ledger, approval = self.report, self.ledger, self.approval
        _require(isinstance(ledger.get('config'), dict) and isinstance(report.get('review'), dict),
                 'invalid_approval_record')
        _require(not any(report.get(k) for k in ('read_only', 'simulated', 'no_git', 'demo')) and
                 report.get('github_enabled') is not False and ledger['config'].get('enabled') is True,
                 'side_effects_disabled')
        self.publication_state()
        _require(report.get('review', {}).get('verdict') == 'approved', 'review_not_approved')
        # This is the native prepare gate, reused rather than a status-only test.
        from harness import failure_feedback
        checks = report.get('delivery_validation', report.get('validation'))
        _require(isinstance(checks, list) and bool(checks) and all(
            isinstance(row, dict) and row.get('status') == 'passed' and
            type(row.get('exit_code')) is int and row['exit_code'] == 0 and
            failure_feedback.check_groups_passed(row.get('checks')) for row in checks),
            'validation_not_passed')
        files = approval.get('files')
        _require(isinstance(files, dict) and bool(files), 'invalid_approval_scope')
        scope, changed, applied = (_names(report.get(k)) for k in ('scope', 'changed_files', 'applied'))
        _require(set(files) == changed == applied and changed <= scope,
                 'approval_scope_or_apply_mismatch')
        _require(all(isinstance(name, str) and name == Path(name).as_posix() and
                     not workspace.protected(name) and name != '.git' and
                     '.git' not in Path(name).parts for name in scope), 'unsafe_scope')
        self.limit = approval.get('max_file_bytes')
        _require(type(self.limit) is int and self.limit > 0, 'invalid_file_limit')
        for name, entry in files.items():
            _require(isinstance(name, str) and name == Path(name).as_posix() and
                     all(part not in ('', '.', '..') for part in name.split('/')),
                     'unsafe_scope')
            _require(isinstance(entry, dict) and set(entry) == {'before', 'after'} and
                     entry['before'] != entry['after'], 'invalid_approval_entry')
            _fingerprint(entry['before'])
            _fingerprint(entry['after'])
        # Includes exact run/config/workspace/journal blob and backup contracts.
        try:
            native.validate_journal(self.directory, ledger, selected=self.selected)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise Stop('native_approval_invalid') from None
        self.files = files
        self.before, self.after = {}, {}
        for name, entry in sorted(files.items()):
            for version, folder, contents in (('before', 'backup', self.before),
                                               ('after', 'workspace', self.after)):
                path = self.selected.record_path(self.directory, folder + '/' + name,
                                                 local_default=native.local_reports())
                raw, fp = _read(self.selected, path, self.limit)
                _require(fp == entry[version], 'native_snapshot_mismatch')
                contents[name] = raw
        self.head = self.git.text('rev-parse', '--verify', 'HEAD')
        _require(isinstance(ledger.get('base_sha'), str) and native.SHA.fullmatch(ledger['base_sha']),
                 'baseline_head_unavailable')
        _require(self.head == ledger['base_sha'], 'baseline_head_mismatch')
        for name in files:
            _require(git_cleanup.same_entry(git_cleanup.tree_file(self.git, self.head, name),
                                            ledger['files'][name]['before']), 'baseline_tree_mismatch')

    def publication_state(self):
        ledger = self.ledger
        code = 'publication_state_requires_reconciliation'
        step, pending = ledger.get('step'), ledger.get('pending_request_id')
        _require(isinstance(step, str) and step != 'done' and not step.startswith('cleanup') and
                 not ledger.get('merge_sha') and ledger.get('merge_status') != 'merged' and
                 ledger.get('status') in ('awaiting_connector', 'awaiting_ci', 'waiting_for_ci'), code)
        _require('pending_write' not in ledger or type(ledger['pending_write']) is bool, code)
        if pending is not None:
            _require(isinstance(pending, str) and git_transport.HEX.fullmatch(pending), code)
        if step == 'merge' or ledger.get('pending_write'):
            _require(step == 'merge' and ledger.get('status') == 'awaiting_connector' and
                     ledger.get('pending_write') is True and pending is not None, code)

        transport = self.directory / 'transport'
        try:
            fd = self.selected.fs.open_directory(transport)
        except FileNotFoundError:
            return  # No transport records, hence no begin or inflight marker.
        try:
            _owned(os.fstat(fd), private=True, directory=True)
            names = set(os.listdir(fd))
            _require(len(names) <= git_transport.MAX_OPERATIONS * 6, code)
        finally:
            os.close(fd)

        def optional(name):
            raw, _ = _read(self.selected, transport / name, MAX_RECORD, private=True)
            if raw is None:
                return None
            value = git_transport.parse(raw)
            _require(isinstance(value, dict), code)
            return value

        _require(optional('inflight.json') is None, code)
        if pending is not None:
            # Native accept identity is request-specific; an older successful
            # accept may be the operation that emitted this pending merge.
            operation = git_transport.digest(git_transport.encode([self.directory.name, 'accept', pending]))
            _require(optional(operation + '.begin.json') is None and
                     not any(name.startswith(operation + '.') for name in names), code)
        if any(name.endswith('.before.json') or (name.endswith('.begin.json') and
                (optional(name) or {}).get('operation') == 'reconcile') for name in names):
            # The shared reader validates every historical reconcile link even
            # when a later normal accept is the current transport head.
            from harness import parent_commands
            try:
                saved, _ = parent_commands.evidence(self.directory.name, ledger)
                _require(saved is not None and saved[0]['native_exit_code'] == 0, code)
            except (parent_commands.Stop, git_transport.TransportError):
                raise Stop(code) from None
            return
        # Partial or unrecognized records cannot prove a completed old operation.
        for name in names - {'claim', 'head.json'}:
            identity, separator, suffix = name.partition('.')
            _require(separator and git_transport.HEX.fullmatch(identity) and
                     suffix in ('begin.json', 'complete.json', 'response.json', 'stdout', 'stderr') and
                     identity + '.begin.json' in names and identity + '.complete.json' in names, code)
        head = optional('head.json')
        if head is None:
            _require(names <= {'claim'}, code)
            return
        command, request_id = head.get('operation'), head.get('request_id')
        _require(head.get('run_id') == self.directory.name and command in ('request', 'accept') and
                 ((command == 'request' and request_id is None) or
                  (command == 'accept' and isinstance(request_id, str) and
                   git_transport.HEX.fullmatch(request_id))), code)
        operation = git_transport.digest(git_transport.encode([self.directory.name, command, request_id]))
        _require(head.get('operation_id') == operation and head.get('journal_sha256') == self.ledger_hash and
                 type(head.get('native_exit_code')) is int and head['native_exit_code'] == 0 and
                 optional(operation + '.complete.json') == head, code)
        begin = optional(operation + '.begin.json')
        _require(begin is not None and set(begin) == {
                     'run_id', 'operation', 'operation_id', 'request_id', 'response_sha256',
                     'journal_sha256', 'started_at'} and
                 set(head) == set(begin) | {'bytes', 'sha256', 'native_exit_code', 'ended_at'} and
                 all(begin.get(key) == head.get(key) for key in
                 ('run_id', 'operation', 'operation_id', 'request_id', 'response_sha256', 'started_at')) and
                 isinstance(begin.get('journal_sha256'), str) and
                 git_transport.HEX.fullmatch(begin['journal_sha256']), code)
        response_hash = begin['response_sha256']
        _require((command == 'request' and response_hash is None) or
                 (command == 'accept' and isinstance(response_hash, str) and
                  git_transport.HEX.fullmatch(response_hash)), code)
        _require(type(head['started_at']) in (int, float) and type(head['ended_at']) in (int, float) and
                 0 <= head['started_at'] <= head['ended_at'] < float('inf'), code)
        raw, _ = _read(self.selected, transport / (operation + '.stdout'), MAX_RECORD, private=True)
        _require(raw is not None and type(head.get('bytes')) is int and len(raw) == head['bytes'] and
                 git_transport.digest(raw) == head.get('sha256'), code)

    def source(self, name):
        return _read(self.selected, workspace.safe_path(self.root, name), self.limit)[1]

    def source_state(self, parked=False, restored=()):
        _require(self.git.text('rev-parse', '--verify', 'HEAD') == self.head, 'baseline_head_changed')
        # Force actual filesystem checks; reject hidden/skip-worktree index entries.
        rows = self.git.run('ls-files', '-v', '-z')[1].split(b'\0')
        _require(all(not row or row.startswith(b'H ') for row in rows), 'unsupported_index_flags')
        code = self.git.run('diff', '--cached', '--quiet', '--no-ext-diff', 'HEAD', '--',
                            allow=(0, 1))[0]
        _require(code == 0, 'staged_changes')
        git_cleanup.no_operations(self.git, [{'worktree': str(self.root)}])
        changes = git_cleanup.status(self.git)
        expected = {}
        for name, item in self.files.items():
            at_baseline = parked or name in restored
            _require(self.source(name) == item['before' if at_baseline else 'after'], 'source_file_changed')
            if not at_baseline:
                # Non-executable POSIX-only changes need not appear in Git status.
                old, new = self.ledger['files'][name]['before'], self.ledger['files'][name]['after']
                if old != ({k: new[k] for k in ('sha', 'mode')} if new else None):
                    expected[name] = '??' if old is None else (' D' if new is None else ' M')
        _require(changes == expected, 'unapproved_worktree_changes')
        # Ignored collisions with an approved addition must not be mistaken for
        # an ordinary untracked source; exact status equality above rejects them.

    def evidence_unchanged(self):
        for name, digest in (('github-approved.json', self.approval_hash), ('report.json', self.report_hash)):
            _require(_record(self.selected, self.directory, name)[1] == digest, 'approval_changed')
        ledger, identity = _record(self.selected, self.directory, 'github.json')
        _require(ledger == self.ledger and identity == self.ledger_hash, 'journal_changed')
        self.publication_state()

    def persist(self, state):
        self.ready()
        path = self.selected.record_path(self.directory, STATE, local_default=native.local_reports())
        if path.exists() or path.is_symlink():
            _read(self.selected, path, MAX_RECORD, private=True)
        git_cleanup.durable_json(path, state)

    def snapshots(self, state):
        path = self.directory / SNAPSHOTS
        fd = self.selected.fs.open_directory(path)
        try:
            _owned(os.fstat(fd), private=True, directory=True)
            _require(set(os.listdir(fd)) == {str(i) for i, name in enumerate(sorted(self.files))
                                             if self.files[name]['after'] is not None},
                     'snapshot_membership_mismatch')
        finally:
            os.close(fd)
        _require(state.get('version') == 'worktree-park-v1' and state.get('run_id') == self.directory.name and
                 state.get('approval_sha256') == self.approval_hash and state.get('head') == self.head and
                 state.get('files') == self.files, 'park_checkpoint_mismatch')
        for i, name in enumerate(sorted(self.files)):
            if self.files[name]['after'] is not None:
                _, fp = _read(self.selected, path / str(i), self.limit, private=True)
                _require(fp is not None and fp['sha256'] == self.files[name]['after']['sha256'],
                         'park_snapshot_invalid')

    def write_snapshot(self, path, raw):
        self.ready()
        parent = self.selected.fs.open_directory(path.parent)
        try:
            fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(parent)
        finally:
            os.close(parent)

    def restore(self, name):
        item = self.files[name]
        path = workspace.safe_path(self.root, name)
        parent = self.selected.fs.open_directory(path.parent)
        temporary = None
        try:
            if item['before'] is not None:
                proposed = '.park-' + secrets.token_hex(16)
                fd = os.open(proposed, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
                temporary = proposed
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(self.before[name])
                    handle.flush()
                    os.fchmod(handle.fileno(), item['before']['mode'])
                    os.fsync(handle.fileno())
            _require(self.source(name) == item['after'], 'source_file_changed')
            self.ready()
            attached = self.selected.fs.open_directory(path.parent)
            try:
                old, new = os.fstat(parent), os.fstat(attached)
                _require((old.st_dev, old.st_ino) == (new.st_dev, new.st_ino), 'source_parent_changed')
            finally:
                os.close(attached)
            if item['before'] is None:
                os.unlink(path.name, dir_fd=parent)
            else:
                os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
                temporary = None
            os.fsync(parent)
        finally:
            if temporary is not None:
                os.unlink(temporary, dir_fd=parent)
            os.close(parent)

    def run(self):
        self.result['stage'] = 'validation'
        self.load()
        state_path = self.directory / STATE
        if state_path.exists() or state_path.is_symlink():
            state, _ = _record(self.selected, self.directory, STATE)
            self.snapshots(state)
            _require(state.get('phase') == 'parked' and
                     state.get('checkpoints') == {name: 'restored' for name in self.files},
                     'interrupted_park_requires_reconciliation')
            self.source_state(parked=True)
            self.evidence_unchanged()
            return 'already_parked'
        self.source_state()
        self.evidence_unchanged()
        self.result['stage'] = 'snapshot'
        snapshots = self.directory / SNAPSHOTS
        _require(not snapshots.exists() and not snapshots.is_symlink(), 'snapshot_conflict')
        self.ready()
        snapshots.mkdir(mode=0o700, exist_ok=False)
        self.effects['created_records'].append(SNAPSHOTS)
        directory_fd = self.selected.fs.open_directory(self.directory)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        for i, name in enumerate(sorted(self.files)):
            if self.after[name] is not None:
                self.write_snapshot(snapshots / str(i), self.after[name])
        state = {'version': 'worktree-park-v1', 'run_id': self.directory.name,
                 'approval_sha256': self.approval_hash, 'head': self.head,
                 'files': self.files, 'phase': 'prepared',
                 'checkpoints': {name: 'pending' for name in self.files}}
        self.snapshots(state)
        self.persist(state)
        self.effects['created_records'].append(STATE)
        # Finish validating every source and native record before the first write.
        self.source_state()
        self.evidence_unchanged()
        self.result['stage'] = 'restore'
        state['phase'] = 'restoring'
        for name in sorted(self.files):
            self.source_state(restored=self.effects['restored_files'])
            self.evidence_unchanged()
            state['checkpoints'][name] = 'applying'
            self.persist(state)
            self.result['executed'] = True
            self.effects['attempted_files'].append(name)
            self.restore(name)
            self.effects['restored_files'].append(name)
            state['checkpoints'][name] = 'restored'
            self.persist(state)
        self.result['stage'] = 'verify'
        self.source_state(parked=True)
        self.evidence_unchanged()
        self.snapshots(state)
        state['phase'] = 'parked'
        self.persist(state)
        return 'parked'


def park(run_id, *, root=None, selected=None, git=None):
    """Return one private JSON-compatible result. Test seams are never CLI flags.

    Success only means source baseline restored and approved after bytes retained;
    it never means merged, cleaned up, archived, or safe to replay publication.
    """
    public_run = run_id if isinstance(run_id, str) and native.RUN_ID.fullmatch(run_id) else None
    result = {'version': VERSION, 'command': 'agent-worktree-park', 'run': public_run,
              'status': 'needs_reconciliation', 'stage': 'authorization', 'code': None,
              'executed': False, 'side_effects': {'created_locks': [], 'created_records': [],
                                                'attempted_files': [], 'restored_files': []},
              'next_action': {'action': 'stop', 'approval_required': True,
                              'reason': 'Trusted parent must review retained evidence; no automatic retry.'}}
    try:
        git_transport.trusted_parent()
        _require(os.environ.get('READ_ONLY') != '1' and os.environ.get('GIT') != '0',
                 'side_effects_disabled')
        _require(isinstance(run_id, str) and native.RUN_ID.fullmatch(run_id), 'invalid_run_id')
        root = Path(root) if root is not None else native.ROOT
        _require(root == native.ROOT, 'project_root_mismatch')
        selected = selected or native.storage_policy()
        selected.check_ready()
        directory = native.directory_for(run_id, selected=selected)
        fd = selected.fs.open_directory(directory)
        try:
            _owned(os.fstat(fd), private=True, directory=True)
        finally:
            os.close(fd)
        result['stage'] = 'lock'
        # Same source/apply -> GitHub ordering as the native controller. No
        # assumption that github.lock or the stable source mutex already exists.
        selected.fs.create_directory(selected.project_lock_path.parent)
        with ExitStack() as locks:
            guards = [locks.enter_context(_lock(selected, selected.project_lock_path, result['side_effects']))]
            selected.validate_run_directory(directory, local_default=native.local_reports())
            lock = selected.record_path(directory, 'github.lock', local_default=native.local_reports())
            guards.append(locks.enter_context(_lock(selected, lock, result['side_effects'])))
            transport = git or git_cleanup.Git(root)
            # Disable the status hook without changing repository/host settings.
            class LocalGit:
                def run(self, *args, **kw):
                    return transport.run('-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
                                         *args, **kw)

                def text(self, *args, **kw):
                    return self.run(*args, **kw)[1].decode('utf-8').strip()
            code = _Park(root, directory, selected, LocalGit(), result, guards).run()
        result.update(status='parked', stage='complete', code=code)
        result['next_action'] = {'action': 'stop', 'approval_required': False,
                                 'reason': 'Park verified; parent retains publication/CI ownership and stops before merge.'}
    except (Stop, git_transport.TransportError, git_cleanup.Pending) as exc:
        result['code'] = str(exc)
    except KeyboardInterrupt:
        result['code'] = 'park_interrupted'
    except (ValueError, OSError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError):
        result['code'] = 'park_validation_or_io_failed'
    if result['status'] == 'needs_reconciliation':
        result['next_action'].update(run=public_run, stage=result['stage'], code=result['code'],
                                     retained_evidence=[STATE, SNAPSHOTS, 'github-approved.json',
                                                        'github.json', 'report.json', 'backup/'])
    return result
