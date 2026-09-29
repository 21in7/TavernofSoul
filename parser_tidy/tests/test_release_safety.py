# -*- coding: utf-8 -*-
"""공개 안전성(안전장치 1, 2) 단위 테스트.

main.py 의 _atomic_write_text, print_version, 조기 export 제거, 버전 파일
갱신 순서를 검증한다.
"""
import os
import sys
import json
import csv
import tempfile

import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


def test_atomic_write_text_replaces_existing():
    from main import _atomic_write_text
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'out.txt')
        with open(path, 'w') as f:
            f.write('OLD')
        _atomic_write_text(path, 'NEW')
        with open(path) as f:
            assert f.read() == 'NEW'


def test_atomic_write_text_no_tmp_left_behind():
    from main import _atomic_write_text
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'out.txt')
        _atomic_write_text(path, 'X')
        # 임시 파일이 남지 않아야 한다.
        assert not os.path.exists(path + '.tmp')


def test_atomic_write_text_preserves_old_on_error(monkeypatch):
    """os.replace 가 실패하면 원본은 보존되어야 한다."""
    from main import _atomic_write_text
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'out.txt')
        with open(path, 'w') as f:
            f.write('OLD')

        def boom(src, dst):
            raise OSError('simulated replace failure')

        monkeypatch.setattr('main.os.replace', boom)
        with pytest.raises(OSError):
            _atomic_write_text(path, 'NEW')
        with open(path) as f:
            assert f.read() == 'OLD'


def test_print_version_writes_csv_atomically():
    import main
    with tempfile.TemporaryDirectory() as d:
        # SCRIPT_DIR 을 임시 디렉터리로 우회.
        orig = main.SCRIPT_DIR
        main.SCRIPT_DIR = d
        try:
            main.print_version('parser_version.csv', {'ktos': '20260722', 'itos': '20260721'})
            path = os.path.join(d, 'parser_version.csv')
            assert os.path.exists(path)
            with open(path) as f:
                rows = list(csv.reader(f))
            d_map = {r[0]: r[1] for r in rows if len(r) >= 2}
            assert d_map['ktos'] == '20260722'
            assert d_map['itos'] == '20260721'
            assert not os.path.exists(path + '.tmp')
        finally:
            main.SCRIPT_DIR = orig


def test_early_skills_export_removed():
    """main.py 소스에 iTOS 조기 skills export 가 더 이상 없어야 한다."""
    src_path = os.path.join(PARENT, 'main.py')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    # 조기 export 코드 라인이 제거됐는지 확인.
    assert "c.printJSON(c.data['skills'], 'skills.json')" not in src, (
        'iTOS early skills export must be removed (release safety)'
    )
    assert 'Early export of skills' not in src


def test_version_update_order_in_source():
    """main.py 소스에서 parser_version.csv 가 export(version_payload) 보다 먼저여야 한다.

    version.json 은 이제 c.export(version_payload=v) 의 JSON 승급 트랜잭션에
    통합되어 공개 JSON 과 함께 원자적으로 승급된다. parser_version.csv 는
    export() 보다 먼저 갱신되며, export() 실패 시 version.json 은 구버전으로
    남아 시작 조건의 불일치 검사가 다음 실행 재시도를 보장한다.
    """
    src_path = os.path.join(PARENT, 'main.py')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    # 주석이 아닌 실제 코드 행을 매칭하도록 들여쓰기(4 spaces)를 포함해 검색.
    pos_parser_csv = src.find("    print_version('parser_version.csv', current_version)")
    pos_export = src.find('    c.export(version_payload=v)')
    assert pos_parser_csv != -1, 'parser_version.csv write not found'
    assert pos_export != -1, 'c.export(version_payload=v) not found'
    assert pos_parser_csv < pos_export, (
        'parser_version.csv must be written BEFORE c.export(version_payload) '
        'so that export failure leaves version.json at the old version '
        '(retry guaranteed by startup inconsistency check)'
    )
    # version.json 은 이제 export() 트랜잭션 내부에서만 기록되어야 한다.
    # main.py 에서 별도의 version.json 직접 쓰기가 없는지 확인.
    assert "join(c.BASE_PATH_OUTPUT, 'version.json')" not in src, (
        'version.json must be written only inside export(version_payload); '
        'no separate direct write in main.py'
    )
