# -*- coding: utf-8 -*-
"""드롭 데이터(ies_drop.ipf) 소스 결정과 provenance 기록을 담당한다.

P0-10(PROFILING_REVIEW.md "지역별 드롭")의 일환으로 기존 ``monsters.py`` 와
``maps.py`` 에 하드코딩된 ``../itos_unpack`` 상대 경로를 대체한다.
"""
import logging
import os

log = logging.getLogger("parser.drop_source")

# 드롭 원본(ipf)이 존재하는 지역. 2026-07 현재 iTOS 에만 ies_drop.ipf 가
# 존재한다(2,248 파일). 다른 지역이 자체 드롭 데이터를 배포하기 시작하면
# 파일 단위 fallback(resolve_drop_file)으로 확장한다.
DROP_SOURCE_REGION = 'itos'


def _project_root(constants):
    """PATH_INPUT_DATA(<project_root>/<region>_unpack)에서 project_root 유도."""
    return os.path.dirname(os.path.normpath(constants.PATH_INPUT_DATA))


def _read_revision(project_root):
    """project_root/downloader/revision.csv 를 {region: version} 으로 읽는다.

    절대경로로 읽어 CWD 에 독립적이다. 실패 시 빈 dict(예외 없음).
    """
    path = os.path.join(project_root, 'downloader', 'revision.csv')
    rev = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                if len(parts) >= 2 and parts[0]:
                    rev[parts[0].strip().lower()] = parts[1].strip()
    except (IOError, OSError):
        log.debug('revision.csv not readable at %s', path)
    return rev


def get_drop_source(constants):
    """드롭 소스(ies_drop.ipf)의 경로와 provenance를 **데이터셋 단위**로 결정한다.

    fallback 단위는 데이터셋(디렉터리) 단위다: iTOS ies_drop.ipf 디렉터리가
    존재하면 모든 하위 파일(몬스터별 .ies, zonedrop, dropgroup)을 iTOS 에서
    읽는다. 개별 파일이 iTOS 에 없고 현재 지역에만 있어도 보조 소스를 쓰지
    않는다. (2026-07 현재 ies_drop.ipf 는 iTOS 에만 존재하므로 파일 단위
    fallback 은 실행 불가능한 분기다. 지역별 자체 드롭 데이터가 생기면
    ``resolve_drop_file()`` 계약으로 확장한다.)

    반환 dict::

        {'drop_ipf'        : <abs path>|None,
         'source_region'   : 'itos'|<region>,
         'input_version'   : str|None,
         'fallback_reason' : str|None}

    - iTOS 우선 → 현재 지역 PATH_INPUT_DATA/ies_drop.ipf → 둘 다 없으면 drop_ipf=None
    - input_version 은 revision.csv 기반 best-effort 값이다. revision.csv 는
      patch_process() 후 갱신되지만 unpack subprocess 는 check 없이 실행되므로
      언팩 성공이 검증된 매니페스트가 아니다.
    """
    project_root = _project_root(constants)
    revision = _read_revision(project_root)

    itos_ipf = os.path.join(project_root,
                            '{}_unpack'.format(DROP_SOURCE_REGION),
                            'ies_drop.ipf')
    current_ipf = os.path.join(constants.PATH_INPUT_DATA, 'ies_drop.ipf')

    if os.path.isdir(itos_ipf):
        src_region = DROP_SOURCE_REGION
        drop_ipf = itos_ipf
        if constants.region.lower() != DROP_SOURCE_REGION:
            reason = ('ies_drop.ipf absent for region {!r}; falling back to {}'
                      .format(constants.region, DROP_SOURCE_REGION))
        else:
            reason = None
    elif os.path.isdir(current_ipf):
        # 미래: 현재 지역이 자체 드롭 데이터를 배포하는 경우.
        src_region = constants.region
        drop_ipf = current_ipf
        reason = None
    else:
        src_region = None
        drop_ipf = None
        reason = 'ies_drop.ipf not found in any region'

    input_version = revision.get(src_region) if src_region else None

    return {
        'drop_ipf': drop_ipf,
        'source_region': src_region,
        'input_version': input_version,
        'fallback_reason': reason,
    }


def list_drop_subdir(drop_ipf, subdir):
    """drop_ipf/<subdir> 의 파일 목록과 case-insensitive 매핑을 반환.

    반환: ``{'dir': <abs path>|None, 'ci': {lowercase_name: actual_name}}``
    디렉터리가 없으면 ``{'dir': None, 'ci': {}}`` (예외 없음).
    """
    sub_path = os.path.join(drop_ipf, subdir) if drop_ipf else None
    if not sub_path or not os.path.isdir(sub_path):
        return {'dir': None, 'ci': {}}
    ci = {}
    try:
        for name in os.listdir(sub_path):
            ci[name.lower()] = name
    except (IOError, OSError):
        return {'dir': None, 'ci': {}}
    return {'dir': sub_path, 'ci': ci}
