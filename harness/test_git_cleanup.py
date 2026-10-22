"""Offline real Git effects; no production URLs, host Git config, or credentials."""
import copy
import json
import os
from pathlib import Path
import subprocess

import pytest

from harness import git_cleanup as cleanup, git_publish as publication, workspace, storage

RUN_ID = '123456-abcdef'
BRANCH = 'codex/' + RUN_ID


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    # Publication keeps its fixture ROOT; storage uses only this disposable root.
    project = tmp_path / 'storage-project'
    project.mkdir()
    resolve = storage.resolve_storage
    class SyntheticFS(storage.FileSystem):
        def read_bytes(self, path):
            pytest.fail('Git cleanup fixture attempted a storage config read')

        def free_bytes(self, path):
            pytest.fail('Git cleanup fixture attempted a mount free-space query')

        def probe(self, path):
            pytest.fail('Git cleanup fixture attempted a storage probe')

    monkeypatch.setenv(storage.CONFIG_ENV, str(tmp_path / 'ignored-storage.json'))
    monkeypatch.setattr(storage, 'resolve_storage',
                        lambda *a, **kw: resolve(project, env={}, fs=SyntheticFS()))


def test_synthetic_storage_ignores_caller_root_and_ambient_policy(tmp_path):
    guard = storage.resolve_storage(tmp_path / 'uncreated-project',
                                    env={storage.CONFIG_ENV: str(tmp_path / 'unread-config.json')})
    assert guard.root == tmp_path / 'storage-project'
    assert guard.artifact_root == guard.root / 'logs/harness'
    assert guard.env == {} and not guard.configured
    assert guard.check_ready() is guard


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # These tests never inherit host Git identity, hooks/templates or transports.
    for key in list(os.environ):
        if key.startswith(('GIT_', 'SSH_', 'GCM_')) or key in (
                'READ_ONLY', 'GIT', 'TAVERN_WORKFLOW_CHILD', 'GH_TOKEN', 'GITHUB_TOKEN',
                'GITHUB_API_KEY', 'EMAIL'):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / 'home'
    home.mkdir()
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home))
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_TERMINAL_PROMPT', '0')
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', 'file')
    monkeypatch.setenv('GIT_AUTHOR_NAME', 'Offline Fixture')
    monkeypatch.setenv('GIT_AUTHOR_EMAIL', 'fixture@example.invalid')
    monkeypatch.setenv('GIT_COMMITTER_NAME', 'Offline Fixture')
    monkeypatch.setenv('GIT_COMMITTER_EMAIL', 'fixture@example.invalid')
    root, origin, writer = [tmp_path / name for name in ('root', 'origin.git', 'writer')]
    root.mkdir()

    def git(where, *args, check=True):
        result = subprocess.run(['git', '-c', 'core.hooksPath=' + str(hooks),
                                 '-c', 'commit.gpgSign=false', '-c', 'tag.gpgSign=false', *args],
                                cwd=str(where), shell=False, capture_output=True, timeout=15)
        if check:
            assert result.returncode == 0, 'Fixture Git command failed'
        return result.stdout.decode('utf-8').strip() if check else result

    git(tmp_path, 'init', '--bare', '--template=', str(origin))
    git(origin, 'symbolic-ref', 'HEAD', 'refs/heads/master')
    git(root, 'init', '--template=')
    git(root, 'symbolic-ref', 'HEAD', 'refs/heads/master')
    for where in (root,):
        git(where, 'config', 'user.name', 'Offline Fixture')
        git(where, 'config', 'user.email', 'fixture@example.invalid')
        git(where, 'config', 'core.hooksPath', str(hooks))
    (root / '.gitignore').write_text('/logs/\n')
    for name, content in {'edit.txt': 'old\n', 'delete.txt': 'remove\n',
                          'exec.txt': 'run\n', 'other.txt': 'unrelated\n'}.items():
        (root / name).write_text(content)
        (root / name).chmod(0o644)
    git(root, 'add', '--', '.')
    git(root, 'commit', '-m', 'baseline')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'remote', 'add', 'origin', str(origin))
    git(root, 'push', 'origin', 'master')
    git(tmp_path, 'clone', '--template=', str(origin), str(writer))
    git(writer, 'config', 'user.name', 'Offline Fixture')
    git(writer, 'config', 'user.email', 'fixture@example.invalid')
    git(writer, 'config', 'core.hooksPath', str(hooks))
    git(writer, 'switch', '-c', BRANCH)
    before = {name: workspace.fingerprint(root / name, 4096)
              for name in ('edit.txt', 'delete.txt', 'add.txt', 'exec.txt')}
    (writer / 'edit.txt').write_text('new\n')
    (writer / 'delete.txt').unlink()
    (writer / 'add.txt').write_text('added\n')
    (writer / 'add.txt').chmod(0o644)
    (writer / 'exec.txt').chmod(0o755)
    git(writer, 'add', '--', '.')
    git(writer, 'commit', '-m', 'approved edits')
    head = git(writer, 'rev-parse', 'HEAD')
    git(writer, 'push', 'origin', 'HEAD:refs/heads/' + BRANCH)
    after = {name: workspace.fingerprint(writer / name, 4096) for name in before}
    git(writer, 'switch', 'master')
    git(writer, 'merge', '--squash', BRANCH)
    git(writer, 'commit', '-m', 'squashed PR')
    merge = git(writer, 'rev-parse', 'HEAD')
    git(writer, 'push', 'origin', 'master')
    git(root, 'fetch', '--no-recurse-submodules', 'origin')
    git(root, 'branch', BRANCH, head)
    directory = root / 'logs/harness/workflows' / RUN_ID
    directory.mkdir(parents=True, mode=0o700)
    cfg = publication.load_config()
    files = {}
    transport = cleanup.Git(root)
    for name in before:
        old = cleanup.tree_file(transport, base, name)
        new = cleanup.tree_file(transport, merge, name)
        files[name] = {'before': old, 'after': new}
    ledger = {'run_id': RUN_ID, 'branch': BRANCH, 'config': cfg, 'files': files,
              'base_sha': base, 'head_sha': head, 'merge_sha': merge, 'pr_number': 11,
              'cleanup_proof': {'head_sha': head, 'merge_sha': merge, 'verified': True,
                                'default_branch': 'master',
                                'branch': {'sha': head, 'protected': False}, 'open_prs': []}}
    approval = {'run_id': RUN_ID, 'config': cfg, 'max_file_bytes': 4096,
                'files': {name: {'before': before[name], 'after': after[name]} for name in before}}
    report = {'changed_files': list(files), 'github_enabled': True}

    def origin_validator(transport, repository):
        # Test-only exact paths. The production URL predicate is tested separately.
        assert repository == cfg['repository']
        for args in [('remote', 'get-url', '--all', 'origin'),
                     ('remote', 'get-url', '--push', '--all', 'origin')]:
            if transport.text(*args).splitlines() != [str(origin)]:
                raise cleanup.Pending('origin_transport_mismatch')

    def run(transport=None):
        return cleanup.Cleanup(root, directory, ledger, report, approval,
                               transport=transport, origin_validator=origin_validator).run()

    return locals()


def assert_complete(repo, result):
    assert result['status'] == 'complete', result
    git, root = repo['git'], repo['root']
    assert git(root, 'status', '--porcelain') == ''
    assert git(root, 'symbolic-ref', '--short', 'HEAD') == 'master'
    assert git(root, 'rev-parse', 'HEAD') == git(root, 'rev-parse', 'origin/master')
    assert git(root, 'ls-remote', '--refs', 'origin', 'refs/heads/' + BRANCH) == ''
    for ref in ('refs/heads/' + BRANCH, 'refs/remotes/origin/' + BRANCH):
        assert git(root, 'show-ref', '--verify', ref, check=False).returncode != 0
    assert (repo['directory'] / 'cleanup.json').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('checkout', ['master', BRANCH, 'absent'])
def test_real_squash_cleanup_and_idempotent_resume(repo, checkout):
    git, root = repo['git'], repo['root']
    if checkout == 'absent':
        git(root, 'update-ref', '-d', 'refs/heads/' + BRANCH, repo['head'])
    else:
        git(root, 'switch', checkout)
    # Squash is deliberately not ancestral; branch -d would reject it.
    assert not cleanup.Git(root).ancestor(repo['head'], repo['merge'])
    assert_complete(repo, repo['run']())
    assert_complete(repo, repo['run']())


def apply_approved(repo):
    for name, item in repo['approval']['files'].items():
        target = repo['root'] / name
        if item['after'] is None:
            target.unlink()
        else:
            blob = repo['ledger']['files'][name]['after']['sha']
            data = cleanup.Git(repo['root']).run('cat-file', 'blob', blob)[1]
            target.write_bytes(data)
            target.chmod(item['after']['mode'])


def test_real_app_edit_add_delete_and_executable_change(repo):
    apply_approved(repo)
    assert_complete(repo, repo['run']())
    assert (repo['root'] / 'exec.txt').stat().st_mode & 0o111
    assert not (repo['root'] / 'delete.txt').exists()
    assert (repo['root'] / 'add.txt').read_text() == 'added\n'
    restore = json.loads((repo['directory'] / 'cleanup.json').read_text())['restore']
    assert restore['phase'] == 'synced'
    assert (repo['directory'] / 'cleanup-backup').stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('kind', ['staged', 'untracked', 'same_file', 'symlink', 'chmod',
                                  'local_commit', 'diverged_base', 'detached', 'other_branch'])
def test_user_state_is_preserved_and_never_complete(repo, kind):
    root, git = repo['root'], repo['git']
    if kind in ('same_file', 'symlink', 'chmod'):
        apply_approved(repo)
        if kind == 'same_file':
            (root / 'edit.txt').write_text('user edit\n')
        elif kind == 'symlink':
            (root / 'edit.txt').unlink()
            (root / 'edit.txt').symlink_to('other.txt')
        else:
            (root / 'exec.txt').chmod(0o644)
    elif kind == 'untracked':
        (root / 'user.txt').write_text('user\n')
    elif kind in ('staged', 'local_commit', 'diverged_base'):
        (root / 'other.txt').write_text('user\n')
        git(root, 'add', '--', 'other.txt')
        if kind != 'staged':
            git(root, 'commit', '-m', 'local only')
    elif kind == 'detached':
        git(root, 'switch', '--detach')
    else:
        git(root, 'switch', '-c', 'user-work')
    before_head = git(root, 'rev-parse', 'HEAD')
    before_status = git(root, 'status', '--porcelain')
    result = repo['run']()
    assert result['status'] == 'cleanup_pending'
    assert git(root, 'rev-parse', 'HEAD') == before_head
    assert git(root, 'status', '--porcelain') == before_status
    assert git(root, 'show-ref', '--verify', 'refs/heads/' + BRANCH)
    assert repo['ledger']['merge_sha'] == repo['merge']


@pytest.mark.parametrize('target', [BRANCH, 'master'])
def test_other_worktree_preserves_branch(repo, target):
    other = repo['tmp_path'] / 'other-worktree'
    if target == 'master':
        repo['git'](repo['root'], 'switch', BRANCH)
    repo['git'](repo['root'], 'worktree', 'add', str(other), target)
    result = repo['run']()
    assert result['status'] == 'cleanup_pending'
    assert repo['git'](repo['root'], 'show-ref', '--verify', 'refs/heads/' + target)
    if target == BRANCH:
        assert repo['git'](repo['root'], 'ls-remote', 'origin', 'refs/heads/' + BRANCH)


@pytest.mark.parametrize('kind', ['protected', 'open_pr', 'proof_missing', 'default_branch',
                                  'default_unknown', 'merge_not_in_base'])
def test_proof_gates_prevent_remote_deletion(repo, kind):
    proof = repo['ledger']['cleanup_proof']
    if kind == 'protected':
        proof['branch']['protected'] = True
    elif kind == 'open_pr':
        proof['open_prs'] = [{'number': 12}]
    elif kind == 'proof_missing':
        proof['verified'] = False
    elif kind == 'default_branch':
        proof['default_branch'] = BRANCH
    elif kind == 'default_unknown':
        proof.pop('default_branch')
    else:
        repo['ledger']['merge_sha'] = repo['head']
        proof['merge_sha'] = repo['head']
    assert repo['run']()['status'] == 'cleanup_pending'
    assert repo['git'](repo['root'], 'ls-remote', 'origin', 'refs/heads/' + BRANCH)


@pytest.mark.parametrize('kind', ['before', 'at_delete'])
def test_lease_protects_remote_tip_race(repo, kind):
    writer, git = repo['writer'], repo['git']
    git(writer, 'switch', BRANCH)
    (writer / 'race.txt').write_text('new work\n')
    git(writer, 'add', '--', 'race.txt')
    git(writer, 'commit', '-m', 'new work')
    advanced = git(writer, 'rev-parse', 'HEAD')

    class Race(cleanup.Git):
        def run(self, *args, **kwargs):
            if args and args[0] == 'push':
                git(writer, 'push', 'origin', BRANCH)
            return super().run(*args, **kwargs)

    if kind == 'before':
        git(writer, 'push', 'origin', BRANCH)
    result = repo['run'](Race(repo['root']))
    assert result['status'] == 'cleanup_pending'
    assert advanced in git(repo['root'], 'ls-remote', 'origin', 'refs/heads/' + BRANCH)


@pytest.mark.parametrize('interrupt', ['timeout', 'crash'])
def test_delete_reply_loss_is_reconciled_without_resending(repo, interrupt):
    class Interrupt(cleanup.Git):
        def run(self, *args, **kwargs):
            value = super().run(*args, **kwargs)
            if args and args[0] == 'push':
                if interrupt == 'crash':
                    raise KeyboardInterrupt
                raise cleanup.Pending('git_timeout')
            return value

    if interrupt == 'crash':
        with pytest.raises(KeyboardInterrupt):
            repo['run'](Interrupt(repo['root']))
    else:
        assert_complete(repo, repo['run'](Interrupt(repo['root'])))

    class NoResend(cleanup.Git):
        def run(self, *args, **kwargs):
            assert not args or args[0] != 'push', 'Ambiguous deletion must not be resent'
            return super().run(*args, **kwargs)

    assert_complete(repo, repo['run'](NoResend(repo['root'])))


def test_ambiguous_delete_remaining_same_sha_never_retries(repo):
    class FailedPush(cleanup.Git):
        def run(self, *args, **kwargs):
            if args and args[0] == 'push':
                raise cleanup.Pending('git_timeout')
            return super().run(*args, **kwargs)

    assert repo['run'](FailedPush(repo['root']))['status'] == 'cleanup_pending'
    assert repo['run']()['remote']['reason'] == 'remote_delete_unresolved_same_sha'
    # A parent can reconcile an externally confirmed deletion, without new writes.
    repo['git'](repo['root'], 'push', 'origin', ':refs/heads/' + BRANCH)
    assert_complete(repo, repo['run']())


@pytest.mark.parametrize('command', ['fetch', 'prune', 'switch', 'merge', 'update-ref'])
def test_partial_failure_then_safe_resume(repo, command):
    if command == 'switch':
        repo['git'](repo['root'], 'switch', BRANCH)
    elif command == 'merge':
        apply_approved(repo)

    class FailOnce(cleanup.Git):
        def run(self, *args, **kwargs):
            match = args and (args[0] == command or (command == 'prune' and args[:2] == ('remote', 'prune')))
            if match:
                raise cleanup.Pending('git_command_failed')
            return super().run(*args, **kwargs)

    result = repo['run'](FailOnce(repo['root']))
    assert result['status'] == 'cleanup_pending'
    assert repo['ledger']['merge_sha'] == repo['merge']
    assert_complete(repo, repo['run']())


def test_restore_interruption_and_external_edit_preserved(repo, monkeypatch):
    apply_approved(repo)
    original = cleanup.replace_bytes
    count = 0

    def fail_restore(path, content, mode):
        nonlocal count
        if Path(path).parent == repo['root']:
            count += 1
            if count == 2:
                raise OSError('synthetic interruption')
        return original(path, content, mode)

    monkeypatch.setattr(cleanup, 'replace_bytes', fail_restore)
    assert repo['run']()['status'] == 'cleanup_pending'
    monkeypatch.setattr(cleanup, 'replace_bytes', original)
    (repo['root'] / 'edit.txt').write_text('external edit after interruption\n')
    assert repo['run']()['status'] == 'cleanup_pending'
    assert (repo['root'] / 'edit.txt').read_text() == 'external edit after interruption\n'
    # Explicitly put the approved snapshot back, then resume remaining files.
    (repo['root'] / 'edit.txt').write_text('new\n')
    assert_complete(repo, repo['run']())


@pytest.mark.parametrize('kind', ['bytes', 'mode', 'resume_bytes', 'resume_mode'])
def test_fetched_base_file_mismatch_preserves_approved_changes(repo, kind, monkeypatch):
    apply_approved(repo)
    if kind.startswith('resume_'):
        original = cleanup.replace_bytes
        def interrupted(path, content, mode):
            if Path(path).parent == repo['root']:
                raise PermissionError
            return original(path, content, mode)
        monkeypatch.setattr(cleanup, 'replace_bytes', interrupted)
        assert repo['run']()['restore']['phase'] == 'prepared'
        monkeypatch.setattr(cleanup, 'replace_bytes', original)
    writer, git = repo['writer'], repo['git']
    if kind.endswith('bytes'):
        (writer / 'edit.txt').write_text('later remote content\n')
    else:
        (writer / 'exec.txt').chmod(0o644)
    git(writer, 'add', '--', '.')
    git(writer, 'commit', '-m', 'later change')
    git(writer, 'push', 'origin', 'master')
    before = {name: workspace.fingerprint(repo['root'] / name, 4096) for name in repo['before']}
    assert repo['run']()['status'] == 'cleanup_pending'
    assert {name: workspace.fingerprint(repo['root'] / name, 4096) for name in before} == before


@pytest.mark.parametrize('field', ['remote.origin.url', 'remote.origin.pushurl'])
def test_wrong_transport_never_deletes(repo, field):
    repo['git'](repo['root'], 'config', field, str(repo['tmp_path'] / 'elsewhere.git'))
    assert repo['run']()['status'] == 'cleanup_pending'
    assert repo['git'](repo['origin'], 'show-ref', '--verify', 'refs/heads/' + BRANCH)


@pytest.mark.parametrize('kind', ['pushurl', 'rewrite', 'multiple'])
def test_production_url_validation_rejects_redirection_without_network(repo, kind):
    git, root = repo['git'], repo['root']
    url = 'https://github.com/' + repo['cfg']['repository'] + '.git'
    git(root, 'config', 'remote.origin.url', url)
    cleanup.validate_origin(cleanup.Git(root), repo['cfg']['repository'])
    if kind == 'pushurl':
        git(root, 'config', 'remote.origin.pushurl', 'https://github.com/other/repository.git')
    elif kind == 'rewrite':
        git(root, 'config', 'url.https://github.com/other/.pushInsteadOf', 'https://github.com/')
    else:
        git(root, 'config', '--add', 'remote.origin.url', url)
    with pytest.raises(cleanup.Pending, match='origin_transport_mismatch'):
        cleanup.validate_origin(cleanup.Git(root), repo['cfg']['repository'])


@pytest.mark.parametrize('mode', ['read_only', 'simulated', 'no_git', 'disabled', 'unchanged', 'child', 'env_read_only', 'env_git'])
def test_disabled_paths_execute_no_git(repo, monkeypatch, mode):
    if mode in ('read_only', 'simulated', 'no_git'):
        repo['report'][mode] = True
    elif mode == 'disabled':
        repo['ledger']['config']['enabled'] = False
    elif mode == 'unchanged':
        repo['report']['changed_files'] = []
    else:
        monkeypatch.setenv({'child': 'TAVERN_WORKFLOW_CHILD', 'env_read_only': 'READ_ONLY', 'env_git': 'GIT'}[mode],
                          '0' if mode == 'env_git' else '1')

    class NoGit(cleanup.Git):
        def run(self, *args, **kwargs):
            pytest.fail('Disabled cleanup invoked Git')

    assert repo['run'](NoGit(repo['root']))['status'] == 'cleanup_pending'


def cli_fixture(repo, monkeypatch):
    root, directory = repo['root'], repo['directory']
    candidate = directory / 'workspace'
    backup = directory / 'backup'
    candidate.mkdir()
    backup.mkdir()
    approval = repo['approval']
    approval['workspace'] = str(candidate)
    for name, entry in repo['ledger']['files'].items():
        for version, destination in [('before', backup), ('after', candidate)]:
            if entry[version]:
                path = destination / name
                path.write_bytes(cleanup.Git(root).run('cat-file', 'blob', entry[version]['sha'])[1])
                path.chmod(approval['files'][name][version]['mode'])
        if entry['after']:
            entry['after']['content'] = (candidate / name).read_text()
    report = {**repo['report'], 'run_id': RUN_ID, 'scope': list(repo['ledger']['files']),
              'workspace': str(candidate), 'status': 'awaiting_github'}
    ledger = repo['ledger']
    ledger.update(version='github-v1', metadata={'commit_message': 'fixture', 'pr_title': 'fixture', 'pr_body': 'fixture'},
                  status='awaiting_connector', step='merge', events=[], deadline=10**12)
    ledger.pop('cleanup_proof')
    cleanup.durable_json(directory / 'report.json', report)
    cleanup.durable_json(directory / 'github-approved.json', approval)
    cleanup.durable_json(directory / 'github.json', ledger)
    monkeypatch.setattr(publication, 'ROOT', root)
    monkeypatch.setattr(publication, 'REPORTS', directory.parent)
    monkeypatch.setattr(publication, 'origin_matches', lambda where, repository: where == root and repository == repo['cfg']['repository'])
    monkeypatch.setattr(cleanup, 'execute', lambda where, target, journal, saved, approved, *, storage_guard=None:
                        cleanup.Cleanup(where, target, journal, saved, approved,
                                        origin_validator=repo['origin_validator'],
                                        storage_guard=storage_guard).run())
    return ledger


def drive_cleanup_cli(repo, capsys, job):
    observed = []
    while job:
        assert job['tool'] == publication.TOOLS['fetch'], 'Cleanup must never publish or remerge'
        url = job['arguments']['url']
        observed.append(url)
        if '/pulls/11' in url:
            identity = {'full_name': repo['cfg']['repository']}
            data = {'number': 11, 'state': 'closed', 'merged': True, 'merge_commit_sha': repo['merge'],
                    'head': {'ref': BRANCH, 'sha': repo['head'], 'repo': identity},
                    'base': {'ref': 'master', 'sha': repo['merge'], 'repo': identity}}
        elif '/check-runs?' in url:
            data = {'total_count': 3, 'check_runs': [
                {'id': i + 1, 'name': name, 'head_sha': repo['head'], 'app': {'slug': 'github-actions'},
                 'status': 'completed', 'conclusion': 'success'}
                for i, name in enumerate(repo['cfg']['required_checks'])]}
        elif url.endswith('/status'):
            data = {'sha': repo['head'], 'total_count': 0}
        elif url == 'https://api.github.com/repos/' + repo['cfg']['repository']:
            data = {'full_name': repo['cfg']['repository'], 'default_branch': 'master'}
        elif '/branches?' in url:
            remote = repo['git'](repo['root'], 'ls-remote', '--refs', 'origin', 'refs/heads/' + BRANCH)
            data = [{'name': BRANCH, 'protected': False, 'commit': {'sha': repo['head']}}] if remote else []
        else:
            assert '/pulls?state=open&head=' in url
            data = []
        code = publication.main(['accept', '--run-id', RUN_ID, '--request-id', job['request_id'],
                                 '--response-json', json.dumps(data)])
        output = json.loads(capsys.readouterr().out)
        job = output['request']
    return code, output, observed


@pytest.mark.parametrize('dirty', [False, True])
def test_cli_accept_merge_automatically_finishes_real_git_cleanup(repo, monkeypatch, capsys, dirty):
    cli_fixture(repo, monkeypatch)
    from harness import improvements as imp, improvement_loop as loop
    selected = storage.resolve_storage(repo['root'])
    monkeypatch.setattr(imp, 'ROOT', repo['root'])
    original_replace = cleanup.replace_bytes
    protected_mutations = []
    def observe_mutation(path, content, mode):
        original_replace(path, content, mode)
        if Path(path).parent == repo['root']:
            # Execute the real snapshot/freshness entry points halfway through
            # actual baseline restoration. The CLI owns an independent flock.
            with pytest.raises(BlockingIOError):
                imp.snapshot_sources(['edit.txt'], selected=selected)
            with pytest.raises(BlockingIOError):
                loop.validate_scan_freshness({'loop_dependencies': {}}, selected=selected)
            protected_mutations.append(Path(path).name)
    monkeypatch.setattr(cleanup, 'replace_bytes', observe_mutation)
    if dirty:
        apply_approved(repo)
    assert publication.main(['request', '--run-id', RUN_ID]) == 0
    request = json.loads(capsys.readouterr().out)['request']
    assert request['tool'] == publication.TOOLS['merge_pull_request']
    assert publication.main(['accept', '--run-id', RUN_ID, '--request-id', request['request_id'],
                             '--response-json', json.dumps({'merged': True, 'sha': repo['merge']})]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['github']['step'] == 'cleanup_pr'
    assert json.loads((repo['directory'] / 'report.json').read_text())['status'] == 'awaiting_github'
    code, output, urls = drive_cleanup_cli(repo, capsys, output['request'])
    assert code == 0 and output['github']['cleanup']['status'] == 'complete'
    assert json.loads((repo['directory'] / 'report.json').read_text())['status'] == 'passed'
    assert_complete(repo, json.loads((repo['directory'] / 'cleanup.json').read_text()))
    if dirty:
        assert protected_mutations
    assert imp.snapshot_sources(['edit.txt'], selected=selected)['edit.txt']['content'] == b'new\n'
    assert publication.main(['resume', '--run-id', RUN_ID]) == 0
    job = json.loads(capsys.readouterr().out)['request']
    code, output, _ = drive_cleanup_cli(repo, capsys, job)
    assert code == 0 and output['github']['cleanup']['status'] == 'complete'
    assert len(urls) == 6


def test_cli_partial_cleanup_remains_non_passed_and_resumes_without_new_writes(repo, monkeypatch, capsys):
    ledger = cli_fixture(repo, monkeypatch)
    ledger.update(status='merged', step='done', merge_sha=repo['merge'])
    cleanup.durable_json(repo['directory'] / 'github.json', ledger)
    (repo['root'] / 'user.txt').write_text('preserve me\n')
    assert publication.main(['cleanup', '--run-id', RUN_ID]) == 0
    job = json.loads(capsys.readouterr().out)['request']
    code, output, _ = drive_cleanup_cli(repo, capsys, job)
    assert code == 1 and output['github']['status'] == 'cleanup_pending'
    assert output['github']['merge_sha'] == repo['merge']
    assert output['github']['cleanup']['remote']['status'] == 'deleted'
    assert json.loads((repo['directory'] / 'report.json').read_text())['status'] == 'cleanup_pending'
    (repo['root'] / 'user.txt').unlink()  # Explicit fixture resolution of the user edit.
    assert publication.main(['resume', '--run-id', RUN_ID]) == 0
    job = json.loads(capsys.readouterr().out)['request']
    code, output, _ = drive_cleanup_cli(repo, capsys, job)
    assert code == 0 and output['github']['cleanup']['status'] == 'complete'
    assert_complete(repo, json.loads((repo['directory'] / 'cleanup.json').read_text()))


def test_automatic_remote_deletion_and_absent_local_branch(repo):
    repo['git'](repo['root'], 'push', 'origin', ':refs/heads/' + BRANCH)
    repo['ledger']['cleanup_proof']['branch'] = None
    repo['git'](repo['root'], 'update-ref', '-d', 'refs/heads/' + BRANCH, repo['head'])
    result = repo['run']()
    assert result['remote']['status'] == result['local']['status'] == 'absent'
    assert_complete(repo, result)


def test_local_compare_and_delete_rejects_tip_race(repo):
    class LocalRace(cleanup.Git):
        def run(self, *args, **kwargs):
            if args[:2] == ('update-ref', '-d'):
                super().run('update-ref', 'refs/heads/' + BRANCH, repo['merge'], repo['head'])
            return super().run(*args, **kwargs)

    result = repo['run'](LocalRace(repo['root']))
    assert result['status'] == 'cleanup_pending'
    assert repo['git'](repo['root'], 'rev-parse', BRANCH) == repo['merge']


def test_clean_already_synced_checkout_with_later_master_is_complete(repo):
    repo['git'](repo['root'], 'merge', '--ff-only', 'origin/master')
    writer, git = repo['writer'], repo['git']
    (writer / 'later.txt').write_text('another merged task\n')
    git(writer, 'add', '--', 'later.txt')
    git(writer, 'commit', '-m', 'later task')
    git(writer, 'push', 'origin', 'master')
    assert_complete(repo, repo['run']())


def test_failed_fetch_never_exposes_transport_output(repo, monkeypatch):
    def failed(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 128, b'https://secret@private/', b'credential material')
    monkeypatch.setattr(subprocess, 'run', failed)
    with pytest.raises(cleanup.Pending) as error:
        cleanup.Git(repo['root']).run('fetch', '--no-recurse-submodules', 'origin')
    assert str(error.value) == 'git_command_failed'


@pytest.mark.parametrize('path,expected', [
    (b'/tmp/a b', '/tmp/a b'),
    (b'"/tmp/a\\tb\\nc\\\\d\\\"e"', '/tmp/a\tb\nc\\d"e'),
    (b'"/tmp/\\354\\225\\210"', '/tmp/안'),
])
def test_git_225_porcelain_paths(path, expected):
    class Porcelain:
        def run(self, *args):
            assert args == ('-c', 'core.quotePath=true', 'worktree', 'list', '--porcelain')
            return 0, b'worktree ' + path + b'\nHEAD ' + b'a' * 40 + b'\nbranch refs/heads/master\n\n'
    assert cleanup.worktrees(Porcelain())[0]['worktree'] == expected


@pytest.mark.parametrize('path', [b'"/tmp/bad\\q"', b'"/tmp/missing', b'/tmp/raw\nline',
                                 b'/tmp/raw\nlocked injected', b'/tmp/raw\nHEAD ' + b'b' * 40,
                                 b'relative', b'/tmp/null\0path'])
def test_ambiguous_worktree_paths_postpone_cleanup(path):
    class Porcelain:
        def run(self, *args):
            return 0, b'worktree ' + path + b'\nHEAD ' + b'a' * 40 + b'\nbranch refs/heads/master\n\n'
    with pytest.raises(cleanup.Pending, match='worktree_state_unknown'):
        cleanup.worktrees(Porcelain())


def test_real_special_worktree_path_and_operation_lookup_are_read_only(repo):
    other = repo['tmp_path'] / '한글 space "back\\slash\ttab'
    git, root = repo['git'], repo['root']
    git(root, 'worktree', 'add', '-b', 'unrelated', str(other), 'master')
    transport = cleanup.Git(root)
    rows = cleanup.worktrees(transport)
    assert str(other) in {row['worktree'] for row in rows}
    index = Path(git(other, 'rev-parse', '--git-path', 'index'))
    if not index.is_absolute():
        index = other / index
    original = index.read_bytes()
    cleanup.no_operations(transport, rows)
    assert index.read_bytes() == original
    assert_complete(repo, repo['run']())


def test_other_worktree_operation_and_dirty_state_are_preserved(repo):
    other = repo['tmp_path'] / 'other'
    git, root = repo['git'], repo['root']
    git(root, 'worktree', 'add', '-b', 'unrelated', str(other), 'master')
    marker = Path(git(other, 'rev-parse', '--git-path', 'MERGE_HEAD'))
    if not marker.is_absolute():
        marker = other / marker
    marker.write_text(repo['head'] + '\n')
    result = repo['run']()
    assert result['remote']['reason'] == 'git_operation_in_progress'
    assert marker.read_text() == repo['head'] + '\n'
    marker.unlink()  # Fixture owner resolves the operation, never the cleanup code.
    (other / 'other.txt').write_text('user work\n')
    result = repo['run']()
    assert result['sync']['reason'] == 'other_worktree_dirty'
    assert (other / 'other.txt').read_text() == 'user work\n'


@pytest.mark.parametrize('kind', ['file', 'directory'])
def test_ignored_collision_preserves_operating_data(repo, kind):
    root = repo['root']
    collision = root / 'add.txt'
    if kind == 'directory':
        collision.mkdir()
        collision = collision / 'operating.db'
    collision.write_bytes(b'private operating data')
    exclude = root / '.git/info/exclude'
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text('add.txt\n')
    assert repo['git'](root, 'status', '--porcelain') == ''
    result = repo['run']()
    assert result['status'] == 'cleanup_pending'
    assert result['sync']['reason'] == 'untracked_or_ignored_collision'
    assert collision.read_bytes() == b'private operating data'
    assert repo['git'](root, 'rev-parse', 'HEAD') == repo['base']


def test_prune_mapping_cannot_delete_unapproved_refs(repo):
    git, root = repo['git'], repo['root']
    git(root, 'config', 'remote.origin.fetch', '+refs/heads/*:refs/heads/*')
    result = repo['run']()
    assert result['status'] == 'cleanup_pending'
    assert result['prune']['reason'] == 'unsafe_prune_refspec'
    assert git(root, 'rev-parse', 'master') == repo['base']
    assert git(root, 'ls-remote', '--refs', 'origin', 'refs/heads/' + BRANCH).split()[0] == repo['head']
    assert git(root, 'rev-parse', 'refs/remotes/origin/' + BRANCH) == repo['head']


@pytest.mark.parametrize('boundary', ['restore', 'merge', 'update-ref'])
def test_crash_after_actual_mutation_resumes_from_state(repo, monkeypatch, boundary):
    apply_approved(repo)
    original = cleanup.replace_bytes
    if boundary == 'restore':
        def interrupted(path, content, mode):
            original(path, content, mode)
            if Path(path).parent == repo['root']:
                raise KeyboardInterrupt
        monkeypatch.setattr(cleanup, 'replace_bytes', interrupted)

    class Crash(cleanup.Git):
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            if args and args[0] == boundary:
                raise KeyboardInterrupt
            return result

    with pytest.raises(KeyboardInterrupt):
        repo['run'](Crash(repo['root']))
    checkpoint = json.loads((repo['directory'] / 'cleanup.json').read_text())
    assert checkpoint['merge_sha'] == repo['merge']
    assert checkpoint['restore']['files']
    monkeypatch.setattr(cleanup, 'replace_bytes', original)
    assert_complete(repo, repo['run']())


def test_permission_failure_preserves_approved_snapshot_then_resumes(repo, monkeypatch):
    apply_approved(repo)
    original = cleanup.replace_bytes
    def denied(path, content, mode):
        if Path(path).parent == repo['root']:
            raise PermissionError('private path must not appear in report')
        return original(path, content, mode)
    monkeypatch.setattr(cleanup, 'replace_bytes', denied)
    result = repo['run']()
    assert result['status'] == 'cleanup_pending'
    assert result['restore']['phase'] == 'prepared'
    assert (repo['root'] / 'edit.txt').read_text() == 'new\n'
    assert 'private path' not in json.dumps(result)
    monkeypatch.setattr(cleanup, 'replace_bytes', original)
    assert_complete(repo, repo['run']())


def test_missing_recovery_snapshot_prevents_overwriting_files(repo, monkeypatch):
    apply_approved(repo)
    original = cleanup.replace_bytes
    def stop(path, content, mode):
        if Path(path).parent == repo['root']:
            raise PermissionError
        return original(path, content, mode)
    monkeypatch.setattr(cleanup, 'replace_bytes', stop)
    assert repo['run']()['status'] == 'cleanup_pending'
    monkeypatch.setattr(cleanup, 'replace_bytes', original)
    snapshot = repo['directory'] / 'cleanup-backup/0'
    snapshot.unlink()
    result = repo['run']()
    assert result['sync']['reason'] == 'recovery_snapshot_invalid'
    assert (repo['root'] / 'edit.txt').read_text() == 'new\n'


def test_completion_rechecks_recreated_remote_ref(repo):
    class Recreate(cleanup.Git):
        fetches = 0
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            if args and args[0] == 'fetch':
                self.fetches += 1
                if self.fetches == 4:
                    repo['git'](repo['writer'], 'push', 'origin', BRANCH)
            return result
    result = repo['run'](Recreate(repo['root']))
    assert result['status'] == 'cleanup_pending'
    assert result['completion']['reason'] == 'ref_reappeared_before_completion'
    assert repo['git'](repo['root'], 'ls-remote', 'origin', 'refs/heads/' + BRANCH)
