"""Copy development sources and publish only validated, conflict-free scoped edits."""
import difflib
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from harness import triage

REGIONS = ('itos', 'ktos', 'ktest', 'jtos', 'twtos')
GENERATED = ('.git', 'logs', '__pycache__', '.pytest_cache')
PLUGIN_TYPES = 'harness/compaction/.claude-plugin/types'


def protected(name):
    parts = Path(name).parts
    if not parts or '..' in parts or Path(name).is_absolute():
        return True
    return (bool(triage.path_rules([name])['protected_paths']) or
            name == PLUGIN_TYPES or name.startswith(PLUGIN_TYPES + '/') or
            parts[0] in ('backups', '.agents', '.aws', '.zcode') or
            any(part in ('node_modules', '.venv', '__pycache__', 'logs') for part in parts) or
            any(part.startswith('.env') for part in parts) or
            (Path(name).suffix.lower() == '.ini' and name != 'harness/pytest.ini') or
            Path(name).suffix.lower() in ('.pem', '.key', '.p12', '.pyc', '.pyo') or
            (len(parts) > 1 and parts[0] == 'TavernofSoul' and parts[1] in REGIONS))


def safe_path(root, name):
    root = Path(root).resolve()
    path = root / name
    if not name or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Invalid workspace path.')
    for candidate in [path] + list(path.parents):
        if candidate == root:
            break
        if candidate.is_symlink():
            raise ValueError('Symlinks are outside the workflow scope: ' + name)
    if path.exists() and not path.is_file():
        raise ValueError('Scope entries must be individual files: ' + name)
    return path


def fingerprint(path, limit):
    if path.is_symlink():
        raise ValueError('Workspace contains a symlink.')
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Workspace file is invalid or too large.')
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'mode': stat.S_IMODE(path.stat().st_mode)}


def source_names(root):
    result = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                            cwd=str(root), capture_output=True, check=True)
    names = sorted(set(result.stdout.decode('utf-8').split('\0')) - {''})
    return [name for name in names if not protected(name)]


def copy_sources(root, destination, scope, policy):
    """Create model context from exact approved files, without discovering others."""
    names = sorted(set(scope))
    if any(protected(name) for name in names):
        raise ValueError('Protected files cannot be copied into model context.')
    return _copy_files(root, destination, names, policy)


def copy_validation_sources(root, destination, scope, policy):
    """Create a complete LOCAL verification snapshot; never give it to a model."""
    names = sorted(set(source_names(root)) | set(scope))
    return _copy_files(root, destination, names, policy)


def _copy_files(root, destination, names, policy):
    baseline, total = {}, 0
    destination.mkdir(parents=True, exist_ok=False)
    for name in names:
        path = safe_path(root, name)
        item = fingerprint(path, policy['max_file_bytes'])
        if item is None:
            continue  # Deleted tracked files stay deleted, including pre-existing user changes.
        total += path.stat().st_size
        if total > policy['max_snapshot_bytes']:
            raise ValueError('Source snapshot exceeds its configured limit.')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(path), str(target))
        if fingerprint(target, policy['max_file_bytes']) != item or \
                fingerprint(path, policy['max_file_bytes']) != item:
            raise ValueError('Source changed while creating the workspace: ' + name)
        baseline[name] = item
    # No source repository metadata, history or credential files are copied.
    # A disposable empty repository lets existing Git ignore regression checks run.
    # Host Git templates must not introduce unapproved files into model context.
    subprocess.run(['git', 'init', '--template=', '-q', str(destination)], check=True, capture_output=True)
    return baseline


def sync_scope(source, destination, baseline, scope, policy, read_only=False):
    """Move only approved model edits into the local validation snapshot."""
    current = manifest(source, policy)
    enforce_scope(baseline, current, scope, read_only=read_only)
    # Synchronize against the destination, including reversions to the original
    # content in a repair round and removal of newly created files.
    changes = [name for name in scope if
               fingerprint(safe_path(destination, name), policy['max_file_bytes']) != current.get(name)]
    for name in changes:
        target = safe_path(destination, name)
        if current.get(name) is None:
            if target.exists():
                target.unlink()
        else:
            replace_file(safe_path(source, name), target, current[name]['mode'])
    return changes


def manifest(root, policy):
    result = {}
    total = 0
    for directory, dirs, files in os.walk(str(root), followlinks=False):
        dirs[:] = [name for name in dirs if name not in GENERATED]
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError('Workspace contains a directory symlink.')
        dirs[:] = [name for name in dirs if
                   (Path(directory) / name).relative_to(root).as_posix() != PLUGIN_TYPES]
        for name in files:
            path = Path(directory) / name
            item = fingerprint(path, policy['max_file_bytes'])
            total += path.stat().st_size
            if total > policy['max_snapshot_bytes']:
                raise ValueError('Workspace exceeds its configured limit.')
            result[path.relative_to(root).as_posix()] = item
    return result


def changed(before, after):
    return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))


def enforce_scope(before, after, scope, read_only=False):
    changes = changed(before, after)
    if (read_only and changes) or set(changes) - set(scope) or any(protected(name) for name in changes):
        raise ValueError('Agent changed files outside its assigned scope: ' + ', '.join(changes))
    return changes


def diff_text(original, candidate, changes, limit):
    chunks = []
    for name in changes:
        a, b = safe_path(original, name), safe_path(candidate, name)
        try:
            before = a.read_text(encoding='utf-8').splitlines(keepends=True) if a.exists() else []
            after = b.read_text(encoding='utf-8').splitlines(keepends=True) if b.exists() else []
        except UnicodeError:
            raise ValueError('Automatic publication supports UTF-8 source edits only: ' + name) from None
        chunks.append(''.join(difflib.unified_diff(before, after, 'a/' + name, 'b/' + name)))
        if sum(len(chunk.encode('utf-8')) for chunk in chunks) > limit:
            raise ValueError('Review diff exceeds its limit; it is never truncated.')
    return '\n'.join(chunks)


def replace_file(source, target, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix='.workflow-', dir=str(target.parent))
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(source.read_bytes())
        os.chmod(filename, mode)
        os.replace(filename, str(target))
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def publish(root, candidate, baseline, validated, changes, scope, backup, policy):
    enforce_scope(baseline, validated, scope)
    if manifest(candidate, policy) != validated:
        raise ValueError('Candidate changed after validation.')
    # Compare every copied source, plus newly introduced names. Other editors and
    # workflows cannot silently replace the inputs that were reviewed and tested.
    current_names = set(source_names(root)) | set(scope)
    current = {name: fingerprint(safe_path(root, name), policy['max_file_bytes']) for name in current_names}
    current = {name: item for name, item in current.items() if item is not None}
    if current != baseline:
        raise ValueError('Original sources changed during the workflow; publication stopped.')
    backup.mkdir(parents=True, exist_ok=True)
    for name in changes:
        if baseline.get(name) is not None:
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(safe_path(root, name)), str(target))
    applied = []
    try:
        for name in changes:
            target = safe_path(root, name)
            if fingerprint(target, policy['max_file_bytes']) != baseline.get(name):
                raise ValueError('File changed during publication: ' + name)
            if validated.get(name) is None:
                target.unlink()
            else:
                replace_file(safe_path(candidate, name), target, validated[name]['mode'])
            applied.append(name)
    except (OSError, ValueError):
        for name in reversed(applied):
            target = safe_path(root, name)
            # Preserve an external edit that arrived after our file replacement.
            if fingerprint(target, policy['max_file_bytes']) != validated.get(name):
                continue
            if baseline.get(name) is None:
                target.unlink()
            else:
                replace_file(backup / name, target, baseline[name]['mode'])
        raise
    return applied
