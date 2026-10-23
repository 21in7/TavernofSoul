"""Private, immutable terminal result archives. No lookup or model/Git execution.

Only archive operations touch the archive spec. Local payloads and state are separate;
retry never repacks an already frozen payload. The active journal remains the
sole authority for workflow recovery. Local freeze uses no-replace directory
rename; remote completion uses a no-replace file link, including on NFS.
"""
import argparse
from contextlib import contextmanager
import ctypes
import errno
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import uuid

from harness import storage

CHUNK = 1024 * 1024
MAX_FILE = 64 * CHUNK
MAX_TOTAL = 256 * CHUNK
TERMINAL = {'passed', 'failed', 'interrupted', 'demonstrated'}
FILES = ('bundle.tar.gz', 'inventory.json', 'manifest.json')
RESULT_STEMS = {'doctor', 'doctor-mysql', 'doctor-browser', 'check', 'check-docs',
                'check-downloader', 'check-parser', 'check-django', 'check-pipeline',
                'check-mysql', 'check-browser', 'check-live', 'check-site',
                'downloader', 'parser', 'django', 'django-regressions', 'pipeline',
                'mysql', 'mysql-doctor', 'browser', 'browser-engine', 'live', 'itos', 'ktos'}
REPORT_FIELDS = ('run_id', 'status', 'read_only', 'simulated', 'no_git', 'github_enabled',
                 'scope', 'changed_files', 'applied', 'required_checks', 'validation_selection',
                 'delivery_validation', 'validation', 'review', 'github', 'finished_at',
                 'error_type', 'model_context_cleanup', 'command', 'checks', 'exit_code')
GIT_FIELDS = ('version', 'run_id', 'status', 'step', 'branch', 'head_sha', 'merge_sha',
              'merge_status', 'pr_number', 'pr_url', 'checks', 'cleanup', 'cleanup_proof')
RESUMED = 'archive-resumed-v1'
RESUMED_KIND = 'workflows-resumed-v1'


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_nlink,
            info.st_uid, info.st_mtime_ns, info.st_ctime_ns)


def private_directory(policy, path):
    storage._safe_path(policy.fs, path)
    policy._private_directory(path)
    return policy.fs.open_directory(path)


def read_file(policy, path, limit=MAX_FILE):
    parent = policy.fs.open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, 'rb') as handle:
        before = os.fstat(handle.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600 or
                before.st_size > limit):
            raise storage.StorageError('Archive input must be private, owned, regular and unlinked.')
        data = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
        attached = policy.fs.lstat(path)
        if len(data) != before.st_size or file_identity(before) != file_identity(after) or file_identity(after) != file_identity(attached):
            raise storage.StorageError('Archive input changed while reading.')
        return data


def write_file(policy, path, data):
    parent = private_directory(policy, path.parent)
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(parent)


def atomic_state(policy, directory, value, filename='archive-state.json'):
    policy.check_ready()
    temporary = directory / ('.archive-state-' + uuid.uuid4().hex)
    write_file(policy, temporary, encoded(value))
    parent = private_directory(policy, directory)
    try:
        os.replace(temporary.name, filename, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)


def publish_directory(parent, source, target):
    """Atomic visibility with EEXIST on *any* existing destination, even empty."""
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise storage.StorageError('Archive publication requires no-replace rename support.') from None
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(source), parent, os.fsencode(target), 1):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError(code, 'Archive destination exists.')
        raise storage.StorageError('Atomic archive publication failed.')
    os.fsync(parent)


def terminal_report(policy, directory, kind):
    report = json.loads(read_file(policy, directory / 'report.json'))
    if report.get('run_id') != directory.name or report.get('status') not in TERMINAL:
        raise storage.StorageError('Only supported terminal results may be archived.')
    if kind == 'workflows' and report.get('github', {}).get('status') in {
            'awaiting_connector', 'waiting_for_ci', 'awaiting_github', 'awaiting_ci',
            'cleanup_pending', 'needs_reconciliation'}:
        raise storage.StorageError('Pending Git delivery is not a terminal archive.')
    if kind == 'workflows' and report.get('github_enabled') and report.get('changed_files'):
        from harness import git_publish
        github = report.get('github', {})
        if report['status'] == 'passed' and not git_publish.cleanup_complete(github):
            raise storage.StorageError('Git results require final merge and cleanup proof.')
        if github.get('merge_sha') and not git_publish.cleanup_complete(github):
            raise storage.StorageError('Pending cleanup is not a terminal archive.')
    return report


def result_files(policy, directory, kind, report):
    """An explicit result allowlist. Never recurse through workspace or backup.

    Raw agent responses, source/model manifests, publication approvals and private
    validation storage config are deliberately absent, including inside report.
    """
    yield 'report.json', encoded({key: report[key] for key in REPORT_FIELDS if key in report})
    if report.get('review'):
        yield 'review.json', encoded(report['review'])
    if kind == 'workflows':
        for name in ('changes.diff', 'cleanup.json'):
            if storage._info(policy.fs, directory / name) is not None:
                yield name, read_file(policy, directory / name)
        if storage._info(policy.fs, directory / 'github.json') is not None:
            ledger = json.loads(read_file(policy, directory / 'github.json'))
            yield 'github.json', encoded({key: ledger[key] for key in GIT_FIELDS if key in ledger})
        roots = [path for path in policy.fs.children(directory)
                 if re.fullmatch(r'checks-[1-3]|prepare', path.name)]
        for root in sorted(roots):
            fd = private_directory(policy, root)
            os.close(fd)
            if root.name == 'prepare':
                for path in sorted(policy.fs.children(root)):
                    if result_name(path.relative_to(directory).as_posix()):
                        yield path.relative_to(directory).as_posix(), read_file(policy, path)
                continue
            for child in sorted(policy.fs.children(root)):
                fd = private_directory(policy, child)
                os.close(fd)
                for path in sorted(policy.fs.children(child)):
                    if result_name(path.relative_to(directory).as_posix()):
                        yield path.relative_to(directory).as_posix(), read_file(policy, path)
    else:
        for path in sorted(policy.fs.children(directory)):
            if path.stem in RESULT_STEMS and path.suffix in ('.json', '.log'):
                yield path.name, read_file(policy, path)


def bundle_fingerprint(policy, bundle_path):
    """Bounded hashing for both local construction and remote readback."""
    parent = private_directory(policy, bundle_path.parent)
    try:
        fd = os.open(bundle_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > MAX_TOTAL + CHUNK):
            raise storage.StorageError('Unsafe compressed archive.')
        hashed, size = hashlib.sha256(), 0
        while True:
            block = stream.read(CHUNK)
            if not block:
                break
            hashed.update(block)
            size += len(block)
            if size > MAX_TOTAL + CHUNK:
                raise storage.StorageError('Compressed archive exceeds its byte limit.')
        if (size != info.st_size or file_identity(info) != file_identity(os.fstat(stream.fileno())) or
                file_identity(info) != file_identity(policy.fs.lstat(bundle_path))):
            raise storage.StorageError('Compressed archive changed during verification.')
    return hashed.hexdigest(), size, info


def verify_payload(policy, directory, extra=()):
    parent = private_directory(policy, directory)
    try:
        if set(os.listdir(parent)) != set(FILES) | set(extra):
            raise storage.StorageError('Archive payload inventory differs.')
    finally:
        os.close(parent)
    manifest_data = read_file(policy, directory / 'manifest.json')
    manifest = json.loads(manifest_data)
    if manifest_data != encoded(manifest):
        raise storage.StorageError('Archive manifest bytes differ from canonical frozen data.')
    inventory_data = read_file(policy, directory / 'inventory.json')
    bundle_path = directory / 'bundle.tar.gz'
    hashed, size, info = bundle_fingerprint(policy, bundle_path)
    if manifest != {'version': 1, 'inventory_sha256': digest(inventory_data),
                    'bundle_sha256': hashed, 'bundle_bytes': size}:
        raise storage.StorageError('Archive manifest digest mismatch.')
    inventory = json.loads(inventory_data)
    if not isinstance(inventory, list) or not inventory:
        raise storage.StorageError('Archive inventory is empty.')
    observed = []
    total = 0
    parent = private_directory(policy, directory)
    try:
        fd = os.open(bundle_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, 'rb') as stream, tarfile.open(fileobj=stream, mode='r|gz') as tar:
        if file_identity(os.fstat(stream.fileno())) != file_identity(info):
            raise storage.StorageError('Compressed archive replaced during verification.')
        for member in tar:
            parts = member.name.split('/')
            if (not member.isfile() or member.mode != 0o600 or member.uid != 0 or member.gid != 0 or
                    any(part in ('', '.', '..') for part in parts) or member.name.startswith('/') or
                    member.size > MAX_FILE or not result_name(member.name)):
                raise storage.StorageError('Unsafe archive member.')
            total += member.size
            if total > MAX_TOTAL:
                raise storage.StorageError('Archive exceeds its byte limit.')
            with tar.extractfile(member) as handle:
                data = handle.read(MAX_FILE + 1)
            observed.append({'path': member.name, 'bytes': len(data), 'mode': '0600', 'sha256': digest(data)})
            if len(observed) > len(inventory):
                raise storage.StorageError('Archive contains unlisted members.')
        if (file_identity(info) != file_identity(os.fstat(stream.fileno())) or
                file_identity(info) != file_identity(policy.fs.lstat(bundle_path))):
            raise storage.StorageError('Compressed archive changed during inventory verification.')
    if observed != inventory or len({row['path'] for row in observed}) != len(observed):
        raise storage.StorageError('Archive contents differ from inventory.')
    return manifest


def result_name(name):
    if name in ('report.json', 'review.json', 'changes.diff', 'cleanup.json', 'github.json'):
        return True
    path = Path(name)
    return bool(re.fullmatch(r'(?:(?:checks-[1-3]/check(?:-[a-z]+)?/|prepare/))?[a-z][a-z0-9-]*\.(json|log)', name)) and path.stem in RESULT_STEMS


def result_inventory(policy, directory, kind, report):
    """Bind a frozen payload to the *current* terminal result, excluding state.

    archive-state.json and the returned archive status deliberately never enter
    this identity. A retry may update those without repacking, but must not
    present a formerly failed run's payload as a later successful result.
    """
    rows, total = [], 0
    for name, data in result_files(policy, directory, kind, report):
        total += len(data)
        if len(data) > MAX_FILE or total > MAX_TOTAL:
            raise storage.StorageError('Archive result exceeds its byte limit.')
        rows.append({'path': name, 'bytes': len(data), 'mode': '0600', 'sha256': digest(data)})
    if terminal_report(policy, directory, kind) != report:
        raise storage.StorageError('Terminal result changed during archive verification.')
    return rows


def verify_current_result(policy, directory, kind, report, payload):
    if result_inventory(policy, directory, kind, report) != json.loads(
            read_file(policy, payload / 'inventory.json')):
        raise storage.StorageError('Terminal results differ from the frozen archive; retain local evidence.')


def freeze(policy, directory, kind, report, destination=None):
    local = directory if destination is None else destination
    payload = local / 'archive-payload'
    if storage._info(policy.fs, payload) is not None:
        if verify_payload(policy, payload) != json.loads(read_file(policy, local / 'archive-frozen.json')):
            raise storage.StorageError('Frozen archive payload changed.')
        verify_current_result(policy, directory, kind, report, payload)
        return payload
    policy.check_ready()
    stage = local / ('.archive-build-' + uuid.uuid4().hex)
    policy.fs.create_directory(stage)
    inventory, total = [], 0
    # Payload is built only on local active storage; NFS never sees file-at-a-time results.
    parent = private_directory(policy, stage)
    try:
        fd = os.open('bundle.tar.gz', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as raw:
            os.fchmod(raw.fileno(), 0o600)
            with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode='w|', format=tarfile.USTAR_FORMAT) as tar:
                    for name, data in result_files(policy, directory, kind, report):
                        total += len(data)
                        if len(data) > MAX_FILE or total > MAX_TOTAL:
                            raise storage.StorageError('Archive result exceeds its byte limit.')
                        policy.check_ready()
                        member = tarfile.TarInfo(name)
                        member.size, member.mode, member.mtime = len(data), 0o600, 0
                        tar.addfile(member, io.BytesIO(data))
                        inventory.append({'path': name, 'bytes': len(data), 'mode': '0600', 'sha256': digest(data)})
            raw.flush()
            os.fsync(raw.fileno())
    finally:
        os.close(parent)
    write_file(policy, stage / 'inventory.json', encoded(inventory))
    bundle_hash, bundle_size, _ = bundle_fingerprint(policy, stage / 'bundle.tar.gz')
    write_file(policy, stage / 'manifest.json', encoded({'version': 1,
        'inventory_sha256': digest(encoded(inventory)), 'bundle_sha256': bundle_hash, 'bundle_bytes': bundle_size}))
    frozen = verify_payload(policy, stage)
    # Re-prove terminal state and attachment after reading all result files.
    if terminal_report(policy, directory, kind) != report:
        raise storage.StorageError('Terminal result changed during archive creation.')
    verify_current_result(policy, directory, kind, report, stage)
    policy.check_ready()
    # A separate immutable checkpoint pins the first terminal payload. A crash
    # here may leave a build directory; preserve it rather than silently repack.
    checkpoint = local / 'archive-frozen.json'
    if storage._info(policy.fs, checkpoint) is None:
        write_file(policy, checkpoint, encoded(frozen))
    elif json.loads(read_file(policy, checkpoint)) != frozen:
        raise storage.StorageError('Archive checkpoint differs; retain local evidence.')
    parent = private_directory(policy, local)
    try:
        publish_directory(parent, stage.name, payload.name)
    finally:
        os.close(parent)
    return payload


def archive_ready(policy, target=None):
    spec = policy.archive
    mount = policy._mount_path('archive', spec, target=target)
    policy._floor('archive', spec, policy._space('archive', spec, {}, mount))
    if storage._info(policy.fs, spec.path) is not None:
        policy._private_directory(spec.path)


def directory_identity(policy, descriptor):
    info = os.fstat(descriptor)
    return [info.st_dev, info.st_ino, policy.fs.mount_identity(descriptor)]


def commit_record(expected, kind, run_id):
    return {'version': 1, 'kind': kind, 'run_id': run_id, 'manifest': expected}


def verify_archive(policy, directory, kind, run_id):
    """Readers must require this final marker, never just a prepared payload."""
    expected = verify_payload(policy, directory, extra=('commit.json',))
    if read_file(policy, directory / 'commit.json') != encoded(commit_record(expected, kind, run_id)):
        raise storage.StorageError('Archive completion marker differs from its payload.')
    return expected


def link_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_uid, info.st_mtime_ns)


def publish_file(parent, temporary, final, refresh, verified):
    """Only a verified, same-directory temporary can become a final name.

    A lost LINK reply or interruption before UNLINK leaves exactly two known
    aliases. No other multiple-link state is accepted, even for matching bytes.
    The caller has verified full contents and the temporary's attachment.
    """
    refresh()
    before = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
    if file_identity(before) != file_identity(verified) or before.st_nlink != 1:
        raise storage.StorageError('Unsafe archive publication source.')
    os.link(temporary, final, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
    os.fsync(parent)
    finish_link(parent, temporary, final, refresh, verified)


def finish_link(parent, temporary, final, refresh, verified):
    refresh()
    source = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
    target = os.stat(final, dir_fd=parent, follow_symlinks=False)
    if (file_identity(source) != file_identity(target) or source.st_nlink != 2 or
            link_identity(source) != link_identity(verified) or
            not stat.S_ISREG(source.st_mode) or source.st_uid != os.geteuid() or
            stat.S_IMODE(source.st_mode) != 0o600):
        raise storage.StorageError('Unknown archive hardlink; preserve destination.')
    # Both names are in the pinned directory; nlink=2 proves no third alias.
    os.unlink(temporary, dir_fd=parent)
    os.fsync(parent)
    target = os.stat(final, dir_fd=parent, follow_symlinks=False)
    if target.st_nlink != 1 or (source.st_dev, source.st_ino) != (target.st_dev, target.st_ino):
        raise storage.StorageError('Archive link cleanup did not verify.')


def transfer_file(policy, payload, name, parent, temporary, refresh, data=None):
    """Compare an interrupted prefix before appending; never truncate/replace.

    The receipt fixes the only allowed temporary name. Existing complete files
    and the narrowly allowed two-link transition are read-only until verified.
    """
    if data is None:
        source_parent = private_directory(policy, payload)
        try:
            source_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_parent)
        finally:
            os.close(source_parent)
        reader = os.fdopen(source_fd, 'rb')
        source_info = os.fstat(reader.fileno())
        if (not stat.S_ISREG(source_info.st_mode) or source_info.st_nlink != 1 or
                source_info.st_uid != os.geteuid() or stat.S_IMODE(source_info.st_mode) != 0o600 or
                source_info.st_size > MAX_TOTAL + CHUNK):
            reader.close()
            raise storage.StorageError('Unsafe archive transfer source.')
        size = source_info.st_size
    else:
        reader, size, source_info = io.BytesIO(data), len(data), None
    try:
        refresh()
        names = set(os.listdir(parent))
        final_exists, temporary_exists = name in names, temporary in names
        selected = name if final_exists else temporary
        if not final_exists and not temporary_exists:
            fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
            os.fchmod(fd, 0o600)
        else:
            # No write access to a final or a two-link transition.
            fd = os.open(selected, (os.O_RDONLY if final_exists else os.O_RDWR) |
                         os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb' if final_exists else 'r+b') as target:
            before = os.fstat(target.fileno())
            links = 2 if final_exists and temporary_exists else 1
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != links or
                    before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600 or
                    before.st_size > size or (final_exists and before.st_size != size)):
                raise storage.StorageError('Unsafe or conflicting archive file.')
            if links == 2 and file_identity(os.stat(temporary, dir_fd=parent, follow_symlinks=False)) != file_identity(before):
                raise storage.StorageError('Archive temporary is not the known final alias.')
            remaining = before.st_size
            while remaining:
                refresh()
                block = reader.read(min(CHUNK, remaining))
                if not block or target.read(len(block)) != block:
                    raise storage.StorageError('Interrupted archive prefix differs from frozen payload.')
                remaining -= len(block)
            if file_identity(before) != file_identity(os.fstat(target.fileno())):
                raise storage.StorageError('Archive file changed during prefix verification.')
            if not final_exists:
                target.seek(before.st_size)
                while True:
                    block = reader.read(CHUNK)
                    if not block:
                        break
                    refresh()
                    attached = os.stat(selected, dir_fd=parent, follow_symlinks=False)
                    if file_identity(attached) != file_identity(os.fstat(target.fileno())):
                        raise storage.StorageError('Archive temporary attachment changed.')
                    target.write(block)
                    target.flush()
                os.fsync(target.fileno())
            after = os.fstat(target.fileno())
            if (after.st_size != size or after.st_nlink != links or
                    file_identity(after) != file_identity(os.stat(selected, dir_fd=parent, follow_symlinks=False))):
                raise storage.StorageError('Archive file changed during transfer.')
            if source_info is not None and (
                    file_identity(source_info) != file_identity(os.fstat(reader.fileno())) or
                    file_identity(source_info) != file_identity(policy.fs.lstat(payload / name))):
                raise storage.StorageError('Frozen archive transfer source changed.')
        refresh()
        if final_exists:
            if temporary_exists:
                finish_link(parent, temporary, name, refresh, after)
        else:
            publish_file(parent, temporary, name, refresh, after)
    finally:
        reader.close()


def transfer(policy, payload, kind, run_id):
    expected = verify_payload(policy, payload)
    archive_ready(policy)
    policy.fs.create_directory(policy.archive.path)
    os.close(private_directory(policy, policy.archive.path))
    category = policy.archive.path / kind
    archive_ready(policy, category)
    policy.fs.create_directory(category)
    parent = private_directory(policy, category)
    try:
        category_identity = directory_identity(policy, parent)
        destination = category / run_id
        receipt_path = payload.parent / 'archive-transfer.json'
        if storage._info(policy.fs, receipt_path) is None:
            archive_ready(policy, category)
            # Exclusive allocation: even an empty unknown destination is a collision.
            os.mkdir(run_id, 0o700, dir_fd=parent)
            os.fsync(parent)
            child = private_directory(policy, destination)
            try:
                os.fchmod(child, 0o700)
                receipt = {'version': 1, 'manifest': expected, 'destination': str(destination),
                           'category_identity': category_identity,
                           'directory_identity': directory_identity(policy, child),
                           'token': uuid.uuid4().hex, 'published': [], 'committed': False}
            finally:
                os.close(child)
            policy.check_ready()
            write_file(policy, receipt_path, encoded(receipt))
            local_parent = private_directory(policy, receipt_path.parent)
            try:
                os.fsync(local_parent)
            finally:
                os.close(local_parent)
        else:
            receipt = json.loads(read_file(policy, receipt_path))
        child = private_directory(policy, destination)
        try:
            if (not isinstance(receipt, dict) or set(receipt) != {
                    'version', 'manifest', 'destination', 'category_identity', 'directory_identity',
                    'token', 'published', 'committed'} or
                    receipt['version'] != 1 or receipt['manifest'] != expected or
                    receipt['destination'] != str(destination) or
                    receipt['category_identity'] != category_identity or
                    receipt['directory_identity'] != directory_identity(policy, child) or
                    not isinstance(receipt['token'], str) or
                    not re.fullmatch(r'[a-f0-9]{32}', receipt['token']) or
                    receipt['published'] not in [list(FILES[:count]) for count in range(len(FILES) + 1)] or
                    type(receipt['committed']) is not bool or
                    (receipt['committed'] and receipt['published'] != list(FILES))):
                raise storage.StorageError('Archive transfer receipt or attachment differs.')
            prefix = '.transfer-' + receipt['token'] + '-'
            allowed = set(FILES) | {'commit.json'}
            def fresh():
                archive_ready(policy, destination)
                for path, descriptor, identity in (
                        (category, parent, category_identity),
                        (destination, child, receipt['directory_identity'])):
                    attached = private_directory(policy, path)
                    try:
                        if (directory_identity(policy, attached) != identity or
                                directory_identity(policy, descriptor) != identity):
                            raise storage.StorageError('Archive destination attachment changed.')
                    finally:
                        os.close(attached)
                if not set(os.listdir(child)) <= allowed | {prefix + name for name in allowed}:
                    raise storage.StorageError('Unknown archive entry; preserve destination.')
            fresh()
            if receipt['committed']:
                if verify_archive(policy, destination, kind, run_id) != expected:
                    raise storage.StorageError('Committed archive changed; preserve destination.')
                fresh()
                return expected
            if not set(receipt['published']) <= set(os.listdir(child)):
                raise storage.StorageError('Previously published archive file is missing.')
            # A visible marker must already have a full payload. Recovery may
            # remove only its verified temporary alias, never repair its payload.
            if 'commit.json' in os.listdir(child):
                if not set(FILES) <= set(os.listdir(child)):
                    raise storage.StorageError('Incomplete committed archive.')
                for name in FILES:
                    if prefix + name in os.listdir(child):
                        raise storage.StorageError('Committed archive has unfinished payload links.')
            for name in FILES:
                transfer_file(policy, payload, name, child, prefix + name, fresh)
                if name not in receipt['published']:
                    receipt['published'].append(name)
                    atomic_state(policy, receipt_path.parent, receipt, 'archive-transfer.json')
            # The marker is last: verify every member/hash before making it visible.
            fresh()
            marker_temp = prefix + 'commit.json'
            extras = tuple(name for name in (marker_temp, 'commit.json') if name in os.listdir(child))
            if verify_payload(policy, destination, extra=extras) != expected:
                raise storage.StorageError('Transferred archive did not verify.')
            transfer_file(policy, payload, 'commit.json', child, marker_temp, fresh,
                          data=encoded(commit_record(expected, kind, run_id)))
            fresh()
            if verify_archive(policy, destination, kind, run_id) != expected:
                raise storage.StorageError('Published archive did not verify.')
            fresh()
            receipt['committed'] = True
            atomic_state(policy, receipt_path.parent, receipt, 'archive-transfer.json')
            return expected
        finally:
            os.close(child)
    finally:
        os.close(parent)


@contextmanager
def archive_mutex(policy, directory, kind):
    """Both archive intents use the original run's persistent lock inode."""
    directory = Path(directory)
    if kind not in ('workflows', 'checks') or not storage.RUN_ID.fullmatch(directory.name):
        raise storage.StorageError('Invalid archive run identity.')
    if kind == 'workflows':
        policy.validate_run_directory(directory)
    if not storage._within(directory, policy.artifact_root) or (kind == 'checks' and directory.parent != policy.artifact_root / kind):
        raise storage.StorageError('Archives require the selected active run root.')
    policy.check_ready()
    parent = private_directory(policy, directory)
    try:
        fd = os.open('archive.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, 'a') as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise storage.StorageError('Unsafe archive lock.')
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if file_identity(os.fstat(lock.fileno())) != file_identity(policy.fs.lstat(directory / 'archive.lock')):
            raise storage.StorageError('Archive lock attachment changed.')
        yield directory


def archive_run(policy, directory, kind='workflows'):
    """Archive only one active terminal run; failure preserves outcome and sources."""
    if policy.version != 2:
        return {'status': 'not_configured'}
    with archive_mutex(policy, directory, kind) as directory:
        try:
            report = terminal_report(policy, directory, kind)
            atomic_state(policy, directory, {'status': 'pending', 'run_id': directory.name})
            payload = freeze(policy, directory, kind, report)
            manifest = transfer(policy, payload, kind, directory.name)
            verify_current_result(policy, directory, kind, report, payload)
            result = {'status': 'archived', 'run_id': directory.name, **manifest}
            atomic_state(policy, directory, result)
            return result
        except (Exception, KeyboardInterrupt) as exc:
            result = {'status': 'pending', 'run_id': directory.name, 'error_type': type(exc).__name__}
            atomic_state(policy, directory, result)
            return result


def trusted_recovery_context(successor=False):
    # These are exclusion markers, not authentication of a human or parent.
    if (any(os.environ.get(key) for key in ('TAVERN_WORKFLOW_CHILD',
            'TAVERN_IMPROVEMENT_DISCOVERY', 'TAVERN_IMPROVEMENT_UNATTENDED')) or
            successor and (os.environ.get('READ_ONLY') == '1' or os.environ.get('GIT') == '0')):
        raise storage.StorageError('Archive recovery requires the trusted parent.')


def payload_records(policy, payload, names):
    """Read selected allowlisted results from an already verified bounded tar."""
    _, _, pinned = bundle_fingerprint(policy, payload / 'bundle.tar.gz')
    parent = private_directory(policy, payload)
    try:
        fd = os.open('bundle.tar.gz', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    records = {}
    with os.fdopen(fd, 'rb') as raw, tarfile.open(fileobj=raw, mode='r|gz') as tar:
        before = os.fstat(raw.fileno())
        if file_identity(before) != file_identity(pinned):
            raise storage.StorageError('Previous archive attachment changed.')
        total = 0
        for member in tar:
            total += member.size
            if not member.isfile() or member.size > MAX_FILE or total > MAX_TOTAL or not result_name(member.name):
                raise storage.StorageError('Unsafe previous archive member.')
            if member.name in names:
                with tar.extractfile(member) as handle:
                    records[member.name] = json.loads(handle.read(MAX_FILE + 1))
        if (file_identity(before) != file_identity(os.fstat(raw.fileno())) or
                file_identity(before) != file_identity(policy.fs.lstat(payload / 'bundle.tar.gz'))):
            raise storage.StorageError('Previous archive changed during evidence reading.')
    return records


def previous_archive(policy, directory):
    """Read only: never repair, transfer, or update the original archive/receipt."""
    payload = directory / 'archive-payload'
    manifest = verify_payload(policy, payload)
    if read_file(policy, directory / 'archive-frozen.json') != encoded(manifest):
        raise storage.StorageError('Previous archive checkpoint differs.')
    receipt_data = read_file(policy, directory / 'archive-transfer.json')
    receipt = json.loads(receipt_data)
    destination = policy.archive.path / 'workflows' / directory.name
    archive_ready(policy, destination)
    identities = []
    for path in (destination.parent, destination):
        fd = private_directory(policy, path)
        try:
            identities.append(directory_identity(policy, fd))
        finally:
            os.close(fd)
    if (set(receipt) != {'version', 'manifest', 'destination', 'category_identity',
            'directory_identity', 'token', 'published', 'committed'} or
            receipt['version'] != 1 or receipt['manifest'] != manifest or
            receipt['destination'] != str(destination) or
            receipt['category_identity'] != identities[0] or
            receipt['directory_identity'] != identities[1] or
            receipt['published'] != list(FILES) or receipt['committed'] is not True or
            not isinstance(receipt['token'], str) or not re.fullmatch(r'[a-f0-9]{32}', receipt['token']) or
            verify_archive(policy, destination, 'workflows', directory.name) != manifest):
        raise storage.StorageError('Previous committed archive or receipt differs.')
    return manifest, digest(receipt_data), payload_records(policy, payload, {'report.json', 'github.json'})


def resumed_evidence(policy, directory, report, old):
    """Permit delivery recovery only; review, diff and validation cannot change."""
    from harness import git_publish
    from harness import failure_feedback
    previous = old['report.json']
    mutable = {'status', 'github', 'finished_at', 'error_type'}
    project = lambda value: {key: value[key] for key in REPORT_FIELDS if key in value and key not in mutable}
    if (previous.get('run_id') != directory.name or previous.get('status') != 'failed' or
            report.get('status') != 'passed' or project(previous) != project(report) or
            any(report.get(key) is not False for key in ('read_only', 'simulated', 'no_git')) or
            report.get('github_enabled') is not True):
        raise storage.StorageError('Recovery must retain the original reviewed publishing result.')
    inventory = result_inventory(policy, directory, 'workflows', report)
    previous_inventory = json.loads(read_file(policy, directory / 'archive-payload' / 'inventory.json'))
    stable = lambda rows: [row for row in rows if row['path'] not in {'report.json', 'github.json', 'cleanup.json'}]
    if (stable(inventory) != stable(previous_inventory) or
            not any(row['path'] == 'changes.diff' and row['bytes'] > 0 for row in inventory)):
        raise storage.StorageError('Reviewed diff or validation artifacts changed.')
    changed, scope = report.get('changed_files'), report.get('scope')
    if (not isinstance(changed, list) or not changed or len(set(changed)) != len(changed) or
            not isinstance(scope, list) or set(changed) - set(scope) or
            set(report.get('applied', [])) != set(changed)):
        raise storage.StorageError('Recovery requires the original applied scope.')
    review = report.get('review', {})
    doc = review.get('documentation', {})
    if (set(review) != {'verdict', 'summary', 'findings', 'documentation'} or
            review['verdict'] != 'approved' or review['findings'] != [] or not review['summary'] or
            set(doc) != {'status', 'files', 'reason'} or doc['status'] not in {'updated', 'not_required'} or
            not doc['reason'] or not isinstance(doc['files'], list) or set(doc['files']) - set(scope) or
            (doc['status'] == 'updated' and not doc['files']) or
            (doc['status'] == 'not_required' and doc['files'])):
        raise storage.StorageError('Independent implementation review evidence is incomplete.')
    checks = report.get('delivery_validation', report.get('validation'))
    required = report.get('required_checks')
    if (not isinstance(required, list) or not required or len(set(required)) != len(required) or
            not isinstance(checks, list) or len(checks) != len(required) or
            {item['command'] for item in checks} != set(required)):
        raise storage.StorageError('Final validation selection differs.')
    names = {row['path'] for row in inventory}
    for item in checks:
        command = item['command']
        candidates = {str(directory / ('checks-' + str(round_id)) / command / (command + '.json'))
                      for round_id in range(1, 4)}
        path = item.get('report')
        if (command not in RESULT_STEMS or not command.startswith('check') or path not in candidates or
                item.get('status') != 'passed' or type(item.get('exit_code')) is not int or
                item['exit_code'] != 0 or not failure_feedback.check_groups_passed(item.get('checks')) or
                Path(path).relative_to(directory).as_posix() not in names):
            raise storage.StorageError('Successful original validation artifacts are required.')
        actual = json.loads(read_file(policy, Path(path)))
        if actual.get('status') != 'passed' or actual.get('checks') != item['checks']:
            raise storage.StorageError('Validation summary differs from its actual result.')
    ledger = json.loads(read_file(policy, directory / 'github.json'))
    before = old['github.json']
    if before.get('status') != 'failed' or before.get('merge_sha'):
        raise storage.StorageError('Only failed delivery before merge supports this recovery.')
    for key in ('version', 'run_id', 'branch'):
        if ledger.get(key) != before.get(key):
            raise storage.StorageError('Original Git run identity changed.')
    for key in ('head_sha', 'pr_number', 'pr_url'):
        if before.get(key) is not None and ledger.get(key) != before[key]:
            raise storage.StorageError('Previously pinned Git identity changed.')
    for key in ('branch', 'base_sha', 'head_sha', 'pr_number', 'pr_url'):
        pinned = previous.get('github', {}).get(key)
        if pinned is not None and report.get('github', {}).get(key) != pinned:
            raise storage.StorageError('Original report Git identity changed.')
    expected = {name: 'success' for name in git_publish.REQUIRED}
    proof = ledger.get('cleanup_proof', {})
    if (ledger.get('version') != 'github-v1' or ledger.get('run_id') != directory.name or
            ledger.get('branch') != 'codex/' + directory.name or ledger.get('status') != 'merged' or
            ledger.get('step') != 'done' or not git_publish.cleanup_complete(ledger) or
            any(not isinstance(ledger.get(key), str) or not re.fullmatch(r'[a-f0-9]{40}', ledger[key])
                for key in ('head_sha', 'merge_sha')) or
            type(ledger.get('pr_number')) is not int or ledger['pr_number'] <= 0 or
            not isinstance(ledger.get('pr_url'), str) or not re.fullmatch(
                r'https://github.com/[^/]+/[^/]+/pull/' + str(ledger['pr_number']), ledger['pr_url']) or
            ledger.get('checks') != expected or proof.get('verified') is not True or
            proof.get('checks') != expected or proof.get('head_sha') != ledger['head_sha'] or
            proof.get('merge_sha') != ledger['merge_sha'] or report.get('github') != git_publish.summary(ledger)):
        raise storage.StorageError('Pinned merge, CI and cleanup proof are required.')
    cleanup = json.loads(read_file(policy, directory / 'cleanup.json'))
    if (cleanup.get('run_id') != directory.name or cleanup.get('head_sha') != ledger['head_sha'] or
            cleanup.get('merge_sha') != ledger['merge_sha'] or any(
                cleanup.get(key) != value for key, value in ledger['cleanup'].items())):
        raise storage.StorageError('Cleanup checkpoint differs from the completed Git run.')
    return inventory


def archive_resumed_run(policy, directory):
    """Explicit trusted-parent failed→passed successor; no execution or approval."""
    trusted_recovery_context(successor=True)  # Before inspecting the supplied storage policy.
    if policy.version != 2:
        return {'status': 'not_configured'}
    directory = Path(directory)
    result = {'status': 'pending', 'run_id': directory.name, 'generation': 'resumed-v1',
              'intent': 'failed-to-passed'}
    local = directory / RESUMED
    owned = False
    try:
        with archive_mutex(policy, directory, 'workflows'):
            try:
                report = terminal_report(policy, directory, 'workflows')
                result['terminal_status'] = report['status']
                manifest, receipt_hash, old = previous_archive(policy, directory)
                result['original'] = {'terminal_status': old['report.json'].get('status'), 'manifest': manifest}
                inventory = resumed_evidence(policy, directory, report, old)
                parent = private_directory(policy, directory)
                try:
                    record = {'version': 1, 'intent': 'failed-to-passed', 'run_id': directory.name,
                              'run_directory': str(directory), 'run_identity': directory_identity(policy, parent),
                              'generation': 'resumed-v1', 'previous_manifest': manifest,
                              'previous_manifest_sha256': digest(encoded(manifest)),
                              'previous_receipt_sha256': receipt_hash, 'current_inventory': inventory,
                              'current_inventory_sha256': digest(encoded(inventory)),
                              'destination': str(policy.archive.path / RESUMED_KIND / directory.name)}
                    if storage._info(policy.fs, local) is None:
                        policy.check_ready()
                        os.mkdir(local.name, 0o700, dir_fd=parent)
                        os.fsync(parent)
                        os.close(private_directory(policy, local))
                        write_file(policy, local / 'recovery.json', encoded(record))
                        child = private_directory(policy, local)
                        try:
                            os.fsync(child)
                        finally:
                            os.close(child)
                    else:
                        os.close(private_directory(policy, local))
                        if read_file(policy, local / 'recovery.json') != encoded(record):
                            raise storage.StorageError('Recovery linkage or current result changed; preserve evidence.')
                    owned = True
                finally:
                    os.close(parent)
                result['inventory_sha256'] = record['current_inventory_sha256']
                atomic_state(policy, local, result)
                payload = freeze(policy, directory, 'workflows', report, destination=local)
                if read_file(policy, payload / 'inventory.json') != encoded(inventory):
                    raise storage.StorageError('Frozen successor differs from recovery inventory.')
                verify_current_result(policy, directory, 'workflows', report, payload)
                manifest = transfer(policy, payload, RESUMED_KIND, directory.name)
                verify_current_result(policy, directory, 'workflows', report, payload)
                # Recheck the immutable predecessor and linkage after remote readback too.
                prior, receipt, old = previous_archive(policy, directory)
                if (prior != record['previous_manifest'] or receipt != record['previous_receipt_sha256'] or
                        resumed_evidence(policy, directory, report, old) != inventory or
                        read_file(policy, local / 'recovery.json') != encoded(record)):
                    raise storage.StorageError('Recovery evidence changed during publication.')
                result.update(status='archived', destination=record['destination'], **manifest)
                atomic_state(policy, local, result)
            except (Exception, KeyboardInterrupt) as exc:
                result.update(status='pending', error_type=type(exc).__name__)
                if owned:
                    atomic_state(policy, local, result)
    except (Exception, KeyboardInterrupt) as exc:
        result.update(status='pending', error_type=type(exc).__name__)
    return result


def resumed_status(policy, directory):
    """Local-only status; a stale successor never represents changed results."""
    local = directory / RESUMED
    result = {'status': 'pending', 'run_id': directory.name, 'generation': 'resumed-v1'}
    try:
        os.close(private_directory(policy, local))
        saved = json.loads(read_file(policy, local / 'archive-state.json'))
        record_data = read_file(policy, local / 'recovery.json')
        record = json.loads(record_data)
        report = terminal_report(policy, directory, 'workflows')
        parent = private_directory(policy, directory)
        try:
            identity = directory_identity(policy, parent)
        finally:
            os.close(parent)
        if (record_data != encoded(record) or record['version'] != 1 or
                record['intent'] != 'failed-to-passed' or record['run_identity'] != identity or
                record['run_id'] != directory.name or record['run_directory'] != str(directory) or
                record['generation'] != 'resumed-v1' or saved['run_id'] != directory.name or
                saved['generation'] != 'resumed-v1' or report['status'] != 'passed' or
                saved['status'] not in {'pending', 'archived'} or
                record['destination'] != str(policy.archive.path / RESUMED_KIND / directory.name) or
                record['previous_manifest_sha256'] != digest(encoded(record['previous_manifest'])) or
                read_file(policy, directory / 'archive-frozen.json') != encoded(record['previous_manifest']) or
                digest(read_file(policy, directory / 'archive-transfer.json')) != record['previous_receipt_sha256'] or
                record['current_inventory'] != result_inventory(policy, directory, 'workflows', report) or
                record['current_inventory_sha256'] != digest(encoded(record['current_inventory'])) or
                saved.get('inventory_sha256') != digest(encoded(record['current_inventory']))):
            return result
        if saved['status'] == 'archived':
            manifest = verify_payload(policy, local / 'archive-payload')
            receipt = json.loads(read_file(policy, local / 'archive-transfer.json'))
            if (any(saved.get(key) != value for key, value in manifest.items()) or
                    receipt.get('manifest') != manifest or receipt.get('destination') != record['destination'] or
                    receipt.get('published') != list(FILES) or receipt.get('committed') is not True or
                    read_file(policy, local / 'archive-frozen.json') != encoded(manifest) or
                    read_file(policy, local / 'archive-payload' / 'inventory.json') != encoded(record['current_inventory'])):
                return result
        return saved
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--kind', choices=('workflows', 'checks'), default='workflows')
    parser.add_argument('--resume-failed-to-passed', action='store_true',
                        help='archive only the original run success in a separate immutable generation')
    args = parser.parse_args(argv)
    try:
        trusted_recovery_context(successor=args.resume_failed_to_passed)
        if args.resume_failed_to_passed and args.kind != 'workflows':
            raise storage.StorageError('Resumed success archives require the original workflow run.')
        policy = storage.resolve_storage()
        if not storage.RUN_ID.fullmatch(args.run_id):
            raise storage.StorageError('Invalid archive run ID.')
        directory = (policy.find_run(args.run_id) if args.kind == 'workflows' else
                     policy.artifact_root / args.kind / args.run_id)
        result = (archive_resumed_run(policy, directory) if args.resume_failed_to_passed else
                  archive_run(policy, directory, args.kind))
        print(json.dumps(result, sort_keys=True))
        return 0 if result['status'] == 'archived' else 1
    except (ValueError, OSError):
        print(json.dumps({'status': 'pending', 'error': 'archive_unavailable'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
