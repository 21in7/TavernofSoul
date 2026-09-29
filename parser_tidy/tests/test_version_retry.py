# -*- coding: utf-8 -*-
"""version.json 커밋 완료 표시와 재시도 보장 회귀 테스트.

PROFILING_REVIEW P1 결함 2: parser_version.csv 를 먼저 전진시킨 뒤
version.json 쓰기가 실패하면, 이전 구현은 시작 조건(revision ==
parser_version.csv)에서 조기 종료해 재시도하지 않았다. 이로 인해
'커밋 완료 표시' 의도가 영구적으로 뒤처질 수 있었다.

새 구현은 시작 조건에서 version.json 의 버전도 검사해, version.json 이
parser_version.csv 보다 뒤처지면(커밋 미완료 상태) 빌드를 재진행한다.
"""
import json
import os
import sys
import tempfile

import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


class TestStripVersionSuffix:
    def test_standard_ipf_suffix(self):
        from main import _strip_version_suffix
        assert _strip_version_suffix('20260723_001001.ipf') == '20260723'

    def test_none(self):
        from main import _strip_version_suffix
        assert _strip_version_suffix(None) is None

    def test_empty(self):
        from main import _strip_version_suffix
        assert _strip_version_suffix('') is None

    def test_no_suffix(self):
        from main import _strip_version_suffix
        # 접미사가 없으면 그대로 반환.
        assert _strip_version_suffix('20260723') == '20260723'


class TestReadCommittedVersion:
    def test_reads_committed_version(self, monkeypatch):
        """version.json 이 존재하면 커밋 완료 버전을 반환한다."""
        import main
        with tempfile.TemporaryDirectory() as d:
            json_dir = os.path.join(d, 'TavernofSoul', 'JSON_ktos')
            os.makedirs(json_dir)
            with open(os.path.join(json_dir, 'version.json'), 'w') as f:
                json.dump({'version': '20260723_001001.ipf'}, f)
            # SCRIPT_DIR 을 임시 디렉터리 기준으로 우회.
            monkeypatch.setattr(main, 'SCRIPT_DIR', os.path.join(d, 'parser_tidy'))
            os.makedirs(os.path.join(d, 'parser_tidy'), exist_ok=True)
            result = main.read_committed_version('ktos')
            assert result == '20260723'

    def test_missing_version_json_returns_none(self, monkeypatch):
        """version.json 이 없으면 None(커밋 미완료)을 반환한다."""
        import main
        with tempfile.TemporaryDirectory() as d:
            json_dir = os.path.join(d, 'TavernofSoul', 'JSON_ktos')
            os.makedirs(json_dir)
            monkeypatch.setattr(main, 'SCRIPT_DIR', os.path.join(d, 'parser_tidy'))
            os.makedirs(os.path.join(d, 'parser_tidy'), exist_ok=True)
            result = main.read_committed_version('ktos')
            assert result is None

    def test_corrupted_version_json_returns_none(self, monkeypatch):
        """손상된 version.json 도 None(커밋 미완료)로 취급한다."""
        import main
        with tempfile.TemporaryDirectory() as d:
            json_dir = os.path.join(d, 'TavernofSoul', 'JSON_ktos')
            os.makedirs(json_dir)
            with open(os.path.join(json_dir, 'version.json'), 'w') as f:
                f.write('{corrupted json')
            monkeypatch.setattr(main, 'SCRIPT_DIR', os.path.join(d, 'parser_tidy'))
            os.makedirs(os.path.join(d, 'parser_tidy'), exist_ok=True)
            result = main.read_committed_version('ktos')
            assert result is None


class TestStartupConditionChecksVersionJson:
    """main.py 소스가 version.json 상태를 시작 조건에서 검사하는지 확인."""

    def test_startup_checks_committed_version(self):
        """main.py 소스에 read_committed_version 호출과 up_to_date 검사가 있어야 함."""
        src_path = os.path.join(PARENT, 'main.py')
        with open(src_path, encoding='utf-8') as f:
            src = f.read()
        # read_committed_version 을 시작 조건에서 호출해야 함.
        assert 'read_committed_version(region)' in src, (
            'startup must call read_committed_version(region) to detect '
            'incomplete commits'
        )
        # up_to_date 가 version.json(committed) 일치도 검사해야 함.
        assert 'committed == current_version[region]' in src, (
            'startup up_to_date must require version.json to match '
            'parser_version.csv (commit-complete marker)'
        )

    def test_commit_incomplete_warning_present(self):
        """커밋 미완료 상태를 감지하고 경고하는 코드가 있어야 함."""
        src_path = os.path.join(PARENT, 'main.py')
        with open(src_path, encoding='utf-8') as f:
            src = f.read()
        assert 'commit incomplete' in src.lower(), (
            'startup must warn when parser_version.csv has advanced but '
            'version.json has not (incomplete commit)'
        )
        # 재시도를 위해 quit() 하지 않고 빌드를 진행해야 함.
        # 'commit incomplete' 경고 후에 quit() 가 바로 오면 안 됨.
        idx_warn = src.lower().find('commit incomplete')
        # 경고 이후 200자 이내에 quit() 가 있으면 재진행하지 않는 것.
        assert 'quit()' not in src[idx_warn:idx_warn + 200], (
            'startup must NOT quit on incomplete commit; it must re-run build'
        )

    def test_version_json_integrated_into_export(self):
        """version.json 이 export(version_payload) 트랜잭션에 통합되어야 함.

        version.json 은 더 이상 main.py 에서 별도로 직접 쓰지 않고,
        c.export(version_payload=v) 의 JSON 승급 트랜잭션에 포함되어 공개 JSON
        과 함께 원자적으로 승급된다. 이로써 JSON 만 신버전이고 version.json 은
        구버전인 혼합 상태가 방지된다.
        """
        src_path = os.path.join(PARENT, 'main.py')
        with open(src_path, encoding='utf-8') as f:
            src = f.read()
        # export 가 version_payload 인자를 받아야 함(주석이 아닌 실제 코드 행).
        assert '    c.export(version_payload=v)' in src, (
            'main.py must call c.export(version_payload=v) to integrate '
            'version.json into the JSON promotion transaction'
        )
        # 별도의 version.json 직접 쓰기가 없어야 함.
        assert "_atomic_write_text(\n        join(c.BASE_PATH_OUTPUT, 'version.json')" not in src, (
            'version.json must not be written separately in main.py; it must '
            'be part of the export() transaction'
        )


class TestVersionJsonInExportTransaction:
    """[P1 결함 3] version.json 이 JSON 승급 트랜잭션에 통합되었는지 동작 검증."""

    def _make_db(self, release_dir, data):
        from DB import ToS_DB
        c = ToS_DB.__new__(ToS_DB)
        c.BASE_PATH_OUTPUT = release_dir
        c.data = data
        return c

    def test_version_json_promoted_with_jsons(self):
        """export(version_payload) 성공 시 version.json 이 공개 디렉터리에 함께 승급."""
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            c = self._make_db(release_dir, {'items': {'1': {}}})
            c.export(version_payload={'version': '20260723_001001.ipf'})
            version_path = os.path.join(release_dir, 'version.json')
            assert os.path.exists(version_path)
            with open(version_path) as f:
                assert json.load(f) == {'version': '20260723_001001.ipf'}

    def test_version_json_rolled_back_on_promotion_failure(self, monkeypatch):
        """[P1 결함 3] 공개 승급 실패 시 version.json 도 구버전으로 롤백되어야 함.

        핵심: version.json 이 JSON 트랜잭션에 통합되었으므로, JSON 승급 실패 시
        version.json 도 구버전으로 복구되어 JSON/version.json 혼합을 방지한다.
        """
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            staging_dir = release_dir + '.staging'
            backup_dir = release_dir + '.backup'
            os.makedirs(release_dir)
            # 기존 공개 파일들(구버전).
            with open(os.path.join(release_dir, 'items.json'), 'w') as f:
                json.dump({'old_items': True}, f)
            with open(os.path.join(release_dir, 'version.json'), 'w') as f:
                json.dump({'version': 'OLD_001001.ipf'}, f)

            original_replace = os.replace
            promote_count = {'n': 0}

            def fail_second_promotion(src, dst):
                if os.path.dirname(src) == backup_dir:
                    return original_replace(src, dst)
                if os.path.dirname(dst) == release_dir:
                    promote_count['n'] += 1
                    if promote_count['n'] >= 2:
                        raise OSError('simulated promotion failure on 2nd file')
                return original_replace(src, dst)

            monkeypatch.setattr('DB.os.replace', fail_second_promotion)
            c = self._make_db(release_dir, {
                'items': {'new_items': True},
            })
            with pytest.raises(OSError):
                c.export(version_payload={'version': 'NEW_001001.ipf'})
            assert promote_count['n'] >= 2
            # 핵심: version.json 도 구버전으로 롤백되어야 한다.
            with open(os.path.join(release_dir, 'version.json')) as f:
                assert json.load(f) == {'version': 'OLD_001001.ipf'}, (
                    'version.json must be rolled back to old version together '
                    'with JSONs (no mixed JSON=new/version=old state)'
                )
            # items.json 도 구버전.
            with open(os.path.join(release_dir, 'items.json')) as f:
                assert json.load(f) == {'old_items': True}

    def test_version_json_not_written_when_export_skips_payload(self):
        """version_payload 미전달 시 기존처럼 version.json 을 건드리지 않음."""
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            c = self._make_db(release_dir, {'items': {'1': {}}})
            c.export()  # version_payload=None
            version_path = os.path.join(release_dir, 'version.json')
            assert not os.path.exists(version_path)
