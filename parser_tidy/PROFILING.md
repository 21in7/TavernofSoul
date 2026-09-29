# parser_tidy 파이프라인 프로파일링 결과

> 실제 IES 및 게임 툴팁 Lua와 대조한 콘텐츠 완전성/개선 리뷰는
> [PROFILING_REVIEW.md](PROFILING_REVIEW.md)를 참고한다.

- 측정일: 2026-07-22
- 대상: `main.py`의 ktos 실행 경로 전체 (translation 단계는 ktos라 미실행)
- 방법: 단계별 wall-clock + 전체 cProfile + py-spy 샘플링 병행
- 환경: Python 3.8.10, 입력 `ktos_unpack` 약 2.2GB (ies 1,017개)
- 주의: cProfile 계측 오버헤드로 절대 시간은 실제보다 다소 부풀려짐(특히 함수 호출이 많은 구간).
  상대 비중과 순위가 중요함. asset 아이콘 복사는 mtime 캐시로 대부분 스킵된 warm 상태에서 측정.

## 전체: 238.4초

## 단계별 시간

| 단계 | 시간(s) | 비중 |
|---|---:|---:|
| items.parse | 85.1 | 35.7% |
| monsters.parse_skill_mon | 62.1 | 26.0% |
| export (JSON 36개 dump) | 40.5 | 17.0% |
| monsters.parse | 14.6 | 6.1% |
| monsters.parse_links | 9.1 | 3.8% |
| luautil.init | 9.1 | 3.8% |
| vaivora.parse_additional_options | 8.1 | 3.4% |
| attributes.parse_clean | 2.3 | 1.0% |
| DB.build / skills.parse | 1.8 / 1.8 | — |
| 나머지 (jobs, buff, maps, misc 등) | < 4 | — |

상위 3개 단계(items.parse + parse_skill_mon + export)가 전체의 **약 79%**.

## 병목 상세 (cProfile 근거)

### 1. items.parse → parse_equips — 85.1s 중 74.3s

`items.py:298 parse_equips` (6개 ies, 약 17,400행). tottime 64.8s로 단일 함수 1위.

- 장비 1행마다 lupa(LUA) 함수를 최대 **약 90회** 호출:
  - Anvil: 강화 레벨 40 × (`GET_REINFORCE_ADD_VALUE[_ATK]` + `GET_REINFORCE_PRICE`) — items.py:460-467
  - Transcend: 10레벨 × `GET_TRANSCEND_MATERIAL_COUNT` — items.py:476-481
- LUA→Python 속성 접근 브리지 `luautil.py:18 attr_getter`가 전 파이프라인에서 **4,430만 회** 호출됐고
  그중 3,440만 회가 parse_equips 발(發). LUA 수식이 row dict를 필드 단위로 계속 읽는 구조.
- 추가로 `items.py:162`에서 `luautil.init(c)`를 **무조건 재호출** → LUA 런타임 재구축 약 9초가
  items.parse 안에 중복 포함됨 (main.py에서 이미 init 완료된 상태).

### 2. monsters.parse_skill_mon — 62.1s

`DB.py:271 getMonbySkill`이 6,534회 호출되는데, 호출마다 **전체 몬스터 dict를 2번 풀스캔**하며
행마다 `.lower()` 비교 → O(스킬 × 몬스터 × 2). `str.lower` 총 1.64억 회의 대부분이 여기서 발생.
tottime 47.3s / cumtime 61.1s.

### 3. export — 40.5s

`DB.export()`가 data 36종 전부를 stdlib `json.dump`로 직렬화. `_iterencode*` 호출 3,500만+.
파싱 결과가 바뀌지 않은 컬렉션도 매번 전량 재직렬화.

### 4. monsters.parse — 14.6s

`monsters.py:107 parse_monsters` tottime 11.4s. 몬스터마다 EXP/명중/회피/크리 등 스탯을
LUA 수식(`SCR_Get_MON_*`)으로 계산 — attr_getter 970만 회.

### 5. luautil.init — 9.1s (실제 누적 18.1s, 2회 호출)

- `init_global_data`: `iesutil.load` 52파일, 누적 9.7s
- `init_runtime`: `os.walk`로 2.2GB unpack 트리 전체를 다시 순회(`posix.listdir` 5.6s)하며
  .lua 파일 24,500여 개 함수를 정규식 전처리 후 로드. `DB.directoryDictionary`가 이미 만든
  `file_dict`가 있는데도 별도로 다시 걷는 구조.

### 6. 그 외

- `iesutil.load`: 셀 단위로 `int()` → 실패 시 `float()` → 실패 시 원본 유지의 try/except 캐스팅.
  파이프라인 전체 csv 24만 행 처리에서 tottime 7.9s.
- `vaivora._build_tooltip_index`: XML 140개 `ET.parse`로 7.6s.

## 개선 우선순위 제안 (예상 효과 순)

| # | 작업 | 예상 절감 | 난이도 |
|---|---|---:|---|
| 1 | `getMonbySkill`을 SkillType→ID 리스트 **사전 인덱스**로 교체 (parse_skill_mon 시작 시 1회 구축) | 약 -60s | 하 |
| 2 | export를 **orjson/ujson**으로 교체하거나, 변경된 컬렉션만 dump | 약 -30~35s | 하 |
| 3 | `items.py:162`의 중복 `luautil.init(c)` 제거(초기화 여부 가드) | 약 -9s | 하 |
| 4 | parse_equips의 Anvil/Transcend LUA 결과 **메모이제이션** — 가격/증가치 곡선은 (Grade, Level, ClassType, tooltip_script) 등 소수 키 조합에 종속이므로 동일 입력 반복 계산 제거 | 약 -30~50s (검증 필요) | 중 |
| 5 | `init_runtime`의 os.walk 제거 — `c.file_dict` 재활용해 .lua만 순회 | 약 -5s | 하 |
| 6 | `iesutil.load` 캐스팅을 컬럼 타입 추론(첫 N행 샘플) 또는 정규식 선판별로 교체 | 약 -5s | 중 |

1~3번(난이도 하)만 적용해도 **238s → 약 135s**, 4번까지 성공하면 **90s 내외** 예상.

## 산출물 위치

`parser_tidy/profiling/` 에 보존:

- `pstats_report.txt` — cProfile 텍스트 리포트 (cumulative/tottime 상위 60 + callers)
- `stage_times.json` — 단계별 wall-clock
- `profile_parser.py` — 재현 스크립트. main.py의 ktos 경로를 그대로 실행하되 export를
  스크래치패드로 우회해 저장소 `JSON_ktos`와 `parser_version.csv`를 건드리지 않음
  (스크립트 상단의 SCRATCH/OUT_DIR 경로만 환경에 맞게 조정)

바이너리 덤프(스크래치패드, 세션 종료 시 소실될 수 있음):

- cProfile 덤프 `parser_ktos.prof` (`snakeviz`로 열람)
- py-spy 샘플(90s, items.parse~parse_skill_mon 구간) `profile_out_pyspy.speedscope.json`
  (https://speedscope.app 에서 열람)

재측정 방법:

```bash
python3 profiling/profile_parser.py
```
