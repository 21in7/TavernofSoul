"""Explicit manual deployment, preserving the operator's existing session environment.

No migrations, credentials/API writes, retries, rollback or host-role authorization.
The CLI is for an authorized operator; workflow workers only write offline tests.
"""
import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
import threading
from urllib.parse import urlsplit

from harness import host_role

ROOT = host_role.ROOT
REPOSITORY = '21in7/TavernofSoul'
ORIGIN = 'https://github.com/' + REPOSITORY + '.git'
API = 'https://api.github.com/repos/' + REPOSITORY
UNPACKER = 'https://github.com/21in7/IPFUnpacker.git'
REGIONS = ('itos', 'jtos', 'ktos')
SHA = re.compile(r'[0-9a-f]{40}')
HTTP_LIMIT = 2 * 1024 * 1024
HTTP_TIMEOUT = 10
GIT_OPTIONS = ['-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
               '-c', 'merge.autoStash=false',
               '-c', 'submodule.recurse=false', '-c', 'fetch.recurseSubmodules=false',
               '-c', 'credential.helper=', '-c', 'credential.interactive=false',
               '-c', 'core.askPass=/bin/false', '-c', 'protocol.allow=never',
               '-c', 'protocol.https.allow=always']


class DeployError(ValueError):
    """Fixed operator diagnostic, safe for results and the terminal."""


def require(condition, message):
    if not condition:
        raise DeployError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def load_json(body):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON field.')
            result[key] = value
        return result

    def invalid(_value):
        raise DeployError('Non-finite JSON number.')
    try:
        return json.loads(body, object_pairs_hook=unique, parse_constant=invalid)
    except (json.JSONDecodeError, UnicodeError):
        raise DeployError('Malformed deployment JSON evidence or configuration.') from None


def url_parts(url, health=False):
    require(isinstance(url, str) and len(url) <= 2048 and url.isascii() and
            not any(ord(c) <= 32 or ord(c) == 127 for c in url), 'Unsafe explicit URL.')
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise DeployError('Malformed explicit URL.') from None
    require(parts.scheme in (('http', 'https') if health else ('https',)) and
            parts.hostname and not parts.username and not parts.password and
            not parts.query and not parts.fragment and '\\' not in url and
            (port is None or 1 <= port <= 65535), 'Unsafe explicit URL.')
    return parts


def public_get(url):
    """One bounded GET on the Linux operator CLI's main thread.

    A process timer also bounds DNS and slow headers, which socket timeouts alone
    do not bound. Do not replace an existing caller's timer or handler.
    """
    require(threading.current_thread() is threading.main_thread() and
            signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0),
            'GET requires the operator CLI main thread without an active alarm.')
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_number, _frame):
        raise DeployError('HTTP response deadline exceeded.')
    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, HTTP_TIMEOUT)
        return _public_get(url)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _public_get(url):
    """No proxy, authentication, redirect, retry or pagination followup; body <=2 MiB."""
    parts = urlsplit(url)
    require(parts.scheme in ('http', 'https') and parts.hostname and
            not parts.username and not parts.password, 'Unsafe GET destination.')
    connection_type = (http.client.HTTPSConnection if parts.scheme == 'https'
                       else http.client.HTTPConnection)
    connection = connection_type(parts.hostname, parts.port, timeout=HTTP_TIMEOUT)
    deadline = time.monotonic() + HTTP_TIMEOUT
    try:
        connection.connect()
        sock = connection.sock
        sock.settimeout(max(0.001, deadline - time.monotonic()))
        path = parts.path or '/'
        if parts.query:
            path += '?' + parts.query
        connection.request('GET', path, headers={
            'Accept': 'application/vnd.github+json' if url.startswith(API) else '*/*',
            'User-Agent': 'TavernofSoul-manual-deploy',
            'X-GitHub-Api-Version': '2022-11-28', 'Connection': 'close'})
        sock.settimeout(max(0.001, deadline - time.monotonic()))
        response = connection.getresponse()
        require(response.status == 200, 'GET did not return HTTP 200.')
        require(not response.getheader('Link'), 'Pagination is refused; one complete page required.')
        length = response.getheader('Content-Length')
        require(length is None or (length.isdigit() and int(length) <= HTTP_LIMIT),
                'HTTP response exceeds its size limit.')
        body = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'HTTP response deadline exceeded.')
            sock.settimeout(remaining)
            chunk = response.read1(min(65536, HTTP_LIMIT + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            require(len(body) <= HTTP_LIMIT, 'HTTP response exceeds its size limit.')
        require(time.monotonic() <= deadline and
                (length is None or len(body) == int(length)), 'Incomplete or late HTTP response.')
        return bytes(body)
    finally:
        connection.close()


class Runtime:
    """Inject command/HTTP seams in tests; never log command output or response bodies."""
    def __init__(self, root=ROOT):
        self.root = Path(root).absolute()

    def command(self, args, timeout=120):
        process = None
        try:
            process = subprocess.Popen(args, cwd=str(self.root), shell=False,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True)
            stdout, _stderr = process.communicate(timeout=timeout)
        except BaseException as exc:
            # A timed-out make must not leave its compiler children running after
            # the deployment releases the fixed locks. This is process cleanup,
            # never a retry or source/service rollback.
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate(timeout=10)
            if isinstance(exc, (OSError, subprocess.SubprocessError)):
                raise DeployError('Deployment command could not complete; no retry.') from None
            raise
        require(process.returncode == 0, 'Deployment command failed; no retry.')
        return stdout.decode('utf-8', errors='strict')

    def git(self, *args):
        return self.command(['git'] + GIT_OPTIONS + list(args))

    def request(self, url):
        return load_json(public_get(url))

    def health(self, url):
        public_get(url)


def ensure_directory(path, private=False):
    """Create only missing components; preserve existing ownership and modes."""
    path = Path(path).absolute()
    parent = host_role.open_directory(path.parent)
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o022 and
                (not private or stat.S_IMODE(info.st_mode) == 0o700),
                'Unsafe deployment directory; operator must reconcile it.')
    finally:
        os.close(fd)


@contextmanager
def fixed_lock(path):
    """Keep the historical inode, owner and mode. Never truncate, unlink or wait."""
    parent = host_role.open_directory(path.parent)
    fd = None
    try:
        try:
            try:
                fd = os.open(path.name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL |
                             os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
                os.fsync(parent)
            except FileExistsError:
                fd = os.open(path.name, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW |
                             os.O_NONBLOCK, dir_fd=parent)
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                    info.st_nlink == 1 and not info.st_mode & 0o022,
                    'Unsafe deployment lock; operator must reconcile it.')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            attached = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            require((info.st_dev, info.st_ino) == (attached.st_dev, attached.st_ino),
                    'Deployment lock attachment changed.')
        except OSError:
            raise DeployError('Deployment lock is busy or unsafe; no wait or forced release.') from None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


class Journal:
    """New private append-only JSONL result; every event and creation is durable."""
    def __init__(self, directory):
        self.path = directory / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') +
                                 '-' + secrets.token_hex(8) + '.jsonl')
        parent = host_role.open_directory(directory)
        self.fd = None
        try:
            self.fd = os.open(self.path.name, os.O_WRONLY | os.O_APPEND | os.O_CREAT |
                              os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            require(stat.S_IMODE(os.fstat(self.fd).st_mode) == 0o600,
                    'Cannot create a private deployment result.')
            os.fsync(self.fd)
            os.fsync(parent)
        except BaseException:
            if self.fd is not None:
                os.close(self.fd)
            raise
        finally:
            os.close(parent)

    def write(self, stage, status, **evidence):
        data = (json.dumps(dict(time=now(), stage=stage, status=status, **evidence),
                           sort_keys=True) + '\n').encode('utf-8')
        while data:
            count = os.write(self.fd, data)
            require(count > 0, 'Cannot persist deployment evidence.')
            data = data[count:]
        os.fsync(self.fd)

    def close(self):
        os.close(self.fd)


def config(root):
    try:
        body = host_role.read_file(root / 'logs/harness/deploy-local.json', 32768, private=True)
    except FileNotFoundError:
        return {'version': 1, 'health_urls': {},
                'cache_urls': {'static': [], 'application': [], 'submodule': []}}
    except (OSError, ValueError):
        raise DeployError('Cannot safely read deployment configuration.') from None
    cfg = load_json(body)
    require(isinstance(cfg, dict) and set(cfg) == {'version', 'health_urls', 'cache_urls'} and
            type(cfg['version']) is int and cfg['version'] == 1 and
            isinstance(cfg['health_urls'], dict) and set(cfg['health_urls']) <= set(REGIONS) and
            isinstance(cfg['cache_urls'], dict) and
            set(cfg['cache_urls']) == {'static', 'application', 'submodule'},
            'Malformed deployment configuration.')
    for url in cfg['health_urls'].values():
        url_parts(url, health=True)
    for urls in cfg['cache_urls'].values():
        require(isinstance(urls, list) and len(urls) <= 100, 'Malformed cache URL list.')
        for url in urls:
            url_parts(url)
    return cfg


def diff_plan(raw):
    if not raw:
        return {'static': False, 'application': False, 'submodule': False}
    records = raw.split('\0')
    require(records[-1] == '', 'Incomplete diff evidence.')
    records.pop()
    paths, gitlinks = [], set()
    index = 0
    while index < len(records):
        match = re.fullmatch(r':([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}) ([0-9a-f]{40}) '
                             r'([AMDT]|R[0-9]{1,3})', records[index])
        index += 1
        require(match and index < len(records), 'Unsupported or incomplete target diff.')
        row = [records[index]]
        index += 1
        if match.group(5).startswith('R'):
            require(index < len(records), 'Incomplete rename evidence.')
            row.append(records[index])
            index += 1
        for name in row:
            require(name and not name.startswith('/') and
                    all(part not in ('', '.', '..') for part in name.split('/')) and
                    not any(ord(c) < 32 or ord(c) == 127 for c in name), 'Unsafe diff path.')
            require('migrations' not in name.split('/'),
                    'Migration changes require a separate deployment.')
            if '160000' in match.group(1, 2):
                require(name == 'IPFUnpacker' and match.group(1, 2) == ('160000', '160000') and
                        match.group(5) == 'M', 'Unknown or structural submodule change refused.')
                gitlinks.add(name)
            paths.append(name)
    runtime = [p for p in paths if not p.startswith('docs/')]
    static = any('static' in p.split('/') or 'staticfiles' in p.split('/') or
                 Path(p).suffix.lower() in {'.css', '.js', '.mjs', '.svg', '.png', '.jpg', '.jpeg',
                                           '.gif', '.webp', '.avif', '.bmp', '.ico', '.woff', '.woff2',
                                           '.ttf', '.otf', '.eot', '.map', '.scss', '.sass', '.less', '.wasm'}
                 for p in runtime)
    application = any(Path(p).suffix.lower() in {'.py', '.html', '.htm', '.jinja', '.jinja2',
                                                '.j2', '.tpl', '.tmpl'} or
                      'templates' in p.split('/') for p in runtime)
    return {'static': static, 'application': application, 'submodule': bool(gitlinks)}


def ci_evidence(rt, target):
    # Reuse native latest run/suite/selection/execution-skip policy without relaxation.
    from harness import git_publish
    repository = rt.request(API)
    require(isinstance(repository, dict) and repository.get('full_name') == REPOSITORY and
            repository.get('url') == API and repository.get('fork') is True and
            repository.get('default_branch') == 'master' and repository.get('archived') is False,
            'GitHub fork identity mismatch.')
    commit = rt.request(API + '/commits/' + target)
    require(isinstance(commit, dict) and commit.get('sha') == target and
            commit.get('url') == API + '/commits/' + target, 'GitHub commit identity mismatch.')
    checks = rt.request(API + '/commits/' + target + '/check-runs?filter=all&per_page=100&page=1')
    require(isinstance(checks, dict) and isinstance(checks.get('check_runs'), list) and
            type(checks.get('total_count')) is int and
            0 < checks['total_count'] == len(checks['check_runs']) <= 100,
            'Incomplete checks; at most one complete page is permitted.')
    rows = checks['check_runs']
    ids = set()
    for row in rows:
        require(isinstance(row, dict) and type(row.get('id')) is int and row['id'] > 0 and
                row['id'] not in ids and git_publish.check_suite_id(row) is not None and
                isinstance(row.get('app'), dict) and row['app'].get('slug') == 'github-actions' and
                isinstance(row.get('details_url'), str) and
                re.fullmatch(r'https://github\.com/' + REPOSITORY +
                             r'/actions/runs/[1-9][0-9]*(?:/job/[1-9][0-9]*)?', row['details_url']),
                'Malformed suite or foreign check evidence.')
        ids.add(row['id'])
    passed, states = git_publish.checks_gate(rows, {
        'check_app': 'github-actions', 'required_checks': sorted(git_publish.REQUIRED)}, target)
    require(passed, 'CI is missing, pending or unsuccessful.')
    statuses = rt.request(API + '/commits/' + target + '/status?per_page=100&page=1')
    require(isinstance(statuses, dict) and statuses.get('sha') == target and
            isinstance(statuses.get('statuses'), list) and type(statuses.get('total_count')) is int and
            0 <= statuses['total_count'] == len(statuses['statuses']) <= 100 and
            ((not statuses['total_count'] and statuses.get('state') in ('pending', 'success')) or
             (statuses['total_count'] > 0 and statuses.get('state') == 'success')) and
            all(isinstance(row, dict) and row.get('state') == 'success' and
                type(row.get('id')) is int and row['id'] > 0 and
                isinstance(row.get('context'), str) and bool(row['context']) and
                row.get('url') == API + '/statuses/' + target
                for row in statuses['statuses']),
            'Commit statuses failed, pending, malformed or incomplete.')
    canonical = json.dumps({'checks': checks, 'statuses': statuses}, sort_keys=True).encode('utf-8')
    return {'sha': target, 'repository': REPOSITORY, 'checked_at': now(), 'required': states,
            'check_ids': sorted(ids), 'evidence_sha256': hashlib.sha256(canonical).hexdigest()}


def identity(rt):
    metadata = host_role.open_directory(rt.root / '.git')
    try:
        index = os.stat('index', dir_fd=metadata, follow_symlinks=False)
        require(stat.S_ISREG(index.st_mode) and index.st_nlink == 1 and
                index.st_uid == os.geteuid() and not index.st_mode & 0o022,
                'Unsafe repository index.')
    finally:
        os.close(metadata)
    require(rt.git('rev-parse', '--show-toplevel').strip() == str(rt.root) and
            rt.git('rev-parse', '--absolute-git-dir').strip() == str(rt.root / '.git') and
            Path(os.path.abspath(str(rt.root / rt.git('rev-parse', '--git-path', 'index').strip()))) ==
            rt.root / '.git/index' and
            rt.git('rev-parse', '--is-bare-repository').strip() == 'false',
            'Deploy requires this repository root and a regular checkout.')
    require(rt.git('symbolic-ref', '--quiet', 'HEAD').strip() == 'refs/heads/master',
            'Deploy requires the master branch.')
    require(rt.git('config', '--get-all', 'remote.origin.url').splitlines() == [ORIGIN] and
            rt.git('remote', 'get-url', '--all', 'origin').splitlines() == [ORIGIN] and
            rt.git('remote', 'get-url', '--push', '--all', 'origin').splitlines() == [ORIGIN],
            'Origin must be the credential-free approved fork.')
    mapping = rt.git('config', '--get-all', 'remote.origin.fetch').splitlines()
    require(mapping in ([ '+refs/heads/*:refs/remotes/origin/*'],
                        [ '+refs/heads/master:refs/remotes/origin/master']),
            'Unsafe origin fetch mapping.')
    require(rt.git('-C', 'IPFUnpacker', 'config', '--get-all', 'remote.origin.url').splitlines() ==
            [UNPACKER] and
            rt.git('-C', 'IPFUnpacker', 'remote', 'get-url', '--all', 'origin').splitlines() ==
            [UNPACKER], 'Unsafe IPFUnpacker origin.')


def gitlink(rt, commit):
    row = rt.git('ls-tree', commit, '--', 'IPFUnpacker')
    match = re.fullmatch(r'160000 commit ([0-9a-f]{40})\tIPFUnpacker\n?', row)
    require(match is not None, 'Missing or unknown IPFUnpacker gitlink.')
    # Fixed approved submodule path and source, checked in BOTH trees before ff.
    entries = rt.git('config', '--blob', commit + ':.gitmodules', '--list').splitlines()
    require(sorted(entries) == sorted(['submodule.IPFUnpacker.path=IPFUnpacker',
                                      'submodule.IPFUnpacker.url=' + UNPACKER]),
            'Unsupported target submodule configuration.')
    return match.group(1)


def clean_state(rt):
    for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply',
                 'sequencer', 'BISECT_LOG', 'index.lock', 'HEAD.lock', 'packed-refs.lock',
                 'config.lock', 'shallow.lock', 'refs/heads/master.lock'):
        require(not os.path.lexists(str(rt.root / '.git' / name)),
                'In-progress Git operation refused.')
    require(not rt.git('status', '--porcelain=v1', '-z', '--untracked-files=all',
                       '--ignore-submodules=none'), 'Dirty/staged/untracked checkout refused.')
    old = rt.git('rev-parse', '--verify', 'HEAD').strip()
    require(SHA.fullmatch(old), 'Malformed current HEAD.')
    link = gitlink(rt, old)
    state = rt.git('submodule', 'status', '--recursive')
    require(re.fullmatch(r' ' + link + r' IPFUnpacker(?: \([^\n]*\))?\n?', state),
            'Submodule dirty, unknown or uninitialized.')
    require(rt.git('-C', 'IPFUnpacker', 'rev-parse', '--verify', 'HEAD').strip() == link and
            not rt.git('-C', 'IPFUnpacker', 'status', '--porcelain=v1', '-z',
                       '--untracked-files=all', '--ignore-submodules=none'),
            'Submodule checkout is dirty or unknown.')
    return old, link


def actual_state(rt):
    result = {}
    for key, args in (('head', ('rev-parse', '--verify', 'HEAD')),
                      ('submodule_head', ('-C', 'IPFUnpacker', 'rev-parse', '--verify', 'HEAD'))):
        try:
            value = rt.git(*args).strip()
            result[key] = value if SHA.fullmatch(value) else 'unknown'
        except (ValueError, OSError, UnicodeError):
            result[key] = 'unknown'
    for key, args in (('checkout_clean', ('status', '--porcelain=v1', '-z', '--untracked-files=all',
                                         '--ignore-submodules=none')),
                      ('submodule_clean', ('-C', 'IPFUnpacker', 'status', '--porcelain=v1', '-z',
                                          '--untracked-files=all', '--ignore-submodules=none'))):
        try:
            result[key] = not bool(rt.git(*args))
        except (ValueError, OSError, UnicodeError):
            result[key] = 'unknown'
    return result


def deploy(rt, target, emit=print):
    require(isinstance(target, str) and SHA.fullmatch(target),
            'COMMIT must be a full lowercase 40-hex SHA.')
    # No host-role check: the marker is deliberately not deployment authority.
    root_fd = host_role.open_directory(rt.root)
    os.close(root_fd)
    cfg = config(rt.root)  # malformed/unsafe config fails before Git fetch or source mutation
    for directory in (rt.root / 'logs', rt.root / 'logs/harness',
                      rt.root / 'logs/harness/workflows'):
        ensure_directory(directory)
    with ExitStack() as stack:
        # Execution mutex first, then cron, then source mutex; all nonblocking.
        for name in ('logs/harness/workflows/.workflow-lock', 'logs/cron-tos.lock',
                     'logs/harness/workflows/.lock'):
            stack.enter_context(fixed_lock(rt.root / name))
        directory = rt.root / 'logs/harness/deployments'
        ensure_directory(directory, private=True)
        journal = Journal(directory)
        stack.callback(journal.close)
        stage = 'preflight'

        def step(name, action):
            nonlocal stage
            stage = name
            journal.write(name, 'started')
            result = action()
            journal.write(name, 'completed', actual=actual_state(rt))
            return result

        try:
            journal.write(stage, 'started', target=target)
            identity(rt)
            old, old_link = clean_state(rt)
            rt.git('fetch', '--no-tags', '--no-prune', '--no-recurse-submodules', '--refmap=', 'origin',
                   'refs/heads/master:refs/remotes/origin/master')
            fetched = rt.git('rev-parse', '--verify', 'refs/remotes/origin/master').strip()
            require(SHA.fullmatch(fetched), 'Malformed fetched master.')
            require(rt.git('rev-parse', '--verify', target + '^{commit}').strip() == target,
                    'Target commit is not exactly the requested SHA.')
            rt.git('merge-base', '--is-ancestor', old, target)
            rt.git('merge-base', '--is-ancestor', target, fetched)
            plan = diff_plan(rt.git('diff', '--raw', '--no-abbrev', '--no-ext-diff',
                                   '--no-textconv', '-z', '--find-renames', old, target, '--'))
            new_link = gitlink(rt, target)
            require(plan['submodule'] == (old_link != new_link), 'Inconsistent gitlink evidence.')
            require(not plan['application'] or set(cfg['health_urls']) == set(REGIONS),
                    'Application deployment requires explicit health URLs for all three regions.')
            ci = ci_evidence(rt, target)
            # Recheck after network inspection, still holding every historical mutex.
            identity(rt)
            require(clean_state(rt) == (old, old_link) and
                    rt.git('rev-parse', '--verify', 'refs/remotes/origin/master').strip() == fetched,
                    'Checkout changed during preflight.')
            journal.write('preflight', 'completed', old_head=old, target=target, branch='master',
                          fetched_master=fetched, plan=plan, ci=ci,
                          submodule={'old': old_link, 'target': new_link}, actual=actual_state(rt))

            def fast_forward():
                rt.git('merge', '--ff-only', '--no-edit', target)
                require(rt.git('rev-parse', '--verify', 'HEAD').strip() == target,
                        'Actual HEAD differs from target after fast-forward.')
            step('fast-forward', fast_forward)
            if plan['submodule']:
                def update():
                    rt.git('-c', 'submodule.IPFUnpacker.url=' + UNPACKER,
                           '-c', 'submodule.IPFUnpacker.update=checkout', 'submodule', 'update',
                           '--init', '--checkout', '--', 'IPFUnpacker')
                    require(rt.git('-C', 'IPFUnpacker', 'rev-parse', '--verify', 'HEAD').strip() ==
                            new_link, 'Updated submodule differs from the approved gitlink.')
                    require(clean_state(rt) == (target, new_link), 'Updated checkout is not clean.')
                step('submodule-update', update)
                step('prepare-ipf-unpacker', lambda: rt.command(['make', 'prepare-ipf-unpacker'],
                                                               timeout=1800))
            if plan['static']:
                step('collectstatic-itos', lambda: rt.command(['make', 'collectstatic-itos'], timeout=600))
            if plan['application']:
                for region in REGIONS:
                    unit = 'uwsgi@' + region
                    step('reload-' + region,
                         lambda unit=unit: rt.command(['sudo', 'systemctl', 'reload', unit], timeout=60))
                    step('is-active-' + region,
                         lambda unit=unit: rt.command(['systemctl', 'is-active', '--quiet', unit], timeout=10))
                    step('http-' + region, lambda region=region: rt.health(cfg['health_urls'][region]))
            urls = sorted({url for branch, enabled in plan.items() if enabled
                           for url in cfg['cache_urls'][branch]})

            def cache_output():
                emit('Cloudflare cache purge candidate URLs (manual purge only):')
                for url in urls:
                    emit(url)
            step('cache-urls', cache_output)
            journal.write('deployment', 'completed', target=target, actual=actual_state(rt),
                          cache_url_count=len(urls))
            return journal.path
        except BaseException as exc:
            # Fixed reason only: never persist source, response bodies, stderr or secrets.
            journal.write(stage, 'failed', reason=(str(exc) if isinstance(exc, DeployError)
                          else 'Stopped; no retry or automatic rollback.'),
                          actual=actual_state(rt))
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args(argv)
    try:
        result = deploy(Runtime(), args.commit)
    except DeployError as exc:
        print('Deployment refused or stopped: ' + str(exc) +
              ' Inspect any private result; no retry or rollback was attempted.', file=sys.stderr)
        return 1
    except (ValueError, OSError, UnicodeError, http.client.HTTPException, subprocess.SubprocessError):
        print('Deployment refused or stopped. Inspect the private result and actual checkout; '
              'no retry or rollback was attempted.', file=sys.stderr)
        return 1
    print('Deployment result: ' + str(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
