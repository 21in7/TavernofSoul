"""A2c fixtures are owned here; no host connector, config, archive or DB.

The orchestrator runs these tests. Git commands below only address disposable
repositories; canonical origin validation still runs before the fixture routes
the transport to its local bare repository.
"""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest

from harness import archive, git_cleanup as cleanup, git_publish as native
from harness import parent_commands as parent, worktree_park as park


RUN = '20261105000000-a2c001'
REPO = '21in7/TavernofSoul'
URL = 'https://api.github.com/repos/' + REPO
PENDING = 'a' * 64


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class LocalFS:
    def lstat(self, path):
        return os.lstat(path)

    def open_directory(self, path):
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def create_directory(self, path):
        Path(path).mkdir(parents=True, exist_ok=True, mode=0o700)


class Selected:
    """Only the storage API used by approved modules, confined to tmp_path."""
    def __init__(self, root, directory):
        self.root, self.directory = root, directory
        self.fs = LocalFS()
        self.project_lock_path = directory.parent / 'source.lock'
        self.version = 2

    def check_ready(self):
        pass

    def validate_run_directory(self, path, **kwargs):
        assert Path(path) == self.directory
        return self.directory

    def record_path(self, directory, name, **kwargs):
        self.validate_run_directory(directory)
        path = directory / name
        assert '..' not in Path(name).parts and not Path(name).is_absolute()
        return path

    def find_run(self, run, **kwargs):
        assert run == RUN
        return self.directory


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    # All exclusion changes are fixture-local and restored by pytest.
    for key in ('TAVERN_WORKFLOW_CHILD', 'READ_ONLY', 'GIT', 'TAVERN_WORKFLOW_DEMO',
                'TAVERN_NO_GIT', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE',
                'GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS', 'GIT_OBJECT_DIRECTORY',
                'GIT_ALTERNATE_OBJECT_DIRECTORIES'):
        monkeypatch.delenv(key, raising=False)
    for key in tuple(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    # A routing regression must fail locally instead of contacting GitHub.
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', 'file')
    root, remote = tmp_path / 'checkout', tmp_path / 'remote.git'
    root.mkdir()
    directory = tmp_path / 'artifacts' / RUN
    directory.mkdir(parents=True, mode=0o700)
    directory.parent.chmod(0o700)

    def git(*args, input=None):
        command = ['git', '-c', 'user.name=A2c fixture', '-c', 'user.email=a2c@example.invalid',
                   '-c', 'core.hooksPath=' + os.devnull, *args]
        return subprocess.run(command, cwd=root, input=input, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip().decode()

    git('init')
    git('symbolic-ref', 'HEAD', 'refs/heads/main')
    source = root / 'sample.txt'
    source.write_bytes(b'before\n')
    source.chmod(0o640)
    git('add', '--', 'sample.txt')
    git('commit', '-m', 'baseline')
    base = git('rev-parse', 'HEAD')
    git('switch', '-c', 'codex/' + RUN)
    source.write_bytes(b'approved after\n')
    source.chmod(0o750)
    git('add', '--', 'sample.txt')
    git('commit', '-m', 'approved head')
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    merge = git('commit-tree', tree, '-p', base, input=b'UI squash\n')
    git('init', '--bare', str(remote))
    git('push', str(remote), merge + ':refs/heads/main', head + ':refs/heads/codex/' + RUN)
    git('switch', 'main')
    source.chmod(0o640)
    git('remote', 'add', 'origin', 'https://github.com/' + REPO + '.git')
    original_git = cleanup.Git
    calls = []

    class FixtureGit(original_git):
        def run(self, *args, **kwargs):
            calls.append(args)
            # No host auth or network: only network-bearing commands are routed.
            if args and (args[0] in ('fetch', 'push', 'ls-remote') or args[:2] == ('remote', 'prune')):
                # origin.url is multivalued: adding a -c value leaves the
                # canonical URL first for fetch. Rewrite that exact URL only
                # for this subprocess; origin validation still reads the real
                # fixture config and the named remote retains its fetch map.
                args = ('-c', 'url.' + str(remote) + '.insteadOf=https://github.com/' + REPO + '.git',
                        *args)
            return super().run(*args, **kwargs)

    monkeypatch.setattr(cleanup, 'Git', FixtureGit)
    monkeypatch.setattr(native, 'ROOT', root)
    monkeypatch.setattr(native, 'REPORTS', directory.parent)
    selected = Selected(root, directory)
    monkeypatch.setattr(native, 'storage_policy', lambda: selected)
    cfg = {'version': 'github-v1', 'enabled': True, 'repository': REPO, 'base': 'main',
           'merge_method': 'squash', 'required_checks': sorted(native.REQUIRED),
           'check_app': 'github-actions', 'wait_seconds': 1800}
    before = {'sha256': digest(b'before\n'), 'mode': 0o640}
    after = {'sha256': digest(b'approved after\n'), 'mode': 0o750}
    approval = {'run_id': RUN, 'config': cfg, 'workspace': str(directory / 'workspace'),
                'max_file_bytes': 4096, 'files': {'sample.txt': {'before': before, 'after': after}}}
    for folder, raw, mode in (('backup', b'before\n', 0o640),
                              ('workspace', b'approved after\n', 0o750)):
        (directory / folder).mkdir(mode=0o700)
        path = directory / folder / 'sample.txt'
        path.write_bytes(raw)
        path.chmod(mode)
    ledger = {'version': 'github-v1', 'run_id': RUN, 'config': cfg, 'branch': 'codex/' + RUN,
              'base_sha': base, 'head_sha': head, 'new_tree': tree, 'pr_number': 123,
              'status': 'awaiting_connector', 'step': 'merge', 'events': [], 'checks': {},
              'pending_request_id': PENDING, 'pending_write': True, 'deadline': 10**12,
              'metadata': {'commit_message': 'fixture', 'pr_title': 'fixture', 'pr_body': 'fixture'},
              'files': {'sample.txt': {
                  'before': {'sha': native.blob_sha(b'before\n'), 'mode': '100644'},
                  'after': {'sha': native.blob_sha(b'approved after\n'), 'mode': '100755',
                            'content': 'approved after\n'}}}}
    report = {'run_id': RUN, 'github_enabled': True, 'changed_files': ['sample.txt'],
              'scope': ['sample.txt'], 'applied': ['sample.txt'], 'workspace': approval['workspace'],
              'status': 'awaiting_github', 'review': {'verdict': 'approved'}}
    for name, value in (('github.json', ledger), ('github-approved.json', approval), ('report.json', report)):
        cleanup.durable_json(directory / name, value)
    pr = {'number': 123, 'merged': True, 'state': 'closed', 'merge_commit_sha': merge,
          'head': {'sha': head, 'ref': ledger['branch'], 'repo': {'full_name': REPO}},
          'base': {'sha': merge, 'ref': 'main', 'repo': {'full_name': REPO}}}
    names = sorted(native.REQUIRED | native.HEAVY_EXECUTION | {native.SELECTION})
    checks = [{'id': i + 1, 'name': name, 'head_sha': head, 'status': 'completed',
               'conclusion': 'success', 'check_suite': {'id': 1}, 'app': {'slug': 'github-actions'}}
              for i, name in enumerate(names)]
    responses = [('/pulls/123', pr),
                 ('/git/commits/' + head, {'sha': head, 'tree': {'sha': tree}, 'parents': [{'sha': base}]}),
                 ('/git/commits/' + merge, {'sha': merge, 'tree': {'sha': tree}, 'parents': [{'sha': base}]}),
                 ('/commits/' + head + '/check-runs?filter=latest&per_page=100&page=1',
                  {'total_count': len(checks), 'check_runs': checks}),
                 ('/commits/' + head + '/status', {'sha': head, 'state': 'success', 'total_count': 0, 'statuses': []}),
                 ('', {'full_name': REPO, 'default_branch': 'main'}),
                 ('/branches?per_page=100&page=1', [{'name': ledger['branch'], 'protected': False,
                                                   'commit': {'sha': head}}]),
                 ('/pulls?state=open&head=21in7%3Acodex%2F' + RUN + '&per_page=100&page=1', [])]
    proof = {'version': 'external-merge-proof-v1', 'run_id': RUN, 'pr_number': 123, 'repository': REPO,
             'base': {'ref': 'main', 'sha': base}, 'head': {'ref': ledger['branch'], 'sha': head},
             'merge_sha': merge, 'responses': [{'method': 'GET', 'url': URL + path, 'status': 200,
                                                'complete': True, 'body': body} for path, body in responses]}
    return SimpleNamespace(root=root, remote=remote, directory=directory, git=git, source=source,
                           selected=selected, ledger=ledger, approval=approval, report=report,
                           proof=proof, calls=calls, merge=merge, head=head, base=base)


def proved(f):
    return native.external_merge_proof(f.ledger, f.proof, 123)


def engine(f):
    return cleanup.Cleanup(f.root, f.directory, proved(f), f.report, f.approval)


def test_saved_gets_use_native_gates_without_mutating_input(isolated):
    f = isolated
    original = copy.deepcopy((f.ledger, f.proof))
    candidate = proved(f)
    assert candidate['step'] == 'cleanup_execute'
    assert candidate['cleanup_proof']['verified'] is True
    assert (f.ledger, f.proof) == original
    assert not (f.directory / 'cleanup.json').exists()


@pytest.mark.parametrize('change,code', [
    ('open', 'external_pr_not_merged'), ('head', 'external_head_mismatch'),
    ('update-branch', 'external_head_mismatch'), ('base', 'external_base_advanced'),
    ('parent', 'external_patch_unproven'), ('tree', 'external_patch_unproven'),
    ('protected', 'external_branch_not_deletable'), ('tip', 'external_branch_not_deletable'),
    ('coverage', 'external_status_coverage_incomplete'), ('error', 'external_get_invalid'),
])
def test_proof_refuses_unsafe_identity_or_incomplete_reads(isolated, change, code):
    f = isolated
    rows = f.proof['responses']
    if change == 'open':
        rows[0]['body'].update(merged=False, state='open')
    elif change in ('head', 'update-branch'):
        rows[0]['body']['head']['sha'] = 'f' * 40
    elif change == 'base':
        rows[0]['body']['base']['sha'] = 'f' * 40
    elif change == 'parent':
        rows[2]['body']['parents'].append({'sha': f.head})
    elif change == 'tree':
        rows[2]['body']['tree']['sha'] = 'f' * 40
    elif change == 'protected':
        rows[6]['body'][0]['protected'] = True
    elif change == 'tip':
        rows[6]['body'][0]['commit']['sha'] = 'f' * 40
    elif change == 'coverage':
        rows[4]['body']['total_count'] = 1
    else:
        rows[0]['status'] = 404
    with pytest.raises(native.ExternalProofError, match=code):
        proved(f)


def test_missing_page_returns_exact_get_before_git_or_lock_writes(isolated):
    f = isolated
    f.proof['responses'][6]['body'] = [{'name': 'other-' + str(i), 'protected': False,
                                       'commit': {'sha': f.head}} for i in range(100)]
    f.calls.clear()
    with pytest.raises(native.ExternalProofError) as caught:
        proved(f)
    assert caught.value.next_get == {'method': 'GET', 'url': URL + '/branches?per_page=100&page=2'}
    assert f.calls == []
    assert not f.selected.project_lock_path.exists()


def save_proof(f):
    path = f.directory / 'proof.json'
    raw = json.dumps(f.proof).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    return str(path), digest(raw), raw


def test_parent_entry_missing_get_preserves_input_and_performs_no_git(isolated, monkeypatch):
    f = isolated
    f.proof['responses'].pop(5)  # Repository metadata must be read, never inferred.
    path, sha, raw = save_proof(f)
    monkeypatch.setattr(parent.transport, 'trusted_parent', lambda: None)
    f.calls.clear()
    result = parent.execute('agent-git-external-merge', RUN, pr_number=123,
                            proof_file=path, sha256=sha)
    assert result['version'] == 'parent-commands-v1'
    assert result['code'] == 'external_get_required'
    assert result['next_action']['action'] == 'collect_get'
    assert result['next_action']['url'] == URL
    assert result['executed'] is False and f.calls == []
    assert Path(path).read_bytes() == raw
    assert not f.selected.project_lock_path.exists()
    assert not (f.directory / 'external-merge.json').exists()


@pytest.mark.parametrize('resume', [False, True])
def test_parent_requires_explicit_resume_and_same_proof_identity(isolated, monkeypatch, resume):
    f = isolated
    path, sha, raw = save_proof(f)
    checkpoint = {'version': 'external-merge-v1', 'run_id': RUN, 'pr_number': 123,
                  'proof_sha256': '0' * 64 if resume else sha, 'completed': ['proof', 'discard']}
    cleanup.durable_json(f.directory / 'external-merge.json', checkpoint)
    before = (f.directory / 'external-merge.json').read_bytes()
    journal = (f.directory / 'github.json').read_bytes()
    monkeypatch.setattr(parent.transport, 'trusted_parent', lambda: None)
    result = parent.execute('agent-git-external-merge', RUN, pr_number=123,
                            proof_file=path, sha256=sha, resume=resume)
    expected = 'external_resume_identity_mismatch' if resume else 'external_explicit_resume_required'
    assert result['code'] == expected
    assert (f.directory / 'external-merge.json').read_bytes() == before
    assert (f.directory / 'github.json').read_bytes() == journal
    assert Path(path).read_bytes() == raw
    if not resume:
        assert result['next_action']['required_arguments']['resume'] is True


def test_ci_skip_and_check_suite_gate_is_not_bypassed(isolated):
    f = isolated
    rows = f.proof['responses'][3]['body']['check_runs']
    next(row for row in rows if row['name'] in native.HEAVY_EXECUTION).update(conclusion='skipped')
    for row in rows:
        row.pop('check_suite')
    with pytest.raises(native.ExternalProofError, match='external_native_gate_rejected'):
        proved(f)


@pytest.mark.parametrize('already_parked', [False, True])
def test_native_park_snapshots_and_baseline_fingerprints(isolated, already_parked):
    f = isolated
    # Exercise the native park's real source/snapshot/restore API with this
    # fixture's approved files, without inventing unrelated validation fixtures.
    native.validate_journal(f.directory, f.ledger, selected=f.selected)
    effects = {'created_records': [], 'restored_files': [], 'attempted_files': []}
    result = {'side_effects': effects}
    obj = park._Park(f.root, f.directory, f.selected, cleanup.Git(f.root), result, [])
    obj.files, obj.limit, obj.head = f.approval['files'], 4096, f.base
    obj.ledger = f.ledger
    obj.before, obj.after = {'sample.txt': b'before\n'}, {'sample.txt': b'approved after\n'}
    obj.approval_hash = digest((f.directory / 'github-approved.json').read_bytes())
    (f.directory / park.SNAPSHOTS).mkdir(mode=0o700)
    obj.write_snapshot(f.directory / park.SNAPSHOTS / '0', b'approved after\n')
    state = {'version': 'worktree-park-v1', 'run_id': RUN, 'approval_sha256': obj.approval_hash,
             'head': f.base, 'files': f.approval['files'], 'phase': 'parked',
             'checkpoints': {'sample.txt': 'restored'}}
    cleanup.durable_json(f.directory / park.STATE, state)
    if not already_parked:
        f.source.write_bytes(b'approved after\n')
        f.source.chmod(0o750)
        obj.source_state()
        obj.restore('sample.txt')
    obj.source_state(parked=True)
    obj.snapshots(state)
    assert f.source.read_bytes() == b'before\n'
    assert stat.S_IMODE(f.source.stat().st_mode) == 0o640
    assert (f.directory / park.SNAPSHOTS / '0').read_bytes() == b'approved after\n'
    assert engine(f).run_external()['status'] == 'complete'


@pytest.mark.parametrize('after_present', [False, True])
def test_cleanup_ff_precedes_remote_delete_and_restores_full_mode(isolated, after_present):
    f = isolated
    if after_present:
        f.source.write_bytes(b'approved after\n')
        f.source.chmod(0o750)
    worker = engine(f)
    result = worker.run_external()
    assert result['status'] == 'complete'
    assert f.git('rev-parse', 'HEAD') == f.merge
    assert f.source.read_bytes() == b'approved after\n'
    assert stat.S_IMODE(f.source.stat().st_mode) == 0o750
    ff = next(i for i, call in enumerate(f.calls) if call[:2] == ('merge', '--ff-only'))
    deletion = next(i for i, call in enumerate(f.calls) if call[0] == 'push')
    assert ff < deletion
    assert '--force-with-lease=refs/heads/codex/' + RUN + ':' + f.head in f.calls[deletion]
    assert f.git('ls-remote', str(f.remote), 'refs/heads/codex/' + RUN) == ''


def test_ff_precondition_failure_preserves_remote_branch(isolated):
    f = isolated
    f.source.write_bytes(b'user edit\n')
    f.git('add', '--', 'sample.txt')
    f.git('commit', '-m', 'unrelated local commit')
    with pytest.raises(cleanup.Pending, match='base_diverged_or_local_only_commits'):
        engine(f).run_external()
    assert not any(call[0] == 'push' for call in f.calls)
    assert f.head in f.git('ls-remote', str(f.remote), 'refs/heads/codex/' + RUN)


def test_actual_remote_tip_compare_mismatch_does_not_delete(isolated):
    f = isolated
    f.git('push', '--force-with-lease=refs/heads/codex/' + RUN + ':' + f.head,
          str(f.remote), f.merge + ':refs/heads/codex/' + RUN)
    with pytest.raises(cleanup.Pending, match='remote_branch_advanced'):
        engine(f).run_external()
    assert not any(call[0] == 'push' for call in f.calls)


def test_explicit_phase_resume_skips_finished_ff_and_delete(isolated, monkeypatch):
    f = isolated
    worker = engine(f)
    real_prune = worker.prune
    monkeypatch.setattr(worker, 'prune', lambda: (_ for _ in ()).throw(cleanup.Pending('fixture_stop')))
    with pytest.raises(cleanup.Pending, match='fixture_stop'):
        worker.run_external()
    assert worker.state['sync']['status'] == 'complete'
    assert worker.state['remote']['status'] == 'deleted'
    f.calls.clear()
    monkeypatch.setattr(worker, 'prune', real_prune)
    assert engine(f).run_external()['status'] == 'complete'
    assert not any(call[0] in ('merge', 'push') for call in f.calls)


def test_unknown_ff_intent_is_never_replayed(isolated):
    worker = engine(isolated)
    worker.state.update(external_order='external-merge-v1', external_attempts={'sync': True})
    worker.persist()
    isolated.calls.clear()
    with pytest.raises(cleanup.Pending, match='external_ff_unknown'):
        engine(isolated).run_external()
    assert not any(call[0] in ('merge', 'push') for call in isolated.calls)


def test_crash_after_ff_before_checkpoint_is_resolved_by_readback(isolated):
    f = isolated
    worker = engine(f)
    worker.state.update(external_order='external-merge-v1', external_attempts={'sync': True})
    worker.persist()
    f.git('merge', '--ff-only', '--no-edit', f.merge)
    f.source.chmod(0o750)
    f.calls.clear()
    assert engine(f).run_external()['status'] == 'complete'
    assert not any(call[0] == 'merge' for call in f.calls)


def test_crash_after_remote_delete_reads_absence_without_push(isolated, monkeypatch):
    f = isolated
    worker = engine(f)
    monkeypatch.setattr(worker, 'remote_cleanup', lambda: (_ for _ in ()).throw(cleanup.Pending('fixture_stop')))
    with pytest.raises(cleanup.Pending):
        worker.run_external()
    worker.state['remote_attempt'] = {'ref': 'refs/heads/codex/' + RUN, 'expected_sha': f.head}
    worker.persist()
    f.git('push', str(f.remote), ':refs/heads/codex/' + RUN)
    f.calls.clear()
    assert engine(f).run_external()['status'] == 'complete'
    assert not any(call[0] in ('merge', 'push') for call in f.calls)


def test_unknown_remote_delete_same_tip_is_never_replayed(isolated, monkeypatch):
    f = isolated
    worker = engine(f)
    monkeypatch.setattr(worker, 'remote_cleanup', lambda: (_ for _ in ()).throw(cleanup.Pending('fixture_stop')))
    with pytest.raises(cleanup.Pending):
        worker.run_external()
    worker.state['remote_attempt'] = {'ref': 'refs/heads/codex/' + RUN, 'expected_sha': f.head}
    worker.persist()
    f.calls.clear()
    with pytest.raises(cleanup.Pending, match='remote_delete_unresolved_same_sha'):
        engine(f).run_external()
    assert not any(call[0] == 'push' for call in f.calls)


@pytest.mark.parametrize('fault', ['mode', 'link', 'symlink', 'parent', 'owner', 'oversize',
                                 'sha', 'same_size_mtime'])
def test_response_snapshot_contract_preserves_proof(isolated, tmp_path, monkeypatch, fault):
    f = isolated
    folder = tmp_path / 'private-proof'
    folder.mkdir(mode=0o700)
    path = folder / 'proof.json'
    raw = json.dumps(f.proof).encode()
    sha = digest(raw)
    path.write_bytes(raw)
    path.chmod(0o600)
    if fault == 'mode':
        path.chmod(0o644)
    elif fault == 'link':
        os.link(path, folder / 'alias')
    elif fault == 'symlink':
        path.rename(folder / 'original')
        path.symlink_to(folder / 'original')
    elif fault == 'parent':
        folder.chmod(0o755)
    elif fault == 'owner':
        target, original = path.stat(), os.fstat

        def fstat(fd):
            info = original(fd)
            if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
                fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
                fields['st_uid'] = info.st_uid + 1
                return SimpleNamespace(**fields)
            return info

        monkeypatch.setattr(parent.os, 'fstat', fstat)
    elif fault == 'oversize':
        with path.open('r+b') as handle:
            handle.truncate(parent.transport.MAX_RESPONSE + 1)
    elif fault == 'sha':
        sha = '0' * 64
    elif fault == 'same_size_mtime':
        before = path.stat()
        changed = raw.replace(b'TavernofSoul', b'TavernofSoux')
        assert len(changed) == len(raw) and changed != raw
        path.write_bytes(changed)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    preserved = path.read_bytes()
    records = {name: (f.directory / name).read_bytes() for name in
               ('github.json', 'github-approved.json', 'report.json')}
    monkeypatch.setattr(parent.transport, 'trusted_parent', lambda: None)
    f.calls.clear()
    result = parent.execute('agent-git-external-merge', RUN, pr_number=123,
                            proof_file=str(path), sha256=sha)
    assert result['status'] == 'failed' and not result['executed']
    assert not f.calls and not result['side_effects']['archive_transfer_invoked']
    assert not f.selected.project_lock_path.exists()
    assert not (f.directory / 'external-merge.json').exists()
    if fault in ('sha', 'same_size_mtime'):
        assert result['code'] == 'response_digest_mismatch'
    assert path.read_bytes() == preserved
    assert {name: (f.directory / name).read_bytes() for name in records} == records


def test_response_snapshot_success_ignores_later_mutation(isolated, tmp_path):
    path = tmp_path / 'input.json'
    tmp_path.chmod(0o700)
    path.write_bytes(b'{}')
    path.chmod(0o600)
    raw = parent.response_snapshot(isolated.selected, str(path), digest(b'{}'))
    assert parent.transport.parse(raw) == {}
    path.write_bytes(b'[]')
    assert parent.transport.parse(raw) == {}
    assert path.exists()


def test_response_snapshot_changed_during_fd_read_fails_before_writes(isolated, monkeypatch):
    f = isolated
    path, sha, raw = save_proof(f)
    path = Path(path)
    target, original = path.stat(), os.fdopen
    changed = []

    def fdopen(fd, *args, **kwargs):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino) and not changed:
            replacement = raw.replace(b'TavernofSoul', b'TavernofSoux')
            assert len(replacement) == len(raw) and replacement != raw
            path.write_bytes(replacement)
            os.utime(path, ns=(target.st_atime_ns, target.st_mtime_ns))
            changed.append(True)
        return original(fd, *args, **kwargs)

    monkeypatch.setattr(parent.transport, 'trusted_parent', lambda: None)
    monkeypatch.setattr(parent.os, 'fdopen', fdopen)
    f.calls.clear()
    result = parent.execute('agent-git-external-merge', RUN, pr_number=123,
                            proof_file=str(path), sha256=sha)
    assert changed and result['code'] == 'response_digest_mismatch' and not result['executed']
    assert not f.calls and not f.selected.project_lock_path.exists()
    assert not (f.directory / 'external-merge.json').exists()


def test_external_lock_busy_preserves_inode_mode_and_fixed_code(isolated, monkeypatch):
    f = isolated
    path, sha, _ = save_proof(f)
    lock = f.selected.project_lock_path
    lock.write_bytes(b'')
    lock.chmod(0o640)
    before = lock.stat()
    monkeypatch.setattr(parent.transport, 'trusted_parent', lambda: None)
    with lock.open('a') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = parent.execute('agent-git-external-merge', RUN, pr_number=123,
                                proof_file=path, sha256=sha)
    after = lock.stat()
    assert result['code'] == 'lock_busy' and not result['executed']
    assert (before.st_dev, before.st_ino, before.st_mode) == (after.st_dev, after.st_ino, after.st_mode)
    assert not (f.directory / 'external-merge.json').exists()


@pytest.mark.parametrize('sent', [None, 'begin', 'complete'])
def test_park_distinguishes_historical_receipt_from_current_pending(isolated, sent):
    f = isolated
    folder = f.directory / 'transport'
    folder.mkdir(mode=0o700)
    old_request = 'b' * 64
    op = parent.operation('accept', RUN, old_request)
    journal_hash = digest((f.directory / 'github.json').read_bytes())
    begin = {'run_id': RUN, 'operation': 'accept', 'operation_id': op, 'request_id': old_request,
             'response_sha256': 'c' * 64, 'journal_sha256': 'd' * 64, 'started_at': 1}
    raw = b'{"run_id":"fixture"}'
    complete = {**begin, 'journal_sha256': journal_hash, 'bytes': len(raw), 'sha256': digest(raw),
                'native_exit_code': 0, 'ended_at': 2}
    for name, value in ((op + '.begin.json', begin), (op + '.complete.json', complete), ('head.json', complete)):
        cleanup.durable_json(folder / name, value)
    (folder / (op + '.stdout')).write_bytes(raw)
    (folder / (op + '.stdout')).chmod(0o600)
    obj = park._Park(f.root, f.directory, f.selected, cleanup.Git(f.root),
                     {'side_effects': {}}, [])
    obj.ledger, obj.ledger_hash = f.ledger, journal_hash
    if sent:
        current = parent.operation('accept', RUN, PENDING)
        cleanup.durable_json(folder / (current + '.begin.json'), {**begin, 'request_id': PENDING})
        if sent == 'complete':
            cleanup.durable_json(folder / (current + '.complete.json'),
                                 {**complete, 'operation_id': current, 'request_id': PENDING})
        with pytest.raises(park.Stop, match='publication_state_requires_reconciliation'):
            obj.publication_state()
    else:
        obj.publication_state()
        assert json.loads((folder / 'head.json').read_text()) == complete


def test_current_parent_attempt_and_inflight_refuse_progress(isolated, monkeypatch):
    f = isolated
    result = parent.result_for('agent-git-external-merge', RUN)
    parent.attempt_marker(f.selected, f.directory, RUN, PENDING, 'e' * 64, result, create=True)
    with pytest.raises(parent.Stop, match='accept_attempt_requires_reconciliation'):
        parent.attempt_marker(f.selected, f.directory, RUN, PENDING, None, result)
    folder = f.directory / 'transport'
    folder.mkdir(mode=0o700)
    cleanup.durable_json(folder / 'inflight.json', {})
    class Records:
        def __init__(self, *args, **kwargs):
            self.fd = f.selected.fs.open_directory(folder)

        def close(self):
            os.close(self.fd)
    monkeypatch.setattr(parent.transport, 'Records', Records)
    with pytest.raises(parent.Stop, match='inflight_requires_reconciliation'):
        parent.evidence(RUN, f.ledger)


def test_current_incomplete_begin_receipt_refuses_progress(isolated, monkeypatch):
    f = isolated
    folder = f.directory / 'transport'
    folder.mkdir(mode=0o700)
    op = parent.operation('accept', RUN, PENDING)
    cleanup.durable_json(folder / (op + '.begin.json'), {})
    class Records:
        def __init__(self, *args, **kwargs):
            self.fd = f.selected.fs.open_directory(folder)

        def optional(self, name):
            path = folder / name
            return json.loads(path.read_text()) if path.exists() else None

        def close(self):
            os.close(self.fd)
    monkeypatch.setattr(parent.transport, 'Records', Records)
    with pytest.raises(parent.Stop, match='incomplete_receipt'):
        parent.evidence(RUN, f.ledger)


def test_archive_pending_retains_merge_cleanup_and_never_resends(isolated, monkeypatch):
    f = isolated
    result = parent.result_for('agent-git-external-merge', RUN)
    result.update(merge={'status': 'merged', 'sha': f.merge}, cleanup={'status': 'complete'})
    worker = parent.ExternalMerge(result, RUN, 123, '/private/proof.json', 'e' * 64, True)
    worker.selected, worker.directory = f.selected, f.directory
    worker.state = {'completed': ['proof', 'discard', 'park', 'native_cleanup', 'cleanup'],
                    'archive_attempted': True}
    transfers = []
    monkeypatch.setattr(archive, 'archive_run', lambda *args: transfers.append(args))
    def pending(*args):
        raise archive.ArchiveReadbackError('archive_state', 'archive_pending')
    monkeypatch.setattr(archive, 'verify_run_archive', pending)
    with pytest.raises(parent.Stop, match='external_archive_pending'):
        worker.archive_phase(True, None)
    for _ in range(2):
        with pytest.raises(parent.Stop, match='external_archive_pending'):
            worker.archive_phase(False, None)
    assert len(transfers) == 1
    assert result['merge']['status'] == 'merged'
    assert result['cleanup']['status'] == 'complete'
    assert result['archive']['status'] == 'pending'
    assert result['next_action']['readback']['command'] == 'archive-verify'


def test_native_journal_transition_records_pre_and_post_identity(isolated):
    f = isolated
    result = parent.result_for('agent-git-external-merge', RUN)
    worker = parent.ExternalMerge(result, RUN, 123, '/private/proof.json', 'e' * 64, False)
    worker.selected, worker.directory = f.selected, f.directory
    worker.lock_checks = []
    original_hash = digest((f.directory / 'github.json').read_bytes())
    report_hash = digest((f.directory / 'report.json').read_bytes())
    worker.state = {'completed': ['proof', 'discard'], 'journal_sha256': original_hash,
                    'report_sha256': report_hash}
    candidate = proved(f)
    worker.save_native(candidate)
    assert worker.state['journal_sha256'] == digest((f.directory / 'github.json').read_bytes())
    assert worker.state['journal_sha256'] != original_hash
    assert 'journal_transition' not in worker.state
    assert worker.state['journal_history'][0]['pre'] == original_hash
    assert worker.state['journal_history'][0]['pre_report'] == report_hash
    assert json.loads((f.directory / 'report.json').read_text())['github'] == native.summary(candidate)
    with pytest.raises(parent.Stop, match='external_merge_owns_journal'):
        parent.external_not_owned(f.selected, f.directory)


@pytest.mark.parametrize('after_present', [False, True])
@pytest.mark.parametrize('snapshot_change', ['unchanged', 'replace', 'delete', 'parent'])
def test_parent_orchestration_and_completed_resume(isolated, monkeypatch, after_present, snapshot_change):
    """Boundary responses are fake; proof/Git/park file APIs/native saves are real.

    Native park authority and transport receipt rejection are tested separately;
    this fixture does not fabricate another module's local-check report schema.
    No production predicate or approval check is changed for this fixture.
    """
    f = isolated
    path, sha, raw = save_proof(f)
    if snapshot_change != 'unchanged':
        # A response directory is independent of the internal run directory.
        folder = f.root.parent / 'proof-input'
        folder.mkdir(mode=0o700)
        moved = folder / 'proof.json'
        Path(path).rename(moved)
        path = str(moved)
    proof_path = Path(path)
    original_proof = native.external_merge_proof
    real_open, real_stat = os.open, os.stat
    seen = []

    def forbid_open(value, *args, **kwargs):
        assert isinstance(value, int) or os.fspath(value) not in (
            proof_path.name, str(proof_path), str(proof_path.parent))
        return real_open(value, *args, **kwargs)

    def forbid_stat(value, *args, **kwargs):
        assert isinstance(value, int) or os.fspath(value) not in (
            proof_path.name, str(proof_path), str(proof_path.parent))
        return real_stat(value, *args, **kwargs)

    def prove(ledger, value, number):
        assert value == f.proof
        if not seen and snapshot_change != 'unchanged':
            if snapshot_change == 'parent':
                proof_path.parent.rename(proof_path.parent.with_name('original-proof-input'))
                proof_path.parent.mkdir(mode=0o700)
            replacement = proof_path.with_name('replacement')
            replacement.write_bytes(b'{"untrusted":"replacement"}')
            replacement.chmod(0o600)
            replacement.replace(proof_path)
            if snapshot_change == 'delete':
                proof_path.unlink()
            monkeypatch.setattr(parent.os, 'open', forbid_open)
            monkeypatch.setattr(parent.os, 'stat', forbid_stat)
        seen.append(copy.deepcopy(value))
        return original_proof(ledger, value, number)

    monkeypatch.setattr(native, 'external_merge_proof', prove)
    monkeypatch.setattr(parent.transport, 'trusted_parent', lambda: None)
    folder = f.directory / 'transport'
    folder.mkdir(mode=0o700)
    old_id = 'b' * 64
    op = parent.operation('accept', RUN, old_id)
    request = {'tool': native.TOOLS['merge_pull_request'], 'request_id': PENDING,
               'arguments': {'repository_full_name': REPO, 'pr_number': 123,
                             'expected_head_sha': f.head, 'merge_method': 'squash'}}
    payload = {'run_id': RUN, 'github': native.summary(f.ledger), 'request': request}
    stdout = parent.transport.encode(payload)
    response = b'{}'
    begin = {'run_id': RUN, 'operation': 'accept', 'operation_id': op, 'request_id': old_id,
             'response_sha256': digest(response), 'journal_sha256': 'c' * 64, 'started_at': 1}
    head = {**begin, 'journal_sha256': digest((f.directory / 'github.json').read_bytes()),
            'bytes': len(stdout), 'sha256': digest(stdout), 'native_exit_code': 0, 'ended_at': 2}
    for name, value in ((op + '.begin.json', begin), (op + '.complete.json', head), ('head.json', head)):
        cleanup.durable_json(folder / name, value)
    for name, content in ((op + '.stdout', stdout), (op + '.stderr', b''), (op + '.response.json', response)):
        (folder / name).write_bytes(content)
        (folder / name).chmod(0o600)
    preserved = {p.name: p.read_bytes() for p in folder.iterdir()}

    class Records:
        def __init__(self, *args, **kwargs):
            self.fd = f.selected.fs.open_directory(folder)

        def read(self, name, limit):
            value = (folder / name).read_bytes()
            assert len(value) <= limit
            return value

        def close(self):
            os.close(self.fd)

    monkeypatch.setattr(parent.transport, 'Records', Records)
    monkeypatch.setattr(parent, 'evidence', lambda *args: ((head, {}, payload), {op: head}))

    def parked_boundary(run):
        assert run == RUN
        native.validate_journal(f.directory, f.ledger, selected=f.selected)
        result = parent.result_for('agent-worktree-park', RUN)
        result['side_effects'].update(created_records=[], attempted_files=[], restored_files=[])
        obj = park._Park(f.root, f.directory, f.selected, cleanup.Git(f.root), result, [])
        obj.files, obj.limit, obj.head, obj.ledger = f.approval['files'], 4096, f.base, f.ledger
        obj.before = {'sample.txt': b'before\n'}
        obj.approval_hash = digest((f.directory / 'github-approved.json').read_bytes())
        if (f.directory / park.STATE).exists():
            obj.source_state(parked=True)
            obj.snapshots(json.loads((f.directory / park.STATE).read_text()))
            result.update(status='parked', stage='complete', code='already_parked', executed=False)
            return result
        (f.directory / park.SNAPSHOTS).mkdir(mode=0o700)
        obj.write_snapshot(f.directory / park.SNAPSHOTS / '0', b'approved after\n')
        if after_present:
            obj.source_state()
            obj.restore('sample.txt')
        obj.source_state(parked=True)
        obj.persist({'version': 'worktree-park-v1', 'run_id': RUN, 'approval_sha256': obj.approval_hash,
                     'head': f.base, 'files': obj.files, 'phase': 'parked',
                     'checkpoints': {'sample.txt': 'restored'}})
        result.update(status='parked', stage='complete', code='parked', executed=after_present)
        return result

    monkeypatch.setattr(park, 'park', parked_boundary)
    transfers, readbacks, current_results = [], [], []
    def archive_boundary(*args):
        assert native.cleanup_complete(json.loads((f.directory / 'github.json').read_text()))
        transfers.append(args)
        return {'status': 'archived'}
    def readback_boundary(*args):
        readbacks.append(args)
        return {'destination': 'fixture/workflows/' + RUN, 'receipt_sha256': '1' * 64,
                'inventory_sha256': '2' * 64, 'bundle_sha256': '3' * 64, 'bundle_bytes': 123}
    monkeypatch.setattr(archive, 'archive_run', archive_boundary)
    monkeypatch.setattr(archive, 'verify_run_archive', readback_boundary)
    monkeypatch.setattr(archive, 'verify_current_result', lambda *args: current_results.append(args))
    if after_present:
        f.source.write_bytes(b'approved after\n')
        f.source.chmod(0o750)
    else:
        parked_boundary(RUN)
    first = parent.execute('agent-git-external-merge', RUN, pr_number=123,
                           proof_file=path, sha256=sha)
    monkeypatch.setattr(parent.os, 'open', real_open)
    monkeypatch.setattr(parent.os, 'stat', real_stat)
    assert first['status'] == 'verified', first
    assert seen and all(value == f.proof for value in seen)
    if snapshot_change in ('replace', 'parent'):
        assert proof_path.read_bytes() == b'{"untrusted":"replacement"}'
        if snapshot_change == 'parent':
            assert (proof_path.parent.with_name('original-proof-input') / proof_path.name).read_bytes() == raw
    elif snapshot_change == 'delete':
        assert not proof_path.exists()
    else:
        assert proof_path.read_bytes() == raw
    assert first['merge']['source'] == 'user_ui' and first['cleanup']['status'] == 'complete'
    assert first['completed_stages'][-2:] == ['archive', 'archive_verify']
    assert len(transfers) == len(readbacks) == len(current_results) == 1
    checkpoint = json.loads((f.directory / 'external-merge.json').read_text())
    assert checkpoint['discard']['request_id'] == PENDING
    assert checkpoint['discard']['proof_sha256'] == sha
    assert checkpoint['discard']['merge_sha'] == f.merge
    assert len(checkpoint['journal_history']) == 2
    if snapshot_change != 'unchanged':
        # A new explicit call must independently read the same approved bytes.
        proof_path.write_bytes(raw)
        proof_path.chmod(0o600)
    f.calls.clear()
    resumed = parent.execute('agent-git-external-merge', RUN, pr_number=123,
                             proof_file=path, sha256=sha, resume=True)
    assert resumed['status'] == 'verified', resumed
    assert len(transfers) == 1 and len(readbacks) == len(current_results) == 2
    assert not any(call[0] in ('fetch', 'merge', 'push', 'update-ref') for call in f.calls)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == preserved
    assert Path(path).read_bytes() == raw
