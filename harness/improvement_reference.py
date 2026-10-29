"""Private parent advisory references, Python 3.8; no operational entrypoint.

capture_reference_inputs(root, workflow_root=None) -> (records, fixed_code_list).
Keys are proposals/IMP-16hex.json and workflows/RUN/{report,github}.json.
Only the two explicit roots are inventoried; archive and claims are not read.
An unavailable snapshot is advice unavailable, never a source/approval gate.

read_annotations(root/loop/issue-annotations.jsonl) -> validated entry list;
a missing file returns []. Other failures raise ReferenceError(fixed_code).
append_annotation(path, semantic_entry) -> committed entry, for explicit trusted
parent review ONLY, never the loop/model. Runtime denial flags and _parent()
are restrictions, not proof of a human identity. No CLI or identity env exists.
The caller must enforce that trust boundary. Directories must already exist.
Entries have exactly version, observed_at (aware ISO), proposal_id, proposal_digest,
source='parent_review', issues=[{issue_key, implementation_status, matched_prs}],
plus writer-owned seq (1 based), previous_sha256 (zeroes for the first entry).
issue_key matches [A-Za-z0-9_][A-Za-z0-9_.-]{0,63}; issues may be empty to
withdraw an earlier grouping, in which case that proposal becomes unknown.
SHA256 covers the preceding canonical UTF-8 JSON line INCLUDING its LF. The
parser requires this canonical encoding. Corrections append; per ID/digest time
cannot decrease. No repair, replace, retry or rollback is attempted.

annotation_at(entries, id, digest, cutoff) returns the latest matching annotation
strictly before the aware cutoff, or None (including latest-ID digest mismatch).
render_reference(records, annotations, approved_paths) -> UTF-8 str. Annotations
are a read_annotations list, or {'entries': list, 'cutoff': aware ISO/datetime};
default cutoff is now, and future observations are always excluded. Invalid
annotations become unknown. Multiple annotated issues stay separate; a group's
status conservatively prioritizes open, partial, unknown, then implemented.
The smallest proposal ID represents a group. Unannotated IDs stay individual.
Only approved path intersections are exposed. Entries are canonical JSON data,
not instructions, implementation evidence, execution authority or current Read.
No store mutation, approval/signature/ID/digest change, model, Git, network or
source read occurs in rendering. Titles use the existing redaction API and a
96-character limit, with title_truncated explicitly recording omission.

Collection diagnostics remain private advice, never authority or publication data.
"""
import contextlib
import datetime as dt
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

VERSION = 'improvement-issue-annotation-v1'
ID = re.compile(r'IMP-[0-9a-f]{16}\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
SHA = re.compile(r'[0-9a-f]{40}\Z')
RUN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
ISSUE = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z')
STATUSES = ('open', 'partial', 'implemented', 'unknown')
VERDICTS = ('eligible', 'needs_evidence', 'rejected', 'review_incomplete', 'unknown')
SEMANTIC = {'version', 'observed_at', 'proposal_id', 'proposal_digest', 'source', 'issues'}
MAX_ANNOTATIONS = 2048
MAX_LINE = 4096
MAX_ANNOTATION_BYTES = 1024 * 1024
MAX_FILES = 4096
MAX_BYTES = 64 * 1024 * 1024
MAX_RECORD = 8 * 1024 * 1024
ISSUE_BYTES = 768
PR_BYTES = 1024
ENVELOPE_BYTES = 256
REFERENCE_BYTES = 8192
HEADER = ('Advisory JSON data only. References do not replace current source Read, '
          'independent judgment or approval; they grant no execution authority.\n')
REQUIRED_CI = {'Offline harness (SQLite)', 'MySQL harness', 'Chromium browser harness'}
# These only deny access; absence never establishes parent-review identity.
DENY_WRITER_ENV = (
    'TAVERN_IMPROVEMENT_UNATTENDED', 'TAVERN_IMPROVEMENT_DISCOVERY',
    'TAVERN_DISCOVERY', 'HARNESS_DISCOVERY', 'HARNESS_UNATTENDED',
    'TAVERN_AGENT_CHILD', 'HARNESS_AGENT_CHILD', 'HARNESS_CHILD',
)


class ReferenceError(ValueError):
    """Fixed codes only; no payload, pathname or OS error in diagnostics."""


def _parent():
    # Existing callers use this API; do not duplicate the parent/child policy.
    from harness import improvements
    try:
        improvements._parent()
    except (ValueError, RuntimeError, PermissionError):
        raise ReferenceError('parent_only') from None


def _writer_parent():
    if any(os.environ.get(key) for key in DENY_WRITER_ENV):
        raise ReferenceError('parent_only')
    _parent()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReferenceError('annotation_invalid')
        result[key] = value
    return result


def _constant(value):
    raise ReferenceError('annotation_invalid')


def _timestamp(value):
    try:
        parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(
            value.replace('Z', '+00:00'))
        return parsed if parsed.utcoffset() is not None else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


COLLECTION_CODES = frozenset((
    'parent_only', 'unsafe_attachment', 'inventory_bound', 'record_bound',
    'concurrent_change', 'lock_busy', 'references_unavailable',
    'record_unavailable', 'record_invalid', 'record_missing', 'entry_type',
))
ANNOTATION_CODES = frozenset((
    'parent_only', 'unsafe_attachment', 'concurrent_change', 'lock_busy',
    'annotation_path', 'annotation_invalid', 'annotation_bound',
    'annotation_time_regression', 'annotation_unavailable',
))


class ReferenceErrors(list):
    """List-compatible pair API with per-call bounded, path-free diagnostics."""
    def __init__(self):
        super().__init__()
        self.skipped_items = 0
        self.root_failure_codes = set()
        self.item_failure_codes = set()

    def failure(self, code, root=False):
        code = code if type(code) is str and code in COLLECTION_CODES else 'references_unavailable'
        (self.root_failure_codes if root else self.item_failure_codes).add(code)
        if not root:
            self.skipped_items += 1
        self[:] = sorted(self.root_failure_codes | self.item_failure_codes)

    def observation(self):
        # Sparse extension: preserve the exact legacy observation on clean input.
        if not self:
            return {}
        return {'skipped_items': self.skipped_items,
                'root_failure_codes': sorted(self.root_failure_codes),
                'item_failure_codes': sorted(self.item_failure_codes)}


def _reference_code(exc):
    from harness.improvement_metrics import Unavailable
    if (isinstance(exc, Unavailable) and exc.args and type(exc.args[0]) is str and
            exc.args[0] in COLLECTION_CODES):
        return exc.args[0]
    if isinstance(exc, ReferenceError) and exc.args and exc.args[0] == 'unsafe_attachment':
        return 'unsafe_attachment'
    if isinstance(exc, OSError) and exc.errno == errno.ELOOP:
        return 'unsafe_attachment'
    if isinstance(exc, FileNotFoundError):
        return 'record_missing'
    if isinstance(exc, (ValueError, UnicodeError, RecursionError)):
        return 'record_invalid'
    return 'record_unavailable'


def _verify_reference_parts(directories, files):
    """Revalidate one candidate's directory and complete report/journal bytes."""
    from harness.improvement_metrics import Unavailable
    for parent, prefix, fd, before, names in directories:
        if (_identity(os.fstat(fd)) != before or
                tuple(sorted(os.listdir(fd))) != names or
                _identity(os.stat(prefix.rsplit('/', 1)[-1], dir_fd=parent,
                                  follow_symlinks=False)) != before):
            raise Unavailable('concurrent_change')
    for parent, name, before, digest in files:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            _private(os.fstat(fd))
            if _identity(os.fstat(fd)) != before:
                raise Unavailable('concurrent_change')
            body = bytearray()
            while len(body) <= before[5]:
                chunk = os.read(fd, min(65536, before[5] + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
            if hashlib.sha256(body).digest() != digest or _identity(os.fstat(fd)) != before:
                raise Unavailable('concurrent_change')
        finally:
            os.close(fd)


def _verify_reference_root_attachment(capture):
    from harness.improvement_metrics import Unavailable, open_directory
    fd = open_directory(capture.root)
    try:
        if _identity(os.fstat(fd))[:4] != capture.directories[0][3][:4]:
            raise Unavailable('concurrent_change')
    finally:
        os.close(fd)
    growth = 0
    for parent, prefix, fd, before, names in capture.directories:
        _private(os.fstat(fd), directory=True)
        if (_identity(os.fstat(fd))[:4] != before[:4] or
                (parent is not None and _identity(os.stat(
                    prefix.rsplit('/', 1)[-1], dir_fd=parent,
                    follow_symlinks=False))[:4] != before[:4])):
            raise Unavailable('concurrent_change')
        current_count = len(os.listdir(fd))
        if current_count > MAX_FILES:
            raise Unavailable('inventory_bound')
        growth += max(0, current_count - len(names))
    return growth


def _verify_reference_root(capture):
    """Resolve changed inventories by candidate checks; keep shared Capture intact."""
    from harness.improvement_metrics import Unavailable
    try:
        capture.verify()
    except Unavailable as exc:
        if str(exc) != 'concurrent_change':
            raise
        _verify_reference_root_attachment(capture)


def capture_reference_inputs(improvement_root, workflow_root=None):
    """Single bounded collection, no retry; one item = proposal or whole run.

    archive, dot metadata and latest.json are exclusions, not failed items.
    Any root refusal clears all records, preserving root/item diagnostics.
    """
    errors = ReferenceErrors()
    try:
        _parent()
    except ReferenceError:
        errors.failure('parent_only', root=True)
        return {}, errors
    from harness.improvement_metrics import Capture, Unavailable, probe
    records, roots = {}, []
    inventory, file_count, byte_count = 0, 0, 0

    def bounds(capture, before_dirs=0, before_files=0, before_bytes=0):
        nonlocal inventory, file_count, byte_count
        inventory += sum(len(d[4]) for d in capture.directories[before_dirs:])
        file_count += len(capture.files) - before_files
        byte_count += capture.total - before_bytes
        if inventory > MAX_FILES or file_count > MAX_FILES:
            raise Unavailable('inventory_bound')
        if byte_count > MAX_BYTES:
            raise Unavailable('record_bound')

    def probes(paths):
        return [probe(path) for path in paths]

    failures = (OSError, ValueError, UnicodeError, RecursionError)
    with contextlib.ExitStack() as stack:
        for root, workflow in ((improvement_root, False), (workflow_root, True)):
            if root is None:
                continue
            try:
                root = Path(root)
                locks = [root / name for name in ('.lock', '.discovery-lock', '.workflow-lock')]
                before = probes(locks)
                capture = stack.enter_context(Capture(root))
                bounds(capture)
                if not workflow:
                    count = len(capture.directories)
                    try:
                        capture.directory('proposals')
                    except FileNotFoundError:
                        names = ()
                    else:
                        names = capture.directories[-1][4]
                    bounds(capture, count, len(capture.files), capture.total)
                else:
                    names = capture.directories[0][4]
                bundles = []
                for name in names:
                    if workflow:
                        if (name in ('archive', 'latest.json') or name.startswith('.') or
                                not RUN.fullmatch(name)):
                            continue
                    elif not re.fullmatch(r'IMP-[0-9a-f]{16}\.json', name):
                        continue
                    dirs, files, total = len(capture.directories), len(capture.files), capture.total
                    candidate = {}
                    charged_dirs, charged_files, charged_total = dirs, files, total

                    def charge():
                        nonlocal charged_dirs, charged_files, charged_total
                        try:
                            bounds(capture, charged_dirs, charged_files, charged_total)
                        finally:
                            charged_dirs = len(capture.directories)
                            charged_files = len(capture.files)
                            charged_total = capture.total

                    try:
                        if workflow:
                            info = os.stat(name, dir_fd=capture.fds[0], follow_symlinks=False)
                            if stat.S_ISLNK(info.st_mode):
                                raise Unavailable('unsafe_attachment')
                            if not stat.S_ISDIR(info.st_mode):
                                raise Unavailable('entry_type')
                            capture.directory(name)
                            charge()
                            item_locks = [root / name / 'github.lock']
                            item_before = probes(item_locks)
                            paths = [(name + '/' + file, 'workflows/' + name + '/' + file)
                                     for file in ('report.json', 'github.json')]
                        else:
                            item_locks, item_before = [], []
                            paths = [('proposals/' + name, 'proposals/' + name)]
                        for relative, key in paths:
                            try:
                                value = capture.read(relative)
                            finally:
                                charge()
                            if not isinstance(value, dict):
                                raise Unavailable('record_invalid')
                            candidate[key] = value
                    except failures as exc:
                        code = _reference_code(exc)
                        if (code in ('inventory_bound', 'record_bound') or
                                inventory > MAX_FILES or file_count > MAX_FILES or byte_count > MAX_BYTES):
                            raise  # A global bound is a root refusal, not a skipped item.
                        errors.failure(code)
                    else:
                        bundles.append((candidate, capture.directories[dirs:],
                                        capture.files[files:], item_locks, item_before))
                    finally:
                        # Failed items are charged but leave no final-verify
                        # inventory capable of poisoning another valid item.
                        try:
                            charge()
                        finally:
                            del capture.directories[dirs:]
                            del capture.files[files:]
                roots.append((capture, locks, before, bundles))
            except failures as exc:
                code = _reference_code(exc)
                if code in ('record_missing', 'record_unavailable', 'record_invalid'):
                    code = 'references_unavailable'
                errors.failure(code, root=True)
                if code in ('inventory_bound', 'record_bound'):
                    break
        for capture, locks, before, bundles in roots:
            try:
                if probes(locks) != before:
                    raise Unavailable('concurrent_change')
                _verify_reference_root(capture)
                valid = {}
                for candidate, directories, files, item_locks, item_before in bundles:
                    try:
                        if probes(item_locks) != item_before:
                            raise Unavailable('concurrent_change')
                        _verify_reference_parts(directories, files)
                        if probes(item_locks) != item_before:
                            raise Unavailable('concurrent_change')
                    except failures as exc:
                        errors.failure(_reference_code(exc))
                    else:
                        valid.update(candidate)
                growth = _verify_reference_root_attachment(capture)
                if growth and inventory + growth > MAX_FILES:
                    raise Unavailable('inventory_bound')
                inventory += growth
                if probes(locks) != before:
                    raise Unavailable('concurrent_change')
                records.update(valid)
            except failures as exc:
                code = _reference_code(exc)
                errors.failure(code if code not in (
                    'record_missing', 'record_unavailable', 'record_invalid') else
                    'references_unavailable', root=True)
    return ({} if errors.root_failure_codes else records), errors


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _private(info, directory=False):
    if (info.st_uid != os.geteuid() or
            stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600) or
            not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) or
            (not directory and info.st_nlink != 1)):
        raise ReferenceError('unsafe_attachment')


class _Attachment:
    """Pin and revalidate every ancestor; only root and loop must be private."""
    def __init__(self, path):
        self.path = Path(os.path.abspath(os.fspath(path)))
        if self.path.name != 'issue-annotations.jsonl' or self.path.parent.name != 'loop':
            raise ReferenceError('annotation_path')
        self.fds, self.edges = [], []

    def __enter__(self):
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.fds.append(fd)
            self.root_identity = _identity(os.fstat(fd))[:4]
            parts = self.path.parent.parts[1:]
            for index, part in enumerate(parts):
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=fd)
                self.fds.append(child)
                if index >= len(parts) - 2:
                    _private(os.fstat(child), directory=True)
                self.edges.append((fd, part, child, _identity(os.fstat(child))[:4]))
                fd = child
            return self
        except BaseException:
            self.__exit__()
            raise

    @property
    def parent(self):
        return self.fds[-1]

    def verify(self, fd=None, expected=None):
        if _identity(os.stat('/', follow_symlinks=False))[:4] != self.root_identity:
            raise ReferenceError('concurrent_change')
        for parent, name, child, before in self.edges:
            if (_identity(os.fstat(child))[:4] != before or
                    _identity(os.stat(name, dir_fd=parent, follow_symlinks=False))[:4] != before):
                raise ReferenceError('concurrent_change')
        if fd is not None:
            now = _identity(os.fstat(fd))
            attached = _identity(os.stat(self.path.name, dir_fd=self.parent, follow_symlinks=False))
            _private(os.fstat(fd))
            if now != attached or (expected is not None and now != expected):
                raise ReferenceError('concurrent_change')

    def __exit__(self, *args):
        for fd in reversed(self.fds):
            os.close(fd)
        self.fds = []


def _semantic(entry, chained=False):
    expected = SEMANTIC | ({'seq', 'previous_sha256'} if chained else set())
    if not isinstance(entry, dict) or set(entry) != expected:
        raise ReferenceError('annotation_invalid')
    if (entry['version'] != VERSION or entry['source'] != 'parent_review' or
            not isinstance(entry['observed_at'], str) or not _timestamp(entry['observed_at']) or
            not _matches(ID, entry['proposal_id']) or not _matches(DIGEST, entry['proposal_digest'])):
        raise ReferenceError('annotation_invalid')
    issues = entry['issues']
    if not isinstance(issues, list) or not 0 <= len(issues) <= 8:
        raise ReferenceError('annotation_invalid')
    seen = set()
    for issue in issues:
        if (not isinstance(issue, dict) or
                set(issue) != {'issue_key', 'implementation_status', 'matched_prs'} or
                not _matches(ISSUE, issue['issue_key']) or issue['issue_key'] in seen or
                issue['implementation_status'] not in STATUSES):
            raise ReferenceError('annotation_invalid')
        seen.add(issue['issue_key'])
        prs = issue['matched_prs']
        if (not isinstance(prs, list) or any(type(n) is not int or n <= 0 for n in prs) or
                len(prs) != len(set(prs))):
            raise ReferenceError('annotation_invalid')
    if chained and (type(entry['seq']) is not int or entry['seq'] <= 0 or
                    not _matches(DIGEST, entry['previous_sha256'])):
        raise ReferenceError('annotation_invalid')


def _parse_annotations(body):
    if len(body) > MAX_ANNOTATION_BYTES:
        raise ReferenceError('annotation_bound')
    if body and not body.endswith(b'\n'):
        raise ReferenceError('annotation_invalid')
    lines = body.splitlines(keepends=True)
    if len(lines) > MAX_ANNOTATIONS:
        raise ReferenceError('annotation_bound')
    entries, clocks, previous = [], {}, '0' * 64
    for seq, line in enumerate(lines, 1):
        if len(line) > MAX_LINE:
            raise ReferenceError('annotation_bound')
        try:
            entry = json.loads(line.decode('utf-8'), object_pairs_hook=_unique,
                               parse_constant=_constant)
            _semantic(entry, chained=True)
            if (line != _json(entry) + b'\n' or entry['seq'] != seq or
                    entry['previous_sha256'] != previous):
                raise ReferenceError('annotation_invalid')
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ReferenceError('annotation_invalid') from None
        key = (entry['proposal_id'], entry['proposal_digest'])
        observed = _timestamp(entry['observed_at'])
        if key in clocks and observed < clocks[key]:
            raise ReferenceError('annotation_time_regression')
        clocks[key] = observed
        entries.append(entry)
        previous = hashlib.sha256(line).hexdigest()
    return entries


def _read_locked(fd):
    before = _identity(os.fstat(fd))
    _private(os.fstat(fd))
    if before[5] > MAX_ANNOTATION_BYTES:
        raise ReferenceError('annotation_bound')
    os.lseek(fd, 0, os.SEEK_SET)
    chunks, remaining = [], before[5] + 1
    while remaining:
        part = os.read(fd, min(65536, remaining))
        if not part:
            break
        chunks.append(part)
        remaining -= len(part)
    body = b''.join(chunks)
    if len(body) != before[5] or _identity(os.fstat(fd)) != before:
        raise ReferenceError('concurrent_change')
    return body, before


@contextlib.contextmanager
def _annotation_file(path, write=False):
    try:
        with _Attachment(path) as attachment:
            flags = (os.O_RDWR | os.O_APPEND) if write else os.O_RDONLY
            flags |= os.O_NOFOLLOW | os.O_NONBLOCK
            created = False
            try:
                fd = os.open(attachment.path.name, flags, dir_fd=attachment.parent)
            except FileNotFoundError:
                if not write:
                    attachment.verify()
                    yield None, attachment, False
                    return
                attachment.verify()
                fd = os.open(attachment.path.name, flags | os.O_CREAT | os.O_EXCL,
                             0o600, dir_fd=attachment.parent)
                created = True
            try:
                _private(os.fstat(fd))
                try:
                    fcntl.flock(fd, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ReferenceError('lock_busy') from None
                attachment.verify(fd)
                yield fd, attachment, created
            finally:
                os.close(fd)
    except ReferenceError:
        raise
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise ReferenceError('annotation_unavailable') from None


def read_annotations(path):
    """Strict single-file parser; no creation, repair or automatic discovery."""
    _parent()
    with _annotation_file(path) as (fd, attachment, created):
        if fd is None:
            return []
        body, before = _read_locked(fd)
        entries = _parse_annotations(body)
        attachment.verify(fd, before)
        return entries


def append_annotation(path, entry):
    """Explicit trusted-parent append; every prewrite refusal preserves bytes."""
    _writer_parent()  # Must precede even path conversion or storage inspection.
    try:
        _semantic(entry)
        # Detach caller-owned mutable input before taking the storage lock.
        semantic = json.loads(_json(entry).decode('utf-8'))
        # Reject an oversized first record before creating the file.
        prospective = dict(semantic, seq=1, previous_sha256='0' * 64)
        if len(_json(prospective)) + 1 > MAX_LINE:
            raise ReferenceError('annotation_bound')
    except ReferenceError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ReferenceError('annotation_invalid') from None
    with _annotation_file(path, write=True) as (fd, attachment, created):
        body, before = _read_locked(fd)
        entries = _parse_annotations(body)
        key = (semantic['proposal_id'], semantic['proposal_digest'])
        if any((e['proposal_id'], e['proposal_digest']) == key and
               _timestamp(e['observed_at']) > _timestamp(semantic['observed_at']) for e in entries):
            raise ReferenceError('annotation_time_regression')
        result = dict(semantic, seq=len(entries) + 1,
                      previous_sha256=hashlib.sha256(body.splitlines(keepends=True)[-1]).hexdigest()
                      if entries else '0' * 64)
        line = _json(result) + b'\n'
        if (len(entries) >= MAX_ANNOTATIONS or len(line) > MAX_LINE or
                len(body) + len(line) > MAX_ANNOTATION_BYTES):
            raise ReferenceError('annotation_bound')
        # Re-read detects an unlocked writer as well as inode/attachment changes.
        current, current_identity = _read_locked(fd)
        if current != body or current_identity != before:
            raise ReferenceError('concurrent_change')
        attachment.verify(fd, before)
        if os.write(fd, line) != len(line):
            # A real I/O failure can leave a partial tail; never repair/truncate.
            raise ReferenceError('annotation_write_failed')
        os.fsync(fd)
        if created:
            os.fsync(attachment.parent)
        after, after_identity = _read_locked(fd)
        if after != body + line:
            raise ReferenceError('concurrent_change')
        attachment.verify(fd, after_identity)
        return result


def _validated_annotations(annotations):
    try:
        cutoff = None
        if isinstance(annotations, dict):
            if set(annotations) != {'entries', 'cutoff'}:
                return [], None
            cutoff = _timestamp(annotations['cutoff'])
            if cutoff is None:
                return [], None
            annotations = annotations['entries']
        if not isinstance(annotations, list) or len(annotations) > MAX_ANNOTATIONS:
            return [], None
        lines, total = [], 0
        for entry in annotations:
            line = _json(entry) + b'\n'
            total += len(line)
            if len(line) > MAX_LINE or total > MAX_ANNOTATION_BYTES:
                return [], None
            lines.append(line)
        entries = _parse_annotations(b''.join(lines))
        now = dt.datetime.now(dt.timezone.utc)
        return entries, min(cutoff, now) if cutoff is not None else now
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return [], None


def annotation_at(entries, proposal_id, proposal_digest, cutoff):
    """Exclusive historical lookup; an ID's latest digest must match."""
    cutoff = _timestamp(cutoff)
    if cutoff is None:
        return None
    candidates = [e for e in entries if e['proposal_id'] == proposal_id and
                  _timestamp(e['observed_at']) < cutoff]
    latest = max(candidates, key=lambda e: (_timestamp(e['observed_at']), e['seq'])) if candidates else None
    return latest if latest and latest['proposal_digest'] == proposal_digest else None


def _path(value):
    return (isinstance(value, str) and bool(value) and not value.startswith('/') and
            '\\' not in value and all(c not in ('', '.', '..') for c in value.split('/')) and
            all(ord(c) >= 32 and ord(c) != 127 for c in value))


def _positive_time(value):
    try:
        return type(value) in (int, float) and value > 0 and math.isfinite(value)
    except (ValueError, OverflowError):
        return False


def _completed_prs(records):
    result = {}
    expected = {name: 'success' for name in REQUIRED_CI}
    for key in sorted(k for k in records if isinstance(k, str)):
        github = records[key]
        match = re.fullmatch(r'workflows/([A-Za-z0-9][A-Za-z0-9_.-]{0,127})/github\.json', key)
        if not match or match[1] == 'archive' or not isinstance(github, dict):
            continue
        run = match[1]
        report = records.get('workflows/' + run + '/report.json')
        try:
            if (not isinstance(report, dict) or report.get('run_id') != run or
                    github.get('run_id') != run or report.get('status') != 'passed' or
                    github.get('status') != 'merged' or github.get('step') != 'done' or
                    github.get('merge_status') != 'merged' or
                    type(github.get('pr_number')) is not int or github['pr_number'] <= 0 or
                    not _matches(SHA, github.get('merge_sha')) or
                    not _matches(SHA, github.get('head_sha')) or github.get('checks') != expected):
                continue
            if any(field in report and report[field] is not value for field, value in
                   (('read_only', False), ('simulated', False), ('no_git', False), ('github_enabled', True))):
                continue
            proof, cleanup = github.get('cleanup_proof'), github.get('cleanup')
            if (not isinstance(proof, dict) or not isinstance(cleanup, dict) or
                    proof.get('verified') is not True or proof.get('head_sha') != github['head_sha'] or
                    proof.get('merge_sha') != github['merge_sha'] or proof.get('checks') != expected or
                    cleanup.get('version') != 'cleanup-v1' or cleanup.get('status') != 'complete' or
                    any(cleanup.get(k, {}).get('status') not in ('deleted', 'absent') for k in ('remote', 'local')) or
                    any(cleanup.get(k, {}).get('status') != 'complete' for k in ('prune', 'sync', 'completion'))):
                continue
            files = github.get('files')
            changed = report.get('changed_files')
            if (not isinstance(files, dict) or not isinstance(changed, list) or not changed or
                    not all(_path(p) for p in changed) or len(changed) != len(set(changed))):
                continue
            if any(not _path(p) or not isinstance(v, dict) or not {'before', 'after'} <= set(v)
                   for p, v in files.items()):
                continue
            actual = sorted(p for p, v in files.items() if v['before'] != v['after'])
            if set(actual) != set(changed) or not actual:
                continue
            if 'applied' in report and (not isinstance(report['applied'], list) or set(report['applied']) != set(actual)):
                continue
            if 'scope' in report and (not isinstance(report['scope'], list) or
                                      not all(_path(p) for p in report['scope']) or
                                      not set(actual) <= set(report['scope'])):
                continue
            if 'review' in report and (not isinstance(report['review'], dict) or
                                      report['review'].get('verdict') != 'approved'):
                continue
            times = [e.get('time') for e in github.get('events', []) if isinstance(e, dict) and
                     e.get('step') == 'merge' and _positive_time(e.get('time'))]
            row = {'pr_number': github['pr_number'], 'merge_sha': github['merge_sha'],
                   'edit_files': actual, 'merge_time': max(times) if times else None}
            old = result.get(row['pr_number'])
            if old is None:
                result[row['pr_number']] = row
            elif old != row:
                # Contradictory duplicate journals cannot certify this PR.
                result[row['pr_number']] = False
        except (TypeError, ValueError, AttributeError, OverflowError):
            continue
    return {number: row for number, row in result.items() if row is not False}


def _title(value):
    from harness.improvement_report import redact_text, safe_text
    value = redact_text(value)
    # safe_text is the existing caller API; omission is explicitly exposed.
    clean = safe_text(value, 4096)
    truncated = clean != value or len(clean) > 96
    return clean[:95] + '…' if truncated else clean, truncated


def _recent(value):
    return (value is None, -value if value is not None else 0)


def _select_entries(entries, maximum, bound):
    result = []
    for entry in entries:
        try:
            if len(_json(entry)) <= bound:
                result.append(entry)
        except (TypeError, ValueError, UnicodeError, RecursionError):
            continue
        if len(result) == maximum:
            break
    return result


def render_reference(records, annotations, approved_paths):
    """Whitelist projection only. Oversized entries are skipped, never sliced."""
    if not isinstance(records, dict) or not isinstance(approved_paths, (list, tuple, set, frozenset)):
        return ''
    approved = {p for p in approved_paths if _path(p)}
    if not approved:
        return ''
    entries, cutoff = _validated_annotations(annotations)
    prs = _completed_prs(records)
    groups, seen = {}, set()
    for key in sorted(k for k in records if isinstance(k, str)):
        saved = records[key]
        if not key.startswith('proposals/') or not isinstance(saved, dict):
            continue
        proposal = saved.get('proposal')
        if not isinstance(proposal, dict):
            continue
        pid, digest = proposal.get('id'), proposal.get('digest')
        if not _matches(ID, pid) or not _matches(DIGEST, digest) or pid in seen:
            continue
        seen.add(pid)
        candidate, review = proposal.get('candidate'), proposal.get('review')
        if not isinstance(candidate, dict) or not isinstance(review, dict):
            continue
        paths = candidate.get('edit_files')
        if (not isinstance(paths, list) or not all(_path(p) for p in paths) or
                not isinstance(candidate.get('title'), str)):
            continue
        overlap = sorted(approved.intersection(paths))
        if not overlap:
            continue
        try:
            title, truncated = _title(candidate['title'])
        except (ValueError, TypeError, UnicodeError, RecursionError):
            continue
        base = {'proposal_id': pid, 'proposal_digest': digest, 'title': title,
                'title_truncated': truncated, 'edit_files': overlap,
                'review_verdict': review.get('verdict') if review.get('verdict') in VERDICTS else 'unknown'}
        annotation = annotation_at(entries, pid, digest, cutoff) if cutoff else None
        if annotation and not annotation['issues']:
            annotation = None
        issues = annotation['issues'] if annotation else [
            {'issue_key': 'unknown', 'implementation_status': 'unknown', 'matched_prs': []}]
        for issue in issues:
            group_key = ('issue', issue['issue_key']) if annotation else ('proposal', pid)
            group = groups.setdefault(group_key, {'members': [], 'statuses': [], 'prs': set()})
            group['members'].append(base)
            group['statuses'].append(issue['implementation_status'])
            group['prs'].update(n for n in issue['matched_prs'] if n in prs)
    ranked = []
    status_order = ('open', 'partial', 'unknown', 'implemented')
    for (kind, identifier), group in sorted(groups.items()):
        representative = min(group['members'], key=lambda p: p['proposal_id'])
        status = min(group['statuses'], key=status_order.index)
        row = dict(representative, issue_key=identifier if kind == 'issue' else 'unknown',
                   implementation_status=status, proposal_count=len(group['members']))
        row['edit_files'] = sorted({p for member in group['members'] for p in member['edit_files']})
        # PR numbers and recency only use certified completed journals, never merge => implemented.
        row['matched_prs'] = sorted(group['prs'])
        times = [prs[n]['merge_time'] for n in group['prs'] if prs[n]['merge_time'] is not None]
        recent = max(times) if times else None
        ranked.append(((status != 'open', _recent(recent), identifier, kind), row))
    issue_rows = _select_entries([row for _, row in sorted(ranked, key=lambda p: p[0])], 5, ISSUE_BYTES)
    pr_rows = []
    for pr in sorted(prs.values(), key=lambda p: (_recent(p['merge_time']), p['pr_number'])):
        overlap = sorted(approved.intersection(pr['edit_files']))
        if overlap:
            pr_rows.append(dict(pr, edit_files=overlap))
    pr_rows = _select_entries(pr_rows, 3, PR_BYTES)
    if not issue_rows and not pr_rows:
        return ''
    # The additive per-entry limits leave room for separators and this envelope.
    empty = {'issues': [], 'merged_prs': []}
    if len(HEADER.encode('utf-8')) + len(_json(empty)) + 8 > ENVELOPE_BYTES:
        raise ReferenceError('reference_bound')
    output = HEADER.encode('utf-8') + _json({'issues': issue_rows, 'merged_prs': pr_rows})
    if len(output) > REFERENCE_BYTES:
        raise ReferenceError('reference_bound')
    return output.decode('utf-8')
