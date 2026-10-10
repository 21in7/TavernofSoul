# -*- coding: utf-8 -*-
"""cron 안전장치(안전장치 3) 검증 테스트.

repo 루트의 추적되는 cron_*.sh.example 5개가 parser 반환 코드를 검사해
실패 시 import 를 중단하는지 확인한다. 로컬 운영 cron 은 읽지 않는다.
"""
import os
import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
REPO_ROOT = os.path.dirname(PARENT)

CRON_FILES = [
    'cron_itos.sh.example',
    'cron_jtos.sh.example',
    'cron_ktos.sh.example',
    'cron_ktest.sh.example',
    'cron_twtos.sh.example',
]


def _read_cron(name):
    path = os.path.join(REPO_ROOT, name)
    # Missing tracked examples must fail, even when a local operational cron exists.
    with open(path, encoding='utf-8') as f:
        return f.read()


@pytest.mark.parametrize('name', CRON_FILES)
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


@pytest.mark.parametrize('name', CRON_FILES)
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


@pytest.mark.parametrize('name', CRON_FILES)
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
