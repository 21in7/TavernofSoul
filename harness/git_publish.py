"""Journal GitHub delivery through the parent Codex's authenticated connector.

The local CLI prepares and validates requests. The parent executes only the named
GitHub tools and returns their responses. No credentials or Git writes reach a
model; the real checkout, index, refs and staged user changes are never modified.
"""
import argparse
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import time

from harness import agent_models, workspace

ROOT = agent_models.ROOT
REPORTS = ROOT / 'logs/harness/workflows'
CONFIG = ROOT / 'harness/git-publish-config.json'
SHA = re.compile(r'^[a-f0-9]{40}$')
RUN_ID = re.compile(r'^[0-9]+-[a-f0-9]{6}$')
REQUIRED = {'Offline harness (SQLite)', 'MySQL harness', 'Chromium browser harness'}
TOOLS = {name: 'mcp__codex_apps__github_' + name for name in
         ('fetch', 'create_tree', 'create_commit', 'create_branch', 'create_pull_request',
          'merge_pull_request')}


def validate_config(cfg):
    fields = {'version', 'enabled', 'repository', 'base', 'merge_method',
              'required_checks', 'check_app', 'wait_seconds'}
    if not isinstance(cfg, dict) or set(cfg) != fields or cfg['version'] != 'github-v1' or type(cfg['enabled']) is not bool or \
            not isinstance(cfg['repository'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', cfg['repository']) or \
            not isinstance(cfg['base'], str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', cfg['base']) or \
            cfg['base'].startswith(('/', '-')) or cfg['base'].endswith(('/', '.')) or \
            '..' in cfg['base'] or '//' in cfg['base'] or cfg['base'].endswith('.lock') or \
            cfg['merge_method'] != 'squash' or cfg['check_app'] != 'github-actions' or \
            not isinstance(cfg['required_checks'], list) or \
            not all(isinstance(name, str) for name in cfg['required_checks']) or \
            set(cfg['required_checks']) != REQUIRED or \
            len(cfg['required_checks']) != len(REQUIRED) or type(cfg['wait_seconds']) is not int or \
            not 0 < cfg['wait_seconds'] <= 1800:
        raise ValueError('Invalid GitHub delivery policy.')
    return cfg


def load_config():
    return validate_config(json.loads(CONFIG.read_text(encoding='utf-8')))


def metadata(response):
    text = response.strip()
    if text.startswith('```json\n') and text.endswith('\n```'):
        text = text[8:-4]
    data = json.loads(text)
    limits = {'commit_message': 2000, 'pr_title': 120, 'pr_body': 16000}
    if not isinstance(data, dict) or set(data) != set(limits) or any(
            not isinstance(data[key], str) or not data[key].strip() or '\0' in data[key] or
            len(data[key].encode('utf-8')) > limit for key, limit in limits.items()):
        raise ValueError('Git role must return bounded commit_message, pr_title and pr_body strings.')
    if '\n' in data['pr_title'] or '\r' in data['pr_title']:
        raise ValueError('PR title must be one line.')
    return data


def origin_matches(root, repository):
    result = subprocess.run(['git', 'config', '--get', 'remote.origin.url'], cwd=str(root),
                            capture_output=True, text=True, timeout=10)
    url = result.stdout.strip()
    return result.returncode == 0 and url in (
        'https://github.com/' + repository, 'https://github.com/' + repository + '.git',
        'git@github.com:' + repository + '.git', 'ssh://git@github.com/' + repository + '.git')


def blob_sha(content):
    return hashlib.sha1(b'blob ' + str(len(content)).encode('ascii') + b'\0' + content).hexdigest()


def mode(item):
    return '100755' if item['mode'] & 0o111 else '100644'


def prepare(root, directory, report, baseline, validated, changes, policy, details):
    cfg = load_config()
    if not cfg['enabled'] or report.get('read_only') or report.get('simulated') or not changes:
        return {'status': 'skipped'}
    if not origin_matches(root, cfg['repository']):
        raise ValueError('Configured GitHub repository does not match the credential-free origin URL.')
    if not RUN_ID.fullmatch(report['run_id']):
        raise ValueError('Invalid GitHub run ID.')
    final_checks = report.get('delivery_validation', report.get('validation'))
    if report.get('review', {}).get('verdict') != 'approved' or not final_checks or \
            any(item.get('status') != 'passed' for item in final_checks):
        raise ValueError('Approved review and successful local checks are required.')
    workspace.enforce_scope(baseline, validated, report['scope'])
    candidate = Path(report['workspace'])
    if workspace.manifest(candidate, policy) != validated or set(changes) != set(workspace.changed(baseline, validated)):
        raise ValueError('Only the reviewed and validated candidate may be published.')
    entries = {}
    for name in changes:
        if workspace.protected(name):
            raise ValueError('Protected GitHub publication path.')
        old = baseline.get(name)
        if old:
            backup = workspace.safe_path(directory / 'backup', name)
            if workspace.fingerprint(backup, policy['max_file_bytes']) != old:
                raise ValueError('Publication baseline backup is missing or changed: ' + name)
            old = {'sha': blob_sha(backup.read_bytes()), 'mode': mode(old)}
        new = validated.get(name)
        if new:
            path = workspace.safe_path(candidate, name)
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != new['sha256']:
                raise ValueError('Candidate changed while preparing GitHub publication.')
            # Workflow diffs already require UTF-8; never silently encode a binary edit.
            text = content.decode('utf-8')
            new = {'sha': blob_sha(content), 'mode': mode(new), 'content': text}
        entries[name] = {'before': old, 'after': new}
    ledger = {'version': 'github-v1', 'run_id': report['run_id'], 'config': cfg,
              'metadata': metadata(json.dumps(details)), 'branch': 'codex/' + report['run_id'],
              'status': 'awaiting_connector', 'step': 'repository', 'files': entries,
              'events': [], 'deadline': time.time() + cfg['wait_seconds'], 'checks': {}}
    directory.chmod(0o700)
    approval = {'config': cfg, 'run_id': report['run_id'], 'workspace': str(candidate),
                'max_file_bytes': policy['max_file_bytes'],
                'files': {name: {'before': baseline.get(name), 'after': validated.get(name)}
                          for name in changes}}
    agent_models.private_json(directory / 'github-approved.json', approval)
    agent_models.private_json(directory / 'github.json', ledger)
    return summary(ledger)


def summary(ledger):
    keys = ('status', 'step', 'branch', 'base_sha', 'head_sha', 'pr_number', 'pr_url',
            'merge_sha', 'error', 'checks')
    return {key: ledger[key] for key in keys if key in ledger}


def next_request(ledger):
    if ledger['status'] not in ('awaiting_connector', 'waiting_for_ci'):
        return None
    if time.time() >= ledger['deadline']:
        ledger['status'] = 'awaiting_ci' if ledger.get('pr_number') else 'failed'
        ledger['error'] = 'Delivery deadline reached; no merge was claimed.'
        return None
    cfg, step = validate_config(ledger['config']), ledger['step']
    repo = cfg['repository']
    prefix = 'https://api.github.com/repos/' + repo
    paths = {'repository': '', 'base_ref': '/git/ref/heads/' + cfg['base'],
             'branch_ref': '/git/ref/heads/' + ledger['branch'],
             'base_commit': '/git/commits/' + ledger.get('base_sha', ''),
             'base_tree': '/git/trees/' + (ledger.get('tree_queue') or [{}])[0].get('sha', ''),
             'pr': '/pulls/' + str(ledger.get('pr_number', '')),
             'final_pr': '/pulls/' + str(ledger.get('pr_number', '')),
             'statuses': '/commits/' + (ledger.get('status_queue') or [''])[0] + '/status'}
    if step in paths:
        return {'tool': TOOLS['fetch'], 'arguments': {'url': prefix + paths[step]}}
    if step in ('head_checks', 'merge_checks'):
        sha = ledger['head_sha'] if step == 'head_checks' else ledger['test_merge_sha']
        return {'tool': TOOLS['fetch'], 'arguments': {'url': prefix + '/commits/' + sha +
                '/check-runs?filter=latest&per_page=100&page=' + str(ledger.get('page', 1))}}
    if step == 'tree':
        elements = []
        for name, entry in sorted(ledger['files'].items()):
            new = entry['after']
            item = {'path': name, 'type': 'blob', 'mode': new['mode'] if new else entry['before']['mode']}
            item.update({'content': new['content']} if new else {'sha': None})
            elements.append(item)
        return {'tool': TOOLS['create_tree'], 'arguments': {'repository_full_name': repo,
                'base_tree_sha': ledger['base_tree'], 'tree_elements': elements}}
    if step == 'commit':
        return {'tool': TOOLS['create_commit'], 'arguments': {'repository_full_name': repo,
                'message': ledger['metadata']['commit_message'], 'parent_sha': ledger['base_sha'],
                'tree_sha': ledger['new_tree']}}
    if step == 'branch':
        return {'tool': TOOLS['create_branch'], 'arguments': {'repository_full_name': repo,
                'branch_name': ledger['branch'], 'sha': ledger['head_sha']}}
    if step == 'create_pr':
        return {'tool': TOOLS['create_pull_request'], 'arguments': {'repository_full_name': repo,
                'head': ledger['branch'], 'base': cfg['base'], 'title': ledger['metadata']['pr_title'],
                'body': ledger['metadata']['pr_body'], 'draft': False, 'maintainer_can_modify': False}}
    if step == 'merge':
        return {'tool': TOOLS['merge_pull_request'], 'arguments': {'repository_full_name': repo,
                'pr_number': ledger['pr_number'], 'expected_head_sha': ledger['head_sha'],
                'merge_method': cfg['merge_method']}}
    raise ValueError('Unknown GitHub delivery step.')


def request(ledger):
    if ledger.get('pending_write'):
        ledger.update(status='needs_reconciliation',
                      error='A write was already dispatched; reconcile its result before any retry.')
        return None
    job = next_request(ledger)
    if job is not None:
        token = secrets.token_hex(32)
        ledger['pending_request_id'] = token
        ledger['pending_write'] = job['tool'] != TOOLS['fetch']
        job['request_id'] = token
    return job


def response_data(result):
    if not isinstance(result, dict) or result.get('isError'):
        raise ValueError('GitHub connector reported an unsuccessful request.')
    data = result.get('structuredContent', result)
    if isinstance(data, dict) and isinstance(data.get('content'), str):
        data = json.loads(data['content'])
    if isinstance(data, dict) and isinstance(data.get('pull_request'), dict):
        data = data['pull_request']
    if not isinstance(data, dict):
        raise ValueError('GitHub connector must return one JSON object.')
    return data


def valid_sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError('Invalid GitHub commit/tree SHA.')
    return value


def object_data(value):
    if not isinstance(value, dict):
        raise ValueError('GitHub response contains malformed object metadata.')
    return value


def check_pr(ledger, data):
    cfg = ledger['config']
    head, base = object_data(data.get('head')), object_data(data.get('base'))
    if head.get('sha') != ledger['head_sha'] or head.get('ref') != ledger['branch'] or \
            object_data(head.get('repo')).get('full_name') != cfg['repository'] or \
            base.get('ref') != cfg['base'] or \
            object_data(base.get('repo')).get('full_name') != cfg['repository'] or base.get('sha') != ledger['base_sha']:
        raise ValueError('PR head, base or repository changed; revalidation is required.')
    if data.get('draft') is not False or data.get('state') != 'open' or data.get('merged'):
        raise ValueError('PR must remain open and non-draft until the pinned merge.')
    if data.get('mergeable_state') in ('dirty', 'behind'):
        raise ValueError('PR has conflicts or an outdated base.')


def checks_gate(records, cfg, sha):
    latest = {}
    for row in records:
        if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0 or \
                not isinstance(row.get('name'), str) or row.get('head_sha') != sha:
            raise ValueError('Malformed or stale GitHub check run.')
        if object_data(row.get('app', {})).get('slug') != cfg['check_app']:
            continue
        if row['name'] not in latest or row['id'] > latest[row['name']]['id']:
            latest[row['name']] = row
    states = {name: latest.get(name, {}).get('conclusion') or 'pending' for name in cfg['required_checks']}
    if any(row.get('status') == 'completed' and row.get('conclusion') != 'success' for row in latest.values()):
        raise ValueError('CI failed, skipped, neutral or cancelled; PR remains unmerged.')
    passed = all(name in latest and latest[name].get('status') == 'completed' and
                 latest[name].get('conclusion') == 'success' for name in cfg['required_checks']) and \
        all(row.get('status') == 'completed' for row in latest.values())
    return passed, states


def accept(ledger, result):
    data = response_data(result)
    step, cfg = ledger['step'], ledger['config']
    ledger['status'] = 'awaiting_connector'
    event = {'step': step, 'time': time.time()}
    if step == 'repository':
        if data.get('full_name') != cfg['repository'] or data.get('archived') is not False or \
                object_data(data.get('permissions', {})).get('push') is not True or data.get('allow_squash_merge') is not True:
            raise ValueError('GitHub repository is not writable or squash merging is unavailable.')
        ledger['step'] = 'base_ref'
    elif step == 'base_ref':
        ref = object_data(data.get('object'))
        if data.get('ref') != 'refs/heads/' + cfg['base'] or ref.get('type') != 'commit':
            raise ValueError('GitHub base branch does not match policy.')
        ledger['base_sha'] = valid_sha(ref['sha'])
        ledger['step'] = 'base_commit'
    elif step == 'base_commit':
        if data.get('sha') != ledger['base_sha']:
            raise ValueError('Base commit changed.')
        ledger['base_tree'] = valid_sha(object_data(data.get('tree'))['sha'])
        ledger.update(tree_queue=[{'sha': ledger['base_tree'], 'prefix': ''}], remote_entries={})
        ledger['step'] = 'base_tree'
    elif step == 'base_tree':
        cursor = ledger['tree_queue'][0]
        if data.get('sha') != cursor['sha'] or data.get('truncated') is not False or not isinstance(data.get('tree'), list):
            raise ValueError('Complete scoped base trees are required before publication.')
        seen = set()
        for item in data['tree']:
            item = object_data(item)
            leaf = item.get('path')
            if not isinstance(leaf, str) or not leaf or '/' in leaf or leaf in seen or leaf in ('.', '..'):
                raise ValueError('Invalid non-recursive base tree entry.')
            seen.add(leaf)
            name = cursor['prefix'] + leaf
            if name in ledger['files']:
                ledger['remote_entries'][name] = item
            if any(path.startswith(name + '/') for path in ledger['files']):
                if item.get('type') != 'tree':
                    raise ValueError('Remote parent path is not a directory: ' + name)
                ledger['tree_queue'].append({'sha': valid_sha(item['sha']), 'prefix': name + '/'})
        ledger['tree_queue'].pop(0)
        if not ledger['tree_queue']:
            for name, entry in ledger['files'].items():
                old, remote = entry['before'], ledger['remote_entries'].get(name)
                if (old is None and remote is not None) or (old is not None and
                        (remote is None or remote.get('type') != 'blob' or
                         remote.get('sha') != old['sha'] or remote.get('mode') != old['mode'])):
                    raise ValueError('Remote baseline differs from the task input: ' + name +
                                     '. Pre-existing edits/bootstrap require a separate approved publication scope.')
            ledger['step'] = 'tree'
    elif step == 'tree':
        ledger['new_tree'] = valid_sha(data['sha'])
        ledger['step'] = 'commit'
    elif step == 'commit':
        ledger['head_sha'] = valid_sha(data['sha'])
        ledger['step'] = 'branch'
    elif step in ('branch', 'branch_ref'):
        if step == 'branch' and set(data) == {'branch'} and data['branch'] == ledger['branch']:
            # The native connector returns only the created branch name. Read
            # its actual ref before accepting the pinned head or opening a PR.
            ledger['step'] = 'branch_ref'
        else:
            ref = object_data(data.get('object'))
            if data.get('ref') != 'refs/heads/' + ledger['branch'] or \
                    ref.get('type') != 'commit' or ref.get('sha') != ledger['head_sha']:
                raise ValueError('Connector did not confirm the expected published branch.')
            ledger['step'] = 'create_pr'
    elif step == 'create_pr':
        number = data.get('number', data.get('pr_number'))
        if type(number) is not int or number <= 0:
            raise ValueError('Connector did not return a PR number.')
        ledger['pr_number'] = number
        ledger['pr_url'] = 'https://github.com/' + cfg['repository'] + '/pull/' + str(number)
        event['pr_url'] = ledger['pr_url']
        ledger['step'] = 'pr'
    elif step in ('pr', 'final_pr'):
        check_pr(ledger, data)
        if step == 'final_pr':
            if data.get('merge_commit_sha') != ledger.get('test_merge_sha'):
                # GitHub may finish computing a test merge after our initial read.
                # Recheck that SHA's CI instead of trusting a previous test merge.
                ledger.update(step='pr', status='waiting_for_ci')
            elif data.get('mergeable') is True and data.get('mergeable_state') == 'clean':
                ledger['step'] = 'merge'
            else:
                ledger.update(step='pr', status='waiting_for_ci')
        else:
            ledger['test_merge_sha'] = valid_sha(data['merge_commit_sha']) if data.get('merge_commit_sha') else None
            ledger.update(step='head_checks', page=1, records=[], head_records=[], total_count=None)
    elif step in ('head_checks', 'merge_checks'):
        rows = data.get('check_runs')
        if not isinstance(rows, list) or type(data.get('total_count')) is not int or data['total_count'] < 0:
            raise ValueError('Invalid CI coverage response.')
        if ledger.get('total_count') is not None and ledger['total_count'] != data['total_count']:
            raise ValueError('Check run coverage changed during pagination; recheck required.')
        ids = [row.get('id') for row in ledger['records'] + rows if isinstance(row, dict)]
        if len(ids) != len(ledger['records']) + len(rows) or \
                any(type(value) is not int or value <= 0 for value in ids) or len(set(ids)) != len(ids):
            raise ValueError('Duplicate or invalid CI check IDs; coverage is incomplete.')
        ledger['total_count'] = data['total_count']
        ledger['records'].extend(rows)
        if len(ledger['records']) > data['total_count']:
            raise ValueError('Inconsistent check run coverage.')
        if len(ledger['records']) < data['total_count']:
            if not rows or ledger['page'] >= 20:
                raise ValueError('Incomplete or excessive GitHub check pagination.')
            ledger['page'] += 1
        elif step == 'head_checks' and ledger.get('test_merge_sha'):
            ledger.update(head_records=ledger['records'], step='merge_checks', page=1, records=[], total_count=None)
        else:
            use_merge = step == 'merge_checks' and bool(ledger['records'])
            sha = ledger['test_merge_sha'] if use_merge else ledger['head_sha']
            rows = ledger['records'] if use_merge or step == 'head_checks' else ledger['head_records']
            passed, ledger['checks'] = checks_gate(rows, cfg, sha)
            ledger['check_sha'] = sha
            if passed:
                status_shas = [ledger['head_sha']]
                if ledger.get('test_merge_sha') and ledger['test_merge_sha'] not in status_shas:
                    status_shas.append(ledger['test_merge_sha'])
                ledger.update(step='statuses', status='awaiting_connector',
                              status_queue=status_shas, statuses_pending=False)
            else:
                ledger.update(step='pr', status='waiting_for_ci')
    elif step == 'statuses':
        if data.get('sha') != ledger['status_queue'][0] or type(data.get('total_count')) is not int or data['total_count'] < 0:
            raise ValueError('Stale or invalid commit status response.')
        if data['total_count'] and data.get('state') in ('error', 'failure'):
            raise ValueError('Required commit status failed.')
        if data['total_count'] and data.get('state') != 'success':
            ledger['statuses_pending'] = True
        ledger['status_queue'].pop(0)
        if not ledger['status_queue']:
            if ledger['statuses_pending']:
                ledger.update(step='pr', status='waiting_for_ci')
            else:
                ledger['step'] = 'final_pr'
    elif step == 'merge':
        if data.get('merged') is not True:
            raise ValueError('GitHub did not confirm a successful merge.')
        ledger.update(status='merged', step='done', merge_sha=valid_sha(data['sha']))
    else:
        raise ValueError('Unknown GitHub delivery response step.')
    ledger['events'].append(event)
    ledger.pop('pending_request_id', None)
    ledger.pop('pending_write', None)
    ledger.pop('error', None)
    return ledger


def directory_for(run_id):
    if not RUN_ID.fullmatch(run_id):
        raise ValueError('Invalid workflow run ID.')
    directory = REPORTS / run_id
    if directory.is_symlink() or directory.resolve().parent != REPORTS.resolve():
        raise ValueError('Unsafe GitHub journal directory.')
    return directory


def validate_journal(directory, ledger):
    cfg = validate_config(ledger['config'])
    if ledger['run_id'] != directory.name or ledger['version'] != 'github-v1' or \
            ledger['branch'] != 'codex/' + directory.name or not origin_matches(ROOT, cfg['repository']):
        raise ValueError('GitHub journal identity or origin changed.')
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    if not isinstance(ledger['files'], dict) or not ledger['files'] or \
            set(ledger['files']) != set(report['changed_files']) or \
            set(ledger['files']) - set(report['scope']) or report.get('read_only') or report.get('simulated'):
        raise ValueError('GitHub journal differs from the approved task scope.')
    metadata(json.dumps(ledger['metadata']))
    approval_path = directory / 'github-approved.json'
    if approval_path.is_symlink() or not approval_path.is_file() or approval_path.stat().st_mode & 0o077:
        raise ValueError('Publication approval must be a private regular file.')
    approval = json.loads(approval_path.read_text(encoding='utf-8'))
    if approval['config'] != cfg or approval['run_id'] != ledger['run_id'] or \
            approval['workspace'] != report['workspace'] or set(approval['files']) != set(ledger['files']):
        raise ValueError('Journal differs from the publication approval.')
    for name, entry in ledger['files'].items():
        if workspace.protected(name):
            raise ValueError('Protected journal path.')
        workspace.safe_path(ROOT, name)
        for version in ('before', 'after'):
            item = entry[version]
            approved = approval['files'][name][version]
            if (item is None) != (approved is None):
                raise ValueError('Journal changed an approved addition or deletion.')
            if item is not None:
                valid_sha(item['sha'])
                if item['mode'] not in ('100644', '100755'):
                    raise ValueError('Invalid journal file mode.')
                if version == 'after' and (not isinstance(item['content'], str) or
                                          blob_sha(item['content'].encode('utf-8')) != item['sha']):
                    raise ValueError('Journal source hash does not match.')
                base = directory / 'backup' if version == 'before' else Path(approval['workspace'])
                source = workspace.safe_path(base, name)
                if workspace.fingerprint(source, approval['max_file_bytes']) != approved or \
                        mode(approved) != item['mode'] or blob_sha(source.read_bytes()) != item['sha']:
                    raise ValueError('Journal differs from the reviewed and validated snapshot.')


def save(directory, ledger):
    agent_models.private_json(directory / 'github.json', ledger)
    path = directory / 'report.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    previous = report.get('github')
    report['github'] = summary(ledger)
    report['status'] = {'merged': 'passed', 'failed': 'failed', 'awaiting_ci': 'awaiting_ci',
                        'needs_reconciliation': 'needs_reconciliation'}.get(
        ledger['status'], 'awaiting_github')
    event = {'phase': 'github', 'stage': 8, 'state': ledger['status'], 'step': ledger['step'],
             'role': None, 'provider': 'github', 'model': None,
             'time': datetime.now(timezone.utc).isoformat()}
    if previous != report['github'] or report.get('current', {}).get('provider') != 'github':
        report['current'] = event
        report.setdefault('events', []).append(event)
        with (directory / 'events.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(event) + '\n')
        (directory / 'events.jsonl').chmod(0o600)
    agent_models.private_json(path, report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('request', 'accept', 'resume', 'doctor'))
    parser.add_argument('--run-id')
    parser.add_argument('--response-json')
    parser.add_argument('--response-file', type=Path)
    parser.add_argument('--request-id')
    args = parser.parse_args(argv)
    lock = None
    try:
        if args.command == 'doctor':
            cfg = load_config()
            ready = origin_matches(ROOT, cfg['repository'])
            print(json.dumps({'status': 'ready_for_connector' if ready else 'failed',
                              'repository': cfg['repository'], 'base': cfg['base'],
                              'transport': 'parent_codex_github_connector', 'enabled': cfg['enabled'],
                              'api_called': False, 'note': 'Parent must verify connector write permission.'}))
            return 0 if ready else 1
        directory = directory_for(args.run_id or '')
        lock_path = directory / 'github.lock'
        if lock_path.is_symlink():
            raise ValueError('Invalid journal lock.')
        lock = lock_path.open('a')
        lock_path.chmod(0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise ValueError('Another GitHub delivery controller is running.') from None
        path = directory / 'github.json'
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError('GitHub journal must be a regular private file.')
        ledger = json.loads(path.read_text(encoding='utf-8'))
        validate_journal(directory, ledger)
        if args.command == 'resume':
            if ledger['status'] != 'awaiting_ci' or not ledger.get('pr_number'):
                raise ValueError('Only an existing PR waiting for CI can resume.')
            ledger.update(step='pr', status='awaiting_connector', deadline=time.time() + ledger['config']['wait_seconds'])
            ledger.pop('error', None)
        elif args.command == 'accept':
            if ledger['status'] not in ('awaiting_connector', 'waiting_for_ci', 'needs_reconciliation') or \
                    bool(args.response_json) == bool(args.response_file) or \
                    not args.request_id or args.request_id != ledger.get('pending_request_id'):
                raise ValueError('No pending GitHub connector response is expected.')
            try:
                raw = args.response_file.read_text(encoding='utf-8') if args.response_file else args.response_json
                accepted = copy.deepcopy(ledger)
                accept(accepted, json.loads(raw))
                ledger = accepted
            except (ValueError, KeyError, TypeError, OSError) as exc:
                ledger.update(status='needs_reconciliation' if ledger.get('pending_write') else 'failed',
                              error='Connector response could not be verified: ' + type(exc).__name__)
        job = request(ledger)
        save(directory, ledger)
        print(json.dumps({'run_id': ledger['run_id'], 'github': summary(ledger), 'request': job,
                          'poll_after_seconds': 10 if ledger['status'] == 'waiting_for_ci' else 0}, ensure_ascii=False))
        return 1 if ledger['status'] in ('failed', 'needs_reconciliation') else 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}))
        return 1
    finally:
        if lock is not None:
            lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
