"""Route development work, run configured agents, review, verify and publish edits."""
import argparse
import contextlib
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

from harness import agent_models, archive, check_selection, docs_check, failure_feedback, git_publish, storage, triage, workspace
from harness import project_lock

ROOT = agent_models.ROOT
CONFIG = ROOT / 'harness/workflow-config.json'
REPORTS = ROOT / 'logs/harness/workflows'
_DEFAULT_REPORTS = REPORTS
PHASES = {'prepare': '준비', 'triage': 'Jev 판단', 'plan': '작업 배정',
          'implement': '담당 에이전트 실행', 'review': 'Claude 검토',
          'validate': '하네스 검증', 'apply': '결과 반영', 'github': 'GitHub 게시·병합·정리'}
CHECKS = ('check', 'check-downloader', 'check-parser', 'check-django', 'check-pipeline', 'check-docs')
DOCUMENTATION_GUIDANCE = (
    'Assess documentation impact at task start and in every review. Changes to structure, '
    'responsibilities, data contracts, isolation, validation, failure recovery or GitHub publication '
    'policy require updates to the relevant design/boundary documents; major decisions require a new '
    'or replacement ADR. Use docs/harness-design.md, docs/adr/README.md and docs/workflow.md only '
    'when explicitly approved for reading. A typo or local behavior-preserving change may need no '
    'documentation update, but the review must record a concrete reason. Never automatically copy, '
    'read or create documents outside the approved scope. If a required document is out of scope, '
    'report its exact missing path; the reviewer must request changes with a finding attributed to '
    'an existing approved file. The main coordinator must confirm scope and prepare a new run; '
    'repair rounds do not expand approval. Documentation completeness is a semantic reviewer '
    'judgment, not something proven by a Markdown extension check.'
)


def load_policy():
    policy = json.loads(CONFIG.read_text(encoding='utf-8'))
    bounds = {'max_tasks': 8, 'max_rounds': 3, 'max_plan_attempts': 3, 'agent_timeout_seconds': 1800,
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
    # A caller-selected private config may be outside the usual protected logs.
    # Never make it model-readable even if mistakenly included in approved scope.
    private_config = storage.resolve_storage(root).config_path
    for name in names:
        if private_config == root / name:
            raise ValueError('Private storage config cannot be assigned to a model.')
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


def status_object(data):
    def unique_fields(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError('Duplicate workflow status metadata.')
            result[name] = value
        return result

    def invalid_constant(value):
        raise ValueError('Invalid workflow status number.')

    return json.loads(data, object_pairs_hook=unique_fields, parse_constant=invalid_constant)


class PlanScopeError(ValueError):
    """Scope and ownership violations are fatal, never plan repair candidates."""


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
        try:
            files = triage.scoped_paths(task['files'], 128)
        except ValueError:
            raise PlanScopeError('Coordinator supplied invalid file scope.') from None
        if files != sorted(task['files']) or set(files) - set(scope) or \
                any(owner(name) != task['role'] for name in files):
            raise PlanScopeError('Coordinator changed the declared scope or file owner.')
        if assigned & set(files):
            raise ValueError('Each scoped file must have exactly one implementation task.')
        assigned.update(files)
    if assigned != set(scope):
        raise ValueError('Coordinator plan did not cover every scoped file.')
    return tasks


def parse_review(response, scope, changed_files=()):
    review = object_response(response)
    if set(review) != {'verdict', 'summary', 'findings', 'documentation'} or \
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
    documentation = review['documentation']
    if not isinstance(documentation, dict) or set(documentation) != {'status', 'files', 'reason'} or \
            documentation['status'] not in ('updated', 'not_required', 'missing') or \
            not isinstance(documentation['reason'], str) or not documentation['reason'].strip() or \
            not isinstance(documentation['files'], list):
        raise ValueError('Invalid reviewer documentation judgment.')
    files = documentation['files']
    if any(not isinstance(name, str) or name not in scope or Path(name).suffix != '.md'
           for name in files) or len(set(files)) != len(files):
        raise ValueError('Documentation files must be unique approved Markdown paths.')
    if documentation['status'] == 'updated' and (not files or set(files) - set(changed_files)):
        raise ValueError('Updated documentation must reference actual changed Markdown files.')
    if documentation['status'] == 'not_required' and files:
        raise ValueError('Unnecessary documentation must have an empty file list.')
    if documentation['status'] == 'missing' and review['verdict'] != 'changes_requested':
        raise ValueError('Missing documentation requires scoped findings and changes_requested.')
    return review


def required_checks(scope, recommendation):
    checks = set(triage.path_rules(scope)['required_checks'])
    checks.update(recommendation['required_checks'])
    checks.update(agent_models.load_config()['roles'][owner(name)]['check'] for name in scope)
    return ['check'] if 'check' in checks else sorted(checks)


def round_checks(changes, recommendation, previous):
    return check_selection.local_checks(
        changes, recommendation, previous, owner=owner, path_rules=triage.path_rules,
        role_check=lambda role: agent_models.load_config()['roles'][role]['check'])


def storage_policy():
    return storage.resolve_storage(ROOT)


def local_reports():
    # ROOT/REPORTS are deliberate test seams; an imported original root must not
    # leak into an isolated project when only ROOT was changed.
    return REPORTS if REPORTS != _DEFAULT_REPORTS else ROOT / 'logs/harness/workflows'


def check_environment(keys):
    env = agent_models.child_environment('codex', keys)
    env.pop('PYTHONPATH', None)
    env.pop('PYTEST_ADDOPTS', None)
    env.pop('PYTEST_PLUGINS', None)
    # Validation receives only the policy supplied by its trusted parent below.
    # Model children must independently strip these in agent_models.
    env.pop(storage.CONFIG_ENV, None)
    env.pop(storage.REPORT_ENV, None)
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    env['TAVERN_WORKFLOW_CHILD'] = '1'
    return env


def run_check(candidate, command, report_dir, keys, policy):
    if command not in CHECKS + ('doctor',):
        raise ValueError('Check command is not allowlisted.')
    selected = storage_policy()
    selected.ensure_directory(report_dir)
    if command == 'check-docs':
        data = docs_check.check(candidate, policy.get('_docs_changes'))
        path = report_dir / 'check-docs.json'
        agent_models.private_json(path, data, policy=selected)
        return {'command': command, 'status': data['status'],
                'exit_code': 0 if data['status'] == 'passed' else 1,
                'report': str(path), 'checks': data['checks']}
    env = check_environment(keys)
    if selected.configured:
        # The original artifact root contains the validation source snapshot.
        # Give the trusted runner its own disjoint application roots instead of
        # weakening the resolver's repository-ancestry checks. Neither this
        # config nor its path is copied into the model workspace/environment.
        with selected.temporary_directory(prefix='tavern-workflow-check-') as temporary:
            artifacts = report_dir
            mount = selected.artifacts.required_mount
            if mount not in artifacts.parents or artifacts == candidate or \
                    artifacts in candidate.parents or candidate in artifacts.parents or \
                    artifacts == temporary or artifacts in temporary.parents:
                artifacts = selected.artifact_root / ('validation-' + secrets.token_hex(8))
            selected.ensure_directory(artifacts)
            config = report_dir / 'storage-validation.json'
            agent_models.private_json(config, {
                'version': 1,
                'artifacts': {'path': str(artifacts), 'required_mount': str(mount),
                              'min_free_bytes': selected.artifacts.min_free_bytes},
                'temporary': {'path': str(temporary),
                              'required_mount': str(selected.temporary.required_mount),
                              'min_free_bytes': selected.temporary.min_free_bytes},
            }, policy=selected)
            env[storage.CONFIG_ENV] = str(config)
            env.update(TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary))
            selected.check_ready()
            result = subprocess.run([sys.executable, '-m', 'harness', command,
                                     '--report-dir', str(report_dir)], cwd=str(candidate),
                                    env=env, capture_output=True, text=True,
                                    timeout=policy['check_timeout_seconds'])
    else:
        result = subprocess.run([sys.executable, '-m', 'harness', command,
                                 '--report-dir', str(report_dir)], cwd=str(candidate),
                                env=env, capture_output=True, text=True,
                                timeout=policy['check_timeout_seconds'])
    selected.check_ready()
    log = report_dir / (command + '.log')
    parent = selected.fs.open_directory(report_dir)
    try:
        fd = os.open(log.name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(agent_models.redact(result.stdout + result.stderr, keys))
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
        passed = passed and failure_feedback.check_groups_passed(groups)
    return {'command': command, 'status': 'passed' if passed else 'failed',
            'exit_code': result.returncode, 'report': str(path), 'log': str(log),
            'checks': groups}


class Progress:
    def __init__(self, directory, report, keys, selected):
        self.directory, self.report, self.keys = directory, report, keys
        self.storage = selected

    def save(self):
        safe = triage.scrub(self.report, self.keys)
        agent_models.private_json(self.directory / 'report.json', safe, policy=self.storage)
        agent_models.private_json(self.directory.parent / 'latest.json',
                                  {'run_id': safe['run_id']}, policy=self.storage)

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
        self.storage.check_ready()
        path = self.storage.record_path(self.directory, 'events.jsonl', local_default=local_reports())
        parent = self.storage.fs.open_directory(self.directory)
        try:
            fd = os.open(path.name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
        finally:
            os.close(parent)
        with os.fdopen(fd, 'a', encoding='utf-8') as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(json.dumps(safe, ensure_ascii=False) + '\n')
        identity = ' / '.join(value for value in (role, safe['provider'], safe['model']) if value)
        print('{}[{}/{} {}] {} · {}{}'.format('[fixture] ' if self.report['simulated'] else '',
              safe['stage'], len(PHASES), PHASES[phase], state,
              identity or 'harness', ' · ' + str(safe['detail']) if 'detail' in safe else ''), flush=True)


def model_step(progress, candidate, phase, role, task, keys, policy, runner,
               scope=(), write=False, task_id=None):
    before = workspace.manifest(candidate, policy)
    progress.event(phase, 'running', role, agent_started=not progress.report['simulated'], task_id=task_id)
    task += '\nApproved readable files (exact paths): ' + json.dumps(progress.report['scope'])
    result = triage.scrub(runner(role, agent_models.redact(task, keys), keys, write=write,
                                timeout=policy['agent_timeout_seconds'], workspace=candidate,
                                scoped=True), keys)
    progress.report['agents'].append({'phase': phase, 'task_id': task_id,
                                     'prompt_sha256': triage.digest(agent_models.redact(task, keys)), **result})
    progress.save()
    if result['status'] != 'passed':
        raise ValueError('Agent failed: {}. See the private agent report.'.format(role))
    workspace.enforce_scope(before, workspace.manifest(candidate, policy), scope, read_only=not write)
    progress.event(phase, 'responded' if phase in ('plan', 'review', 'github') else 'passed',
                   role, task_id=task_id)
    return result['response']


def repair_feedback(progress, tasks, items, round_number, attempts, previous, keys, read_only, policy):
    targets = failure_feedback.route(tasks, items)
    evidence, pending = [], {}
    for index, own in targets.items():
        identity = failure_feedback.fingerprint(own)
        recurring = previous.get(index) == identity
        changed = attempts[index]['source_changed']
        payload = {'task_id': index, 'files': tasks[index]['files'], 'attempt_round': round_number,
                   'implementation_attempt_round': attempts[index]['round'],
                   'failure_fingerprint': identity, 'same_failure_recurred': recurring,
                   'preceding_attempt_source_changed': changed, 'diagnostics': own}
        text = ('Required correction; do not run checks yourself. Diagnostics contain only approved '
                'source context or scoped reviewer findings. Unavailable/unattributed context has no '
                'known cause; conservatively inspect only your assigned files or report missing context. '
                'All originally required checks will run after a fresh review.\n' +
                json.dumps(payload, ensure_ascii=False))
        if recurring:
            text += '\nThe same failure recurred.'
        if not changed:
            text += '\nThe preceding implementation attempt made no assigned source change.'
        text = agent_models.redact(text, keys)
        evidence.append({**payload, 'role': tasks[index]['role'], 'feedback': text,
                         'sent': False})
        pending[index] = text
        previous[index] = identity
    record = {'round': round_number, 'target_tasks': list(targets),
              'target_files': sorted({name for index in targets for name in tasks[index]['files']}),
              'fallback': any(item.get('attribution') == 'unattributed' for item in items),
              'assignments': evidence}
    progress.report['repairs'].append(record)
    progress.event('implement', 'repair_targets', **triage.scrub(record, keys))
    if read_only:
        raise ValueError('Read-only failure; repair retries disabled; originals are preserved.')
    if round_number == policy['max_rounds']:
        no_progress = any(item['same_failure_recurred'] and
                          not item['preceding_attempt_source_changed'] for item in evidence)
        category = 'no_progress' if no_progress else 'exhausted_repair'
        progress.report['repair_failure'] = category
        progress.event('implement', category, round=round_number, target_tasks=list(targets))
        raise ValueError(category + ': required correction failed within max_rounds; originals are preserved.')
    if not pending:
        raise ValueError('No approved repair task; originals are preserved.')
    return pending


def execute(task, files, read_only=False, rules_only=False, simulated=False,
            runner=None, checker=None, keys=None, fixture=None, no_git=False,
            _improvement_guard=None):
    if os.environ.get('TAVERN_WORKFLOW_CHILD'):
        raise ValueError('Workflow workers must not start another workflow.')
    if os.environ.get('TAVERN_IMPROVEMENT_DISCOVERY') or (
            os.environ.get('TAVERN_IMPROVEMENT_UNATTENDED') and not read_only):
        raise ValueError('Unattended improvement discovery cannot start a development workflow.')
    policy = load_policy()
    github_enabled = not (read_only or simulated or no_git) and git_publish.load_config()['enabled']
    scope = scoped_files(ROOT, files)
    if not task.strip() or len(task.encode('utf-8')) > triage.load_policy()['max_task_bytes']:
        raise ValueError('Task is empty or too large.')
    keys = agent_models.load_keys() if keys is None else keys
    task = agent_models.redact(task, keys)
    runner, checker = runner or agent_models.run, checker or run_check
    selected = storage_policy()
    reports = selected.workflow_root(local_default=local_reports())
    selected.ensure_directory(reports)
    # Execution ownership is local and stable across storage v1/v2/overrides.
    # Source protection uses the historical inode only during capture/apply.
    lock = contextlib.ExitStack()
    source_lock = contextlib.ExitStack()
    try:
        lock.enter_context(project_lock.hold(selected, kind='workflow_lock', reentrant=False))
        if _improvement_guard is not None and hasattr(_improvement_guard, 'state_lock'):
            source_lock.enter_context(_improvement_guard.state_lock())
        source_lock.enter_context(project_lock.hold(selected, reentrant=False))
    except BlockingIOError:
        source_lock.close()
        lock.close()
        raise ValueError('Another workflow is running in this repository.') from None
    except BaseException:
        source_lock.close()
        lock.close()
        raise
    run_id = str(time.time_ns()) + '-' + secrets.token_hex(3)
    directory = reports / run_id
    try:
        # The trusted improvement parent claims authorization before entry, then
        # revalidates it here under the same lock used by apply and cleanup.
        # Ordinary explicit-user workflows retain their existing authority.
        if _improvement_guard is not None:
            _improvement_guard(run_id)
        selected.check_ready()
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
        selected.validate_run_directory(directory, local_default=local_reports())
    except BaseException:
        source_lock.close()
        lock.close()
        raise
    candidate = directory / 'workspace'
    report = {'run_id': run_id, 'policy_version': policy['version'], 'pid': os.getpid(),
              'status': 'running', 'read_only': read_only, 'simulated': simulated,
              'scope': scope, 'task_sha256': triage.digest(task),
              'workspace': str(candidate), 'model_read_scope': scope,
              'agents': [], 'events': [], 'validation': [], 'plan_attempts': [],
              'implementation_attempts': [], 'repairs': [],
              'applied': [], 'report': str(directory / 'report.json')}
    report['github_enabled'] = github_enabled
    report['no_git'] = no_git
    progress = Progress(directory, report, keys, selected)
    context_cleanup = contextlib.ExitStack()
    context_dir = None
    try:
        progress.event('prepare', 'running', detail='승인 파일 모델 사본과 로컬 검증 사본을 분리해 생성')
        # Policy is a source dependency too; use its value at the capture boundary.
        policy = load_policy()
        selected.check_ready()
        baseline = workspace.copy_validation_sources(ROOT, candidate, scope, policy)
        # Everything below reads isolated copies until the final apply section.
        # A legacy long holder still blocks this capture; never bypass its inode.
        source_lock.close()
        candidate.chmod(0o700)
        agent_models.private_json(directory / 'baseline.json', baseline, policy=selected)
        # Review the captured input, even if the live repository changes during
        # an unlocked model/check phase. Keep only approved original files.
        original = directory / 'original'
        workspace.copy_sources(candidate, original, scope, policy)
        original.chmod(0o700)
        # Outside repository ancestry: native CLIs must not discover parent project
        # instructions. The local verification snapshot is never a model workspace.
        context_dir = context_cleanup.enter_context(selected.temporary_directory(
            prefix='tavern-model-context-', purpose='context'))
        if context_dir == ROOT or ROOT in context_dir.parents or context_dir in ROOT.parents:
            raise ValueError('Model context must be outside repository ancestry.')
        model_context = context_dir / 'sources'
        model_baseline = workspace.copy_sources(candidate, model_context, scope, policy)
        model_context.chmod(0o700)
        report['model_workspace'] = str(model_context)
        report['model_context_manifest'] = str(directory / 'model-context.json')
        agent_models.private_json(directory / 'model-context.json',
                                  {'approved_files': scope, 'copied_files': model_baseline}, policy=selected)
        # Actual docs-only edits can have code in their read scope. Defer the
        # dependency doctor until final changes are known whenever prose is in
        # scope; the ordinary full runner still owns its doctor gate.
        environment_checked = False
        if not any(docs_check.prose(name) for name in scope):
            selected.ensure_directory(directory / 'prepare')
            result = checker(candidate, 'doctor', directory / 'prepare', keys, policy)
            report['environment'] = result
            if result['status'] != 'passed':
                raise ValueError('Harness environment is not ready.')
            environment_checked = True
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
            prompt += '\n' + DOCUMENTATION_GUIDANCE
            original_prompt = prompt
            for plan_attempt in range(1, policy['max_plan_attempts'] + 1):
                attempt = {'attempt': plan_attempt, 'status': 'running'}
                report['plan_attempts'].append(attempt)
                progress.event('plan', 'attempt', 'coordinator', attempt=plan_attempt)
                # CLI failures and read-only scope enforcement are outside the
                # parse recovery boundary; neither is retried.
                try:
                    response = model_step(progress, model_context, 'plan', 'coordinator', prompt, keys, policy, runner)
                except Exception:
                    attempt.update(status='failed', diagnostic={'category': 'planner_execution'})
                    progress.event('plan', 'rejected', 'coordinator', **attempt)
                    raise
                try:
                    tasks = parse_plan(response, scope, policy)
                except PlanScopeError:
                    attempt.update(status='failed', diagnostic={'category': 'scope_or_owner_violation'})
                    progress.event('plan', 'rejected', 'coordinator', **attempt)
                    raise
                except (json.JSONDecodeError, ValueError) as exc:
                    diagnostic = {'category': 'json_syntax' if isinstance(exc, json.JSONDecodeError)
                                  else 'plan_schema'}
                    if isinstance(exc, json.JSONDecodeError):
                        diagnostic.update(line=exc.lineno, column=exc.colno, position=exc.pos)
                    attempt.update(status='invalid', diagnostic=diagnostic)
                    progress.event('plan', 'invalid', 'coordinator', **attempt)
                    if plan_attempt == policy['max_plan_attempts']:
                        raise ValueError('Plan attempts exhausted; no implementation or application allowed.') from None
                    prompt = (original_prompt + '\nTrusted plan diagnostic: ' + json.dumps(diagnostic) +
                              '\nReturn a fresh short complete valid JSON object with exactly tasks. '
                              'Each task has exactly role (supplied owner), task (nonempty string), '
                              'files (nonempty approved path list). Cover each supplied file once. '
                              'Correctly escape task strings; avoid embedded unescaped quotes or code. '
                              'No extra text. Keep the exact original owners and file scope.')
                else:
                    attempt.update(status='accepted', recovered=plan_attempt > 1)
                    report['plan_recovered'] = plan_attempt > 1
                    progress.event('plan', 'recovered' if plan_attempt > 1 else 'accepted',
                                   'coordinator', **attempt)
                    break
        else:
            tasks = [{'role': recommendation['role'], 'task': task, 'files': scope}]
            progress.event('plan', 'direct', detail='Jev와 경로 규칙이 일치해 담당자에 직접 배정')
        report['tasks'] = tasks
        pending = {index: '' for index in range(len(tasks))}
        previous, attempts = {}, {}
        for round_number in range(1, policy['max_rounds'] + 1):
            report['round'] = round_number
            for index, feedback in pending.items():
                assigned = tasks[index]
                before_attempt = workspace.manifest(model_context, policy)
                prompt = ('Original request:\n{}\nAssigned task:\n{}\n'
                          'Allowed edit files (exact paths): {}\n'
                          'Preserve existing user edits. {} '
                          'Do not run checks, agent-run, harness.workflow, cron or operating data pipelines. '
                          'The orchestrator runs checks. Report your result and remaining concerns.\n{}').format(
                              task, assigned['task'], json.dumps(assigned['files'], ensure_ascii=False),
                              'Do not edit any files; this is analysis only.' if read_only else
                              'Implement the assigned change only in the allowed files.', feedback)
                prompt += '\n' + DOCUMENTATION_GUIDANCE
                if feedback:
                    assignment = next(item for item in report['repairs'][-1]['assignments']
                                      if item['task_id'] == index)
                    assignment['sent'] = True
                    progress.event('implement', 'repair_feedback', assigned['role'], task_id=index,
                                   round=round_number, feedback=feedback)
                model_step(progress, model_context, 'implement', assigned['role'], prompt, keys, policy,
                           runner, assigned['files'], write=not read_only, task_id=index)
                after_attempt = workspace.manifest(model_context, policy)
                source_changed = any(before_attempt.get(name, {}).get('sha256') !=
                                     after_attempt.get(name, {}).get('sha256') for name in assigned['files'])
                attempts[index] = {'round': round_number, 'task_id': index,
                                   'files': assigned['files'], 'source_changed': source_changed,
                                   'before': {name: before_attempt.get(name) for name in assigned['files']},
                                   'after': {name: after_attempt.get(name) for name in assigned['files']}}
                report['implementation_attempts'].append(attempts[index])
                progress.event('implement', 'source_progress', assigned['role'], task_id=index,
                               round=round_number, source_changed=source_changed)
            workspace.sync_scope(model_context, candidate, model_baseline, scope, policy, read_only=read_only)
            candidate_manifest = workspace.manifest(candidate, policy)
            changes = workspace.enforce_scope(baseline, candidate_manifest, scope, read_only=read_only)
            diff = workspace.diff_text(original, candidate, changes, policy['max_diff_bytes'])
            diff_path = directory / 'changes.diff'
            diff_path.write_text(agent_models.redact(diff, keys), encoding='utf-8')
            diff_path.chmod(0o600)
            report['changed_files'] = changes
            summaries = [agent['response'] for agent in report['agents'] if agent['phase'] == 'implement']
            prompt = ('Review the task outcome and candidate source against the original request. '
                      'Return ONLY JSON with exactly verdict, summary, findings, documentation. '
                      'verdict is approved or changes_requested. approved requires findings=[]. '
                      'Otherwise each finding has file (one of the scoped files), severity '
                      '(high/medium/low) and message. Inspect source as needed; do not edit files. '
                      'documentation has exactly status, files, reason. status is updated, not_required '
                      'or missing; reason is a nonempty string explaining the concrete impact judgment. '
                      'files is a unique list of approved .md paths. updated requires at least one '
                      'actual changed .md file and may reference only changed documents. not_required '
                      'requires files=[] and a specific reason. missing requires changes_requested '
                      'and nonempty findings attributed to approved files, even when the needed '
                      'document itself is outside scope (name the missing path in reason/message). '
                      'No changes is acceptable for an analysis request or an already satisfied request, '
                      'but reject an unimplemented requested fix.\nRead only: {}\nScope: {}\n'
                      'Request: {}\nImplementation results: {}\nDiff:\n{}').format(
                          read_only, json.dumps(scope), task, json.dumps(summaries, ensure_ascii=False), diff)
            prompt += '\nActual changed files: ' + json.dumps(changes) + '\n' + DOCUMENTATION_GUIDANCE
            response = model_step(progress, model_context, 'review', 'reviewer', prompt, keys, policy, runner)
            review = parse_review(response, scope, changes)
            report['review'] = review
            if review['verdict'] != 'approved':
                progress.event('review', 'changes_requested', 'reviewer', round=round_number)
                findings = [{'file': item['file'], 'severity': item['severity'],
                             'message': item['message'][:2000], 'category': 'review_changes_requested'}
                            for item in review['findings']]
                pending = repair_feedback(progress, tasks, findings, round_number, attempts,
                                          previous, keys, read_only, policy)
                continue
            progress.event('review', 'approved', 'reviewer', round=round_number)
            selection = docs_check.classify(docs_check.manifest_changes(baseline, candidate_manifest))
            selection['digest'] = docs_check.change_digest(baseline, candidate_manifest)
            report['validation_selection'] = selection
            selected_checks = round_checks(selection['changes'], recommendation, checks)
            if selection['mode'] == 'docs' and selected_checks != ['check-docs']:
                selection.update(mode='full', reason='shared_contract_change')
            selection['local_checks'] = selected_checks
            report['required_checks'] = selected_checks
            round_policy = {**policy, '_docs_changes': selection['changes']}
            if selection['mode'] != 'docs' and not environment_checked:
                selected.ensure_directory(directory / 'prepare')
                result = checker(candidate, 'doctor', directory / 'prepare', keys, policy)
                report['environment'] = result
                if result['status'] != 'passed':
                    raise ValueError('Harness environment is not ready.')
                environment_checked = True
            failures, round_validation = [], []
            for command in selected_checks:
                progress.event('validate', 'running', detail=command, round=round_number)
                selected.check_ready()
                check_dir = selected.ensure_directory(directory / ('checks-' + str(round_number)) / command)
                result = checker(candidate, command, check_dir,
                                 keys, round_policy)
                result['validation_digest'] = selection['digest']
                # A successful CLI/fixture status cannot override structured
                # failures, skipped coverage, or a nonzero process exit.
                if result.get('status') != 'passed' or result.get('exit_code', 0) != 0 or \
                        (not (simulated and command != 'check-docs' and result.get('checks') == {}) and
                         not failure_feedback.check_groups_passed(result.get('checks'))):
                    result = {**result, 'status': 'failed'}
                report['validation'].append(result)
                round_validation.append(result)
                workspace.enforce_scope(candidate_manifest, workspace.manifest(candidate, policy), [], read_only=True)
                progress.event('validate', result['status'], detail=command, round=round_number)
                if result['status'] != 'passed':
                    failures.append(result)
            if failures:
                items = failure_feedback.diagnostics(failures, candidate, model_context, scope, policy)
                pending = repair_feedback(progress, tasks, items, round_number, attempts,
                                          previous, keys, read_only, policy)
                continue
            report['delivery_validation'] = round_validation
            progress.event('apply', 'running', detail='읽기 전용/데모는 원본에 반영하지 않음' if read_only or simulated else '')
            if not read_only and not simulated:
                state_guard = getattr(_improvement_guard, 'state_lock', contextlib.nullcontext)
                with state_guard(), project_lock.hold(selected, reentrant=False):
                    validate_apply = getattr(_improvement_guard, 'validate_apply', None)
                    if validate_apply is not None:
                        validate_apply(run_id)
                    selected.check_ready()
                    selected.ensure_directory(directory / 'backup')
                    report['applied'] = workspace.publish(ROOT, candidate, baseline, candidate_manifest, changes,
                                                          scope, directory / 'backup', policy)
            report['status'] = ('running' if github_enabled and changes else
                                ('demonstrated' if simulated else 'passed'))
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
                selected.check_ready()
                with project_lock.hold(selected, reentrant=False):
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
        try:
            try:
                context_cleanup.close()
                if context_dir is not None:
                    report['model_context_cleanup'] = {'status': 'passed'}
            except BaseException as exc:
                report['status'] = 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed'
                report['model_context_cleanup'] = {
                    'status': 'failed', 'error_type': type(exc).__name__,
                    'error': agent_models.redact(str(exc), keys)}
                report.setdefault('error_type', type(exc).__name__)
                report.setdefault('error', report['model_context_cleanup']['error'])
            finally:
                report['finished_at'] = datetime.now(timezone.utc).isoformat()
                progress.save()
        finally:
            source_lock.close()
            lock.close()
    if selected.version == 2 and report['status'] in archive.TERMINAL:
        try:
            report['archive'] = archive.archive_run(selected, directory)
        except (Exception, KeyboardInterrupt) as exc:
            report['archive'] = {'status': 'pending', 'error_type': type(exc).__name__}
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
            response = {'verdict': 'approved', 'summary': 'Fixture review only.', 'findings': [],
                        'documentation': {'status': 'not_required', 'files': [],
                                          'reason': 'Only a private demonstration text file changes; '
                                                    'harness behavior and design remain unchanged.'}}
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
            selected = storage_policy()
            directory = (selected.find_run(args.run_id, local_default=local_reports()) if args.run_id
                         else selected.latest_run(local_default=local_reports()))
            record = selected.record_path(directory, 'report.json', local_default=local_reports())
            report = status_object(selected.fs.read_bytes(record))
            state = directory / 'archive-state.json'
            if selected.version == 2 and storage._info(selected.fs, state) is not None:
                report['archive'] = status_object(selected.fs.read_bytes(state))
            elif selected.version == 2 and report.get('status') in archive.TERMINAL:
                report['archive'] = {'status': 'pending', 'reason': 'archive_not_recorded'}
            if selected.version == 2 and storage._info(selected.fs, directory / archive.RESUMED) is not None:
                report['archive_original'] = report.get('archive', {})
                report['archive'] = archive.resumed_status(selected, directory)
            if not isinstance(report, dict) or report.get('run_id') != directory.name or \
                    not isinstance(report.get('status'), str) or \
                    not isinstance(report.get('github', {}), dict) or \
                    not isinstance(report.get('github', {}).get('cleanup', {}), dict):
                raise ValueError('Invalid workflow status record.')
            if report.get('status') == 'passed' and report.get('github', {}).get('merge_sha') and \
                    not git_publish.cleanup_complete(report['github']):
                # Old reports prove merge only. Display the explicit migration
                # boundary without rewriting historical evidence during status.
                report['status'] = 'cleanup_pending'
                report['github'] = {**report['github'], 'merge_status': 'merged',
                                    'cleanup': {**report['github'].get('cleanup', {}),
                                                'status': 'cleanup_pending', 'proof': {
                                                    'status': 'pending', 'reason': 'legacy_cleanup_required'}}}
            if report['status'] == 'running':
                if type(report.get('pid')) is not int or report['pid'] <= 0:
                    raise ValueError('Invalid workflow process metadata.')
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
                   'changed_files', 'applied', 'report', 'error', 'simulated', 'github', 'archive',
                   'archive_original') if name in report}
        print(json.dumps(summary if args.command != 'plan' else report, ensure_ascii=False, indent=2))
        # Exit 0 hands control to the parent; awaiting_github still means incomplete.
        return 0 if report.get('status', 'passed') in ('passed', 'running', 'demonstrated', 'awaiting_github') and report.get('archive', {}).get('status') != 'pending' else 1
    except storage.StorageError as exc:
        print('Workflow failed: StorageError: {}'.format(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('Workflow failed: {}'.format(type(exc).__name__), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
