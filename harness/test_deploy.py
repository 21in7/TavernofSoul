"""Offline deployment regressions: fake Git, make, systemctl and public HTTP only."""
import copy
import fcntl
import json
import os
import stat

import pytest

from harness import deploy as d, git_publish

OLD, TARGET, TIP, OLD_LINK, NEW_LINK = [char * 40 for char in 'abcde']
LOCKS = ('logs/harness/workflows/.workflow-lock', 'logs/cron-tos.lock',
         'logs/harness/workflows/.lock')


@pytest.fixture(autouse=True)
def isolated_storage_environment(monkeypatch):
    monkeypatch.delenv('HARNESS_STORAGE_CONFIG', raising=False)
    monkeypatch.delenv('HARNESS_REPORT_DIR', raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError('Live subprocess/network is forbidden in deploy tests.')
    monkeypatch.setattr(d.subprocess, 'run', forbidden)
    monkeypatch.setattr(d.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(d, 'public_get', forbidden)


def raw(path, status='M', new=None, gitlink=False):
    before, after = ('160000', '160000') if gitlink else ('100644', '100644')
    if status == 'A':
        before = '000000'
    if status == 'D':
        after = '000000'
    return ':{} {} {} {} {}\0{}\0{}'.format(
        before, after, OLD_LINK, NEW_LINK, status, path, new + '\0' if new else '')


def check_rows():
    names = sorted(git_publish.REQUIRED)
    return [dict(id=index, name=name, head_sha=TARGET, status='completed', conclusion='success',
                 app={'slug': 'github-actions'}, check_suite={'id': 1},
                 details_url='https://github.com/' + d.REPOSITORY + '/actions/runs/1/job/' + str(index))
            for index, name in enumerate(names, 1)]


def fixture_directories(root):
    # Safe fixture permissions must not depend on the caller's creation mask.
    # Keep pre-existing permissions intact so unsafe-path cases remain testable.
    for name in ('logs', 'logs/harness', 'logs/harness/workflows'):
        (root / name).mkdir(mode=0o700, exist_ok=True)


class FakeRuntime(d.Runtime):
    def __init__(self, root, diff=''):
        super().__init__(root)
        self.head, self.link = OLD, OLD_LINK
        self.target_link = NEW_LINK if '160000' in diff else OLD_LINK
        self.diff = diff
        self.events, self.commands, self.requests = [], [], []
        self.fail = None
        self.dirty = ''
        self.subdirty = ''
        self.substatus = None
        self.branch = 'refs/heads/master'
        self.origin = d.ORIGIN
        self.mapping = '+refs/heads/*:refs/remotes/origin/*'
        self.overrides = {}
        self.rows = check_rows()
        self.check_count = None
        self.repo = dict(full_name=d.REPOSITORY, url=d.API, fork=True,
                         default_branch='master', archived=False)
        self.commit = dict(sha=TARGET, url=d.API + '/commits/' + TARGET)
        self.statuses = dict(sha=TARGET, total_count=0, statuses=[], state='pending')
        fixture_directories(root)
        (root / '.git').mkdir(mode=0o700)
        index = root / '.git/index'
        index.write_bytes(b'fixture index, never passed to real Git')
        index.chmod(0o600)

    def attempted(self, event):
        self.events.append(event)
        if event == self.fail:
            raise ValueError('Injected stage failure.')

    def command(self, args, timeout=120):
        self.commands.append((tuple(args), timeout, self.root))
        self.attempted(' '.join(args))
        return ''

    def git(self, *args):
        self.commands.append((('git',) + args, 120, self.root))
        if args in self.overrides:
            value = self.overrides[args]
            if isinstance(value, Exception):
                raise value
            return value
        if args == ('rev-parse', '--show-toplevel'):
            return str(self.root) + '\n'
        if args == ('rev-parse', '--absolute-git-dir'):
            return str(self.root / '.git') + '\n'
        if args == ('rev-parse', '--git-path', 'index'):
            return '.git/index\n'
        if args == ('rev-parse', '--is-bare-repository'):
            return 'false\n'
        if args == ('symbolic-ref', '--quiet', 'HEAD'):
            return self.branch + '\n'
        if args == ('config', '--get-all', 'remote.origin.fetch'):
            return self.mapping + '\n'
        if args == ('config', '--get-all', 'remote.origin.url') or args[:2] == ('remote', 'get-url'):
            return self.origin + '\n'
        if args[:2] == ('-C', 'IPFUnpacker'):
            if args[2:4] in (('config', '--get-all'), ('remote', 'get-url')):
                return d.UNPACKER + '\n'
            if args[2:] == ('rev-parse', '--verify', 'HEAD'):
                return self.link + '\n'
            if args[2] == 'status':
                return self.subdirty
        if args[:2] == ('rev-parse', '--verify'):
            return {'HEAD': self.head, 'refs/remotes/origin/master': TIP,
                    TARGET + '^{commit}': TARGET}[args[2]] + '\n'
        if args[0] == 'ls-tree':
            link = self.target_link if args[1] == TARGET else OLD_LINK
            return '160000 commit ' + link + '\tIPFUnpacker\n'
        if args[:2] == ('config', '--blob'):
            return ('submodule.IPFUnpacker.path=IPFUnpacker\n' +
                    'submodule.IPFUnpacker.url=' + d.UNPACKER + '\n')
        if args[0] == 'status':
            return self.dirty
        if args[:2] == ('submodule', 'status'):
            return self.substatus if self.substatus is not None else ' ' + self.link + ' IPFUnpacker (fixture)\n'
        if args[0] == 'fetch':
            self.attempted('fetch')
            return ''
        if args[0] == 'merge-base':
            self.attempted('ancestor-' + args[2])
            return ''
        if args[0] == 'diff':
            return self.diff
        if args[:2] == ('merge', '--ff-only'):
            # The old state must already be durable on disk when mutation starts.
            evidence = records(self.root)
            assert any(row['stage'] == 'preflight' and row['status'] == 'completed' and
                       row['old_head'] == OLD and row['ci']['sha'] == TARGET for row in evidence)
            self.attempted('ff')
            self.head = TARGET
            return ''
        if 'update' in args and 'submodule' in args:
            assert args == ('-c', 'submodule.IPFUnpacker.url=' + d.UNPACKER,
                            '-c', 'submodule.IPFUnpacker.update=checkout', 'submodule',
                            'update', '--init', '--checkout', '--', 'IPFUnpacker')
            self.attempted('submodule-update')
            self.link = self.target_link
            return ''
        raise AssertionError('Unexpected fake Git operation: ' + repr(args))

    def request(self, url):
        self.requests.append(url)
        self.attempted('api')
        if url == d.API:
            return copy.deepcopy(self.repo)
        if url == d.API + '/commits/' + TARGET:
            return copy.deepcopy(self.commit)
        if url.endswith('/check-runs?filter=all&per_page=100&page=1'):
            return {'total_count': len(self.rows) if self.check_count is None else self.check_count,
                    'check_runs': copy.deepcopy(self.rows)}
        if url.endswith('/status?per_page=100&page=1'):
            return copy.deepcopy(self.statuses)
        raise AssertionError('Unexpected HTTP request: ' + url)

    def health(self, url):
        self.attempted('health ' + url)


def configuration(root):
    fixture_directories(root)
    directory = root / 'logs/harness'
    cfg = {'version': 1, 'health_urls': {r: 'https://' + r + '.example.invalid/health/'
                                        for r in d.REGIONS},
           'cache_urls': {'static': ['https://example.invalid/static/site.css'],
                          'application': ['https://example.invalid/'], 'submodule': []}}
    path = directory / 'deploy-local.json'
    path.write_text(json.dumps(cfg))
    path.chmod(0o600)
    return cfg


def records(root):
    paths = list((root / 'logs/harness/deployments').glob('*.jsonl'))
    assert len(paths) == 1
    assert stat.S_IMODE(paths[0].stat().st_mode) == 0o600
    return [json.loads(line) for line in paths[0].read_text().splitlines()]


@pytest.mark.parametrize('change,expected', [
    ('docs/guide.md', {'static': False, 'application': False, 'submodule': False}),
    ('README.md', {'static': False, 'application': False, 'submodule': False}),
    ('app/views.py', {'static': False, 'application': True, 'submodule': False}),
    ('app/templates/page.html', {'static': False, 'application': True, 'submodule': False}),
    ('app/templates/message.txt', {'static': False, 'application': True, 'submodule': False}),
    ('app/templates/message.md', {'static': False, 'application': True, 'submodule': False}),
    ('app/static/site.css', {'static': True, 'application': False, 'submodule': False}),
    ('app/static/help.md', {'static': True, 'application': False, 'submodule': False}),
    ('IPFUnpacker', {'static': False, 'application': False, 'submodule': True}),
])
def test_diff_branches_and_deleted_paths(change, expected):
    assert d.diff_plan(raw(change, gitlink=change == 'IPFUnpacker')) == expected
    if change != 'IPFUnpacker':
        assert d.diff_plan(raw(change, status='D')) == expected


def test_rename_classifies_both_paths():
    assert d.diff_plan(raw('app/static/old.css', status='R100', new='app/templates/new.html')) == {
        'static': True, 'application': True, 'submodule': False}


@pytest.mark.parametrize('change', [raw('app/migrations/0002.py'),
    raw('app/migrations/old.py', status='D'), raw('app/migrations/new.py', status='A'),
    raw('app/migrations/old.py', status='R100', new='app/ordinary.py'),
    raw('app/ordinary.py', status='R100', new='app/migrations/new.py'),
    raw('../unsafe.py'), raw('unknown', gitlink=True), raw('IPFUnpacker', gitlink=True)[:-1],
    ':160000 000000 ' + OLD_LINK + ' ' + NEW_LINK + ' D\0IPFUnpacker\0'])
def test_unsafe_diff_refused(change):
    with pytest.raises(ValueError):
        d.diff_plan(change)


@pytest.mark.parametrize('branch', ['docs', 'static', 'application', 'submodule', 'all'])
def test_exact_deployment_order_and_conditional_commands(tmp_path, branch):
    changes = {'docs': raw('docs/guide.md'), 'static': raw('app/static/site.css'),
               'application': raw('app/views.py'), 'submodule': raw('IPFUnpacker', gitlink=True)}
    diff = ''.join(changes.values()) if branch == 'all' else changes[branch]
    cfg = configuration(tmp_path)
    # A production marker neither grants nor denies deployment authority.
    (tmp_path / 'logs/harness/host-role').write_text('production\n')
    rt = FakeRuntime(tmp_path, diff)
    output = []
    path = d.deploy(rt, TARGET, emit=output.append)
    assert path.exists()
    actions = ['ff']
    if branch in ('submodule', 'all'):
        actions += ['submodule-update', 'make prepare-ipf-unpacker']
    if branch in ('static', 'all'):
        actions += ['make collectstatic-itos']
    if branch in ('application', 'all'):
        for region in d.REGIONS:
            actions += ['sudo systemctl reload uwsgi@' + region, 'systemctl is-active --quiet uwsgi@' + region,
                        'health ' + cfg['health_urls'][region]]
    assert [e for e in rt.events if e not in ('fetch', 'api') and not e.startswith('ancestor-')] == actions
    assert rt.events.count('fetch') == 1
    assert len(rt.requests) == 4
    assert rt.head == TARGET
    assert all(root == tmp_path for _args, _timeout, root in rt.commands)
    assert not any(args[0] not in ('git', 'make', 'sudo', 'systemctl') for args, _timeout, _root in rt.commands)
    assert any(args == ('git', 'fetch', '--no-tags', '--no-prune', '--no-recurse-submodules', '--refmap=',
                        'origin', 'refs/heads/master:refs/remotes/origin/master')
               for args, _timeout, _root in rt.commands)
    assert output[1:] == sorted({url for key in cfg['cache_urls']
                                 if branch in (key, 'all') for url in cfg['cache_urls'][key]})
    rows = records(tmp_path)
    assert rows[0]['stage'] == 'preflight'
    assert rows[-1]['stage'] == 'deployment' and rows[-1]['status'] == 'completed'
    assert rows[-1]['actual']['head'] == TARGET
    assert [row['stage'] for row in rows if row['status'] == 'started'][-1] == 'cache-urls'
    assert all('failed' != row['status'] for row in rows)


FAILURES = ['fetch', 'api', 'ff', 'submodule-update', 'make prepare-ipf-unpacker',
            'make collectstatic-itos'] + [e for r in d.REGIONS for e in
            ('sudo systemctl reload uwsgi@' + r, 'systemctl is-active --quiet uwsgi@' + r,
             'health https://' + r + '.example.invalid/health/')]


@pytest.mark.parametrize('failure', FAILURES)
def test_every_failure_stops_without_retry_and_retains_actual_state(tmp_path, failure):
    configuration(tmp_path)
    rt = FakeRuntime(tmp_path, raw('IPFUnpacker', gitlink=True) + raw('app/static/site.css') +
                     raw('app/views.py'))
    rt.fail = failure
    output = []
    with pytest.raises(ValueError, match='Injected'):
        d.deploy(rt, TARGET, emit=output.append)
    assert rt.events[-1] == failure
    assert rt.events.count(failure) == 1
    assert not output
    rows = records(tmp_path)
    assert rows[-1]['status'] == 'failed'
    assert rows[-1]['actual']['head'] == (OLD if failure in ('fetch', 'api', 'ff') else TARGET)
    assert 'Deployment command' not in json.dumps(rows)  # no subprocess body stored
    for name in LOCKS:
        inode = (tmp_path / name).stat().st_ino
        with d.fixed_lock(tmp_path / name):
            assert (tmp_path / name).stat().st_ino == inode


@pytest.mark.parametrize('reason', ['dirty', 'staged', 'untracked', 'subdirty', 'subunknown',
    'branch', 'origin', 'mapping', 'sha', 'ancestor', 'target-outside-master', 'migration',
    'operation', 'gitdir', 'alternate-index', 'target-not-exact', 'wrong-submodule-url', 'ci',
    'index-symlink', 'index-writable'])
def test_preflight_refusals_never_fast_forward(tmp_path, reason):
    configuration(tmp_path)
    rt = FakeRuntime(tmp_path, raw('docs/guide.md'))
    target = TARGET
    if reason in ('dirty', 'staged', 'untracked'):
        rt.dirty = {'dirty': ' M app.py\0', 'staged': 'M  app.py\0', 'untracked': '?? new.py\0'}[reason]
    elif reason == 'subdirty':
        rt.subdirty = '?? new.py\0'
    elif reason == 'subunknown':
        rt.substatus = '-' + OLD_LINK + ' IPFUnpacker\n'
    elif reason == 'branch':
        rt.branch = 'refs/heads/other'
    elif reason == 'origin':
        rt.origin = 'https://token@github.com/' + d.REPOSITORY + '.git'
    elif reason == 'mapping':
        rt.mapping = '+refs/*:refs/*'
    elif reason == 'sha':
        target = 'short'
    elif reason in ('ancestor', 'target-outside-master'):
        rt.fail = 'ancestor-' + (OLD if reason == 'ancestor' else TARGET)
    elif reason == 'migration':
        rt.diff = raw('app/migrations/0002.py')
    elif reason == 'operation':
        (tmp_path / '.git/MERGE_HEAD').write_text(OLD)
    elif reason == 'gitdir':
        rt.overrides[('rev-parse', '--absolute-git-dir')] = str(tmp_path / 'other')
    elif reason == 'alternate-index':
        rt.overrides[('rev-parse', '--git-path', 'index')] = str(tmp_path / 'other-index')
    elif reason == 'target-not-exact':
        rt.overrides[('rev-parse', '--verify', TARGET + '^{commit}')] = OLD
    elif reason == 'wrong-submodule-url':
        rt.overrides[('config', '--blob', TARGET + ':.gitmodules', '--list')] = 'unsafe'
    elif reason == 'ci':
        rt.rows[0]['conclusion'] = 'failure'
    elif reason == 'index-symlink':
        index = tmp_path / '.git/index'
        other = tmp_path / 'other-index'
        index.rename(other)
        index.symlink_to(other)
    elif reason == 'index-writable':
        (tmp_path / '.git/index').chmod(0o660)
    with pytest.raises(ValueError):
        d.deploy(rt, target)
    assert rt.head == OLD
    assert 'ff' not in rt.events


@pytest.mark.parametrize('name', ['logs', 'logs/harness', 'logs/harness/workflows'])
@pytest.mark.parametrize('mode', [0o770, 0o707])
def test_writable_deployment_directories_refused_without_repair(tmp_path, name, mode):
    rt = FakeRuntime(tmp_path, raw('docs/guide.md'))
    directory = tmp_path / name
    directory.chmod(mode)
    before = directory.stat()
    with pytest.raises(ValueError, match='Unsafe deployment directory'):
        d.deploy(rt, TARGET)
    after = directory.stat()
    assert (before.st_ino, before.st_uid, before.st_mode) == (after.st_ino, after.st_uid, after.st_mode)
    assert rt.head == OLD and not rt.commands and not rt.events
    assert not (tmp_path / 'logs/harness/deployments').exists()


@pytest.mark.parametrize('problem', ['missing', 'pending', 'failure', 'foreign-sha', 'foreign-app',
    'foreign-run', 'missing-suite', 'incomplete-page', 'too-many', 'repository', 'commit',
    'extra-pending', 'extra-failure', 'status-pending', 'status-failure', 'status-incomplete'])
def test_ci_fail_closed(tmp_path, problem):
    rt = FakeRuntime(tmp_path)
    if problem == 'missing':
        rt.rows.pop()
    elif problem in ('pending', 'failure'):
        rt.rows[0]['status'] = 'in_progress' if problem == 'pending' else 'completed'
        rt.rows[0]['conclusion'] = None if problem == 'pending' else 'failure'
    elif problem == 'foreign-sha':
        rt.rows[0]['head_sha'] = OLD
    elif problem == 'foreign-app':
        rt.rows[0]['app']['slug'] = 'unknown'
    elif problem == 'foreign-run':
        rt.rows[0]['details_url'] = 'https://github.com/other/repo/actions/runs/1'
    elif problem == 'missing-suite':
        rt.rows[0]['check_suite'] = {}
    elif problem in ('incomplete-page', 'too-many'):
        rt.check_count = 4 if problem == 'incomplete-page' else 101
    elif problem == 'repository':
        rt.repo['full_name'] = 'other/repo'
    elif problem == 'commit':
        rt.commit['sha'] = OLD
    elif problem.startswith('extra-'):
        extra = copy.deepcopy(rt.rows[0])
        extra.update(id=99, name='Extra check', status='in_progress' if problem == 'extra-pending'
                     else 'completed', conclusion=None if problem == 'extra-pending' else 'failure')
        rt.rows.append(extra)
    else:
        state = 'pending' if problem == 'status-pending' else 'failure'
        rt.statuses = dict(sha=TARGET, state=state, total_count=1,
                           statuses=[dict(id=1, context='extra', state=state,
                                          url=d.API + '/statuses/' + TARGET)])
        if problem == 'status-incomplete':
            rt.statuses.update(state='success', total_count=2)
            rt.statuses['statuses'][0]['state'] = 'success'
    with pytest.raises(ValueError):
        d.ci_evidence(rt, TARGET)
    assert rt.head == OLD


def test_native_selection_skip_and_latest_policy(tmp_path):
    rt = FakeRuntime(tmp_path)
    template = rt.rows[0]
    for index, name in enumerate([git_publish.SELECTION] + sorted(git_publish.HEAVY_EXECUTION), 10):
        row = copy.deepcopy(template)
        row.update(id=index, name=name, conclusion='success' if name == git_publish.SELECTION else 'skipped')
        rt.rows.append(row)
    assert d.ci_evidence(rt, TARGET)['required'] == {name: 'success' for name in git_publish.REQUIRED}
    latest = copy.deepcopy(rt.rows[0])
    latest.update(id=100, status='in_progress', conclusion=None)
    rt.rows.append(latest)
    with pytest.raises(ValueError):
        d.ci_evidence(rt, TARGET)


@pytest.mark.parametrize('name', LOCKS)
@pytest.mark.parametrize('unsafe', ['busy', 'symlink', 'hardlink', 'fifo', 'writable', 'owner'])
def test_locks_preserve_inode_owner_mode_and_refuse_unsafe(tmp_path, name, unsafe, monkeypatch):
    configuration(tmp_path)
    rt = FakeRuntime(tmp_path)
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    other = tmp_path / 'other'
    other.write_text('historical\n')
    handle = None
    if unsafe == 'symlink':
        path.symlink_to(other)
    elif unsafe == 'hardlink':
        os.link(str(other), str(path))
    elif unsafe == 'fifo':
        os.mkfifo(str(path))
    else:
        path.write_text('historical\n')
        path.chmod(0o666 if unsafe == 'writable' else 0o640)
        if unsafe == 'busy':
            handle = path.open('a')
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if unsafe == 'owner':
            from types import SimpleNamespace

            real_fstat = os.fstat
            target = path.stat()
            identity = (target.st_dev, target.st_ino)
            proxy = SimpleNamespace(**vars(os))

            def foreign_owner(fd):
                info = real_fstat(fd)
                if (info.st_dev, info.st_ino) == identity:
                    values = list(info)
                    values[4] = info.st_uid + 1
                    return os.stat_result(values)
                return info
            proxy.fstat = foreign_owner
    before = path.lstat()
    try:
        with pytest.raises(ValueError):
            if unsafe == 'owner':
                with monkeypatch.context() as patch:
                    patch.setattr(d, 'os', proxy)
                    d.deploy(rt, TARGET)
            else:
                d.deploy(rt, TARGET)
    finally:
        if handle is not None:
            handle.close()
    after = path.lstat()
    assert (before.st_ino, before.st_uid, before.st_mode) == (after.st_ino, after.st_uid, after.st_mode)
    if unsafe in ('busy', 'writable', 'owner', 'hardlink'):
        assert path.read_text() == 'historical\n'
    assert not rt.events
    assert rt.head == OLD


@pytest.mark.parametrize('problem', ['malformed', 'public', 'symlink', 'unknown-key',
                                    'url-secret', 'missing-region'])
def test_config_errors_precede_source_mutation(tmp_path, problem):
    cfg = configuration(tmp_path)
    path = tmp_path / 'logs/harness/deploy-local.json'
    if problem == 'malformed':
        path.write_text('{')
    elif problem == 'public':
        path.chmod(0o644)
    elif problem == 'symlink':
        other = tmp_path / 'other-config'
        path.rename(other)
        path.symlink_to(other)
    else:
        if problem == 'unknown-key':
            cfg['unexpected'] = True
        elif problem == 'url-secret':
            cfg['health_urls']['itos'] = 'https://secret@example.invalid/'
        else:
            cfg['health_urls'].pop('ktos')
        path.write_text(json.dumps(cfg))
    rt = FakeRuntime(tmp_path, raw('app/views.py'))
    with pytest.raises(ValueError):
        d.deploy(rt, TARGET)
    assert rt.head == OLD and 'ff' not in rt.events
    if problem != 'missing-region':
        assert not rt.commands


def test_no_config_is_valid_for_docs_but_application_requires_urls(tmp_path):
    rt = FakeRuntime(tmp_path, raw('docs/guide.md'))
    d.deploy(rt, TARGET, emit=lambda line: None)
    assert rt.head == TARGET
    other = tmp_path / 'another-checkout'
    other.mkdir()
    application = FakeRuntime(other, raw('app/views.py'))
    with pytest.raises(ValueError, match='health URLs'):
        d.deploy(application, TARGET)
    assert application.head == OLD and 'ff' not in application.events


def test_existing_lock_contents_and_metadata_survive_success(tmp_path):
    rt = FakeRuntime(tmp_path, raw('docs/guide.md'))
    before = {}
    for name in LOCKS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('keep\n')
        path.chmod(0o640)
        info = path.stat()
        before[name] = (info.st_ino, info.st_uid, info.st_mode)
    d.deploy(rt, TARGET, emit=lambda line: None)
    for name in LOCKS:
        path = tmp_path / name
        info = path.stat()
        assert (info.st_ino, info.st_uid, info.st_mode) == before[name]
        assert path.read_text() == 'keep\n'


def test_http_limits_no_redirect_or_page_following(tmp_path, monkeypatch):
    # Exercise the real bounded GET implementation with an entirely fake transport.
    calls = []

    class Socket:
        def settimeout(self, value):
            assert 0 < value <= d.HTTP_TIMEOUT

    class Response:
        status = 200
        headers = {}
        body = b'{}'

        def getheader(self, key):
            return self.headers.get(key)

        def read1(self, size):
            chunk, self.body = self.body[:size], self.body[size:]
            return chunk

    class Connection:
        def __init__(self, host, port, timeout):
            calls.append((host, port, timeout))
            self.sock = Socket()

        def connect(self):
            pass

        def request(self, method, path, headers):
            assert method == 'GET' and 'Authorization' not in headers
            calls.append(path)

        def getresponse(self):
            return response

        def close(self):
            calls.append('close')

    # Exercise the transport directly; the public network seam stays blocked.
    monkeypatch.setattr(d.http.client, 'HTTPSConnection', Connection)
    response = Response()
    assert d._public_get(d.API) == b'{}'
    for headers, status in [({'Link': '<next>; rel="next"'}, 200), ({}, 302),
                             ({'Content-Length': str(d.HTTP_LIMIT + 1)}, 200),
                             ({'Content-Length': '10'}, 200), ({'Content-Length': '-1'}, 200)]:
        response = Response()
        response.headers, response.status = headers, status
        before = len(calls)
        with pytest.raises(ValueError):
            d._public_get(d.API)
        assert calls[before:].count('close') == 1
        assert len(calls[before:]) == 3  # one connection and one request, no retry
    response = Response()
    response.body = b'x' * (d.HTTP_LIMIT + 1)
    with pytest.raises(ValueError, match='size limit'):
        d._public_get(d.API)


def test_total_http_deadline_covers_connect_and_restores_alarm(monkeypatch):
    previous = object()
    handlers = [previous]
    timers = []
    monkeypatch.setattr(d.signal, 'getitimer', lambda kind: (0.0, 0.0))
    monkeypatch.setattr(d.signal, 'setitimer', lambda kind, seconds: timers.append(seconds))
    monkeypatch.setattr(d.signal, 'getsignal', lambda kind: handlers[0])
    monkeypatch.setattr(d.signal, 'signal', lambda kind, handler: handlers.__setitem__(0, handler))

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            # A stuck resolver or header parser receives the same process deadline.
            d.signal.getsignal(d.signal.SIGALRM)(d.signal.SIGALRM, None)

        def close(self):
            pass
    monkeypatch.setattr(d.http.client, 'HTTPSConnection', Connection)
    with pytest.raises(ValueError, match='deadline'):
        BOUNDED_GET(d.API)
    assert timers == [d.HTTP_TIMEOUT, 0]
    assert d.signal.getsignal(d.signal.SIGALRM) == previous


def test_http_does_not_replace_an_existing_timer(monkeypatch):
    monkeypatch.setattr(d.signal, 'getitimer', lambda kind: (5.0, 0.0))
    with pytest.raises(ValueError, match='active alarm'):
        BOUNDED_GET(d.API)


def test_runtime_preserves_environment_and_uses_argv(monkeypatch, tmp_path):
    captured = []

    class Process:
        returncode = 0

        def __init__(self, args, **kwargs):
            captured.append((args, kwargs))

        def communicate(self, timeout):
            return b'', b''
    monkeypatch.setattr(d.subprocess, 'Popen', Process)
    monkeypatch.setenv('DEPLOY_OPERATOR_FIXTURE', 'preserved')
    rt = d.Runtime(tmp_path)
    rt.command(['make', 'collectstatic-itos'], timeout=600)
    rt.git('fetch', '--no-recurse-submodules', 'origin')
    assert captured[0][0] == ['make', 'collectstatic-itos']
    for args, options in captured:
        assert isinstance(args, list)
        assert options['shell'] is False and options['cwd'] == str(tmp_path)
        assert options['start_new_session'] is True
        assert 'env' not in options
    assert captured[1][0][:1 + len(d.GIT_OPTIONS)] == ['git'] + d.GIT_OPTIONS
    assert os.environ['DEPLOY_OPERATOR_FIXTURE'] == 'preserved'


def test_command_timeout_cleans_child_group_without_restarting(monkeypatch, tmp_path):
    calls = []

    class Process:
        pid = 123456

        def __init__(self, args, **kwargs):
            calls.append(('spawn', args))
            self.attempts = 0

        def communicate(self, timeout):
            self.attempts += 1
            if self.attempts == 1:
                raise d.subprocess.TimeoutExpired('fixture', timeout)
            calls.append(('reap', timeout))
            return b'', b''
    monkeypatch.setattr(d.subprocess, 'Popen', Process)
    monkeypatch.setattr(d.os, 'killpg', lambda pid, sig: calls.append(('kill-group', pid, sig)))
    with pytest.raises(ValueError, match='no retry'):
        d.Runtime(tmp_path).command(['make', 'prepare-ipf-unpacker'], timeout=1)
    assert calls == [('spawn', ['make', 'prepare-ipf-unpacker']),
                     ('kill-group', 123456, d.signal.SIGKILL), ('reap', 10)]


def test_partial_fast_forward_failure_records_actual_head(tmp_path):
    rt = FakeRuntime(tmp_path, raw('app/static/site.css'))
    original = rt.git

    def failed_after_mutation(*args):
        result = original(*args)
        if args[:2] == ('merge', '--ff-only'):
            raise ValueError('Injected failure after ff.')
        return result
    rt.git = failed_after_mutation
    with pytest.raises(ValueError, match='after ff'):
        d.deploy(rt, TARGET)
    assert rt.head == TARGET
    assert not any(event.startswith('make ') for event in rt.events)
    assert records(tmp_path)[-1]['actual']['head'] == TARGET


def test_durable_record_failure_blocks_fast_forward(tmp_path, monkeypatch):
    rt = FakeRuntime(tmp_path, raw('docs/guide.md'))
    original = d.Journal.write

    def fail_old_state(self, stage, status, **evidence):
        if stage == 'preflight' and status == 'completed':
            raise OSError('Injected disk failure.')
        return original(self, stage, status, **evidence)
    monkeypatch.setattr(d.Journal, 'write', fail_old_state)
    with pytest.raises(OSError):
        d.deploy(rt, TARGET)
    assert rt.head == OLD and 'ff' not in rt.events
    assert records(tmp_path)[-1]['status'] == 'failed'


def test_cache_output_failure_preserves_result_without_repeating(tmp_path):
    configuration(tmp_path)
    rt = FakeRuntime(tmp_path, raw('app/static/site.css'))
    output = []

    def broken_output(line):
        output.append(line)
        raise ValueError('Injected output failure.')
    with pytest.raises(ValueError, match='output failure'):
        d.deploy(rt, TARGET, emit=broken_output)
    assert len(output) == 1
    assert rt.events.count('make collectstatic-itos') == 1
    assert records(tmp_path)[-1]['stage'] == 'cache-urls'
    assert records(tmp_path)[-1]['status'] == 'failed'


# Preserve the implementation before the autouse offline guard replaces the public seam.
BOUNDED_GET = d.public_get
