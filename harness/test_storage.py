"""Offline storage regressions: fake mounts, real disposable private files only."""

import json
import os
from pathlib import Path
import stat

import pytest

from harness import storage


class FakeFS(storage.FileSystem):
    def __init__(self, mounts=(), free=10000):
        self.mounts = set(mounts)
        self.free = free
        self.created = []
        self.probes = []
        self.fail_probe = False

    def mount_ready(self, path):
        return path in self.mounts

    def free_bytes(self, path):
        return self.free

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
