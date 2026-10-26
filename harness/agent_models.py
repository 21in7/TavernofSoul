"""Connect project roles to subscription Codex and isolated Claude/GLM CLI runs."""
import argparse
from contextlib import contextmanager, nullcontext
import getpass
import json
import math
import os
from pathlib import Path
import secrets
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from harness import agent_telemetry, agent_usage, storage, improvement_diagnostics as diagnostics

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

    def __init__(self, stage, category, *, source=None, exit_code=None, errno=None):
        self.diagnostic = {'stage': stage, 'category': category}
        super().__init__(self.REASONS[category])
        if source is not None:
            diagnostics.inherit(self, source)
        diagnostics.attach(self, diagnostics.detail('role_execution_failed', category,
            phase=stage if stage in ('runtime', 'authentication', 'execution') else 'execution',
            exit_code=exit_code, errno=errno))


def _failure(message, cause, phase, **numbers):
    return diagnostics.attach(ValueError(message), diagnostics.detail(
        'role_execution_failed', cause, phase=phase, **numbers))


def _os_errno(exc):
    # Read the native OS observation, never a provider's property or attribute.
    return OSError.errno.__get__(exc) if isinstance(exc, OSError) else None


@contextmanager
def _preserve_failure(manager, observe=None):
    """Cleanup may fail, but must not replace the body's first exception."""
    first = None
    try:
        with manager as value:
            try:
                yield value
            except (Exception, KeyboardInterrupt) as exc:
                first = exc
                if observe is not None:
                    try:
                        observe(exc)
                    except (Exception, KeyboardInterrupt):
                        pass
                raise
    except (Exception, KeyboardInterrupt):
        if first is not None:
            raise first
        raise


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
    except OSError as exc:
        raise CodexFailure('authentication', 'auth_file_unavailable', errno=_os_errno(exc)) from None


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
        with _preserve_failure(tempfile.TemporaryDirectory(prefix='tavern-codex-runtime-',
                                         dir=str(policy.credential_temp_root))) as name:
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
    except OSError as exc:
        raise CodexFailure('runtime', 'runtime_unavailable', errno=_os_errno(exc)) from None


def codex_subprocess(command, env, stage, **options):
    try:
        return subprocess.run(command, env=env, capture_output=True, text=True, **options)
    except subprocess.TimeoutExpired:
        raise CodexFailure(stage, 'timeout') from None
    except OSError as exc:
        # Legacy diagnostic stays cli_failed; the observed boundary is spawn.
        return_error = _failure('Codex CLI could not start.', 'spawn_failed', stage,
                                errno=_os_errno(exc))
        raise CodexFailure(stage, 'cli_failed', source=return_error) from None
    except (UnicodeError, subprocess.SubprocessError):
        raise CodexFailure(stage, 'cli_failed') from None


def codex_failure_category(stderr, stage, *, exit_code=None, has_output=False):
    """Classify only a nonzero CLI exit with unambiguous stderr evidence.

    Never search model/tool stdout. Execution output makes stderr provenance
    ambiguous too: tools may echo errors there. Warnings and unfamiliar formats
    prove no cause. The login-status command has no model/tools.
    """
    if (type(exit_code) is not int or not 1 <= exit_code <= 255 or
            stage not in ('authentication', 'execution') or
            type(stderr) is not str or (stage != 'authentication' and has_output)):
        return 'cli_failed'
    # Accept one CLI error with only recognized advisory lines around it.
    # A narrative/source dump containing a matching line is not a CLI envelope.
    lines = [line.strip().lower() for line in stderr.splitlines() if line.strip()]
    errors = [line for line in lines if not codex_warnings(line, stage)]
    if len(errors) != 1:
        return 'cli_failed'
    line = errors[0]
    if line.startswith(('authentication failed:', 'error: authentication failed:',
                        'error: unexpected status 401 unauthorized')):
        return 'authentication_failed'
    if stage == 'authentication' and (line == 'not logged in' or
                                      line.startswith('not logged in:')):
        return 'authentication_failed'
    return 'cli_failed'


def codex_warnings(output, stage):
    """Fixed metadata only; warnings never establish authentication or completion."""
    # Advisory even when the CLI subsequently fails. Quoted source and JSON
    # envelopes, or words appearing on different lines, are not this warning.
    for line in output.splitlines():
        line = line.strip().lower()
        if line.startswith('path aliases:') and any(marker in line for marker in (
                'read-only file system', 'read-only filesystem', 'os error 30')):
            return [{'stage': stage, 'category': 'path_aliases_read_only'}]
    return []


def codex_login_status(runtime):
    command = [runtime['cli'], '--no-daemon', '-c', 'forced_login_method="chatgpt"',
               '-c', 'cli_auth_credentials_store="file"', 'login', 'status']
    auth = codex_subprocess(command, runtime['env'], 'authentication', timeout=20)
    output = auth.stdout + '\n' + auth.stderr
    if auth.returncode:
        category = codex_failure_category(auth.stderr, 'authentication', exit_code=auth.returncode)
        # This stdout is exclusively login status, never model/tool content.
        if any(line.strip().lower() == 'not logged in' for line in auth.stdout.splitlines()):
            category = 'authentication_failed'
        raise CodexFailure('authentication', category, exit_code=auth.returncode)
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
                max_budget_usd=None, discovery_schema=None):
    spec = load_config()['roles'][role]
    provider = spec['provider']
    native_schema = None
    if discovery_schema is not None:
        from harness import improvement_schema
        native_schema = improvement_schema.validate_request(discovery_schema, role, provider,
            workspace, write=write, smoke=smoke, scoped=scoped)
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
    if native_schema is not None:
        command += ['--effort', 'low', '--json-schema', native_schema]
    return command


def task_prompt(role, task, workspace=None, scoped=False):
    spec = load_config()['roles'][role]
    if scoped:
        return ('Role: {}. This is a scoped workflow leaf worker.\n'
                'Read only the approved files provided in this workspace. '
                'Do not read other paths, credentials, parent instructions or host settings. '
                'Start with relevant sections of needed approved files; read entire approved files when needed. '
                'Avoid repeated bulk output or rereading of supplied diffs and results; the full review scope remains. '
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


def response_text(provider, output, *, discovery_schema=None):
    if discovery_schema is not None:
        return _structured_response_text(provider, output, discovery_schema)
    def parse(value):
        try:
            return json.loads(value)
        except (ValueError, TypeError, RecursionError) as exc:
            diagnostics.attach(exc, diagnostics.detail('role_execution_failed',
                               'json_invalid', phase='json'))
            raise
    if provider != 'codex':
        data = parse(output)
        if not isinstance(data, dict):
            raise _failure('Model CLI returned an invalid envelope.', 'envelope_invalid', 'response')
        if data.get('is_error') or data.get('subtype', 'success') != 'success':
            raise _failure('Model CLI reported an unsuccessful run.', 'envelope_invalid', 'response')
        if not isinstance(data.get('result'), str) or not data['result'].strip():
            raise _failure('Model CLI returned no final response.', 'empty_response', 'response')
        # Claude Code's estimated dollar cost is not Z.ai Coding Lite credit usage.
        return data['result'], data.get('total_cost_usd') if provider == 'claude' else None
    events = [parse(line) for line in output.splitlines() if line.strip()]
    if any(not isinstance(event, dict) for event in events):
        raise _failure('Codex returned an invalid event.', 'envelope_invalid', 'response')
    if any(event.get('type') in ('turn.failed', 'error') for event in events):
        raise _failure('Codex reported an unsuccessful turn.', 'envelope_invalid', 'response')
    messages = [event['item'].get('text') for event in events
                if event.get('type') == 'item.completed'
                and isinstance(event.get('item'), dict)
                and event['item'].get('type') == 'agent_message']
    if (not messages or not isinstance(messages[-1], str) or not messages[-1].strip()
            or not any(event.get('type') == 'turn.completed' for event in events)):
        raise _failure('Codex returned no completed turn with a final response.', 'response_incomplete', 'response')
    return messages[-1], None


def _structured_response_text(provider, output, request):
    from harness import improvement_report as contract, improvement_schema
    limit = improvement_schema.response_limit(request)
    if provider != 'zai':
        raise _failure('discovery_schema_scope_invalid', 'envelope_invalid', 'response')
    try:
        # Bound the whole envelope as well as the canonical structured body.
        # Strict parsing sees duplicates/non-finite values before a dict exists.
        data = contract.parse_json(output, min(contract.MAX_RESPONSE_BYTES, limit + 8192))
    except ValueError as exc:
        diagnostics.attach(exc, diagnostics.detail('role_json_invalid', 'json_invalid', phase='json'))
        raise
    if (type(data) is not dict or data.get('type') != 'result' or
            data.get('subtype') != 'success' or data.get('is_error') is not False):
        raise _failure('Model CLI reported an unsuccessful structured run.', 'envelope_invalid', 'response')
    structured = data.get('structured_output')
    if (type(structured) is not dict or set(structured) != {'candidates'} or
            type(structured['candidates']) is not list):
        raise _failure('Model CLI returned no structured candidates.', 'envelope_invalid', 'response')
    body = contract.canonical_json(structured)
    if len(body) > limit:
        raise _failure('Structured response exceeds its bound.', 'response_too_large', 'response')
    # No result-string fallback. Final candidate validation occurs only after
    # the parent has checked role identity and unchanged read-only snapshots.
    return body.decode('utf-8'), None


def _review_subprocess(command, prompt, cwd, env, timeout):
    """Discovery-only bounded pipes, including stderr and wall time.

    No raw partial output escapes timeout, interrupt or size failure. Normal
    workflow/GLM keep their existing subprocess and telemetry paths.
    """
    from harness import review_coverage as coverage
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, cwd=cwd, env=env, start_new_session=True)
    output, errors = bytearray(), bytearray()
    body, offset = prompt.encode('utf-8'), 0
    deadline = time.monotonic() + timeout
    first = None
    try:
        with selectors.DefaultSelector() as selector:
            for pipe, event in ((process.stdin, selectors.EVENT_WRITE),
                                (process.stdout, selectors.EVENT_READ),
                                (process.stderr, selectors.EVENT_READ)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, event)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _failure('source_review_transport_failed', 'timeout', 'transport')
                for key, _ in selector.select(min(remaining, .25)):
                    pipe = key.fileobj
                    if pipe is process.stdin:
                        if offset < len(body):
                            offset += os.write(pipe.fileno(), body[offset:offset + 4096])
                        if offset == len(body):
                            selector.unregister(pipe)
                            pipe.close()
                    else:
                        chunk = os.read(pipe.fileno(), 4096)
                        if not chunk:
                            selector.unregister(pipe)
                            pipe.close()
                            continue
                        target = output if pipe is process.stdout else errors
                        target.extend(chunk)
                        if len(target) > (coverage.MAX_STDOUT if pipe is process.stdout else coverage.MAX_STDERR):
                            raise _failure('source_review_transport_failed', 'response_too_large', 'transport')
            process.wait(timeout=max(.001, deadline - time.monotonic()))
        return subprocess.CompletedProcess(command, process.returncode, output.decode('utf-8', 'strict'),
                                           errors.decode('utf-8', 'replace'))
    except (Exception, KeyboardInterrupt) as exc:
        first = exc
        if isinstance(exc, subprocess.TimeoutExpired):
            diagnostics.attach(exc, diagnostics.detail('role_execution_failed', 'timeout', phase='transport'))
        elif isinstance(exc, OSError):
            diagnostics.attach(exc, diagnostics.detail('role_execution_failed', 'transport_failed',
                                                       phase='transport', errno=_os_errno(exc)))
        elif isinstance(exc, UnicodeError):
            diagnostics.attach(exc, diagnostics.detail('role_execution_failed', 'invalid_response',
                                                       phase='response'))
        raise
    finally:
        try:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        finally:
            try:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    pipe.close()
            finally:
                if first is not None:
                    raise first


def run(role, task, keys, write=False, smoke=False, timeout=300, compaction=None, workspace=None,
        scoped=False, *, max_budget_usd=None, discovery_review=None, discovery_schema=None):
    """Run one role; invalid budget overrides raise before any runtime or model call.

    Exploration callers must persist their reservation before entry. Ordinary
    workflows omit the override and retain their configured per-call budgets.
    """
    spec = load_config()['roles'][role]
    provider = spec['provider']
    enabled = uses_compaction(provider, smoke, compaction)
    work_root = Path(workspace) if workspace is not None else ROOT
    command = command_for(role, write=write, smoke=smoke, compaction=compaction, workspace=workspace,
                          scoped=scoped, max_budget_usd=max_budget_usd,
                          discovery_schema=discovery_schema)
    if discovery_schema is not None and discovery_review is not None:
        raise ValueError('discovery_schema_scope_invalid')
    if discovery_review is not None:
        from harness import review_coverage as coverage
        if (type(discovery_review) is not coverage.Capture or role != 'reviewer' or
                provider != 'claude' or write or smoke or not scoped or workspace is None or
                str(Path(workspace).absolute()) != discovery_review.root):
            raise ValueError('source_review_transport_invalid')
        command[command.index('--output-format') + 1] = 'stream-json'
        command += ['--verbose']
        # Read is the sole tool in this private protocol. Compaction hooks,
        # identity, budget and environment handling retain the existing path.
        command[command.index('--tools') + 1] = 'Read'
        command[command.index('--allowedTools') + 1] = 'Read'
    nonce = 'TAVERN_MODEL_OK_' + secrets.token_hex(8)
    prompt = ('Reply with exactly {}. Do not use any tools.'.format(nonce) if smoke
              else task_prompt(role, task, workspace=workspace, scoped=scoped))
    report = {'role': role, 'provider': provider, 'model': spec['model'],
              'kind': 'smoke' if smoke else 'task', 'status': 'failed',
              'prompt_size': agent_usage.prompt_size(prompt), 'usage': agent_usage.unavailable()}
    if provider == 'codex':
        report['warnings'] = []
    report['compaction'] = {'requested': enabled, 'key_registered': bool(keys.get('TYPESAFE_API_KEY')),
                            'status': 'requested' if enabled else 'disabled'}
    collector = None
    telemetry_outcome = 'spawn_failed'
    telemetry_cli = {}
    try:
        storage.resolve_storage(ROOT).check_ready()
        if enabled:
            from harness.compaction import verify_vendor
            verify_vendor()
        context = codex_runtime(keys, load_config()['providers']['codex']['cli'], enabled) \
            if provider == 'codex' else nullcontext(None)
        with _preserve_failure(context) as runtime:
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
                    raise _failure(status['reason'],
                        'missing_cli' if status.get('cli') is None else 'authentication_failed',
                        'runtime' if status.get('cli') is None else 'authentication')
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
                if provider == 'zai':
                    env = agent_telemetry.child_environment(env)
                    try:
                        collector = agent_telemetry.Collector(timeout)
                        collector.start()
                        env = agent_telemetry.child_environment(env, collector.endpoint)
                        collector.launch_ns = time.time_ns()
                        collector.started = time.monotonic()
                    except Exception:
                        if collector is not None:
                            collector.finish('spawn_failed')
                        collector = None
                        report['telemetry'] = agent_telemetry.unavailable()
                if discovery_schema is not None:
                    # command_for already validated the native Zai capability.
                    # Apply after child/telemetry sanitation, only to this child.
                    # GLM thinking is forced; low effort does not disable it.
                    env.update({
                        'CLAUDE_CODE_ALWAYS_ENABLE_EFFORT': '1',
                        'CLAUDE_CODE_EFFORT_LEVEL': 'low',
                        'CLAUDE_CODE_MAX_OUTPUT_TOKENS': '8192',
                        # Installed CLI needs 1 for Read turns before its first
                        # structured attempt; invalid output gets no repair turn.
                        'MAX_STRUCTURED_OUTPUT_RETRIES': '1',
                        'CLAUDE_CODE_MAX_RETRIES': '0',
                    })
                execution_error = None
                try:
                    if discovery_review is not None:
                        result = _review_subprocess(command, prompt, str(work_root), env, timeout)
                    else:
                        result = subprocess.run(command, input=prompt, cwd=str(work_root), env=env,
                                                capture_output=True, text=True, timeout=timeout)
                    if collector is not None:
                        collector.wall_ms = (time.monotonic() - collector.started) * 1000
                    telemetry_outcome = 'child_failed' if result.returncode else 'success'
                    if collector is not None and len(result.stdout) <= 2097152:
                        try:
                            final = json.loads(result.stdout)
                            if isinstance(final, dict):
                                telemetry_cli = {k: final.get(k) for k in
                                                 ('duration_ms', 'duration_api_ms', 'num_turns')}
                                usage = final.get('usage')
                                if isinstance(usage, dict):
                                    telemetry_cli.update({
                                        'input_tokens': usage.get('input_tokens'),
                                        'output_tokens': usage.get('output_tokens'),
                                        'cache_read_tokens': usage.get('cache_read_input_tokens'),
                                        'cache_creation_tokens': usage.get('cache_creation_input_tokens'),
                                    })
                        except (ValueError, TypeError, RecursionError):
                            pass
                except subprocess.TimeoutExpired as exc:
                    execution_error = exc
                    telemetry_outcome = 'timeout'
                    diagnostics.attach(exc, diagnostics.detail('role_execution_failed', 'timeout',
                                                               phase='execution'))
                    raise
                except OSError as exc:
                    execution_error = exc
                    diagnostics.attach(exc, diagnostics.detail('role_execution_failed', 'spawn_failed',
                        phase='execution', errno=_os_errno(exc)))
                    raise
                except KeyboardInterrupt as exc:
                    execution_error = exc
                    telemetry_outcome = 'interrupted'
                    diagnostics.attach(exc, diagnostics.detail('role_interrupted', 'interrupted',
                                                               phase='execution'))
                    raise
                except Exception as exc:
                    execution_error = exc
                    raise
                finally:
                    try:
                        if collector is not None:
                            if collector.wall_ms is None:
                                collector.wall_ms = (time.monotonic() - collector.started) * 1000
                            report['telemetry'] = collector.finish(telemetry_outcome, telemetry_cli)
                        elif provider == 'zai':
                            report['telemetry'] = agent_telemetry.unavailable(telemetry_outcome)
                    finally:
                        if execution_error is not None:
                            raise execution_error
            report['exit_code'] = result.returncode
            if not result.returncode:
                try:
                    report['usage'] = agent_usage.observe(
                        provider, result.stdout, stream=discovery_review is not None)
                except Exception:
                    pass  # Optional measurement must not change execution/cost/diagnostics.
            if provider != 'codex':
                report['stderr'] = '' if discovery_review is not None else redact(result.stderr, keys)
            else:
                report['warnings'].extend(codex_warnings(result.stderr, 'execution'))
            if enabled and any(message in result.stderr.lower() for message in (
                    'hooks module not loaded', 'hooks module did not load', 'not loaded:', 'hook skipped')):
                report['compaction']['status'] = 'unavailable'
            if result.returncode:
                if provider == 'codex':
                    raise CodexFailure('execution', codex_failure_category(
                        result.stderr, 'execution', exit_code=result.returncode,
                        has_output=bool(result.stdout.strip())), exit_code=result.returncode)
                if discovery_review is None:
                    report['diagnostic'] = redact(result.stdout, keys)
                raise _failure('Model CLI exited with code {}.'.format(result.returncode),
                               'cli_failed', 'execution', exit_code=result.returncode)
            try:
                response_output = result.stdout
                if discovery_review is not None:
                    # Retain actual final CLI cost even if receipt validation
                    # fails afterwards; never refund a failed discovery call.
                    stream_lines = result.stdout.splitlines()
                    final = None
                    for line in reversed(stream_lines):
                        event = coverage.event_json(line)
                        if isinstance(event, dict) and event.get('type') == 'rate_limit_event':
                            # Locate cost only in the actual result. Capture
                            # still rejects malformed/oversize advisories and
                            # invalid ordering before this call can succeed.
                            continue
                        final = event
                        break
                    if not isinstance(final, dict) or final.get('type') != 'result':
                        raise _failure('source_review_transport_failed', 'envelope_invalid', 'response')
                    response_output = json.dumps(final)
                    if 'total_cost_usd' in final:
                        report['cli_estimated_cost_usd'] = final['total_cost_usd']
                response, cost = response_text(provider, response_output,
                                               discovery_schema=discovery_schema)
                if discovery_review is not None:
                    try:
                        discovery_review.accept(result.stdout)
                    except (ValueError, KeyError, TypeError) as exc:
                        diagnostics.attach(exc, diagnostics.detail('source_review_unverified',
                            'source_review_unverified', phase='review'))
                        raise
            except (ValueError, KeyError, TypeError) as exc:
                if provider == 'codex':
                    # exit0 is a response-validation failure, not evidence that
                    # words in model/tool output describe an authentication error.
                    raise CodexFailure('execution', 'invalid_response', source=exc) from None
                diagnostics.attach(exc, diagnostics.detail('role_execution_failed',
                                   'envelope_invalid', phase='response'))
                raise
            if smoke and response.strip() != nonce:
                if provider == 'codex':
                    raise CodexFailure('execution', 'probe_mismatch')
                raise _failure('Model response did not match the connection probe.', 'probe_mismatch', 'response')
            report['response'] = redact(response, keys)
            if cost is not None:
                report['cli_estimated_cost_usd'] = cost
            report['status'] = 'passed'
    except storage.StorageError as exc:
        report = diagnostics.attach_result(report, source=exc)
        report['status'] = 'failed'
        report.pop('response', None)
        report['diagnostic'] = {'stage': 'storage', 'category': 'storage_unavailable'}
        report['error'] = str(exc)
    except CodexFailure as exc:
        report = diagnostics.attach_result(report, source=exc)
        report['status'] = 'failed'
        report.pop('response', None)
        report['diagnostic'] = exc.diagnostic
        report['error'] = str(exc)
    except KeyboardInterrupt as exc:
        diagnostics.attach(exc, diagnostics.detail('role_interrupted', 'interrupted', phase='execution'))
        if provider != 'zai':
            raise
        report = diagnostics.attach_result(report, source=exc)
        telemetry_outcome = 'interrupted'
        report['error'] = 'Model CLI interrupted.'
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        diagnostics.attach(exc, diagnostics.detail('role_execution_failed', 'unavailable', phase='execution'))
        report = diagnostics.attach_result(report, source=exc)
        if provider == 'codex':
            report['status'] = 'failed'
            report.pop('response', None)
            report['diagnostic'] = {'stage': 'execution', 'category': 'cli_failed'}
            report['error'] = CodexFailure.REASONS['cli_failed']
        else:
            report['error'] = ('source_review_transport_failed' if discovery_review is not None
                               else redact(str(exc), keys))
    finally:
        # Also owns interruption during collector setup or environment assembly,
        # before the inner subprocess finally has been entered.
        if collector is not None and 'telemetry' not in report:
            try:
                report['telemetry'] = collector.finish(telemetry_outcome, telemetry_cli)
            except (Exception, KeyboardInterrupt):
                if report['status'] == 'passed':
                    raise
                report['telemetry'] = agent_telemetry.unavailable(telemetry_outcome)
    if report.get('telemetry') and report['status'] != 'passed':
        if report['telemetry']['outcome'] == 'success':
            report['telemetry']['outcome'] = 'invalid_response'
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
