"""Connect project roles to subscription Codex and isolated Claude/GLM CLI runs."""
import argparse
from contextlib import contextmanager, nullcontext
import getpass
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from harness import storage

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'harness' / 'agent-models.json'
KEY_FILE = ROOT / '.agent-keys.json'
REPORTS = ROOT / 'logs' / 'harness' / 'agents'
_DEFAULT_REPORTS = REPORTS
KEY_NAMES = ('ANTHROPIC_API_KEY', 'ZAI_API_KEY', 'TYPESAFE_API_KEY')


def load_config():
    return json.loads(CONFIG.read_text(encoding='utf-8'))


def load_keys(include_environment=True):
    keys = {}
    if KEY_FILE.exists():
        if KEY_FILE.is_symlink() or KEY_FILE.stat().st_mode & 0o077:
            raise ValueError('Local key file must be a regular private file (chmod 600).')
        keys = json.loads(KEY_FILE.read_text(encoding='utf-8'))
        if not isinstance(keys, dict) or set(keys) - set(KEY_NAMES):
            raise ValueError('Invalid local key file; only provider API keys are allowed.')
    if include_environment:
        for name in KEY_NAMES:
            if os.environ.get(name):
                keys[name] = os.environ[name]
    if any(not isinstance(value, str) or not value.strip() or any(char in value for char in '\n\r\0')
           for value in keys.values()):
        raise ValueError('API keys must be non-empty single-line strings.')
    return keys


def report_directory(explicit=None, *, category='agents', root=None, local_default=None):
    """Resolve at use time; report overrides never select authentication homes."""
    root = ROOT if root is None else root
    if local_default is None:
        local_default = REPORTS if REPORTS != _DEFAULT_REPORTS else root / 'logs/harness/agents'
    policy = storage.resolve_storage(root)
    return policy, policy.report_dir(category, explicit=explicit, local_default=local_default)


def credential_runtime_directory(category='agents', provider=None, *, root=None):
    """Create only local private provider state, without chmodding existing paths."""
    policy = storage.resolve_storage(ROOT if root is None else root)
    policy.check_ready()
    if category not in ('agents', 'compaction') or provider not in (None, 'claude', 'zai'):
        raise ValueError('Invalid local runtime category or provider.')
    path = (policy.credential_runtime_root if category == 'agents' else
            policy.root / 'logs/harness/compaction/runtime')
    runtime = path if provider is None else path / provider
    directories = [path] if provider is None else [path, runtime]
    directories.append(runtime / 'tmp')
    try:
        for directory in directories:
            policy.check_ready()
            policy.fs.create_directory(directory)
            fd = policy.fs.open_directory(directory)
            try:
                info = os.fstat(fd)
                if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
                    raise ValueError('Local credential runtime requires an owned private 0700 directory.')
            finally:
                os.close(fd)
    except OSError:
        raise ValueError('Cannot prepare private local credential runtime; check directory access.') from None
    return runtime


def private_json(path, data, *, policy=None):
    # Keys and durable callers retain their local/caller-selected destination.
    # Report writers supply the policy so readiness is rechecked before output.
    path = Path(path)
    if policy is not None:
        policy.ensure_directory(path.parent)
    else:
        storage.FileSystem().create_directory(path.parent.absolute())
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        if policy is not None:
            policy.check_ready()
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def configure(provider):
    name = load_config()['providers'][provider]['key_env']
    if not sys.stdin.isatty():
        raise ValueError('Run configure in an interactive terminal; never put a key in an argument.')
    value = getpass.getpass('{} (hidden): '.format(name)).strip()
    if not value or any(char in value for char in '\n\r\0'):
        raise ValueError('A non-empty single-line API key is required.')
    # Preserve previously saved keys, but do not copy unrelated process credentials.
    keys = load_keys(include_environment=False) if KEY_FILE.exists() else {}
    keys[name] = value
    private_json(KEY_FILE, keys)
    print('Saved {} in the ignored private key file.'.format(name))


def child_environment(provider, keys, compaction=False):
    env = dict(os.environ)
    for name in list(env):
        if name.startswith('ANTHROPIC_') or name.startswith('CLAUDE_CODE_') or name in (
                'OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'ZAI_API_KEY',
                'Z_AI_API_KEY', 'TYPESAFE_API_KEY', 'CLAUDE_CONFIG_DIR',
                storage.CONFIG_ENV, storage.REPORT_ENV,
                'GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN'):
            env.pop(name, None)
    if provider == 'codex':
        return env
    spec = load_config()['providers'][provider]
    key = keys.get(spec['key_env'])
    if not key:
        raise ValueError('Missing {}; run configure --provider {} in your terminal.'.format(
            spec['key_env'], provider))
    # Different local state directories prevent API and Coding Lite auth from mixing.
    runtime = credential_runtime_directory(provider=provider)
    env['CLAUDE_CONFIG_DIR'] = str(runtime)
    env['TMPDIR'] = env['TMP'] = env['TEMP'] = str(runtime / 'tmp')
    env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'
    env['ANTHROPIC_BASE_URL'] = spec['base_url']
    env['API_TIMEOUT_MS'] = '120000'
    if compaction and keys.get('TYPESAFE_API_KEY'):
        env['TYPESAFE_API_KEY'] = keys['TYPESAFE_API_KEY']
    if provider == 'claude':
        env['ANTHROPIC_API_KEY'] = key
    else:
        env['ANTHROPIC_AUTH_TOKEN'] = key
        for family in ('OPUS', 'SONNET', 'HAIKU'):
            env['ANTHROPIC_DEFAULT_' + family + '_MODEL'] = 'glm-5.3-flash'
    return env


def redact(text, keys):
    for key in sorted(keys.values(), key=len, reverse=True):
        text = text.replace(key, '[REDACTED]')
    return text


class CodexFailure(ValueError):
    """Only fixed, local diagnostics may leave the Codex runtime boundary."""
    REASONS = {
        'missing_cli': 'Codex CLI is not installed.',
        'runtime_unavailable': 'Cannot create or clean up the private Codex runtime.',
        'unsafe_workspace': 'The model workspace must not contain the original Codex authentication home.',
        'auth_file_unavailable': 'A regular readable auth.json is required; keyring auth is not copied.',
        'authentication_failed': 'Run codex login --device-auth; API-key billing is not used.',
        'path_aliases_read_only': 'Codex PATH aliases initialization failed on a read-only filesystem.',
        'timeout': 'Codex CLI timed out.',
        'cli_failed': 'Codex CLI failed; permissions and network were not expanded.',
        'invalid_response': 'Codex returned no valid completed response.',
        'probe_mismatch': 'Model response did not match the connection probe.',
    }

    def __init__(self, stage, category):
        self.diagnostic = {'stage': stage, 'category': category}
        super().__init__(self.REASONS[category])


def codex_paths(cli):
    """Resolve before replacing child temp/home paths, including standalone zsh."""
    executable = shutil.which(cli)
    if not executable:
        raise CodexFailure('runtime', 'missing_cli')
    executable = str(Path(executable).resolve())
    bundled_shell = Path(executable).parent.parent / 'codex-resources' / 'zsh' / 'bin' / 'zsh'
    shell = (str(bundled_shell.resolve()) if bundled_shell.is_file()
             and os.access(bundled_shell, os.X_OK) else
             shutil.which(os.environ.get('SHELL') or 'bash') or shutil.which('sh'))
    return executable, str(Path(shell).resolve()) if shell else None


def copy_codex_auth(home, source_home):
    """Copy only the login file, without following a final symlink or opening a FIFO."""
    try:
        fd = os.open(source_home / 'auth.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise CodexFailure('authentication', 'auth_file_unavailable')
            # Bound the copy; malformed credentials never appear in an exception/report.
            content = source.read(1024 * 1024 + 1)
        if not content or len(content) > 1024 * 1024:
            raise CodexFailure('authentication', 'auth_file_unavailable')
        fd = os.open(home / 'auth.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as target:
            os.fchmod(target.fileno(), 0o600)
            target.write(content)
    except OSError:
        raise CodexFailure('authentication', 'auth_file_unavailable') from None


@contextmanager
def codex_runtime(keys, cli, compaction=False):
    """CLI writes are private runtime writes, never model-tool permissions.

    Do not use the real login home as a fallback. No config, instructions, skills,
    other credentials or keyring entries are copied, and the parent env is untouched.
    TemporaryDirectory also cleans up on subprocess errors and timeouts.
    """
    try:
        policy = storage.resolve_storage(ROOT)
        policy.check_ready()
        executable, shell = codex_paths(cli)
        source_home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve()
        with tempfile.TemporaryDirectory(prefix='tavern-codex-runtime-',
                                         dir=str(policy.credential_temp_root)) as name:
            root = Path(name)
            root.chmod(0o700)
            env = child_environment('codex', keys, compaction=compaction)
            for variable, directory in (
                    ('CODEX_HOME', 'home'), ('TMPDIR', 'tmp'),
                    ('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'),
                    ('XDG_DATA_HOME', 'data'), ('XDG_STATE_HOME', 'state')):
                path = root / directory
                path.mkdir(mode=0o700)
                path.chmod(0o700)
                env[variable] = str(path)
            env['TMP'] = env['TEMP'] = env['TMPDIR']
            env.pop('CODEX_PERMISSION_PROFILE', None)
            if shell:
                env['SHELL'] = shell
            copy_codex_auth(Path(env['CODEX_HOME']), source_home)
            yield {'cli': executable, 'shell': shell, 'root': root, 'env': env,
                   'source_home': source_home}
    except OSError:
        raise CodexFailure('runtime', 'runtime_unavailable') from None


def codex_subprocess(command, env, stage, **options):
    try:
        return subprocess.run(command, env=env, capture_output=True, text=True, **options)
    except subprocess.TimeoutExpired:
        raise CodexFailure(stage, 'timeout') from None
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise CodexFailure(stage, 'cli_failed') from None


def codex_failure_category(output, stage):
    """Inspect locally; never return excerpts, paths, credentials or remote bodies."""
    output = output.lower()
    if 'path aliases' in output and any(marker in output for marker in (
            'read-only file system', 'read-only filesystem', 'os error 30')):
        return 'path_aliases_read_only'
    if any(marker in output for marker in ('unexpected argument', 'unrecognized', 'unknown variant')):
        return 'cli_failed'
    if stage == 'authentication' or any(marker in output for marker in (
            'unauthorized', 'authentication', 'not logged in', '401', 'token expired')):
        return 'authentication_failed'
    return 'cli_failed'


def codex_warnings(output, stage):
    """Fixed metadata only; warnings never establish authentication or completion."""
    if codex_failure_category(output, stage) == 'path_aliases_read_only':
        return [{'stage': stage, 'category': 'path_aliases_read_only'}]
    return []


def codex_login_status(runtime):
    command = [runtime['cli'], '--no-daemon', '-c', 'forced_login_method="chatgpt"',
               '-c', 'cli_auth_credentials_store="file"', 'login', 'status']
    auth = codex_subprocess(command, runtime['env'], 'authentication', timeout=20)
    output = auth.stdout + '\n' + auth.stderr
    if auth.returncode:
        raise CodexFailure('authentication', codex_failure_category(output, 'authentication'))
    lines = [line.strip().lower() for line in output.splitlines()]
    subscribed = 'logged in using chatgpt' in lines and not any(
        line.startswith('logged in using api key') for line in lines)
    if not subscribed:
        raise CodexFailure('authentication', 'authentication_failed')
    return {'status': 'ready', 'auth': 'chatgpt',
            'warnings': codex_warnings(auth.stderr, 'authentication')}


def connection_status(provider, keys):
    storage.resolve_storage(ROOT).check_ready()
    spec = load_config()['providers'][provider]
    if spec.get('transport') == 'http':
        ready = bool(keys.get(spec['key_env']))
        result = {'provider': provider, 'transport': 'http', 'endpoint': spec['endpoint'],
                  'key_env': spec['key_env'], 'status': 'ready' if ready else 'not_configured'}
        if not ready:
            result['reason'] = 'API key is not registered.'
        return result
    cli = shutil.which(spec['cli'])
    result = {'provider': provider, 'cli': cli, 'status': 'not_configured'}
    if provider == 'codex':
        result['warnings'] = []
    if not cli:
        result['reason'] = 'Missing CLI: ' + spec['cli']
        if provider == 'codex':
            result['diagnostic'] = {'stage': 'runtime', 'category': 'missing_cli'}
    elif provider != 'codex':
        result['key_env'] = spec['key_env']
        result['status'] = 'ready' if keys.get(spec['key_env']) else 'not_configured'
        if result['status'] != 'ready':
            result['reason'] = 'API key is not registered.'
    else:
        try:
            with codex_runtime(keys, spec['cli']) as runtime:
                result['cli'] = runtime['cli']
                result.update(codex_login_status(runtime))
        except CodexFailure as exc:
            result.update(status='not_configured', auth='requires_chatgpt_login',
                          reason=str(exc), diagnostic=exc.diagnostic)
    return result


def uses_compaction(provider, smoke=False, compaction=None):
    config = load_config().get('compaction', {})
    requested = config.get('enabled', False) and not smoke if compaction is None else compaction
    return bool(requested and provider in config.get('providers', []))


def scoped_codex_config(workspace, write=False, cli=None, shell=None, runtime_root=None,
                        auth_home=None):
    """Limit tool reads as well as writes; the legacy read-only sandbox is broader."""
    access = 'write' if write else 'read'
    entries = ['":root"="deny"', '":minimal"="read"',
               json.dumps(str(Path(workspace).resolve())) + '=' + json.dumps(access)]
    # :root already denies unrelated temp paths. Explicit :slash_tmp deny rules
    # also hide a context located under /tmp in current Linux CLI builds.
    # Standalone installations place the sandbox helper binary under ~/.codex,
    # outside :minimal. Allow that executable only, never the home/config tree.
    cli = cli or shutil.which('codex')
    if cli:
        entries.append(json.dumps(str(Path(cli).resolve())) + '="read"')
    if shell:
        entries.append(json.dumps(str(Path(shell).resolve())) + '="read"')
    if runtime_root is not None:
        # Even a workspace encompassing /tmp must not expose this auth/cache tree.
        entries.append(json.dumps(str(Path(runtime_root).resolve())) + '="deny"')
    if auth_home is not None:
        source_home = Path(auth_home).resolve()
        source_root = Path(workspace).resolve()
        if source_root == source_home or source_root in source_home.parents:
            raise CodexFailure('runtime', 'unsafe_workspace')
        # :root denies the original auth home already. A separate directory deny
        # masks standalone binary exceptions on Linux, blocking every tool.
        # Reject overlapping workspaces instead of granting credential access.
    filesystem = '{' + ','.join(entries) + '}'
    values = ['default_permissions="harness-scoped"',
              'permissions.harness-scoped.filesystem=' + filesystem,
              'permissions.harness-scoped.network.enabled=false',
              'project_doc_max_bytes=0', 'web_search="disabled"',
              'features.apps=false', 'features.browser_use=false',
              'features.computer_use=false', 'features.memories=false',
              'features.skill_search=false', 'features.skip_host_skill_discovery=true']
    return [item for value in values for item in ('-c', value)]


def _validated_budget_override(spec, max_budget_usd, smoke):
    """Accept only an explicit downward Claude CLI estimate cap, never a fallback.

    The automatic exploration parent owns durable reservations and settlement;
    this option does not impose a provider billing limit or change role defaults.
    """
    if max_budget_usd is None:
        return None
    if spec['provider'] != 'claude':
        raise ValueError('Budget override requires the Claude provider.')

    def positive_finite(value):
        if type(value) not in (int, float):
            return False
        try:
            return math.isfinite(value) and value > 0
        except OverflowError:
            return False

    configured = spec.get('max_budget_usd')
    if not positive_finite(configured):
        raise ValueError('Budget override requires a positive finite configured Claude limit.')
    if not positive_finite(max_budget_usd):
        raise ValueError('Budget override must be a positive finite number.')
    limit = min(configured, 0.25) if smoke else configured
    if max_budget_usd > limit:
        raise ValueError('Budget override must not increase the existing Claude limit.')
    return max_budget_usd


def command_for(role, write=False, smoke=False, compaction=None, workspace=None, scoped=False,
                codex_cli=None, codex_shell=None, runtime_root=None, auth_home=None, *,
                max_budget_usd=None):
    spec = load_config()['roles'][role]
    provider = spec['provider']
    budget_override = _validated_budget_override(spec, max_budget_usd, smoke)
    if write and role in ('reviewer', 'escalation', 'git'):
        raise ValueError('Reviewer, escalation and Git roles are read-only.')
    work_root = Path(workspace) if workspace is not None else ROOT
    if scoped and workspace is None:
        raise ValueError('Scoped model execution requires an explicit workspace.')
    if provider == 'codex':
        command = [codex_cli or 'codex', '--no-daemon', '--strict-config']
        # Workflow contexts intentionally contain approved files only, without Git
        # metadata or host trust records. The explicit permission profile still
        # enforces their read/write boundary independently of the Git guard.
        command += ['exec', '--skip-git-repo-check', '--ignore-user-config', '--ephemeral',
                '--json', '--color', 'never', '--model', spec['model'], '--cd', str(work_root),
                '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"',
                '-c', 'cli_auth_credentials_store="file"',
                '-c', 'approval_policy="never"', '-c', 'agents.enabled=false',
                '-c', 'features.plugins=false',
                '-c', 'model_reasoning_effort="{}"'.format(spec['effort'])]
        # Do not combine --sandbox with permission profiles: it overrides their
        # restricted read policy. Unknown profiles must fail, never silently broaden.
        # Smoke and direct runs must also keep the private auth runtime inaccessible.
        command += scoped_codex_config(work_root, write, cli=codex_cli,
                                       shell=codex_shell, runtime_root=runtime_root, auth_home=auth_home)
        return command + ['-']
    tools = '' if smoke else ('Read,Glob,Grep,Edit,Write' if write else 'Read,Glob,Grep')
    enabled = uses_compaction(provider, smoke, compaction)
    command = ['claude']
    if scoped:
        command += ['--restricted']  # File tools confined to cwd; no shell/code tools.
        command += ['--permission-prompts', 'none']
    if enabled:
        # Trusted CLI hook runtime stays outside approved model-readable sources.
        plugin_root = ROOT if scoped else work_root
        command += ['--plugin-dir', str(plugin_root / load_config()['compaction']['plugin_path'])]
    else:
        command += ['--bare' if provider == 'claude' else '--safe-mode']
    command += ['--setting-sources', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
               '--no-session-persistence', '--no-chrome', '--disable-slash-commands',
               '--print', '--output-format', 'json', '--model', spec['model'],
               '--tools', tools, '--allowedTools', tools,
               '--permission-mode', 'acceptEdits' if write else 'dontAsk']
    if provider == 'claude':
        command += ['--effort', spec['effort'], '--max-budget-usd',
                    str(budget_override if budget_override is not None else
                        (0.25 if smoke else spec['max_budget_usd']))]
    return command


def task_prompt(role, task, workspace=None, scoped=False):
    spec = load_config()['roles'][role]
    if scoped:
        return ('Role: {}. This is a scoped workflow leaf worker.\n'
                'Read only the approved files provided in this workspace. '
                'Do not read other paths, credentials, parent instructions or host settings. '
                'If context is missing, report which additional files are needed.\n'
                'Do not delegate or start harness.workflow or agent-run. '
                'The orchestrator owns validation; do not run checks, cron, downloads or importAll.\n'
                'Preserve existing user edits and report limitations.\n\nTask:\n{}').format(role, task)
    paths = list(dict.fromkeys(['AGENTS.md', spec['instructions']]))
    work_root = Path(workspace) if workspace is not None else ROOT
    instructions = '\n\n'.join((work_root / path).read_text(encoding='utf-8') for path in paths)
    return ('Role: {}. Required validation: make {}.\n'
            'Read docs/architecture.md and docs/harness.md before project work.\n'
            'Do not read credential files or print secrets. Do not delegate to other agents.\n'
            'TAVERN_WORKFLOW_CHILD=1: this is a leaf role; do not start harness.workflow or agent-run.\n'
            '{}'
            'Never run production cron, full downloads, or production importAll.\n'
            'Report changed files, validation performed, and remaining limitations.\n\n'
            '{}\n\nTask:\n{}').format(role, spec['check'],
                'The orchestrator owns validation.\n' if workspace is not None else '', instructions, task)


def response_text(provider, output):
    if provider != 'codex':
        data = json.loads(output)
        if data.get('is_error') or data.get('subtype', 'success') != 'success':
            raise ValueError('Model CLI reported an unsuccessful run.')
        if not isinstance(data.get('result'), str) or not data['result'].strip():
            raise ValueError('Model CLI returned no final response.')
        # Claude Code's estimated dollar cost is not Z.ai Coding Lite credit usage.
        return data['result'], data.get('total_cost_usd') if provider == 'claude' else None
    events = [json.loads(line) for line in output.splitlines() if line.strip()]
    if any(not isinstance(event, dict) for event in events):
        raise ValueError('Codex returned an invalid event.')
    if any(event.get('type') in ('turn.failed', 'error') for event in events):
        raise ValueError('Codex reported an unsuccessful turn.')
    messages = [event['item'].get('text') for event in events
                if event.get('type') == 'item.completed'
                and isinstance(event.get('item'), dict)
                and event['item'].get('type') == 'agent_message']
    if (not messages or not isinstance(messages[-1], str) or not messages[-1].strip()
            or not any(event.get('type') == 'turn.completed' for event in events)):
        raise ValueError('Codex returned no completed turn with a final response.')
    return messages[-1], None


def run(role, task, keys, write=False, smoke=False, timeout=300, compaction=None, workspace=None,
        scoped=False, *, max_budget_usd=None):
    """Run one role; invalid budget overrides raise before any runtime or model call.

    Exploration callers must persist their reservation before entry. Ordinary
    workflows omit the override and retain their configured per-call budgets.
    """
    spec = load_config()['roles'][role]
    provider = spec['provider']
    enabled = uses_compaction(provider, smoke, compaction)
    work_root = Path(workspace) if workspace is not None else ROOT
    command = command_for(role, write=write, smoke=smoke, compaction=compaction, workspace=workspace,
                          scoped=scoped, max_budget_usd=max_budget_usd)
    nonce = 'TAVERN_MODEL_OK_' + secrets.token_hex(8)
    prompt = ('Reply with exactly {}. Do not use any tools.'.format(nonce) if smoke
              else task_prompt(role, task, workspace=workspace, scoped=scoped))
    report = {'role': role, 'provider': provider, 'model': spec['model'],
              'kind': 'smoke' if smoke else 'task', 'status': 'failed'}
    if provider == 'codex':
        report['warnings'] = []
    report['compaction'] = {'requested': enabled, 'key_registered': bool(keys.get('TYPESAFE_API_KEY')),
                            'status': 'requested' if enabled else 'disabled'}
    try:
        storage.resolve_storage(ROOT).check_ready()
        if enabled:
            from harness.compaction import verify_vendor
            verify_vendor()
        context = codex_runtime(keys, load_config()['providers']['codex']['cli'], enabled) \
            if provider == 'codex' else nullcontext(None)
        with context as runtime:
            if runtime is not None:
                status = codex_login_status(runtime)
                report['warnings'].extend(status['warnings'])
                env = runtime['env']
                command = command_for(role, write=write, smoke=smoke, compaction=compaction,
                                      workspace=workspace, scoped=scoped, codex_cli=runtime['cli'],
                                      codex_shell=runtime['shell'], runtime_root=runtime['root'],
                                      auth_home=runtime['source_home'], max_budget_usd=max_budget_usd)
            else:
                status = connection_status(provider, keys)
                if status['status'] != 'ready':
                    raise ValueError(status['reason'])
                env = child_environment(provider, keys, compaction=enabled)
            env['TAVERN_WORKFLOW_CHILD'] = '1'
            if scoped:
                # Desktop session permissions and project memories must not replace or
                # extend the explicit context prepared by the workflow.
                env.pop('CODEX_PERMISSION_PROFILE', None)
                env['CLAUDE_CODE_DISABLE_CLAUDE_MDS'] = '1'
                env['CLAUDE_CODE_DISABLE_AUTO_MEMORY'] = '1'
            if runtime is not None:
                result = codex_subprocess(command, env, 'execution', input=prompt,
                                          cwd=str(work_root), timeout=timeout)
            else:
                result = subprocess.run(command, input=prompt, cwd=str(work_root), env=env,
                                        capture_output=True, text=True, timeout=timeout)
            report['exit_code'] = result.returncode
            if provider != 'codex':
                report['stderr'] = redact(result.stderr, keys)
            else:
                report['warnings'].extend(codex_warnings(result.stderr, 'execution'))
            if enabled and any(message in result.stderr.lower() for message in (
                    'hooks module not loaded', 'hooks module did not load', 'not loaded:', 'hook skipped')):
                report['compaction']['status'] = 'unavailable'
            if result.returncode:
                if provider == 'codex':
                    raise CodexFailure('execution', codex_failure_category(
                        result.stdout + '\n' + result.stderr, 'execution'))
                report['diagnostic'] = redact(result.stdout, keys)
                raise ValueError('Model CLI exited with code {}.'.format(result.returncode))
            try:
                response, cost = response_text(provider, result.stdout)
            except (ValueError, KeyError, TypeError):
                if provider == 'codex':
                    category = codex_failure_category(result.stdout + '\n' + result.stderr, 'execution')
                    if category in ('cli_failed', 'path_aliases_read_only'):
                        category = 'invalid_response'
                    raise CodexFailure('execution', category) from None
                raise
            if smoke and response.strip() != nonce:
                if provider == 'codex':
                    raise CodexFailure('execution', 'probe_mismatch')
                raise ValueError('Model response did not match the connection probe.')
            report['response'] = redact(response, keys)
            if cost is not None:
                report['cli_estimated_cost_usd'] = cost
            report['status'] = 'passed'
    except storage.StorageError as exc:
        report['status'] = 'failed'
        report.pop('response', None)
        report['diagnostic'] = {'stage': 'storage', 'category': 'storage_unavailable'}
        report['error'] = str(exc)
    except CodexFailure as exc:
        report['status'] = 'failed'
        report.pop('response', None)
        report['diagnostic'] = exc.diagnostic
        report['error'] = str(exc)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if provider == 'codex':
            report['status'] = 'failed'
            report.pop('response', None)
            report['diagnostic'] = {'stage': 'execution', 'category': 'cli_failed'}
            report['error'] = CodexFailure.REASONS['cli_failed']
        else:
            report['error'] = redact(str(exc), keys)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('doctor', 'configure', 'smoke', 'run'))
    parser.add_argument('--provider', choices=tuple(load_config()['providers']))
    parser.add_argument('--role', choices=tuple(load_config()['roles']))
    parser.add_argument('--task-file', type=Path)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--report-dir', type=Path)
    compaction = parser.add_mutually_exclusive_group()
    compaction.add_argument('--compaction', dest='compaction', action='store_true')
    compaction.add_argument('--no-compaction', dest='compaction', action='store_false')
    parser.set_defaults(compaction=None)
    args = parser.parse_args(argv)
    try:
        if args.command == 'configure':
            if args.provider not in ('claude', 'zai', 'typesafe'):
                parser.error('configure requires --provider claude, zai or typesafe')
            configure(args.provider)
            return 0
        if args.command == 'run' and not args.role:
            parser.error('run requires --role')
        if args.command == 'smoke' and not args.provider:
            parser.error('smoke requires --provider')
        if args.command == 'smoke' and args.provider == 'typesafe':
            parser.error('Use python -m harness.triage smoke for the TypeSafe decision API')
        if args.command != 'run' and (args.role or args.write or args.task_file):
            parser.error('--role, --write and --task-file are for run only')
        if args.compaction is not None and args.command not in ('run', 'smoke'):
            parser.error('--compaction and --no-compaction are for run or smoke')
        if args.command == 'run' and args.provider:
            parser.error('run selects its provider through --role')
        if args.timeout <= 0:
            parser.error('--timeout must be positive')
        role = args.role or {'codex': 'coordinator', 'claude': 'reviewer', 'zai': 'downloader'}.get(args.provider)
        if args.dry_run:
            if args.command not in ('run', 'smoke'):
                parser.error('--dry-run is for run or smoke')
            print(json.dumps({'role': role, 'command': command_for(role, args.write, args.command == 'smoke', args.compaction)},
                             ensure_ascii=False, indent=2))
            return 0
        policy, reports = report_directory(args.report_dir)
        policy.ensure_directory(reports)
        keys = load_keys()
        if args.command == 'doctor':
            providers = [args.provider] if args.provider else list(load_config()['providers'])
            checks = [connection_status(provider, keys) for provider in providers]
            report = {'status': 'passed' if all(check['status'] == 'ready' for check in checks)
                      else 'not_configured', 'checks': checks,
                      'note': 'Local configuration check only; no inference request was sent.'}
            path = reports / ('doctor-' + (args.provider or 'all') + '.json')
        else:
            task = args.task_file.read_text(encoding='utf-8') if args.task_file else ''
            if args.command == 'run' and not task.strip():
                parser.error('run requires a non-empty --task-file')
            report = run(role, task, keys, args.write, args.command == 'smoke', args.timeout, args.compaction)
            path = reports / '{}-{}-{}.json'.format(args.command, role, time.time_ns())
        private_json(path, report, policy=policy)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('Report: {}'.format(path))
        return 0 if report['status'] == 'passed' else 1
    except storage.StorageError as exc:
        print('Model storage unavailable: {}'.format(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Do not include credential values or untrusted key-file contents in errors.
        print('Model connection failed: {}'.format(type(exc).__name__), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
