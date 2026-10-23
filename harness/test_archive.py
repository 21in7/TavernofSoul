"""Offline specifications; fake mount seam, real private disposable files only."""
import errno
import io
import json
import os
from pathlib import Path
import tarfile
import threading

import pytest

from harness import archive, storage
from harness.test_storage import FakeFS, config_document, save_config


def preserved_tree(path):
    """Compare immutable bytes, permissions, inode and directory entries."""
    info = path.lstat()
    identity = (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid)
    if path.is_dir():
        return identity, {child.name: preserved_tree(child) for child in path.iterdir()}
    return identity, path.read_bytes()


class ArchiveFS(FakeFS):
    remote_online = True

    def local_filesystem(self, path):
        return not str(path).startswith(str(self.remote))

    def mount_ready(self, path):
        if path == self.remote and not self.remote_online:
            return False
        return super().mount_ready(path)


@pytest.fixture
def selected(tmp_path):
    root, local, remote = [tmp_path / name for name in ('project', 'local', 'remote')]
    for path in (root, local, remote):
        path.mkdir(mode=0o700)
    fs = ArchiveFS([local, remote], free=1024 ** 3)
    fs.remote = remote
    data = config_document(local)
    data.update(version=2, archive={'path': str(remote / 'results'),
                                   'required_mount': str(remote), 'min_free_bytes': 1000})
    save_config(root, data)
    policy = storage.resolve_storage(root, env={}, fs=fs)
    policy.prepare()
    return policy, fs


def result(policy, status='passed', kind='workflows'):
    directory = policy.ensure_directory(policy.artifact_root / kind / '100-abcdef')
    report = {'run_id': directory.name, 'status': status,
              'agents': [{'response': 'SECRET RAW MODEL RESPONSE'}],
              'scope': ['README.md'], 'review': {'verdict': 'approved'}}
    archive.write_file(policy, directory / 'report.json', archive.encoded(report))
    archive.write_file(policy, directory / 'changes.diff', b'reviewed result\n')
    return directory


def test_private_terminal_payload_inventory_and_idempotent_resume(selected):
    policy, fs = selected
    directory = result(policy)
    policy.ensure_directory(directory / 'workspace')
    archive.write_file(policy, directory / 'workspace' / 'credential.json', b'not a result')
    archive.write_file(policy, directory / 'model-context.json', b'not a result')
    archive.write_file(policy, directory / 'github-approved.json', b'not a result')
    first = archive.archive_run(policy, directory)
    assert first['status'] == 'archived'
    destination = policy.archive.path / 'workflows' / directory.name
    inventory = json.loads(archive.read_file(policy, destination / 'inventory.json'))
    assert {row['path'] for row in inventory} == {'report.json', 'review.json', 'changes.diff'}
    with tarfile.open(fileobj=io.BytesIO(archive.read_file(policy, destination / 'bundle.tar.gz')), mode='r:gz') as tar:
        report = tar.extractfile('report.json').read()
        assert b'SECRET RAW' not in report and b'agents' not in report
        assert all(member.mode == 0o600 and member.isfile() for member in tar)
    identity = destination.stat().st_ino
    assert archive.archive_run(policy, directory) == first
    assert destination.stat().st_ino == identity
    assert directory.exists() and (directory / 'workspace' / 'credential.json').exists()
    assert destination.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in destination.iterdir())


def test_unavailable_archive_is_pending_and_retry_uses_same_local_payload(selected):
    policy, fs = selected
    directory = result(policy, 'failed')
    fs.remote_online = False
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    frozen = archive.verify_payload(policy, directory / 'archive-payload')
    assert json.loads(archive.read_file(policy, directory / 'report.json'))['status'] == 'failed'
    fs.remote_online = True
    assert archive.archive_run(policy, directory)['status'] == 'archived'
    assert archive.verify_payload(policy, directory / 'archive-payload') == frozen


@pytest.mark.parametrize('status', ['running', 'awaiting_github', 'awaiting_ci', 'cleanup_pending', 'needs_reconciliation'])
def test_intermediate_journals_are_not_archived(selected, status):
    policy, fs = selected
    directory = result(policy, status)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert not policy.archive.path.exists()
    assert not (directory / 'archive-payload').exists()


@pytest.mark.parametrize('attack', ['symlink', 'hardlink', 'fifo', 'mode'])
def test_source_type_and_private_boundary(selected, attack):
    policy, fs = selected
    directory = result(policy)
    path = directory / 'changes.diff'
    if attack == 'symlink':
        path.unlink()
        path.symlink_to(directory / 'report.json')
    elif attack == 'hardlink':
        os.link(path, directory / 'other')
    elif attack == 'fifo':
        path.unlink()
        os.mkfifo(path, 0o600)
    else:
        path.chmod(0o644)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert not policy.archive.path.exists()


@pytest.mark.parametrize('attack', ['contents', 'extra', 'empty', 'symlink', 'hardlink', 'manifest_bytes', 'marker_bytes'])
def test_remote_collision_or_tampering_never_overwrites(selected, attack):
    policy, fs = selected
    directory = result(policy)
    assert archive.archive_run(policy, directory)['status'] == 'archived'
    destination = policy.archive.path / 'workflows' / directory.name
    path = destination / 'inventory.json'
    if attack == 'contents':
        path.write_bytes(b'[]')
    elif attack == 'extra':
        archive.write_file(policy, destination / 'extra.json', b'{}')
    elif attack == 'empty':
        for child in destination.iterdir():
            child.unlink()
    elif attack == 'symlink':
        path.unlink()
        path.symlink_to(directory / 'archive-payload' / 'inventory.json')
    elif attack == 'hardlink':
        os.link(path, destination / 'linked.json')
    else:
        path = destination / ('manifest.json' if attack == 'manifest_bytes' else 'commit.json')
        path.write_bytes(path.read_bytes() + b' ')
    inode = destination.stat().st_ino
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert destination.stat().st_ino == inode
    assert (directory / 'report.json').exists()


def test_remote_rename_einval_does_not_prevent_commit_or_idempotent_readback(selected, monkeypatch):
    policy, fs = selected
    directory = result(policy, 'interrupted')
    original, calls = archive.publish_directory, []
    def nfs_rename(parent, source, target):
        calls.append(target)
        if target != 'archive-payload':
            raise OSError(errno.EINVAL, 'NFS directory no-replace unsupported')
        return original(parent, source, target)
    monkeypatch.setattr(archive, 'publish_directory', nfs_rename)
    first = archive.archive_run(policy, directory)
    assert first['status'] == 'archived'
    payload = archive.verify_payload(policy, directory / 'archive-payload')
    destination = policy.archive.path / 'workflows' / directory.name
    assert archive.verify_archive(policy, destination, 'workflows', directory.name) == payload
    assert archive.archive_run(policy, directory) == first
    assert calls == ['archive-payload']  # Local freeze keeps its stronger rename contract.
    assert {p.name for p in destination.iterdir()} == set(archive.FILES) | {'commit.json'}
    assert all(p.stat().st_nlink == 1 and p.stat().st_mode & 0o777 == 0o600
               for p in destination.iterdir())


@pytest.mark.parametrize('point', ['before_payload_link', 'after_payload_link', 'before_commit_link',
                                   'after_commit_link', 'after_commit_unlink', 'readback'])
def test_publication_interruptions_preserve_evidence_and_resume_exact_frozen_payload(selected, monkeypatch, point):
    policy, fs = selected
    directory = result(policy)
    link, finish, verify = os.link, archive.finish_link, archive.verify_archive
    fired = []
    def interrupt_link(source, target, **kwargs):
        wanted = ('payload' in point and target == 'bundle.tar.gz') or ('commit_link' in point and target == 'commit.json')
        if wanted and not fired:
            fired.append(point)
            if point.startswith('after'):
                link(source, target, **kwargs)
            raise KeyboardInterrupt()
        return link(source, target, **kwargs)
    def interrupt_finish(parent, temporary, final, refresh, verified):
        finish(parent, temporary, final, refresh, verified)
        if point == 'after_commit_unlink' and final == 'commit.json' and not fired:
            fired.append(point)
            raise KeyboardInterrupt()
    def interrupt_readback(*args):
        if point == 'readback' and not fired:
            fired.append(point)
            raise OSError('readback unavailable')
        return verify(*args)
    monkeypatch.setattr(os, 'link', interrupt_link)
    monkeypatch.setattr(archive, 'finish_link', interrupt_finish)
    monkeypatch.setattr(archive, 'verify_archive', interrupt_readback)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert fired == [point]
    frozen = archive.verify_payload(policy, directory / 'archive-payload')
    destination = policy.archive.path / 'workflows' / directory.name
    if point in ('before_payload_link', 'after_payload_link', 'before_commit_link', 'after_commit_link'):
        with pytest.raises((storage.StorageError, OSError)):
            verify(policy, destination, 'workflows', directory.name)
    else:
        assert verify(policy, destination, 'workflows', directory.name) == frozen
    monkeypatch.setattr(os, 'link', link)
    monkeypatch.setattr(archive, 'finish_link', finish)
    monkeypatch.setattr(archive, 'verify_archive', verify)
    assert archive.archive_run(policy, directory)['status'] == 'archived'
    assert archive.verify_payload(policy, directory / 'archive-payload') == frozen
    assert verify(policy, destination, 'workflows', directory.name) == frozen
    assert all(p.stat().st_nlink == 1 and p.stat().st_mode & 0o777 == 0o600
               for p in destination.iterdir())


@pytest.mark.parametrize('tampered', [False, True])
def test_bounded_partial_prefix_is_compared_before_resume_and_never_overwritten(selected, monkeypatch, tampered):
    policy, fs = selected
    directory = result(policy)
    transfer_file = archive.transfer_file
    def partial(policy, payload, name, parent, temporary, refresh, data=None):
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            os.write(fd, b'BAD' if tampered else archive.read_file(policy, payload / name)[:17])
            os.fsync(fd)
        finally:
            os.close(fd)
        raise KeyboardInterrupt()
    monkeypatch.setattr(archive, 'transfer_file', partial)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    destination = policy.archive.path / 'workflows' / directory.name
    assert not (destination / 'commit.json').exists()
    temporary = next(destination.iterdir())
    before = temporary.read_bytes()
    monkeypatch.setattr(archive, 'transfer_file', transfer_file)
    assert archive.archive_run(policy, directory)['status'] == ('pending' if tampered else 'archived')
    if tampered:
        assert temporary.read_bytes() == before
        assert not (destination / 'commit.json').exists()
    else:
        assert archive.verify_archive(policy, destination, 'workflows', directory.name)


@pytest.mark.parametrize('attack', ['empty_directory', 'symlink', 'file'])
def test_unknown_existing_destination_is_not_adopted_or_deleted(selected, attack):
    policy, fs = selected
    directory = result(policy)
    category = policy.archive.path / 'workflows'
    policy.fs.create_directory(category)
    destination = category / directory.name
    if attack == 'empty_directory':
        destination.mkdir(mode=0o700)
    elif attack == 'symlink':
        destination.symlink_to(directory, target_is_directory=True)
    else:
        archive.write_file(policy, destination, b'foreign result')
    inode = destination.lstat().st_ino
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert destination.lstat().st_ino == inode
    assert not (directory / 'archive-transfer.json').exists()


@pytest.mark.parametrize('attack', ['third_link', 'different_temporary', 'mode', 'replaced_directory', 'commit'])
def test_resume_refuses_unknown_hardlinks_attachments_and_marker_tampering(selected, monkeypatch, attack):
    policy, fs = selected
    directory = result(policy)
    link = os.link
    def stop_after_link(source, target, **kwargs):
        link(source, target, **kwargs)
        raise KeyboardInterrupt()
    monkeypatch.setattr(os, 'link', stop_after_link)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    monkeypatch.setattr(os, 'link', link)
    destination = policy.archive.path / 'workflows' / directory.name
    temporary = next(p for p in destination.iterdir() if p.name.startswith('.transfer-'))
    final = destination / 'bundle.tar.gz'
    if attack == 'third_link':
        link(final, directory / 'unknown-alias')
    elif attack == 'different_temporary':
        temporary.unlink()
        archive.write_file(policy, temporary, final.read_bytes())
    elif attack == 'mode':
        final.chmod(0o644)
    elif attack == 'replaced_directory':
        destination.rename(destination.with_name('preserved-evidence'))
        destination.mkdir(mode=0o700)
    else:
        archive.write_file(policy, destination / 'commit.json', b'{}')
    inode = destination.stat().st_ino
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert destination.stat().st_ino == inode
    assert (directory / 'archive-payload' / 'manifest.json').exists()


def test_standalone_checks_archive_and_nested_config_noop(selected):
    policy, fs = selected
    directory = result(policy, kind='checks')
    archive.write_file(policy, directory / 'check.json', b'{"status":"passed"}')
    archive.write_file(policy, directory / 'check.log', b'validation output')
    assert archive.archive_run(policy, directory, 'checks')['status'] == 'archived'
    nested = storage.Storage(root=policy.root)
    assert archive.archive_run(nested, directory)['status'] == 'not_configured'


def test_frozen_payload_tampering_preserves_remote_and_source(selected):
    policy, fs = selected
    directory = result(policy)
    assert archive.archive_run(policy, directory)['status'] == 'archived'
    (directory / 'archive-payload' / 'bundle.tar.gz').write_bytes(b'tampered')
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert (directory / 'report.json').exists()


@pytest.mark.parametrize('kind', ['workflows', 'checks'])
def test_archive_only_cli_never_runs_models_checks_or_git(selected, monkeypatch, kind):
    policy, fs = selected
    directory = result(policy, kind=kind)
    # Full workflow validation intentionally inherits this marker. Simulate the
    # trusted parent's CLI here without weakening the production child guard.
    monkeypatch.delenv('TAVERN_WORKFLOW_CHILD', raising=False)
    monkeypatch.setattr(storage, 'resolve_storage', lambda: policy)
    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('archive recovery executed a process'))
    assert archive.main(['--run-id', directory.name, '--kind', kind]) == 0
    assert json.loads(archive.read_file(policy, directory / 'archive-state.json'))['status'] == 'archived'
    assert json.loads(archive.read_file(policy, directory / 'report.json'))['status'] == 'passed'


@pytest.mark.parametrize('kind', ['workflows', 'checks'])
def test_archive_only_cli_rejects_workflow_child_before_storage_access(monkeypatch, capsys, kind):
    monkeypatch.setenv('TAVERN_WORKFLOW_CHILD', '1')
    def forbidden(*args, **kwargs):
        pytest.fail('workflow child attempted archive recovery or storage access')
    monkeypatch.setattr(storage, 'resolve_storage', forbidden)
    monkeypatch.setattr(archive, 'archive_run', forbidden)
    import subprocess
    monkeypatch.setattr(subprocess, 'run', forbidden)
    assert archive.main(['--run-id', '100-abcdef', '--kind', kind]) == 1
    assert json.loads(capsys.readouterr().out) == {'status': 'pending', 'error': 'archive_unavailable'}


def test_archive_floor_loss_preserves_terminal_outcome(selected):
    policy, fs = selected
    directory = result(policy)
    fs.free = {policy.artifacts.required_mount: 10000, fs.remote: 0}
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert json.loads(archive.read_file(policy, directory / 'report.json'))['status'] == 'passed'
    assert not policy.archive.path.exists()


def test_prepare_files_and_nested_validation_logs_use_actual_layout(selected):
    policy, fs = selected
    directory = result(policy)
    prepare = policy.ensure_directory(directory / 'prepare')
    checks = policy.ensure_directory(directory / 'checks-1' / 'check')
    for path, contents in ((prepare / 'doctor.json', b'{"status":"passed"}'),
                           (prepare / 'doctor.log', b'prepared'),
                           (checks / 'check.json', b'{"status":"passed"}'),
                           (checks / 'parser.log', b'checked')):
        archive.write_file(policy, path, contents)
    archive.write_file(policy, prepare / 'storage-validation.json', b'private config')
    archive.write_file(policy, checks / 'storage-validation.json', b'private config')
    assert archive.archive_run(policy, directory)['status'] == 'archived'
    inventory = json.loads(archive.read_file(policy, directory / 'archive-payload' / 'inventory.json'))
    names = {row['path'] for row in inventory}
    assert {'prepare/doctor.json', 'prepare/doctor.log', 'checks-1/check/check.json',
            'checks-1/check/parser.log'} <= names
    assert not any('storage-validation' in name for name in names)


@pytest.mark.parametrize('published', [False, True])
@pytest.mark.parametrize('changed', ['status', 'review', 'diff', 'new_log', 'removed_diff'])
def test_frozen_payload_never_becomes_evidence_for_changed_terminal_result(selected, published, changed):
    policy, fs = selected
    directory = result(policy, 'failed')
    fs.remote_online = published
    assert archive.archive_run(policy, directory)['status'] == ('archived' if published else 'pending')
    frozen = archive.verify_payload(policy, directory / 'archive-payload')
    if changed in ('status', 'review'):
        report = json.loads(archive.read_file(policy, directory / 'report.json'))
        if changed == 'status':
            report['status'] = 'passed'
        else:
            report['review'] = {'verdict': 'changes_requested'}
        (directory / 'report.json').write_bytes(archive.encoded(report))
    elif changed == 'diff':
        (directory / 'changes.diff').write_bytes(b'new result')
    elif changed == 'removed_diff':
        (directory / 'changes.diff').unlink()
    else:
        prepare = policy.ensure_directory(directory / 'prepare')
        archive.write_file(policy, prepare / 'doctor.log', b'new validation')
    fs.remote_online = True
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert archive.verify_payload(policy, directory / 'archive-payload') == frozen
    destination = policy.archive.path / 'workflows' / directory.name
    if published:
        assert archive.verify_archive(policy, destination, 'workflows', directory.name) == frozen
    else:
        assert not destination.exists()


def test_result_mutation_during_transfer_is_pending_without_changing_local_success(selected, monkeypatch):
    policy, fs = selected
    directory = result(policy)
    transfer = archive.transfer
    def change_after_transfer(*args):
        manifest = transfer(*args)
        (directory / 'changes.diff').write_bytes(b'changed during transfer')
        return manifest
    monkeypatch.setattr(archive, 'transfer', change_after_transfer)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert json.loads(archive.read_file(policy, directory / 'report.json'))['status'] == 'passed'


@pytest.mark.parametrize('status', ['awaiting_connector', 'waiting_for_ci', 'cleanup_pending'])
def test_failed_report_with_pending_git_work_is_not_terminal(selected, status):
    policy, fs = selected
    directory = result(policy, 'failed')
    report = json.loads(archive.read_file(policy, directory / 'report.json'))
    report['github'] = {'status': status}
    (directory / 'report.json').write_bytes(archive.encoded(report))
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert not (directory / 'archive-payload').exists()


@pytest.mark.parametrize('same_bytes', [False, True])
def test_racing_file_eexist_preserves_both_names_and_never_falls_back_to_rename(selected, monkeypatch, same_bytes):
    policy, fs = selected
    directory = result(policy)
    link = os.link
    fired = []
    def collide(source, target, **kwargs):
        if not fired:
            fired.append(target)
            parent = kwargs['dst_dir_fd']
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
            try:
                data = archive.read_file(policy, directory / 'archive-payload' / target) if same_bytes else b'foreign'
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
        return link(source, target, **kwargs)  # Real EEXIST, no replacement.
    monkeypatch.setattr(os, 'link', collide)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    destination = policy.archive.path / 'workflows' / directory.name
    final = destination / 'bundle.tar.gz'
    identity, data = final.stat().st_ino, final.read_bytes()
    monkeypatch.setattr(os, 'link', link)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert final.stat().st_ino == identity and final.read_bytes() == data
    assert len(list(destination.iterdir())) == 2
    assert not (destination / 'commit.json').exists()


def test_published_file_deletion_during_uncommitted_resume_is_not_repaired(selected, monkeypatch):
    policy, fs = selected
    directory = result(policy)
    publish = archive.publish_file
    def before_marker(parent, temporary, final, refresh, verified):
        if final == 'commit.json':
            raise KeyboardInterrupt()
        return publish(parent, temporary, final, refresh, verified)
    monkeypatch.setattr(archive, 'publish_file', before_marker)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    destination = policy.archive.path / 'workflows' / directory.name
    (destination / 'inventory.json').unlink()
    monkeypatch.setattr(archive, 'publish_file', publish)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert not (destination / 'inventory.json').exists()
    assert not (destination / 'commit.json').exists()


def test_crash_before_local_transfer_receipt_fails_closed_without_adopting_remote_directory(selected, monkeypatch):
    policy, fs = selected
    directory = result(policy)
    write = archive.write_file
    def fail_receipt(policy, path, data):
        if path.name == 'archive-transfer.json':
            raise KeyboardInterrupt()
        return write(policy, path, data)
    monkeypatch.setattr(archive, 'write_file', fail_receipt)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    destination = policy.archive.path / 'workflows' / directory.name
    identity = destination.stat().st_ino
    assert list(destination.iterdir()) == []
    monkeypatch.setattr(archive, 'write_file', write)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert destination.stat().st_ino == identity and list(destination.iterdir()) == []


def test_archive_state_failure_after_commit_retries_without_remote_mutation(selected, monkeypatch):
    policy, fs = selected
    directory = result(policy)
    atomic = archive.atomic_state
    def fail_archived_state(policy, directory, value, filename='archive-state.json'):
        if filename == 'archive-state.json' and value['status'] == 'archived':
            raise OSError('local state unavailable after remote commit')
        return atomic(policy, directory, value, filename)
    monkeypatch.setattr(archive, 'atomic_state', fail_archived_state)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    destination = policy.archive.path / 'workflows' / directory.name
    frozen = archive.verify_archive(policy, destination, 'workflows', directory.name)
    identities = {p.name: p.stat().st_ino for p in destination.iterdir()}
    monkeypatch.setattr(archive, 'atomic_state', atomic)
    monkeypatch.setattr(os, 'link', lambda *a, **kw: pytest.fail('committed retry attempted a link'))
    assert archive.archive_run(policy, directory)['status'] == 'archived'
    assert archive.verify_archive(policy, destination, 'workflows', directory.name) == frozen
    assert {p.name: p.stat().st_ino for p in destination.iterdir()} == identities


def test_mount_loss_between_link_and_unlink_is_pending_then_resumes_known_transition(selected, monkeypatch):
    policy, fs = selected
    directory = result(policy)
    link = os.link
    def lose_mount(*args, **kwargs):
        link(*args, **kwargs)
        fs.remote_online = False
    monkeypatch.setattr(os, 'link', lose_mount)
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    assert (directory / 'report.json').exists()
    fs.remote_online = True
    monkeypatch.setattr(os, 'link', link)
    assert archive.archive_run(policy, directory)['status'] == 'archived'
    destination = policy.archive.path / 'workflows' / directory.name
    assert archive.verify_archive(policy, destination, 'workflows', directory.name)
    assert all(p.stat().st_nlink == 1 for p in destination.iterdir())


@pytest.fixture
def resumed(selected, monkeypatch):
    """Disposable evidence models delivery resumption, without running Git/checks.

    The shared offline guard stays installed. Only exclusion markers are cleared
    for exercising the parent's archive-only API against the selected FakeFS.
    """
    from harness import git_publish
    for key in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                'TAVERN_IMPROVEMENT_UNATTENDED', 'READ_ONLY'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('GIT', '1')
    policy, fs = selected
    directory = result(policy, 'failed')
    report = json.loads(archive.read_file(policy, directory / 'report.json'))
    checks = {'offline': {'status': 'passed', 'selected': 3, 'passed': 3,
                          'skipped': [], 'errors': [], 'failures': []}}
    check_dir = policy.ensure_directory(directory / 'checks-1' / 'check')
    archive.write_file(policy, check_dir / 'check.json', archive.encoded({'status': 'passed', 'checks': checks}))
    archive.write_file(policy, check_dir / 'check.log', b'fixture validation evidence\n')
    report.update(read_only=False, simulated=False, no_git=False, github_enabled=True,
                  changed_files=['README.md'], applied=['README.md'], required_checks=['check'],
                  review={'verdict': 'approved', 'summary': 'Fixture independent review.', 'findings': [],
                          'documentation': {'status': 'not_required', 'files': [], 'reason': 'Fixture prose.'}},
                  delivery_validation=[{'command': 'check', 'status': 'passed', 'exit_code': 0,
                                        'checks': checks, 'report': str(check_dir / 'check.json')}])
    ledger = {'version': 'github-v1', 'run_id': directory.name, 'branch': 'codex/' + directory.name,
              'status': 'failed', 'step': 'repository', 'checks': {}}
    report['github'] = git_publish.summary(ledger)
    (directory / 'report.json').write_bytes(archive.encoded(report))
    archive.write_file(policy, directory / 'github.json', archive.encoded(ledger))
    assert archive.archive_run(policy, directory)['status'] == 'archived'
    old_remote = policy.archive.path / 'workflows' / directory.name
    old_paths = [directory / name for name in ('archive-payload', 'archive-frozen.json', 'archive-transfer.json')]
    old_paths.append(old_remote)
    original = {path: preserved_tree(path) for path in old_paths}
    ledger.update(status='merged', step='done', head_sha='a' * 40, merge_sha='b' * 40,
                  merge_status='merged', pr_number=66,
                  pr_url='https://github.com/fixture/project/pull/66',
                  checks={name: 'success' for name in git_publish.REQUIRED},
                  cleanup={'version': 'cleanup-v1', 'status': 'complete',
                           'remote': {'status': 'deleted'}, 'local': {'status': 'absent'},
                           'prune': {'status': 'complete'}, 'sync': {'status': 'complete'},
                           'completion': {'status': 'complete'}})
    ledger['cleanup_proof'] = {'verified': True, 'head_sha': ledger['head_sha'],
                               'merge_sha': ledger['merge_sha'], 'checks': ledger['checks']}
    report.update(status='passed', github=git_publish.summary(ledger))
    cleanup = dict(ledger['cleanup'], run_id=directory.name,
                   head_sha=ledger['head_sha'], merge_sha=ledger['merge_sha'])
    for name, value in (('report.json', report), ('github.json', ledger), ('cleanup.json', cleanup)):
        path = directory / name
        if path.exists():
            path.write_bytes(archive.encoded(value))
        else:
            archive.write_file(policy, path, archive.encoded(value))
    local = directory / archive.RESUMED
    remote = policy.archive.path / archive.RESUMED_KIND / directory.name
    return policy, fs, directory, local, remote, original


def assert_original(original):
    assert {path: preserved_tree(path) for path in original} == original


def test_failed_delivery_success_is_separate_immutable_and_idempotent(resumed, monkeypatch):
    policy, fs, directory, local, remote, original = resumed
    assert archive.archive_run(policy, directory)['status'] == 'pending'
    archive.write_file(policy, directory / 'github-approved.json', b'PRIVATE APPROVAL')
    archive.write_file(policy, directory / 'model-context.json', b'RAW MODEL SOURCE')
    first = archive.archive_resumed_run(policy, directory)
    assert first['status'] == 'archived' and first['terminal_status'] == 'passed'
    assert first['original']['terminal_status'] == 'failed'
    manifest = archive.verify_archive(policy, remote, archive.RESUMED_KIND, directory.name)
    assert manifest != first['original']['manifest']
    record = json.loads(archive.read_file(policy, local / 'recovery.json'))
    assert record['previous_manifest'] == first['original']['manifest']
    assert record['current_inventory_sha256'] == first['inventory_sha256']
    assert record['destination'] == str(remote) and record['run_id'] == directory.name
    records = archive.payload_records(policy, remote, {'report.json', 'github.json', 'cleanup.json'})
    assert records['report.json']['status'] == 'passed'
    assert records['github.json']['merge_sha'] == records['cleanup.json']['merge_sha'] == 'b' * 40
    assert records['cleanup.json']['status'] == 'complete'
    inventory = json.loads(archive.read_file(policy, remote / 'inventory.json'))
    assert all(archive.result_name(row['path']) for row in inventory)
    assert not any('approved' in row['path'] or 'context' in row['path'] for row in inventory)
    before = preserved_tree(remote), preserved_tree(local / 'archive-payload'), preserved_tree(local / 'recovery.json')
    monkeypatch.setattr(os, 'link', lambda *a, **kw: pytest.fail('completed recovery republished'))
    assert archive.archive_resumed_run(policy, directory) == first
    assert archive.resumed_status(policy, directory) == first
    assert before == (preserved_tree(remote), preserved_tree(local / 'archive-payload'), preserved_tree(local / 'recovery.json'))
    assert_original(original)
    assert archive.archive_run(policy, directory)['status'] == 'pending'


@pytest.mark.parametrize('fault', ['status_only', 'pending', 'unknown', 'cleanup_pending', 'review',
    'validation', 'diff', 'new_log', 'missing_log', 'ci', 'proof', 'merge', 'cleanup', 'run', 'branch',
    'applied', 'boolean_exit', 'actual_check', 'no_git', 'read_only', 'simulated', 'selection', 'old_identity'])
def test_resumed_archive_rejects_unproven_or_unrelated_changes(resumed, fault):
    policy, fs, directory, local, remote, original = resumed
    report = json.loads(archive.read_file(policy, directory / 'report.json'))
    ledger = json.loads(archive.read_file(policy, directory / 'github.json'))
    cleanup = json.loads(archive.read_file(policy, directory / 'cleanup.json'))
    if fault == 'status_only':
        ledger = {'version': 'github-v1', 'run_id': directory.name, 'branch': 'codex/' + directory.name,
                  'status': 'failed', 'step': 'repository', 'checks': {}}
    elif fault in ('pending', 'unknown'):
        report['status'] = 'running' if fault == 'pending' else 'unknown'
    elif fault == 'cleanup_pending':
        ledger['cleanup']['status'] = 'cleanup_pending'
    elif fault == 'review':
        report['review']['summary'] = 'Different independent review'
    elif fault == 'validation':
        report['delivery_validation'][0]['checks']['offline']['passed'] = 0
    elif fault == 'diff':
        (directory / 'changes.diff').write_bytes(b'unreviewed change\n')
    elif fault == 'new_log':
        archive.write_file(policy, directory / 'checks-1' / 'check' / 'parser.log', b'new check')
    elif fault == 'missing_log':
        (directory / 'checks-1' / 'check' / 'check.log').unlink()
    elif fault == 'ci':
        ledger['checks'][next(iter(ledger['checks']))] = 'skipped'
    elif fault == 'proof':
        ledger['cleanup_proof']['head_sha'] = 'c' * 40
    elif fault == 'merge':
        ledger['merge_sha'] = 'unknown'
    elif fault == 'cleanup':
        cleanup['run_id'] = '200-fedcba'
    elif fault == 'run':
        ledger['run_id'] = '200-fedcba'
    elif fault == 'branch':
        ledger['branch'] = 'codex/200-fedcba'
    elif fault == 'applied':
        report['applied'] = []
    elif fault == 'boolean_exit':
        report['delivery_validation'][0]['exit_code'] = False
    elif fault == 'actual_check':
        (directory / 'checks-1' / 'check' / 'check.json').write_bytes(b'{"status":"failed"}')
    elif fault in ('no_git', 'read_only', 'simulated'):
        report[fault] = True
    elif fault == 'selection':
        report['required_checks'] = ['check-docs']
    elif fault == 'old_identity':
        ledger['version'] = 'github-v2'
    from harness import git_publish
    report['github'] = git_publish.summary(ledger)
    for name, value in (('report.json', report), ('github.json', ledger), ('cleanup.json', cleanup)):
        (directory / name).write_bytes(archive.encoded(value))
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert not remote.exists() and not local.exists()
    assert_original(original)


@pytest.mark.parametrize('point', ['freeze', 'receipt', 'before_payload', 'after_payload', 'before_commit',
                                   'after_commit', 'readback', 'state'])
def test_resumed_archive_interruption_preserves_evidence_and_exact_resume(resumed, monkeypatch, point):
    policy, fs, directory, local, remote, original = resumed
    freeze, write, link = archive.freeze, archive.write_file, os.link
    verify, atomic = archive.verify_archive, archive.atomic_state
    fired = []
    def stop():
        fired.append(point)
        raise KeyboardInterrupt()
    def freeze_stop(*args, **kwargs):
        value = freeze(*args, **kwargs)
        if point == 'freeze' and not fired:
            stop()
        return value
    def write_stop(policy, path, data):
        if point == 'receipt' and path == local / 'archive-transfer.json' and not fired:
            stop()
        return write(policy, path, data)
    def link_stop(source, target, **kwargs):
        wanted = (point.endswith('payload') and target == 'bundle.tar.gz' or
                  point.endswith('commit') and target == 'commit.json')
        if wanted and not fired:
            if point.startswith('after'):
                link(source, target, **kwargs)
            stop()
        return link(source, target, **kwargs)
    def verify_stop(policy, path, kind, run_id):
        if path == remote and point == 'readback' and not fired:
            stop()
        return verify(policy, path, kind, run_id)
    def state_stop(policy, path, value, filename='archive-state.json'):
        if path == local and point == 'state' and value.get('status') == 'archived' and not fired:
            stop()
        return atomic(policy, path, value, filename)
    monkeypatch.setattr(archive, 'freeze', freeze_stop)
    monkeypatch.setattr(archive, 'write_file', write_stop)
    monkeypatch.setattr(os, 'link', link_stop)
    monkeypatch.setattr(archive, 'verify_archive', verify_stop)
    monkeypatch.setattr(archive, 'atomic_state', state_stop)
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert fired == [point]
    record = preserved_tree(local / 'recovery.json')
    payload = preserved_tree(local / 'archive-payload')
    assert_original(original)
    retry = archive.archive_resumed_run(policy, directory)
    assert retry['status'] == ('pending' if point == 'receipt' else 'archived')
    if point == 'receipt':
        assert not (local / 'archive-transfer.json').exists() and list(remote.iterdir()) == []
    else:
        assert verify(policy, remote, archive.RESUMED_KIND, directory.name)
    assert record == preserved_tree(local / 'recovery.json')
    assert payload == preserved_tree(local / 'archive-payload')
    assert_original(original)


@pytest.mark.parametrize('tampered', [False, True])
def test_resumed_partial_prefix_is_compared_and_never_replaced(resumed, monkeypatch, tampered):
    policy, fs, directory, local, remote, original = resumed
    transfer = archive.transfer_file
    def partial(policy, payload, name, parent, temporary, refresh, data=None):
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(b'BAD' if tampered else archive.read_file(policy, payload / name)[:17])
        raise KeyboardInterrupt()
    monkeypatch.setattr(archive, 'transfer_file', partial)
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    path = next(remote.iterdir())
    before = preserved_tree(path)
    monkeypatch.setattr(archive, 'transfer_file', transfer)
    assert archive.archive_resumed_run(policy, directory)['status'] == ('pending' if tampered else 'archived')
    if tampered:
        assert preserved_tree(path) == before and not (remote / 'commit.json').exists()
    assert_original(original)


@pytest.mark.parametrize('fault', ['linkage', 'generation', 'current', 'commit', 'marker_run', 'marker_kind', 'missing_commit',
                                  'payload', 'missing_payload', 'remote_extra', 'receipt', 'old_marker'])
def test_resumed_commit_linkage_and_current_changes_remain_pending(resumed, fault):
    policy, fs, directory, local, remote, original = resumed
    assert archive.archive_resumed_run(policy, directory)['status'] == 'archived'
    if fault in ('linkage', 'generation'):
        path = local / 'recovery.json'
        record = json.loads(path.read_bytes())
        record['run_id' if fault == 'linkage' else 'generation'] = '200-fedcba'
        path.write_bytes(archive.encoded(record))
    elif fault == 'current':
        report = json.loads((directory / 'report.json').read_bytes())
        report['finished_at'] = 'later'
        (directory / 'report.json').write_bytes(archive.encoded(report))
        assert archive.resumed_status(policy, directory)['status'] == 'pending'
    elif fault in ('marker_run', 'marker_kind'):
        path = remote / 'commit.json'
        marker = json.loads(path.read_bytes())
        marker['run_id' if fault == 'marker_run' else 'kind'] = '200-fedcba'
        path.write_bytes(archive.encoded(marker))
    elif fault == 'receipt':
        path = local / 'archive-transfer.json'
        receipt = json.loads(path.read_bytes())
        receipt['destination'] = str(remote.parent / '200-fedcba')
        path.write_bytes(archive.encoded(receipt))
    elif fault in ('commit', 'payload', 'old_marker'):
        path = {'commit': remote / 'commit.json', 'payload': remote / 'bundle.tar.gz',
                'old_marker': policy.archive.path / 'workflows' / directory.name / 'commit.json'}[fault]
        path.write_bytes(path.read_bytes() + b' ')
    elif fault in ('missing_commit', 'missing_payload'):
        (remote / ('commit.json' if fault == 'missing_commit' else 'inventory.json')).unlink()
    else:
        archive.write_file(policy, remote / 'unknown', b'foreign')
    before = preserved_tree(remote)
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert preserved_tree(remote) == before
    if fault != 'old_marker':
        assert_original(original)


@pytest.mark.parametrize('fault', ['mount', 'floor', 'local_floor', 'mode', 'symlink', 'hardlink', 'collision'])
def test_resumed_storage_boundaries_preserve_prior_archive(resumed, fault):
    policy, fs, directory, local, remote, original = resumed
    if fault == 'mount':
        fs.remote_online = False
    elif fault in ('floor', 'local_floor'):
        fs.free = {policy.artifacts.required_mount: 0 if fault == 'local_floor' else 1024 ** 3,
                   fs.remote: 0 if fault == 'floor' else 1024 ** 3}
    elif fault == 'collision':
        policy.fs.create_directory(remote.parent)
        remote.mkdir(mode=0o700)
    else:
        path = directory / 'cleanup.json'
        if fault == 'mode':
            path.chmod(0o644)
        elif fault == 'symlink':
            path.unlink()
            path.symlink_to(directory / 'report.json')
        else:
            os.link(path, directory / 'extra-link')
    before = preserved_tree(remote) if remote.exists() else None
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    if before is not None:
        assert preserved_tree(remote) == before and not (local / 'archive-transfer.json').exists()
    assert_original(original)


def test_concurrent_resumed_archives_share_original_mutex(resumed, monkeypatch):
    policy, fs, directory, local, remote, original = resumed
    entered, release = threading.Event(), threading.Event()
    transfer = archive.transfer
    outcomes = []
    def held(*args):
        entered.set()
        assert release.wait(5)
        return transfer(*args)
    monkeypatch.setattr(archive, 'transfer', held)
    thread = threading.Thread(target=lambda: outcomes.append(archive.archive_resumed_run(policy, directory)))
    thread.start()
    try:
        assert entered.wait(5)
        assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
        # The ordinary intent is serialized by exactly the same persistent inode.
        with pytest.raises(BlockingIOError):
            archive.archive_run(policy, directory)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and outcomes[0]['status'] == 'archived'
    assert archive.archive_resumed_run(policy, directory) == outcomes[0]
    assert list(remote.parent.iterdir()) == [remote]
    assert_original(original)


@pytest.mark.parametrize('marker', ['TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                                  'TAVERN_IMPROVEMENT_UNATTENDED', 'READ_ONLY', 'GIT'])
def test_explicit_recovery_excludes_children_before_any_storage(monkeypatch, marker):
    monkeypatch.setenv(marker, '0' if marker == 'GIT' else '1')
    monkeypatch.setattr(storage, 'resolve_storage', lambda: pytest.fail('excluded context touched storage'))
    assert archive.main(['--run-id', '100-abcdef', '--resume-failed-to-passed']) == 1
    with pytest.raises(storage.StorageError):
        archive.archive_resumed_run(object(), Path('/not-accessed/100-abcdef'))


def test_explicit_recovery_cli_exit_and_kind_contract(resumed, monkeypatch):
    policy, fs, directory, local, remote, original = resumed
    monkeypatch.setattr(storage, 'resolve_storage', lambda: policy)
    args = ['--run-id', directory.name, '--resume-failed-to-passed']
    assert archive.main(args + ['--kind', 'checks']) == 1
    assert archive.main(args) == 0
    (directory / 'changes.diff').write_bytes(b'later changed result')
    assert archive.main(args) == 1
    assert_original(original)


@pytest.mark.parametrize('fault', ['record', 'record_mode', 'record_symlink', 'record_hardlink',
                                  'checkpoint', 'run_identity', 'prior_digest', 'inventory_digest'])
def test_private_recovery_record_cannot_be_adopted_or_rebound(resumed, monkeypatch, fault):
    policy, fs, directory, local, remote, original = resumed
    transfer = archive.transfer
    monkeypatch.setattr(archive, 'transfer', lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    monkeypatch.setattr(archive, 'transfer', transfer)
    path = local / 'recovery.json'
    if fault == 'record':
        path.unlink()
    elif fault == 'record_mode':
        path.chmod(0o644)
    elif fault == 'record_symlink':
        path.unlink()
        path.symlink_to(directory / 'report.json')
    elif fault == 'record_hardlink':
        os.link(path, directory / 'unknown-record-alias')
    elif fault == 'checkpoint':
        (local / 'archive-frozen.json').write_bytes(b'{}')
    else:
        record = json.loads(path.read_bytes())
        if fault == 'run_identity':
            record['run_identity'][1] += 1
        else:
            record['previous_manifest_sha256' if fault == 'prior_digest' else 'current_inventory_sha256'] = '0' * 64
        path.write_bytes(archive.encoded(record))
    before = preserved_tree(local / 'archive-payload')
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert not remote.exists() and preserved_tree(local / 'archive-payload') == before
    assert_original(original)


@pytest.mark.parametrize('fault', ['receipt', 'receipt_identity', 'uncommitted', 'checkpoint', 'marker'])
def test_recovery_requires_verified_predecessor_without_repairing_it(resumed, fault):
    policy, fs, directory, local, remote, original = resumed
    if fault in ('receipt', 'receipt_identity', 'uncommitted'):
        path = directory / 'archive-transfer.json'
        if fault == 'receipt':
            path.unlink()
        else:
            receipt = json.loads(path.read_bytes())
            if fault == 'receipt_identity':
                receipt['directory_identity'][1] += 1
            else:
                receipt['committed'] = False
            path.write_bytes(archive.encoded(receipt))
    elif fault == 'checkpoint':
        (directory / 'archive-frozen.json').write_bytes(b'{}')
    else:
        (policy.archive.path / 'workflows' / directory.name / 'commit.json').write_bytes(b'{}')
    old_remote = policy.archive.path / 'workflows' / directory.name
    before = preserved_tree(old_remote)
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert not local.exists() and not remote.exists()
    assert preserved_tree(old_remote) == before


def test_current_result_change_during_transfer_never_becomes_success(resumed, monkeypatch):
    policy, fs, directory, local, remote, original = resumed
    transfer = archive.transfer
    def change_after_commit(*args):
        value = transfer(*args)
        report = json.loads((directory / 'report.json').read_bytes())
        report['finished_at'] = 'changed during readback'
        (directory / 'report.json').write_bytes(archive.encoded(report))
        return value
    monkeypatch.setattr(archive, 'transfer', change_after_commit)
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert archive.verify_archive(policy, remote, archive.RESUMED_KIND, directory.name)
    assert archive.resumed_status(policy, directory)['status'] == 'pending'
    before = preserved_tree(remote), preserved_tree(local / 'recovery.json')
    monkeypatch.setattr(archive, 'transfer', lambda *a: pytest.fail('changed result entered transfer'))
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert before == (preserved_tree(remote), preserved_tree(local / 'recovery.json'))
    assert_original(original)


def test_result_change_between_linkage_and_freeze_is_not_transferred(resumed, monkeypatch):
    policy, fs, directory, local, remote, original = resumed
    freeze = archive.freeze
    def change_before_freeze(*args, **kwargs):
        report = json.loads((directory / 'report.json').read_bytes())
        report['finished_at'] = 'changed before freeze'
        (directory / 'report.json').write_bytes(archive.encoded(report))
        return freeze(*args, **kwargs)
    monkeypatch.setattr(archive, 'freeze', change_before_freeze)
    monkeypatch.setattr(archive, 'transfer', lambda *a: pytest.fail('changed freeze entered transfer'))
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert not remote.exists() and (local / 'recovery.json').exists()
    assert_original(original)


def test_status_exposes_successor_and_original_without_remote_io(resumed, monkeypatch, capsys):
    from harness import workflow
    policy, fs, directory, local, remote, original = resumed
    assert archive.archive_resumed_run(policy, directory)['status'] == 'archived'
    monkeypatch.setattr(workflow, 'storage_policy', lambda: policy)
    monkeypatch.setattr(workflow, 'ROOT', policy.root)
    monkeypatch.setattr(workflow, 'REPORTS', directory.parent)
    monkeypatch.setattr(archive, 'archive_ready', lambda *a: pytest.fail('status touched remote archive'))
    monkeypatch.setattr(archive, 'verify_archive', lambda *a: pytest.fail('status verified remote archive'))
    assert workflow.main(['status', '--run-id', directory.name]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['archive']['status'] == 'archived'
    assert summary['archive']['terminal_status'] == 'passed'
    assert summary['archive_original']['status'] == 'archived'
    (directory / 'checks-1' / 'check' / 'check.log').write_bytes(b'later validation')
    assert workflow.main(['status', '--run-id', directory.name]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary['status'] == 'passed' and summary['archive']['status'] == 'pending'
    assert summary['github']['cleanup']['status'] == 'complete'
    assert_original(original)


def test_unconfigured_recovery_never_converts_legacy_storage(selected, monkeypatch):
    for key in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                'TAVERN_IMPROVEMENT_UNATTENDED', 'READ_ONLY'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('GIT', '1')
    policy, fs = selected
    legacy = storage.Storage(root=policy.root)
    assert archive.archive_resumed_run(legacy, Path('/not-read/100-abcdef')) == {'status': 'not_configured'}


@pytest.mark.parametrize('fault', ['mode', 'symlink', 'hardlink', 'mount_identity', 'replacement'])
def test_resumed_destination_keeps_private_attachment_guards(resumed, fault):
    policy, fs, directory, local, remote, original = resumed
    assert archive.archive_resumed_run(policy, directory)['status'] == 'archived'
    path = remote / 'inventory.json'
    if fault == 'mode':
        path.chmod(0o644)
    elif fault == 'symlink':
        path.unlink()
        path.symlink_to(local / 'archive-payload' / 'inventory.json')
    elif fault == 'hardlink':
        os.link(path, directory / 'unknown-remote-alias')
    elif fault == 'mount_identity':
        info = remote.stat()
        fs.mount_ids[(info.st_dev, info.st_ino)] = 99
    else:
        remote.rename(remote.with_name('preserved-foreign-directory'))
        remote.mkdir(mode=0o700)
    before = preserved_tree(remote)
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert preserved_tree(remote) == before
    assert_original(original)


def test_recovery_mkdir_without_record_stays_unowned(resumed, monkeypatch):
    policy, fs, directory, local, remote, original = resumed
    write = archive.write_file
    def stop_record(policy, path, data):
        if path == local / 'recovery.json':
            raise KeyboardInterrupt()
        return write(policy, path, data)
    monkeypatch.setattr(archive, 'write_file', stop_record)
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert local.exists() and list(local.iterdir()) == []
    before = preserved_tree(local)
    monkeypatch.setattr(archive, 'write_file', write)
    assert archive.archive_resumed_run(policy, directory)['status'] == 'pending'
    assert preserved_tree(local) == before and not remote.exists()
    assert_original(original)


def test_regular_archive_cli_retains_git_zero_terminal_support(selected, monkeypatch):
    policy, fs = selected
    directory = result(policy, 'failed')
    for key in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY', 'TAVERN_IMPROVEMENT_UNATTENDED'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('GIT', '0')
    monkeypatch.setattr(storage, 'resolve_storage', lambda: policy)
    assert archive.main(['--run-id', directory.name]) == 0
    assert json.loads(archive.read_file(policy, directory / 'report.json'))['status'] == 'failed'
