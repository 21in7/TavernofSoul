"""Route development work, run configured agents, review, verify and publish edits."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time

from harness import agent_models, git_publish, triage, workspace

ROOT = agent_models.ROOT
CONFIG = ROOT / 'harness/workflow-config.json'
REPORTS = ROOT / 'logs/harness/workflows'
PHASES = {'prepare': '준비', 'triage': 'Jev 판단', 'plan': '작업 배정',
          'implement': '담당 에이전트 실행', 'review': 'Claude 검토',
          'validate': '하네스 검증', 'apply': '결과 반영', 'github': 'GitHub 게시와 병합'}
CHECKS = ('check', 'check-downloader', 'check-parser', 'check-django', 'check-pipeline')


def load_policy():
    policy = json.loads(CONFIG.read_text(encoding='utf-8'))
    bounds = {'max_tasks': 8, 'max_rounds': 3, 'agent_timeout_seconds': 1800,
              'check_timeout_seconds': 3600, 'max_file_bytes': 33554432,
              'max_snapshot_bytes': 268435456, 'max_diff_bytes': 1048576}
    if set(policy) != set(bounds) | {'version'} or policy['version'] != 'workflow-v1':
        raise ValueError('Invalid workflow policy.')
    for name, maximum in bounds.items():
        if type(policy[name]) is not int or not 0 < policy[name] <= maximum:
            raise ValueError('Invalid workflow policy: ' + name)
    return policy


def scoped_files(root, files):
    # Path normalization belongs to triage; publication additionally rejects
    # directories, secrets, environments and symlinked ancestors.
    names = triage.scoped_paths(files, triage.load_policy()['max_files'])
    if not names:
        raise ValueError('An explicit list of source files is required.')
    for name in names:
        if workspace.protected(name):
            raise ValueError('Protected file cannot be assigned: ' + name)
        workspace.safe_path(root, name)
    return names


def owner(name):
    if name in ('parser_tidy/tests/test_canonical_id.py',
                'parser_tidy/tests/test_import_safety.py',
                'parser_tidy/tests/test_recipe_migration_db.py'):
        return 'django'
    return {'downloader': 'downloader', 'parser_tidy': 'parser',
            'TavernofSoul': 'django'}.get(Path(name).parts[0], 'coordinator')


def object_response(text):
    text = text.strip()
    if text.startswith('```json\n') and text.endswith('\n```'):
        text = text[8:-4]
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError('Expected one JSON object from the agent.')
    return result


def parse_plan(response, scope, policy):
    plan = object_response(response)
    tasks = plan.get('tasks')
    if set(plan) != {'tasks'} or not isinstance(tasks, list) or not 0 < len(tasks) <= policy['max_tasks']:
        raise ValueError('Invalid coordinator task plan.')
    assigned = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {'role', 'task', 'files'} or \
                not isinstance(task['task'], str) or not task['task'].strip() or \
                len(task['task'].encode('utf-8')) > 16000 or \
                not isinstance(task['files'], list) or not task['files']:
            raise ValueError('Invalid coordinator task.')
        files = triage.scoped_paths(task['files'], 128)
        if files != sorted(task['files']) or set(files) - set(scope) or \
                any(owner(name) != task['role'] for name in files):
            raise ValueError('Coordinator changed the declared scope or file owner.')
        if assigned & set(files):
            raise ValueError('Each scoped file must have exactly one implementation task.')
        assigned.update(files)
    if assigned != set(scope):
        raise ValueError('Coordinator plan did not cover every scoped file.')
    return tasks


def parse_review(response, scope):
    review = object_response(response)
    if set(review) != {'verdict', 'summary', 'findings'} or \
            review['verdict'] not in ('approved', 'changes_requested') or \
            not isinstance(review['summary'], str) or not review['summary'].strip() or \
            not isinstance(review['findings'], list) or len(review['findings']) > 32:
        raise ValueError('Invalid reviewer verdict.')
    for finding in review['findings']:
        if not isinstance(finding, dict) or set(finding) != {'file', 'severity', 'message'} or \
                finding['file'] not in scope or finding['severity'] not in ('high', 'medium', 'low') or \
                not isinstance(finding['message'], str) or not finding['message'].strip():
            raise ValueError('Invalid reviewer finding.')
    if (review['verdict'] == 'approved') != (not review['findings']):
        raise ValueError('Reviewer verdict contradicts its findings.')
    return review


def required_checks(scope, recommendation):
    checks = set(triage.path_rules(scope)['required_checks'])
    checks.update(recommendation['required_checks'])
    checks.update(agent_models.load_config()['roles'][owner(name)]['check'] for name in scope)
    return ['check'] if 'check' in checks else sorted(checks)


def check_environment(keys):
    env = agent_models.child_environment('codex', keys)
    env.pop('PYTHONPATH', None)
    env.pop('PYTEST_ADDOPTS', None)
    env.pop('PYTEST_PLUGINS', None)
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    env['TAVERN_WORKFLOW_CHILD'] = '1'
    return env


def run_check(candidate, command, report_dir, keys, policy):
    if command not in CHECKS + ('doctor',):
        raise ValueError('Check command is not allowlisted.')
    report_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([sys.executable, '-m', 'harness', command,
                             '--report-dir', str(report_dir)], cwd=str(candidate),
                            env=check_environment(keys), capture_output=True, text=True,
                            timeout=policy['check_timeout_seconds'])
    log = report_dir / (command + '.log')
    log.write_text(agent_models.redact(result.stdout + result.stderr, keys), encoding='utf-8')
    log.chmod(0o600)
    path = report_dir / (command + '.json')
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    groups = data.get('checks', {})
    passed = result.returncode == 0 and data.get('status') == 'passed'
    if command != 'doctor':
        passed = passed and isinstance(groups, dict) and bool(groups) and all(
            isinstance(group, dict) and group.get('status') == 'passed' and
            type(group.get('selected')) is int and group['selected'] > 0 and
            group.get('passed') == group.get('selected') and not group.get('skipped') and
            not group.get('errors') and not group.get('failures')
            for group in groups.values())
    return {'command': command, 'status': 'passed' if passed else 'failed',
            'exit_code': result.returncode, 'report': str(path), 'log': str(log),
            'checks': groups}


class Progress:
    def __init__(self, directory, report, keys):
        self.directory, self.report, self.keys = directory, report, keys

    def save(self):
        safe = triage.scrub(self.report, self.keys)
        agent_models.private_json(self.directory / 'report.json', safe)
        agent_models.private_json(REPORTS / 'latest.json', {'run_id': safe['run_id']})

    def event(self, phase, state, role=None, **detail):
        spec = agent_models.load_config()['roles'].get(role, {})
        event = {'time': datetime.now(timezone.utc).isoformat(), 'phase': phase,
                 'stage': list(PHASES).index(phase) + 1, 'state': state, 'role': role,
                 'provider': spec.get('provider'), 'model': spec.get('model'), **detail}
        if phase == 'triage':
            event.update(provider='typesafe', model=triage.load_policy()['model'])
        self.report['current'] = event
        self.report['events'].append(event)
        self.save()
        safe = triage.scrub(event, self.keys)
        with (self.directory / 'events.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(safe, ensure_ascii=False) + '\n')
        (self.directory / 'events.jsonl').chmod(0o600)
        identity = ' / '.join(value for value in (role, safe['provider'], safe['model']) if value)
        print('{}[{}/{} {}] {} · {}{}'.format('[fixture] ' if self.report['simulated'] else '',
              safe['stage'], len(PHASES), PHASES[phase], state,
              identity or 'harness', ' · ' + str(safe['detail']) if 'detail' in safe else ''), flush=True)


def model_step(progress, candidate, phase, role, task, keys, policy, runner,
               scope=(), write=False):
    before = workspace.manifest(candidate, policy)
    progress.event(phase, 'running', role, agent_started=not progress.report['simulated'])
    task += '\nApproved readable files (exact paths): ' + json.dumps(progress.report['scope'])
    result = triage.scrub(runner(role, agent_models.redact(task, keys), keys, write=write,
                                timeout=policy['agent_timeout_seconds'], workspace=candidate,
                                scoped=True), keys)
    progress.report['agents'].append({'phase': phase, **result})
    progress.save()
    if result['status'] != 'passed':
        raise ValueError('Agent failed: {}. See the private agent report.'.format(role))
    workspace.enforce_scope(before, workspace.manifest(candidate, policy), scope, read_only=not write)
    progress.event(phase, 'responded' if phase in ('plan', 'review', 'github') else 'passed', role)
    return result['response']


def execute(task, files, read_only=False, rules_only=False, simulated=False,
            runner=None, checker=None, keys=None, fixture=None, no_git=False):
    if os.environ.get('TAVERN_WORKFLOW_CHILD'):
        raise ValueError('Workflow workers must not start another workflow.')
    policy = load_policy()
    github_enabled = not (read_only or simulated or no_git) and git_publish.load_config()['enabled']
    scope = scoped_files(ROOT, files)
    if not task.strip() or len(task.encode('utf-8')) > triage.load_policy()['max_task_bytes']:
        raise ValueError('Task is empty or too large.')
    keys = agent_models.load_keys() if keys is None else keys
    task = agent_models.redact(task, keys)
    runner, checker = runner or agent_models.run, checker or run_check
    REPORTS.mkdir(parents=True, exist_ok=True)
    REPORTS.chmod(0o700)
    lock = (REPORTS / '.lock').open('a')
    (REPORTS / '.lock').chmod(0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError('Another workflow is running in this repository.') from None
    run_id = str(time.time_ns()) + '-' + secrets.token_hex(3)
    directory = REPORTS / run_id
    directory.mkdir(mode=0o700)
    candidate = directory / 'workspace'
    report = {'run_id': run_id, 'policy_version': policy['version'], 'pid': os.getpid(),
              'status': 'running', 'read_only': read_only, 'simulated': simulated,
              'scope': scope, 'task_sha256': triage.digest(task),
              'workspace': str(candidate), 'model_read_scope': scope,
              'agents': [], 'events': [], 'validation': [],
              'applied': [], 'report': str(directory / 'report.json')}
    report['github_enabled'] = github_enabled
    progress = Progress(directory, report, keys)
    try:
        progress.event('prepare', 'running', detail='승인 파일 모델 사본과 로컬 검증 사본을 분리해 생성')
        baseline = workspace.copy_validation_sources(ROOT, candidate, scope, policy)
        agent_models.private_json(directory / 'baseline.json', baseline)
        # Outside repository ancestry: native CLIs must not discover parent project
        # instructions. The local verification snapshot is never a model workspace.
        context_dir = Path(tempfile.mkdtemp(prefix='tavern-model-context-', dir='/tmp'))
        model_context = context_dir / 'sources'
        model_baseline = workspace.copy_sources(candidate, model_context, scope, policy)
        report['model_workspace'] = str(model_context)
        report['model_context_manifest'] = str(directory / 'model-context.json')
        agent_models.private_json(directory / 'model-context.json',
                                  {'approved_files': scope, 'copied_files': model_baseline})
        result = checker(candidate, 'doctor', directory / 'prepare', keys, policy)
        report['environment'] = result
        if result['status'] != 'passed':
            raise ValueError('Harness environment is not ready.')
        workspace.enforce_scope(baseline, workspace.manifest(candidate, policy), [], read_only=True)
        progress.event('prepare', 'passed')
        progress.event('triage', 'running', api_requested=not rules_only and not simulated)
        decision = triage.observe(task, scope, live=not rules_only and not simulated, fixture=fixture)
        report['triage'] = decision
        recommendation = decision['recommendation']
        checks = required_checks(scope, recommendation)
        report['required_checks'] = checks
        progress.event('triage', 'passed' if decision['status'] == 'passed' else 'fallback',
                       detail='담당 추천: ' + recommendation['role'], source=decision['source'])
        # Missing review credentials are caught before charging any implementation role.
        if not simulated:
            roles = {'reviewer', recommendation['role']}
            if github_enabled:
                roles.add('git')
            roles.update(owner(name) for name in scope)
            for role in sorted(roles):
                provider = agent_models.load_config()['roles'][role]['provider']
                ready = agent_models.connection_status(provider, keys)
                if ready['status'] != 'ready':
                    raise ValueError('Role is not configured: ' + role)
        if recommendation['role'] == 'coordinator' or any(owner(name) != recommendation['role'] for name in scope):
            prompt = ('Plan this development task without editing files or running checks. '
                      'Return ONLY JSON: {{"tasks":[{{"role":"parser","task":"...","files":["..."]}}]}}. '
                      'Use each declared file exactly once; never invent additional files. '
                      'Role must equal the supplied owner. Tasks execute sequentially in listed order. '
                      'Do not call agent-run or harness.workflow.\nOwners: {}\nTask: {}').format(
                          json.dumps({name: owner(name) for name in scope}, ensure_ascii=False), task)
            response = model_step(progress, model_context, 'plan', 'coordinator', prompt, keys, policy, runner)
            tasks = parse_plan(response, scope, policy)
        else:
            tasks = [{'role': recommendation['role'], 'task': task, 'files': scope}]
            progress.event('plan', 'direct', detail='Jev와 경로 규칙이 일치해 담당자에 직접 배정')
        report['tasks'] = tasks
        feedback = ''
        for round_number in range(1, policy['max_rounds'] + 1):
            report['round'] = round_number
            for assigned in tasks:
                prompt = ('Original request:\n{}\nAssigned task:\n{}\n'
                          'Allowed edit files (exact paths): {}\n'
                          'Preserve existing user edits. {} '
                          'Do not run checks, agent-run, harness.workflow, cron or operating data pipelines. '
                          'The orchestrator runs checks. Report your result and remaining concerns.\n{}').format(
                              task, assigned['task'], json.dumps(assigned['files'], ensure_ascii=False),
                              'Do not edit any files; this is analysis only.' if read_only else
                              'Implement the assigned change only in the allowed files.', feedback)
                model_step(progress, model_context, 'implement', assigned['role'], prompt, keys, policy,
                           runner, assigned['files'], write=not read_only)
            workspace.sync_scope(model_context, candidate, model_baseline, scope, policy, read_only=read_only)
            candidate_manifest = workspace.manifest(candidate, policy)
            changes = workspace.enforce_scope(baseline, candidate_manifest, scope, read_only=read_only)
            diff = workspace.diff_text(ROOT, candidate, changes, policy['max_diff_bytes'])
            diff_path = directory / 'changes.diff'
            diff_path.write_text(agent_models.redact(diff, keys), encoding='utf-8')
            diff_path.chmod(0o600)
            report['changed_files'] = changes
            summaries = [agent['response'] for agent in report['agents'] if agent['phase'] == 'implement']
            prompt = ('Review the task outcome and candidate source against the original request. '
                      'Return ONLY JSON with exactly verdict, summary, findings. '
                      'verdict is approved or changes_requested. approved requires findings=[]. '
                      'Otherwise each finding has file (one of the scoped files), severity '
                      '(high/medium/low) and message. Inspect source as needed; do not edit files. '
                      'No changes is acceptable for an analysis request or an already satisfied request, '
                      'but reject an unimplemented requested fix.\nRead only: {}\nScope: {}\n'
                      'Request: {}\nImplementation results: {}\nDiff:\n{}').format(
                          read_only, json.dumps(scope), task, json.dumps(summaries, ensure_ascii=False), diff)
            response = model_step(progress, model_context, 'review', 'reviewer', prompt, keys, policy, runner)
            review = parse_review(response, scope)
            report['review'] = review
            if review['verdict'] != 'approved':
                feedback = 'Address these reviewer findings:\n' + json.dumps(review, ensure_ascii=False)
                progress.event('review', 'changes_requested', 'reviewer', round=round_number)
                if read_only or round_number == policy['max_rounds']:
                    raise ValueError('Review did not approve within max_rounds; originals are preserved.')
                continue
            progress.event('review', 'approved', 'reviewer', round=round_number)
            failures, round_validation = [], []
            for command in checks:
                progress.event('validate', 'running', detail=command, round=round_number)
                result = checker(candidate, command, directory / ('checks-' + str(round_number)) / command,
                                 keys, policy)
                report['validation'].append(result)
                round_validation.append(result)
                workspace.enforce_scope(candidate_manifest, workspace.manifest(candidate, policy), [], read_only=True)
                progress.event('validate', result['status'], detail=command, round=round_number)
                if result['status'] != 'passed':
                    failures.append(result)
            if failures:
                # Tracebacks, node IDs and log paths can contain unapproved source.
                # Only fixed, allowlisted command/status metadata crosses this boundary.
                feedback = ('Required local checks failed; do not run checks yourself. '
                            'Detailed logs remain local because they may contain unapproved source. '
                            'Inspect approved files for a correction or report missing context:\n' +
                            json.dumps([{'command': failure['command'], 'status': 'failed'}
                                        for failure in failures], ensure_ascii=False))
                if read_only or round_number == policy['max_rounds']:
                    raise ValueError('Required checks failed within max_rounds; originals are preserved.')
                continue
            report['delivery_validation'] = round_validation
            progress.event('apply', 'running', detail='읽기 전용/데모는 원본에 반영하지 않음' if read_only or simulated else '')
            if not read_only and not simulated:
                report['applied'] = workspace.publish(ROOT, candidate, baseline, candidate_manifest, changes,
                                                      scope, directory / 'backup', policy)
            report['status'] = 'demonstrated' if simulated else 'passed'
            progress.event('apply', 'passed', detail='반영된 파일: ' + str(len(report['applied'])))
            if github_enabled and changes:
                # The model writes bounded descriptions only. The parent connector
                # performs all GitHub mutations; credentials never reach a worker.
                prompt = ('Write a commit message and PR description for this reviewed, validated change. '
                          'Return ONLY JSON with exactly commit_message, pr_title, pr_body (all strings). '
                          'Describe the problem, final behavior and actual validation. Do not edit files, '
                          'execute Git, call tools that publish, or request extra source. Do not invent tests. '
                          'The orchestrator controls repository, branch, scope and merge policy.\n'
                          'Task: {}\nChanged files: {}\nReview: {}\nLocal check results: {}\nDiff:\n{}').format(
                              task, json.dumps(changes), json.dumps(review, ensure_ascii=False),
                              json.dumps([{'command': item['command'], 'status': item['status']}
                                          for item in report['delivery_validation']]), diff)
                response = model_step(progress, model_context, 'github', 'git', prompt, keys, policy, runner)
                report['github'] = git_publish.prepare(ROOT, directory, report, baseline, candidate_manifest,
                                                       changes, policy, git_publish.metadata(response))
                report['status'] = 'awaiting_github'
                progress.event('github', 'awaiting_connector', detail='메인 /root가 GitHub 앱 요청을 이어 실행')
            else:
                report['github'] = {'status': 'skipped'}
                progress.event('github', 'skipped', detail='읽기 전용·데모·GIT=0·변경 없음 또는 게시 비활성화')
            break
    except (Exception, KeyboardInterrupt) as exc:
        report['status'] = 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed'
        report['error_type'] = type(exc).__name__
        report['error'] = agent_models.redact(str(exc), keys)
        phase = report.get('current', {}).get('phase', 'prepare')
        progress.event(phase, report['status'], report.get('current', {}).get('role'), detail=report['error'])
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        progress.save()
        lock.close()
    return triage.scrub(report, keys)


def plan(files):
    scope = scoped_files(ROOT, files)
    rules = triage.path_rules(scope)
    config = agent_models.load_config()
    return {'mode': 'plan', 'agent_started': False, 'api_called': False, 'scope': scope,
            'owners': {name: owner(name) for name in scope}, 'phases': PHASES,
            'roles': {role: config['roles'][role] for role in set(map(owner, scope)) | {'coordinator', 'reviewer', 'git'}},
            'minimum_checks': rules['required_checks'],
            'note': 'Execution also preserves Jev-required checks; this preview makes no model request.'}


def demo():
    def fixture_runner(role, task, keys, **options):
        if role == 'reviewer':
            response = {'verdict': 'approved', 'summary': 'Fixture review only.', 'findings': []}
        elif 'Plan this development task' in task:
            response = {'tasks': [{'role': 'coordinator', 'task': 'Write the demonstration file.',
                                   'files': ['harness/fixtures/workflow/example.txt']}]}
        else:
            path = options['workspace'] / 'harness/fixtures/workflow/example.txt'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Offline workflow demonstration.\n', encoding='utf-8')
            response = 'Demonstration file created in the private candidate workspace.'
        spec = agent_models.load_config()['roles'][role]
        return {'role': role, 'provider': spec['provider'], 'model': spec['model'], 'status': 'passed',
                'source': 'fixture', 'response': json.dumps(response) if isinstance(response, dict) else response}

    def fixture_check(candidate, command, report_dir, keys, policy):
        return {'command': command, 'status': 'passed', 'source': 'fixture', 'checks': {}}

    return execute('Demonstrate orchestration with fixture responses only.',
                   ['harness/fixtures/workflow/example.txt'], simulated=True,
                   runner=fixture_runner, checker=fixture_check, keys={}, rules_only=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'plan', 'status', 'demo'))
    parser.add_argument('--task-file', type=Path)
    parser.add_argument('--files-file', type=Path)
    parser.add_argument('--file', action='append', default=[])
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--rules-only', action='store_true')
    parser.add_argument('--no-git', action='store_true')
    parser.add_argument('--run-id')
    args = parser.parse_args(argv)
    try:
        if args.command in ('status', 'demo') and (args.task_file or args.files_file or args.file or
                                                  args.read_only or args.rules_only or args.no_git):
            parser.error('status/demo do not take task or execution options')
        if args.run_id and args.command != 'status':
            parser.error('--run-id is for status only')
        if args.command == 'status':
            run_id = args.run_id or json.loads((REPORTS / 'latest.json').read_text())['run_id']
            if not re.fullmatch(r'[0-9]+-[a-f0-9]{6}', run_id):
                raise ValueError('Invalid run ID.')
            report = json.loads((REPORTS / run_id / 'report.json').read_text())
            if report['status'] == 'running':
                try:
                    os.kill(report['pid'], 0)
                except ProcessLookupError:
                    report['status'] = 'abandoned'
                except PermissionError:
                    pass  # The process exists but belongs to a different uid.
        elif args.command == 'demo':
            report = demo()
        else:
            files = list(args.file)
            if args.files_file:
                if args.files_file.stat().st_size > 65536:
                    raise ValueError('File scope is too large.')
                files += [line for line in args.files_file.read_text(encoding='utf-8').splitlines() if line]
            if args.command == 'plan':
                if args.task_file or args.read_only or args.rules_only or args.no_git:
                    parser.error('plan requires file scope only')
                report = plan(files)
            else:
                if not args.task_file or args.task_file.stat().st_size > triage.load_policy()['max_task_bytes']:
                    raise ValueError('A non-empty task file within the size limit is required.')
                report = execute(args.task_file.read_text(encoding='utf-8'), files,
                                 read_only=args.read_only, rules_only=args.rules_only, no_git=args.no_git)
        # Agent responses and check output stay in the private report, not the terminal.
        summary = {name: report[name] for name in ('run_id', 'pid', 'status', 'current', 'required_checks',
                   'changed_files', 'applied', 'report', 'error', 'simulated', 'github') if name in report}
        print(json.dumps(summary if args.command != 'plan' else report, ensure_ascii=False, indent=2))
        # Exit 0 hands control to the parent; awaiting_github still means incomplete.
        return 0 if report.get('status', 'passed') in ('passed', 'running', 'demonstrated', 'awaiting_github') else 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('Workflow failed: {}'.format(type(exc).__name__), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
