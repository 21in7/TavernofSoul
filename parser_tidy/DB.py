# -*- coding: utf-8 -*-
"""
Created on Mon Sep 20 09:20:20 2021
@author: Temperantia
everything goes here
temporary database from parse and make json database to be inserted to mysql
"""
from os.path import join, exists,getmtime
import os
import logging
import json
import shutil
import time
import sys

# The flat parser also runs directly from parser_tidy/ in regional cron jobs.
_django_project = join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'TavernofSoul')
if _django_project not in sys.path:
    sys.path.append(_django_project)
from ipfparser.contracts import load_release, validate_release


def _atomic_write_json(filepath, item):
    """JSON 을 임시 파일에 완전히 쓴 뒤 fsync + os.replace 로 원자 교체.

    직접 open(...,'w') 쓰기는 도중 예외 시 빈/부분 파일을 남길 수 있다.
    임시 파일을 같은 디렉터리에 만들어 완전히 기록한 뒤 교체하면,
    대상 파일은 항상 구버전 또는 신버전 중 하나로 남는다.
    """
    import tempfile
    dirname = os.path.dirname(filepath)
    tmp = filepath + '.tmp'
    with open(tmp, 'w') as f:
        f.write(json.dumps(item, allow_nan=False))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, filepath)


def _validate_json_file(filepath):
    """직렬화한 JSON 파일이 온전히 읽히는지 검증.

    staging 단계에서 쓰기 직후 읽어 보아 디스크 손상/잘림을 잡는다.
    """
    with open(filepath, 'r') as f:
        json.load(f)
def is_ascii(item):
    try:
        item.decode('ascii')
    except UnicodeDecodeError:
        return False
    return True

class ToS_DB():
    BASE_PATH_INPUT                 = None
    BASE_PATH_OUTPUT                = None
    STATIC_ROOT                     = None
    PATH_BUILD_ASSETS_ICONS         = None
    PATH_BUILD_ASSETS_MODELS        = None
    PATH_BUILD_ASSETS_IMAGES_MAPS   = None
    PATH_INPUT_DATA                 = None
    PATH_INPUT_DATA_LUA             = None
    transaltion_path                = None
    region                          = None
    CONVERTER_PATH                  = join("XAC", 'XAC2DAE.jar')
    
    EQUIPMENT_IES   = ['item_equip.ies',
                        'item_Equip_EP12.ies',
                        'item_Equip_EP13.ies',
                        'item_event_equip.ies',]
    EQUIPMENT_REINFORCE_IES = {'item_goddess_reinforce.ies' : 460, 
                'item_goddess_reinforce_470.ies' : 470,
                'item_goddess_reinforce_480.ies' : 480,
                'item_goddess_reinforce_490.ies' : 490,
                'item_goddess_reinforce_500.ies' : 500,
                'item_goddess_reinforce_510.ies' : 510,
                'item_goddess_reinforce_520.ies' : 520,
                'item_goddess_reinforce_530.ies' : 530,
                'item_goddess_reinforce_540.ies' : 540,
                # 550은 accessory 전용(5열: ClassID, BasicProp, AddAccAtk, BasicAccAtk, ClassName).
                # armor/weapon용 Lua 분기가 없으므로 material은 acc만 생성한다.
                # 정적 등록은 유지하되, 현재 지역에 파일이 없으면(twtos/ktest)
                # parse_goddess_EQ의 file_dict 게이트가 material 생성을 건너뛴다.
                'item_goddess_reinforce_550.ies' : 550,
                'item_goddess_reinforce_560.ies' : 560}
    # Declared order defines deterministic precedence for duplicate raw IDs.
    # Canonical recipe IDs are handled separately; this does not remove collisions.
    ITEM_IES = (
        "item.ies",
        'item_colorspray.ies',
        'item_gem.ies',
        'item_Equip.ies',
        'item_Equip_EP12.ies',
        'item_premium.ies',
        'item_quest.ies',
        'recipe.ies',
        'item_EP12.ies',
        'item_gem_relic.ies',
        'item_gem_bernice.ies',
        'item_GuildHousing.ies',
        'item_PersonalHousing.ies',
        'item_HiddenAbility.ies',
        'item_event.ies', 
        'item_event_Equip.ies', 
        'item_EP13.ies',
        'item_Equip_EP13.ies',
        'item_Reputation.ies',
        )

    
    file_dict = {}
    
    
    data_build = ['assets_icons', 'maps', 'maps_by_name', 'maps_by_position']
        
    data = {
       'dictionary'          : {},
       'items'               : {},
       'items_by_name'       : {},
       'cubes_by_stringarg'  : {},
       'equipment_sets'      : {},
       'item_type'           : {},
       'equipment_sets_by_name' : {},
       'assets_icons'        : {},
       'jobs'                : {},
       'jobs_by_name'        : {},
       'attributes'          : {},
       'attributes_by_name'  : {},
       'skills'              : {},
       'skills_by_name'      : {},
       'monsters'            : {},
       'monsters_by_name'    : {},
       'item_monster'        : [],
       'npcs'                : {},
       'npcs_by_name'        : {},
       'maps'                : {},
       'maps_by_name'        : {},
       'maps_by_position'    : {},
       'map_item'            : [],
       'map_npc'             : [],
       'map_item_spawn'      : [],
       'skill_mon'           : {},
       'equipment_grade_ratios' : {},
       'buff'                : {},
       'achievements'        : {},
       'charxp'              : {},
       'petxp'               : {},
       'assisterxp'          : {},
       'goddess_reinf_mat'   : {},
       'goddess_reinf'       : {},
       # P0-10: 드롭 provenance. data 는 클래스 수준 mutable 이라 monsters 와
       # maps 양쪽이 공유하므로 build() 에서 새 객체로 교체한다.
       'unresolved_drops'    : [],   # items_by_name 에 없는 드롭 참조 (raw, 문맥 보존)
       'build_provenance'    : {},   # 드롭 소스 결정: source_region/input_version/fallback_reason
       }
    
    
    def build(self, region, base_path):
        project_root = os.path.dirname(base_path)
        region = region.lower()
        self.region                          = region
        self.BASE_PATH_INPUT                 = join(project_root, "TavernofSoul", "JSON_{}".format(region))
        self.BASE_PATH_OUTPUT                = join(project_root, "TavernofSoul", "JSON_{}".format(region))
        #self.STATIC_ROOT                     = '/home/tavp7339/www/itos/static'
        self.STATIC_ROOT                     = join(project_root, "TavernofSoul", "staticfiles_itos")
        self.PATH_BUILD_ASSETS_ICONS         = join (self.STATIC_ROOT,"icons")
        self.PATH_BUILD_ASSETS_IMAGES_MAPS   = join (self.STATIC_ROOT,"maps")
        self.PATH_BUILD_ASSETS_MODELS        = join (self.STATIC_ROOT,"models")
        
        try:
            os.mkdir(self.PATH_BUILD_ASSETS_ICONS) 
        except:
            pass
        try:
            os.mkdir(self.PATH_BUILD_ASSETS_IMAGES_MAPS)
        except:
            pass
        try:
            os.mkdir(self.PATH_BUILD_ASSETS_MODELS) 
        except:
            pass
        
        self.PATH_INPUT_DATA                 = join(project_root,'{}_unpack'.format(region))
        self.PATH_INPUT_DATA_LUA             = join(project_root,'{}_unpack'.format(region))
        if region == 'itos':
            self.transaltion_path                = join (project_root,"Translation", 'English')
        elif region == 'jtos':
            self.transaltion_path                = join (project_root,"Translation", 'Japanese')
        elif region == 'twtos':
            self.transaltion_path                = join (project_root,"Translation", 'Taiwanese')
        else:
            self.transaltion_path                = "."
            
        self.directoryDictionary(self.PATH_INPUT_DATA)

        # P0-10: data 는 클래스 수준 mutable 이라 이전 빌드/지역의
        # unresolved_drops, build_provenance 가 잔존할 수 있다.
        # monsters·maps 양쪽이 append/갱신하므로 빌드 시작에 새 객체로 교체한다.
        self.data['unresolved_drops'] = []
        self.data['build_provenance'] = {}
        
        
        for i in self.data_build:
            path = "%s.json"%(i)
            path = join(self.BASE_PATH_INPUT, path)
            self.data[i] = self.importJSON(path)
        
    def _validate_release(self, version_payload):
        data = dict(self.data)
        if version_payload is not None:
            data['version'] = version_payload
        validate_release(data, require_version=version_payload is not None)

    def _validate_staged_release(self, directory, version_payload):
        load_release(directory, require_version=version_payload is not None)

    def export(self, version_payload=None):
        """모든 data 컬렉션을 임시 staging 디렉터리에 완전히 직렬화하고
        검증한 뒤, 전체 성공 시에만 공개 파일을 백업·롤백으로 일괄 교체한다.

        version_payload 가 주어지면 version.json 도 같은 트랜잭션에 포함한다.
        이렇게 하면 공개 JSON 과 version.json 이 항상 함께 승급되어, JSON 만
        신버전이고 version.json 은 구버전인 혼합 상태가 발생하지 않는다.
        parser_version.csv 는 SCRIPT_DIR(별도 디렉터리)에 있어 이 트랜잭션에
        포함되지 않는다 — caller(main.py) 가 version.json 보다 먼저 갱신하고,
        시작 조건의 불일치 검사가 재시도를 보장한다.

        PROFILING_REVIEW P0 (설계 후 범위): 이전 export() 는 공개 디렉터리의
        각 JSON 파일을 순차적으로 직접 덮어써서, 중간 실패 시 이미 쓴 파일만
        새 패치인 혼합 결과가 남았다. 이제 입력 디렉터리와 분리된 형제
        staging 디렉터리(JSON_<region>.staging/)에 모든 JSON 을 먼저 쓰고,
        각 파일을 읽어 검증한 뒤, 전부 성공했을 때만 공개 파일을 교체한다.

        백업·롤백의 안전성 보장:
          - 백업은 copy(공개 파일을 move 로 옮기지 않음). 백업 단계에서 실패해도
            공개 파일은 전혀 건드리지 않은 상태로 남는다.
          - 교체는 os.replace(staging, release) 로 파일별 원자 덮어쓰기.
            교체 도중 하나라도 실패하면 백업에서 공개 파일을 전부 구버전으로
            되돌린다(백업 원본이 없는 신규 파일은 공개에서 제거).
          - 백업 폐기 기준: 전체 교체 성공 시, 그리고 롤백이 완전히 성공해
            공개 릴리스가 구버전으로 일관 복구된 경우에도 폐기한다(다음 실행
            자가 회복). 롤백이 불완전할 때만 백업을 보존하고, 다음 실행은
            비어 있지 않은 backup 감지로 중단되어 운영자가 개입한다.
          - 사전 sentinel: 첫 공개 승급 직전(3b 단계)에 backup 에
            .promotion-in-progress sentinel 을 만든다. 이것이 "비어 있지 않은
            backup 감지"의 구조적 보장이다 — all-new 경계(백업 원본이 하나도
            없는 초기 배포)에서도, 롤백 실패 + 롤백 마커 작성 실패가 겹쳐도
            sentinel 이 있어 시작 가드가 다음 실행을 중단한다. sentinel 생성
            실패 시에는 공개 파일을 전혀 건드리지 않은 채 중단한다.
            보장 범위는 프로세스 수준 실패(예외·롤백 실패·마커 실패·SIGKILL)
            까지이며, 전원 단절 수준(OS 페이지 캐시 미반영, fsync 미사용)은
            보장하지 않는다.
          - BASE_PATH_OUTPUT 이 고정 디렉터리를 직접 가리키므로 디렉터리 포인터
            단위 교체(symlink)는 도입하지 않는다. 따라서 교체 진행 중에는 독자가
            일시적으로 신구 혼합 상태를 관찰할 수 있으나, 최종 상태는 전부 신버전
            또는 전부 구버전 둘 중 하나로만 귀결된다. importer 는 cron 이 parser
            전체 성공 후에만 실행되므로 혼합 관찰 창에 도달하지 않는다.
        """
        # Reject domain errors before creating staging or touching any old release.
        self._validate_release(version_payload)
        release_dir = self.BASE_PATH_OUTPUT
        staging_dir = release_dir.rstrip('/') + '.staging'
        backup_dir = release_dir.rstrip('/') + '.backup'

        # 이전 staging 잔재가 있으면 폐기하고 깨끗하게 시작.
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
        os.makedirs(staging_dir, exist_ok=True)

        # stale backup 보존: 정상 경로(성공·롤백 성공·교체 전 실패)는 backup 을
        # 스스로 폐기하므로, 비어 있지 않은 backup 이 남아 있다는 것은 이전 run 의
        # 롤백이 불완전해 수동 복구를 기다리는 상태라는 뜻이다. 자동 삭제하면
        # 유일한 구버전 사본이 사라지므로, 실행을 중단하고 운영자에게 맡긴다.
        if os.path.isdir(backup_dir) and os.listdir(backup_dir):
            raise RuntimeError(
                'non-empty backup dir exists at %s — previous rollback may have '
                'failed; inspect and recover manually before re-running'
                % backup_dir
            )
        # 비어 있는 backup 잔재는 안전하게 제거.
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)

        written = []
        rollback_incomplete = False
        try:
            # 1) 모든 컬렉션을 staging 에 원자적으로 직렬화.
            for key in self.data:
                filename = "{}.json".format(key)
                staging_path = join(staging_dir, filename)
                _atomic_write_json(staging_path, self.data[key])
                written.append((key, filename, staging_path))

            # 1b) version_payload 가 주어지면 version.json 도 같은 staging 에 쓴다.
            #     이렇게 하면 공개 JSON 승급과 version.json 승급이 같은 트랜잭션에
            #     묶여 JSON 만 신버전이고 version.json 은 구버전인 혼합을 방지한다.
            if version_payload is not None:
                version_filename = 'version.json'
                version_staging = join(staging_dir, version_filename)
                _atomic_write_json(version_staging, version_payload)
                written.append(('__version__', version_filename, version_staging))

            # 2) 각 파일이 온전히 역직렬화되는지 검증.
            for key, filename, staging_path in written:
                _validate_json_file(staging_path)
            self._validate_staged_release(staging_dir, version_payload)

            # 3) 교체 전 기존 공개 파일을 백업으로 복사(copy).
            #    copy 를 쓰므로 백업 단계 실패 시 공개 파일은 원래 상태 그대로다.
            #    (이전 move 구현은 백업 이동 실패 시 공개 파일이 사라졌다.)
            os.makedirs(backup_dir, exist_ok=True)
            for key, filename, staging_path in written:
                release_path = join(release_dir, filename)
                backup_path = join(backup_dir, filename)
                if os.path.exists(release_path):
                    shutil.copy2(release_path, backup_path)

            # 3b) 첫 공개 승급 직전에 백업 디렉터리에 sentinel 을 만든다.
            #     이것이 핵심 안전 조건이다: 불완전 상태(롤백 실패)에서는 백업이
            #     구조적으로 비어 있을 수 없게 한다. all-new 경계(백업 원본이
            #     하나도 없는 초기 배포)에서 특히 중요하다 — sentinel 이 없으면
            #     마커 작성 실패 겹침 시 다음 실행이 침묵하고 불완전 릴리스를
            #     정상으로 취급한다. sentinel 을 승급 "전" 조건으로 두었으므로,
            #     만들지 못하면 공개 파일을 전혀 건드리지 않은 채 중단한다(혼합
            #     상태 자체가 발생하지 않는다). 사후 마커 방식과 달리 승급 루프
            #     도중 SIGKILL(예외 핸들러가 아예 못 도는 강제 종료)에도 백업이
            #     비어 있지 않음이 보장된다.
            #     보장 범위: 프로세스 수준 실패(예외·롤백 실패·마커 실패·SIGKILL)
            #     까지. 전원 단절 수준의 영속성(OS 페이지 캐시 미반영)은 보장하지
            #     않는다(fsync 미사용, cron 배치 특성상 범위 한정). 강제 종료 후
            #     공개 파일이 무결해도 다음 실행이 중단되는 false positive 는
            #     안전 방향 트레이드오프로 감수한다.
            sentinel_path = join(backup_dir, '.promotion-in-progress')
            try:
                with open(sentinel_path, 'w') as f:
                    f.write(
                        'promotion was in progress at %s\n'
                        'target files (restore from backup copies where '
                        'present; files ABSENT from backup are NEW and must '
                        'be removed if they survived in release):\n'
                        % time.strftime('%Y-%m-%dT%H:%M:%S%z')
                    )
                    for key, filename, staging_path in written:
                        f.write('  %s\n' % filename)
                    f.write(
                        '\nmanual recovery MAY be required if the promotion '
                        'did not complete atomically. if release files are '
                        'all old/intact, this sentinel may be a false '
                        'positive from a hard kill - inspect before '
                        'recovering.\n'
                    )
            except OSError:
                # sentinel 못 만들면 승급을 시작하지 않는다. 공개 파일은 아직
                # 전혀 변경되지 않았으므로 외부 except 가 백업(copy 사본뿐)을
                # 폐기하고 무결 상태로 재시도할 수 있다.
                logging.error(
                    'failed to create pre-promotion sentinel at %s; aborting '
                    'before any public file is touched', sentinel_path,
                )
                raise

            # 4) staging 파일들을 공개 위치로 교체.
            #    os.replace 는 대상이 존재해도 원자적으로 덮어쓴다. 한 건이라도
            #    실패하면 _rollback_promotion 으로 공개 릴리스를 전부 구버전으로.
            for key, filename, staging_path in written:
                release_path = join(release_dir, filename)
                try:
                    os.replace(staging_path, release_path)
                except Exception:
                    rollback_incomplete = self._rollback_promotion(
                        written, backup_dir,
                    )
                    if not rollback_incomplete:
                        # 롤백 완전 성공: 공개 릴리스가 전부 구버전으로 일관
                        # 복구됐고 백업 사본은 더 이상 유일본이 아니다. 여기서
                        # 폐기해야 다음 실행이 stale backup 중단 없이 자가
                        # 회복한다. 판단은 파일시스템 마커가 아니라 반환값
                        # 기반이라, 마커 작성 실패 시에도 보존이 유지된다.
                        shutil.rmtree(backup_dir, ignore_errors=True)
                    raise

            # 5) 전체 교체 성공 — 백업·staging 폐기.
            shutil.rmtree(backup_dir, ignore_errors=True)
            shutil.rmtree(staging_dir, ignore_errors=True)
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            # backup 보존 정책:
            #   - 롤백이 불완전하면(rollback_incomplete, 마커 작성 실패 포함)
            #     백업을 절대 삭제하지 않는다(수동 복구 대기). 마커가 아닌
            #     반환값 기반 플래그이므로 마커 작성 실패에도 안전하다.
            #   - 그 외(직렬화/검증/백업 copy 단계 실패, 롤백 성공 후 재도달)는
            #     공개 파일이 무결하고 백업은 copy 사본일 뿐이므로 정리한다.
            #     여기서 정리해야 다음 실행이 stale backup 중단 없이 재시도한다.
            if rollback_incomplete:
                logging.error(
                    'rollback was incomplete; backup preserved at %s '
                    'for manual recovery', backup_dir,
                )
            elif os.path.isdir(backup_dir):
                shutil.rmtree(backup_dir, ignore_errors=True)
            raise

    @staticmethod
    def _rollback_promotion(written, backup_dir):
        """교체 도중 실패 시 공개 릴리스를 전부 구버전으로 되돌린다.

        written 의 각 (key, filename, staging_path) 에 대해:
          - 백업에 원본이 있으면 copy2 로 공개 위치에 덮어쓴다(구버전 복원).
            copy 를 쓰므로 백업 원본은 소비되지 않고 백업 디렉터리에 남는다.
          - 백업에 원본이 없으면(신규 파일) 공개 위치에서 삭제한다.
            교체 도중 실패했으므로 신규 파일이 신버전으로 남으면 안 된다.

        반환: 복구가 하나라도 실패했으면 True(불완전), 전부 성공했으면 False.
        호출자(export)는 True 면 백업을 보존하고(다음 실행이 stale backup
        감지로 중단), False 면 백업을 폐기해 자가 회복한다. 판단은 이 반환값
        기반이므로 마커 작성 실패에도 보존이 유지된다.

        불완전 시 백업 디렉터리에 .rollback-failed 마커도 남긴다 — 운영자가
        백업 디렉터리만 보고도 수동 복구 대기 상태임을 알 수 있게 하는
        보조 표시다.

        역할 구분: sentinel(.promotion-in-progress) = 승급이 진행 중이었음을
        나타내는 "승급 전 조건"으로, export 의 3b 단계에서 첫 공개 승급 직전에
        만들어진다(all-new 에서도 백업이 비어 있지 않음을 보장). 이 마커는
        롤백마저 실패했을 때 보조로 남는 "롤백 실패" 표시다. sentinel 이 이미
        있으므로 이 마커 작성이 실패해도 백업은 비어 있지 않아 시작 가드가
        다음 실행을 중단한다.
        (이전 os.replace(backup, release) 구현은 백업을 소비해 버리므로
        신규 파일 제거 실패 시 백업이 비어 staleness 감지가 동작하지 않았다.)
        """
        release_dir = backup_dir[:-len('.backup')] if backup_dir.endswith('.backup') \
            else backup_dir + '.release'
        rollback_failed = False
        for key, filename, staging_path in written:
            backup_path = join(backup_dir, filename)
            release_path = join(release_dir, filename)
            if os.path.exists(backup_path):
                try:
                    # copy2 로 백업 원본을 보존하며 공개 위치를 구버전으로 덮어쓴다.
                    shutil.copy2(backup_path, release_path)
                except OSError:
                    logging.error(
                        'rollback failed for %s; backup preserved at %s',
                        release_path, backup_dir,
                    )
                    rollback_failed = True
            else:
                # 신규 파일: 공개 위치에 신버전이 올라갔을 수 있으므로 제거.
                try:
                    if os.path.exists(release_path):
                        os.remove(release_path)
                except OSError:
                    logging.error(
                        'rollback cleanup failed for %s; backup preserved at %s',
                        release_path, backup_dir,
                    )
                    rollback_failed = True
        if rollback_failed:
            # 마커를 남겨 외부 except 가 백업을 보존하게 한다. copy 기반이므로
            # 백업 원본은 여전히 온전하다.
            try:
                with open(join(backup_dir, '.rollback-failed'), 'w') as f:
                    f.write('rollback incomplete; manual recovery required\n')
            except OSError:
                # 마커 작성이 실패해도 백업은 비어 있지 않다 — sentinel
                # (.promotion-in-progress) 이 승급 전(3b 단계)에 이미 만들어져
                # 있으므로, all-new 경계에서도 시작 가드가 다음 실행을 중단한다.
                logging.error(
                    'failed to write rollback marker; backup still preserved '
                    'at %s (sentinel guarantees non-empty)', backup_dir,
                )
            logging.error(
                'rollback incomplete; backup preserved at %s for manual recovery',
                backup_dir,
            )
        return rollback_failed


    def export_one(self, file):
        i = file
        path = "{}.json".format(i)
        # 단일 파일도 원자 교체로 직접 기록(현재는 사용되지 않음).
        _atomic_write_json(join(self.BASE_PATH_OUTPUT, path), self.data[i])
    
    def reverseDict(self, dicts):
        a = {}
        for i in dicts.keys():
            a [dicts[i]] =  i
        return a
    
    """
    utility functions
    """
    
        
    def directoryDictionary(self, base_dir):
        #os.path.getmtime(path)
        items = os.listdir(base_dir)
        for i in items:
            path = os.path.join(base_dir, i)
            if os.path.isdir(path):
                self.directoryDictionary(path)
            else:
                il = i.lower()
                time        = os.path.getmtime(path)
                mini_dict   ={'time': time, 'name' : i, 'path': path}
                if il in self.file_dict and time > self.file_dict[il]['time']:
                    self.file_dict[il] = mini_dict
                else:
                    self.file_dict[il] = mini_dict
                
    
    def translate(self, key):
        if self.transaltion_path == None:
            return self.data['dictionary'][key]
        key = key.replace('"', '')
        if (self.data['dictionary']=={}):
            logging.debug('dictionary is empty')
            return key
        if not self.data['dictionary']:
            return key
    
        if key != '' and key not in self.data['dictionary']:
            #logging.warn('Missing translation for key: %s', key)
            return key
        if key == '':
            return ''
            
        return self.data['dictionary'][key]
    
        
    
    def parse_entity_icon(self,icon):
        icon = icon.lower()
        icon_found = None
    
        if icon == '':
            return None
    
        if icon in self.data['assets_icons']:
            icon_found = icon
        elif 'icon_' + icon in self.data['assets_icons']:
            icon_found = 'icon_' + icon
        elif icon +'_f' in self.data['assets_icons']:
            icon_found = icon + '_f'
        elif icon + '_m' in self.data['assets_icons']:
            icon_found = icon + '_m'
    
        if icon_found is not None:
            #constants.assets_icons_used.append(icon_found)
            return self.data['assets_icons'][icon_found]
        else:
            # Note: there's nothing we can do about this :'(
            #logging.debug('Missing icon: %s', icon)
            return icon

 

    def printJSON(self, item, file):
        file_input = join (self.BASE_PATH_INPUT, file)
        #file_output = join(self.BASE_PATH_OUTPUT, file)
        with open(file_input, "w") as f:
            json.dump(item,f)
        #shutil.copy(file_input, file_output)
        
        
    def importJSON(self,  file):
        
        if not exists(file):
            logging.warn("not exists{}".format(file))
            return {}
        try:
            with open(file, "r") as f:
                data = json.load(f)
        except:
            logging.error("error in importing file {}".format(file))
            return {}
        return data
    
    def getNPCbyName(self, name):
        if name in self.data['monsters_by_name']:
            return self.data['monsters_by_name'][name], 'mon'
        elif name in self.data['npcs_by_name']:
            return self.data['npcs_by_name'][name], 'npc'
        else:
            return None
    def build_monster_skill_index(self):
        """Snapshot completed monster parsing in insertion order.

        Rebuild after editing SkillType or IDs in place. parse_skill_mon does this
        at its boundary, including when parsing again on the same DB instance.
        """
        monsters = self.data['monsters']
        index = {}
        seen = {}
        for mon in monsters.values():
            if 'SkillType' not in mon:
                logging.warning("skill type not in mon {}".format(mon['$ID']))
                continue
            key = mon['SkillType'].lower()
            mid = mon['$ID']
            ids = index.setdefault(key, [])
            key_seen = seen.setdefault(key, set())
            if mid not in key_seen:
                key_seen.add(mid)
                ids.append(mid)
        self._monster_skill_source = monsters
        self._monster_skill_source_size = len(monsters)
        self._monster_skill_index = index

    def getMonbySkill(self, skill):
        monsters = self.data['monsters']
        if (getattr(self, '_monster_skill_source', None) is not monsters or
                getattr(self, '_monster_skill_source_size', None) != len(monsters)):
            self.build_monster_skill_index()
        key = skill.lower()
        matches = self._monster_skill_index.get(key)
        if not matches:
            matches = self._monster_skill_index.get('mon_' + key, [])
        # Callers receive their own list, as with the former linear scan.
        return list(matches)

"""
enums
"""
    
class TOSElement():
    DARK = 'Dark'
    EARTH = 'Earth'
    FIRE = 'Fire'
    HOLY = 'Holy'
    ICE = 'Ice'
    LIGHTNING = 'Lightning'
    MELEE = 'None'
    POISON = 'Poison'
    SOUL = 'Soul'
    none = 'None'

    @staticmethod
    def to_string(value):
        if value == None:
            return 'None'
        return {
            TOSElement.DARK: 'Dark',
            TOSElement.EARTH: 'Earth',
            TOSElement.FIRE: 'Fire',
            TOSElement.HOLY: 'Holy',
            TOSElement.ICE: 'Ice',
            TOSElement.LIGHTNING: 'Lightning',
            TOSElement.MELEE: 'None',
            TOSElement.POISON: 'Poison',
            TOSElement.SOUL: 'Soul',
            'None':'None'
        }[value]

    @staticmethod
    def value_of(string):
        if string == None:
            return 'None'.upper()
        return {
            'DARK': TOSElement.DARK,
            'EARTH': TOSElement.EARTH,
            'FIRE': TOSElement.FIRE,
            'HOLY': TOSElement.HOLY,
            'ICE': TOSElement.ICE,
            'LIGHTING': TOSElement.LIGHTNING,
            'LIGHTNING': TOSElement.LIGHTNING,
            'MELEE': TOSElement.MELEE,
            'POISON': TOSElement.POISON,
            'SOUL': TOSElement.SOUL,
            '': None,
            'None':'None'
        }[string.upper()]


class TOSAttackType():
    BUFF = 'Buff'
    MAGIC = 'Magic'
    MISSILE = 'Missile'
    MISSILE_BOW = 'Bow'
    MISSILE_CANNON = 'Cannon'
    MISSILE_GUN = 'Gun'
    MELEE = 'Physical'
    MELEE_PIERCING = 'Piercing'
    MELEE_SLASH = 'Slash'
    MELEE_STRIKE = 'Strike'
    MELEE_THRUST = 'Thrust'
    TRUE = 'True Damage'
    UNKNOWN = ''
    RESPONSIVE = "Responsive"
    @staticmethod
    def to_string(value):
        return {
            TOSAttackType.BUFF: 'Buff',
            TOSAttackType.MAGIC: 'Magic',
            TOSAttackType.MISSILE: 'Missile',
            TOSAttackType.MISSILE_BOW: 'Bow',
            TOSAttackType.MISSILE_CANNON: 'Cannon',
            TOSAttackType.MISSILE_GUN: 'Gun',
            TOSAttackType.MELEE: 'Physical',
            TOSAttackType.MELEE_PIERCING: 'Piercing',
            TOSAttackType.MELEE_SLASH: 'Slash',
            TOSAttackType.MELEE_STRIKE: 'Strike',
            TOSAttackType.MELEE_THRUST: 'Thrust',
            TOSAttackType.TRUE: 'True Damage',
            TOSAttackType.UNKNOWN: '',
            TOSAttackType.RESPONSIVE: "Responsive",
        }[value]

    @staticmethod
    def value_of(string):
        return {
            'RESPONSIVE' : TOSAttackType.RESPONSIVE, #whats this?
            'ARIES': TOSAttackType.MELEE_PIERCING,
            'ARROW': TOSAttackType.MISSILE_BOW,
            'CANNON': TOSAttackType.MISSILE_CANNON,
            'GUN': TOSAttackType.MISSILE_GUN,
            'HOLY': None,  # HotFix: obsolete skill #40706 uses it
            'MAGIC': TOSAttackType.MAGIC,
            'MELEE': TOSAttackType.MELEE,
            'MISSILE': TOSAttackType.MISSILE,
            'SLASH': TOSAttackType.MELEE_SLASH,
            'STRIKE': TOSAttackType.MELEE_STRIKE,
            'THRUST': TOSAttackType.MELEE_THRUST,
            'TRUEDAMAGE': TOSAttackType.TRUE,
            '': TOSAttackType.UNKNOWN
        }[string.upper()]
