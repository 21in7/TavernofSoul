# -*- coding: utf-8 -*-
"""cron 안전장치(안전장치 3) 검증 테스트.

repo 루트의 cron_*.sh 5개가 parser 반환 코드를 검사해 실패 시 import 를
중단하는지 확인한다.
"""
import os
import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
REPO_ROOT = os.path.dirname(PARENT)

CRON_FILES = [
    'cron_itos.sh',
    'cron_jtos.sh',
    'cron_ktos.sh',
    'cron_ktest.sh',
    'cron_twtos.sh',
]


def _read_cron(name):
    path = os.path.join(REPO_ROOT, name)
    if not os.path.exists(path):
        pytest.skip('%s not available' % name)
    with open(path, encoding='utf-8') as f:
        return f.read()


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
    assert pos_parse < pos_abort < pos_import or pos_abort < pos_import, (
        '%s: import must come after parser failure guard' % name
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
