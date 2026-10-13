"""Trusted parent post-merge cleanup. No publication or credential discovery.

Callers hold the project lock before the journal lock and supply freshly checked
GitHub evidence. Git output is private to this module; failures expose only codes.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from harness import workspace

SHA = re.compile(r'^[a-f0-9]{40}$')
RUN = re.compile(r'^[0-9]+-[a-f0-9]{6}$')


class Pending(ValueError):
    """A bounded, credential-free reason suitable for the report."""


def durable_json(path, data):
    """Atomic private checkpoint, including directory durability after rename."""
    path = Path(path)
    if path.is_symlink():
        raise Pending('unsafe_checkpoint')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def enabled(report, cfg):
    return cfg.get('enabled') is True and not (
        report.get('read_only') or report.get('simulated') or report.get('no_git') or
        report.get('github_enabled') is False or not report.get('changed_files') or
        os.environ.get('TAVERN_WORKFLOW_CHILD') or os.environ.get('READ_ONLY') == '1' or
        os.environ.get('GIT') == '0')


class Git:
    """Argument-only transport with explicit timeouts and no interactive fallback."""
    def __init__(self, root):
        self.root = Path(root)

    def run(self, *args, allow=(0,), input=None, cwd=None):
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never',
                   GIT_OPTIONAL_LOCKS='0')
        try:
            result = subprocess.run(
                ['git', '-c', 'submodule.recurse=false', '-c', 'core.filemode=true',
                 '-c', 'remote.origin.mirror=false', '-c', 'push.followTags=false',
                 '-c', 'fetch.pruneTags=false', '-c', 'remote.origin.pruneTags=false', *args],
                cwd=str(cwd or self.root), env=env, input=input, shell=False,
                capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise Pending('git_timeout') from None
        except OSError:
            raise Pending('git_unavailable') from None
        if result.returncode not in allow:
            raise Pending('git_command_failed')
        return result.returncode, result.stdout

    def text(self, *args, **kwargs):
        return self.run(*args, **kwargs)[1].decode('utf-8').strip()

    def ancestor(self, old, new):
        return self.run('merge-base', '--is-ancestor', old, new, allow=(0, 1))[0] == 0

    def ref(self, ref):
        code, data = self.run('rev-parse', '--verify', '--quiet', ref, allow=(0, 1))
        if code == 1:
            return None
        value = data.decode('ascii').strip()
        if not SHA.fullmatch(value):
            raise Pending('invalid_ref_sha')
        return value

    def remote(self, ref):
        data = self.text('ls-remote', '--refs', 'origin', ref)
        if not data:
            return None
        rows = data.splitlines()
        if len(rows) != 1 or rows[0].split('\t')[1:] != [ref] or not SHA.fullmatch(rows[0].split('\t')[0]):
            raise Pending('ambiguous_remote_ref')
        return rows[0].split('\t')[0]


def validate_origin(git, repository):
    """Validate raw and effective fetch/push URLs, including Git URL rewrites."""
    allowed = {'https://github.com/' + repository, 'https://github.com/' + repository + '.git',
               'git@github.com:' + repository + '.git', 'ssh://git@github.com/' + repository + '.git'}
    raw = git.text('config', '--get-all', 'remote.origin.url').splitlines()
    push = git.text('config', '--get-all', 'remote.origin.pushurl', allow=(0, 1)).splitlines()
    fetch_effective = git.text('remote', 'get-url', '--all', 'origin').splitlines()
    push_effective = git.text('remote', 'get-url', '--push', '--all', 'origin').splitlines()
    if any(len(urls) != 1 or urls[0] not in allowed for urls in
           (raw, push or raw, fetch_effective, push_effective)):
        raise Pending('origin_transport_mismatch')


def identity(ledger):
    cfg = ledger['config']
    if not RUN.fullmatch(ledger['run_id']) or ledger['branch'] != 'codex/' + ledger['run_id'] or \
            ledger['branch'] in (cfg['base'], 'master', 'main', 'dev') or \
            not all(SHA.fullmatch(ledger.get(key, '')) for key in ('head_sha', 'merge_sha', 'base_sha')) or \
            not re.fullmatch(r'[A-Za-z0-9_./-]+', cfg['base']) or '..' in cfg['base'] or \
            cfg['base'].startswith(('/', '-')) or cfg['base'].endswith(('/', '.', '.lock')) or \
            '//' in cfg['base']:
        raise Pending('cleanup_identity_mismatch')


def worktree_path(value):
    """Decode Git's C-quoted path bytes; ambiguous old raw output fails closed."""
    if value.startswith(b'"'):
        if not value.endswith(b'"'):
            raise Pending('worktree_state_unknown')
        source, decoded, i = value[1:-1], bytearray(), 0
        escapes = {ord(a): ord(b) for a, b in zip('abtnvfr', '\a\b\t\n\v\f\r')}
        escapes.update({ord('\\'): ord('\\'), ord('"'): ord('"')})
        while i < len(source):
            byte = source[i]
            i += 1
            if byte == ord('\\'):
                if i == len(source):
                    raise Pending('worktree_state_unknown')
                if source[i] in escapes:
                    byte = escapes[source[i]]
                    i += 1
                elif re.fullmatch(rb'[0-3][0-7]{2}', source[i:i + 3]):
                    byte = int(source[i:i + 3], 8)
                    i += 3
                else:
                    raise Pending('worktree_state_unknown')
            elif byte == ord('"'):
                raise Pending('worktree_state_unknown')
            decoded.append(byte)
        value = bytes(decoded)
    if not value or b'\0' in value or not os.path.isabs(value):
        raise Pending('worktree_state_unknown')
    return os.fsdecode(value)


def worktrees(git):
    # -z is unavailable in Git 2.25. Old Git may emit raw paths: never infer a
    # path across lines or accept unrecognised/duplicate fields as another row.
    data = git.run('-c', 'core.quotePath=true', 'worktree', 'list', '--porcelain')[1]
    rows, item = [], {}
    for field in data.split(b'\n'):
        if not field:
            if item:
                rows.append(item)
                item = {}
        else:
            key, separator, value = field.partition(b' ')
            if key not in (b'worktree', b'HEAD', b'branch', b'detached', b'bare', b'locked', b'prunable'):
                raise Pending('worktree_state_unknown')
            key = key.decode('ascii')
            if key in item or (not item and key != 'worktree') or \
                    (key in ('worktree', 'HEAD', 'branch') and not separator):
                raise Pending('worktree_state_unknown')
            value = worktree_path(value) if key == 'worktree' else os.fsdecode(value)
            item[key] = value
    if item:
        rows.append(item)
    if not rows or any('worktree' not in row or 'bare' in row or 'prunable' in row or 'locked' in row or
                       not SHA.fullmatch(row.get('HEAD', '')) or
                       ('branch' in row) == ('detached' in row) or
                       (row.get('branch') and not row['branch'].startswith('refs/heads/'))
                       for row in rows) or len({row['worktree'] for row in rows}) != len(rows):
        raise Pending('worktree_state_unknown')
    return rows


def no_operations(git, rows):
    for row in rows:
        for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge',
                     'rebase-apply', 'sequencer', 'BISECT_START', 'index.lock'):
            value = git.text('rev-parse', '--git-path', name, cwd=row['worktree'])
            path = Path(value)
            if not path.is_absolute():
                path = Path(row['worktree']) / path
            if path.exists() or path.is_symlink():
                raise Pending('git_operation_in_progress')


def status(git, cwd=None):
    data = git.run('status', '--porcelain=v1', '-z', '--untracked-files=all',
                   '--ignore-submodules=none', cwd=cwd)[1].decode('utf-8')
    result = {}
    for row in data.split('\0'):
        if not row:
            continue
        if len(row) < 4 or row[2] != ' ' or row[:2] not in (' M', ' D', '??', ' T'):
            raise Pending('staged_or_conflicted_changes')
        result[row[3:]] = row[:2]
    return result


def tree_file(git, sha, name):
    rows = git.run('ls-tree', '-z', sha, '--', name)[1].split(b'\0')
    rows = [row for row in rows if row]
    if not rows:
        return None
    if len(rows) != 1:
        raise Pending('ambiguous_tree_file')
    info, path = rows[0].split(b'\t', 1)
    mode, kind, blob = info.decode('ascii').split(' ')
    if path.decode('utf-8') != name or kind != 'blob' or mode not in ('100644', '100755'):
        raise Pending('unsupported_tree_file')
    return {'sha': blob, 'mode': mode}


def same_entry(a, b):
    return a == ({key: b[key] for key in ('sha', 'mode')} if b else None)


def fingerprint(root, name, limit):
    return workspace.fingerprint(workspace.safe_path(root, name), limit)


def replace_bytes(path, content, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.cleanup-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        with open(temporary, 'rb') as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Cleanup:
    def __init__(self, root, directory, ledger, report, approval, *, transport=None,
                 origin_validator=validate_origin, storage_guard=None):
        # Injection is only a Python test seam, never a CLI/config option.
        self.root, self.directory = Path(root), Path(directory)
        self.ledger, self.report, self.approval = ledger, report, approval
        self.git = transport or Git(root)
        self.origin_validator = origin_validator
        # The journal controller supplies readiness/containment checks. Standalone
        # Python callers retain the existing API and durability/policy checks.
        self.storage_guard = storage_guard or (lambda: None)
        self.storage_guard()
        self.path = self.directory / 'cleanup.json'
        if self.path.exists():
            if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
                raise Pending('unsafe_checkpoint')
            self.state = json.loads(self.path.read_text(encoding='utf-8'))
            if self.state.get('run_id') != ledger['run_id'] or \
                    self.state.get('head_sha') != ledger.get('head_sha') or \
                    self.state.get('merge_sha') != ledger.get('merge_sha'):
                raise Pending('checkpoint_identity_mismatch')
        else:
            self.state = {'version': 'cleanup-v1', 'run_id': ledger['run_id'],
                          'head_sha': ledger.get('head_sha'), 'merge_sha': ledger.get('merge_sha'),
                          'remote': {}, 'prune': {}, 'sync': {}, 'local': {}, 'events': []}
        self.target = 'proof'

    def persist(self):
        # A mount check is not a lease: recheck after potentially slow Git reads.
        self.storage_guard()
        durable_json(self.path, self.state)

    def checkpoint(self, target, state, reason=None):
        self.state[target] = {'status': state, **({'reason': reason} if reason else {})}
        self.state['events'].append({'target': target, **self.state[target]})
        self.state['status'] = 'cleanup_pending'
        self.persist()

    def fetch(self, prune=False):
        self.origin_validator(self.git, self.ledger['config']['repository'])
        # Even an explicit fetch can update destinations from the configured
        # refmap. Validate before the first fetch, not only before pruning.
        self.prune_refspec()
        args = ['fetch', '--no-recurse-submodules', '--no-tags']
        if prune:
            args.append('--prune')
        # Explicit base destination avoids trusting a changed configured fetch refspec.
        base = self.ledger['config']['base']
        args += ['origin', 'refs/heads/' + base + ':refs/remotes/origin/' + base]
        self.git.run(*args)
        tip = self.git.ref('refs/remotes/origin/' + base)
        if not tip or not self.git.ancestor(self.ledger['merge_sha'], tip):
            raise Pending('merge_missing_from_base')
        return tip

    def prune_refspec(self):
        # remote prune must never interpret a locally rewritten fetch mapping as
        # permission to remove local branches, tags or another remote's refs.
        if self.git.text('config', '--get-all', 'remote.origin.fetch').splitlines() != [
                '+refs/heads/*:refs/remotes/origin/*']:
            self.target = 'prune'
            raise Pending('unsafe_prune_refspec')

    def collisions(self, old, new, allowed=()):
        """Protect ignored data as well as ordinary untracked paths before checkout.

        Git checkout/merge can overwrite ignored files. Compare unowned leaf paths
        and their parent/child relationships with paths introduced by the target.
        No recursive filesystem walk or content read of operating data is needed.
        """
        unowned = self.git.run('ls-files', '--others', '-z')[1].decode('utf-8').split('\0')
        changed = self.git.run('diff', '--name-only', '-z', '--no-renames',
                               '--diff-filter=ACDMT', old, new, '--')[1].decode('utf-8').split('\0')
        for name in filter(None, changed):
            if workspace.protected(name):
                raise Pending('protected_checkout_path')
            for other in filter(None, unowned):
                if other in allowed:
                    continue
                if other == name or other.startswith(name + '/') or name.startswith(other.rstrip('/') + '/'):
                    raise Pending('untracked_or_ignored_collision')
            path = self.root / name
            for parent in path.parents:
                if parent == self.root:
                    break
                if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                    raise Pending('checkout_parent_collision')

    def proof(self):
        identity(self.ledger)
        proof = self.ledger.get('cleanup_proof', {})
        if proof.get('head_sha') != self.ledger['head_sha'] or \
                proof.get('merge_sha') != self.ledger['merge_sha'] or proof.get('verified') is not True:
            raise Pending('github_proof_required')
        if not isinstance(proof.get('default_branch'), str) or not proof['default_branch']:
            raise Pending('github_default_branch_proof_required')
        if proof['default_branch'] == self.ledger['branch']:
            raise Pending('repository_default_branch')
        branch = proof.get('branch')
        if branch is not None and (branch.get('protected') is not False or
                                   branch.get('sha') != self.ledger['head_sha']):
            raise Pending('protected_or_advanced_remote_branch')
        if proof.get('open_prs') != []:
            raise Pending('branch_has_open_pr')

    def inspect(self, remote_base):
        rows = worktrees(self.git)
        no_operations(self.git, rows)
        branch, base = self.ledger['branch'], self.ledger['config']['base']
        if sum(Path(row['worktree']).resolve() == self.root.resolve() for row in rows) != 1:
            raise Pending('worktree_state_unknown')
        for row in rows:
            if Path(row['worktree']).resolve() != self.root.resolve():
                if row.get('branch') in ('refs/heads/' + branch, 'refs/heads/' + base):
                    raise Pending('branch_used_by_other_worktree')
                if status(self.git, cwd=row['worktree']):
                    raise Pending('other_worktree_dirty')
        current = self.git.text('symbolic-ref', '-q', 'HEAD', allow=(0, 1))
        if current not in ('refs/heads/' + base, 'refs/heads/' + branch):
            raise Pending('unapproved_checkout')
        local_base = self.git.ref('refs/heads/' + base)
        if not local_base or not self.git.ancestor(local_base, remote_base):
            raise Pending('base_diverged_or_local_only_commits')
        head = self.git.text('rev-parse', 'HEAD')
        if head != self.ledger['head_sha'] and not self.git.ancestor(head, remote_base):
            raise Pending('local_only_commits')
        task_tip = self.git.ref('refs/heads/' + branch)
        if task_tip is not None and task_tip != self.ledger['head_sha']:
            raise Pending('local_branch_advanced')
        return current, head

    def approved_changes(self, head, remote_base):
        changes = status(self.git)
        if not changes:
            return
        files, approval = self.ledger['files'], self.approval
        if set(changes) != set(files) or approval.get('run_id') != self.ledger['run_id'] or \
                approval.get('config') != self.ledger['config']:
            raise Pending('unapproved_worktree_changes')
        if not self.git.ancestor(head, self.ledger['base_sha']):
            raise Pending('baseline_head_mismatch')
        limit = approval['max_file_bytes']
        for name, entry in files.items():
            if workspace.protected(name):
                raise Pending('protected_file')
            item = approval['files'][name]
            for version in ('before', 'after'):
                fp, blob = item[version], entry[version]
                if (fp is None) != (blob is None):
                    raise Pending('approval_file_mismatch')
                if version == 'after' and fp:
                    content = self.git.run('cat-file', 'blob', blob['sha'])[1]
                    if hashlib.sha256(content).hexdigest() != fp['sha256']:
                        raise Pending('approval_file_mismatch')
            if fingerprint(self.root, name, limit) != item['after']:
                raise Pending('approved_file_changed')
            if not same_entry(tree_file(self.git, head, name), entry['before']):
                raise Pending('baseline_tree_mismatch')
            for sha in (self.ledger['merge_sha'], remote_base):
                if not same_entry(tree_file(self.git, sha, name), entry['after']):
                    raise Pending('remote_file_content_or_mode_changed')
            expected_status = '??' if entry['before'] is None else (' D' if entry['after'] is None else ' M')
            if changes[name] != expected_status:
                raise Pending('index_or_file_type_mismatch')
            # POSIX permissions are full fingerprints; Git stores only executable bits.
            for version in ('before', 'after'):
                fp, blob = item[version], entry[version]
                if (fp is None) != (blob is None) or (fp and
                        ('100755' if fp['mode'] & 0o111 else '100644') != blob['mode']):
                    raise Pending('approval_mode_mismatch')
                if version == 'before' and fp:
                    content = self.git.run('cat-file', 'blob', blob['sha'])[1]
                    if hashlib.sha256(content).hexdigest() != fp['sha256']:
                        raise Pending('baseline_fingerprint_mismatch')
        snapshots = self.directory / 'cleanup-backup'
        if snapshots.is_symlink():
            raise Pending('unsafe_backup')
        self.storage_guard()
        snapshots.mkdir(mode=0o700, exist_ok=True)
        if snapshots.stat().st_mode & 0o077:
            raise Pending('unsafe_backup')
        entries = {}
        for i, (name, entry) in enumerate(sorted(files.items())):
            item = approval['files'][name]
            if fingerprint(self.root, name, limit) != item['after']:
                raise Pending('approved_file_changed')
            if item['after']:
                self.storage_guard()
                replace_bytes(snapshots / str(i), workspace.safe_path(self.root, name).read_bytes(), 0o600)
            entries[name] = {'before': item['before'], 'after': item['after'], 'snapshot': str(i)}
        self.state['restore'] = {'head': head, 'phase': 'prepared', 'files': entries}
        self.persist()
        self.finish_restore(head)

    def finish_restore(self, head):
        """Resume per-file baseline restoration; never replace an unknown edit."""
        restore = self.state.get('restore')
        if not restore:
            return
        approved = self.approval['files']
        if set(restore['files']) != set(approved) or not SHA.fullmatch(restore['head']) or \
                any(item.get(version) != approved[name][version]
                    for name, item in restore['files'].items() for version in ('before', 'after')):
            raise Pending('restore_approval_mismatch')
        limit = self.approval['max_file_bytes']
        for name, item in restore['files'].items():
            if item['after']:
                snapshot = self.directory / 'cleanup-backup' / item['snapshot']
                if not re.fullmatch(r'[0-9]+', item['snapshot']) or snapshot.parent.is_symlink() or \
                        snapshot.is_symlink() or not snapshot.is_file() or snapshot.stat().st_mode & 0o077 or \
                        workspace.fingerprint(snapshot, limit)['sha256'] != item['after']['sha256']:
                    raise Pending('recovery_snapshot_invalid')
        if head != restore['head']:
            if restore['phase'] not in ('baseline', 'syncing', 'synced'):
                raise Pending('restore_head_changed')
            # A crash after ff-only may precede the final checkpoint.
            if not self.git.ancestor(self.ledger['merge_sha'], head):
                raise Pending('restore_head_changed')
            for name in restore['files']:
                entry = tree_file(self.git, head, name)
                current = fingerprint(self.root, name, limit)
                if current is None:
                    if entry is not None:
                        raise Pending('recovery_user_edit')
                elif not entry or hashlib.sha256(self.git.run('cat-file', 'blob', entry['sha'])[1]).hexdigest() != current['sha256'] or \
                        ('100755' if current['mode'] & 0o111 else '100644') != entry['mode']:
                    raise Pending('recovery_user_edit')
            restore['phase'] = 'synced'
            self.persist()
            return
        changes = status(self.git)
        if set(changes) - set(restore['files']):
            raise Pending('recovery_user_edit')
        for name, item in restore['files'].items():
            current = fingerprint(self.root, name, limit)
            if current == item['before']:
                continue
            if current != item['after']:
                raise Pending('recovery_user_edit')
            path = workspace.safe_path(self.root, name)
            before = self.ledger['files'][name]['before']
            if before is None:
                if path.exists():
                    if fingerprint(self.root, name, limit) != item['after']:
                        raise Pending('recovery_user_edit')
                    path.unlink()
                    directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            else:
                content = self.git.run('cat-file', 'blob', before['sha'])[1]
                # Check again after reading Git; external editors are not locked.
                if fingerprint(self.root, name, limit) != item['after']:
                    raise Pending('recovery_user_edit')
                replace_bytes(path, content, item['before']['mode'])
            self.persist()
        restore['phase'] = 'baseline'
        self.persist()

    def remote_cleanup(self):
        ref = 'refs/heads/' + self.ledger['branch']
        self.origin_validator(self.git, self.ledger['config']['repository'])
        tip = self.git.remote(ref)
        if tip is None:
            self.checkpoint('remote', 'absent')
            return
        if tip != self.ledger['head_sha']:
            raise Pending('remote_branch_advanced')
        if self.ledger['cleanup_proof'].get('branch') is None:
            raise Pending('remote_branch_reappeared')
        if self.state.get('remote_attempt') or self.state['remote'].get('status') in ('deleting', 'uncertain') or \
                self.state['remote'].get('reason') == 'remote_delete_unresolved_same_sha':
            raise Pending('remote_delete_unresolved_same_sha')
        self.state['remote_attempt'] = {'ref': ref, 'expected_sha': tip}
        self.checkpoint('remote', 'deleting')
        problem = None
        try:
            self.origin_validator(self.git, self.ledger['config']['repository'])
            rows = worktrees(self.git)
            no_operations(self.git, rows)
            if any(Path(row['worktree']).resolve() != self.root.resolve() and
                   row.get('branch') == ref for row in rows):
                raise Pending('branch_used_by_other_worktree')
            self.git.run('push', '--recurse-submodules=no',
                         '--force-with-lease=' + ref + ':' + tip, 'origin', ':' + ref)
        except Pending as exc:
            problem = str(exc)
        # Even a timeout or unsuccessful response must be reconciled by reading.
        self.checkpoint('remote', 'uncertain', problem)
        remaining = self.git.remote(ref)
        if remaining is not None:
            raise Pending('remote_branch_advanced' if remaining != tip else 'remote_delete_unresolved_same_sha')
        self.checkpoint('remote', 'deleted')

    def prune(self):
        self.fetch(prune=True)
        # Explicit refspec fetch cannot prune an unrelated tracking ref. Use the
        # configured remote's prune, then verify exactly the task ref is absent.
        self.origin_validator(self.git, self.ledger['config']['repository'])
        self.prune_refspec()
        if self.git.remote('refs/heads/' + self.ledger['branch']) is not None:
            raise Pending('remote_branch_reappeared')
        self.git.run('remote', 'prune', 'origin')
        ref = 'refs/remotes/origin/' + self.ledger['branch']
        tip = self.git.ref(ref)
        if tip is not None:
            raise Pending('tracking_ref_remains')
        self.checkpoint('prune', 'complete')

    def local_cleanup(self, remote_base):
        current, head = self.inspect(remote_base)
        changes = status(self.git)
        allowed = [name for name, entry in self.ledger['files'].items()
                   if entry['before'] is None and entry['after'] is not None and
                   changes.get(name) == '??' and fingerprint(self.root, name, self.approval['max_file_bytes']) ==
                   self.approval['files'][name]['after']]
        # Run before preparing/temporarily restoring any approved file.
        self.collisions(head, remote_base, allowed)
        if self.state.get('restore'):
            if head == self.state['restore']['head']:
                # A later fetch may differ from the base checked before a crash.
                # Keep the snapshots and remaining approved bytes until revalidated.
                for name, entry in self.ledger['files'].items():
                    if not same_entry(tree_file(self.git, head, name), entry['before']):
                        raise Pending('baseline_tree_mismatch')
                    for sha in (self.ledger['merge_sha'], remote_base):
                        if not same_entry(tree_file(self.git, sha, name), entry['after']):
                            raise Pending('remote_file_content_or_mode_changed')
            self.finish_restore(head)
        else:
            self.approved_changes(head, remote_base)
        if status(self.git):
            raise Pending('worktree_not_clean')
        base = self.ledger['config']['base']
        if current != 'refs/heads/' + base:
            self.inspect(remote_base)
            self.collisions(head, self.git.ref('refs/heads/' + base))
            if status(self.git):
                raise Pending('worktree_changed_before_switch')
            self.checkpoint('sync', 'switching')
            self.git.run('switch', '--no-recurse-submodules', base)
        self.checkpoint('sync', 'fetching')
        remote_base = self.fetch(prune=True)
        self.inspect(remote_base)
        if self.state.get('restore') and self.state['restore']['phase'] != 'synced':
            for name, entry in self.ledger['files'].items():
                if not same_entry(tree_file(self.git, remote_base, name), entry['after']):
                    raise Pending('remote_file_content_or_mode_changed')
        self.collisions(self.git.ref('HEAD'), remote_base)
        if status(self.git):
            raise Pending('worktree_changed_before_sync')
        if self.state.get('restore'):
            self.state['restore']['phase'] = 'syncing'
        self.checkpoint('sync', 'synchronizing')
        self.git.run('merge', '--ff-only', '--no-edit', remote_base)
        if self.git.text('rev-parse', 'HEAD') != remote_base or status(self.git):
            raise Pending('sync_incomplete')
        if self.state.get('restore'):
            self.state['restore']['phase'] = 'synced'
        self.checkpoint('sync', 'complete')
        self.target = 'local'
        ref = 'refs/heads/' + self.ledger['branch']
        tip = self.git.ref(ref)
        if tip is None:
            self.checkpoint('local', 'absent')
            return
        self.inspect(remote_base)
        if tip != self.ledger['head_sha']:
            raise Pending('local_branch_advanced')
        # Both ordinary and squash deletion use the same compare-and-delete.
        # branch -d cannot make its tip check atomic; update-ref with old SHA can.
        self.proof()
        if not self.git.ancestor(self.ledger['merge_sha'], remote_base):
            raise Pending('merge_missing_from_base')
        self.checkpoint('local', 'deleting')
        self.git.run('update-ref', '-d', ref, tip)
        if self.git.ref(ref) is not None:
            raise Pending('local_ref_remains')
        self.checkpoint('local', 'deleted')

    def complete(self):
        # A branch can be recreated after deletion or another process can switch
        # HEAD. Completion checks actual state once more; locks do not stop editors.
        self.target = 'completion'
        base = self.fetch(prune=True)
        self.inspect(base)
        if self.git.text('symbolic-ref', '-q', 'HEAD', allow=(0, 1)) != \
                'refs/heads/' + self.ledger['config']['base'] or self.git.ref('HEAD') != base or status(self.git):
            raise Pending('checkout_changed_before_completion')
        if self.git.remote('refs/heads/' + self.ledger['branch']) is not None or \
                self.git.ref('refs/remotes/origin/' + self.ledger['branch']) is not None or \
                self.git.ref('refs/heads/' + self.ledger['branch']) is not None:
            raise Pending('ref_reappeared_before_completion')
        self.checkpoint('completion', 'complete')

    def run(self):
        if not enabled(self.report, self.ledger['config']):
            self.checkpoint('proof', 'pending', 'cleanup_side_effects_disabled')
            return self.state
        try:
            self.proof()
            self.target = 'fetch'
            remote_base = self.fetch()
            # Remote deletion is independent of user file changes, but never
            # deletes a branch checked out by another worktree.
            self.target = 'remote'
            rows = worktrees(self.git)
            no_operations(self.git, rows)
            if any(Path(row['worktree']).resolve() != self.root.resolve() and
                   row.get('branch') == 'refs/heads/' + self.ledger['branch'] for row in rows):
                raise Pending('branch_used_by_other_worktree')
            self.remote_cleanup()
            self.target = 'prune'
            self.prune()
            self.target = 'sync'
            self.local_cleanup(remote_base)
            self.complete()
            self.state['status'] = 'complete'
            self.persist()
        except (Pending, OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
            # Only Pending strings originate from our fixed reason codes.
            self.checkpoint(self.target, 'pending', str(exc) if isinstance(exc, Pending) else 'cleanup_state_invalid')
        return self.state


def execute(root, directory, ledger, report, approval, *, storage_guard=None):
    return Cleanup(root, directory, ledger, report, approval, storage_guard=storage_guard).run()
