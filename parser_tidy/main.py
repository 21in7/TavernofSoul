# -*- coding: utf-8 -*-
"""
Created on Thu Sep 23 11:17:20 2021
@author: Temperantia
"""

from DB import ToS_DB as constants
from os.path import join
import os

import logging
import translation
import jobs
import skills
import attributes
import luautil
import asset
import json
import items
import monsters
import maps
import buff
import vaivora
import sys
import misc
import skill_bytool
import parse_xac
from item_static import add_item_static
import csv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

region = "ktos"

def _atomic_write_text(filepath, text):
    """임시 파일에 완전히 쓴 뒤 fsync + os.replace 로 원자 교체.

    직접 open(...,'w') 쓰기는 도중 예외 시 빈/부분 파일을 남길 수 있다.
    임시 파일을 같은 디렉터리에 만들어 완전히 기록한 뒤 교체하면,
    대상 파일은 항상 구버전 또는 신버전 중 하나로 남는다.
    """
    dirname = os.path.dirname(filepath)
    tmp = filepath + '.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, filepath)

def print_version(filename, data):
    """parser_version.csv 를 원자 교체로 기록."""
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    for key in data:
        w.writerow([key, data[key]])
    filepath = os.path.join(SCRIPT_DIR, filename)
    _atomic_write_text(filepath, buf.getvalue())

def read_version(filename):
    rev = {}
    filepath = os.path.join(SCRIPT_DIR, filename)
    with open(filepath, 'r') as f:
        w = csv.reader(f)
        for lines in w:
            if len(lines)<2:
                continue
            rev[lines[0]] = lines[1]
    return rev

def _strip_version_suffix(version_ipf):
    """version.json 의 'ver_001001.ipf' 형식에서 'ver' 만 추출.

    version.json 은 {"version": "<region_version>_001001.ipf"} 형식이다.
    parser_version.csv 의 region 키 값과 비교하려면 _001001.ipf 접미사를 떼야 한다.
    """
    if not version_ipf:
        return None
    s = str(version_ipf)
    # '_001001.ipf' 접미사 제거(또는 마지막 '_' 이전까지).
    idx = s.rfind('_')
    if idx > 0 and s[idx:].lower().endswith('.ipf'):
        return s[:idx]
    return s

def read_committed_version(region):
    """version.json 에 기록된 '커밋 완료' 버전을 읽는다.

    version.json 은 export() 성공 후 가장 마지막에 교체되므로, 이 값이
    parser_version.csv 의 값과 일치하면 이전 run 이 끝까지 완료된 것이다.
    일치하지 않으면(또는 version.json 이 없으면) 이전 run 이 version.json
    교체 직전에 실패한 것이므로 빌드를 재진행해야 한다.

    반환: version.json 의 버전 문자열(접미사 제거) 또는 None.
    """
    return _read_committed_version_stdpath(region)


def _read_committed_version_stdpath(region):
    """표준 JSON_ROOT 위치에서 version.json 을 읽는다.

    DB.build() 의 경로 규칙(project_root/TavernofSoul/JSON_<region>)을
    build() 호출 전에 유추한다. version.json 이 없거나 읽을 수 없으면
    None 을 반환해 "커밋 미완료"로 취급한다.
    """
    project_root = os.path.dirname(SCRIPT_DIR)
    version_json_path = join(
        project_root, "TavernofSoul", "JSON_{}".format(region), 'version.json'
    )
    if not os.path.exists(version_json_path):
        return None
    try:
        with open(version_json_path, 'r') as f:
            data = json.load(f)
    except (ValueError, OSError):
        # 손상된 version.json 도 커밋 미완료로 취급.
        return None
    return _strip_version_suffix(data.get('version'))

if __name__ == "__main__":
    try:
        region = sys.argv[1]
        region = region.lower()
        accepted = ['itos','ktos','ktest', 'jtos', 'twtos']
        if region not in accepted:
            logging.warning("region unsupported")
            quit()
    except:
        logging.warning("need 1 positional argument; region")
        quit()

    c= constants()
    current_version = read_version('parser_version.csv')
    #version = c.importJSON(join("..", 'unpacker_version_{}.txt'.format(region.lower())))['patched'][-1]
    version = read_version(join("..", 'downloader', 'revision.csv'))
    # 시작 조건: 다운로드 revision == parser_version.csv 이더라도 version.json 이
    # 아직 그 버전으로 갱신되지 않았으면(이전 run 이 version.json 교체 직전에
    # 실패한 커밋 미완료 상태) 빌드를 재진행해야 한다. version.json 경로는
    # build() 후에 확정되므로 여기서는 settings 없이 표준 위치를 가정한다.
    committed = read_committed_version(region)
    up_to_date = (
        version[region] == current_version[region]
        and committed == current_version[region]
    )
    if up_to_date and ('-f' not in sys.argv):
        logging.warning("ipf up to date")
        quit()
    if version[region] == current_version[region] and committed != current_version[region]:
        logging.warning(
            "commit incomplete: parser_version.csv=%s but version.json=%s; "
            "re-running build",
            current_version[region], committed,
        )
        
    c.build(region, SCRIPT_DIR)
    parse_xac.parse_xac(c)
    luautil.init(c)
    no_tl = ['ktos', 'ktest']
    asset.parse(c)
    if (region not in no_tl):
        translation.makeDictionary(c)
    jobs.parse(c)
    skill_bytool.parse(c)
    skills.parse(c)
    attributes.parse(c)
    attributes.parse_links(c)   
    attributes.parse_clean(c)
    skills.parse_clean(c)
    # 안전장치: iTOS 조기 skills export 제거.
    # 이전에는 파이프라인 중간에 skills.json 을 공개 디렉터리에 써서,
    # 이후 단계가 실패해도 일부 파일만 새 패치인 혼합 결과가 남았다.
    # 공개는 전체 성공 후 c.export() 에서만 일어난다.
    buff.parse(c)
    items.parse(c)
    vaivora.parse_additional_options(c)
    add_item_static(c)
    
    items.parse_goddess_EQ(c)
    
    monsters.parse(c)
    monsters.parse_links(c)
    monsters.parse_skill_mon(c)
    
    maps.parse(c)
    maps.parse_maps_images(c) #run map_image.py with py2.7 before running this
    maps.parse_links(c)
    misc.parse_achievements(c)
    #c.export_one("achievements")

    # 안전장치: version.json 을 JSON 승급 트랜잭션에 통합.
    # c.export(version_payload=v) 는 모든 JSON 을 staging 에 직렬화·검증한 뒤
    # version.json 까지 같은 staging 에 쓰고, 백업·롤백과 함께 일괄 교체한다.
    # 이렇게 하면 공개 JSON 과 version.json 이 항상 함께 승급되어, JSON 만
    # 신버전이고 version.json 은 구버전인 혼합 상태가 발생하지 않는다.
    #
    # parser_version.csv 는 version.json 보다 먼저 갱신한다(SCRIPT_DIR, 별도 파일).
    # parser_version.csv 갱신 후 export() 실패 시 version.json 은 구버전으로
    # 남아 시작 조건의 불일치 검사가 다음 실행에서 재시도를 보장한다.
    current_version[region] = version[region]
    v = {'version' : "{}_001001.ipf".format(version[region])}
    print_version('parser_version.csv', current_version)
    c.export(version_payload=v)
