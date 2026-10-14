"""Offline storage regressions: fake mounts, real disposable private files only."""

import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from harness import storage


class FakeFS(storage.FileSystem):
    def __init__(self, mounts=(), free=10000):
        self.mounts = set(mounts)
        self.free = free
        self.created = []
        self.probes = []
        self.fail_probe = False
        self.mount_queries = []
        self.space_queries = []
        self.identity_queries = []
        self.open_queries = []
        self.mount_ids = {}

    def mount_ready(self, path):
        self.mount_queries.append(path)
        return path in self.mounts

    def free_bytes(self, path):
        self.space_queries.append(path)
        return self.free

    def mount_identity(self, directory, name=''):
        # Synthetic kernel identities keep these tests independent of real
        # mounts/statx support; dedicated ABI tests below fake the libc seam.
        owner = os.fstat(directory)
        info = (os.stat(name, dir_fd=directory, follow_symlinks=False)
                if name else owner)
        result = self.mount_ids.get((info.st_dev, info.st_ino), 1)
        self.identity_queries.append(((owner.st_dev, owner.st_ino), name, result))
        return result

    def open_directory(self, path):
        self.open_queries.append(path)
        return super().open_directory(path)

    def create_directory(self, path):
        self.created.append(path)
        super().create_directory(path)

    def probe(self, path):
        self.probes.append(path)
        if self.fail_probe:
            raise PermissionError('sensitive OS diagnostic must not escape')
        super().probe(path)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    return root


def config_document(mount):
    return {'version': 1,
            'artifacts': {'path': str(mount / 'private/artifacts'),
                          'required_mount': str(mount), 'min_free_bytes': 1000},
            'temporary': {'path': str(mount / 'private/temporary'),
                          'required_mount': str(mount), 'min_free_bytes': 1000}}


def save_config(root, data, path=None):
    path = path or root / 'logs/harness/storage-local.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')
    path.chmod(0o600)
    return path


@pytest.fixture
def configured(project, tmp_path):
    mount = tmp_path / 'fake-mount'
    mount.mkdir()
    fs = FakeFS([mount])
    data = config_document(mount)
    save_config(project, data)
    policy = storage.resolve_storage(project, env={}, fs=fs)
    return policy, fs, data


def make_run(root, run_id='100-abcdef', *, report=True, time_ns=1000):
    directory = root / run_id
    missing = []
    for component in (directory, *directory.parents):
        if component.exists():
            break
        missing.append(component)
    for component in reversed(missing):
        component.mkdir(mode=0o700)
        component.chmod(0o700)
    if report:
        path = directory / 'report.json'
        path.write_text(json.dumps({'run_id': run_id, 'workspace': str(directory / 'workspace'),
                                    'status': 'awaiting_github'}))
        path.chmod(0o600)
        os.utime(path, ns=(time_ns, time_ns))
    return directory


def test_defaults_are_lazy_local_and_do_not_create_directories(project):
    class NoMountAccess(FakeFS):
        def mount_ready(self, path):
            raise AssertionError('local defaults must not inspect mounts')

        def free_bytes(self, path):
            raise AssertionError('local defaults must not inspect free space')

    fs = NoMountAccess()
    policy = storage.resolve_storage(project, env={}, fs=fs)
    assert not policy.configured
    assert policy.artifact_root == project / 'logs/harness'
    assert policy.report_dir() == project / 'logs/harness'
    assert policy.report_dir('agents') == project / 'logs/harness/agents'
    assert policy.workflow_root() == project / 'logs/harness/workflows'
    assert policy.context_root == Path('/tmp')
    assert policy.temp_root is None
    assert policy.status()['status'] == 'ready'
    assert fs.created == fs.probes == []
    assert not (project / 'logs').exists()


def test_explicit_root_and_local_reports_never_consult_another_project(project, tmp_path):
    # A different repository's config can point at unavailable real storage.
    other = tmp_path / 'other'
    other.mkdir()
    save_config(other, config_document(tmp_path / 'absent-mount'))
    policy = storage.resolve_storage(project, env={})
    custom_reports = project / 'custom-reports'
    assert policy.report_dir('agents', local_default=custom_reports) == custom_reports
    assert policy.workflow_roots(local_default=custom_reports) == (
        custom_reports, project / 'logs/harness/workflows')
    assert policy.project_lock_path == project / 'logs/harness/workflows/.lock'
    assert policy.status()['mode'] == 'local'


def test_optional_private_config_and_environment_precedence(configured, tmp_path):
    policy, fs, data = configured
    assert policy.configured
    assert policy.artifact_root == Path(data['artifacts']['path'])
    second = dict(data)
    second['artifacts'] = {**data['artifacts'], 'path': str(next(iter(fs.mounts)) / 'second-artifacts')}
    path = save_config(policy.root, second, tmp_path / 'explicit.json')
    selected = storage.resolve_storage(policy.root, env={storage.CONFIG_ENV: str(path)}, fs=fs)
    assert selected.artifact_root == Path(second['artifacts']['path'])
    assert fs.created == fs.probes == []


def test_explicit_valid_config_does_not_merge_invalid_optional_config(configured, tmp_path):
    policy, fs, data = configured
    explicit = save_config(policy.root, data, tmp_path / 'valid.json')
    (policy.root / 'logs/harness/storage-local.json').write_text('invalid')
    chosen = storage.resolve_storage(policy.root, env={storage.CONFIG_ENV: str(explicit)}, fs=fs)
    assert chosen.artifact_root == policy.artifact_root


def test_report_precedence_is_consistent_for_all_categories(configured, tmp_path):
    policy, fs, _ = configured
    env_dir = tmp_path / 'environment-reports'
    explicit = tmp_path / 'explicit-reports'
    policy.env[storage.REPORT_ENV] = str(env_dir)
    for category in (None, 'agents', 'triage', 'compaction', 'workflows'):
        assert policy.report_dir(category, explicit=explicit) == explicit
        assert policy.report_dir(category) == env_dir
    del policy.env[storage.REPORT_ENV]
    for category in ('agents', 'triage', 'compaction', 'workflows'):
        assert policy.report_dir(category, local_default=policy.root / 'old') == policy.artifact_root / category
    assert fs.created == []


def test_local_explicit_and_environment_report_overrides(project, tmp_path):
    env_dir, explicit = tmp_path / 'env', tmp_path / 'explicit'
    policy = storage.resolve_storage(project, env={storage.REPORT_ENV: str(env_dir)})
    assert policy.report_dir('agents') == env_dir
    assert policy.report_dir('agents', explicit=explicit) == explicit


def test_prepare_creates_private_roots_without_chmod_mount_or_existing_parents(configured):
    policy, fs, _ = configured
    mount = next(iter(fs.mounts))
    mount.chmod(0o755)
    parent = mount / 'private'
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    policy.prepare()
    assert stat.S_IMODE(mount.stat().st_mode) == 0o755
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    for path in (policy.artifact_root, policy.temp_root):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
        assert list(path.iterdir()) == []
    assert set(fs.probes) == {policy.artifact_root, policy.temp_root}


def test_probe_file_is_private_and_unique_and_removed(configured, monkeypatch):
    policy, _, _ = configured
    policy.prepare(probe=False)
    existing = policy.artifact_root / 'preserve.txt'
    existing.write_text('existing user file')
    observed = []
    unlink = os.unlink

    def observe_unlink(path, *args, **kwargs):
        if isinstance(path, str) and path.startswith('.harness-storage-probe-'):
            info = os.stat(path, dir_fd=kwargs['dir_fd'], follow_symlinks=False)
            observed.append((path, stat.S_IMODE(info.st_mode)))
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, 'unlink', observe_unlink)
    policy.status(probe=True)
    policy.status(probe=True)
    assert len(observed) == 4
    assert len({name for name, _ in observed}) == 4
    assert all(mode == 0o600 for _, mode in observed)
    assert existing.read_text() == 'existing user file'
    assert list(policy.artifact_root.iterdir()) == [existing]


def test_custom_context_and_validation_temp_use_shared_policy(configured, monkeypatch):
    policy, _, _ = configured
    before = dict(os.environ)
    monkeypatch.setenv('TMPDIR', '/unrelated-existing-process-value')
    for purpose in ('context', 'validation'):
        with policy.temporary_directory(prefix='test-harness-', purpose=purpose) as directory:
            assert directory.parent == policy.temp_root
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
            (directory / 'fixture').write_text('non-credential data')
        assert not directory.exists()
    assert os.environ['TMPDIR'] == '/unrelated-existing-process-value'
    assert os.environ.get('HOME') == before.get('HOME')
    assert os.environ.get('CODEX_HOME') == before.get('CODEX_HOME')


def test_configured_temp_creation_does_not_follow_replaced_parent(configured, tmp_path, monkeypatch):
    policy, fs, _ = configured
    policy.prepare(probe=False)
    outside = tmp_path / 'outside-temporary'
    outside.mkdir(mode=0o700)
    create_temporary = fs.create_temporary

    def replace_parent_then_create(parent, prefix):
        parent.rename(parent.with_name('retained-original-temporary'))
        parent.symlink_to(outside, target_is_directory=True)
        return create_temporary(parent, prefix)

    monkeypatch.setattr(fs, 'create_temporary', replace_parent_then_create)
    with pytest.raises(storage.StorageError, match='Cannot create private non-credential'):
        policy.mkdtemp(purpose='context')
    assert list(outside.iterdir()) == []
    assert list(policy.temp_root.with_name('retained-original-temporary').iterdir()) == []


def test_local_temp_call_retains_legacy_dir_arguments(project, tmp_path, monkeypatch):
    policy = storage.resolve_storage(project, env={})
    observed = []

    def fake_mkdtemp(*, prefix, dir):
        observed.append(dir)
        path = tmp_path / ('created-' + str(len(observed)))
        path.mkdir(mode=0o700)
        return str(path)

    monkeypatch.setattr(storage.tempfile, 'mkdtemp', fake_mkdtemp)
    policy.mkdtemp(purpose='context')
    policy.mkdtemp(purpose='validation')
    assert observed == ['/tmp', None]


def test_credential_runtime_is_local_regardless_of_artifacts_temp_and_reports(configured, tmp_path):
    policy, fs, _ = configured
    policy.env[storage.REPORT_ENV] = str(tmp_path / 'external-reports')
    assert policy.credential_runtime_root == policy.root / 'logs/harness/agents/runtime'
    assert policy.credential_temp_root == Path('/tmp')
    assert policy.project_lock_path == policy.root / 'logs/harness/workflows/.lock'
    assert policy.credential_runtime_root != policy.report_dir('agents') / 'runtime'
    assert fs.created == fs.probes == []


@pytest.mark.parametrize('value', ['', 'relative.json', '../secret.json', '/tmp/../secret.json', '/tmp//bad', '/tmp/bad\n'])
def test_invalid_explicit_config_paths_are_sanitized(project, value):
    with pytest.raises(storage.StorageError, match='absolute normalized') as error:
        storage.resolve_storage(project, env={storage.CONFIG_ENV: value})
    assert 'secret' not in str(error.value)


def test_missing_explicit_config_never_falls_back_to_valid_optional(configured, tmp_path):
    policy, fs, _ = configured
    with pytest.raises(storage.StorageError, match='Explicit HARNESS_STORAGE_CONFIG is missing'):
        storage.resolve_storage(policy.root, env={storage.CONFIG_ENV: str(tmp_path / 'missing.json')}, fs=fs)
    assert fs.created == fs.probes == []


@pytest.mark.parametrize('raw', ['not JSON PRIVATE-SECRET', '{"version":1,"version":1}',
                                '{"version":NaN}', '[]', 'null', '{"version":2}', '{"version":true}'])
def test_present_malformed_config_is_fatal_and_never_echoed(project, raw):
    path = save_config(project, {})
    path.write_text(raw)
    with pytest.raises(storage.StorageError) as error:
        storage.resolve_storage(project, env={})
    assert 'PRIVATE-SECRET' not in str(error.value)


@pytest.mark.parametrize('field,value', [('path', 'relative'), ('path', 3), ('path', None),
                                       ('required_mount', []), ('min_free_bytes', True),
                                       ('min_free_bytes', -1), ('min_free_bytes', 1.5),
                                       ('min_free_bytes', '1000')])
def test_directory_schema_is_strict(configured, field, value):
    policy, fs, data = configured
    data['artifacts'][field] = value
    save_config(policy.root, data)
    with pytest.raises(storage.StorageError):
        storage.resolve_storage(policy.root, env={}, fs=fs)
    assert fs.created == fs.probes == []


@pytest.mark.parametrize('where', ['root', 'directory'])
def test_unknown_config_fields_are_rejected(configured, where):
    policy, fs, data = configured
    target = data if where == 'root' else data['temporary']
    target['private-secret-value'] = 'never echo'
    save_config(policy.root, data)
    with pytest.raises(storage.StorageError) as error:
        storage.resolve_storage(policy.root, env={}, fs=fs)
    assert 'never echo' not in str(error.value)
    assert 'private-secret-value' not in str(error.value)


@pytest.mark.parametrize('kind', ['inside-repository', 'repository-parent', 'mount-root',
                                 'outside-mount', 'same-app', 'nested-app', 'contains-other-mount'])
def test_unsafe_directory_relationships_are_rejected(configured, kind):
    policy, fs, data = configured
    mount = next(iter(fs.mounts))
    if kind == 'inside-repository':
        data['artifacts'].update(path=str(policy.root / 'logs/output'), required_mount=str(policy.root.parent))
    elif kind == 'repository-parent':
        data['artifacts'].update(path=str(policy.root.parent), required_mount='/')
    elif kind == 'mount-root':
        data['artifacts']['path'] = str(mount)
    elif kind == 'outside-mount':
        data['artifacts']['path'] = str(policy.root.parent / 'other')
    elif kind == 'same-app':
        data['temporary']['path'] = data['artifacts']['path']
    elif kind == 'nested-app':
        data['temporary']['path'] = data['artifacts']['path'] + '/temporary'
    else:
        data['temporary'].update(required_mount=data['artifacts']['path'] + '/nested-mount',
                                 path=data['artifacts']['path'] + '/nested-mount/tmp')
    save_config(policy.root, data)
    with pytest.raises(storage.StorageError):
        storage.resolve_storage(policy.root, env={}, fs=fs)
    assert fs.created == fs.probes == []


@pytest.mark.parametrize('kind', ['config', 'application', 'mount', 'ancestor', 'dangling'])
def test_symlinked_config_and_storage_components_are_rejected(configured, tmp_path, kind):
    policy, fs, data = configured
    mount = next(iter(fs.mounts))
    target = tmp_path / 'target'
    target.mkdir()
    if kind == 'config':
        path = policy.config_path
        copy = tmp_path / 'real-config.json'
        copy.write_text(path.read_text())
        path.unlink()
        path.symlink_to(copy)
    elif kind == 'mount':
        mount.rmdir()
        mount.symlink_to(target, target_is_directory=True)
    elif kind == 'application':
        policy.artifact_root.parent.mkdir()
        policy.artifact_root.symlink_to(target, target_is_directory=True)
    else:
        (mount / 'private').symlink_to(target if kind == 'ancestor' else tmp_path / 'nonexistent')
    with pytest.raises(storage.StorageError, match='symlink'):
        storage.resolve_storage(policy.root, env={}, fs=fs)
    assert fs.created == fs.probes == []


def test_absent_mount_fails_before_mkdir_probe_or_local_fallback(configured):
    policy, fs, _ = configured
    fs.mounts.clear()  # The mount directory still exists, as after unmounting NFS.
    for operation in (policy.prepare, lambda: policy.ensure_directory(policy.artifact_root / 'agents'),
                      lambda: policy.mkdtemp(purpose='context'), policy.workflow_root):
        with pytest.raises(storage.StorageError, match='required mount is absent'):
            operation()
    assert fs.created == fs.probes == []
    assert not policy.artifact_root.exists()
    assert not policy.temp_root.exists()
    assert not (policy.root / 'logs/harness/workflows').exists()
    result = policy.status()
    assert result['status'] == 'failed'
    assert not result['directories']['artifacts']['mount_ready']


def test_absent_second_mount_blocks_even_first_application_creation(configured, tmp_path):
    policy, fs, data = configured
    second = tmp_path / 'second-unmounted'
    second.mkdir()
    data['temporary'].update(required_mount=str(second), path=str(second / 'temporary'))
    save_config(policy.root, data)
    policy = storage.resolve_storage(policy.root, env={}, fs=fs)
    with pytest.raises(storage.StorageError, match='temporary required mount is absent'):
        policy.prepare()
    assert fs.created == fs.probes == []


def test_below_floor_blocks_writes_and_reports_actual_mount_readiness(configured):
    policy, fs, _ = configured
    fs.free = 999
    with pytest.raises(storage.StorageError, match='below min_free_bytes'):
        policy.prepare()
    assert fs.created == fs.probes == []
    state = policy.status()['directories']['artifacts']
    assert state['mount_ready']
    assert state['free_bytes'] == 999
    assert state['min_free_bytes'] == 1000
    fs.free = 1000
    policy.prepare()


def test_existing_nonprivate_application_is_rejected_without_chmod(configured):
    policy, fs, _ = configured
    policy.artifact_root.mkdir(parents=True)
    policy.artifact_root.chmod(0o755)
    with pytest.raises(storage.StorageError, match='mode 0700'):
        policy.prepare()
    assert stat.S_IMODE(policy.artifact_root.stat().st_mode) == 0o755
    assert fs.created == fs.probes == []


def test_failed_writeability_probe_is_sanitized_and_does_not_fallback(configured):
    policy, fs, _ = configured
    fs.fail_probe = True
    with pytest.raises(storage.StorageError, match='writeability probe failed') as error:
        policy.prepare()
    assert 'sensitive' not in str(error.value)
    assert not (policy.root / 'logs/harness/workflows').exists()
    assert policy.artifact_root.exists()
    assert list(policy.artifact_root.iterdir()) == []
    assert policy.status(probe=True)['status'] == 'failed'


def test_directory_creation_error_is_sanitized_without_fallback(configured, monkeypatch):
    policy, fs, _ = configured

    def fail_creation(path):
        raise PermissionError('PRIVATE-FILESYSTEM-MESSAGE')

    monkeypatch.setattr(fs, 'create_directory', fail_creation)
    with pytest.raises(storage.StorageError, match='Cannot create private') as error:
        policy.prepare()
    assert 'PRIVATE-FILESYSTEM-MESSAGE' not in str(error.value)
    assert not policy.artifact_root.exists()
    assert not (policy.root / 'logs/harness/workflows').exists()


def test_free_space_error_is_sanitized_before_any_write(configured, monkeypatch):
    policy, fs, _ = configured

    def fail_free_bytes(path):
        raise OSError('PRIVATE-MOUNT-MESSAGE')

    monkeypatch.setattr(fs, 'free_bytes', fail_free_bytes)
    with pytest.raises(storage.StorageError, match='mount/free-space check failed') as error:
        policy.prepare()
    assert 'PRIVATE-MOUNT-MESSAGE' not in str(error.value)
    assert fs.created == fs.probes == []
    assert policy.status()['status'] == 'failed'


def test_readonly_status_and_doctor_probe_never_create_application_roots(configured):
    policy, fs, _ = configured
    assert policy.status()['status'] == 'ready'
    assert not policy.status()['directories']['artifacts']['private_directory']
    assert policy.status(probe=True)['status'] == 'failed'
    assert fs.created == fs.probes == []


def test_readonly_status_reports_probe_success_for_existing_private_roots(configured):
    policy, fs, _ = configured
    policy.prepare(probe=False)
    fs.created.clear()
    result = policy.status(probe=True)
    assert result['status'] == 'ready'
    assert all(item['probe'] == 'passed' for item in result['directories'].values())
    assert fs.created == []


def test_nested_mount_cannot_satisfy_different_required_mount(configured):
    policy, fs, _ = configured
    nested = policy.artifact_root.parent
    nested.mkdir()
    fs.mounts.add(nested)
    with pytest.raises(storage.StorageError, match='different mount'):
        policy.prepare()
    assert fs.created == fs.probes == []


@pytest.mark.parametrize('location', ['application-descendant', 'mount-sibling'])
def test_output_nested_mount_is_rejected_before_any_write(configured, location):
    policy, fs, _ = configured
    policy.prepare(probe=False)
    mount = next(iter(fs.mounts))
    nested = (policy.artifact_root / 'nested' if location == 'application-descendant'
              else mount / 'explicit-nested')
    nested.mkdir(mode=0o700)
    fs.mounts.add(nested)
    fs.created.clear()
    output = nested / 'reports'
    for operation in (lambda: policy.report_dir(explicit=output),
                      lambda: policy.ensure_directory(output)):
        with pytest.raises(storage.StorageError, match='different mount'):
            operation()
    assert fs.created == fs.probes == []
    assert not output.exists()


def test_mount_appearing_between_selection_and_creation_is_rechecked(configured, monkeypatch):
    policy, fs, _ = configured
    policy.prepare(probe=False)
    nested = policy.artifact_root / 'nested'
    nested.mkdir(mode=0o700)
    output = policy.report_dir(explicit=nested / 'reports')
    prepare = policy.prepare

    def prepare_then_mount(*, probe=True):
        prepare(probe=False)
        fs.mounts.add(nested)

    monkeypatch.setattr(policy, 'prepare', prepare_then_mount)
    fs.created.clear()
    with pytest.raises(storage.StorageError, match='different mount'):
        policy.ensure_directory(output)
    assert output not in fs.created
    assert not output.exists()
    assert fs.probes == []


def test_mount_inside_run_cannot_redirect_journal_reads(configured):
    policy, fs, _ = configured
    run = make_run(policy.workflow_root())
    records = run / 'records'
    records.mkdir(mode=0o700)
    fs.mounts.add(records)
    with pytest.raises(storage.StorageError, match='different mount'):
        policy.record_path(run, 'records/github.json')
    fs.mounts.remove(records)
    fs.mounts.add(run)
    with pytest.raises(storage.StorageError, match='different mount'):
        policy.find_run(run.name)
    with pytest.raises(storage.StorageError, match='different mount'):
        policy.latest_run()
    assert fs.created == fs.probes == []


def test_legacy_lookup_retains_absolute_workspace_and_journal_bytes(configured):
    policy, fs, _ = configured
    legacy = make_run(policy.root / 'logs/harness/workflows')
    journal = legacy / 'github.json'
    original = b'{"workspace":"/old/absolute/workspace","approved":"immutable"}\n'
    journal.write_bytes(original)
    journal.chmod(0o600)
    assert policy.find_run(legacy.name) == legacy
    assert policy.record_path(legacy, 'github.json') == journal
    assert policy.latest_run() == legacy
    assert journal.read_bytes() == original
    assert fs.created == fs.probes == []


def test_legacy_mount_contract_is_independent_of_external_application(configured):
    policy, fs, data = configured
    # / is a valid required mount for configured local storage, while the
    # project and its legacy journals may live on a separate mounted volume.
    for spec in data.values():
        if isinstance(spec, dict):
            spec['required_mount'] = '/'
    save_config(policy.root, data)
    fs.mounts = {Path('/'), policy.root}
    policy = storage.resolve_storage(policy.root, env={}, fs=fs)
    legacy = make_run(policy.root / 'logs/harness/workflows')
    assert policy.find_run(legacy.name) == legacy
    assert policy.record_path(legacy, 'github.json') == legacy / 'github.json'
    assert policy.latest_run() == legacy
    assert policy.project_lock_path == legacy.parent / '.lock'
    assert fs.created == fs.probes == []


def test_new_and_legacy_runs_share_one_local_project_lock(configured, tmp_path):
    policy, _, _ = configured
    legacy_root = policy.root / 'logs/harness/workflows'
    new_root = policy.workflow_root()
    old = make_run(legacy_root)
    new = make_run(new_root, '200-abcdef', time_ns=2000)
    assert policy.find_run(old.name) == old
    assert policy.find_run(new.name) == new
    assert policy.project_lock_path == legacy_root / '.lock'
    assert policy.record_path(old, 'github.lock') == old / 'github.lock'
    assert policy.record_path(new, 'github.lock') == new / 'github.lock'
    policy.env[storage.REPORT_ENV] = str(tmp_path / 'override')
    assert policy.project_lock_path == legacy_root / '.lock'
    assert policy.find_run(new.name) == new
    default = storage.resolve_storage(policy.root, env={storage.CONFIG_ENV: str(policy.config_path)}, fs=policy.fs)
    assert default.project_lock_path == policy.project_lock_path


def test_duplicate_ids_are_ambiguous_even_with_latest_pointer(configured):
    policy, _, _ = configured
    old = make_run(policy.root / 'logs/harness/workflows')
    make_run(policy.workflow_root(), old.name)
    (old.parent / 'latest.json').write_text(json.dumps({'run_id': old.name}))
    for operation in (lambda: policy.find_run(old.name), policy.latest_run):
        with pytest.raises(storage.StorageError, match='Ambiguous workflow run ID'):
            operation()
    with pytest.raises(storage.StorageError, match='Ambiguous workflow run ID'):
        policy.record_path(old, 'github.json')


def test_latest_covers_both_roots_and_does_not_rewrite_pointers(configured):
    policy, _, _ = configured
    old = make_run(policy.root / 'logs/harness/workflows', time_ns=1000)
    new = make_run(policy.workflow_root(), '200-abcdef', time_ns=2000)
    assert policy.latest_run() == new
    marker = old.parent / 'latest.json'
    marker.write_text(json.dumps({'run_id': old.name}))
    original = marker.read_bytes()
    os.utime(marker, ns=(3000, 3000))
    assert policy.latest_run() == old
    assert marker.read_bytes() == original


@pytest.mark.parametrize('run_id', ['../escape', 'x', '/100-abcdef', '100-abcdef/elsewhere', None])
def test_invalid_run_ids_are_rejected_without_creation(project, run_id):
    policy = storage.resolve_storage(project, env={})
    with pytest.raises(storage.StorageError, match='Invalid workflow run ID'):
        policy.find_run(run_id)
    assert not (project / 'logs').exists()


@pytest.mark.parametrize('where', ['legacy', 'new'])
def test_symlinked_run_is_rejected_in_both_roots(configured, tmp_path, where):
    policy, _, _ = configured
    policy.prepare(probe=False)
    root = policy.root / 'logs/harness/workflows' if where == 'legacy' else policy.workflow_root()
    root.mkdir(parents=True, mode=0o700)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (root / '100-abcdef').symlink_to(outside, target_is_directory=True)
    with pytest.raises(storage.StorageError, match='symlink'):
        policy.find_run('100-abcdef')
    with pytest.raises(storage.StorageError, match='symlink'):
        policy.latest_run()


def test_symlinked_legacy_root_cannot_escape_under_new_config(configured, tmp_path):
    policy, _, _ = configured
    outside = tmp_path / 'outside'
    outside.mkdir()
    (policy.root / 'logs/harness/workflows').symlink_to(outside, target_is_directory=True)
    with pytest.raises(storage.StorageError, match='symlink'):
        policy.workflow_roots()


def test_selected_root_and_record_containment_are_checked(configured, tmp_path):
    policy, _, _ = configured
    run = make_run(policy.root / 'logs/harness/workflows')
    outside = make_run(tmp_path / 'unapproved-root', '200-abcdef')
    with pytest.raises(storage.StorageError, match='escapes'):
        policy.validate_run_directory(outside)
    for name in ('../github.json', '/github.json', 'nested/../github.json', './github.json', 'nested//file'):
        with pytest.raises(storage.StorageError, match='Invalid workflow record path'):
            policy.record_path(run, name)
    (run / 'github.json').symlink_to(outside / 'report.json')
    with pytest.raises(storage.StorageError, match='symlink'):
        policy.record_path(run, 'github.json')


def test_latest_pointer_cannot_select_a_different_root(configured):
    policy, _, _ = configured
    old = make_run(policy.root / 'logs/harness/workflows')
    make_run(policy.workflow_root(), '200-abcdef')
    (policy.workflow_root() / 'latest.json').write_text(json.dumps({'run_id': old.name}))
    with pytest.raises(storage.StorageError, match='pointer escapes'):
        policy.latest_run()


def test_missing_lookup_has_useful_error_and_no_creation(project):
    policy = storage.resolve_storage(project, env={})
    with pytest.raises(storage.StorageError, match='not found'):
        policy.find_run('100-abcdef')
    with pytest.raises(storage.StorageError, match='No workflow reports'):
        policy.latest_run()
    assert not (project / 'logs').exists()


def test_cli_status_doctor_and_wrapper_resolution_are_offline(configured, monkeypatch, capsys):
    policy, fs, _ = configured
    monkeypatch.setattr(storage, 'resolve_storage', lambda *a, **kw: policy)
    for command in ('status', 'doctor'):
        assert storage.main([command]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result['artifact_root'] == str(policy.artifact_root)
        assert result['project_lock'] == str(policy.project_lock_path)
    assert fs.created == fs.probes == []
    assert storage.main(['resolve', 'reports', '--category', 'agents', '--prepare']) == 0
    assert capsys.readouterr().out.strip() == str(policy.artifact_root / 'agents')
    assert stat.S_IMODE((policy.artifact_root / 'agents').stat().st_mode) == 0o700
    fs.created.clear()
    fs.probes.clear()
    fs.mounts.clear()
    assert storage.main(['resolve', 'reports', '--prepare']) == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'required mount is absent' in json.loads(captured.err)['error']
    assert fs.created == fs.probes == []


@pytest.mark.parametrize('option', ['--root', '--report-dir'])
@pytest.mark.parametrize('suffix', ['/./output', '//output', '/output/'])
def test_cli_validates_raw_path_spelling(project, monkeypatch, capsys, option, suffix):
    # An explicit project root and empty environment isolate this CLI test from
    # the repository's private configuration and inherited mount selections.
    resolve = storage.resolve_storage
    monkeypatch.setattr(storage, 'resolve_storage',
                        lambda root=None: resolve(root or project, env={}))
    value = str(project) + suffix
    command = ['status', option, value] if option == '--root' else [
        'resolve', 'reports', option, value, '--prepare']
    assert storage.main(command) == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'absolute normalized path' in json.loads(captured.err)['error']
    assert not (project / 'output').exists()
    assert not (project / 'logs').exists()


def _observe_cleanup(monkeypatch, before=None):
    """Record destructive operations only after the caller finishes allocation."""
    operations = []
    for action in ('unlink', 'rmdir', 'fchmod'):
        original = getattr(os, action)

        def observe(name, *args, _action=action, _original=original, **kwargs):
            if before is not None:
                before(_action, name, kwargs)
            operations.append((_action, name))
            return _original(name, *args, **kwargs)

        monkeypatch.setattr(os, action, observe)
    return operations


def _identity(info):
    return info.st_dev, info.st_ino


def _changed_stat(info, **changes):
    return SimpleNamespace(st_dev=changes.get('st_dev', info.st_dev),
                           st_ino=changes.get('st_ino', info.st_ino),
                           st_uid=changes.get('st_uid', info.st_uid),
                           st_mode=changes.get('st_mode', info.st_mode))


@pytest.mark.parametrize('nested', [False, True], ids=['flat', 'nested'])
@pytest.mark.parametrize('file_count', [1, 64, 256])
def test_cleanup_readiness_is_bounded_with_fresh_per_operation_proofs(
        configured, tmp_path, monkeypatch, nested, file_count):
    policy, fs, data = configured
    # Keep artifact readiness separate, as on the unrelated configured NFS mount.
    artifact_mount = tmp_path / 'artifact-mount'
    artifact_mount.mkdir()
    fs.mounts.add(artifact_mount)
    data['artifacts'].update(path=str(artifact_mount / 'artifacts'),
                             required_mount=str(artifact_mount))
    save_config(policy.root, data)
    policy = storage.resolve_storage(policy.root, env={}, fs=fs)
    with policy.temporary_directory() as root:
        directories = [root]
        if nested:
            for level in range(4):
                child = directories[-1] / ('level-' + str(level))
                child.mkdir(mode=0o700)
                directories.append(child)
        directory_proofs = {}
        parent_keys = {}
        for directory in directories:
            key = _identity(directory.stat())
            parent_key = _identity(directory.parent.stat())
            directory_proofs[key] = (parent_key, directory.name)
            parent_keys[key] = parent_key
        for index in range(file_count):
            file = directories[index % len(directories)] / ('file-' + str(index))
            file.write_text('fixture')
            file.chmod(0o400)
        for directory in directories:
            directory.chmod(0o500)
        root_key = _identity(root.stat())
        root_parent = _identity(root.parent.stat())
        fs.mount_queries.clear()
        fs.space_queries.clear()
        fs.identity_queries.clear()
        fs.open_queries.clear()
        cursors = [0, 0]

        def prove_each_operation(action, name, kwargs):
            recent = {(owner, entry) for owner, entry, _ in
                      fs.identity_queries[cursors[0]:]}
            assert root.parent in fs.open_queries[cursors[1]:]
            assert (root_parent, '') in recent
            assert directory_proofs[root_key] in recent
            if action == 'fchmod':
                info = os.fstat(name)
                assert stat.S_ISDIR(info.st_mode)
                assert info.st_uid == os.geteuid()
                key = _identity(info)
                assert (key, '') in recent  # pinned directory mount proof
                assert directory_proofs[key] in recent
            else:
                key = _identity(os.fstat(kwargs['dir_fd']))
                assert (key, name) in recent  # no-follow target mount proof
            while key in directory_proofs:
                assert directory_proofs[key] in recent
                key = parent_keys[key]
            cursors[:] = [len(fs.identity_queries), len(fs.open_queries)]

        operations = _observe_cleanup(monkeypatch, prove_each_operation)
    assert not root.exists()
    assert [action for action, _ in operations].count('unlink') == file_count
    assert [action for action, _ in operations].count('rmdir') == len(directories)
    assert [action for action, _ in operations].count('fchmod') == len(directories)
    # Exactly two readiness boundaries, each querying both floors/mounts.
    assert len(fs.space_queries) == 4
    for mount in fs.mounts:
        assert fs.space_queries.count(mount) == 2
        assert fs.mount_queries.count(mount) == 2
    assert len(fs.identity_queries) >= file_count * 3
    assert fs.open_queries.count(root.parent) >= len(operations)


@pytest.mark.parametrize('invalid', ['mount', 'floor', 'inspection-error'])
def test_new_cleanup_never_reuses_previous_readiness(configured, monkeypatch, invalid):
    policy, fs, _ = configured
    with policy.temporary_directory() as previous:
        (previous / 'first').write_text('fixture')
    assert not previous.exists()
    with pytest.raises(storage.StorageError):
        with policy.temporary_directory() as root:
            (root / 'retained').write_text('fixture')
            root.chmod(0o500)
            operations = _observe_cleanup(monkeypatch)
            if invalid == 'mount':
                fs.mounts.clear()
            elif invalid == 'floor':
                fs.free = 999
            else:
                def fail_space(path):
                    raise OSError('PRIVATE-READINESS-DIAGNOSTIC')
                monkeypatch.setattr(fs, 'free_bytes', fail_space)
    assert operations == []
    assert root.exists()
    assert (root / 'retained').read_text() == 'fixture'
    assert stat.S_IMODE(root.stat().st_mode) == 0o500


@pytest.mark.parametrize('invalid', ['mount', 'floor', 'inspection-error'])
def test_final_cleanup_readiness_failure_retains_root(configured, monkeypatch, invalid):
    policy, fs, _ = configured
    with pytest.raises(storage.StorageError):
        with policy.temporary_directory() as root:
            child = root / 'child'
            child.mkdir()
            (child / 'fixture').write_text('fixture')
            unlink = os.unlink

            def unlink_then_invalidate(name, *args, **kwargs):
                result = unlink(name, *args, **kwargs)
                if invalid == 'mount':
                    fs.mounts.clear()
                elif invalid == 'floor':
                    fs.free = 999
                else:
                    def fail_space(path):
                        raise OSError('PRIVATE-READINESS-DIAGNOSTIC')
                    monkeypatch.setattr(fs, 'free_bytes', fail_space)
                return result

            monkeypatch.setattr(os, 'unlink', unlink_then_invalidate)
            operations = _observe_cleanup(monkeypatch)
    assert root.is_dir()
    assert list(root.iterdir()) == []
    assert ('rmdir', 'child') in operations
    assert ('rmdir', root.name) not in operations


@pytest.mark.parametrize('purpose', ['context', 'validation'])
def test_owned_cleanup_handles_readonly_tree_links_and_preserves_unrelated_data(
        configured, tmp_path, monkeypatch, purpose):
    policy, _, _ = configured
    external = tmp_path / 'external'
    external.mkdir()
    target = external / 'target'
    target.write_bytes(b'external bytes')
    target.chmod(0o400)
    with policy.temporary_directory(purpose=purpose) as root:
        sibling = root.parent / 'unrelated'
        sibling.mkdir(mode=0o700)
        (sibling / 'preserve').write_text('user data')
        child = root / 'readonly-directory'
        child.mkdir()
        file = child / 'readonly-file'
        file.write_bytes(b'disposable')
        file.chmod(0o400)
        (child / 'file-link').symlink_to(target)
        (child / 'directory-link').symlink_to(external, target_is_directory=True)
        (child / 'dangling-link').symlink_to(external / 'absent')
        os.link(target, child / 'hardlink')
        child.chmod(0o500)
        root.chmod(0o500)
        chmod_targets = []
        fchmod = os.fchmod

        def directory_chmod_only(fd, mode):
            info = os.fstat(fd)
            assert stat.S_ISDIR(info.st_mode)
            chmod_targets.append(_identity(info))
            return fchmod(fd, mode)

        monkeypatch.setattr(os, 'fchmod', directory_chmod_only)
    assert not root.exists()
    assert len(chmod_targets) == 2
    assert target.read_bytes() == b'external bytes'
    assert stat.S_IMODE(target.stat().st_mode) == 0o400
    assert list(external.iterdir()) == [target]
    assert (sibling / 'preserve').read_text() == 'user data'


def test_owned_cleanup_preserves_body_exception_after_removal(configured):
    policy, _, _ = configured
    failure = RuntimeError('body failure')
    with pytest.raises(RuntimeError) as error:
        with policy.temporary_directory() as root:
            (root / 'fixture').write_text('fixture')
            root.chmod(0o500)
            raise failure
    assert error.value is failure
    assert not root.exists()


@pytest.mark.parametrize('operation', ['unlink', 'rmdir', 'fchmod', 'listdir', 'open'])
def test_owned_cleanup_os_errors_are_sanitized_without_fallback(
        configured, monkeypatch, operation):
    policy, _, _ = configured
    with pytest.raises(storage.StorageError, match='Cannot safely remove') as error:
        with policy.temporary_directory() as root:
            child = root / 'child'
            child.mkdir()
            (child / 'fixture').write_text('fixture')
            root.chmod(0o500)
            original = getattr(os, operation)

            def fail(*args, **kwargs):
                # Leave fresh parent traversal working; fail opening this child.
                if operation == 'open' and args[0] != 'child':
                    return original(*args, **kwargs)
                raise PermissionError('PRIVATE-CLEANUP-DIAGNOSTIC')

            monkeypatch.setattr(os, operation, fail)
    assert 'PRIVATE-CLEANUP-DIAGNOSTIC' not in str(error.value)
    assert root.exists()
    assert not (policy.root / 'logs/harness/workflows').exists()


def test_cleanup_failure_does_not_hide_body_exception(configured, monkeypatch):
    policy, _, _ = configured
    failure = RuntimeError('body failure')
    with pytest.raises(storage.StorageError) as error:
        with policy.temporary_directory() as root:
            (root / 'fixture').write_text('fixture')

            def fail_unlink(*args, **kwargs):
                raise PermissionError('PRIVATE-CLEANUP-DIAGNOSTIC')

            monkeypatch.setattr(os, 'unlink', fail_unlink)
            raise failure
    assert error.value.__context__.__context__ is failure
    assert root.exists()


def test_cleanup_rejects_replacement_between_allocation_and_pin(configured, monkeypatch):
    policy, _, _ = configured
    allocate = policy._allocate_temporary
    allocated_paths = []

    def allocate_then_replace(**kwargs):
        path, identity = allocate(**kwargs)
        retained = path.with_name(path.name + '-retained')
        path.rename(retained)
        path.mkdir(mode=0o700)
        (path / 'replacement').write_text('user data')
        allocated_paths.extend([path, retained])
        return path, identity

    monkeypatch.setattr(policy, '_allocate_temporary', allocate_then_replace)
    with pytest.raises(storage.StorageError, match='directory identity changed'):
        with policy.temporary_directory():
            pytest.fail('replacement must fail before yielding')
    path, retained = allocated_paths
    assert path.exists() and retained.exists()
    assert (path / 'replacement').read_text() == 'user data'


def test_local_cleanup_preserves_shared_parent_owner(project, tmp_path, monkeypatch):
    fs = FakeFS()
    policy = storage.resolve_storage(project, env={}, fs=fs)
    parent_info = tmp_path.stat()
    parent_key = _identity(parent_info)
    real_stat = os.stat
    real_fstat = os.fstat

    def shared_parent_stat(*args, **kwargs):
        info = real_stat(*args, **kwargs)
        return (_changed_stat(info, st_uid=os.geteuid() + 1)
                if _identity(info) == parent_key else info)

    def shared_parent_fstat(fd):
        info = real_fstat(fd)
        return (_changed_stat(info, st_uid=os.geteuid() + 1)
                if _identity(info) == parent_key else info)

    def local_mkdtemp(*, prefix, dir):
        assert dir is None
        path = tmp_path / 'local-validation'
        path.mkdir(mode=0o700)
        return str(path)

    monkeypatch.setattr(storage.tempfile, 'mkdtemp', local_mkdtemp)
    monkeypatch.setattr(os, 'stat', shared_parent_stat)
    monkeypatch.setattr(os, 'fstat', shared_parent_fstat)
    with policy.temporary_directory() as root:
        (root / 'fixture').write_text('fixture')
        root_key = _identity(os.stat(root))
        root.chmod(0o500)

        def prove_parent_is_untouched(action, name, kwargs):
            if action == 'fchmod':
                assert _identity(os.fstat(name)) == root_key

        operations = _observe_cleanup(monkeypatch, prove_parent_is_untouched)
    assert not root.exists()
    # Some pathlib versions retain the original os.stat in their accessor;
    # observe synthetic ownership through the explicitly patched OS seam.
    assert os.stat(tmp_path).st_uid == os.geteuid() + 1
    assert real_stat(tmp_path).st_uid == parent_info.st_uid
    assert stat.S_IMODE(real_stat(tmp_path).st_mode) == stat.S_IMODE(parent_info.st_mode)
    assert [action for action, _ in operations] == ['fchmod', 'unlink', 'rmdir']
    assert fs.space_queries == []


@pytest.mark.parametrize('replacement', ['directory', 'symlink'])
def test_cleanup_rejects_child_replacement_during_no_follow_open(
        configured, tmp_path, monkeypatch, replacement):
    policy, _, _ = configured
    outside = tmp_path / 'external'
    outside.mkdir()
    (outside / 'preserve').write_text('external')
    with pytest.raises(storage.StorageError):
        with policy.temporary_directory() as root:
            child = root / 'child'
            child.mkdir()
            (child / 'fixture').write_text('retained')
            retained = root / 'retained-child'
            open_directory = os.open

            def replace_then_open(name, flags, *args, **kwargs):
                if name == 'child' and 'dir_fd' in kwargs:
                    assert flags & os.O_NOFOLLOW
                    assert flags & os.O_DIRECTORY
                    child.rename(retained)
                    if replacement == 'directory':
                        child.mkdir(mode=0o700)
                        (child / 'replacement').write_text('user data')
                    else:
                        child.symlink_to(outside, target_is_directory=True)
                return open_directory(name, flags, *args, **kwargs)

            monkeypatch.setattr(os, 'open', replace_then_open)
            operations = _observe_cleanup(monkeypatch)
    assert operations == []
    assert (retained / 'fixture').read_text() == 'retained'
    assert (outside / 'preserve').read_text() == 'external'
    if replacement == 'directory':
        assert (child / 'replacement').read_text() == 'user data'
    else:
        assert child.is_symlink()


def test_cleanup_reproves_root_after_final_readiness(configured, monkeypatch):
    policy, _, _ = configured
    with pytest.raises(storage.StorageError, match='identity changed'):
        with policy.temporary_directory() as root:
            (root / 'fixture').write_text('fixture')
            retained = root.with_name(root.name + '-retained')
            check_ready = policy.check_ready
            boundaries = []

            def ready_then_replace_root():
                result = check_ready()
                boundaries.append(True)
                if len(boundaries) == 2:
                    root.rename(retained)
                    root.mkdir(mode=0o700)
                    (root / 'replacement').write_text('user data')
                return result

            monkeypatch.setattr(policy, 'check_ready', ready_then_replace_root)
            operations = _observe_cleanup(monkeypatch)
    assert len(boundaries) == 2
    assert [action for action, _ in operations] == ['unlink']
    assert retained.is_dir()
    assert (root / 'replacement').read_text() == 'user data'


@pytest.mark.parametrize('replacement', ['directory', 'symlink'])
def test_cleanup_rejects_replaced_root_without_destructive_operations(
        configured, tmp_path, monkeypatch, replacement):
    policy, _, _ = configured
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'preserve').write_text('external')
    with pytest.raises(storage.StorageError, match='directory identity changed'):
        with policy.temporary_directory() as root:
            (root / 'fixture').write_text('retained')
            retained = root.with_name(root.name + '-retained')
            root.rename(retained)
            if replacement == 'directory':
                root.mkdir(mode=0o700)
                (root / 'replacement').write_text('user data')
            else:
                root.symlink_to(outside, target_is_directory=True)
            operations = _observe_cleanup(monkeypatch)
    assert operations == []
    assert (retained / 'fixture').read_text() == 'retained'
    assert (outside / 'preserve').read_text() == 'external'
    if replacement == 'directory':
        assert (root / 'replacement').read_text() == 'user data'
    else:
        assert root.is_symlink()


@pytest.mark.parametrize('replacement', ['directory', 'symlink'])
def test_cleanup_rejects_replaced_parent_without_destructive_operations(
        configured, tmp_path, monkeypatch, replacement):
    policy, _, _ = configured
    outside = tmp_path / 'outside'
    outside.mkdir(mode=0o700)
    with pytest.raises(storage.StorageError):
        with policy.temporary_directory() as root:
            (root / 'fixture').write_text('retained')
            parent = root.parent
            retained = parent.with_name(parent.name + '-retained')
            parent.rename(retained)
            if replacement == 'directory':
                parent.mkdir(mode=0o700)
                (parent / 'preserve').write_text('user data')
            else:
                parent.symlink_to(outside, target_is_directory=True)
            operations = _observe_cleanup(monkeypatch)
    assert operations == []
    assert (retained / root.name / 'fixture').read_text() == 'retained'
    assert list(outside.iterdir()) == []
    if replacement == 'directory':
        assert (parent / 'preserve').read_text() == 'user data'


@pytest.mark.parametrize('location', ['root', 'parent', 'directory', 'file'])
def test_cleanup_rejects_foreign_owned_entries_before_chmod_or_removal(
        configured, monkeypatch, location):
    policy, _, _ = configured
    with pytest.raises(storage.StorageError, match='foreign-owned|Application directory'):
        with policy.temporary_directory() as root:
            child = root / 'child'
            child.mkdir()
            file = child / 'fixture'
            file.write_text('retained')
            child.chmod(0o500)
            target = {'root': root, 'parent': root.parent,
                      'directory': child, 'file': file}[location]
            foreign = _identity(target.stat())
            real_stat = os.stat
            real_fstat = os.fstat

            def foreign_stat(*args, **kwargs):
                info = real_stat(*args, **kwargs)
                return (_changed_stat(info, st_uid=os.geteuid() + 1)
                        if _identity(info) == foreign else info)

            def foreign_fstat(fd):
                info = real_fstat(fd)
                return (_changed_stat(info, st_uid=os.geteuid() + 1)
                        if _identity(info) == foreign else info)

            monkeypatch.setattr(os, 'stat', foreign_stat)
            monkeypatch.setattr(os, 'fstat', foreign_fstat)
            operations = _observe_cleanup(monkeypatch)
    # A foreign file is found only after regaining access to its owned parent.
    assert all(action == 'fchmod' for action, _ in operations)
    assert len(operations) == (1 if location == 'file' else 0)
    assert file.read_text() == 'retained'


@pytest.mark.parametrize('location', ['root', 'parent', 'directory', 'file'])
@pytest.mark.parametrize('boundary', ['mount', 'same-device-bind', 'device'])
def test_cleanup_rejects_mount_boundaries_before_target_mutation(
        configured, monkeypatch, location, boundary):
    policy, fs, _ = configured
    with pytest.raises(storage.StorageError, match='mount boundaries|identity changed|different mount'):
        with policy.temporary_directory() as root:
            child = root / 'child'
            child.mkdir()
            file = child / 'fixture'
            file.write_text('retained')
            target = {'root': root, 'parent': root.parent,
                      'directory': child, 'file': file}[location]
            target_key = _identity(target.stat())
            if boundary == 'mount':
                fs.mounts.add(target)
            elif boundary == 'same-device-bind':
                # ismount is intentionally false and st_dev stays unchanged.
                fs.mount_ids[target_key] = 2
            else:
                real_stat = os.stat
                real_fstat = os.fstat

                def other_device_stat(*args, **kwargs):
                    info = real_stat(*args, **kwargs)
                    return (_changed_stat(info, st_dev=info.st_dev + 1)
                            if _identity(info) == target_key else info)

                def other_device_fstat(fd):
                    info = real_fstat(fd)
                    return (_changed_stat(info, st_dev=info.st_dev + 1)
                            if _identity(info) == target_key else info)

                monkeypatch.setattr(os, 'stat', other_device_stat)
                monkeypatch.setattr(os, 'fstat', other_device_fstat)
            operations = _observe_cleanup(monkeypatch)
    assert operations == []
    assert file.read_text() == 'retained'


@pytest.mark.parametrize('changed', ['root', 'parent', 'ancestor'])
def test_cleanup_rechecks_attachment_after_each_file_operation(
        configured, monkeypatch, changed):
    policy, _, _ = configured
    with pytest.raises(storage.StorageError, match='identity changed'):
        with policy.temporary_directory() as root:
            child = root / 'child'
            child.mkdir()
            (child / 'first').write_text('fixture')
            (child / 'second').write_text('fixture')
            target = {'root': root, 'parent': root.parent, 'ancestor': child}[changed]
            retained = target.with_name(target.name + '-retained')
            unlink = os.unlink
            removed = []

            def unlink_then_replace(name, *args, **kwargs):
                result = unlink(name, *args, **kwargs)
                removed.append(name)
                if len(removed) == 1:
                    target.rename(retained)
                    target.mkdir(mode=0o700)
                    (target / 'replacement').write_text('user data')
                return result

            monkeypatch.setattr(os, 'unlink', unlink_then_replace)
            operations = _observe_cleanup(monkeypatch)
    assert len(removed) == 1
    assert [action for action, _ in operations] == ['unlink']
    assert (target / 'replacement').read_text() == 'user data'
    original_child = (retained if changed == 'ancestor' else retained / 'child'
                      if changed == 'root' else retained / root.name / 'child')
    assert len(list(original_child.iterdir())) == 1


@pytest.mark.parametrize('change', ['foreign-owner', 'bind-mount'])
def test_cleanup_rechecks_parent_proof_after_each_file_operation(
        configured, monkeypatch, change):
    policy, fs, _ = configured
    with pytest.raises(storage.StorageError, match='foreign-owned|mount boundaries'):
        with policy.temporary_directory() as root:
            (root / 'first').write_text('fixture')
            (root / 'second').write_text('fixture')
            parent_key = _identity(root.parent.stat())
            unlink = os.unlink
            real_fstat = os.fstat
            removed = []

            def changed_parent_fstat(fd):
                info = real_fstat(fd)
                return (_changed_stat(info, st_uid=os.geteuid() + 1)
                        if removed and _identity(info) == parent_key else info)

            def unlink_then_change(name, *args, **kwargs):
                result = unlink(name, *args, **kwargs)
                removed.append(name)
                if change == 'bind-mount':
                    fs.mount_ids[parent_key] = 2
                return result

            if change == 'foreign-owner':
                monkeypatch.setattr(os, 'fstat', changed_parent_fstat)
            monkeypatch.setattr(os, 'unlink', unlink_then_change)
            operations = _observe_cleanup(monkeypatch)
    assert len(removed) == 1
    assert [action for action, _ in operations] == ['unlink']
    assert len(list(root.iterdir())) == 1


@pytest.mark.parametrize('location', ['root', 'ancestor', 'file'])
def test_cleanup_rechecks_mount_identity_after_each_file_operation(
        configured, monkeypatch, location):
    policy, fs, _ = configured
    with pytest.raises(storage.StorageError, match='mount boundaries'):
        with policy.temporary_directory() as root:
            child = root / 'child'
            child.mkdir()
            files = [child / 'first', child / 'second']
            for file in files:
                file.write_text('fixture')
            keys = {file.name: _identity(file.stat()) for file in files}
            unlink = os.unlink
            removed = []

            def unlink_then_mount(name, *args, **kwargs):
                result = unlink(name, *args, **kwargs)
                removed.append(name)
                if location == 'file':
                    remaining = next(key for filename, key in keys.items() if filename != name)
                    fs.mount_ids[remaining] = 2
                else:
                    fs.mount_ids[_identity((root if location == 'root' else child).stat())] = 2
                return result

            monkeypatch.setattr(os, 'unlink', unlink_then_mount)
            operations = _observe_cleanup(monkeypatch)
    assert len(removed) == 1
    assert [action for action, _ in operations] == ['unlink']
    assert len(list(child.iterdir())) == 1


@pytest.mark.parametrize('support', ['no-libc', 'no-symbol', 'syscall-error', 'missing-mask'])
def test_cleanup_unsupported_statx_fails_closed_before_any_mutation(
        configured, monkeypatch, support):
    policy, fs, _ = configured
    with pytest.raises(storage.StorageError, match='kernel mount identity') as error:
        with policy.temporary_directory() as root:
            (root / 'fixture').write_text('retained')
            root.chmod(0o500)

            class UnsupportedStatx:
                def __call__(self, directory, name, flags, mask, result):
                    assert flags == 0x1900
                    assert mask == 0x1000
                    return -1 if support == 'syscall-error' else 0

            def fake_libc(name):
                assert name is None
                if support == 'no-libc':
                    raise OSError('PRIVATE-LIBC-DIAGNOSTIC')
                if support == 'no-symbol':
                    return SimpleNamespace()
                return SimpleNamespace(statx=UnsupportedStatx())

            monkeypatch.setattr(storage.ctypes, 'CDLL', fake_libc)
            monkeypatch.setattr(fs, 'mount_identity', storage.FileSystem().mount_identity)
            operations = _observe_cleanup(monkeypatch)
    assert operations == []
    assert 'PRIVATE-LIBC-DIAGNOSTIC' not in str(error.value)
    assert (root / 'fixture').read_text() == 'retained'
    assert stat.S_IMODE(root.stat().st_mode) == 0o500


@pytest.mark.parametrize('name', ['', 'entry', 'symlink'])
def test_kernel_mount_identity_uses_fixed_abi_and_no_follow_flags(monkeypatch, name):
    calls = []

    class Statx:
        def __call__(self, directory, entry, flags, mask, result):
            calls.append((directory, entry, flags, mask))
            info = storage.ctypes.cast(result, storage.ctypes.POINTER(storage._Statx)).contents
            info.mask = 0x1000
            info.mount_id = 987654321
            return 0

    statx = Statx()
    monkeypatch.setattr(storage.ctypes, 'CDLL', lambda library: SimpleNamespace(statx=statx))
    assert storage.ctypes.sizeof(storage._Statx) == 256
    assert storage._Statx.mount_id.offset == 144
    assert storage.FileSystem().mount_identity(123, name) == 987654321
    assert calls == [(123, os.fsencode(name), 0x1900, 0x1000)]
    assert statx.restype is storage.ctypes.c_int


@pytest.mark.parametrize('prefix', ['/escape-', '../escape-', 'nested/escape-', 'bad\n', 'bad\ud800'])
def test_temporary_prefix_cannot_escape_configured_root(configured, prefix):
    policy, fs, _ = configured
    with pytest.raises(storage.StorageError, match='plain filename prefix'):
        policy.mkdtemp(prefix=prefix)
    assert fs.created == fs.probes == []


def test_symlinked_local_lock_cannot_bypass_serialization(project, tmp_path):
    policy = storage.resolve_storage(project, env={})
    lock = project / 'logs/harness/workflows/.lock'
    lock.parent.mkdir(parents=True)
    lock.symlink_to(tmp_path / 'unrelated-lock')
    with pytest.raises(storage.StorageError, match='symlink'):
        _ = policy.project_lock_path


def test_report_override_cannot_be_mount_root_or_use_symlink(configured, tmp_path):
    policy, fs, _ = configured
    mount = next(iter(fs.mounts))
    with pytest.raises(storage.StorageError, match='mount root'):
        policy.report_dir(explicit=mount)
    link = tmp_path / 'unsafe-report-root'
    link.symlink_to(mount)
    with pytest.raises(storage.StorageError, match='symlink'):
        policy.report_dir(explicit=link)
    assert fs.created == fs.probes == []


def test_existing_report_override_is_not_chmodded(configured, tmp_path):
    policy, _, _ = configured
    reports = tmp_path / 'unrelated-existing-reports'
    reports.mkdir()
    reports.chmod(0o755)
    sentinel = reports / 'existing-user-file'
    sentinel.write_text('preserved')
    with pytest.raises(storage.StorageError, match='mode 0700'):
        policy.ensure_directory(reports)
    assert stat.S_IMODE(reports.stat().st_mode) == 0o755
    assert sentinel.read_text() == 'preserved'
