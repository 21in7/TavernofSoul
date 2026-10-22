"""Private, sealed round inputs. Two fixed banks, no archive or directory scan.

Only approved UTF-8 source bytes and original mode/existence are persisted.
The state pointer binds an atomic manifest; incomplete inactive banks are never
read. Each payload is a separate bounded Store record (not a model context).
Store uses fixed per-record staging names here, so repeated power loss cannot
accumulate random temporary source files. Unsafe staging is never retired.
Callers hold the improvement state lock; live capture separately holds the
historical source lock. Sealed bank reads need no live source lock.
Same-uid malicious writers are outside the
Store trust boundary; hashes detect corruption, not an attacker rewriting state.
"""

import base64
import os
import stat

from harness import improvement_report as contract, improvements as imp
from harness import improvement_diagnostics as diagnostics


VERSION = 'improvement-snapshot-v1'
MAX_FILES = 37
BANKS = ('a', 'b')


class SnapshotError(imp.ImprovementError):
    """Fixed private diagnostic; never embed paths or payloads."""


def _directory(store, bank, create=False):
    if bank not in BANKS:
        raise SnapshotError('snapshot_invalid')
    name = 'loop/snapshots/' + bank
    if create:
        store.policy.ensure_directory(store.path(name))
    # open_directory pins every ancestor without following links. Verify all
    # owned private components, including existing directories, without chmod.
    for part in ('', 'loop', 'loop/snapshots', name):
        fd = store.policy.fs.open_directory(store.path(part))
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise SnapshotError('snapshot_permissions')
        finally:
            os.close(fd)
    return name


def _limits(paths, sources, limits):
    contract.validate_scope_paths(paths, MAX_FILES)
    if set(paths) != set(sources):
        raise SnapshotError('snapshot_invalid')
    fingerprints = contract.fingerprint_sources(sources)
    if (any(item['size'] > limits['max_file_bytes'] for item in fingerprints.values()) or
            sum(item['size'] for item in fingerprints.values()) > limits['max_source_bytes']):
        raise SnapshotError('snapshot_size')
    for item in sources.values():
        if item['exists']:
            item['content'].decode('utf-8', 'strict')
    return fingerprints


@diagnostics.at('seal')
def publish(store, scan_id, paths, sources, limits, previous=None):
    """Write inactive bank, manifest last, then return a state-bound pointer.

    Never overwrite the active bank. Crash before state publication leaves at
    most one inactive bank; its exact 37 record names are replaced/removed on
    the next publication. Old scans retain fingerprints, never source payload.
    """
    try:
        if not isinstance(scan_id, str) or not imp.storage.RUN_ID.fullmatch(scan_id):
            raise SnapshotError('snapshot_invalid')
        fingerprints = _limits(paths, sources, limits)
        bank = 'b' if previous and previous.get('bank') == 'a' else 'a'
        prefix = _directory(store, bank, create=True)
        for index, path in enumerate(paths):
            item = sources[path]
            store.write(prefix + '/{}.json'.format(index), {
                'path': path, 'exists': item['exists'], 'mode': item['mode'],
                'content': (base64.b64encode(item['content']).decode('ascii')
                            if item['exists'] else None)})
        # Bounded cleanup only, no discovery of files or recursive deletion.
        parent = store.policy.fs.open_directory(store.path(prefix))
        try:
            for index in range(len(paths), MAX_FILES):
                store.policy.check_ready()
                try:
                    os.unlink('{}.json'.format(index), dir_fd=parent)
                except FileNotFoundError:
                    pass
            os.fsync(parent)
        finally:
            os.close(parent)
        manifest = {'version': VERSION, 'scan_id': scan_id, 'paths': list(paths),
                    'fingerprints': fingerprints}
        store.write(prefix + '/manifest.json', manifest)
        seal = {'bank': bank, 'scan_id': scan_id, 'digest': contract.digest(manifest)}
        # Read back via the same fail-closed boundary used after restart.
        load(store, seal, paths, fingerprints, limits)
        return seal
    except SnapshotError:
        raise
    except Exception:
        raise SnapshotError('snapshot_unavailable') from None


@diagnostics.at('seal')
def load(store, seal, paths, fingerprints, limits):
    try:
        if (not isinstance(seal, dict) or set(seal) != {'bank', 'scan_id', 'digest'} or
                not imp.storage.RUN_ID.fullmatch(seal['scan_id'])):
            raise SnapshotError('snapshot_invalid')
        prefix = _directory(store, seal['bank'])
        manifest = store.read(prefix + '/manifest.json')
        if (manifest != {'version': VERSION, 'scan_id': seal['scan_id'],
                         'paths': list(paths), 'fingerprints': fingerprints} or
                contract.digest(manifest) != seal['digest']):
            raise SnapshotError('snapshot_manifest_changed')
        sources = {}
        contract.validate_scope_paths(paths, MAX_FILES)
        for index, path in enumerate(paths):
            record = store.read(prefix + '/{}.json'.format(index))
            if (not isinstance(record, dict) or
                    set(record) != {'path', 'exists', 'mode', 'content'} or record['path'] != path or
                    type(record['exists']) is not bool):
                raise SnapshotError('snapshot_invalid')
            content = record['content']
            if record['exists']:
                if (not isinstance(content, str) or
                        len(content) > 4 * ((limits['max_file_bytes'] + 2) // 3)):
                    raise SnapshotError('snapshot_size')
                content = base64.b64decode(content, validate=True)
            elif content is not None:
                raise SnapshotError('snapshot_invalid')
            sources[path] = {'exists': record['exists'], 'mode': record['mode'], 'content': content}
        if _limits(paths, sources, limits) != fingerprints:
            raise SnapshotError('snapshot_sources_changed')
        return sources
    except SnapshotError:
        raise
    except Exception:
        raise SnapshotError('snapshot_unavailable') from None
