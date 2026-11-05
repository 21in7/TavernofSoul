"""Offline fixtures only. The orchestrator runs these tests, never the worker.

The cleanup repo fixture performs remote Git simulation and reads production
publication config. Park deliberately uses its own smaller, network-free repo;
the synthetic storage boundary follows test_git_cleanup.isolated_storage.
"""
import copy
import fcntl
import json
import os
import stat
import subprocess

import pytest

from harness import git_cleanup, git_publish as native, storage, workspace
from harness import worktree_park as parking


@pytest.fixture(autouse=True)
def isolated_parent_context(monkeypatch):
    # The test runner may itself be a workflow child. Model only the trusted
    # parent here; rejection tests explicitly set each forbidden context below.
    for key in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                'TAVERN_IMPROVEMENT_UNATTENDED', 'READ_ONLY', 'GIT'):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def parked_repo(tmp_path, monkeypatch):
    monkeypatch.delenv(storage.CONFIG_ENV, raising=False)
    monkeypatch.delenv(storage.REPORT_ENV, raising=False)
    for key in list(os.environ):
        if key.startswith(('GIT_', 'SSH_', 'GCM_', 'TAVERN_')) or key in (
                'READ_ONLY', 'GIT', 'GH_TOKEN', 'GITHUB_TOKEN', 'GITHUB_API_KEY', 'EMAIL'):
            monkeypatch.delenv(key, raising=False)
    home, hooks, root = (tmp_path / name for name in ('private-home', 'empty-hooks', 'source'))
    for path in (home, hooks, root):
        path.mkdir(mode=0o700)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home))
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', '')
    monkeypatch.setenv('GIT_TERMINAL_PROMPT', '0')
    monkeypatch.setenv('GIT_AUTHOR_NAME', 'Park Fixture')
    monkeypatch.setenv('GIT_AUTHOR_EMAIL', 'park@example.invalid')
    monkeypatch.setenv('GIT_COMMITTER_NAME', 'Park Fixture')
    monkeypatch.setenv('GIT_COMMITTER_EMAIL', 'park@example.invalid')

    def git(*args):
        proc = subprocess.run(['git', '-c', 'core.hooksPath=' + str(hooks),
                               '-c', 'commit.gpgSign=false', '-c', 'tag.gpgSign=false', *args],
                              cwd=str(root), capture_output=True, timeout=15, shell=False)
        assert proc.returncode == 0, 'Offline fixture Git failed'
        return proc.stdout.decode('utf-8').strip()

    git('init', '--template=', '-q')
    git('symbolic-ref', 'HEAD', 'refs/heads/master')
    git('config', 'core.hooksPath', str(hooks))
    git('remote', 'add', 'origin', 'https://github.com/example/fixture.git')
    originals = {'edit.txt': b'before\n', 'delete.txt': b'delete me\n',
                 'mode.txt': b'executable\n', 'other.txt': b'unchanged\n',
                 '.gitignore': b'/logs/\n'}
    for name, raw in originals.items():
        (root / name).write_bytes(raw)
        (root / name).chmod(0o644)
    git('add', '--', *sorted(originals))
    git('commit', '-m', 'isolated baseline')
    head = git('rev-parse', 'HEAD')
    run_id = '123456-abcdef'
    directory = root / 'logs/harness/workflows' / run_id
    directory.mkdir(parents=True, mode=0o700)
    candidate = directory / 'workspace'
    candidate.mkdir(mode=0o700)
    scope = ['edit.txt', 'delete.txt', 'mode.txt', 'nested/add.txt']
    policy = {'max_file_bytes': 4096, 'max_snapshot_bytes': 65536}
    baseline = {}
    # Native publish compares the entire source baseline, including unchanged
    # tracked files; only `changes` is limited to the approved edit scope.
    for name in sorted(set(originals) | set(scope)):
        fp = workspace.fingerprint(root / name, 4096)
        if fp is not None:
            baseline[name] = fp
            (candidate / name).write_bytes((root / name).read_bytes())
            (candidate / name).chmod(fp['mode'])
    (candidate / 'edit.txt').write_bytes(b'approved after\n')
    (candidate / 'edit.txt').chmod(0o640)
    (candidate / 'delete.txt').unlink()
    (candidate / 'mode.txt').chmod(0o755)
    (candidate / 'nested').mkdir()
    (candidate / 'nested/add.txt').write_text('approved Unicode: 한글\n', encoding='utf-8')
    (candidate / 'nested/add.txt').chmod(0o644)
    validated = workspace.manifest(candidate, policy)
    changes = workspace.changed(baseline, validated)
    workspace.publish(root, candidate, baseline, validated, changes, scope,
                      directory / 'backup', policy)

    class FixtureFS(storage.FileSystem):
        def read_bytes(self, path):
            pytest.fail('Park fixture attempted private storage config read')

        def probe(self, path):
            pytest.fail('Park fixture attempted storage probe')

        def free_bytes(self, path):
            pytest.fail('Park fixture attempted mount query')

    selected = storage.resolve_storage(root, env={}, fs=FixtureFS())
    monkeypatch.setattr(storage, 'resolve_storage', lambda *args, **kw: selected)
    monkeypatch.setattr(native, 'ROOT', root)
    monkeypatch.setattr(native, 'REPORTS', directory.parent)
    monkeypatch.setattr(native, 'storage_policy', lambda: selected)
    cfg = {'version': 'github-v1', 'enabled': True, 'repository': 'example/fixture',
           'base': 'master', 'merge_method': 'squash', 'required_checks': sorted(native.REQUIRED),
           'check_app': 'github-actions', 'wait_seconds': 60}
    monkeypatch.setattr(native, 'load_config', lambda: cfg)
    report = {'run_id': run_id, 'scope': scope, 'changed_files': changes, 'applied': changes,
              'workspace': str(candidate), 'status': 'awaiting_github',
              'review': {'verdict': 'approved'}, 'validation': [{
                  'command': 'check', 'status': 'passed', 'exit_code': 0,
                  'checks': {'offline': {'status': 'passed', 'selected': 1, 'passed': 1,
                                         'skipped': [], 'errors': [], 'failures': []}}}]}
    git_cleanup.durable_json(directory / 'report.json', report)
    native.prepare(root, directory, report, baseline, validated, changes, policy,
                   {'commit_message': 'fixture', 'pr_title': 'fixture', 'pr_body': 'fixture'})
    ledger = json.loads((directory / 'github.json').read_text())
    ledger['base_sha'] = head
    git_cleanup.durable_json(directory / 'github.json', ledger)
    approval = json.loads((directory / 'github-approved.json').read_text())

    def run():
        return parking.park(run_id)

    return locals()


def source_image(repo):
    """Include full POSIX mode, bytes and index; ignored operational data too."""
    root = repo['root']
    names = set(repo['scope']) | {'other.txt', '.gitignore'}
    result = {}
    for name in names:
        path = root / name
        result[name] = ((path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                        if path.is_file() else None)
    result['index'] = (root / '.git/index').read_bytes()
    return result


def evidence(repo):
    return {name: (repo['directory'] / name).read_bytes()
            for name in ('github.json', 'github-approved.json', 'report.json')}


def test_edit_add_delete_mode_and_readonly_reinvocation(parked_repo):
    repo = parked_repo
    native_before = evidence(repo)
    index_before = (repo['root'] / '.git/index').read_bytes()
    operational = repo['root'] / 'logs/operating-data'
    operational.write_bytes(b'leave ignored data alone')
    result = repo['run']()
    assert result['status'] == 'parked', result
    assert result['code'] == 'parked' and result['executed'] is True
    assert set(result['side_effects']['restored_files']) == set(repo['scope'])
    assert (repo['root'] / '.git/index').read_bytes() == index_before
    assert repo['git']('status', '--porcelain') == ''
    assert repo['git']('rev-parse', 'HEAD') == repo['head']
    assert evidence(repo) == native_before
    assert operational.read_bytes() == b'leave ignored data alone'
    for name, entry in repo['approval']['files'].items():
        assert workspace.fingerprint(repo['root'] / name, 4096) == entry['before']
    snapshots = repo['directory'] / parking.SNAPSHOTS
    for i, name in enumerate(sorted(repo['scope'])):
        item = repo['approval']['files'][name]['after']
        if item:
            fp = workspace.fingerprint(snapshots / str(i), 4096)
            assert fp == {'sha256': item['sha256'], 'mode': 0o600}
    parked_state = (repo['directory'] / parking.STATE).read_bytes()
    again = repo['run']()
    assert again['code'] == 'already_parked' and again['executed'] is False
    assert not any(again['side_effects'].values())
    assert (repo['directory'] / parking.STATE).read_bytes() == parked_state


@pytest.mark.parametrize('kind', ['tracked', 'untracked', 'staged', 'same_file', 'after_mode'])
def test_user_changes_reject_entire_operation_before_snapshot(parked_repo, kind):
    repo = parked_repo
    if kind == 'tracked':
        (repo['root'] / 'other.txt').write_text('user change')
    elif kind == 'untracked':
        (repo['root'] / 'user-file').write_text('preserve untracked')
    elif kind == 'staged':
        repo['git']('add', '--', 'edit.txt')
    elif kind == 'same_file':
        (repo['root'] / 'edit.txt').write_text('user edit of approved file')
    else:
        (repo['root'] / 'edit.txt').chmod(0o644)
    before, records = source_image(repo), evidence(repo)
    result = repo['run']()
    assert result['status'] == 'needs_reconciliation', result
    assert result['executed'] is False
    assert source_image(repo) == before and evidence(repo) == records
    assert not (repo['directory'] / parking.SNAPSHOTS).exists()
    assert result['next_action']['action'] == 'stop'
    if kind == 'untracked':
        assert (repo['root'] / 'user-file').read_text() == 'preserve untracked'


@pytest.mark.parametrize('kind', ['review', 'checks', 'applied', 'scope', 'before_mode', 'after_mode', 'head'])
def test_all_approval_gates_precede_every_source_write(parked_repo, kind):
    repo = parked_repo
    directory = repo['directory']
    if kind in ('review', 'checks', 'applied', 'scope'):
        report = copy.deepcopy(repo['report'])
        if kind == 'review':
            report['review']['verdict'] = 'changes_requested'
        elif kind == 'checks':
            report['validation'][0]['checks']['offline']['passed'] = 0
        elif kind == 'applied':
            report['applied'] = []
        else:
            report['scope'] = ['other.txt']
        git_cleanup.durable_json(directory / 'report.json', report)
    elif kind == 'head':
        journal = copy.deepcopy(repo['ledger'])
        journal['base_sha'] = 'a' * 40
        git_cleanup.durable_json(directory / 'github.json', journal)
    else:
        # Non-executable mode difference must be caught, not only Git's x bit.
        folder = 'backup' if kind == 'before_mode' else 'workspace'
        (directory / folder / 'edit.txt').chmod(0o600)
    before = source_image(repo)
    result = repo['run']()
    assert result['status'] == 'needs_reconciliation', result
    assert not result['executed'] and source_image(repo) == before
    assert not (directory / parking.SNAPSHOTS).exists()


def test_missing_locks_created_and_existing_inode_mode_preserved(parked_repo):
    repo = parked_repo
    locks = [repo['selected'].project_lock_path, repo['directory'] / 'github.lock']
    assert not any(path.exists() for path in locks)
    assert set(repo['run']()['side_effects']['created_locks']) == {'.lock', 'github.lock'}
    identities = {}
    for path in locks:
        path.chmod(0o640)
        info = path.stat()
        identities[path] = (info.st_dev, info.st_ino, info.st_mode)
    result = repo['run']()
    assert result['code'] == 'already_parked', result
    for path in locks:
        info = path.stat()
        assert (info.st_dev, info.st_ino, info.st_mode) == identities[path]


@pytest.mark.parametrize('which', ['project', 'github'])
@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'directory', 'busy'])
def test_unsafe_and_busy_lock_preserves_source_and_lock(parked_repo, which, kind):
    repo = parked_repo
    lock = repo['selected'].project_lock_path if which == 'project' else repo['directory'] / 'github.lock'
    target = repo['directory'] / 'preserved-lock-target'
    target.write_bytes(b'lock target')
    target.chmod(0o640)
    handle = None
    if kind == 'symlink':
        lock.symlink_to(target)
    elif kind == 'hardlink':
        os.link(str(target), str(lock))
    elif kind == 'directory':
        lock.mkdir()
    else:
        handle = lock.open('w')
        lock.chmod(0o640)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    info, before = lock.lstat(), source_image(repo)
    try:
        result = repo['run']()
    finally:
        if handle:
            handle.close()
    assert result['status'] == 'needs_reconciliation', result
    assert not result['executed'] and source_image(repo) == before
    after = lock.lstat()
    assert (info.st_ino, info.st_mode, info.st_nlink) == (after.st_ino, after.st_mode, after.st_nlink)
    assert target.read_bytes() == b'lock target' and stat.S_IMODE(target.stat().st_mode) == 0o640


def test_foreign_owned_lock_fake_rejected_without_chmod(parked_repo, monkeypatch):
    repo = parked_repo
    lock = repo['directory'] / 'github.lock'
    lock.write_bytes(b'keep inode')
    lock.chmod(0o640)
    original, inode = parking.os.fstat, lock.stat().st_ino

    def foreign(fd):
        info = original(fd)
        if info.st_ino == inode:
            values = list(info)
            values[4] = os.geteuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(parking.os, 'fstat', foreign)
    before = source_image(repo)
    result = repo['run']()
    assert result['code'] == 'unsafe_file'
    assert source_image(repo) == before
    assert lock.stat().st_ino == inode and stat.S_IMODE(lock.stat().st_mode) == 0o640


def test_existing_snapshot_collision_is_never_overwritten(parked_repo):
    repo = parked_repo
    path = repo['directory'] / parking.SNAPSHOTS
    path.mkdir(mode=0o700)
    (path / '0').write_bytes(b'prior evidence')
    before = source_image(repo)
    result = repo['run']()
    assert result['code'] == 'snapshot_conflict', result
    assert source_image(repo) == before and (path / '0').read_bytes() == b'prior evidence'


def test_source_race_while_snapshotting_stops_before_any_restore(parked_repo, monkeypatch):
    repo = parked_repo
    write_snapshot = parking._Park.write_snapshot

    def change_source(self, path, raw):
        write_snapshot(self, path, raw)
        (repo['root'] / 'other.txt').write_bytes(b'concurrent user edit')

    monkeypatch.setattr(parking._Park, 'write_snapshot', change_source)
    before = source_image(repo)
    result = repo['run']()
    assert result['status'] == 'needs_reconciliation' and not result['executed']
    after = source_image(repo)
    assert after['other.txt'][0] == b'concurrent user edit'
    for name in repo['scope']:
        assert after[name] == before[name]
    assert (repo['directory'] / parking.STATE).is_file()
    assert repo['run']()['code'] == 'interrupted_park_requires_reconciliation'


def test_lock_replacement_during_snapshot_never_reaches_source_restore(parked_repo, monkeypatch):
    repo = parked_repo
    write_snapshot = parking._Park.write_snapshot
    replaced = []

    def replace_lock(self, path, raw):
        write_snapshot(self, path, raw)
        if not replaced:
            lock = repo['directory'] / 'github.lock'
            lock.rename(repo['directory'] / 'retained-original-lock')
            lock.write_bytes(b'replacement')
            lock.chmod(0o640)
            replaced.append(lock.stat().st_ino)

    monkeypatch.setattr(parking._Park, 'write_snapshot', replace_lock)
    before = source_image(repo)
    result = repo['run']()
    assert result['code'] == 'lock_attachment_changed' and not result['executed']
    assert source_image(repo) == before
    lock = repo['directory'] / 'github.lock'
    assert lock.stat().st_ino == replaced[0] and stat.S_IMODE(lock.stat().st_mode) == 0o640


def test_preexisting_temporary_collision_is_preserved(parked_repo, monkeypatch):
    repo = parked_repo
    monkeypatch.setattr(parking.secrets, 'token_hex', lambda size: 'fixed')
    collision = repo['root'] / '.park-fixed'
    # Ignored operational data is outside status and must still never be removed.
    exclude = repo['root'] / '.git/info/exclude'
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text('.park-fixed\n')
    collision.write_bytes(b'preexisting temporary')
    before = source_image(repo)
    result = repo['run']()
    assert result['status'] == 'needs_reconciliation'
    assert source_image(repo) == before and collision.read_bytes() == b'preexisting temporary'


@pytest.mark.parametrize('boundary', ['before_write', 'after_write'])
def test_interruption_checkpoint_blocks_blind_replay(parked_repo, monkeypatch, boundary):
    repo = parked_repo
    restore = parking._Park.restore
    count = []

    def interrupt(self, name):
        count.append(name)
        if boundary == 'after_write':
            restore(self, name)
        raise OSError('synthetic interruption; must not be exposed')

    monkeypatch.setattr(parking._Park, 'restore', interrupt)
    records = evidence(repo)
    first = repo['run']()
    assert first['status'] == 'needs_reconciliation' and first['stage'] == 'restore'
    assert len(count) == 1
    state_path = repo['directory'] / parking.STATE
    state = json.loads(state_path.read_text())
    assert state['checkpoints'][count[0]] == 'applying'
    assert (repo['directory'] / parking.SNAPSHOTS).is_dir()
    monkeypatch.setattr(parking._Park, 'restore', restore)
    before, checkpoint = source_image(repo), state_path.read_bytes()
    again = repo['run']()
    assert again['code'] == 'interrupted_park_requires_reconciliation', again
    assert source_image(repo) == before and state_path.read_bytes() == checkpoint
    assert evidence(repo) == records
    assert 'synthetic interruption' not in json.dumps(first)


def test_already_parked_rechecks_user_edit_and_snapshot_corruption(parked_repo):
    repo = parked_repo
    assert repo['run']()['status'] == 'parked'
    (repo['root'] / 'edit.txt').write_text('later user edit')
    before = source_image(repo)
    result = repo['run']()
    assert result['status'] == 'needs_reconciliation' and source_image(repo) == before
    snapshot = repo['directory'] / parking.SNAPSHOTS / str(sorted(repo['scope']).index('edit.txt'))
    snapshot.write_bytes(b'corrupt snapshot')
    result = repo['run']()
    assert result['code'] == 'park_snapshot_invalid'
    assert source_image(repo) == before


@pytest.mark.parametrize('key', ['TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                                 'TAVERN_IMPROVEMENT_UNATTENDED', 'READ_ONLY', 'GIT'])
def test_untrusted_context_never_reaches_storage(monkeypatch, key):
    monkeypatch.setenv(key, '0' if key == 'GIT' else '1')
    monkeypatch.setattr(native, 'storage_policy', lambda: pytest.fail('untrusted reached storage'))
    result = parking.park('123456-abcdef')
    assert result['status'] == 'needs_reconciliation' and not result['executed']
    assert result['stage'] == 'authorization' and not any(result['side_effects'].values())


def test_invalid_run_returns_bounded_json_before_storage(monkeypatch):
    monkeypatch.setattr(native, 'storage_policy', lambda: pytest.fail('invalid run reached storage'))
    result = parking.park('../unapproved')
    assert result['code'] == 'invalid_run_id' and result['version'] == parking.VERSION
    assert json.loads(json.dumps(result)) == result


def test_argument_only_local_git_seam_never_requests_mutating_commands(parked_repo):
    repo = parked_repo
    actual, calls = git_cleanup.Git(repo['root']), []

    class AuditedGit:
        def run(self, *args, **kwargs):
            positional = list(args)
            while positional and positional[0] == '-c':
                positional = positional[2:]
            assert positional[0] in ('rev-parse', 'ls-tree', 'ls-files', 'diff', 'status')
            calls.append(positional)
            return actual.run(*args, **kwargs)

    result = parking.park(repo['run_id'], git=AuditedGit())
    assert result['status'] == 'parked', result
    assert {row[0] for row in calls} == {'rev-parse', 'ls-tree', 'ls-files', 'diff', 'status'}


@pytest.mark.parametrize('record', ['github.json', 'github-approved.json', 'report.json'])
def test_nonobject_record_stays_bounded_and_preserves_source(parked_repo, record, capsys):
    repo = parked_repo
    git_cleanup.durable_json(repo['directory'] / record, ['untrusted record content'])
    before = source_image(repo)
    result = repo['run']()
    assert result['code'] == 'invalid_record_object' and not result['executed']
    assert source_image(repo) == before
    assert 'untrusted record content' not in json.dumps(result)
    assert capsys.readouterr().out == ''
