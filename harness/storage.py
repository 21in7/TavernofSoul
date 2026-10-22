"""Shared, lazy harness storage policy; importing this module performs no I/O.

Configuration precedence (no merge): HARNESS_STORAGE_CONFIG, then the optional
PROJECT/logs/harness/storage-local.json, then the historical local defaults.
The environment path must be absolute. A missing explicit config, or any invalid
present config, is fatal. Errors never echo input, JSON contents or OS messages.

Version 1 is exactly {"version": 1, "artifacts": {...}, "temporary": {...}}.
Each directory object has exactly "path", "required_mount", "min_free_bytes".
Paths are absolute, normalized, symlink-free; application roots are strict mount
descendants, disjoint from each other and from both repository ancestors and
descendants. Mounts may be shared. Floors are nonnegative integer bytes (not bool).
There is no automatic migration, mount change, archive, deletion or local fallback.

Integrators call resolve_storage(ROOT, env=..., fs=...) at operation time, never
at import time. report_dir(category, explicit=..., local_default=REPORTS) honors
explicit --report-dir, HARNESS_REPORT_DIR, configured artifact/category, then the
caller's local default. Passing the current ROOT/REPORTS keeps tests isolated;
no configuration is ever read from another imported module's original ROOT.
workflow_roots/find_run/latest_run include the untouched legacy local root.
project_lock_path is ALWAYS PROJECT/logs/harness/workflows/.lock. Journal locks
remain in find_run(...)/github.lock; callers retain their journal/hash checks.

prepare() checks ALL mounts and floors before ANY mkdir/probe, then creates only
missing private application directories and probes both roots. Routine output
and temporary preparation probes newly created roots and actual destinations,
without probing unrelated existing roots. ensure_directory() checks for
nested mounts between each output and its configured required mount. Explicit
outputs outside either configured mount are caller-selected overrides, still
subject to all configured readiness checks and private-directory probes. Existing unrelated paths
are never chmodded. Configured application directories must already be owned by
the process with mode 0700, or are created with that mode. Probe files are 0600.
Every write operation must recheck readiness; do not cache readiness as a lease.

temporary_directory/mkdtemp are ONLY for non-credential work. Without config,
context copies keep /tmp and validation uses tempfile's existing default. With
config both use temporary.path. credential_runtime_root stays in local logs;
credential_temp_root is /tmp and never follows configured temporary/report roots.
Never export this policy as global TMPDIR, HOME or the real CODEX_HOME.
Context-manager cleanup pins its unique directory's allocation identity before
use. Removing that owned tree is one high-level filesystem operation: readiness
is checked at cleanup entry and immediately before final root removal, freshly
for each call. Every chmod/unlink/rmdir still proves root, parent and ancestor
attachment, ownership, device and kernel mount identity without following links.
Only owned directories regain owner access; files and external targets are
never chmodded. Replacement paths, foreign owners and nested mounts fail closed.

CLI (no models): python -m harness.storage status | doctor [--probe]. Both are
read-only by default; --probe requires existing private application directories.
python -m harness.storage resolve reports [--category agents] [--report-dir PATH]
  --prepare : checks mounts/floors, creates/probes private output, prints one path
Other resolve targets: artifacts, temporary, context, workflows, lock,
credential-runtime, credential-temp. --prepare is for non-credential outputs only.
Use a quoted shell command substitution, never eval the result. --root permits an
explicit project root. Example setup (edit illustrative paths before preparing):
  mkdir -p logs/harness
  (umask 077; cp -n harness/storage-config.json.example logs/harness/storage-local.json)
  python -m harness.storage doctor
  python -m harness.storage resolve artifacts --prepare
  make storage-doctor PROBE=1
Alternatively set HARNESS_STORAGE_CONFIG=/absolute/private/storage.json. Track
only the example; do not include the private config in model source contexts.
"""

import argparse
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass, field
from functools import wraps
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import uuid


CONFIG_ENV = 'HARNESS_STORAGE_CONFIG'
REPORT_ENV = 'HARNESS_REPORT_DIR'
RUN_ID = re.compile(r'^[0-9]+-[a-f0-9]{6}$')
_CATEGORY = re.compile(r'^[a-z][a-z0-9_-]*$')


class StorageError(ValueError):
    """Actionable fixed metadata only; never includes arbitrary config values."""


def _diagnostic_at(name):
    """Observe improvement calls without importing optional orchestration code.

    An active improvement trace necessarily has its module loaded already.
    Standalone storage packages need only this file; their errors still propagate.
    """
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            diagnostics = sys.modules.get('harness.improvement_diagnostics')
            if diagnostics is None:
                return function(*args, **kwargs)
            with diagnostics.boundary(name):
                return function(*args, **kwargs)
        return call
    return decorate


class _StatxTimestamp(ctypes.Structure):
    _fields_ = [('seconds', ctypes.c_int64), ('nanoseconds', ctypes.c_uint32),
                ('reserved', ctypes.c_int32)]


class _Statx(ctypes.Structure):
    # Linux statx's fixed 256-byte ABI; the trailing fields are not consumed.
    _fields_ = [('mask', ctypes.c_uint32), ('block_size', ctypes.c_uint32),
                ('attributes', ctypes.c_uint64), ('links', ctypes.c_uint32),
                ('uid', ctypes.c_uint32), ('gid', ctypes.c_uint32),
                ('mode', ctypes.c_uint16), ('reserved0', ctypes.c_uint16),
                ('inode', ctypes.c_uint64), ('size', ctypes.c_uint64),
                ('blocks', ctypes.c_uint64), ('attributes_mask', ctypes.c_uint64),
                ('atime', _StatxTimestamp), ('btime', _StatxTimestamp),
                ('ctime', _StatxTimestamp), ('mtime', _StatxTimestamp),
                ('rdev_major', ctypes.c_uint32), ('rdev_minor', ctypes.c_uint32),
                ('dev_major', ctypes.c_uint32), ('dev_minor', ctypes.c_uint32),
                ('mount_id', ctypes.c_uint64), ('reserved', ctypes.c_uint64 * 13)]


class FileSystem:
    """Offline seams: subclass mount_ready/free_bytes/probe (or I/O methods).

    No mount table, host settings, credentials or subprocesses are consulted.
    os.path.ismount requires the exact configured mount, not just an existing dir.
    Directory traversal/creation uses no-follow file descriptors on Unix.
    """

    def lstat(self, path):
        return path.lstat()

    def local_filesystem(self, path):
        """Positive Linux filesystem allowlist, using the kernel, never mount files.

        Unknown and userspace/network filesystems fail closed. Probe the closest
        existing ancestor without following links; readiness repeats this proof.
        """
        while True:
            try:
                fd = self.open_directory(path)
                break
            except FileNotFoundError:
                if path == path.parent:
                    return False
                path = path.parent
        try:
            buffer = ctypes.create_string_buffer(512)
            call = ctypes.CDLL(None).fstatfs
            call.argtypes = (ctypes.c_int, ctypes.c_void_p)
            call.restype = ctypes.c_int
            if call(fd, buffer) != 0:
                return False
            magic = ctypes.c_long.from_buffer(buffer).value & 0xffffffff
            return magic in {0xef53, 0x58465342, 0x9123683e, 0x01021994,
                             0x794c7630, 0x2fc12fc1, 0xf2f52010}
        except (AttributeError, OSError):
            return False
        finally:
            os.close(fd)

    def mount_ready(self, path):
        return os.path.ismount(path)

    def mount_identity(self, directory, name=''):
        """Kernel mount identity, including same-device bind mounts; no host files.

        Cleanup fails closed on platforms/libcs/kernels without STATX_MNT_ID.
        Empty names inspect a pinned descriptor; other names never follow links
        or trigger automounts (AT_EMPTY_PATH | AT_SYMLINK_NOFOLLOW | AT_NO_AUTOMOUNT).
        """
        try:
            statx = ctypes.CDLL(None).statx
        except (AttributeError, OSError):
            raise StorageError('Temporary cleanup requires kernel mount identity support.') from None
        statx.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                         ctypes.c_uint, ctypes.POINTER(_Statx))
        statx.restype = ctypes.c_int
        info = _Statx()
        if statx(directory, os.fsencode(name), 0x1900, 0x1000, ctypes.byref(info)) != 0 or \
                not info.mask & 0x1000:
            raise StorageError('Temporary cleanup cannot establish kernel mount identity.')
        return info.mount_id

    def free_bytes(self, path):
        return shutil.disk_usage(path).free

    def children(self, path):
        return list(path.iterdir())

    def read_bytes(self, path):
        directory = self.open_directory(path.parent)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                raise StorageError('Storage JSON must be a regular file under 1 MiB.')
            return handle.read(1024 * 1024 + 1)

    def open_directory(self, path):
        """Open every existing ancestor with no-follow, including probe parents."""
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in path.parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=fd)
                os.close(fd)
                fd = child
        except BaseException:
            os.close(fd)
            raise
        return fd

    def create_directory(self, path):
        """Create missing components privately; never chmod an existing component."""
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in path.parts[1:]:
                created = False
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=fd)
                except FileNotFoundError:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        created = True
                    except FileExistsError:
                        pass
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=fd)
                try:
                    if created:
                        os.fchmod(child, 0o700)
                except BaseException:
                    os.close(child)
                    raise
                os.close(fd)
                fd = child
        finally:
            os.close(fd)

    def create_temporary(self, parent, prefix):
        """Create a unique work directory through a pinned no-follow parent."""
        directory = self.open_directory(parent)
        try:
            info = os.fstat(directory)
            if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
                raise StorageError('Temporary storage requires an owned private 0700 application directory.')
            for _ in range(100):
                name = prefix + uuid.uuid4().hex
                try:
                    os.mkdir(name, 0o700, dir_fd=directory)
                except FileExistsError:
                    continue
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
                try:
                    os.fchmod(child, 0o700)
                finally:
                    os.close(child)
                return parent / name
            raise StorageError('Cannot allocate a unique private temporary directory.')
        finally:
            os.close(directory)

    def probe(self, path):
        """Actual write/fsync/read/delete, only a unique file in the application."""
        directory = self.open_directory(path)
        name = '.harness-storage-probe-' + uuid.uuid4().hex
        created = False
        try:
            info = os.fstat(directory)
            if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
                raise StorageError('Storage probe requires an owned private 0700 application directory.')
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            created = True
            with os.fdopen(fd, 'w+b') as handle:
                os.fchmod(handle.fileno(), 0o600)
                if stat.S_IMODE(os.fstat(handle.fileno()).st_mode) != 0o600:
                    raise StorageError('Storage probe could not establish private file mode.')
                handle.write(b'harness-storage-probe\n')
                handle.flush()
                os.fsync(handle.fileno())
                handle.seek(0)
                if handle.read() != b'harness-storage-probe\n':
                    raise StorageError('Storage probe readback failed.')
        finally:
            try:
                if created:
                    os.unlink(name, dir_fd=directory)
            finally:
                os.close(directory)


def _absolute(value, label):
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value or any(
            ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise StorageError(label + ' must be an absolute normalized path.')
    path = Path(value)
    if not path.is_absolute() or value.startswith('//') or '..' in value.split('/') or \
            '.' in value.split('/') or str(path) != value:
        raise StorageError(label + ' must be an absolute normalized path.')
    return path


def _within(path, root):
    return path == root or root in path.parents


def _overlap(first, second):
    return _within(first, second) or _within(second, first)


def _info(fs, path):
    try:
        return fs.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise StorageError('Cannot inspect storage path; check directory access.') from None


def _safe_path(fs, path, *, directory=True):
    """Inspect every ancestor without resolve() hiding symlinks (even dangling)."""
    parts = [*reversed(path.parents), path]
    for component in parts:
        info = _info(fs, component)
        if info is None:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise StorageError('Unsafe storage path: symlinked component.')
        if component != path or directory:
            if not stat.S_ISDIR(info.st_mode):
                raise StorageError('Storage directory has a non-directory component.')
        elif not stat.S_ISREG(info.st_mode):
            raise StorageError('Storage record must be a regular file.')
    return path


def _json(fs, path, label):
    _safe_path(fs, path, directory=False)
    try:
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise StorageError(label + ' has duplicate JSON fields.')
                result[key] = value
            return result

        data = fs.read_bytes(path)
        if len(data) > 1024 * 1024:
            raise StorageError(label + ' exceeds 1 MiB.')

        def invalid_constant(_):
            raise StorageError(label + ' has a nonstandard JSON number.')

        return json.loads(data.decode('utf-8'), object_pairs_hook=unique_pairs,
                          parse_constant=invalid_constant)
    except StorageError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise StorageError(label + ' cannot be read as valid JSON.') from None


def resolve_project_root(project_root=None, *, fs=None):
    """No global ROOT; explicit roots never consult the original repository."""
    fs = fs or FileSystem()
    root = _absolute(project_root if project_root is not None else
                     Path(__file__).absolute().parents[1], 'Project root')
    _safe_path(fs, root)
    if _info(fs, root) is None:
        raise StorageError('Project root must be an existing directory.')
    return root


@dataclass(frozen=True)
class DirectorySpec:
    path: Path
    required_mount: Path
    min_free_bytes: int


@dataclass
class Storage:
    root: Path
    artifacts: DirectorySpec = None
    temporary: DirectorySpec = None
    config_path: Path = None
    env: dict = field(default_factory=dict, repr=False)
    fs: FileSystem = field(default_factory=FileSystem, repr=False)
    version: int = 1
    archive: DirectorySpec = None

    def require_local(self, path):
        if self.version == 2 and not self.fs.local_filesystem(path):
            raise StorageError('Version 2 work and report paths require a supported local filesystem.')

    @property
    def configured(self):
        return self.config_path is not None

    @property
    def artifact_root(self):
        return self.artifacts.path if self.configured else self.root / 'logs/harness'

    @property
    def temp_root(self):
        """None retains tempfile's legacy default without altering its globals."""
        return self.temporary.path if self.configured else None

    @property
    def context_root(self):
        return self.temporary.path if self.configured else Path('/tmp')

    @property
    def project_lock_path(self):
        return _safe_path(self.fs, self.root / 'logs/harness/workflows/.lock', directory=False)

    @property
    def credential_runtime_root(self):
        return _safe_path(self.fs, self.root / 'logs/harness/agents/runtime')

    @property
    def credential_temp_root(self):
        return Path('/tmp')

    def _specs(self):
        return (('artifacts', self.artifacts), ('temporary', self.temporary)) if self.configured else ()

    def _mount_path(self, label, spec, *, target=None):
        """Fresh containment/mount proof, independent of free-space measurement."""
        target = spec.path if target is None else target
        if target == spec.required_mount or not _within(target, spec.required_mount):
            raise StorageError(label + ' output must be below its required mount.')
        _safe_path(self.fs, spec.required_mount)
        _safe_path(self.fs, target)
        try:
            if not self.fs.mount_ready(spec.required_mount):
                raise StorageError(label + ' required mount is absent; mount it before using storage.')
            mount_info = _info(self.fs, spec.required_mount)
            if mount_info is None:
                raise StorageError(label + ' required mount is absent; no local fallback is permitted.')
            for ancestor in (target, *target.parents):
                if ancestor == spec.required_mount:
                    break
                info = _info(self.fs, ancestor)
                if info is not None and (info.st_dev != mount_info.st_dev or self.fs.mount_ready(ancestor)):
                    raise StorageError(label + ' application path crosses a different mount.')
            return mount_info
        except OSError:
            raise StorageError(label + ' mount/free-space check failed; check mount access.') from None

    def _space(self, label, spec, measurements, mount_info):
        """Measurements belong only to the caller's unchanged read-only boundary."""
        mount = spec.required_mount
        if mount_info is None:
            raise StorageError(label + ' required mount is absent; no local fallback is permitted.')
        identity = (mount_info.st_dev, mount_info.st_ino)
        if mount not in measurements:
            try:
                measurements[mount] = (identity, True, self.fs.free_bytes(mount))
            except OSError:
                measurements[mount] = (identity, False, None)
        previous, measured, free = measurements[mount]
        if previous != identity:
            raise StorageError(label + ' required mount changed during storage validation; check mounts.')
        if not measured:
            raise StorageError(label + ' mount/free-space check failed; check mount access.') from None
        return free

    def _floor(self, label, spec, free):
        if type(free) is not int or free < spec.min_free_bytes:
            raise StorageError(label + ' free space is below min_free_bytes; free space or revise the floor.')

    @_diagnostic_at('storage_readiness')
    def check_ready(self):
        """Read-only; all required mounts/floors are checked before any writes."""
        return self._check_ready()

    def _check_ready(self, *, target=None):
        """One boundary, including optional fresh output proof before returning."""
        measurements = {}
        self.require_local(self.root)
        for label, spec in self._specs():
            self.require_local(spec.path)
            mount_info = self._mount_path(label, spec)
            self._floor(label, spec, self._space(label, spec, measurements, mount_info))
            if _info(self.fs, spec.path) is not None:
                self._private_directory(spec.path)
        if target is not None:
            self._output_safe(target, measurements=measurements)
        return self

    def _private_directory(self, path):
        _safe_path(self.fs, path)
        info = _info(self.fs, path)
        if info is None or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
            raise StorageError('Application directory must be owned by this user with mode 0700; '
                               'use a dedicated private directory.')

    def _create(self, path, private):
        _safe_path(self.fs, path)
        missing = _info(self.fs, path) is None
        if missing:
            try:
                self.fs.create_directory(path)
            except OSError:
                raise StorageError('Cannot create private storage directory; check access and mount readiness.') from None
        if private:
            self._private_directory(path)
        return missing

    def _probe(self, path):
        self._private_directory(path)
        try:
            self.fs.probe(path)
        except OSError:
            raise StorageError('Private storage writeability probe failed; check permissions and available space.') from None

    def _prepare_roots(self, *, probe, target=None):
        """Setup only; every mutation has a fresh complete readiness boundary.

        Existing roots are checked by each write gate, never used as evidence
        of writeability. A target root's probe is deferred to its output gate.
        """
        for _, spec in self._specs():
            if _info(self.fs, spec.path) is not None:
                continue
            self._check_ready(target=spec.path)
            self._create(spec.path, private=True)
            if probe and spec.path != target:
                self._check_ready(target=spec.path)
                self._probe(spec.path)

    def prepare(self, *, probe=True):
        self._prepare_roots(probe=False)
        if probe:
            for _, spec in self._specs():
                self._check_ready(target=spec.path)
                self._probe(spec.path)
        else:
            self.check_ready()
        return self

    def _output_safe(self, path, *, legacy=False, measurements=None):
        """Fresh containment only; callers own the all-spec readiness boundary."""
        self.require_local(path)
        _safe_path(self.fs, path)
        # Local historical records retain their own containment contract even
        # if a broadly configured mount (such as /) also contains the project.
        if legacy and _within(path, self.root):
            return path
        if self.configured:
            for _, spec in self._specs():
                if _within(spec.required_mount, path):
                    raise StorageError('Output directory must not be a mount root or its ancestor.')
            if _within(self.root, path):
                raise StorageError('Output directory must not contain the project root.')
            # The application root alone cannot prove a descendant is on the
            # same filesystem: a nested mount may have appeared since setup.
            application = [(label, spec) for label, spec in self._specs()
                           if _within(path, spec.path)]
            mounts = [(label, spec) for label, spec in self._specs()
                      if _within(path, spec.required_mount)]
            if application or mounts:
                label, spec = max(application or mounts,
                                  key=lambda item: len(item[1].required_mount.parts))
                mount_info = self._mount_path(label, spec, target=path)
                if measurements is not None:
                    self._floor(label, spec, self._space(label, spec, measurements, mount_info))
        return path

    def ensure_directory(self, path, *, probe=True):
        """Prepare a non-credential output directory, respecting explicit overrides."""
        path = self._output_safe(_absolute(path, 'Output directory'))
        self._prepare_roots(probe=probe, target=path)
        self._check_ready(target=path)
        created = self._create(path, private=self.configured)
        if probe and self.configured:
            if created:
                self._check_ready(target=path)
            self._probe(path)
        return path

    def report_dir(self, category=None, *, explicit=None, local_default=None):
        """Selection only; writers must call ensure_directory before output."""
        if category is not None and (not isinstance(category, str) or not _CATEGORY.fullmatch(category)):
            raise StorageError('Invalid report category; use a single lowercase directory name.')
        if explicit is not None:
            path = _absolute(explicit, 'Explicit report directory')
        elif REPORT_ENV in self.env:
            path = _absolute(self.env[REPORT_ENV], 'HARNESS_REPORT_DIR')
        elif self.configured:
            path = self.artifact_root / category if category else self.artifact_root
        elif local_default is not None:
            path = _absolute(local_default, 'Local report default')
        else:
            path = self.artifact_root / category if category else self.artifact_root
        self.require_local(path)
        if self.version == 2 and not _within(path, self.artifact_root):
            raise StorageError('Version 2 reports must remain below active artifacts.')
        self._check_ready(target=path)
        return path

    def workflow_root(self, *, local_default=None):
        return self.report_dir('workflows', local_default=local_default)

    def workflow_roots(self, *, local_default=None):
        """Current report override, configured default, supplied legacy, local legacy.

        Including both configured and canonical roots keeps overrides from hiding
        durable records. No directories are created by lookup.
        """
        current = self.workflow_root(local_default=local_default)
        candidates = [current]
        if self.configured:
            candidates.append(self.artifact_root / 'workflows')
        if local_default is not None:
            candidates.append(_absolute(local_default, 'Local workflow default'))
        candidates.append(self.root / 'logs/harness/workflows')
        roots = []
        for path in candidates:
            self._output_safe(path, legacy=True)
            if path not in roots:
                roots.append(path)
        return tuple(roots)

    def validate_run_directory(self, directory, *, local_default=None):
        directory = _absolute(directory, 'Run directory')
        if not RUN_ID.fullmatch(directory.name):
            raise StorageError('Invalid workflow run ID.')
        roots = self.workflow_roots(local_default=local_default)
        if directory.parent not in roots:
            raise StorageError('Workflow run directory escapes its selected root.')
        _safe_path(self.fs, directory)
        self._output_safe(directory, legacy=True)
        if self.find_run(directory.name, local_default=local_default) != directory:
            raise StorageError('Workflow run directory differs from its selected root.')
        return directory

    def find_run(self, run_id, *, local_default=None):
        """Locate a single existing run, rejecting ambiguity and symlink escapes."""
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise StorageError('Invalid workflow run ID.')
        matches = []
        for root in self.workflow_roots(local_default=local_default):
            directory = root / run_id
            self._output_safe(directory, legacy=True)
            if _info(self.fs, directory) is not None:
                matches.append(directory)
        if len(matches) > 1:
            raise StorageError('Ambiguous workflow run ID exists in distinct storage roots; '
                               'resolve the duplicate explicitly without rewriting approved journals.')
        if not matches:
            raise StorageError('Workflow run ID was not found in current or legacy storage.')
        return matches[0]

    def record_path(self, directory, name, *, local_default=None):
        """Containment for the selected journal root; existing journal checks remain."""
        directory = self.validate_run_directory(directory, local_default=local_default)
        if not isinstance(name, str) or not name or Path(name).is_absolute() or \
                any(part in ('', '.', '..') for part in name.split('/')):
            raise StorageError('Invalid workflow record path.')
        path = _absolute(directory / name, 'Workflow record path')
        _safe_path(self.fs, path, directory=False)
        self._output_safe(path.parent, legacy=True)
        return path

    def latest_run(self, *, local_default=None):
        """Read-only newest record across roots (mtime_ns; deterministic tie break).

        Valid latest.json pointers participate using their modification times;
        report.json scanning also supports missing old pointers. Any duplicate ID
        or unsafe pointer/record fails rather than choosing an arbitrary journal.
        No historical JSON, snapshot, absolute workspace path or pointer is changed.
        """
        candidates = []
        for root in self.workflow_roots(local_default=local_default):
            if _info(self.fs, root) is None:
                continue
            try:
                children = self.fs.children(root)
            except OSError:
                raise StorageError('Cannot list workflow storage; check directory access.') from None
            for child in children:
                if not RUN_ID.fullmatch(child.name):
                    continue
                directory = self.find_run(child.name, local_default=local_default)
                record = self.record_path(directory, 'report.json', local_default=local_default)
                info = _info(self.fs, record)
                if info is not None:
                    candidates.append((info.st_mtime_ns, directory.name, str(directory), directory))
            marker = root / 'latest.json'
            if _info(self.fs, marker) is not None:
                data = _json(self.fs, marker, 'Workflow latest pointer')
                if not isinstance(data, dict) or set(data) != {'run_id'}:
                    raise StorageError('Workflow latest pointer must contain only run_id.')
                directory = self.find_run(data['run_id'], local_default=local_default)
                if directory.parent != root:
                    raise StorageError('Workflow latest pointer escapes its selected root.')
                record = self.record_path(directory, 'report.json', local_default=local_default)
                if _info(self.fs, record) is None:
                    raise StorageError('Workflow latest pointer has no report record.')
                candidates.append((_info(self.fs, marker).st_mtime_ns, directory.name, str(directory), directory))
        if not candidates:
            raise StorageError('No workflow reports exist in current or legacy storage.')
        return max(candidates)[3]

    def mkdtemp(self, *, prefix='tavern-harness-', purpose='validation'):
        path, _ = self._allocate_temporary(prefix=prefix, purpose=purpose)
        return path

    def _allocate_temporary(self, *, prefix, purpose):
        """Keep allocation identity private; public mkdtemp still returns a path."""
        if purpose not in ('context', 'validation'):
            raise StorageError('Temporary purpose must be context or validation (never credentials).')
        if not isinstance(prefix, str) or not prefix or '/' in prefix or '\\' in prefix or \
                any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in prefix):
            raise StorageError('Temporary prefix must be a plain filename prefix.')
        parent = self.context_root if purpose == 'context' else self.temp_root
        if self.configured:
            self._prepare_roots(probe=True)
        elif parent is not None:
            _safe_path(self.fs, parent)
        try:
            if self.configured:
                self._check_ready(target=parent)
                path = self.fs.create_temporary(parent, prefix)
                self._check_ready(target=path)
                self._probe(path)
            else:
                path = Path(tempfile.mkdtemp(prefix=prefix, dir=str(parent) if parent is not None else None))
            self._private_directory(path)
            return path, self.fs.lstat(path)
        except OSError:
            raise StorageError('Cannot create private non-credential temporary directory.') from None

    @contextmanager
    def temporary_directory(self, *, prefix='tavern-harness-', purpose='validation'):
        path, allocated = self._allocate_temporary(prefix=prefix, purpose=purpose)
        parent = directory = None
        try:
            parent = self.fs.open_directory(path.parent)
            parent_identity = os.fstat(parent)
            directory = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=parent)
            identity = os.fstat(directory)
            if (identity.st_dev, identity.st_ino) != (allocated.st_dev, allocated.st_ino):
                raise StorageError('Temporary cleanup directory identity changed.')
            if identity.st_uid != os.geteuid() or not stat.S_ISDIR(identity.st_mode):
                raise StorageError('Temporary cleanup requires an owned directory.')
            try:
                yield path
            finally:
                self._remove_owned_temporary(path, parent, directory, identity, parent_identity)
        finally:
            if directory is not None:
                os.close(directory)
            if parent is not None:
                os.close(parent)

    def _remove_owned_temporary(self, path, parent, directory, identity, parent_identity):
        """Remove only this call's pinned non-credential tree, without following links.

        Readonly regular files need no chmod: unlink uses parent permissions.
        This also preserves modes on external hardlinks. Directory chmod uses an
        owned, identity-checked descriptor, never a path or a symlink target.
        Inaccessible directories and concurrent identity changes are errors.
        Readiness belongs to this whole removal, never a persistent lease;
        attachment and mount proofs remain fresh at every destructive operation.
        """
        def same(first, second):
            return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)

        ancestry = []

        def attached(where, owner, name, expected):
            current = os.stat(name, dir_fd=owner, follow_symlinks=False)
            if not same(current, expected) or stat.S_IFMT(current.st_mode) != stat.S_IFMT(expected.st_mode):
                raise StorageError('Temporary cleanup directory identity changed.')
            if current.st_uid != os.geteuid():
                raise StorageError('Temporary cleanup refuses foreign-owned entries.')
            if self.fs.mount_identity(owner, name) != mount_identity or \
                    current.st_dev != identity.st_dev or (
                    not stat.S_ISLNK(current.st_mode) and self.fs.mount_ready(where)):
                raise StorageError('Temporary cleanup refuses mount boundaries.')
            return current

        def root_attached():
            # A pinned parent alone is insufficient if it has since been moved.
            current_parent = self.fs.open_directory(path.parent)
            try:
                current = os.fstat(current_parent)
                pinned = os.fstat(parent)
                if not same(current, parent_identity) or not same(pinned, parent_identity):
                    raise StorageError('Temporary cleanup parent identity changed.')
                # Legacy /tmp may be a shared parent owned by another user.
                # Its pinned owner must remain unchanged; tree entries below
                # it must always be owned by this process.
                if current.st_uid != parent_identity.st_uid or pinned.st_uid != parent_identity.st_uid:
                    raise StorageError('Temporary cleanup refuses foreign-owned entries.')
                if current.st_dev != identity.st_dev or \
                        self.fs.mount_identity(current_parent) != mount_identity or \
                        self.fs.mount_identity(parent) != mount_identity:
                    raise StorageError('Temporary cleanup refuses mount boundaries.')
            finally:
                os.close(current_parent)
            attached(path, parent, path.name, identity)
            for where, owner, name, expected in ancestry:
                attached(where, owner, name, expected)

        def remove(where, owner, name, fd, expected):
            ancestry.append((where, owner, name, expected))
            try:
                remove_contents(where, owner, name, fd, expected)
            finally:
                ancestry.pop()

        def remove_contents(where, owner, name, fd, expected):
            root_attached()
            current = attached(where, owner, name, expected)
            opened = os.fstat(fd)
            if not same(current, opened) or opened.st_uid != os.geteuid():
                raise StorageError('Temporary cleanup directory identity changed.')
            if self.fs.mount_identity(fd) != mount_identity:
                raise StorageError('Temporary cleanup refuses mount boundaries.')
            # Restore access only on owned directories, within the pinned tree.
            mode = stat.S_IMODE(opened.st_mode)
            if mode & 0o700 != 0o700:
                os.fchmod(fd, mode | 0o700)
            for child_name in os.listdir(fd):
                root_attached()
                attached(where, owner, name, expected)
                child_path = where / child_name
                child = os.stat(child_name, dir_fd=fd, follow_symlinks=False)
                if child.st_uid != os.geteuid():
                    raise StorageError('Temporary cleanup refuses foreign-owned entries.')
                if stat.S_ISDIR(child.st_mode):
                    attached(child_path, fd, child_name, child)
                    child_fd = os.open(child_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                       dir_fd=fd)
                    try:
                        remove(child_path, fd, child_name, child_fd, child)
                    finally:
                        os.close(child_fd)
                else:
                    # Unlink does not alter linked external bytes or permissions.
                    attached(child_path, fd, child_name, child)
                    os.unlink(child_name, dir_fd=fd)
            if len(ancestry) == 1:
                # Final boundary: readiness may have changed during this tree's
                # removal. Re-prove attachment afterwards, before removing root.
                self.check_ready()
            root_attached()
            attached(where, owner, name, expected)
            os.rmdir(name, dir_fd=owner)

        try:
            # All configured mounts/floors precede even the first directory chmod.
            self.check_ready()
            mount_identity = self.fs.mount_identity(parent)
            if self.fs.mount_identity(directory) != mount_identity:
                raise StorageError('Temporary cleanup refuses mount boundaries.')
            root_attached()
            remove(path, parent, path.name, directory, identity)
        except OSError:
            raise StorageError('Cannot safely remove owned non-credential temporary directory.') from None

    def status(self, *, probe=False):
        """Read-only unless probing existing application directories is requested."""
        result = {'version': self.version, 'mode': 'configured' if self.configured else 'local',
                  'artifact_root': str(self.artifact_root),
                  'temp_root': str(self.temp_root) if self.temp_root else None,
                  'context_root': str(self.context_root),
                  'project_lock': str(self.project_lock_path),
                  'credential_runtime_root': str(self.credential_runtime_root),
                  'credential_temp_root': str(self.credential_temp_root),
                  'directories': {}, 'status': 'ready'}
        # Only known, validated path fields are emitted; config/env contents are not.
        measurements = {}
        for label, spec in self._specs():
            state = {'path': str(spec.path), 'required_mount': str(spec.required_mount),
                     'min_free_bytes': spec.min_free_bytes, 'mount_ready': False,
                     'free_bytes': None, 'private_directory': False, 'probe': 'not_requested'}
            try:
                self.require_local(self.root)
                self.require_local(spec.path)
                _safe_path(self.fs, spec.required_mount)
                state['mount_ready'] = bool(self.fs.mount_ready(spec.required_mount))
                if state['mount_ready']:
                    state['free_bytes'] = self._space(
                        label, spec, measurements, _info(self.fs, spec.required_mount))
                mount_info = self._mount_path(label, spec)
                state['free_bytes'] = self._space(label, spec, measurements, mount_info)
                self._floor(label, spec, state['free_bytes'])
                if _info(self.fs, spec.path) is not None:
                    self._private_directory(spec.path)
                    state['private_directory'] = True
            except StorageError as exc:
                state['error'] = str(exc)
                result['status'] = 'failed'
            except OSError:
                state['error'] = 'Mount/free-space inspection failed; check storage access.'
                result['status'] = 'failed'
            result['directories'][label] = state
        # No measurement survives into the probe writes below.
        del measurements
        if probe and self.configured:
            # Require BOTH roots to exist before the first probe, then check
            # all mounts/floors/modes freshly at each probe's write boundary.
            try:
                for _, spec in self._specs():
                    self._private_directory(spec.path)
                for label, spec in self._specs():
                    self._check_ready(target=spec.path)
                    self._probe(spec.path)
                    result['directories'][label]['probe'] = 'passed'
            except StorageError as exc:
                result['status'] = 'failed'
                result['probe_error'] = str(exc)
        elif probe:
            result['probe'] = 'not_applicable_to_legacy_defaults'
        return result


@_diagnostic_at('config')
def resolve_storage(project_root=None, *, env=None, fs=None):
    """Parse at call time; injection avoids real mounts and ambient test config."""
    fs = fs or FileSystem()
    root = resolve_project_root(project_root, fs=fs)
    environment = dict(os.environ if env is None else env)
    explicit = CONFIG_ENV in environment
    config_path = (_absolute(environment[CONFIG_ENV], 'HARNESS_STORAGE_CONFIG') if explicit
                   else root / 'logs/harness/storage-local.json')
    _safe_path(fs, config_path, directory=False)
    if _info(fs, config_path) is None:
        if explicit:
            raise StorageError('Explicit HARNESS_STORAGE_CONFIG is missing; supply an existing config file.')
        return Storage(root=root, env=environment, fs=fs)
    data = _json(fs, config_path, 'Storage config')
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] not in (1, 2):
        raise StorageError('Storage config requires version 1 or 2.')
    version = data['version']
    labels = ('artifacts', 'temporary', 'archive') if version == 2 else ('artifacts', 'temporary')
    if set(data) != {'version', *labels}:
        raise StorageError('Storage config fields must match its explicit version.')
    specs = {}
    for label in labels:
        value = data[label]
        if not isinstance(value, dict) or set(value) != {'path', 'required_mount', 'min_free_bytes'}:
            raise StorageError(label + ' must have exactly path, required_mount and min_free_bytes.')
        path = _absolute(value['path'], label + '.path')
        mount = _absolute(value['required_mount'], label + '.required_mount')
        floor = value['min_free_bytes']
        if type(floor) is not int or floor < 0:
            raise StorageError(label + '.min_free_bytes must be a nonnegative integer byte count.')
        # Archive parsing is lexical only: an unavailable NFS server must never
        # block local work, progress, lookup or approval.
        if label != 'archive':
            _safe_path(fs, path)
            _safe_path(fs, mount)
        if path == mount or not _within(path, mount):
            raise StorageError(label + '.path must be a strict descendant of its required_mount.')
        if _overlap(path, root):
            raise StorageError(label + '.path must be outside repository ancestry.')
        specs[label] = DirectorySpec(path, mount, floor)
    for index, label in enumerate(labels):
        if any(_overlap(specs[label].path, specs[other].path) for other in labels[index + 1:]):
            raise StorageError('Storage application roots must be distinct and disjoint.')
    for spec in specs.values():
        for other in specs.values():
            if _within(other.required_mount, spec.path):
                raise StorageError('Application roots must not contain required mounts.')
    selected = Storage(root, specs['artifacts'], specs['temporary'], config_path, environment, fs,
                       version=version, archive=specs.get('archive'))
    if version == 2:
        for path in (root, specs['artifacts'].path, specs['temporary'].path):
            selected.require_local(path)
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description='Inspect/resolve harness storage without model calls.')
    parser.add_argument('command', choices=('status', 'doctor', 'resolve'))
    parser.add_argument('target', nargs='?', choices=('reports', 'artifacts', 'temporary', 'context',
                                                   'workflows', 'lock', 'credential-runtime', 'credential-temp'))
    # Validate the original spelling; Path() would erase repeated/trailing
    # separators and dot components before the strict path validator sees them.
    parser.add_argument('--root')
    parser.add_argument('--category')
    parser.add_argument('--report-dir')
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args(argv)
    if args.command != 'resolve' and (args.target or args.category or args.report_dir or args.prepare):
        parser.error('Output selection/--prepare options are for resolve only.')
    if args.command == 'resolve' and (not args.target or args.probe):
        parser.error('resolve requires a target; use --prepare to prepare/probe outputs.')
    if args.target not in (None, 'reports', 'workflows') and (args.category or args.report_dir):
        parser.error('Report overrides are for reports/workflows only.')
    try:
        policy = resolve_storage(args.root)
        if args.command != 'resolve':
            result = policy.status(probe=args.probe)
            print(json.dumps(result, sort_keys=True))
            return 0 if result['status'] == 'ready' else 1
        policy.check_ready()
        if args.target == 'reports':
            path = policy.report_dir(args.category, explicit=args.report_dir)
        elif args.target == 'workflows':
            path = policy.report_dir('workflows', explicit=args.report_dir)
        else:
            path = {'artifacts': policy.artifact_root, 'temporary': policy.temp_root,
                    'context': policy.context_root, 'lock': policy.project_lock_path,
                    'credential-runtime': policy.credential_runtime_root,
                    'credential-temp': policy.credential_temp_root}[args.target]
        if args.prepare:
            if args.target in ('lock', 'credential-runtime', 'credential-temp'):
                raise StorageError('--prepare only supports non-credential application outputs.')
            if path is not None:
                path = policy.ensure_directory(path)
        # Empty temporary output in local mode means omit tempfile's dir argument.
        print(str(path) if path is not None else '')
        return 0
    except StorageError as exc:
        import sys
        print(json.dumps({'status': 'failed', 'error': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
