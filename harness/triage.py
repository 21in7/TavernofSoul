"""Observe Jev task-routing recommendations without starting or editing agents."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from harness import agent_models, jev_client

ROOT = agent_models.ROOT
CONFIG = ROOT / 'harness' / 'triage-config.json'
REPORTS = ROOT / 'logs' / 'harness' / 'triage'
DOMAINS = ('downloader', 'parser', 'django')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode('utf-8')).hexdigest()


def load_policy():
    policy = json.loads(CONFIG.read_text(encoding='utf-8'))
    try:
        if not re.fullmatch(r'jev-[A-Za-z0-9._-]+', policy['model']) or \
                not isinstance(policy['policy_version'], str) or not policy['policy_version']:
            raise ValueError()
        jev_client.number(policy['timeout_seconds'], 0.1, 30)
        for name, maximum in (('max_task_bytes', 24000), ('max_files', 128)):
            if isinstance(policy[name], bool) or not isinstance(policy[name], int) or \
                    not 0 < policy[name] <= maximum:
                raise ValueError()
        thresholds = policy['thresholds']
        for name in ('domain_confidence', 'complexity_confidence', 'contract_clear_max'):
            jev_client.number(thresholds[name], 0, 1)
        jev_client.number(thresholds['direct_complexity_max'], 0, 2)
        questions = policy['questions']
        if set(questions) != {'domain', 'complexity', 'contract_impact'} or \
                questions['domain']['type'] != 'choice' or \
                not isinstance(questions['domain']['criteria'], dict) or \
                set(questions['domain']['criteria']) != set(DOMAINS + ('cross_boundary', 'unknown')) or \
                questions['complexity']['type'] != 'score' or \
                not isinstance(questions['complexity']['criteria'], list) or \
                len(questions['complexity']['criteria']) != 3 or \
                questions['contract_impact']['type'] != 'noul' or \
                not isinstance(questions['contract_impact']['criteria'], dict) or \
                set(questions['contract_impact']['criteria']) != {'true', 'false'}:
            raise ValueError()
        for question in questions.values():
            if not isinstance(question['instructions'], str) or not question['instructions']:
                raise ValueError()
            levels = (question['criteria'].values() if isinstance(question['criteria'], dict)
                      else question['criteria'])
            if any(not isinstance(level, str) or not level.strip() for level in levels):
                raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError('Invalid triage policy.') from None
    return policy


def scoped_paths(files, limit):
    if len(files) > limit:
        raise ValueError('Too many scoped paths.')
    paths = set()
    for value in files:
        if not isinstance(value, str) or not value or any(char in value for char in '\r\n\0\\'):
            raise ValueError('Invalid scoped path.')
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.relative_to(ROOT)
            except ValueError:
                raise ValueError('Scoped paths must be inside the repository.') from None
        if not path.parts or '..' in path.parts or len(str(path).encode('utf-8')) > 512:
            raise ValueError('Invalid scoped path.')
        paths.add(path.as_posix())
    return sorted(paths)


def path_rules(files):
    areas, protected = set(), []
    shared, review = False, False
    for path in files:
        parts = Path(path).parts
        runtime = (parts[0] in ('.git', '.codex', '.claude', 'IPFUnpacker', 'Translation') or
                   parts[0].endswith(('_patch', '_unpack')) or
                   any(part.startswith('JSON_') for part in parts) or
                   path in ('.env', '.agent-keys.json', 'downloader/release.csv',
                            'downloader/revision.csv', 'parser_tidy/parser_version.csv'))
        if runtime:
            protected.append(path)
        area = {'downloader': 'downloader', 'parser_tidy': 'parser',
                'TavernofSoul': 'django'}.get(parts[0], 'cross_boundary')
        areas.add(area)
        contract = (path.startswith('TavernofSoul/ipfparser/') or
                    path in ('parser_tidy/DB.py', 'parser_tidy/main.py', 'docs/data-contracts.md'))
        shared = shared or contract or parts[0] == 'harness' or path.startswith('cron_')
        review = review or contract or path.endswith('/models.py') or '/migrations/' in path or \
            path in ('parser_tidy/luautil.py', 'parser_tidy/items.py', 'parser_tidy/skills.py')
    domain = next(iter(areas)) if len(areas) == 1 and not shared and not protected else 'cross_boundary'
    if not files:
        domain = 'unknown'
    check = {'downloader': 'check-downloader', 'parser': 'check-parser', 'django': 'check-django'}.get(domain, 'check')
    return {'domain': domain, 'required_checks': [check],
            'requires_planning': domain not in DOMAINS or bool(protected),
            'requires_review': bool(review), 'protected_paths': protected}


def recommendation(rules, answers=None, error=None, policy=None):
    reasons = []
    role = rules['domain'] if rules['domain'] in DOMAINS else 'coordinator'
    review = rules['requires_review']
    if rules['requires_planning']:
        reasons.append('path_rules_require_planning')
    if error:
        reasons.append(error)
    if answers:
        thresholds = policy['thresholds']
        domain, complexity = answers['domain'], answers['complexity']
        if domain['choice'] not in DOMAINS:
            reasons.append('jev_domain_requires_planning')
        if domain['choice'] != rules['domain']:
            reasons.append('domain_disagrees_with_paths')
        if domain['confidence'] < thresholds['domain_confidence']:
            reasons.append('low_domain_confidence')
        if complexity['confidence'] < thresholds['complexity_confidence']:
            reasons.append('low_complexity_confidence')
        if complexity['score'] > thresholds['direct_complexity_max']:
            reasons.append('implementation_planning_needed')
        if answers['contract_impact']['noul'] > thresholds['contract_clear_max']:
            reasons.append('possible_contract_impact')
            review = True
    if reasons:
        role = 'coordinator'
    checks = ['check'] if role == 'coordinator' else list(rules['required_checks'])
    spec = agent_models.load_config()['roles'][role]
    return {'role': role, 'provider': spec['provider'], 'model': spec['model'],
            'required_checks': checks, 'review_required': review,
            'reasons': reasons or ['clear_local_task'], 'execution_allowed': False}


def scrub(value, keys):
    if isinstance(value, str):
        return agent_models.redact(value, keys)
    if isinstance(value, list):
        return [scrub(item, keys) for item in value]
    if isinstance(value, dict):
        return {name: scrub(item, keys) for name, item in value.items()}
    return value


def observe(task, files, live=False, fixture=None, expected_role=None):
    policy = load_policy()
    if live and fixture is not None:
        raise ValueError('Choose either a live request or a response fixture.')
    if not isinstance(task, str) or not task.strip() or len(task.encode('utf-8')) > policy['max_task_bytes']:
        raise ValueError('Task must be non-empty and within max_task_bytes; it is never truncated.')
    paths = scoped_paths(files, policy['max_files'])
    rules = path_rules(paths)
    report = {'mode': 'shadow', 'agent_started': False, 'api_called': False,
              'policy_version': policy['policy_version'], 'policy_sha256': digest(policy),
              'requested_model': policy['model'], 'paths': paths, 'path_rules': rules,
              'status': 'fallback', 'source': 'rules_only'}
    keys, error, response = {}, None, None
    started = time.monotonic()
    try:
        keys = agent_models.load_keys()
        state = scrub({'task': task, 'scoped_files': paths, 'path_rules': rules}, keys)
        if len(json.dumps(state, ensure_ascii=False).encode('utf-8')) > 48000:
            raise ValueError('Triage state is too large.')
        report['state_sha256'] = digest(state)
        if rules['protected_paths']:
            error = 'protected_runtime_scope'
        elif fixture is not None:
            report['source'] = 'fixture'
            response = jev_client.validate_response(fixture, policy['questions'])
        elif not live:
            error = 'live_not_requested'
        elif not keys.get('TYPESAFE_API_KEY'):
            error = 'missing_typesafe_key'
        else:
            report.update(source='api', api_called=True)
            endpoint = agent_models.load_config()['providers']['typesafe']['endpoint']
            response = jev_client.evaluate(state, policy['questions'], keys['TYPESAFE_API_KEY'],
                                           policy['model'], policy['timeout_seconds'], endpoint)
        if response:
            report.update(status='passed', resolved_model=response['model'],
                          answers=response['answers'], usage=response['usage'])
    except jev_client.JevError as exc:
        error = exc.code
        diagnostic = jev_client.safe_diagnostic(exc.diagnostic)
        if diagnostic is not None:
            report['diagnostic'] = diagnostic
        if type(exc.http_status) is int:
            report['http_status'] = exc.http_status
    except (OSError, ValueError):
        error = 'local_configuration_or_input_error'
    report['elapsed_ms'] = round((time.monotonic() - started) * 1000, 2)
    report['recommendation'] = recommendation(rules, response['answers'] if response else None, error, policy)
    if error:
        report['fallback_reason'] = error
    if expected_role is not None:
        report['comparison'] = {'expected_role': expected_role,
                                'agrees': report['recommendation']['role'] == expected_role}
    return scrub(report, keys)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('recommend', 'smoke'))
    parser.add_argument('--task-file', type=Path)
    parser.add_argument('--files-file', type=Path)
    parser.add_argument('--file', action='append', default=[])
    parser.add_argument('--expected-role', choices=tuple(agent_models.load_config()['roles']))
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--live', action='store_true')
    source.add_argument('--fixture-response', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'smoke':
            if args.fixture_response or args.task_file or args.file or args.files_file or args.expected_role:
                parser.error('smoke accepts only --live')
            if not args.live:
                parser.error('smoke requires --live; it sends one TypeSafe request')
            task = 'Explain the retry logic in downloader/downloader.py without changing code.'
            files = ['downloader/downloader.py']
        else:
            if args.task_file is None:
                parser.error('recommend requires --task-file')
            policy = load_policy()
            if args.task_file.stat().st_size > policy['max_task_bytes']:
                raise ValueError('Task is too large.')
            task = args.task_file.read_text(encoding='utf-8')
            files = list(args.file)
            if args.files_file:
                if args.files_file.stat().st_size > 65536:
                    raise ValueError('Scoped path list is too large.')
                files += [line for line in args.files_file.read_text(encoding='utf-8').splitlines() if line]
        fixture = None
        if args.fixture_response:
            if args.fixture_response.stat().st_size > jev_client.MAX_RESPONSE_BYTES:
                raise ValueError('Response fixture is too large.')
            fixture = json.loads(args.fixture_response.read_text(encoding='utf-8'))
        report = observe(task, files, args.live, fixture, args.expected_role)
        path = REPORTS / '{}-{}.json'.format(args.command, time.time_ns())
        agent_models.private_json(path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('Report: {}'.format(path))
        # A usable fallback is still distinct from a successful Jev evaluation.
        return 0 if report['status'] == 'passed' or (not args.live and fixture is None) else 1
    except (OSError, ValueError):
        print('Triage failed: invalid input or configuration; no agent was started.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
