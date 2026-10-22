"""Short source critical sections on the unchanged historical flock inode.

Internal nested reads may borrow a lock held by this thread in this process.
Independent controllers must use reentrant=False; even another handle in the
same process then contends. No pid file, unlink, waiting, or storage fallback.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import os
import threading

from harness import improvement_diagnostics as diagnostics

_local = threading.local()


@contextmanager
def hold(selected, *, kind='project_lock', reentrant=True):
    if kind not in ('project_lock', 'workflow_lock', 'discovery_lock', 'sender_lock'):
        raise ValueError('Invalid lock kind.')
    with diagnostics.boundary(kind):
        path = selected.project_lock_path
        if kind != 'project_lock':
            path = path.with_name({'workflow_lock': '.workflow-lock',
                'discovery_lock': '.discovery-lock', 'sender_lock': '.sender-lock'}[kind])
    identity = (os.getpid(), str(path))
    owned = getattr(_local, 'owned', None)
    if owned is None:
        owned = _local.owned = {}
    if reentrant and identity in owned:
        yield
        return
    with diagnostics.boundary('storage_readiness'):
        selected.check_ready()
    with diagnostics.boundary(kind):
        # Import lazily: git_publish also uses this module at operation time.
        from harness.git_publish import open_lock
        selected.fs.create_directory(path.parent)
        handle = open_lock(selected, path)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            handle.close()
            raise
    owned[identity] = handle
    try:
        yield
    finally:
        owned.pop(identity, None)
        handle.close()


def bind_discovery_root(selected, root):
    """No automatic replay of a new artifact root's empty loop ledger.

Called under the stable discovery mutex before admission/publication. Its
inode contains ONLY a root hash, never a path/PID. Partial/corrupt/different
bindings fail closed; switching storage requires trusted offline reconciliation
of state/reservations/journals, never deletion based on a stale PID.
Legacy artifact locks are still acquired separately for old controllers.
"""
    path = selected.project_lock_path.with_name('.discovery-lock')
    identity = (os.getpid(), str(path))
    handle = getattr(_local, 'owned', {}).get(identity)
    if handle is None:
        raise ValueError('Discovery mutex is required for storage binding.')
    parent = selected.fs.open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        expected_info, actual_info = os.fstat(handle.fileno()), os.fstat(fd)
        if (expected_info.st_dev, expected_info.st_ino) != (actual_info.st_dev, actual_info.st_ino):
            raise ValueError('Discovery mutex attachment changed.')
        body = os.read(fd, 66)
    finally:
        os.close(fd)
    expected = hashlib.sha256(os.fsencode(root)).hexdigest().encode('ascii') + b'\n'
    if not body:
        with diagnostics.boundary('storage_readiness'):
            selected.check_ready()
        handle.write(expected.decode('ascii'))
        handle.flush()
        os.fsync(handle.fileno())
        directory = selected.fs.open_directory(path.parent)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    elif body != expected:
        raise ValueError('Discovery storage binding requires explicit reconciliation.')
