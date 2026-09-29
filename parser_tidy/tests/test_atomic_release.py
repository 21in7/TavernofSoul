# -*- coding: utf-8 -*-
"""원자적 릴리스 디렉터리 일괄 승급 단위 테스트.

PROFILING_REVIEW P0 (설계 후 범위): export() 는 모든 data 컬렉션을
입력 디렉터리와 분리된 형제 staging 디렉터리(JSON_<region>.staging/)에
완전히 직렬화·검증한 뒤, 전체 성공 시에만 공개 파일을 os.replace 로
원자 교체한다. 실패 시 staging 만 폐기하고 기존 공개 릴리스를 보존한다.

이 테스트는 DB.py 의 export(), _atomic_write_json, _validate_json_file 을
직접 검증한다.
"""
import json
import os
import shutil
import sys
import tempfile

import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


def _make_constants(release_dir, data):
    """export() 에 필요한 최소 ToS_DB 표면을 가짜로 만든다."""
    from DB import ToS_DB
    c = ToS_DB.__new__(ToS_DB)  # __init__ 건너뛰기(클래스 가변 상태 오염 방지)
    c.BASE_PATH_OUTPUT = release_dir
    c.data = data
    return c


class TestAtomicWriteJson:
    def test_writes_and_replaces(self):
        from DB import _atomic_write_json
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'out.json')
            _atomic_write_json(path, {'a': 1})
            with open(path) as f:
                assert json.load(f) == {'a': 1}
            assert not os.path.exists(path + '.tmp')

    def test_preserves_old_on_replace_failure(self, monkeypatch):
        from DB import _atomic_write_json
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'out.json')
            with open(path, 'w') as f:
                json.dump({'old': True}, f)

            def boom(src, dst):
                raise OSError('simulated replace failure')

            monkeypatch.setattr('DB.os.replace', boom)
            with pytest.raises(OSError):
                _atomic_write_json(path, {'new': True})
            with open(path) as f:
                assert json.load(f) == {'old': True}


class TestValidateJsonFile:
    def test_valid_file_passes(self):
        from DB import _validate_json_file
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'ok.json')
            with open(path, 'w') as f:
                json.dump({'a': 1}, f)
            # 예외 없이 통과해야 한다.
            _validate_json_file(path)

    def test_invalid_json_raises(self):
        from DB import _validate_json_file
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'bad.json')
            with open(path, 'w') as f:
                f.write('{not valid json')
            with pytest.raises(json.JSONDecodeError):
                _validate_json_file(path)


class TestExportAtomicPromotion:
    def test_all_files_promoted_on_success(self):
        """export() 성공 시 모든 컬렉션이 공개 디렉터리에 원자 교체된다."""
        from DB import ToS_DB
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            data = {
                'items': {'1': {'Name': 'A'}},
                'skills': {'2': {'Name': 'B'}},
            }
            c = _make_constants(release_dir, data)
            c.export()

            items_path = os.path.join(release_dir, 'items.json')
            skills_path = os.path.join(release_dir, 'skills.json')
            assert os.path.exists(items_path)
            assert os.path.exists(skills_path)
            with open(items_path) as f:
                assert json.load(f) == {'1': {'Name': 'A'}}
            with open(skills_path) as f:
                assert json.load(f) == {'2': {'Name': 'B'}}

    def test_staging_dir_cleaned_after_success(self):
        """성공 후 staging 디렉터리는 비어 있어야 한다(os.replace 로 파일 이동)."""
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            staging_dir = release_dir + '.staging'
            c = _make_constants(release_dir, {'items': {'1': {}}})
            c.export()
            # staging 디렉터리 자체는 남을 수 있지만 안은 비어 있어야 한다.
            if os.path.exists(staging_dir):
                assert os.listdir(staging_dir) == []

    def test_existing_release_preserved_on_serialization_failure(
        self, monkeypatch,
    ):
        """직렬화 실패 시 기존 공개 파일은 보존되고 staging 만 폐기된다."""
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            # 기존 공개 파일을 미리 둔다.
            existing_path = os.path.join(release_dir, 'items.json')
            with open(existing_path, 'w') as f:
                json.dump({'old': True}, f)

            # 직렬화 불가능한 객체를 넣어 json.dump 가 실패하게 한다.
            class NotSerializable:
                pass
            c = _make_constants(release_dir, {'items': NotSerializable()})
            with pytest.raises(Exception):
                c.export()
            # 공개 파일은 기존 내용 그대로.
            with open(existing_path) as f:
                assert json.load(f) == {'old': True}
            # staging 은 폐기되어야 한다.
            staging_dir = release_dir + '.staging'
            assert not os.path.exists(staging_dir)

    def test_existing_release_preserved_on_validation_failure(
        self, monkeypatch,
    ):
        """검증 실패 시에도 기존 공개 파일은 보존되고 staging 만 폐기된다.

        검증 단계에서 실패하면 아직 공개 파일 교체가 시작되지 않았으므로
        공개 릴리스는 무결하다.
        """
        from DB import _validate_json_file
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            existing_path = os.path.join(release_dir, 'items.json')
            with open(existing_path, 'w') as f:
                json.dump({'old': True}, f)

            # 검증 단계에서 항상 실패하게 만든다.
            def fail_validate(filepath):
                raise OSError('simulated validation failure')

            monkeypatch.setattr('DB._validate_json_file', fail_validate)
            c = _make_constants(release_dir, {'items': {'new': True}})
            with pytest.raises(OSError):
                c.export()
            with open(existing_path) as f:
                assert json.load(f) == {'old': True}
            staging_dir = release_dir + '.staging'
            assert not os.path.exists(staging_dir)

    def test_no_partial_promotion_on_validation_failure(self, monkeypatch):
        """검증 단계 실패 시 공개 파일이 전혀 교체되지 않아야 한다.

        검증을 모두 마친 뒤에만 교체 단계로 진입하므로, 검증 중 실패하면
        공개 릴리스는 전부 구버전 그대로다(교체 전이므로).
        """
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            # 두 컬렉션의 기존 파일.
            for name in ('items', 'skills'):
                with open(os.path.join(release_dir, name + '.json'), 'w') as f:
                    json.dump({'old_%s' % name: True}, f)

            # 검증 단계: 두 번째 파일 검증 시 실패.
            original_validate = _validate_json_file_import()
            call_count = {'n': 0}

            def selective_fail(filepath):
                call_count['n'] += 1
                if call_count['n'] >= 2:
                    raise OSError('simulated validation failure on 2nd file')
                original_validate(filepath)

            monkeypatch.setattr('DB._validate_json_file', selective_fail)
            c = _make_constants(release_dir, {
                'items': {'new_items': True},
                'skills': {'new_skills': True},
            })
            with pytest.raises(OSError):
                c.export()
            # 두 파일 모두 기존 내용이어야 한다(교체 전 검증 실패).
            for name in ('items', 'skills'):
                with open(os.path.join(release_dir, name + '.json')) as f:
                    assert json.load(f) == {'old_%s' % name: True}

    def test_replace_failure_rolls_back_all_files(self, monkeypatch):
        """[P1 결함 1] os.replace 공개 승급 실패 시 백업에서 전부 복구해야 한다.

        핵심 회귀: 파일별 os.replace 를 반복하므로, N번째 승급이 실패할 때
        1~N-1번 파일은 이미 신버전이다. 백업·롤백 없으면 공개 릴리스가
        부분 승격(혼합)된다. 이 테스트는 두 번째 공개 승급을 실패시키고
        첫 번째 파일까지 구버전으로 복구되는지 검증한다.

        주의: os.replace 는 staging 직렬화(.tmp->JSON)에서도 호출되므로,
        단순 호출 카운트로는 공개 승급 경로를 시험할 수 없다. src 가
        staging_dir 에 있는(공개 승급) 호출만 세어 실패를 주입한다.
        """
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            staging_dir = release_dir + '.staging'
            os.makedirs(release_dir)
            # 두 컬렉션의 기존 파일(구버전).
            with open(os.path.join(release_dir, 'items.json'), 'w') as f:
                json.dump({'old_items': True}, f)
            with open(os.path.join(release_dir, 'skills.json'), 'w') as f:
                json.dump({'old_skills': True}, f)

            # 공개 승급(staging->release) os.replace 만 카운트해 실패시킨다.
            # 주의: src 부모가 staging_dir 인 조건만으로는 부족하다 — staging 내부
            # 직렬화의 .tmp -> JSON os.replace 도 src 부모가 staging_dir 이다.
            # dst 부모가 release_dir 인 공개 승급 호출만 세되, 롤백 단계의
            # os.replace(backup->release) 도 dst 부모가 release_dir 이다.
            # 따라서 src 부모가 backup_dir 인 롤백 호출은 실패에서 제외한다.
            original_replace = os.replace
            promote_count = {'n': 0}
            backup_dir = release_dir + '.backup'

            def fail_second_promotion(src, dst):
                # 롤백(backup->release) 호출은 정상 통과시킨다.
                if os.path.dirname(src) == backup_dir:
                    return original_replace(src, dst)
                # 공개 승급(staging->release) 만 카운트.
                if os.path.dirname(dst) == release_dir:
                    promote_count['n'] += 1
                    if promote_count['n'] >= 2:
                        raise OSError('simulated promotion failure on 2nd file')
                return original_replace(src, dst)

            monkeypatch.setattr('DB.os.replace', fail_second_promotion)
            c = _make_constants(release_dir, {
                'items': {'new_items': True},
                'skills': {'new_skills': True},
            })
            with pytest.raises(OSError):
                c.export()
            # 두 번째 공개 승급이 실제로 시도되었는지 확인(롤백 경로 검증 전제).
            assert promote_count['n'] >= 2, (
                'test must reach the 2nd public promotion; staging serialization '
                'replaces must not be counted (%d)' % promote_count['n']
            )
            # 핵심: 두 파일 모두 구버전으로 복구되어야 한다.
            with open(os.path.join(release_dir, 'items.json')) as f:
                assert json.load(f) == {'old_items': True}, (
                    'items.json must be rolled back to old version '
                    '(partial promotion bug)'
                )
            with open(os.path.join(release_dir, 'skills.json')) as f:
                assert json.load(f) == {'old_skills': True}, (
                    'skills.json must be rolled back to old version '
                    '(partial promotion bug)'
                )

    def test_replace_failure_removes_new_files_without_backup(self, monkeypatch):
        """[P1 결함 1] 백업 원본이 없는(신규) 파일은 공개 승급 실패 시 제거.

        신규 파일은 백업에 원본이 없다. 신규 파일이 먼저 승급된 뒤 후속(기존 파일)
        승급이 실패하면, 신규 파일의 신버전이 공개에 올라간 상태에서 롤백이
        공개 위치에서 삭제해야 한다.

        순서 주의: newcoll(신규) 을 data dict 에서 items(기존) 보다 먼저 두어
        newcoll 이 먼저 승급되게 하고, 두 번째 승급(items) 을 실패시킨다. 그래야
        newcoll 이 공개에 신버전으로 올라간 뒤 롤백 제거 경로가 실행된다.
        dst 부모가 release_dir 인 공개 승급 호출만 카운트한다.
        """
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            staging_dir = release_dir + '.staging'
            os.makedirs(release_dir)
            # items 는 기존 파일, newcoll 은 신규(기존 파일 없음).
            with open(os.path.join(release_dir, 'items.json'), 'w') as f:
                json.dump({'old_items': True}, f)

            original_replace = os.replace
            promote_count = {'n': 0}
            backup_dir = release_dir + '.backup'

            def fail_second_promotion(src, dst):
                # 롤백(backup->release) 호출과 신규 파일 제거는 정상 통과시킨다.
                if os.path.dirname(src) == backup_dir:
                    return original_replace(src, dst)
                # 공개 승급(staging->release) 만 카운트.
                if os.path.dirname(dst) == release_dir:
                    promote_count['n'] += 1
                    if promote_count['n'] >= 2:
                        raise OSError('simulated promotion failure on 2nd file')
                return original_replace(src, dst)

            monkeypatch.setattr('DB.os.replace', fail_second_promotion)
            # newcoll(신규) 먼저, items(기존) 나중 — newcoll 승급 성공 후
            # items 승급 실패로 newcoll 롤백 제거 경로를 시험한다.
            c = _make_constants(release_dir, {
                'newcoll': {'new_newcoll': True},
                'items': {'new_items': True},
            })
            with pytest.raises(OSError):
                c.export()
            # 두 번째 공개 승급이 실제로 시도되었는지 확인.
            assert promote_count['n'] >= 2, (
                'test must reach the 2nd public promotion; staging serialization '
                'replaces must not be counted (%d)' % promote_count['n']
            )
            # items 는 구버전으로 복구.
            with open(os.path.join(release_dir, 'items.json')) as f:
                assert json.load(f) == {'old_items': True}
            # newcoll 은 공개에 남지 않아야 한다(백업 원본이 없으므로 제거).
            assert not os.path.exists(os.path.join(release_dir, 'newcoll.json')), (
                'new file must be removed on rollback (no backup to restore)'
            )

    def test_staging_is_sibling_not_inside_release(self):
        """staging 디렉터리는 release_dir 안이 아니라 형제여야 한다."""
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            c = _make_constants(release_dir, {'items': {'1': {}}})
            c.export()
            staging_dir = release_dir + '.staging'
            # staging 경로는 release_dir 의 형제.
            assert os.path.dirname(staging_dir) == os.path.dirname(release_dir)
            # release_dir 안에 .staging 서브디렉터리가 없어야 한다.
            assert not os.path.exists(os.path.join(release_dir, '.staging'))

    def test_stale_staging_cleaned_on_start(self):
        """이전 run 의 잔재 staging 이 있으면 폐기하고 시작한다."""
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            staging_dir = release_dir + '.staging'
            os.makedirs(staging_dir)
            # 잔재 파일.
            with open(os.path.join(staging_dir, 'garbage.json'), 'w') as f:
                f.write('stale')
            c = _make_constants(release_dir, {'items': {'1': {}}})
            c.export()
            items_path = os.path.join(release_dir, 'items.json')
            assert os.path.exists(items_path)
            # 잔재 파일이 공개 디렉터리로 승격되지 않았는지 확인.
            assert not os.path.exists(os.path.join(release_dir, 'garbage.json'))

    def test_backup_copy_failure_preserves_release(self, monkeypatch):
        """[P1] 백업 copy 단계 실패 시 공개 파일은 원래 상태 그대로 보존된다.

        핵심 회귀: 이전 move 기반 백업은 두 번째 파일 이동 실패 시 첫 번째
        파일이 이미 공개에서 사라진 상태로 남았다. copy 기반에서는 공개 파일을
        옮기지 않으므로 백업 실패가 공개에 영향을 주지 않는다.
        """
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            # 두 컬렉션의 기존 공개 파일.
            with open(os.path.join(release_dir, 'items.json'), 'w') as f:
                json.dump({'old_items': True}, f)
            with open(os.path.join(release_dir, 'skills.json'), 'w') as f:
                json.dump({'old_skills': True}, f)

            # shutil.copy2 를 두 번째 호출에서 실패시킨다(백업 단계).
            original_copy2 = shutil.copy2
            copy_count = {'n': 0}

            def fail_second_copy(src, dst):
                copy_count['n'] += 1
                if copy_count['n'] >= 2:
                    raise OSError('simulated backup copy failure on 2nd file')
                return original_copy2(src, dst)

            monkeypatch.setattr('DB.shutil.copy2', fail_second_copy)
            c = _make_constants(release_dir, {
                'items': {'new_items': True},
                'skills': {'new_skills': True},
            })
            with pytest.raises(OSError):
                c.export()
            # 핵심: 두 공개 파일 모두 원래 구버전 그대로 보존되어야 한다.
            # (이전 move 구현에서는 items.json 이 공개에서 사라졌다.)
            assert os.path.exists(os.path.join(release_dir, 'items.json')), (
                'items.json must remain in release after backup copy failure '
                '(move-based backup corrupted release)'
            )
            assert os.path.exists(os.path.join(release_dir, 'skills.json')), (
                'skills.json must remain in release after backup copy failure'
            )
            with open(os.path.join(release_dir, 'items.json')) as f:
                assert json.load(f) == {'old_items': True}
            with open(os.path.join(release_dir, 'skills.json')) as f:
                assert json.load(f) == {'old_skills': True}

    def test_non_empty_stale_backup_aborts_run(self):
        """[P1] 비어 있지 않은 stale backup 디렉터리가 있으면 실행을 중단한다.

        이전 run 의 롤백이 실패해 수동 복구를 기다리는 상태일 수 있다.
        자동 삭제(rmtree)하면 유일한 구버전 사본이 사라지므로, 중단하고
        운영자에게 맡겨야 한다.
        """
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            backup_dir = release_dir + '.backup'
            os.makedirs(backup_dir)
            # 수동 복구 대기 중인 백업 원본.
            with open(os.path.join(backup_dir, 'items.json'), 'w') as f:
                json.dump({'recovery_copy': True}, f)
            c = _make_constants(release_dir, {'items': {'1': {}}})
            with pytest.raises(RuntimeError, match='non-empty backup'):
                c.export()
            # 백업 원본이 보존되어 있어야 한다(자동 삭제되지 않음).
            assert os.path.exists(os.path.join(backup_dir, 'items.json'))
            # 공개 파일은 건드리지 않았어야 한다.
            # (release_dir 는 원래 비어 있으므로 여전히 비어 있음)

    def test_empty_stale_backup_cleaned_safely(self):
        """빈 backup 잔재는 안전하게 제거된다(중단하지 않음)."""
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            os.makedirs(release_dir)
            backup_dir = release_dir + '.backup'
            os.makedirs(backup_dir)  # 빈 디렉터리.
            c = _make_constants(release_dir, {'items': {'1': {}}})
            # 빈 backup 은 RuntimeError 없이 정상 진행.
            c.export()
            items_path = os.path.join(release_dir, 'items.json')
            assert os.path.exists(items_path)

    def test_new_file_rollback_failure_preserves_backup(self, monkeypatch):
        """[P1 결함 2] 신규 파일 제거 롤백 실패 시 백업이 보존되어야 한다.

        핵심 회귀: 이전 os.replace(backup, release) 롤백은 백업을 소비(move)했다.
        기존 파일 복원이 끝나 백업이 비고, 이후 신규 파일 제거가 실패하면
        백업이 이미 비어 있어 stale backup 감지가 동작하지 않았다. 공개 릴리스는
        혼합(신규 파일만 신버전)인데 다음 실행이 중단되지 않는 심각한 결함.

        새 copy 기반 롤백은 백업을 소비하지 않고, 롤백 실패 시 .rollback-failed
        마커를 남겨 백업을 보존한다. 다음 실행은 비어 있지 않은 backup 감지로
        중단된다.

        시나리오: newcoll(신규) 승급 성공 -> items(기존) 승급 실패 ->
        롤백: items copy 복원(성공), newcoll 제거(실패 주입) ->
        백업에 .rollback-failed 마커 + 기존 백업 원본 보존.
        """
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            staging_dir = release_dir + '.staging'
            backup_dir = release_dir + '.backup'
            os.makedirs(release_dir)
            # items 기존 파일, newcoll 신규.
            with open(os.path.join(release_dir, 'items.json'), 'w') as f:
                json.dump({'old_items': True}, f)

            original_replace = os.replace
            promote_count = {'n': 0}
            # newcoll 승급(1번째) 성공, items 승급(2번째) 실패.
            def fail_second_promotion(src, dst):
                if os.path.dirname(src) == backup_dir:
                    return original_replace(src, dst)
                if os.path.dirname(dst) == release_dir:
                    promote_count['n'] += 1
                    if promote_count['n'] >= 2:
                        raise OSError('simulated promotion failure')
                return original_replace(src, dst)

            monkeypatch.setattr('DB.os.replace', fail_second_promotion)
            # newcoll 제거(os.remove)를 실패시킨다. 공개에 신버전 newcoll 이 남아
            # 혼합 상태가 되는데, 백업이 보존되어야 다음 실행이 중단된다.
            def fail_remove(path):
                if path.endswith('newcoll.json'):
                    raise OSError('simulated remove failure on new file')
                return os_remove_orig(path)

            os_remove_orig = os.remove
            monkeypatch.setattr('DB.os.remove', fail_remove)

            c = _make_constants(release_dir, {
                'newcoll': {'new_newcoll': True},
                'items': {'new_items': True},
            })
            with pytest.raises(OSError):
                c.export()
            assert promote_count['n'] >= 2
            # 핵심: 백업 디렉터리가 보존되어야 한다(마커 + 원본).
            assert os.path.isdir(backup_dir), (
                'backup must be preserved when new-file rollback fails '
                '(stale backup detection depends on it)'
            )
            assert os.path.exists(os.path.join(backup_dir, '.rollback-failed')), (
                '.rollback-failed marker must be written so the outer except '
                'preserves the backup'
            )
            # 기존 백업 원본도 copy 기반이므로 남아 있어야 한다.
            assert os.path.exists(os.path.join(backup_dir, 'items.json'))
            # 다음 실행이 비어 있지 않은 backup 을 감지해 중단하는지 확인.
            c2 = _make_constants(release_dir, {'newcoll': {'x': 1}, 'items': {'y': 2}})
            with pytest.raises(RuntimeError, match='non-empty backup'):
                c2.export()

    def test_successful_rollback_discards_backup_and_self_heals(
        self, monkeypatch,
    ):
        """[회귀] 롤백 완전 성공 시 백업을 폐기해 다음 실행이 자가 회복해야 한다.

        핵심 회귀: copy 기반 롤백은 백업을 소비하지 않으므로, 롤백이 완전히
        성공해도(릴리스 전부 구버전으로 일관 복구) 백업이 비어 있지 않게
        남았다. stale backup 감지가 이를 '롤백 실패'로 오인해, 일시적 승급
        실패 한 번에 이후 모든 실행이 RuntimeError 로 중단됐다.

        수정: _rollback_promotion 의 반환값으로 롤백 성공을 판단해, 성공 시
        승급 except 에서 백업을 폐기한다. 이 테스트는 승급 실패 + 롤백 성공
        후 백업이 사라지고, 다음 실행이 중단 없이 성공하는지 검증한다.
        """
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            backup_dir = release_dir + '.backup'
            os.makedirs(release_dir)
            with open(os.path.join(release_dir, 'items.json'), 'w') as f:
                json.dump({'old_items': True}, f)
            with open(os.path.join(release_dir, 'skills.json'), 'w') as f:
                json.dump({'old_skills': True}, f)

            original_replace = os.replace
            promote_count = {'n': 0}

            def fail_second_promotion(src, dst):
                if os.path.dirname(dst) == release_dir:
                    promote_count['n'] += 1
                    if promote_count['n'] >= 2:
                        raise OSError('simulated promotion failure on 2nd file')
                return original_replace(src, dst)

            monkeypatch.setattr('DB.os.replace', fail_second_promotion)
            c = _make_constants(release_dir, {
                'items': {'new_items': True},
                'skills': {'new_skills': True},
            })
            with pytest.raises(OSError):
                c.export()
            assert promote_count['n'] >= 2
            # 릴리스는 전부 구버전으로 일관 복구.
            with open(os.path.join(release_dir, 'items.json')) as f:
                assert json.load(f) == {'old_items': True}
            with open(os.path.join(release_dir, 'skills.json')) as f:
                assert json.load(f) == {'old_skills': True}
            # 핵심: 롤백이 완전 성공했으므로 백업은 폐기되어야 한다.
            assert not os.path.exists(backup_dir), (
                'backup must be discarded after a fully successful rollback; '
                'a leftover backup blocks every subsequent run (self-heal bug)'
            )
            # 다음 실행은 stale backup 중단 없이 정상 성공해야 한다.
            monkeypatch.setattr('DB.os.replace', original_replace)
            c2 = _make_constants(release_dir, {
                'items': {'new_items': True},
                'skills': {'new_skills': True},
            })
            c2.export()
            with open(os.path.join(release_dir, 'items.json')) as f:
                assert json.load(f) == {'new_items': True}

    def test_backup_copy_failure_discards_backup_and_self_heals(
        self, monkeypatch,
    ):
        """[회귀] 백업 copy 단계 실패 시에도 백업을 정리해 다음 실행이 재시도.

        백업 copy 단계(교체 진입 전) 실패는 공개 파일을 전혀 건드리지 않고,
        백업에는 copy 사본만 일부 남는다. 이 잔재를 정리하지 않으면 stale
        backup 감지가 다음 실행을 중단시킨다.
        """
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            backup_dir = release_dir + '.backup'
            os.makedirs(release_dir)
            with open(os.path.join(release_dir, 'items.json'), 'w') as f:
                json.dump({'old_items': True}, f)
            with open(os.path.join(release_dir, 'skills.json'), 'w') as f:
                json.dump({'old_skills': True}, f)

            original_copy2 = shutil.copy2
            copy_count = {'n': 0}

            def fail_second_copy(src, dst):
                copy_count['n'] += 1
                if copy_count['n'] >= 2:
                    raise OSError('simulated backup copy failure on 2nd file')
                return original_copy2(src, dst)

            monkeypatch.setattr('DB.shutil.copy2', fail_second_copy)
            c = _make_constants(release_dir, {
                'items': {'new_items': True},
                'skills': {'new_skills': True},
            })
            with pytest.raises(OSError):
                c.export()
            # 핵심: 부분 copy 잔재가 정리되어야 다음 실행이 중단되지 않는다.
            assert not os.path.exists(backup_dir), (
                'partially-populated backup from a pre-promotion failure must '
                'be cleaned up; release files are intact (copies only)'
            )
            monkeypatch.setattr('DB.shutil.copy2', original_copy2)
            c2 = _make_constants(release_dir, {
                'items': {'new_items': True},
                'skills': {'new_skills': True},
            })
            c2.export()
            with open(os.path.join(release_dir, 'skills.json')) as f:
                assert json.load(f) == {'new_skills': True}

    def test_rollback_failure_with_marker_write_failure_preserves_backup(
        self, monkeypatch,
    ):
        """[회귀] 롤백 실패 + 마커 작성 실패에도 백업이 보존되어야 한다.

        백업 보존 판단이 파일시스템 마커가 아니라 _rollback_promotion 의
        반환값(rollback_incomplete 플래그) 기반이므로, .rollback-failed 마커
        작성이 실패해도 백업은 삭제되지 않고 다음 실행이 중단되어야 한다.
        """
        import builtins
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            backup_dir = release_dir + '.backup'
            os.makedirs(release_dir)
            with open(os.path.join(release_dir, 'items.json'), 'w') as f:
                json.dump({'old_items': True}, f)

            original_replace = os.replace
            promote_count = {'n': 0}

            def fail_second_promotion(src, dst):
                if os.path.dirname(src) == backup_dir:
                    return original_replace(src, dst)
                if os.path.dirname(dst) == release_dir:
                    promote_count['n'] += 1
                    if promote_count['n'] >= 2:
                        raise OSError('simulated promotion failure')
                return original_replace(src, dst)

            monkeypatch.setattr('DB.os.replace', fail_second_promotion)
            # newcoll 제거 실패로 롤백을 불완전하게 만든다.
            os_remove_orig = os.remove

            def fail_remove(path):
                if path.endswith('newcoll.json'):
                    raise OSError('simulated remove failure on new file')
                return os_remove_orig(path)

            monkeypatch.setattr('DB.os.remove', fail_remove)
            # .rollback-failed 마커 작성도 실패시킨다.
            original_open = builtins.open

            def fail_marker_open(file, *args, **kwargs):
                if str(file).endswith('.rollback-failed'):
                    raise OSError('simulated marker write failure')
                return original_open(file, *args, **kwargs)

            monkeypatch.setattr('builtins.open', fail_marker_open)
            c = _make_constants(release_dir, {
                'newcoll': {'new_newcoll': True},
                'items': {'new_items': True},
            })
            with pytest.raises(OSError):
                c.export()
            assert promote_count['n'] >= 2
            # 핵심: 마커가 없어도 백업(구버전 유일 사본)이 보존되어야 한다.
            assert os.path.isdir(backup_dir), (
                'backup must be preserved via the in-process flag even when '
                'the .rollback-failed marker cannot be written'
            )
            assert os.path.exists(os.path.join(backup_dir, 'items.json'))
            assert not os.path.exists(
                os.path.join(backup_dir, '.rollback-failed')
            )
            # 다음 실행은 stale backup 감지로 중단.
            c2 = _make_constants(release_dir, {
                'newcoll': {'x': 1}, 'items': {'y': 2},
            })
            with pytest.raises(RuntimeError, match='non-empty backup'):
                c2.export()

    def test_all_new_empty_backup_rollback_failure_aborts_next_run(
        self, monkeypatch,
    ):
        """[P1 sentinel] all-new + 신규 파일 제거 실패 + 마커 작성 실패 겹침.

        핵심 회귀: 모든 출력 파일이 신규인 초기 배포(all-new 경계)에서는
        백업에 원본이 하나도 없다. 이 상태에서 승급 실패 → 롤백(신규 파일
        제거) 실패 → .rollback-failed 마커 작성 실패 까지 겹치면, sentinel
        없던 구버전에서는 백업이 완전히 비어 다음 실행이 침묵했다(불완전
        릴리스를 정상으로 취급). 사전 sentinel 은 첫 공개 승급 직전에 만들어
        있으므로, 이 모든 실패가 겹쳐도 백업이 비어 있지 않아 시작 가드가
        다음 실행을 중단한다.

        단언:
          (a) 백업 디렉터리가 비어 있지 않다(sentinel 존재).
          (b) 공개 릴리스는 혼합(newcoll.json 신버전이 남아 있음).
          (c) .rollback-failed 마커는 부재(마커 작성 실패 주입).
          (d) 2차 실행이 RuntimeError 로 중단.
          (e) 2차 실행 후 공개 파일은 무변경(staging 재생성과 무관).
        """
        import builtins
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            backup_dir = release_dir + '.backup'
            os.makedirs(release_dir)
            # release_dir 비어 있음 — 모든 출력 파일이 신규(all-new).

            original_replace = os.replace
            promote_count = {'n': 0}

            def fail_second_promotion(src, dst):
                # 롤백(backup->release) 호출은 정상 통과.
                if os.path.dirname(src) == backup_dir:
                    return original_replace(src, dst)
                # 공개 승급(staging->release) 만 카운트.
                if os.path.dirname(dst) == release_dir:
                    promote_count['n'] += 1
                    if promote_count['n'] >= 2:
                        raise OSError('simulated promotion failure')
                return original_replace(src, dst)

            monkeypatch.setattr('DB.os.replace', fail_second_promotion)

            # 신규 파일 제거(newcoll) 실패로 롤백을 불완전하게 만든다.
            os_remove_orig = os.remove

            def fail_remove(path):
                if path.endswith('newcoll.json'):
                    raise OSError('simulated remove failure on new file')
                return os_remove_orig(path)

            monkeypatch.setattr('DB.os.remove', fail_remove)

            # .rollback-failed 마커 작성도 실패시킨다(세 번 실패 겹침).
            original_open = builtins.open

            def fail_marker_open(file, *args, **kwargs):
                if str(file).endswith('.rollback-failed'):
                    raise OSError('simulated marker write failure')
                return original_open(file, *args, **kwargs)

            monkeypatch.setattr('builtins.open', fail_marker_open)

            c = _make_constants(release_dir, {
                'newcoll': {'new_newcoll': True},   # 신규
                'items': {'new_items': True},        # 신규
            })
            with pytest.raises(OSError):
                c.export()
            assert promote_count['n'] >= 2

            # (a) 백업이 비어 있지 않아야 한다 — sentinel 이 보장한다.
            assert os.path.isdir(backup_dir), (
                'backup must be preserved (in-process flag) even when marker '
                'write fails'
            )
            backup_listing = os.listdir(backup_dir)
            assert '.promotion-in-progress' in backup_listing, (
                'pre-promotion sentinel must be present so the backup dir is '
                'non-empty even in the all-new boundary'
            )
            # (c) .rollback-failed 마커는 없어야 한다(작성 실패 주입).
            assert '.rollback-failed' not in backup_listing, (
                'test precondition: .rollback-failed marker write must have '
                'failed'
            )
            # (b) 공개 릴리스는 혼합 — newcoll.json(신버전) 이 남아 있다.
            newcoll_release = os.path.join(release_dir, 'newcoll.json')
            assert os.path.exists(newcoll_release), (
                'precondition: new-file rollback failed, newcoll.json '
                'survives in release (mixed state)'
            )

            # (d) 2차 실행 전 공개 디렉터리 스냅샷.
            release_snapshot_before = sorted(os.listdir(release_dir))

            monkeypatch.setattr('DB.os.replace', original_replace)
            monkeypatch.setattr('DB.os.remove', os_remove_orig)
            monkeypatch.setattr('builtins.open', original_open)

            c2 = _make_constants(release_dir, {
                'newcoll': {'x': 1}, 'items': {'y': 2},
            })
            # (d) 시작 가드가 비어 있지 않은 backup(sentinel) 을 감지해 중단.
            with pytest.raises(RuntimeError, match='non-empty backup'):
                c2.export()

            # (e) 2차 실행 후 공개 파일은 무변경(시작 가드가 staging 재생성
            # 후 백업을 검사하므로 공개 디렉터리는 건드리지 않는다).
            release_snapshot_after = sorted(os.listdir(release_dir))
            assert release_snapshot_after == release_snapshot_before, (
                'release dir must be unchanged after the aborted 2nd run; '
                'only staging may have been touched'
            )

    def test_sentinel_creation_failure_aborts_before_any_promotion(
        self, monkeypatch,
    ):
        """[P1 sentinel] sentinel 생성 실패 시 공개 파일을 전혀 건드리지 않는다.

        sentinel 은 첫 공개 승급 직전(3b 단계) 조건이므로, 만들지 못하면
        승급 루프에 진입하지 않고 중단한다. 공개 파일은 무결하고, 백업은
        copy 사본만 일부 들어 있으므로 폐기되어 다음 실행이 재시도할 수 있다.
        """
        with tempfile.TemporaryDirectory() as d:
            release_dir = os.path.join(d, 'JSON_ktos')
            backup_dir = release_dir + '.backup'
            os.makedirs(release_dir)
            # 기존 공개 파일(구버전).
            with open(os.path.join(release_dir, 'items.json'), 'w') as f:
                json.dump({'old_items': True}, f)
            with open(os.path.join(release_dir, 'skills.json'), 'w') as f:
                json.dump({'old_skills': True}, f)

            release_before = {
                name: _read_json(os.path.join(release_dir, name))
                for name in ('items.json', 'skills.json')
            }

            import builtins
            original_open = builtins.open

            def fail_sentinel_open(file, *args, **kwargs):
                if str(file).endswith('.promotion-in-progress'):
                    raise OSError('simulated sentinel creation failure')
                return original_open(file, *args, **kwargs)

            monkeypatch.setattr('builtins.open', fail_sentinel_open)

            c = _make_constants(release_dir, {
                'items': {'new_items': True},
                'skills': {'new_skills': True},
            })
            # sentinel 생성 실패 -> 승급 진입 전 중단.
            with pytest.raises(OSError, match='simulated sentinel'):
                c.export()

            # 핵심: 공개 파일은 전혀 변경되지 않았다(혼합 상태 미발생).
            for name in ('items.json', 'skills.json'):
                assert _read_json(os.path.join(release_dir, name)) == \
                    release_before[name], (
                        '%s must be untouched when sentinel creation fails '
                        '(no partial promotion)' % name
                    )
            # 백업은 copy 사본만 있으므로 폐기되어야 한다(rollback_incomplete
            # 가 False 이므로 외부 except 의 elif 분기가 정리).
            assert not os.path.exists(backup_dir), (
                'backup must be discarded after a pre-promotion abort; '
                'release files are intact (copies only)'
            )

            # 다음 실행은 stale backup 중단 없이 정상 진행해야 한다.
            monkeypatch.setattr('builtins.open', original_open)
            c2 = _make_constants(release_dir, {
                'items': {'new_items': True},
                'skills': {'new_skills': True},
            })
            c2.export()
            assert _read_json(os.path.join(release_dir, 'items.json')) == \
                {'new_items': True}
            assert _read_json(os.path.join(release_dir, 'skills.json')) == \
                {'new_skills': True}


def _read_json(path):
    with open(path) as f:
        return json.load(f)


def _validate_json_file_import():
    """테스트 내에서 원본 _validate_json_file 을 가져오는 헬퍼."""
    import DB
    return DB._validate_json_file
