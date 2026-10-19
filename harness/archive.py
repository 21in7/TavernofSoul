"""Private, immutable terminal result archives. No lookup or model/Git execution.

Only archive_run touches the archive spec. Local payloads and state are separate;
retry never repacks an already frozen payload. The active journal remains the
sole authority for workflow recovery. Local freeze uses no-replace directory
rename; remote completion uses a no-replace file link, including on NFS.
"""
import argparse
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


def freeze(policy, directory, kind, report):
    payload = directory / 'archive-payload'
    if storage._info(policy.fs, payload) is not None:
        if verify_payload(policy, payload) != json.loads(read_file(policy, directory / 'archive-frozen.json')):
            raise storage.StorageError('Frozen archive payload changed.')
        verify_current_result(policy, directory, kind, report, payload)
        return payload
    policy.check_ready()
    stage = directory / ('.archive-build-' + uuid.uuid4().hex)
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
    checkpoint = directory / 'archive-frozen.json'
    if storage._info(policy.fs, checkpoint) is None:
        write_file(policy, checkpoint, encoded(frozen))
    elif json.loads(read_file(policy, checkpoint)) != frozen:
        raise storage.StorageError('Archive checkpoint differs; retain local evidence.')
    parent = private_directory(policy, directory)
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


def archive_run(policy, directory, kind='workflows'):
    """Archive only one active terminal run; failure preserves outcome and sources."""
    if policy.version != 2:
        return {'status': 'not_configured'}
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--kind', choices=('workflows', 'checks'), default='workflows')
    args = parser.parse_args(argv)
    try:
        if os.environ.get('TAVERN_WORKFLOW_CHILD'):
            raise storage.StorageError('Archive recovery requires the trusted parent.')
        policy = storage.resolve_storage()
        if not storage.RUN_ID.fullmatch(args.run_id):
            raise storage.StorageError('Invalid archive run ID.')
        directory = (policy.find_run(args.run_id) if args.kind == 'workflows' else
                     policy.artifact_root / args.kind / args.run_id)
        result = archive_run(policy, directory, args.kind)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['status'] == 'archived' else 1
    except (ValueError, OSError):
        print(json.dumps({'status': 'pending', 'error': 'archive_unavailable'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
