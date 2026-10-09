"""Inspect and exercise the pinned Claude Code compaction plugin."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from harness import agent_models

PLUGIN = agent_models.ROOT / 'harness' / 'compaction'
REPORTS = agent_models.ROOT / 'logs' / 'harness' / 'compaction'


def verify_vendor():
    vendor = PLUGIN / 'vendor'
    metadata = json.loads((vendor / 'UPSTREAM.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'[0-9a-f]{40}', metadata['commit']):
        raise ValueError('Invalid upstream pin.')
    for group in ('source_sha256', 'compiled_sha256'):
        if not metadata.get(group):
            raise ValueError('Missing vendor hashes.')
        for name, expected in metadata[group].items():
            path = vendor / name
            if path.is_symlink() or vendor.resolve() not in path.resolve().parents or \
                    hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Pinned vendor files differ; review and regenerate before use.')
    return metadata


def diagnostic_environment():
    env = agent_models.child_environment('codex', {})
    env['CLAUDE_CONFIG_DIR'] = str(REPORTS / 'runtime')
    return env


def doctor(keys):
    metadata = verify_vendor()
    report = {'status': 'not_configured', 'upstream_commit': metadata['commit'],
              'plugin': str(PLUGIN), 'key_registered': bool(keys.get('TYPESAFE_API_KEY')),
              'api_called': False, 'agent_started': False}
    cli = shutil.which('claude')
    if not cli:
        report['reason'] = 'Claude Code CLI is missing.'
        return report
    env = diagnostic_environment()
    version = subprocess.run([cli, '--version'], env=env, capture_output=True, text=True, timeout=20)
    match = re.match(r'(\d+)\.(\d+)\.(\d+)', version.stdout)
    minimum = agent_models.load_config()['compaction']['minimum_cli_version']
    if version.returncode or not match or tuple(map(int, match.groups())) < tuple(map(int, minimum.split('.'))):
        report['reason'] = 'Claude Code {} or newer is required.'.format(minimum)
        return report
    report['cli_version'] = match.group(0)
    result = subprocess.run([cli, 'plugin', 'validate', '--json', '--strict', str(PLUGIN)],
                            env=env, capture_output=True, text=True, timeout=30)
    validation = json.loads(result.stdout)
    report['validation'] = validation
    if result.returncode or validation.get('success') is not True:
        report['reason'] = 'Plugin validation failed.'
    elif not report['key_registered']:
        report['reason'] = 'Register TYPESAFE_API_KEY with agent-configure PROVIDER=typesafe.'
    else:
        report['status'] = 'passed'
    report['note'] = 'Local inspection only; actual session activation is separate from validation.'
    return report


def probe(live=False, keys=None):
    verify_vendor()
    node = shutil.which('node')
    if not node:
        raise ValueError('Node.js >= 18 is required.')
    env = diagnostic_environment()
    if live:
        key = (agent_models.load_keys() if keys is None else keys).get('TYPESAFE_API_KEY')
        if not key:
            raise ValueError('TYPESAFE_API_KEY is not registered.')
        env['TYPESAFE_API_KEY'] = key
    result = subprocess.run([node, str(PLUGIN / 'run.mjs'), 'smoke' if live else 'demo'],
                            env=env, capture_output=True, text=True, timeout=40)
    report = json.loads(result.stdout)
    if result.returncode or report.get('status') != 'passed':
        report['status'] = 'failed'
    return report


def engine_check():
    verify_vendor()
    cli = shutil.which('claude')
    if not cli:
        raise ValueError('Claude Code CLI is required for the engine check.')
    result = subprocess.run([cli, 'plugin', 'test', str(PLUGIN)], env=diagnostic_environment(),
                            capture_output=True, text=True, timeout=40)
    passed = re.search(r'^\s*(\d+) pass$', result.stdout, re.MULTILINE)
    failed = re.search(r'^\s*(\d+) fail$', result.stdout, re.MULTILINE)
    valid = result.returncode == 0 and passed and failed and int(passed.group(1)) > 0 and \
        int(failed.group(1)) == 0 and not re.search(r'^\s*\d+ (skip|todo)', result.stdout, re.MULTILINE)
    return {'status': 'passed' if valid else 'failed', 'source': 'claude_code_test_engine',
            'api_called': False, 'agent_started': False,
            'passed': int(passed.group(1)) if passed else 0,
            'failed': int(failed.group(1)) if failed else 0,
            'diagnostic': result.stdout + result.stderr}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('doctor', 'demo', 'smoke', 'engine'))
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args(argv)
    if args.live != (args.command == 'smoke'):
        parser.error('Only smoke uses --live; it sends the synthetic transcript to TypeSafe.')
    keys = {}
    try:
        keys = agent_models.load_keys() if args.command in ('doctor', 'smoke') else {}
        if args.command == 'doctor':
            report = doctor(keys)
        elif args.command == 'engine':
            report = engine_check()
        else:
            report = probe(live=args.live, keys=keys)
    except (OSError, ValueError, subprocess.SubprocessError):
        report = {'status': 'failed', 'reason': 'Compaction inspection or probe failed; check configuration.'}
    report = json.loads(agent_models.redact(json.dumps(report, ensure_ascii=False), keys))
    path = REPORTS / '{}-{}.json'.format(args.command, time.time_ns())
    agent_models.private_json(path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('Report: {}'.format(path))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
