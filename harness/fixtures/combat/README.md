# 스킬·몬스터·드롭 원본 fixture

아이템 fixture 위에 이 디렉터리의 입력을 복사해 임시 프로젝트를 만든다.
IES는 해제·변환 후의 CSV 형식이며 XML·Lua와 함께 직접 작성한 작은 샘플이다.
게임 바이너리나 운영 게임의 계산식·지역 데이터는 포함하지 않는다.
`expected_combat.json`은 파서 출력에서 생성하지 않고 별도로 작성한 주요 필드의 기대값이다.

## 입력과 확인값

| 입력 | 검증하는 동작 |
| --- | --- |
| `job.ies`, `statbase_pc.ies` | 직업 ID·트리·기본 능력치와 스킬의 직업 참조 |
| `skill.ies`, `skilltree.ies`, `cooldown.ies` | 활성 스킬 1개, 비활성 스킬 제거, 미참조 Common 스킬 제외, 최대 레벨·직업 연결·오버히트 |
| `shared.ipf/combat_calculate.lua` | 실제 Lua로 레벨별 계수·비율·시간·자원 소비·쿨다운과 몬스터 수치 계산 |
| `monster.ies`, `monster_const.ies` | 몬스터 2개의 레벨, 갑옷·종족 변환, Lua HP·공격력·경험치 |
| `field_monster_status_harness_*.ies` | 파일명 순서대로 지역 수치 보정, EXP와 JOBEXP의 서로 다른 값 유지 |
| `skill_mon.ies` | 몬스터 스킬 1개의 타수·쿨다운·공유 SkillType에 의한 몬스터 2개 연결 |
| `skill_bytool.ipf/combat.xml` | 대상 버프 문자열의 지속시간 ms → 초; 버프 도메인 적재는 포함하지 않음 |
| `ies_drop.ipf/HARNESS_WOLF.IES`, `harness_boar.ies` | 대소문자가 다른 파일명, 아이템 참조·확률·수량·미해결 참조 |
| `revision.csv` | 드롭 출처 지역과 입력 버전 기록; 공개 파서 버전과 구분 |

나머지 몬스터 유형과 statbase IES는 실제 파서의 파일 접근을 위한 헤더만 있다.
NPC·펫·소환수 등 빈 유형의 도메인 coverage로 계산하지 않는다.

- 스킬은 최대 레벨 3이며 현재 파서는 레벨 0부터 `MaxLevel + 9`까지 13개 계산값을 출력한다.
  스킬 계수는 `100..220`, 비율은 `0.4 → 40`, 기본 SP는 `15.9 → 15`, 쿨다운은 `6000ms`다.
  DB는 비율을 다시 확대하지 않고 40으로 저장하며 상세 화면의 기본 쿨다운은 6초다.
- Wolf는 HP 500, 물리 공격력 30~35, EXP 1000, JOBEXP 300이다.
  Boar는 지역 보정 후 HP 3333, 공격력 75~95, EXP 1234, JOBEXP 432다.
- 드롭 확률은 원본 `DropRatio / 100`의 **퍼센트 값**이다.
  `1250`은 `12.5%`, `100`은 `1%`이고 0~1 확률로 저장하지 않는다.
- `expired_drop`은 아이템이나 DB 관계로 만들지 않고 `unresolved_drops.json`에 문맥과 함께 기록한다.
  출처 `itos`, 입력 버전 `drop-fixture-v1`은 공개 파서 버전과 별도로 JSON에 남는다.

## 실행과 격리

```text
parse_xac + 번역 + luautil.init
  → jobs.parse + skill_bytool.parse + skills.parse/parse_clean
  → items.parse
  → monsters.parse + parse_links + parse_skill_mon
  → ToS_DB.export
  → importAll + 실제 migrations/ORM
  → 스킬·몬스터 검색/상세 및 아이템의 드롭 역참조
```

`make check-parser`는 독립 기대값, 원본 IES/Lua 변경, 레벨 경계, 지역 보정 제거,
전역 상태 복원, 잘못된 수치·직업 참조·필수 입력 누락·몬스터 Lua 함수 누락 시
이전 공개 JSON과 버전 보존 및 재시도를 검사한다.
스킬의 지역 보충 데이터도 입력 프로젝트 아래 임시 JSON에서 읽는다.

`make check-pipeline`는 같은 원본부터 DB·HTTP까지 검사한다.
타수 변경과 몬스터 연결 제거, 반복 적재, 원본 수치 변경, 이전 드롭 관계 삭제,
잘못된 몬스터 참조로 적재 실패 시 전체 DB·비교 기준 복원과 재시도를 포함한다.
드롭의 출처·미해결 정보는 JSON에서 검사하며 현재 ORM의 별도 필드에 저장하지 않는다.

필수 fixture 목록은 `harness/fixture_inputs.py`를 doctor와 실행기가 함께 사용한다.
Lua 런타임, 스킬 effect 목록, 몬스터 전역 테이블은 매 실행 격리하고 기존 상태를 복원한다.
게임 전체 스킬/Lua 계산, 모든 지역·몬스터 유형, 맵 zonedrop/dropgroup 원본 통합,
속성·버프 도메인, 자산 생성, 전체 `main.py`, MySQL과 브라우저 JavaScript는 후속 검증 범위다.
