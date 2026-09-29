# -*- coding: utf-8 -*-
"""
parser_tidy 파이프라인 프로파일링 드라이버.
main.py의 ktos 실행 경로를 그대로 재현하되:
  - 단계별 wall-clock 시간 측정
  - 전체 실행 cProfile 수집 (.prof 덤프)
  - export는 스크래치패드로 우회 (저장소 JSON_ktos를 덮어쓰지 않음)
  - parser_version.csv는 건드리지 않음
"""
import cProfile
import pstats
import time
import sys
import os
import json

PARSER_DIR = "/home/ubuntu/TavernofSoul/parser_tidy"
SCRATCH = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRATCH, "profile_out")
EXPORT_DIR = os.path.join(SCRATCH, "export_redirect")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

sys.path.insert(0, PARSER_DIR)
os.chdir(PARSER_DIR)

import logging
logging.basicConfig(level=logging.ERROR)  # 로그 소음/오버헤드 최소화

from DB import ToS_DB as constants
import translation, jobs, skills, attributes, luautil, asset
import items, monsters, maps, buff, vaivora, misc, skill_bytool, parse_xac
from item_static import add_item_static

region = "ktos"
c = constants()

stage_times = []

def run_stage(name, fn):
    t0 = time.perf_counter()
    try:
        fn()
        status = "ok"
    except Exception as e:
        status = "ERROR: {}".format(e)
    dt = time.perf_counter() - t0
    stage_times.append((name, dt, status))
    print("[stage] {:35s} {:10.2f}s  {}".format(name, dt, status), flush=True)

def redirect_and_export():
    # 저장소 출력을 덮어쓰지 않도록 export 경로를 스크래치패드로 변경
    c.BASE_PATH_INPUT = EXPORT_DIR
    c.BASE_PATH_OUTPUT = EXPORT_DIR
    c.export()

STAGES = [
    ("DB.build",                  lambda: c.build(region, PARSER_DIR)),
    ("parse_xac.parse_xac",       lambda: parse_xac.parse_xac(c)),
    ("luautil.init",              lambda: luautil.init(c)),
    ("asset.parse",               lambda: asset.parse(c)),
    # ktos는 translation.makeDictionary 미실행 (main.py의 no_tl)
    ("jobs.parse",                lambda: jobs.parse(c)),
    ("skill_bytool.parse",        lambda: skill_bytool.parse(c)),
    ("skills.parse",              lambda: skills.parse(c)),
    ("attributes.parse",          lambda: attributes.parse(c)),
    ("attributes.parse_links",    lambda: attributes.parse_links(c)),
    ("attributes.parse_clean",    lambda: attributes.parse_clean(c)),
    ("skills.parse_clean",        lambda: skills.parse_clean(c)),
    ("buff.parse",                lambda: buff.parse(c)),
    ("items.parse",               lambda: items.parse(c)),
    ("vaivora.parse_additional_options", lambda: vaivora.parse_additional_options(c)),
    ("add_item_static",           lambda: add_item_static(c)),
    ("items.parse_goddess_EQ",    lambda: items.parse_goddess_EQ(c)),
    ("monsters.parse",            lambda: monsters.parse(c)),
    ("monsters.parse_links",      lambda: monsters.parse_links(c)),
    ("monsters.parse_skill_mon",  lambda: monsters.parse_skill_mon(c)),
    ("maps.parse",                lambda: maps.parse(c)),
    ("maps.parse_maps_images",    lambda: maps.parse_maps_images(c)),
    ("maps.parse_links",          lambda: maps.parse_links(c)),
    ("misc.parse_achievements",   lambda: misc.parse_achievements(c)),
    ("export(redirected)",        redirect_and_export),
]

prof = cProfile.Profile()
t_total0 = time.perf_counter()
prof.enable()
for name, fn in STAGES:
    run_stage(name, fn)
prof.disable()
t_total = time.perf_counter() - t_total0

prof_path = os.path.join(OUT_DIR, "parser_ktos.prof")
prof.dump_stats(prof_path)

# 단계별 시간 저장
with open(os.path.join(OUT_DIR, "stage_times.json"), "w") as f:
    json.dump(
        {"total_sec": t_total,
         "stages": [{"name": n, "sec": s, "status": st} for n, s, st in stage_times]},
        f, ensure_ascii=False, indent=2)

print("\n==== TOTAL: {:.2f}s ====".format(t_total), flush=True)

# 텍스트 리포트도 같이 남김
report_path = os.path.join(OUT_DIR, "pstats_report.txt")
with open(report_path, "w") as f:
    st = pstats.Stats(prof_path, stream=f)
    st.strip_dirs()
    f.write("==== sort by cumulative time (top 60) ====\n")
    st.sort_stats("cumulative").print_stats(60)
    f.write("\n==== sort by internal time (top 60) ====\n")
    st.sort_stats("tottime").print_stats(60)
    f.write("\n==== callers of hottest internals (top 25) ====\n")
    st.sort_stats("tottime").print_callers(25)

print("done. prof={} report={}".format(prof_path, report_path), flush=True)
