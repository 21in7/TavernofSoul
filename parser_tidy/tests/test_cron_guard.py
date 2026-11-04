# -*- coding: utf-8 -*-
"""cron 안전장치(안전장치 3) 검증 테스트.

세 지역은 추적 예제와 공통 runner를 복사한 격리 repo에서 실제 Bash/flock으로
검증한다. ktest/twtos는 기존 본문 기반 검증을 유지한다. 운영 cron은 읽지 않는다.
"""
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import textwrap

import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
REPO_ROOT = os.path.dirname(PARENT)

REGIONS = ('itos', 'jtos', 'ktos')
LEGACY_CRON_FILES = [
    'cron_ktest.sh.example',
    'cron_twtos.sh.example',
]


def _read_cron(name):
    path = os.path.join(REPO_ROOT, name)
    # Missing tracked examples must fail, even when a local operational cron exists.
    with open(path, encoding='utf-8') as f:
        return f.read()


@pytest.mark.parametrize('name', LEGACY_CRON_FILES)
def test_cron_preserves_region_flow(name):
    """Check regional commands and ordering without executing the example."""
    src = _read_cron(name)
    region = name[len('cron_'):-len('.sh.example')]
    lines = [line.strip() for line in src.splitlines()]
    map_command = 'python map_image.py %s' % region
    if region in ('itos', 'jtos', 'ktos'):
        map_command = 'python2.7 map_image.py %s' % region
    import_command = 'python manage_%s.py importAll' % region
    if region in ('ktest', 'twtos'):
        import_command += ' >> ../err.txt'
    commands = [
        'python downloader.py %s' % region,
        'download_result=$?',
        map_command,
        'python main.py %s' % region,
        'parse_result=$?',
        import_command,
        'import_result=$?',
    ]
    positions = [lines.index(command) for command in commands]
    assert positions == sorted(positions), '%s: regional pipeline is out of order' % name
    download_guard = lines.index(
        'if [ "$download_result" -ne 0 ] && [ "$download_result" -ne 1 ]; then'
    )
    download_guard_end = lines.index('fi', download_guard)
    assert positions[1] < download_guard < download_guard_end < positions[2], (
        '%s: download failure guard must precede map parsing' % name
    )
    assert 'exit "$download_result"' in lines[download_guard:download_guard_end], (
        '%s: download failure must stop the pipeline' % name
    )
    import_guard = lines.index('if [ "$import_result" -ne 0 ]; then')
    import_guard_end = lines.index('fi', import_guard)
    assert positions[-1] < import_guard < import_guard_end, (
        '%s: import failure guard must follow return code capture' % name
    )
    if region in ('ktest', 'twtos'):
        assert lines.index('python closer.py %s' % region) > import_guard_end, (
            '%s: closer must follow the import failure guard' % name
        )


@pytest.mark.parametrize('name', LEGACY_CRON_FILES)
def test_cron_checks_parser_return_code(name):
    """각 cron 이 parser 반환 코드를 검사하는지 확인."""
    src = _read_cron(name)
    # parser 실행 후 반환 코드 캡처.
    assert 'parse_result=$?' in src, (
        '%s must capture parser return code (parse_result=$?)' % name
    )
    # 실패 시 중단 분기.
    assert 'if [ $parse_result -ne 0 ]' in src, (
        '%s must abort on parser failure' % name
    )
    # import 는 parser 성공 분기 뒤에 있어야 한다.
    pos_parse = src.find('parse_result=$?')
    pos_abort = src.find('if [ $parse_result -ne 0 ]')
    pos_import = src.find('importAll')
    assert pos_parse != -1 and pos_abort != -1 and pos_import != -1
    assert pos_parse < pos_abort < pos_import, (
        '%s: import must come after parser failure guard' % name
    )
    guard_end = src.index('\nfi', pos_abort) + 1
    assert guard_end < pos_import
    assert '\n    exit 1\n' in src[pos_abort:guard_end], (
        '%s: parser failure guard must exit before import' % name
    )


@pytest.mark.parametrize('name', LEGACY_CRON_FILES)
@pytest.mark.parametrize('return_code', [0, 7])
def test_import_failure_stops_before_success_message(name, return_code):
    """Execute the actual post-import shell block without running cron or webhooks."""
    import subprocess

    src = _read_cron(name)
    start = src.index('import_result=$?')
    end = src.index('\nfi', start) + len('\nfi')
    block = src[start:end]
    result = subprocess.run(
        ['bash', '-c', '(exit %d)\n%s\nprintf reached_success' % (return_code, block)],
        capture_output=True, text=True,
    )
    assert result.returncode == return_code
    assert ('reached_success' in result.stdout) == (return_code == 0)


# These executables only record arguments/cwd and simulate a stage result. No
# downloader/parser/import module, game data, network, or real activation is used.
FAKE_TOOL = r'''
import json
import os
from pathlib import Path
import sys

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ['FIXTURE_ROOT'])
if tool == 'curl':
    record = {'tool': tool, 'args': args, 'cwd': os.getcwd()}
else:
    commands = {'downloader.py': 'downloader', 'map_image.py': 'map',
                'main.py': 'parser', '-c': 'parser_logging'}
    stage = commands.get(args[0], 'import')
    if stage == 'import':
        region = args[0][len('manage_'):-len('.py')]
    elif stage == 'parser_logging':
        region = os.environ['FIXTURE_REGION']
    else:
        region = args[1]
    record = {'tool': tool, 'stage': stage, 'region': region, 'args': args,
              'cwd': os.getcwd(), 'venv': os.environ.get('FAKE_VENV_COUNT')}
fd = os.open(os.environ['TRACE'], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
try:
    os.write(fd, (json.dumps(record) + '\n').encode())
finally:
    os.close(fd)

if tool == 'curl':
    # A failed transport could mention the URL; the runner must suppress both
    # streams rather than accidentally leaking even this synthetic credential.
    print(args[-1])
    print(args[-1], file=sys.stderr)
    sys.exit(int(os.environ.get('CURL_EXIT', '0')))

print('fixture stdout ' + stage, flush=True)
print('fixture stderr ' + stage, file=sys.stderr, flush=True)
if os.environ.get('LARGE_OUTPUT'):
    print('DO_NOT_FORWARD_FULL_LOG:' + 'x' * 12000, flush=True)

revision = os.environ.get('REVISION_AFTER_' + stage.upper())
if revision is not None:
    path = root / 'downloader' / 'revision.csv'
    if revision == 'missing':
        path.unlink()
    else:
        rows = path.read_text().splitlines()
        rows = [row for row in rows if not row.startswith(region + ',')]
        rows.append(region + ',' + revision)
        path.write_bytes(('\r\n'.join(rows) + '\r\n').encode())

if (os.environ.get('BLOCK_STAGE') == stage and
        os.environ.get('BLOCK_REGION', region) == region):
    with open(os.environ['READY_FIFO'], 'wb', buffering=0) as ready:
        ready.write(b'R')
    with open(os.environ['RELEASE_FIFO'], 'rb', buffering=0) as release:
        if release.read(1) != b'G':
            sys.exit(91)

if os.environ.get('REMOVE_IMPORT_CWD') and stage == 'parser':
    (root / 'TavernofSoul').rename(root / 'TavernofSoul.hidden')
sys.exit(int(os.environ.get(stage.upper() + '_EXIT', '0')))
'''

FAKE_ACTIVATE = r'''
export FAKE_VENV_COUNT=$((${FAKE_VENV_COUNT:-0} + 1))
printf 'fixture activate stdout %s\n' "$FAKE_VENV_COUNT"
printf 'fixture activate stderr %s\n' "$FAKE_VENV_COUNT" >&2
if [ "$FAKE_VENV_COUNT" -eq 1 ]; then
    return "${ACTIVATE_EXIT:-0}"
fi
return "${REACTIVATE_EXIT:-0}"
'''


class IsolatedCron:
    """Copy only approved entry points; invoke every stage through fake tools."""

    def __init__(self, tmp_path, name='isolated repo'):
        self.base = tmp_path
        self.root = tmp_path / name
        self.bin = tmp_path / 'bin'
        self.trace = tmp_path / 'trace.jsonl'
        self.processes = []
        self.fds = []
        self.bash = shutil.which('bash')
        self.flock = shutil.which('flock')
        assert self.bash, 'actual Bash is required (never skip)'
        assert self.flock, 'actual flock is required (never skip)'
        self.bin.mkdir()
        for region in REGIONS:
            self.root.mkdir(exist_ok=True)
            # copyfile raises for missing tracked files, including the runner.
            shutil.copyfile(
                Path(REPO_ROOT) / ('cron_%s.sh.example' % region),
                self.root / ('cron_%s.sh.example' % region),
            )
        (self.root / 'scripts').mkdir()
        shutil.copyfile(Path(REPO_ROOT) / 'scripts/run_region_cron.sh',
                        self.root / 'scripts/run_region_cron.sh')
        for directory in ('downloader', 'parser_tidy',
                          'TavernofSoul/itos/3.8/bin'):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.activate = self.root / 'TavernofSoul/itos/3.8/bin/activate'
        self.activate.write_text(textwrap.dedent(FAKE_ACTIVATE), encoding='utf-8')
        self.revision = self.root / 'downloader/revision.csv'
        self.initial_revision = b'itos,409351\r\njtos,509352\r\nktos,609353\r\n'
        self.revision.write_bytes(self.initial_revision)
        for tool in ('python', 'python2.7', 'curl'):
            self.write_tool(tool, FAKE_TOOL)
        self.env = {
            'PATH': str(self.bin) + os.pathsep + os.defpath,
            'HOME': str(tmp_path), 'LC_ALL': 'C',
            'FIXTURE_ROOT': str(self.root), 'TRACE': str(self.trace),
            'TAVERN_DISCORD_WEBHOOK_URL':
                'https://discord.invalid/api/webhooks/fixture/SECRET_FIXTURE_TOKEN',
        }

    def write_tool(self, name, body):
        path = self.bin / name
        path.write_text('#!%s\n%s\n' % (sys.executable, textwrap.dedent(body)),
                        encoding='utf-8')
        path.chmod(0o700)

    @property
    def stored_root(self):
        # A setup_cwd failure moves the fixture after opening its log and lock.
        return self.root if self.root.exists() else Path(str(self.root) + '.moved')

    def start(self, region='itos', direct=False, **changes):
        env = dict(self.env, FIXTURE_REGION=region)
        for key, value in changes.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = str(value)
        if direct:
            args = [self.bash, str(self.root / 'scripts/run_region_cron.sh'), region]
        else:
            args = [self.bash, str(self.root / ('cron_%s.sh.example' % region))]
        # Use an unrelated cwd and a fresh process group for reliable cleanup,
        # including stage children still holding the runner's inherited lock FD.
        proc = subprocess.Popen(args, cwd=str(self.base), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        self.processes.append(proc)
        return proc

    def complete(self, proc):
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail('isolated cron exceeded bounded completion time')
        return subprocess.CompletedProcess(proc.args, proc.returncode,
                                           stdout.decode(), stderr.decode())

    def run(self, region='itos', **changes):
        return self.complete(self.start(region, **changes))

    def records(self, tool=None):
        rows = [json.loads(line) for line in self.trace.read_text().splitlines()] \
            if self.trace.exists() else []
        return rows if tool is None else [row for row in rows if row['tool'] == tool]

    def stages(self):
        return [row for row in self.records() if 'stage' in row]

    def logs(self):
        return sorted((self.stored_root / 'logs').glob('cron-*.log'))

    def log(self):
        assert len(self.logs()) == 1
        return self.logs()[0].read_text(encoding='utf-8')

    def messages(self):
        return [json.loads(row['args'][row['args'].index('--data-binary') + 1])
                ['content'] for row in self.records('curl')]

    def block(self):
        for name in ('ready', 'release'):
            path = self.base / (name + '.fifo')
            os.mkfifo(str(path), 0o600)
            fd = os.open(str(path), os.O_RDWR | os.O_NONBLOCK)
            self.fds.append(fd)
            self.env[name.upper() + '_FIFO'] = str(path)
        return self.fds[-2:]

    def wait_ready(self, proc, ready_fd):
        readable, _, _ = select.select([ready_fd], [], [], 5)
        assert readable, 'stage did not signal readiness within five seconds'
        assert os.read(ready_fd, 1) == b'R'
        assert proc.poll() is None, 'holder exited before contention was tested'

    def close(self):
        for proc in self.processes:
            # Kill a process group even if its leader has exited: descendants
            # must not survive an assertion/timeout and retain the shared lock.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate(timeout=5)
        for fd in self.fds:
            os.close(fd)


@pytest.fixture
def cron_factory(tmp_path):
    fixtures = []

    def make(name='isolated repo'):
        parent = tmp_path / str(len(fixtures))
        parent.mkdir()
        cron = IsolatedCron(parent, name)
        fixtures.append(cron)
        return cron

    yield make
    for cron in reversed(fixtures):
        cron.close()


def assert_end(log, status, stage, code, revision=None):
    lines = [line for line in log.splitlines() if 'event=run_end ' in line]
    assert len(lines) == 1
    line = lines[0]
    assert ' status=%s ' % status in line
    assert ' stage=%s ' % stage in line
    assert ' code=%s ' % code in line
    assert 'elapsed_seconds=' in line
    if revision is not None:
        assert ' revision=%s ' % revision in line


def assert_final_notification(cron, status, stage, code, pipeline_code,
                              revision, region='itos', map_code=0):
    assert len(cron.records('curl')) == len(cron.messages()) == 1
    # Every fake pipeline command must precede the sole final delivery attempt.
    assert cron.records()[:-1] == cron.stages()
    assert cron.records()[-1]['tool'] == 'curl'
    log = cron.log()
    for event in ('pipeline_end', 'notification_summary', 'run_end'):
        assert log.count('event=' + event + ' ') == 1
    assert (log.index('event=pipeline_end ') <
            log.index('event=notification_summary ') <
            log.index('event=notification status=') < log.index('event=run_end '))
    message = cron.messages()[0]
    for field in ('region=' + region, 'revision=' + revision, 'status=' + status,
                  'stage=' + stage, 'code=%s' % code,
                  'pipeline_exit=%s' % pipeline_code, 'map_exit=%s' % map_code,
                  'notification_problem=none'):
        assert field in message.splitlines()
    assert 'log=' + str(cron.logs()[0]) in message
    assert_curl_contract(cron)


def assert_no_notification(cron, log):
    assert cron.records('curl') == []
    assert cron.messages() == []
    assert 'event=notification_summary ' not in log
    assert 'event=notification ' not in log
    assert '_notification_unconfigured' not in log
    assert '_notification_failed' not in log


@pytest.mark.parametrize('region', REGIONS)
def test_shared_runner_region_order_cwd_arguments_and_logs(cron_factory, region):
    cron = cron_factory()
    result = cron.run(region)
    assert result.returncode == 0
    expected = [
        ('python', 'downloader', ['downloader.py', region], 'downloader', '1'),
        ('python2.7', 'map', ['map_image.py', region], 'parser_tidy', '1'),
        ('python', 'parser_logging',
         ['-c', 'import logging; logging.basicConfig(level=logging.INFO)'],
         'parser_tidy', '2'),
        ('python', 'parser', ['main.py', region], 'parser_tidy', '2'),
        ('python', 'import', ['manage_%s.py' % region, 'importAll'],
         'TavernofSoul', '2'),
    ]
    actual = [(row['tool'], row['stage'], row['args'],
               str(Path(row['cwd']).relative_to(cron.root)), row['venv'])
              for row in cron.stages()]
    assert actual == expected
    log = cron.log()
    assert_end(log, 'completed', 'import', 0)
    assert 'event=run_start region=%s ' % region in log
    for _, stage, _, _, _ in expected:
        assert 'event=stage_start stage=%s' % stage in log
        assert 'event=stage_end stage=%s code=0 elapsed_seconds=' % stage in log
        assert 'fixture stdout ' + stage in log
        assert 'fixture stderr ' + stage in log
    for line in log.splitlines():
        if 'event=' in line:
            assert len(line.split()[0]) >= 24  # ISO date, time and numeric offset
    revision = dict(itos='409351', jtos='509352', ktos='609353')[region]
    assert_final_notification(cron, 'completed', 'import', 0, 0, revision, region)
    assert cron.revision.read_bytes() == cron.initial_revision
    assert (cron.root / 'logs/cron-tos.lock').is_file()
    assert 'SECRET_FIXTURE_TOKEN' not in log + result.stdout + result.stderr


@pytest.mark.parametrize('region', REGIONS)
@pytest.mark.parametrize('code', [1, 2, 7])
def test_shared_runner_downloader_exit_contract(cron_factory, region, code):
    cron = cron_factory()
    result = cron.run(region, DOWNLOADER_EXIT=code,
                      REVISION_AFTER_DOWNLOADER='700007')
    assert result.returncode == (0 if code == 1 else code)
    assert [row['stage'] for row in cron.stages()] == ['downloader']
    status = 'no_changes' if code == 1 else 'failed'
    assert_end(cron.log(), status, 'downloader', code, '700007')
    assert 'event=stage_end stage=downloader code=%s elapsed_seconds=' % code in cron.log()
    if code == 1:
        assert_no_notification(cron, cron.log())
    else:
        assert_final_notification(cron, status, 'downloader', code, code,
                                  '700007', region)
    assert 'event=pipeline_end region=%s revision=700007 status=%s ' % (
        region, status) in cron.log()
    assert 'pipeline_exit=%s map_exit=0 log=%s' % (
        result.returncode, cron.logs()[0]) in cron.log()
    assert 'status=completed' not in cron.log()


@pytest.mark.parametrize('region', REGIONS)
@pytest.mark.parametrize('delivery', ['unset', 'http', 'timeout'])
def test_shared_runner_no_changes_never_attempts_notification(cron_factory,
                                                             region, delivery):
    cron = cron_factory()
    settings = dict(DOWNLOADER_EXIT=1, REVISION_AFTER_DOWNLOADER='700007',
                    CURL_EXIT=28 if delivery == 'timeout' else 22)
    if delivery == 'unset':
        settings['TAVERN_DISCORD_WEBHOOK_URL'] = None
    result = cron.run(region, **settings)
    assert result.returncode == 0
    assert [row['stage'] for row in cron.stages()] == ['downloader']
    log = cron.log()
    assert_end(log, 'no_changes', 'downloader', 1, '700007')
    assert_no_notification(cron, log)
    assert 'event=stage_end stage=downloader code=1 elapsed_seconds=' in log
    assert 'event=pipeline_end region=%s revision=700007 status=no_changes ' % region in log
    assert 'pipeline_exit=0 map_exit=0 log=' + str(cron.logs()[0]) in log
    assert 'SECRET_FIXTURE_TOKEN' not in log + result.stdout + result.stderr


@pytest.mark.parametrize('region', REGIONS)
@pytest.mark.parametrize('failed_stage,code,expected', [
    ('parser', 19, ['downloader', 'map', 'parser_logging', 'parser']),
    ('import', 23, ['downloader', 'map', 'parser_logging', 'parser', 'import']),
])
def test_shared_runner_original_failure_blocks_success(
        cron_factory, region, failed_stage, code, expected):
    cron = cron_factory()
    result = cron.run(region, **{failed_stage.upper() + '_EXIT': code,
                                'REVISION_AFTER_' + failed_stage.upper(): '800008'})
    assert result.returncode == code
    assert [row['stage'] for row in cron.stages()] == expected
    assert_end(cron.log(), 'failed', failed_stage, code, '800008')
    assert 'event=stage_end stage=%s code=%s elapsed_seconds=' % (
        failed_stage, code) in cron.log()
    assert 'status=completed' not in cron.log()
    assert_final_notification(cron, 'failed', failed_stage, code, code,
                              '800008', region)


@pytest.mark.parametrize('region', REGIONS)
@pytest.mark.parametrize('failed_stage,code', [(None, 0), ('parser', 17), ('import', 29)])
def test_shared_runner_map_warning_continues_and_observes_revision(
        cron_factory, region, failed_stage, code):
    cron = cron_factory()
    settings = dict(MAP_EXIT=11, REVISION_AFTER_DOWNLOADER='710001',
                    REVISION_AFTER_MAP='710002', REVISION_AFTER_PARSER='710003',
                    REVISION_AFTER_IMPORT='710004')
    if failed_stage:
        settings[failed_stage.upper() + '_EXIT'] = code
    ready, release = cron.block()
    proc = cron.start(region, BLOCK_STAGE='parser', **settings)
    cron.wait_ready(proc, ready)
    # Map has already failed and the parser is running, but no notification is
    # due until EXIT knows the outcome of the remaining pipeline.
    assert [row['stage'] for row in cron.stages()] == [
        'downloader', 'map', 'parser_logging', 'parser']
    assert 'event=map_warning code=11 action=continue_parser_and_import' in cron.log()
    assert 'event=pipeline_end ' not in cron.log()
    assert_no_notification(cron, cron.log())
    os.write(release, b'G')
    result = cron.complete(proc)
    assert result.returncode == code
    expected = ['downloader', 'map', 'parser_logging', 'parser']
    if failed_stage != 'parser':
        expected.append('import')
    assert [row['stage'] for row in cron.stages()] == expected
    log = cron.log()
    assert 'event=stage_end stage=map code=11 elapsed_seconds=' in log
    assert 'event=map_warning code=11 action=continue_parser_and_import' in log
    revision = '710003' if failed_stage == 'parser' else '710004'
    status = 'failed' if failed_stage else 'completed_with_warnings'
    assert_end(log, status, failed_stage or 'import', code, revision)
    assert_final_notification(cron, status, failed_stage or 'import', code, code,
                              revision, region, map_code=11)
    assert 'event=pipeline_end region=%s revision=%s status=%s ' % (
        region, revision, status) in log
    assert 'pipeline_exit=%s map_exit=11 log=%s' % (code, cron.logs()[0]) in log
    assert 'status=map_warning' not in log
    assert 'revision=710002' not in cron.messages()[0]


def test_shared_runner_map_stderr_with_zero_is_not_failure(cron_factory):
    cron = cron_factory()
    result = cron.run()
    assert result.returncode == 0
    assert 'fixture stderr map' in cron.log()
    assert 'event=map_warning' not in cron.log()
    assert_final_notification(cron, 'completed', 'import', 0, 0, '409351')
    assert_end(cron.log(), 'completed', 'import', 0)


@pytest.mark.parametrize('failure,stage,code,expected', [
    ('activate', 'setup_venv', 31, []),
    ('missing_activate', 'setup_venv', 1, []),
    ('activate_exit', 'setup_venv', 37, []),
    ('activate_exit_zero', 'setup_venv', 70, []),
    ('reactivate', 'parser_venv', 32, ['downloader', 'map']),
    ('downloader_cwd', 'downloader_cwd', 1, []),
    ('map_cwd', 'map_cwd', 1, ['downloader']),
    ('import_cwd', 'import_cwd', 1,
     ['downloader', 'map', 'parser_logging', 'parser']),
    ('logging', 'parser_logging', 33, ['downloader', 'map', 'parser_logging']),
])
def test_shared_runner_setup_and_cd_failures_are_stage_failures(
        cron_factory, failure, stage, code, expected):
    cron = cron_factory()
    settings = {}
    if failure == 'activate':
        settings['ACTIVATE_EXIT'] = code
    elif failure == 'missing_activate':
        cron.activate.unlink()
    elif failure in ('activate_exit', 'activate_exit_zero'):
        cron.activate.write_text('exit %s\n' % (37 if code == 37 else 0))
    elif failure == 'reactivate':
        settings['REACTIVATE_EXIT'] = code
    elif failure == 'downloader_cwd':
        shutil.rmtree(str(cron.root / 'downloader'))
    elif failure == 'map_cwd':
        (cron.root / 'parser_tidy').rmdir()
    elif failure == 'import_cwd':
        settings['REMOVE_IMPORT_CWD'] = '1'
    else:
        settings['PARSER_LOGGING_EXIT'] = code
    result = cron.run(**settings)
    assert result.returncode == code
    assert [row['stage'] for row in cron.stages()] == expected
    # An activation script exiting zero is still an incomplete failed run; the
    # summary retains its observed zero while the pipeline uses software error 70.
    stage_code = 0 if failure == 'activate_exit_zero' else code
    revision = 'unknown' if failure == 'downloader_cwd' else '409351'
    assert_end(cron.log(), 'failed', stage, stage_code, revision)
    assert 'event=stage_end stage=%s code=%s elapsed_seconds=' % (
        stage, stage_code) in cron.log()
    assert_final_notification(cron, 'failed', stage, stage_code, code, revision)
    assert 'status=completed' not in cron.log()


@pytest.mark.parametrize('failure,stage,code', [
    ('root', 'setup_root', 1),
    ('mkdir', 'setup_log', 34),
    ('mktemp', 'setup_log', 35),
    ('lock_open', 'setup_lock', 1),
    ('root_cwd', 'setup_cwd', 1),
])
def test_shared_runner_early_setup_errors_have_exit_summary(
        cron_factory, failure, stage, code):
    cron = cron_factory()
    direct = False
    if failure == 'root':
        # Direct/manual entry avoids replacing the thin example's dirname call.
        cron.write_tool('dirname', "print('/fixture-root-does-not-exist')")
        direct = True
    elif failure in ('mkdir', 'mktemp'):
        cron.write_tool(failure, 'import sys\nsys.exit(%s)' % code)
    elif failure == 'lock_open':
        (cron.root / 'logs/cron-tos.lock').mkdir(parents=True)
    else:
        # Acquire the actual flock first, then move just this temporary root so
        # the immediately following builtin cd fails. Its open log FD survives.
        cron.write_tool('flock', '''
            import os
            from pathlib import Path
            import subprocess
            import sys
            code = subprocess.call([%r] + sys.argv[1:], pass_fds=(9,))
            if code == 0:
                root = Path(os.environ['FIXTURE_ROOT'])
                root.rename(str(root) + '.moved')
            sys.exit(code)
        ''' % cron.flock)
    result = cron.run(direct=direct)
    assert result.returncode == code
    assert cron.stages() == []
    output = result.stdout + result.stderr
    if cron.logs():
        output += cron.log()
    assert_end(output, 'failed', stage, code)
    assert len(cron.records('curl')) == len(cron.messages()) == 1
    assert 'stage=%s\ncode=%s' % (stage, code) in cron.messages()[0]
    assert 'status=completed' not in output


@pytest.mark.parametrize('region', ['unknown', 'ktest', 'ITos', 'itos;echo unsafe'])
def test_shared_runner_rejects_non_supported_regions(cron_factory, region):
    cron = cron_factory()
    result = cron.run(region, direct=True)
    assert result.returncode == 64
    assert cron.stages() == []
    assert not cron.logs()
    assert_end(result.stdout + result.stderr, 'failed', 'setup_region', 64,
               'unknown')
    assert len(cron.records('curl')) == len(cron.messages()) == 1


@pytest.mark.parametrize('csv', [
    None, b'', b'jtos,509352\r\n', b'itos,broken\r\n',
    b'itos,409351,unexpected\r\n',
])
def test_shared_runner_unknown_revision_is_explicit(cron_factory, csv):
    cron = cron_factory()
    if csv is None:
        cron.revision.unlink()
    else:
        cron.revision.write_bytes(csv)
    result = cron.run(PARSER_EXIT=41)
    assert result.returncode == 41
    assert_end(cron.log(), 'failed', 'parser', 41, 'unknown')
    assert 'revision=unknown' in cron.messages()[0]
    assert '409351' not in cron.messages()[0]


@pytest.mark.parametrize('code', [0, 7])
@pytest.mark.parametrize('observed', ['900009', 'missing', 'malformed'])
def test_shared_runner_final_revision_is_not_a_cached_download_value(
        cron_factory, code, observed):
    cron = cron_factory()
    result = cron.run(REVISION_AFTER_DOWNLOADER='700007',
                      REVISION_AFTER_IMPORT=observed, IMPORT_EXIT=code)
    assert result.returncode == code
    revision = observed if observed == '900009' else 'unknown'
    assert_end(cron.log(), 'failed' if code else 'completed', 'import', code,
               revision)
    assert 'revision=' + revision in cron.messages()[0]
    assert 'revision=700007' not in cron.messages()[0]


def test_shared_runner_accepts_revision_without_final_newline(cron_factory):
    cron = cron_factory()
    cron.revision.write_bytes(b'jtos,12\r\nitos,987654')
    result = cron.run(DOWNLOADER_EXIT=1)
    assert result.returncode == 0
    assert_end(cron.log(), 'no_changes', 'downloader', 1, '987654')
    assert_no_notification(cron, cron.log())
    assert cron.revision.read_bytes() == b'jtos,12\r\nitos,987654'


def assert_curl_contract(cron):
    requests = cron.records('curl')
    assert requests
    for request in requests:
        args = request['args']
        assert args[0] == '--disable'  # never load a real curlrc
        assert '--fail' in args
        for option in ('--connect-timeout', '--max-time'):
            assert 0 < float(args[args.index(option) + 1]) <= 30
        if '--retry' in args:
            assert args[args.index('--retry') + 1] == '0'
        assert '--retry-all-errors' not in args
        assert args[args.index('--output') + 1] == '/dev/null'
        assert args[args.index('-H') + 1] == 'Content-Type: application/json'
        assert args[-1] == cron.env['TAVERN_DISCORD_WEBHOOK_URL']
        payload = args[args.index('--data-binary') + 1]
        document = json.loads(payload)
        assert set(document) == {'content'}
        assert len(document['content']) < 2000
        assert 'DO_NOT_FORWARD_FULL_LOG' not in document['content']
        assert 'SECRET_FIXTURE_TOKEN' not in document['content']


def test_shared_runner_webhook_json_escape_and_bounded_summary(cron_factory):
    cron = cron_factory('repo "quoted" \\backslash\n\t\r 한글')
    result = cron.run(LARGE_OUTPUT=1, MAP_EXIT=13)
    assert result.returncode == 0
    assert_final_notification(cron, 'completed_with_warnings', 'import', 0, 0,
                              '409351', map_code=13)
    for message in cron.messages():
        assert 'log=' + str(cron.logs()[0]) in message
        assert 'region=itos\nrevision=409351\n' in message
    assert 'DO_NOT_FORWARD_FULL_LOG:' in cron.log()
    assert 'SECRET_FIXTURE_TOKEN' not in cron.log() + result.stdout + result.stderr
    assert_end(cron.log(), 'completed_with_warnings', 'import', 0)


@pytest.mark.parametrize('delivery,curl_code', [('unset', 0), ('http', 22),
                                               ('timeout', 28)])
@pytest.mark.parametrize('pipeline_code', [0, 47])
def test_shared_runner_notification_failure_preserves_pipeline_and_status(
        cron_factory, delivery, curl_code, pipeline_code):
    cron = cron_factory()
    settings = {'PARSER_EXIT': pipeline_code, 'CURL_EXIT': curl_code}
    if delivery == 'unset':
        settings['TAVERN_DISCORD_WEBHOOK_URL'] = None
    result = cron.run(**settings)
    assert result.returncode == pipeline_code
    expected = ['downloader', 'map', 'parser_logging', 'parser']
    if not pipeline_code:
        expected.append('import')
    assert [row['stage'] for row in cron.stages()] == expected
    problem = 'unconfigured' if delivery == 'unset' else 'failed'
    base_status = 'failed' if pipeline_code else 'completed'
    assert_end(cron.log(), base_status + '_notification_' + problem,
               'parser' if pipeline_code else 'import', pipeline_code)
    assert 'event=notification status=' + problem in cron.log()
    if delivery == 'unset':
        assert cron.records('curl') == []
        assert cron.messages() == []
    else:
        assert_final_notification(cron, base_status,
                                  'parser' if pipeline_code else 'import',
                                  pipeline_code, pipeline_code, '409351')
        assert 'summary=%s code=%s' % (base_status, curl_code) in cron.log()
    assert 'SECRET_FIXTURE_TOKEN' not in cron.log() + result.stdout + result.stderr


@pytest.mark.parametrize('delivery', ['unset', 'http', 'timeout'])
@pytest.mark.parametrize('failed_stage,code', [(None, 0), ('parser', 49), ('import', 51)])
def test_shared_runner_map_final_notification_failure_preserves_pipeline(
        cron_factory, delivery, failed_stage, code):
    cron = cron_factory()
    curl_code = 28 if delivery == 'timeout' else 22
    settings = dict(MAP_EXIT=15, CURL_EXIT=curl_code,
                    REVISION_AFTER_PARSER='720003', REVISION_AFTER_IMPORT='720004')
    if failed_stage:
        settings[failed_stage.upper() + '_EXIT'] = code
    if delivery == 'unset':
        settings['TAVERN_DISCORD_WEBHOOK_URL'] = None
    result = cron.run(**settings)
    assert result.returncode == code
    expected = ['downloader', 'map', 'parser_logging', 'parser']
    if failed_stage != 'parser':
        expected.append('import')
    assert [row['stage'] for row in cron.stages()] == expected
    problem = 'unconfigured' if delivery == 'unset' else 'failed'
    status = 'failed' if failed_stage else 'completed_with_warnings'
    stage = failed_stage or 'import'
    revision = '720003' if failed_stage == 'parser' else '720004'
    assert_end(cron.log(), status + '_notification_' + problem,
               stage, code, revision)
    assert 'event=map_warning code=15' in cron.log()
    assert 'status=map_warning' not in cron.log()
    assert 'event=pipeline_end region=itos revision=%s status=%s ' % (
        revision, status) in cron.log()
    assert 'pipeline_exit=%s map_exit=15 log=%s' % (code, cron.logs()[0]) in cron.log()
    assert cron.log().count('event=notification_summary ') == 1
    assert cron.log().count('event=notification status=' + problem) == 1
    if delivery == 'unset':
        assert cron.records('curl') == []
        assert cron.messages() == []
    else:
        assert_final_notification(cron, status, stage, code, code, revision,
                                  map_code=15)
        assert 'summary=%s code=%s' % (status, curl_code) in cron.log()
    assert 'SECRET_FIXTURE_TOKEN' not in cron.log() + result.stdout + result.stderr


@pytest.mark.parametrize('held_stage', ['downloader', 'map', 'parser', 'import'])
@pytest.mark.parametrize('contender_region', REGIONS)
@pytest.mark.parametrize('holder_code', [0, 53])
def test_shared_runner_real_lock_covers_all_stages_and_releases(
        cron_factory, held_stage, contender_region, holder_code):
    cron = cron_factory()
    lock = cron.root / 'logs/cron-tos.lock'
    lock.parent.mkdir()
    lock.write_bytes(b'existing lock inode\n')
    inode = lock.stat().st_ino
    ready, release = cron.block()
    holder = cron.start('itos', BLOCK_STAGE=held_stage,
                        **{held_stage.upper() + '_EXIT': holder_code})
    cron.wait_ready(holder, ready)
    holder_log = cron.logs()[0]
    before = cron.stages()
    assert before[-1]['stage'] == held_stage
    # Direct/manual entry must contend with an example using the same lock.
    contender = cron.run(contender_region, direct=True)
    assert contender.returncode == 0
    assert cron.stages() == before, 'a skipped run executed a pipeline command'
    skipped_log = next(path for path in cron.logs() if path != holder_log)
    skipped = skipped_log.read_text()
    assert_end(skipped, 'skipped_lock', 'lock', 200)
    assert 'event=skipped_lock region=%s ' % contender_region in skipped
    assert 'event=stage_start stage=setup_venv' not in skipped
    assert 'event=stage_start stage=downloader' not in skipped
    assert 'status=failed' not in skipped
    assert_no_notification(cron, skipped)
    assert 'event=pipeline_end region=%s ' % contender_region in skipped
    assert 'pipeline_exit=0 map_exit=0 log=' + str(skipped_log) in skipped
    assert lock.stat().st_ino == inode
    assert lock.read_bytes() == b'existing lock inode\n'

    # The readiness pipe proves the holder is inside the selected stage; no
    # timing sleep is used to assume it owns the lock or to release it.
    os.write(release, b'G')
    finished = cron.complete(holder)
    expected_code = 0 if held_stage == 'map' else holder_code
    assert finished.returncode == expected_code
    holder_status = ('failed' if expected_code else
                     'completed_with_warnings' if held_stage == 'map' and holder_code
                     else 'completed')
    assert_end(holder_log.read_text(), holder_status,
               held_stage if expected_code else 'import', expected_code)
    assert len(cron.records('curl')) == len(cron.messages()) == 1
    assert 'status=' + holder_status in cron.messages()[0]
    assert 'map_exit=%s' % (holder_code if held_stage == 'map' else 0) in cron.messages()[0]
    assert 'log=' + str(holder_log) in cron.messages()[0]
    assert_curl_contract(cron)
    preserved = {path: path.read_bytes() for path in cron.logs()}
    previous_stages = len(cron.stages())
    # A new region succeeds after either normal or failed exit of the holder.
    following = cron.run('ktos')
    assert following.returncode == 0
    assert len(cron.stages()) == previous_stages + 5
    for path, data in preserved.items():
        assert path.read_bytes() == data
    assert len(cron.logs()) == 3
    assert len(cron.records('curl')) == len(cron.messages()) == 2
    assert lock.stat().st_ino == inode
    assert lock.read_bytes() == b'existing lock inode\n'


@pytest.mark.parametrize('contender_region', REGIONS)
@pytest.mark.parametrize('delivery', ['unset', 'http', 'timeout'])
def test_shared_runner_skipped_lock_never_attempts_notification(
        cron_factory, contender_region, delivery):
    cron = cron_factory()
    ready, release = cron.block()
    holder = cron.start('itos', BLOCK_STAGE='parser')
    cron.wait_ready(holder, ready)
    holder_log = cron.logs()[0]
    lock = cron.root / 'logs/cron-tos.lock'
    inode = lock.stat().st_ino
    before = cron.stages()
    settings = dict(CURL_EXIT=28 if delivery == 'timeout' else 22)
    if delivery == 'unset':
        settings['TAVERN_DISCORD_WEBHOOK_URL'] = None
    result = cron.run(contender_region, direct=True, **settings)
    assert result.returncode == 0
    assert cron.stages() == before
    skipped_log = next(path for path in cron.logs() if path != holder_log)
    skipped = skipped_log.read_text()
    assert_end(skipped, 'skipped_lock', 'lock', 200)
    assert_no_notification(cron, skipped)
    assert 'event=stage_end stage=lock code=200 elapsed_seconds=' in skipped
    assert 'event=skipped_lock region=%s ' % contender_region in skipped
    assert 'event=pipeline_end region=%s ' % contender_region in skipped
    assert 'pipeline_exit=0 map_exit=0 log=' + str(skipped_log) in skipped
    assert 'event=stage_start stage=setup_venv' not in skipped
    assert 'SECRET_FIXTURE_TOKEN' not in skipped + result.stdout + result.stderr
    saved = skipped_log.read_bytes()
    os.write(release, b'G')
    assert cron.complete(holder).returncode == 0
    assert_end(holder_log.read_text(), 'completed', 'import', 0, '409351')
    assert len(cron.records('curl')) == len(cron.messages()) == 1
    assert 'status=completed\nstage=import\ncode=0' in cron.messages()[0]
    assert 'log=' + str(holder_log) in cron.messages()[0]
    assert skipped_log.read_bytes() == saved
    assert len(cron.logs()) == 2
    assert lock.stat().st_ino == inode


@pytest.mark.parametrize('code', [7, 65])
def test_shared_runner_flock_error_is_not_lock_contention(cron_factory, code):
    cron = cron_factory()
    cron.write_tool('flock', 'import sys\nsys.exit(%s)' % code)
    result = cron.run()
    assert result.returncode == code
    assert cron.stages() == []
    assert_end(cron.log(), 'failed', 'lock', code)
    assert 'skipped_lock' not in cron.log()
    assert_final_notification(cron, 'failed', 'lock', code, code, '409351')
    assert (cron.root / 'logs/cron-tos.lock').is_file()


def test_shared_runner_actual_flock_error_is_not_skipped(cron_factory):
    cron = cron_factory()
    cron.write_tool('flock', '''
        import os
        import sys
        # Close only the child's descriptor, then let actual flock report its
        # invalid-FD error. The runner still owns its open, unlocked descriptor.
        os.close(9)
        os.execv(%r, [%r] + sys.argv[1:])
    ''' % (cron.flock, cron.flock))
    result = cron.run()
    assert result.returncode not in (0, 200)
    assert cron.stages() == []
    assert_end(cron.log(), 'failed', 'lock', result.returncode)
    assert 'skipped_lock' not in cron.log()
    assert_final_notification(cron, 'failed', 'lock', result.returncode,
                              result.returncode, '409351')
    assert (cron.root / 'logs/cron-tos.lock').is_file()


def test_shared_runner_interruption_is_failure_and_releases_lock(cron_factory):
    cron = cron_factory()
    ready, _ = cron.block()
    holder = cron.start(BLOCK_STAGE='parser')
    cron.wait_ready(holder, ready)
    lock = cron.root / 'logs/cron-tos.lock'
    inode = lock.stat().st_ino
    os.killpg(holder.pid, signal.SIGTERM)
    result = cron.complete(holder)
    assert result.returncode == 143
    assert [row['stage'] for row in cron.stages()] == [
        'downloader', 'map', 'parser_logging', 'parser']
    assert_end(cron.log(), 'failed', 'parser', 143)
    assert 'status=completed' not in cron.log()
    assert_final_notification(cron, 'failed', 'parser', 143, 143, '409351')
    interrupted_log = cron.logs()[0]
    saved = interrupted_log.read_bytes()
    assert cron.run('jtos').returncode == 0
    assert lock.stat().st_ino == inode
    assert interrupted_log.read_bytes() == saved


def test_shared_runner_logs_unique_even_with_identical_timestamp_and_preserved(
        cron_factory):
    cron = cron_factory()
    actual_mktemp = shutil.which('mktemp')
    assert actual_mktemp, 'actual mktemp is required (never skip)'
    # Freeze only the timestamp in the requested template, then use real mktemp.
    # This exercises same-second uniqueness without depending on test speed or
    # changing the runner's Bash implementation, clock, or random suffixes.
    cron.write_tool('mktemp', '''
        from pathlib import Path
        import subprocess
        import sys
        args = sys.argv[1:]
        template = Path(args[-1])
        parts = template.name.split('.')
        parts[1] = 'fixedsecond'
        args[-1] = str(template.with_name('.'.join(parts)))
        sys.exit(subprocess.call([%r] + args))
    ''' % actual_mktemp)
    logs = cron.root / 'logs'
    logs.mkdir()
    previous = logs / 'cron-itos.fixedsecond.KEEP00.log'
    previous.write_bytes(b'prior output must survive\n')
    preserved = {previous: previous.read_bytes()}
    for code in (0, 59, 0):
        result = cron.run(PARSER_EXIT=code)
        assert result.returncode == code
        for path, data in preserved.items():
            assert path.read_bytes() == data
        created = set(cron.logs()) - set(preserved)
        assert len(created) == 1
        path = created.pop()
        assert '.fixedsecond.' in path.name
        assert_end(path.read_text(), 'failed' if code else 'completed',
                   'parser' if code else 'import', code)
        preserved[path] = path.read_bytes()
    assert len(cron.logs()) == 4
    assert len({path.name for path in cron.logs()}) == 4
