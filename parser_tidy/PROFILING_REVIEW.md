# parser_tidy 프로파일링 및 IES 콘텐츠 완전성 리뷰

- 리뷰일: 2026-07-22
- 보완 섹션 재검증: 2026-07-22 (`importAll.py`, Django 모델, 현재/prev JSON 포함)
- 구현 가능성 코드 검증: 2026-07-22 (파서, importer, 모델, URL/API 소비 경로 포함)
- 2차 코드 재리뷰: 2026-07-22 (현재 worktree와 IES/JSON 교차 집계)
- 구현 착수 판정: 2026-07-22 (조건부 착수 승인 — 아래 "구현 착수 판정" 절 참조)
- 최종 고정 전 정리: 2026-07-22 (지적 4건 반영 — "최종 고정 전 정리 4건 처리" 절 참조)
- 3차 재검증: 2026-07-22 (즉시 공개 안전조치와 완전한 원자성의 보장 범위 재정의)
- 4차 보완: 2026-07-22 (기존 리뷰 누락 후보 6건 추가 — 후속 재검증에서 5건 확정·1건 기각)
- 외부 리뷰 재검증: 2026-07-22 (버전 파일의 개별 원자적 교체 선결 조건 추가)
- 5차 재검증: 2026-07-22 (`revision.csv` CWD 의존 주장 기각, Grade 수정 우선순위 교정)
- 6차 코드 검증: 2026-07-22 (5차 정정 2건 코드·데이터 재확인 — "6차 코드 검증" 절 참조)
- 7차 최종 재리뷰: 2026-07-22 (현재 worktree·테스트·cron 재확인, 단계별 구현 착수 승인)
- 8차 착수 직전 검증: 2026-07-22 (핵심 근거 7건 코드 재대조 일치, 스냅샷 미커밋 상태만 선행 조건 미충족 — "8차 착수 직전 검증" 절 참조)
- P0 구현 후 현행화: 2026-07-22 (커밋 `6a62f9bad`~`5d986fc35`, 테스트 78개 통과 기준)
- 원자적 승격·패키지 미해결 분리 현행화: 2026-07-23 (staging 디렉터리 일괄 승격 구현, PackageContents.unresolved 분리, 테스트 94개 통과 기준)
- 백업·롤백·재시도 보장 현행화: 2026-07-23 (교체 단계 실패 시 백업·롤백, version.json 미완료 재시도, 테스트 106개 통과 기준)
- 백업 copy 전환·stale backup 보존 현행화: 2026-07-23 (백업 move→copy 전환으로 백업 실패 시 공개 무결, 비어 있지 않은 stale backup 시 실행 중단, 테스트 109개 통과 기준)
- 드롭 provenance 현행화: 2026-07-24 (`drop_source.py` 데이터셋 단위 iTOS 우선 fallback, 레코드에 `SourceRegion`/`InputVersion`, `build_provenance`/`unresolved_drops` 컬렉션, 하드코딩 `../itos_unpack` 제거, maps 직접 zonedrop 유실·셰도잉·dropgroup 합계0 버그 수정, 테스트 19개 통과 기준)
- version.json 트랜잭션 통합 현행화: 2026-07-23 (version.json을 export(version_payload) JSON 승급 트랜잭션에 통합, 롤백 copy 기반 + `.rollback-failed` 마커로 백업 보존, 공개 승급 os.replace 정확 카운트 테스트 교정, 테스트 116개 통과 기준. 자가 회복 회귀 수정: 롤백 완전 성공·교체 전 실패 시 백업을 폐기해 다음 실행이 stale backup 중단 없이 재시도 — 보존 판단은 _rollback_promotion 반환값 기반이라 마커 작성 실패에도 안전)
- 기준 입력: `ktos_unpack`의 실제 IES 1,017개와 게임 툴팁 Lua
- 기준 출력: `TavernofSoul/JSON_ktos/*.json`
- 관련 문서: [PROFILING.md](PROFILING.md)

## 결론

현재 파서는 **플레이어 스킬과 등록된 기본 아이템의 레코드 자체는 대부분 수집**하지만, 게임 툴팁을 재현하는 데이터셋으로 보기에는 중요한 누락과 구조적 오류가 있다.

구현 가능성 판정은 **조건부 승인**이다. P0~P3 방향은 유지할 수 있지만 문서 전체를 그대로 한 번에 구현하면 안 되며, ID/DB/API 마이그레이션과 큐브 다중 매핑, 550 accessory 구분을 먼저 설계에 반영해야 한다. 2차 재리뷰에서는 패키지 토큰 오해석, 몬스터 EXP/JOBEXP 역매핑, 지역 드롭 출처 혼합, 비원자적 결과 공개를 추가 P0로 판정했다.

착수 당시 가장 먼저 고칠 항목과 현재 상태는 다음과 같다.

1. **완료:** `EQUIPMENT_IES`의 대소문자 중복을 제거하고 realpath 중복 처리를 방지했다.
2. **완료:** 큐브 보상 연결을 다중 매핑으로 수정했다. 현재 CUBE 1,045개 중 117개가 `reward_indun` 보상과 연결된다.
3. **미구현:** Item과 Recipe의 `ClassID` 충돌 49건을 canonical ID와 DB/API 마이그레이션으로 해소한다.
4. **미구현:** 가디스 강화 레벨을 자동 탐색하고 `item_goddess_reinforce_550.ies`의 accessory 지원을 반영한다.
5. **미구현:** 스킬 메타데이터와 ARK·RELIC·BELT·EARRING·CORE 전용 옵션을 툴팁 종류별로 정규화한다.
6. **부분 완료:** 패키지 `/` 토큰 오해석 261건과 `RANDOM_MUTIPLE`, `SET_ACCOUNT_PROP` 분류 오류를 수정했다. 만료 이벤트 Item 참조 2건은 `PackageContents.unresolved`로 명시 분리했다(가짜 fallback 생성 금지, 원문 보존). 남은 것은 DB `package_contents` TextField의 직렬화 결과를 API/화면에서 구조화해 렌더링하는 표시 계층뿐이다.
7. **부분 완료:** 지역 보정 `EXP`/`JOBEXP` 역매핑은 수정해 916개 대조에서 불일치가 0건이다. 맵별 상이한 스탯 17개를 전역 한 건으로 덮어쓰는 문제는 남아 있다.
8. **완료(최종 상태 원자성, 독자 관점 원자성은 제한):** iTOS 조기 저장 제거, 버전 파일별 원자 교체·순서 교정, cron 실패 중단, 그리고 전체 JSON의 임시 릴리스 디렉터리(`JSON_<region>.staging/`) 기반 백업·롤백 일괄 교체를 모두 구현했다. `export(version_payload=v)`는 모든 컬렉션을 staging에 완전히 직렬화·검증한 뒤, 기존 공개 파일을 백업 디렉터리로 **복사(copy)**해둔다. 백업 단계 실패 시 공개 파일은 전혀 건드리지 않은 상태로 남는다(copy이므로). 검증·백업 성공 후 staging 파일을 공개 위치로 `os.replace` 교체하며, 교체 도중 하나라도 실패하면 백업에서 모든 공개 파일을 구버전으로 롤백하고(신규 파일은 공개에서 제거), 전체 성공 시에만 백업을 폐기한다. **version.json은 JSON 승급 트랜잭션에 통합**되어 공개 JSON과 함께 원자적으로 승급·롤백되므로, JSON만 신버전이고 version.json은 구버전인 혼합이 발생하지 않는다. 롤백 자체가 실패하면 `.rollback-failed` 마커를 남겨 백업 디렉터리를 보존하고(copy 기반이므로 백업 원본은 온전), 다음 실행은 비어 있지 않은 backup을 감지해 중단해 운영자가 수동 복구할 수 있도록 한다. `parser_version.csv`는 `export()`보다 먼저 갱신되며, `export()` 실패 시 version.json이 구버전으로 남아 시작 조건의 `version.json`/`parser_version.csv` 불일치 검사가 실패한 run을 자동으로 재시도한다. **한계:** `BASE_PATH_OUTPUT`이 고정 디렉터리를 직접 가리키므로 디렉터리 포인터 단위 교체(symlink)는 도입하지 않았다. 따라서 교체 진행 중 독자가 일시적으로 신구 혼합 상태를 관찰할 수 있으나, 최종 상태는 전부 신버전 또는 전부 구버전 둘 중 하나로만 귀결된다. importer는 cron이 parser 전체 성공 후에만 실행되므로 혼합 관찰 창에 도달하지 않는다.

이 여덟 항목 중 1번은 정확성 변경 없이 약 30초를 줄일 수 있는 것으로 추정된다. 기존 프로파일링 문서의 성능 우선순위에는 이 항목이 빠져 있다.

## 조사 범위와 판정 기준

2차 재리뷰는 현재 source와 2026-07-21 `JSON_ktos`, 2026-07-22 프로파일 결과를 읽기 전용으로
교차 검증했다. 전체 파서를 새로 실행하지는 않았으므로 성능 예상치는 기존 프로파일 기준이며,
새 정확성 수치는 IES/JSON 집계와 해당 생성 코드가 일치하는 경우에만 확정값으로 기록했다.

다음 세 층을 별도로 비교했다.

1. 원본 레코드 완전성: 대상 IES의 `ClassName`이 JSON에 존재하는가.
2. 정적 툴팁 완전성: 이름, 설명, 요구 조건, 옵션 정의와 레벨별 공식이 존재하는가.
3. 인스턴스 툴팁 완전성: 강화 수치, 랜덤 옵션, 소켓, 귀속, 현재 경험치처럼 개별 아이템 상태가 필요한가.

3번은 IES만으로 완전 재현할 수 없다. 따라서 정적 데이터에는 가능한 옵션, 범위, 공식과 소스만 저장하고, 실제 값은 별도의 인스턴스 입력과 결합해야 한다. 이 구분 없이 게임 화면을 그대로 복제하려 하면 파서가 임의의 0 또는 기본값을 사실처럼 노출하게 된다.

## 실제 IES 대조 결과

### 아이템

`ITEM_IES`에 등록된 파일의 고유 원본 행은 28,743개이며, `items_by_name.json`에는 이 28,743개가 모두 존재한다. 여기에 수동 정적 항목 10개가 더해져 이름 기준 결과는 28,753개다. 즉, 등록된 파일 범위 안에서는 `ClassName` 기준 기본 레코드 누락은 없다.

그러나 다음 문제가 있다.

| 항목 | 실제 상태 | 판정 |
|---|---:|---|
| 이름 기준 아이템 | 28,753 | 등록 범위는 완전 |
| ID 기준 아이템 | 28,704 | 49개 ID 충돌로 손실 |
| 장비 원본 | 10,171 | 이름 기준 전부 존재 |
| `item_petequip.ies` | 22 | `ITEM_IES` 미등록으로 전부 누락 |
| CUBE | 1,045 | `reward_indun`과 연결된 큐브 117개 |
| 패키지 객체 생성 | 코드 기준 1,486 / 후보 1,493 | 오해석 0건. GROWTH 6개와 SET_ACCOUNT_PROP 1개는 보고 전용. 체크인된 JSON은 수정 전 1,487개라 재생성 필요 |
| 설명이 비어 있는 아이템 | 2,024 | Recipe 1,364, Equipment 626이 대부분 |

설명이 빈 레코드가 모두 파서 오류인 것은 아니다. 원본 `Desc`가 빈 경우도 많다. 다만 게임 클라이언트는 `Desc` 외에 `UsageDesc`, `Desc_Sub`, `CustomToolTip`과 전용 Lua를 조합한다. 현재 파서는 다음 원본 콘텐츠를 일반 아이템 결과에 보존하지 않는다.

| 원본 필드 | 값이 있는 행 | 용도 |
|---|---:|---|
| `UsageDesc` | 550 | 사용법/추가 안내 |
| `Desc_Sub` | 97 | 보조 설명 |
| `CustomToolTip` | 26 | 커스텀 툴팁 함수 |
| `SpineTooltipImage` | 31 | 전용 툴팁 이미지 |
| `SkillType` | 19 | 아이템이 참조하는 스킬 |
| `SkillLevel` | 20 | 참조 스킬 레벨 |
| `ExpireDateTime` | 1,124 | 고정 만료 정보 |

`TooltipImage`, `ToolTipScp`, `ReqToolTip`, `MarketCategory`, `Reinforce_Type`, `StringArg*`도 대부분 결과 스키마에서 사라진다. 일부는 현재 파서의 파생 필드로 대체되지만, 원본을 남기지 않아 새 툴팁 형식이 추가됐을 때 재처리와 원인 추적이 어렵다.

### 장비 툴팁

기본 공격력/방어력, 스탯, 강화·초월 재료 곡선, 요구 레벨, 직업, 소켓 수는 파싱된다. 반면 실제 게임은 `ToolTipScp`에 따라 별도 렌더링 경로를 사용한다.

| 전용 툴팁 | 실제 장비 수 | 현재 상태 |
|---|---:|---|
| ARK | 26 | 기본 장비 필드만 있고 레벨별 옵션/성장 비용 스키마 없음 |
| RELIC | 1 | 성물 레벨 옵션, 경험치, 젬 소켓 정의 없음 |
| BELT | 72 | 랜덤 옵션 범위/업그레이드 옵션 정의 없음 |
| EARRING | 3 | 특수 옵션 등급/레벨 구조 없음 |
| CORE | 2 | 코어 전용 옵션 구조 없음 |

게임 Lua의 `ITEM_TOOLTIP_ARK`, `ITEM_TOOLTIP_RELIC`, `ITEM_TOOLTIP_BELT`, `ITEM_TOOLTIP_EARRING`, `ITEM_TOOLTIP_CORE`는 각각 별도 함수와 보조 IES/Lua 테이블을 조회한다. 현재 `parse_equips`는 이 구분 없이 대부분을 `Bonus`와 네 개의 기본 스탯으로 평탄화한다.

최근 추가된 `vaivora.parse_additional_options()`는 별도로 긍정적인 진전이다. 실제
`AdditionalOption_1..4`가 있는 장비 501개, 옵션 엔트리 611개가 `DicIDTable.xml`의 툴팁 키와
전부 연결되고 현재 JSON에도 611개가 `Bonus`로 들어간다. 다만 결과가 `lv4/add_opt + 렌더링 문자열`로
평탄화되어 원본 키, 옵션 슬롯, 구조화 수치가 사라지고, 비한국 지역에서 번역이 없으면 한국어로
fallback한다. 따라서 ktos 정적 문구 커버리지는 통과했지만 다지역/구조화 툴팁 완료로 보기는 어렵다.

또한 장비 원본에는 `MaxSocket_MA` 값이 있는 행이 248개 있지만 현재 결과에는 일반 소켓만 있다. `EnableDuctility`가 활성인 64개 템플릿도 연성 가능 여부와 관련 테이블이 노출되지 않는다. `RandomOption_*`, `RerollIndex`, `Ductility_Count`, `EnchantSkillName_*`, `UpgradeRank` 등은 주로 인스턴스 값이므로 정적 IES가 0인 것이 정상이다. 대신 정적 결과에는 해당 장비가 어떤 인스턴스 옵션을 지원하는지와 값 범위를 제공해야 한다.

### 큐브와 패키지 툴팁

`reward_indun.ies`에는 1,450개 보상 행과 130개 그룹이 있고, 그중 해석 가능한 116개 그룹은
공유 그룹을 포함한 큐브 117개와 연결된다. 잘못된 `items_by_name` 선행 조건, `ID_NAME` 키 오타,
단일 `StringArg -> cube` 매핑은 제거됐고 현재 출력은 CUBE 1,045개 중 117개에 `Link_Items`가 있다.

패키지류 후보는 1,493개이고 `resolve_package_contents`가 1,486개에
`PackageContents`를 만든다(후보 1,493 = 생성 1,486 + growth 6 + account_prop 1).
이전 구현의 `rpartition('/')` 버그 — `Item/Count/Property/Value/...` 형식에서 마지막 값을
수량으로, 그 앞 전체를 Item 이름으로 잘못 저장해 72개 패키지의 261개 구성물 참조가
존재하지 않는 Item 이름을 가리키던 문제(예: `Legendcard_Leticia/5/ItemExp/60`이
Item=`Legendcard_Leticia/5/ItemExp`, Count=60으로 저장) — 는 `package_parser` 분리로
수정됐다. 현재는 앞에서부터 Item, Count를 읽고 나머지를 property/value 쌍(인스턴스
옵션)으로 보존하며, 오해석 참조는 0건이다.

`SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT_GROWTH` 6개는 `StringArg=Melee|Magic`이므로 Item
목록이 아니며 growth_selection 범주로 보고만 한다(성장 선택 규칙 해석은 미구현).
`SCR_USE_STRING_SET_ACCOUNT_PROP` 1개(`portion_reset_10th_boss_loot`)는 StringArg가
`account.ies`의 계정 속성명(`EVENT_FIELD_BOSS_10TH/None`)이므로 account_prop 범주로
보고만 하고 구성물을 생성하지 않는다. DB `package_contents` TextField와 importer 저장은
구현됐지만 serializer에서는 JSON 문자열이고 화면 템플릿은 이를 렌더링하지 않는다.
직접 Item 참조 중 `Event_misc_reinforce_percentUp_470_NoTrade_limit` 2건은 원본 Item 정의가 없는
만료 이벤트 참조다. 현재는 `name=null`인 성공 항목으로 남으므로 미해결 참조 보고 또는 명시적인
`unresolved` 상태로 분리해야 한다. 또한 체크인된 `JSON_ktos/items.json`은 account_prop 수정 전에
생성되어 `portion_reset_10th_boss_loot`의 잘못된 구성물이 남아 있으므로 재생성이 필요하다.
따라서 패키지는 **토큰 파싱 정확성 확보·미해결 참조 정책과 표시 계층 미구현** 상태다.

다음 검증이 필요하다.

- `Script`별 비어 있지 않은 `StringArg` 형식 목록을 자동 집계한다.
- 미지원 형식은 조용히 버리지 않고 항목 수와 샘플을 리포트한다.
- 고정 지급, 수량 지급, 랜덤 지급, 성장 선택을 서로 다른 타입으로 저장한다.
- split 토큰은 최소 `item/count`를 먼저 읽고 뒤쪽 `property/value` 쌍을 인스턴스 옵션으로 보존한다.
- 모든 직접 Item 참조가 `items_by_name`에 존재하는지 검증하고, 미존재 참조를 성공으로 세지 않는다.
- `reward_indun`, `reward_ratio_open_list`, `item_package`처럼 확률 또는 외부 그룹을 쓰는 콘텐츠는 별도 소스로 연결한다.

### 스킬 툴팁

플레이어 스킬의 레코드 범위는 정확하다. `skilltree.ies`의 `Type=Skill` 고유 참조 912개와 `skills_by_name.json` 912개가 정확히 일치한다. `skill.ies` 전체 1,483개 중 빠진 571개는 현재 직업 트리에 연결되지 않은 NPC·아이템·폐기 스킬이 중심이며, `skills.parse_clean`의 의도와 일치한다.

다만 다음 범위는 별도 데이터셋으로 필요할 수 있다.

- `skill_common.ies` 405개: 변환/보조/바이보라 서브스킬 성격
- `skill_ancient.ies` 145개: 어시스터/고대 몬스터 스킬
- `skill_mon.ies` 6,534개: 몬스터 스킬

플레이어 스킬 912개의 실제 툴팁 메타데이터 중 현재 결과에 없는 주요 필드는 다음과 같다.

| 필드 | 실제 분포 | 게임 툴팁 영향 |
|---|---|---|
| `CastingCategory` | instant 667, cast 160, channeling 47, dynamic 8 | 캐스팅/채널링 문구 |
| `HitType` | Pad 52, Installation 25 등 | 장판/설치형 문구 |
| `AffectedByAttackSpeedRate` | YES 49 | 공격 속도 영향 문구 |
| `TooltipType` | Active 887, Passive 25 | 액티브/패시브 처리 |
| `EnableCompanion` | BOTH 122, YES 38 | 컴패니언 요구 문구 |
| `EngName` | 912 | 검색/지역 간 안정 키 |
| `CoolDownGroup` | 892개에 값 | 공유 쿨다운 관계 |
| `SpendItem` | 3개에 함수 | 소모 아이템 툴팁 |
| `SelfBuff` | 6개에 값 | 부여 버프 연결 |

`EnableCompanion`은 현재 `RequiredStanceCompanion`으로 일부 보존되지만, 게임 문구를 재현하는 데 필요한 나머지 필드와 함께 정규화되어 있지 않다. `skills.py:419-424`는 공격 타입/속성 헤더를 계산만 하고 `Description`에 붙이지 않는 코드이므로 의도한 보정도 실제 출력에는 반영되지 않는다.

레벨별 공식은 `sfr`, `CaptionRatio*` 일부가 정상 생성되지만 실패가 모두 `except: pass`로 숨겨진다. 현재 결과에도 빈 `CaptionRatio` 계열 배열 12개가 있으며, `CoolDown`은 912개 모두 리스트지만 880개가 빈 리스트다. 기본 쿨다운은 별도 필드에 있어 화면이 완전히 깨지지는 않지만, “공식 없음”과 “공식 평가 실패”를 구분할 수 없다.

### 특성 툴팁

`ability.ies` 2,922개 중 최종 1,814개가 남는다. 직업별 `ability_<Job>.ies`에서 활성 레벨과 연결을 찾지 못한 항목을 `attributes.parse_clean`이 제거하는 구조다. 이는 활성 특성만 보여 주려는 목적에는 맞지만, 삭제 사유가 결과나 리포트에 남지 않는다.

게임 특성 툴팁은 `Desc`뿐 아니라 `Desc2`를 레벨별로 파싱한다. 현재 파서는 `Desc`와 직업 파일의 `UnlockDesc`는 저장하지만 `Desc2`, `AddSpend`, `Keyword`, `ActiveGroup` 등은 보존하지 않는다. 특성 레벨별 효과와 추가 소비 포인트를 정확히 보여 주려면 별도 정규화가 필요하다.

### 몬스터와 지역별 드롭 콘텐츠

2차 재리뷰에서 아이템 링크의 공급자인 몬스터/맵 데이터도 확인했다. 현재
`monsters.parse()`는 `field_monster_status*.ies` 179개, 951행을 하나의
`monster_const_stat[ClassName]` dict에 합친다. 고유 ClassName은 918개이고 28개는 여러 파일에
등장하며, 그중 17개는 실제 HP/방어/EXP 값이 서로 다르다. 정렬된 파일에서 마지막 행만 남기므로
같은 몬스터의 맵별 난이도 차이를 표현하지 못한다.

지역 보정 행의 `EXP=JOBEXP`, `EXPClass=EXP` 역매핑은 수정됐다. 현재 선택되는
`field_monster_status*` 행과 출력 916개를 대조한 결과 원본 `EXP`↔출력 `EXP`, 원본
`JOBEXP`↔출력 `EXPClass` 불일치는 0건이다. 다만 동일 ClassName의 맵별 상이한 스탯 17개를
마지막 행 하나로 덮어쓰는 구조는 그대로이므로 `map_monsters` 분리 또는 대표값 출처 명시가 필요하다.

드롭 원본은 현재 unpack 중 iTOS에만 존재한다(`ies_drop.ipf` 2,248개, 다른 네 지역은 없음).
`monsters.py:255`와 `maps.py:166`은 모든 지역에서 이를 명시 없이 `../itos_unpack`으로 읽는다.
로컬 원본이 없을 때 iTOS를 fallback으로 쓰는 것 자체는 가능하지만 다음 조건이 필요하다.

- 출력에 `source_region=itos`, fallback 이유와 입력 버전을 기록한다.
- 지역 Item에 없는 드롭 참조와 iTOS/대상 지역 패치버전 불일치를 리포트한다.
- 경로를 하드코딩하지 말고 입력 매니페스트에서 의존성을 선택한다.
- `maps.py`처럼 첫 경로는 iTOS, 보조 경로는 현재 지역을 쓰는 혼합 규칙을 하나로 통일한다.

맵별 몬스터 스탯이 제품 범위라면 `map_monsters`를 별도 데이터셋으로 복원하고, 전역
`monsters`에는 기준 템플릿만 둔다. 범위가 아니라면 어떤 맵의 값을 대표값으로 선택했는지 적어도
출처를 명시해야 한다.

## 프로파일링 문서 보완

기존 [PROFILING.md](PROFILING.md)의 큰 병목 순위는 타당하다. 다만 `items.parse` 분석에서 가장 값싼 최적화 하나가 누락됐다.

착수 전 `DB.py:33-38`의 `EQUIPMENT_IES`에는 다음 대소문자 중복이 있었다.

- `item_equip.ies` / `item_Equip.ies`
- `item_event_equip.ies` / `item_event_Equip.ies`

현재 목록은 고유 파일 4개로 정리됐고 `parse_equips`도 realpath 중복을 건너뛴다. 착수 전 중복은
7,192행으로 전체 장비 루프의 41.4%였다. 실제 절감 시간은 같은 입력의 재프로파일로 확정해야 한다.

`parse_equips` 74.3초에 단순 비례하면 중복 제거만으로 약 31초를 줄일 여지가 있다. 실제 절감량은 재측정해야 하지만, 메모이제이션보다 먼저 적용할 수 있는 저위험 수정이다.

수정된 성능 우선순위는 다음과 같다.

| 순위 | 작업 | 예상 효과 | 난이도 | 콘텐츠 영향 |
|---:|---|---:|---|---|
| 1 | `EQUIPMENT_IES` 대소문자 중복 제거 및 경로 중복 assert | 약 -25~-31초 | 하 | 없음 |
| 2 | `getMonbySkill` 사전 인덱스와 중복 결과 수정 | 약 -60초 | 하 | 승인된 정확성 변경 |
| 3 | `items.py:162` 중복 `luautil.init` 제거 | 약 -9초 | 하 | 출력 동등성 검증 필요 |
| 4 | export 고속화 또는 변경분만 저장 | 약 -30~-35초 | 하~중 | 직렬화 동일성 검증 |
| 5 | 남은 고유 장비의 강화/초월 공식 메모이제이션 | 약 -15~-30초 | 중 | 키 완전성 검증 필수 |
| 6 | Lua 탐색에 `file_dict` 재사용 | 약 -5초 | 하 | 없음 |
| 7 | IES 타입 추론/캐스팅 개선 | 약 -5초 | 중 | 값 타입 회귀 위험 |

1~4번을 합치면 현재 238초에서 약 100초 전후까지 내려갈 가능성이 있다. 이는 cProfile 계측 기준의 거친 추정이며, 각각 독립 적용 후 동일 입력으로 다시 측정해야 한다.

`items.parse_goddess_EQ`는 `items.parse` 내부에서 한 번 호출되고 `main.py:100`에서 다시 호출된다. 현재 비용은 약 0.008초라 성능상 중요하지 않지만 실행 경로를 단일화하는 편이 맞다.

## 권장 설계

### 1. 입력 매니페스트를 자동 생성한다

하드코딩된 파일 목록 대신 빌드 시작 시 스키마와 파일명 패턴으로 매니페스트를 만든다.

- `item*.ies`라는 이름만으로 자동 포함하지 않는다. 공통 필드와 역할별 스키마 서명을 만족하는
  파일만 후보로 탐색하고, 스키마가 일치해도 역할이 미분류면 리포트 후 빌드를 실패시키고
  명시적으로 승인한다.
- `item_equip*.ies`는 실제 경로를 정규화해 중복 제거한다.
- `item_goddess_reinforce(_<level>)?.ies`에서 레벨을 추출한다.
- `directoryDictionary()`의 동일 소문자 파일 선택 버그와 클래스 공유 `file_dict`를 먼저 고쳐야 매니페스트가 결정적이다.
- 이번 입력에서 누락된 `item_petequip.ies` 22개와 레벨 550이 테스트 케이스가 된다. 펫 장비는 공통 Item/Equipment 스키마를 만족하지만 사이트 분류와 노출 정책은 별도 결정한다.

### 2. 원본과 정규화 결과를 함께 둔다

각 엔터티를 다음처럼 나누면 새 콘텐츠에 대응하기 쉽다.

```json
{
  "id": "...",
  "class_name": "...",
  "tooltip_type": "ARK",
  "base": {},
  "requirements": {},
  "static_options": [],
  "growth": {},
  "references": {},
  "raw": {
    "source_file": "item_Equip_EP13.ies",
    "fields": {}
  }
}
```

`raw`는 모든 열을 무조건 공개하라는 뜻이 아니다. 툴팁과 링크에 쓰이는 원본 필드와 출처를 보존해, 파생 값 오류를 추적할 수 있게 하자는 의미다.

### 3. ID 네임스페이스를 분리한다

Item과 Recipe의 `ClassID`는 서로 다른 IES 클래스의 키라 전역 유일하지 않다. 현재처럼 하나의 `items` dict에 숫자만 키로 쓰면 충돌한다.

가능한 장기 설계는 다음과 같다.

- `items`, `recipes`, `collections`를 별도 컬렉션으로 분리한다.
- 호환성이 필요하면 내부 키를 `Item:10006`, `Recipe:10006`처럼 만들고, 원본 `ClassID`를 별도 필드로 둔다.
- 외부 API의 기존 숫자 ID를 유지해야 한다면 `(table, ClassID)` 복합 유일 키를 DB에 추가한다.

`ITEM_IES`가 `set`이라 순회 순서도 보장되지 않으므로, 현재 충돌 시 어느 레코드가 `items.json`에 남는지 비결정적이다. 파일 우선순위를 명시하거나, 충돌을 빌드 오류로 처리해야 한다.

현재 코드에 가장 작은 호환성 변경은 실제 Item의 기존 숫자 `ids`는 유지하고 Recipe만
`recipe-<ClassID>` 같은 slug 호환 내부 ID를 쓰는 전환안이다. 원본 `ClassID`와 `source_table`은
별도 필드에 보존하고 둘에 유일 제약을 둔다. `Recipe:<ClassID>`처럼 콜론을 쓰면 현재
`Items/urls.py`의 `<slug:id>`와 맞지 않으므로 URL 변경 없이는 사용할 수 없다. 어떤 안을 택하든
파서만 바꾸면 안 되고 importer의 비교 키, 기존 DB 행 마이그레이션, URL/API 호환 정책을 함께
확정해야 한다.

### 4. 툴팁 타입별 파서를 둔다

공통 필드 다음에 `ToolTipScp`별 어댑터를 실행한다.

- Item: ETC, CUBE, GEM, CARD, PACKAGE, RECIPE, 커스텀 툴팁
- Equipment: WEAPON, ARMOR, ARK, RELIC, BELT/SHOULDER, EARRING, CORE
- Skill: Active/Passive, casting category, hit type, resource, buff, level formula
- Ability: `Desc`/`Desc2`, 레벨별 효과, 추가 비용, 해금 조건

렌더링된 한국어 문장 하나만 저장하기보다 구조화 값과 번역 키를 같이 저장해야 다른 지역 데이터에도 재사용할 수 있다.

### 5. Lua 평가 실패를 데이터로 만든다

`except: pass`를 제거하고 다음을 빌드 리포트에 기록한다.

- 엔터티 ID와 원본 파일
- 함수명과 레벨
- 실패 종류: 함수 없음, 필드 없음, Lua 실행 오류, NaN
- 대체 값 사용 여부

공식이 원래 없는 경우는 `null`, 평가 실패는 `error`로 구분한다. 빈 배열 하나로 두 상태를 합치면 누락을 자동 탐지할 수 없다.

### 6. 패치버전별 JSON 관리와 DB 증분 적재 (보완안 재검증)

#### 판정

패치버전별 스냅샷, diff 리뷰, 롤백을 도입하자는 방향은 합당하다. 다만 “현재 DB가 매번 전량
재적재되므로 새 delta 체계가 필요하다”는 전제는 실제 코드와 다르다. `importAll.py:101-197`에
이미 현재 JSON과 `prev` JSON을 비교해 `added/changed/removed`를 만드는 `comparer`가 있고,
아이템·몬스터·맵·직업·특성·버프 등은 이 변경분만 ORM으로 저장한다.

따라서 권장 방향은 새 체계를 처음부터 만드는 것이 아니라 **기존 1세대 delta 구현을 고치고,
결정적 출력과 버전 이력을 추가하는 것**이다.

| 보완안 주장 | 코드 대조 결과 | 최종 판정 |
|---|---|---|
| JSON 뒤에서 MariaDB를 전량 재적재한다 | 대부분 `comparer` 결과만 저장 | 부정확, 문구 수정 필요 |
| 아이템 약 2.9만 개를 매번 `.save()` 한다 | 최초 적재 또는 모두 변경으로 판정될 때만 해당 | 일반 패치 설명으로는 부정확 |
| 자식 테이블을 delete 후 재삽입한다 | 변경된 장비·제작서·컬렉션에는 실제 수행 | 맞음 |
| 패치별 스냅샷이 필요하다 | 현재 `prev` 한 세대만 보관 | 합당 |
| 엔터티 해시/delta가 필요하다 | 객체 전체 비교 기반 delta가 이미 있음 | 대체가 아니라 개선안으로 합당 |
| DB 비용이 export보다 클 가능성이 높다 | DB 구간 프로파일링 결과 없음 | 측정 전에는 우선순위 확정 불가 |
| 중복 JSON을 인덱스로 바꾸면 절감된다 | 여러 `*_by_name`이 같은 값을 중복 저장 | 합당, 소비자 호환성 확인 필요 |

#### 실제 현재 비용

- 프로파일링의 export는 `DB.export()`가 data 컬렉션 36개를 전량 `json.dump`한 40.5초다.
- 현재 `JSON_ktos` 디렉터리는 JSON 44개, 약 204MiB다. `prev`도 약 204MiB이므로 디스크에
  현재+직전 버전이 약 408MiB 존재한다. 이것을 “한 번의 parser export가 407MB”라고 표현하면
  안 된다.
- 현재 JSON 44개를 gzip 스트림으로 압축한 실측 합계는 약 12.7MB다. 압축 효율은 좋지만,
  압축 시간·CPU와 랜덤 접근 불가를 운영 설계에서 함께 고려해야 한다.
- `importAll`은 비교할 때 현재와 `prev` JSON을 모두 `json.load`하고 전체 객체를 깊은 비교한다.
  DB 변경행이 적어도 JSON 읽기·메모리 할당·비교 비용은 항상 발생한다.
- 적재가 끝난 뒤 모든 JSON을 `prev`로 다시 복사한다(`importAll.py:258-262`). 이 복사 비용은
  기존 프로파일링에 포함되지 않았다.

DB import 시간을 따로 측정하지 않았으므로 `json.dump` 40.5초와 DB 적재 중 무엇이 더 큰지는
현재 근거로 단정할 수 없다. 다음 프로파일에서는 JSON load/compare, ORM query/save, 자식 테이블
재생성, `prev` 복사를 별도 단계로 계측해야 한다.

#### 기존 delta 구현에서 먼저 고칠 문제

1. **스킬은 delta 경로를 우회한다.** `handle()`은 `skills.json`을 `importJSON`으로 직접 읽고,
   `importSkills()`가 912개 전부를 `get + save`한다. 스킬도 `comparer`를 사용해야 한다.
2. **복합키 삭제가 불완전하다.** `comparer`의 복합키 분기(`importAll.py:188-191`)는 부모 키가
   현재 결과에도 있을 때 자식 키 삭제만 찾는다. 부모 키 자체가 사라진 경우 그 부모 아래 관계를
   `removed`에 넣지 않아 `item_monster`, `map_item`, `map_npc`, `map_item_spawn`에 고아 관계가
   남을 수 있다.
3. **변경된 자식행은 전량 재생성한다.** 장비 보너스, 제작 재료/대상, 컬렉션 재료/보너스는 부모가
   변경되면 기존 행을 전부 지우고 개별 `.save()`한다. 정확성은 단순하지만 변경량이 클 때 쿼리가
   많아진다. DB 프로파일 후 `bulk_create` 또는 자식 단위 diff를 선택한다.
4. **버전 성공 여부가 없다.** `Version.objects.get_or_create()`가 실제 import보다 먼저 실행되고,
   모델은 `version, created`만 가진다. 중간 실패 시 Dashboard에는 해당 버전이 기록됐지만 DB는
   일부만 반영된 상태가 될 수 있다.
5. **전체 작업 트랜잭션이 없다.** 엔터티별 예외를 광범위하게 삼키므로 부분 성공을 정상 완료처럼
   취급할 수 있다. 최소한 import run에 `pending/succeeded/failed`, 시작·종료 시각, 입력 해시,
   변경 건수와 오류 요약을 기록해야 한다.

#### 권장 진화 경로

1. P0의 입력 순서 결정성, ID 충돌, 큐브 링크 오류를 먼저 해결한다.
2. 기존 `comparer`를 공통 경로로 유지하면서 스킬을 포함한 모든 DB 대상에 적용하고 복합키 삭제
   테스트를 추가한다.
3. import 단위를 `transaction.atomic()`으로 감싸거나, 전체 원자성이 부담되면 컬렉션별 원자성과
   import run 상태를 도입한다. `Version`은 성공한 run만 현재 버전으로 노출해야 한다.
4. 현재의 `prev` 한 세대는 빠른 비교용으로 유지한다. 장기 보관이 필요하면 성공한 패치의 정식
   스냅샷만 `snapshots/<region>/<version>/`에 gzip으로 보관하고 최근 N개 보존 정책을 둔다.
5. 엔터티 해시 매니페스트는 기존 깊은 비교를 대체하는 2단계 최적화로 도입한다. 해시는 정렬과
   숫자/문자열 타입이 고정된 **최종 정규화 객체**에서 계산한다. importer가 전체 스냅샷을 읽지
   않게 하려면 파서가 매니페스트뿐 아니라 실제 `added/changed/removed` payload도 만들어야 한다.
6. MariaDB bulk upsert와 자식 단위 diff는 import 프로파일을 얻은 뒤 적용한다. 현재 자료만으로는
   parser의 `getMonbySkill`, 중복 장비 계산, export보다 높은 우선순위라고 판단할 수 없다.

#### 중복 JSON 정리

`monsters`/`monsters_by_name`, `skills`/`skills_by_name`, `attributes`/`attributes_by_name`,
`jobs`/`jobs_by_name`, `maps`/`maps_by_name`은 키만 다르고 값 집합은 같다. `items`만 앞서 설명한
49개 ID 충돌 때문에 `items_by_name`보다 값이 적다. 현재 크기만 보면 monsters 두 파일이 각각
약 58MiB, items 두 파일이 각각 약 33~34MiB라 중복 제거 효과가 크다.

P0에서 ID 충돌을 해소한 뒤 `by_id` 정규 데이터 하나와 `name -> id` 인덱스 하나를 내보내는 형태가
적절하다. 다만 현재 `importAll`은 `items_by_name.json`을 주 입력으로 사용하고, 지역 fallback은
`skills_by_name.json`의 완전한 객체를 기대한다. 저장 형식을 바꿀 때 이 소비 코드와 외부 소비자를
함께 마이그레이션해야 한다. 호환 기간에는 기존 파일을 생성하되 deprecated 표시를 두는 편이 안전하다.

고속 JSON 라이브러리도 실측 후 선택한다. `orjson`이 stdlib보다 빠를 가능성은 높지만 현재
환경에서 “export 40초를 거의 해결한다”는 측정값은 없다. 먼저 결과 의미 동등성 테스트와 동일
프로파일 드라이버로 wall-clock을 비교해야 한다.

## 구현 가능성 코드 기반 검증

### 최종 판정

**문서의 방향은 합당하지만 현재 내용 전체를 그대로 일괄 구현하면 안 된다.** 중복 장비 입력 제거,
결정적 순서, 기존 delta 보완, import run 상태는 설계대로 진행할 수 있다. 반면 ID 충돌, 큐브 링크,
가디스 550, 툴팁 스키마, 몬스터 스킬 인덱스, 장비 공식 캐시는 실제 코드 계약에 맞게 아래처럼
수정한 뒤 구현해야 한다. 특히 패키지 261개 오해석과 몬스터 EXP 역매핑은 새 기능보다 먼저
고칠 현재 데이터 오류이고, 원자적 결과 공개 없이는 이후 변경의 안전한 배포를 보장할 수 없다.

이 절은 구현 승인 여부만 검증한 결과이며, 이번 리뷰에서는 파서·Django 코드를 변경하지 않았다.

| 문서 항목 | 코드 기반 판정 | 구현 전 조건 |
|---|---|---|
| 장비 IES 대소문자 중복 제거 | 그대로 가능 | 소문자명뿐 아니라 `realpath` 중복 assert, 전후 장비 10,171개 의미 동등성 |
| `ITEM_IES`를 결정적 list/tuple로 변경 | 그대로 가능 | 파일 우선순위 고정, 충돌을 마지막 값 승리로 처리하지 않기 |
| 입력 매니페스트 자동 생성 | 수정 후 가능 | 역할별 스키마 허용 목록과 미분류 실패 정책, `file_dict` 결정성 선행 수정 |
| 큐브 링크 조건/키 오타 수정 | 수정 후 가능 | `StringArg -> cube 목록` 구조, 링크 중복 제거, `Type=CUBE` 유지 |
| 패키지 구성물 파서 | 현재 구현 보완 필수 | `item/count/(property/value)*` 문법과 GROWTH 분리, 261개 잘못된 참조 제거 |
| Item/Recipe ID 네임스페이스 | 선행 설계·마이그레이션 필요 | canonical ID, DB 유일 제약, importer 비교 키, URL/API 호환 동시 변경 |
| 가디스 550 자동 반영 | 수정 후 가능 | 강화 수치 IES와 재료 그룹을 분리해 발견; 550은 accessory 전용으로 처리 |
| `item_petequip.ies` 포함 | 제품 결정 필요 | 22개를 일반 장비/펫 장비 중 어디에 노출할지와 API 분류 확정 |
| 공통 툴팁 원본 필드 추가 | 수정 후 가능 | 기존 JSON에 additive 추가 후 모델·migration·importer·serializer/화면까지 연결 |
| ARK/RELIC/BELT/EARRING/CORE 파서 | 수정 후 가능 | 타입별 보조 IES/Lua 입력과 정적/인스턴스 필드 경계 명세 |
| AdditionalOption 툴팁 | ktos 연결은 가능·구조 보완 필요 | 611/611 연결 유지, 원본 키/슬롯/번역 fallback 상태 보존 |
| `skill_common`/`skill_ancient` 제공 | 별도 데이터셋이면 가능 | 플레이어 스킬 912개와 DB/API를 섞지 않기 |
| CaptionRatio 퍼센트 보정 | 한 계층으로 통합 필요 | parser 또는 importer 한 곳만 소유, 작은 소수 회귀 테스트 |
| Lua 실패를 리포트 | 단계적으로 가능 | 먼저 baseline/허용 목록을 만들고, 즉시 모든 경고를 빌드 실패로 바꾸지 않기 |
| `getMonbySkill` 인덱스 | 정확성 수정과 함께 가능 | 기존 중복 결과 제거를 승인된 diff로 고정 |
| 몬스터 EXP/JOBEXP 보정 | 즉시 수정 가능 | 역매핑 불일치 0건 완료 조건과 골든 diff, 기본/지역 보정 필드 의미 통일 |
| 맵별 몬스터 스탯 | 별도 데이터셋 설계 필요 | 17개 다중 값부터 `map_monsters`로 보존 |
| 비-iTOS 지역 드롭 링크 | provenance 조건부 가능 | iTOS fallback 명시, 패치버전/누락 참조 검증 |
| 중복 `luautil.init` 제거 | 검증 후 가능 | 초기화 guard와 전체 JSON 의미 동등성 테스트 |
| 장비 공식 메모이제이션 | 현재 설계로는 불가 | Lua가 읽는 행 필드 전체를 계측해 완전한 캐시 키를 먼저 정의 |
| 변경분만 export | 수정 후 가능 | 최초/clean build는 전량 출력, 증분 build는 원자적 임시 파일 교체 |
| 스킬 delta/복합키 삭제 수정 | 그대로 가능 | comparer 단위 테스트와 변경 없는 import의 ORM write 0건 확인 |
| `*_by_name`을 인덱스로 축소 | 소비자 마이그레이션 후 가능 | importer와 지역 fallback을 먼저 새 형식에 대응, 호환 파일 유지 기간 설정 |
| 패치 스냅샷/import run 상태 | 그대로 가능 | 성공 시에만 `prev`와 현재 버전 전환, 보존 정책과 원자성 범위 명시 |
| parser 결과/버전 공개 | 완료 | 즉시 범위(조기 skills export 제거·버전 파일별 임시 쓰기/원자 교체·cron 실패 중단)와 설계 후 범위(staging 디렉터리 일괄 승격·`version.json` 마지막 교체) 모두 구현됨 |

### 판정 근거와 필수 설계 수정

#### 1. 입력 발견부터 결정적이지 않다

`DB.py:71`, `DB.py:76`의 `file_dict`와 `data`는 인스턴스가 아닌 클래스 가변 상태다. 같은 프로세스에서
여러 `ToS_DB`를 만들면 이전 지역/빌드 상태가 남을 수 있다. 또한 `directoryDictionary()`의
`if`와 `else`가 모두 새 경로를 대입하므로(`DB.py:191-194`) 주석과 달리 최신 mtime을 선택하지 않고
`os.listdir()` 순회에서 마지막으로 만난 파일을 선택한다.

따라서 자동 매니페스트보다 먼저 다음이 필요하다.

1. `file_dict`와 `data`를 빌드마다 새로 만드는 인스턴스 상태로 옮긴다.
2. 디렉터리 순회를 정렬하고 동일 소문자명 충돌 시 선택 규칙을 적용하거나 빌드를 실패시킨다.
3. Item/Equipment/Goddess/Pet Equipment별 필수 열 서명을 검사한다.
4. `item*.ies`라는 이름만으로 일반 Item 파서에 자동 투입하지 않는다.

`item_petequip.ies`는 190개 열을 가진 Equipment 계열 스키마이고 22행 모두 현재 결과에 없다.
기술적으로 `parse_items + parse_equips` 대상이 될 수 있지만 `GroupName=PetWeapon` 같은 별도 분류를
일반 장비로 노출할지는 제품 계약이므로 자동 포함 대상은 아니다.

#### 2. Item/Recipe ID 수정은 파서 단독 변경이 아니다

현재 `Items.ids`는 `CharField(max_length=30, db_index=True)`일 뿐 유일 제약이 없지만
`importAll.py:269,280,336`, `Items/views.py:170`은 모두 `objects.get(ids=...)`로 유일하다고 가정한다.
`comparer()`도 `$ID` 하나로 dict를 만들어 현재/prev 양쪽에서 같은 ID의 다른 엔터티를 다시
덮어쓴다. JSON 키만 바꾸고 객체 안의 `$ID`를 유지하면 DB 손실은 해결되지 않는다.

구현 시 canonical ID를 JSON 객체와 comparer/DB에 끝까지 전달해야 한다. 최소 전환안은 다음과 같다.

- 실제 Item은 기존 숫자 ID를 유지한다.
- Recipe는 `recipe-10006` 같은 내부 ID를 사용하고 원본 ID는 `class_id=10006`으로 보존한다.
- `(source_table, class_id)` 유일 제약과 canonical `ids` 유일 제약을 추가한다.
- importer, 삭제 로직, Recipe 관계 생성, URL/API 테스트를 같은 배포에 포함한다.
- 기존 숫자 recipe URL을 사용한 외부 소비자가 있는지 확인하고 필요하면 redirect/호환 조회를 둔다.

별도 `recipes` 컬렉션과 모델로 완전히 분리하는 안도 더 깨끗하지만 현재 `Recipes`가 `Items`의
OneToOne 자식이고 재료/대상 관계가 이를 참조하므로 작은 P0 수정이 아니라 별도 마이그레이션 작업이다.

#### 3. 큐브 수정은 두 줄 패치보다 범위가 크다

잘못된 선행 조건 제거와 `'$ID_NAME'` 수정은 필요하지만 충분하지 않다. 현재
`cubes_by_stringarg[row['StringArg']] = obj`는 같은 `StringArg`의 이전 큐브를 덮어쓴다. 실제
큐브 1,044개에서 `StringArg` 그룹은 788개이며, 두 개 이상의 큐브가 공유하는 그룹이 65개다.
`reward_indun`과 일치하는 116개 그룹은 큐브 117개에 연결되어야 한다.

따라서 `StringArg -> list[cube]`로 인덱싱하고 각 reward 행을 해당 큐브 모두에 연결해야 한다.
링크는 stable dedupe하고 누락 Item만 fallback으로 보내야 한다. 현재 원본 타입은 `CUBE`인데 링크
코드가 `Cube`로 바꾸므로, DB 검색/분류 호환을 위해 `Type`은 `CUBE`로 유지하고 `item_type.CUBES`만
분류 인덱스로 사용한다.

#### 4. 가디스 550은 accessory 전용이다

`item_goddess_reinforce_550.ies`는 실제로 존재하고 30행이지만 540 파일의 10열과 달리
`BasicProp, AddAccAtk, BasicAccAtk` 중심의 5열만 가진다. 게임 Lua도 `equip_end_lv=550`으로 두면서
`setting_lv_material_acc()`에만 550 분기를 제공한다. armor/weapon 재료 분기는 540까지다.

따라서 강화 수치 IES 파일 레벨과 재료 지원 그룹을 별도로 탐지해야 한다. 550에 빈 armor/weapon
30단계를 생성하거나 단순히 기존 짝/홀수 목록 끝에 넣는 구현은 잘못이다. 기대 결과는
`goddess_reinf[550]` 30행과 `goddess_reinf_mat[550].acc`이며, 지원되지 않는 그룹은 빈 dict보다
명시적인 `null/not_supported`가 안전하다.

#### 5. 툴팁 필드는 end-to-end로 추가해야 한다

현재 importer가 Item에서 새 구조 필드로 저장하는 것은 최근 추가된 `PackageContents`뿐이고
(`importAll.py:302,359`), 모델도 이에 대응하는 `package_contents`만 있다. Skill importer 역시
고정 필드만 대입하며 Django Item/Skill serializer는 모델의 `fields='__all__'`을 내보낸다. 따라서
파서 JSON에 `UsageDesc`, `CastingCategory`, 전용 장비 구조를 추가하는 것만으로 사이트/API에는
노출되지 않는다.

호환성 있는 순서는 다음과 같다.

1. 기존 top-level JSON 계약을 유지한 채 `Tooltip`/`RawTooltip`을 additive로 추가한다.
2. 자주 검색할 필드는 명시적 DB 열로, 가변 타입별 구조는 현재 스택 관례에 맞춘 JSON 문자열
   `TextField`로 저장한다.
3. migration과 importer mapping을 추가한 뒤 serializer 응답과 HTML 렌더링을 연결한다.
4. 대표 골든 샘플로 JSON, DB, API, 화면 네 층을 검증한다.
5. 호환 기간이 끝난 뒤에만 문서의 새 정규화 형태를 기본 계약으로 전환한다.

#### 6. 성능 항목 중 두 개는 의미 변경을 동반한다

`getMonbySkill()`의 두 번째 루프가 첫 결과를 중복 추가하던 문제는 stable dedupe와 fallback 조건
수정으로 해결됐다. 현재 `skill_mon.json` 6,277개 엔트리의 중복 Monster ID는 0건이다.
다만 매 호출마다 전체 몬스터를 순회하므로 사전 인덱스를 이용한 성능 최적화는 남아 있다.

장비 공식은 `RefreshScp` 실행으로 원본 row가 먼저 변하고, 강화/초월 Lua가 `ItemGrade`, `UseLv`,
`ClassType`, `BasicTooltipProp` 외 여러 필드를 동적으로 읽는다. 문서에 예시된 소수 필드만 캐시 키로
사용하면 서로 다른 장비 곡선을 잘못 공유할 수 있다. Lua attribute getter로 실제 접근 필드를
계측하거나, 공식 입력의 완전한 정규화 projection을 정의하기 전에는 메모이제이션을 구현하지 않는다.

중복 `luautil.init`은 `main.py`와 `items.parse()` 양쪽에 존재하지만 전역 Lua runtime과 IES 테이블을
재구성한다. 단순 삭제보다는 initialized 상태/지역 키 guard를 두고 ktos/itos 대표 빌드의 전체 JSON
의미 동등성을 확인하는 방식이 안전하다.

#### 7. 새로 추가된 보정 로직도 단일 책임이 필요하다

`CaptionRatio*` 퍼센트 변환은 parser가 단독 소유하도록 정리됐고 importer는 정수 저장만 수행한다.
작은 소수 합성 fixture와 ktos DB 통합 테스트를 포함해 이중 확대가 없음을 확인했다. 다만 parser가
0.5 같은 정규화 결과를 만들면 importer의 정수 변환에서 0이 될 수 있으므로 소수 보존/반올림 정책은
별도 데이터 계약으로 정해야 한다.

fallback Item은 `ClassName`의 MD5 앞 24비트를 숫자로 바꿔 `$ID`로 쓴다(`items.py:41-50`). 현재
7개 fallback끼리 또는 기존 결과와의 충돌은 없지만, 실제 Item/Recipe ID 공간과 같은 dict를 쓰면서
충돌 검사가 없다. canonical ID 도입 전이라도 `fallback-<hash>`처럼 별도 namespace를 사용하고
충돌 시 빌드를 실패시켜야 한다.

#### 8. 결과 공개 순서가 성공 원자성을 깨뜨린다

착수 전에는 iTOS 스킬 조기 export와 잘못된 버전 갱신 순서가 있었다. 현재는 조기 export를 제거했고,
공개 릴리스는 staging·검증 후 파일별 원자 교체(`os.replace`)와 백업·롤백을 수행하는 **일괄 승격**으로
바뀌었다. cron 5개도 parser 실패 시 DB import를 중단한다.

**구현 상태.** `c.export(version_payload=v)`는 모든 JSON 컬렉션을 입력 디렉터리와 분리된 형제
staging 디렉터리(`JSON_<region>.staging/`)에 완전히 직렬화하고 각 파일을 역직렬화 검증한 뒤,
전체 성공 시에만 공개 파일을 교체한다. `version.json`도 같은 staging 에 쓰므로 JSON 컬렉션과
`version.json`은 항상 함께 승급되어 일관되게 귀결된다. 교체 도중 하나라도 실패하면 백업에서
공개 릴리스를 전부 구버전으로 되돌리고(신규 파일은 공개에서 제거), 롤백마저 불완전하면
사전 sentinel(`.promotion-in-progress`)이 백업을 비어 있지 않게 보장해 다음 실행이 중단된다.
정상 종료 또는 복구 가능한 실패 후의 **최종 상태 일관성**을 보장한다.

단, 이것은 디렉터리 포인터를 한 번에 교체하는 의미의 원자적 승급은 **아니다**.
`BASE_PATH_OUTPUT`이 고정 디렉터리를 직접 가리키므로 디렉터리 단위 교체(symlink)는 도입하지
않았고, 파일별 `os.replace`를 순회하므로 교체 진행 중에는 일시적으로 신구 혼합 상태를
관찰할 수 있다(최종 상태는 전부 신버전 또는 전부 구버전 둘 중 하나로만 귀결).
importer는 cron이 parser 전체 성공 후에만 실행되므로 혼합 관찰 창에 도달하지 않는다.

**버전 파일 갱신 순서와 보장 범위.** `parser_version.csv`는 `SCRIPT_DIR`의 별도 파일로
`export()` 트랜잭션 **외부**에서 먼저 갱신되고, 이어 `c.export(version_payload=v)`가
`version.json`을 JSON 승급 트랜잭션에 통합한다. 따라서 JSON 컬렉션과 `version.json`은
일관 귀결하지만, `parser_version.csv`는 트랜잭션 외부라 `export()` 실패 시
(csv만 신버전) 일시적 불일치가 생길 수 있다. 이 불일치는 시작 조건 검사가 다음 실행에서
재시도를 강제하므로 자가 회복된다(`main.py`의 commit-incomplete 가드).
`parser_version.csv`, DB의 현재 Version, `prev` 전환은 공개 성공 이후 같은 run 상태를
기준으로 갱신한다.

### 구현 승인 게이트

다음 순서로 나누면 각 단계는 구현 가능하다.

1. **기준선 고정:** 현재 개수, 49개 충돌 목록, 큐브 그룹, 패키지 오류 261개, 몬스터 EXP 역매핑 목록(개수가 아닌 `ClassName`+원본 값 목록), 중복 skill-mon, 대표 툴팁을 fixture로 저장한다.
2. **결정성/공개 안전성:** 인스턴스 상태 초기화, 입력 정렬, 장비 경로 중복 제거, 그리고 공개 안전성의 즉시 범위(조기 export 제거, 버전 파일별 임시 쓰기/원자 교체와 갱신 순서 교정, cron 실패 중단)를 적용한다. 완전한 원자적 승격은 릴리스 방식 결정 후로 미룬다.
3. **파서 정확성:** 패키지 문법, 몬스터 EXP, 큐브 다중 매핑, skill-mon stable dedupe, 가디스 550 acc를 각각 별도 승인 diff로 적용한다.
4. **ID 마이그레이션:** canonical ID 계약과 DB/API 전환안을 먼저 확정한 뒤 49개 Recipe 손실을 복구한다.
5. **툴팁 수직 구현:** 한 타입씩 parser → JSON → importer → model → API/화면을 끝까지 연결한다.
6. **최적화/운영:** Lua 초기화와 공식 캐시는 동등성 테스트 후, delta/run 상태/snapshot은 실패 복구 테스트 후 배포한다.

즉, P0~P3의 우선순위 틀은 유지할 수 있지만 위 게이트를 통과하지 않은 항목을 같은 변경 묶음으로
구현하는 것은 승인하지 않는다.

## 구현 착수 판정 (2026-07-22)

최종 판정: **기준선 테스트와 실행 중단 안전장치부터 구현 시작 가능.** 전체 계획의 일괄 진행은
승인하지 않으며, 아래 즉시 착수 범위만 게이트 1~3 순서로 진행한다.

### 즉시 착수 가능한 범위

1. **패키지 파서 fixture 작성 및 토큰 문법 수정**
   - 대부분 `item/count/(property/value)*` 규칙과 일치한다.
   - GROWTH 6건은 지금은 감지·분리·경고·보고까지만 구현한다. 현재 코드는 `items.py:125-132`에서
     일반 형식 불일치로 스킵만 하므로, `_SPLIT_GROWTH` 스크립트를 명시 분기해 미해석 범주
     (`growth_selection`)로 기록하되 구성물 목록은 생성하지 않는다. 실제 해석은 선택 규칙
     확정 후 진행한다.
   - 선행 `/`가 잘못 들어간 원본 1건(`item_premium.ies`의 `JPN_2212package_Reward`,
     `StringArg` 두 번째 토큰 `/Multiple_Token_TurbulentCore_Auto_NoTrade/10`)은 경고 후
     복구하거나 명시적으로 제외한다.
2. **몬스터 `EXP`/`EXPClass` 역매핑 수정**
   - 145~147 같은 개수가 아니라 원본 `EXP`↔출력 `EXP`, 원본 `JOBEXP`↔출력 `EXPClass`
     불일치 0건을 완료 조건으로 사용한다.
3. **장비 IES 중복 제거**
4. **큐브 다중 매핑과 `skill_mon` 중복 제거**
   - 둘 다 승인된 의미 변경 fixture가 필요하다.
5. **CaptionRatio 변환을 parser 또는 importer 한 곳으로 통합**
6. **장비 ItemGrade 빈 값·유효 범위 방어**
   - 현재 ktos 10,171행에는 빈 값이 없으므로 합성 fixture와 기존 출력 동등성 검증을 먼저 둔다.

### 착수 전에 반드시 필요한 안전장치

- **현재 상태 스냅샷 고정.** 현재 브랜치의 변경 파일이 4,048개이고 이번 수정 대상 파일도 이미
  수정돼 있다. 별도 commit/worktree 또는 복구 가능한 스냅샷으로 고정해야 새 변경의 diff를
  신뢰할 수 있다.
- **기준선 fixture 선작성.** 실질적인 parser 자동 테스트가 없다. 본 문서의 기준선 수치
  (49개 충돌, 큐브 그룹 116/117, 패키지 오류 261, EXP 역매핑, 중복 skill_mon 등)를 fixture로
  먼저 만든다.
- **cron 실행 중단 안전장치.** `cron_itos/jtos/ktos/ktest/twtos.sh` 다섯 개 모두
  `python main.py <region>` 실패 여부와 무관하게 `manage_<region>.py importAll`을 이어서
  실행한다(예: `cron_ktos.sh:74-85`). parser/import 반환 코드를 검사해 실패 시 즉시 중단하도록
  고친다.
- **공개 파일 즉시 안전장치.** iTOS 조기 skills export를 제거하고, `c.export()` 전체 성공 후에만
  `version.json`과 `parser_version.csv`를 각각 같은 디렉터리의 임시 파일에 완전히 쓴 뒤
  `flush/fsync`와 `os.replace`로 교체한다. 이는 버전 파일별 손상을 막는 즉시 조치이며 전체 JSON의
  완전한 원자적 승격을 대신하지 않는다.

### 설계 확정 후 착수할 항목

- Item/Recipe canonical ID와 DB/API 마이그레이션
- 맵별 몬스터 데이터 모델(`map_monsters`)
- 펫 장비 노출 정책
- GROWTH 패키지의 실제 선택 규칙
- 전체 툴팁 정규화 스키마
- 원자적 릴리스 디렉터리 전환 — **완료.** `export()`가 `JSON_<region>.staging/` 형제 디렉터리에
  모든 JSON을 직렬화·검증한 뒤 전체 성공 시에만 `os.replace`로 공개 파일을 일괄 교체한다.
  `JSON_ROOT` 고정 참조와 `prev/` 위치는 그대로 유지(parser/importer 경로 변경 없음).
  `version.json`을 가장 마지막에 교체해 커밋 완료 표시로 사용한다.

### 최종 고정 전 정리 4건 처리 (2026-07-22)

최종 판정에서 지적된 4건을 코드 확인 후 다음과 같이 처리해 본문에 반영했다.

1. **매니페스트 문장 중복** — "권장 설계 1"에서 자동 포함 금지와 스키마 서명 탐색을 말하던
   중복 항목 두 개를 하나로 병합했다.
2. **EXP 완료 조건 통일** — 고정 개수(147개) 표기를 본문 전체에서 제거하거나 "병합 순서에 따라
   145~147로 변동하는 스냅샷"으로 명시하고, 수정·검증 기준은 모두
   `field_monster_status*` 대상 전체의 원본 `EXP`↔출력 `EXP`, 원본 `JOBEXP`↔출력 `EXPClass`
   **불일치 0건**으로 통일했다. 기준선 fixture도 개수가 아닌 `ClassName`+원본 값 목록으로 저장한다.
3. **GROWTH 단계 구분** — 현재 코드는 GROWTH 토큰을 `items.py:125-132`의 일반 형식 불일치
   경고로만 스킵하므로, 착수 범위를 "`_SPLIT_GROWTH` 스크립트 명시 분기 → 미해석 범주
   (`growth_selection`) 기록·보고, 구성물 미생성"까지로 한정하고 실제 해석은 선택 규칙 확정 후로
   미룬다고 본문(즉시 착수 범위, P0-1, 검증 체크리스트)에 명시했다.
4. **원자적 공개 이원화** — 즉시 범위(조기 skills export 제거 `main.py:88-94`,
   `c.export()` 성공 후 두 버전 파일을 개별 원자 교체하고 `version.json` → `parser_version.csv`
   순서로 갱신 `main.py:34-39,112-118`,
   `cron_*.sh` 5개의 반환 코드 검사·실패 중단)와 설계 후 범위(임시 빌드 디렉터리 일괄 승격 —
   `JSON_ROOT` 고정 참조와 `prev/` 위치 때문에 symlink 방식 또는 `--json-root` 선결정 필요)로
   분리해 P0-3, 승인 게이트 2, 판정 근거 8, 판정 표를 모두 이원화 기준으로 고쳤다.

### 3차 재검증 보완: 즉시 안전조치의 한계 (2026-07-22)

재검증에서 위 4번의 단계 분리는 타당하지만, 즉시 범위의 보장 수준을 과도하게 표현한 문장이
확인됐다. `version.json`을 먼저 쓰고 `parser_version.csv` 쓰기가 실패하면 전자는 이미 전진하며,
`DB.py:158-161,243-247`의 `c.export()`도 JSON을 하나씩 현재 디렉터리에 직접 덮어쓴다. 따라서
쓰기 순서 교정만으로 "실패 시 공개 JSON과 두 버전 파일 중 어느 것도 전진하지 않는다"고 보장할
수 없다.

즉시 범위의 정확한 보장은 다음과 같다.

- `c.export()`가 실패하면 `version.json`과 `parser_version.csv` 갱신 단계에 진입하지 않는다.
- 두 버전 파일을 각각 임시 파일에 완전히 쓴 뒤 `os.replace`하고, `version.json` 후
  `parser_version.csv` 순서로 교체하면 마지막 교체 실패 시 `parser_version.csv`가 온전한 구버전으로
  남아 다음 실행이 빌드를 다시 시도하게 한다. 현재 `open(..., 'w')` 직접 쓰기만 유지하면 실패 시
  빈 파일이나 부분 파일이 남을 수 있으므로 이 보장은 성립하지 않는다.
- cron이 parser의 비정상 종료를 확인하면 혼합 결과를 DB로 import하지 않는다.
- 이미 직접 덮어쓴 공개 JSON과 먼저 갱신된 `version.json`의 롤백까지는 보장하지 않는다.

공개 JSON, `version.json`, `parser_version.csv`가 실패 시 모두 기존 상태를 유지한다는 완료 조건은
임시 릴리스 디렉터리 생성·검증 후 일괄 승격을 구현한 **설계 후 범위**에만 적용한다. 따라서 구현
착수는 계속 승인하지만, 즉시 안전조치를 완전한 원자적 공개로 간주해서는 안 된다.

### 외부 리뷰 재검증 판정 (2026-07-22)

외부 리뷰가 확인한 `c.export()`의 파일별 직접 덮어쓰기, 공개 JSON 롤백 비보장, cron 중단의 DB
유입 차단, 완전 무전진 조건의 설계 후 분리는 코드와 일치한다. 따라서 3차 재검증의 핵심 결론과
구현 착수 승인은 유효하다.

다만 "`parser_version.csv` 쓰기 실패 시 구버전으로 남고 다음 실행에서 자가 복구한다"는 평가는
**버전 파일을 개별적으로 원자 교체할 때만** 성립한다. 현재 `main.py:34-39`의 `print_version()`과
`main.py:117-118`의 `version.json` 저장은 모두 공개 파일을 `open(..., 'w')`로 직접 잘라낸 뒤 쓴다.
쓰기 도중 예외가 발생하면 구버전이 보존되지 않고 빈 파일 또는 부분 파일이 남을 수 있으며,
`read_version()`이 다음 실행에서 정상적인 지역 버전을 읽는다는 보장도 없다.

따라서 즉시 안전조치에 두 버전 파일 각각의 `임시 파일 완전 쓰기 → flush/fsync → os.replace`를
포함한다. 이는 각 파일이 항상 구버전 또는 신버전 중 하나로 남도록 하지만 두 파일과 전체 JSON을
하나의 트랜잭션으로 만들지는 않는다. 전체 결과의 원자성은 기존 판정대로 임시 릴리스 디렉터리
일괄 승격 단계에서만 완료된다. 이 조건을 반영한 뒤에는 문서를 구현 착수용 최종본으로 고정해도 된다.

### 4차 보완: 기존 리뷰 누락 후보 (2026-07-22, 5차 재검증 반영)

지금까지의 리뷰가 다루지 않은 코드 경로에서 후보 6건을 추가 대조했다. 후속 5차 재검증 결과
1·2·3·5·6번은 코드와 출력으로 확인됐고, 4번의 `revision.csv` CWD 의존 주장은 기각됐다.

1. **경험치 데이터셋이 전혀 생성되지 않는다.** `exp.py`에 `parseChar`(`xp.ies`)와
   `parsePetAssister`(`pet_exp.xml`)가 구현돼 있고 두 원본 파일 모두 `ktos_unpack`에 실재하지만,
   `main.py`는 `exp` 모듈을 import조차 하지 않는다. 그 결과 `DB.data`에 선언된
   `charxp`/`petxp`/`assisterxp`는 매 빌드 빈 `{}`로 export되며(`charxp.json` 등 현재 JSON 확인),
   importer 소비 경로도 없다. 처리: 레벨별 경험치를 사이트에 노출할 것인지 제품 결정 후,
   노출한다면 `main.py`에 두 함수를 연결하고 출력 계약(list)을 정의하며, 노출하지 않는다면
   `data` 스키마와 export 대상에서 제거해 죽은 파일 3개를 없앤다.
2. **standalone 실행 경로 5곳이 전부 깨져 있다.** `DB.build(region, base_path)`는 인자 2개가
   필수인데 `items.py:151`·`exp.py:16`·`parse_xac.py:16`은 `c.build("itos")` 한 개 인자로,
   `monsters.py:55`는 `c.build()` 무인자로 호출한다. `attributes.py:89`는 존재하지 않는 속성
   `constants.iTOS`를 참조하고, `monsters.py:56`·`attributes.py:90`은 인자가 필수인
   `luautil.init()`을 무인자로 호출한다. 이 `c == None` fallback은 어느 경로든 즉시
   TypeError/AttributeError로 죽는 데드 코드다. 처리: 결정성 게이트(인스턴스 상태 정리)와 같은
   변경 묶음에서 시그니처를 맞춰 살리거나 fallback 자체를 제거해 모듈 단독 실행을 금지한다.
3. **맵 이미지 전처리가 Python 2.7에 묶여 있다.** `map_image.py`는 `#!/usr/bin/env python2`
   스크립트이고(2행에 있어 shebang으로도 동작하지 않음) `main.py:107` 주석은
   "py2.7로 먼저 실행"을 전제한다. `maps.parse_maps_images()`는 이 사전 산출물이 있어야
   동작하지만 이 운영 전제가 리뷰와 운영 문서 어디에도 없었다. 처리: 입력 매니페스트/운영
   문서에 전제 조건으로 명시하고, 장기적으로 Python 3 포팅을 P2에 둔다.
4. **`revision.csv`는 CWD 의존이 아니다(5차 재검증에서 기각).** `main.py:69`가
   `join("..", 'downloader', 'revision.csv')`를 전달하지만 `read_version()`은 `main.py:43`에서 이를
   항상 `SCRIPT_DIR`과 결합한다. 따라서 실제 경로는 실행 CWD와 무관하게 프로젝트의
   `downloader/revision.csv`로 해석되며 별도 수정이 필요 없다. 반면 `monsters.py:255`와
   `maps.py:166`의 `../itos_unpack`은 CWD 상대 경로이므로 기존 드롭 경로 개선 항목은 유효하다.
5. **importer의 `escaper()`는 데드 코드다.** `importAll.py:69`에 정의만 있고 호출이 0회이며,
   변환표가 쉼표를 빈 문자열로 치환하는 등 실사용 시 데이터를 훼손할 내용이다. 처리: 삭제한다.
6. **장비 Grade 보정 분기가 도달 불가다.** `items.py:368-370`은 `int(row['ItemGrade'])` 결과를
   `""`와 비교하지만 int 결과는 문자열일 수 없어 보정이 실행되지 않으며, `ItemGrade`가 실제로
   비어 있으면 그 전 `items.py:331`의 `int()`에서 예외가 난다. 처리: 빈 값 방어를 331행 이전으로
   옮기고 도달 불가 분기를 제거한다. 사소하지만 "Grade 기본값 1" 의도가 실제로는 동작하지 않음을
   기록해 둔다.

확정된 다섯 건은 기존 착수 판정을 바꾸지 않는다. 1·3번은 제품/운영 결정이 필요한 P1 성격이다.
2·5번은 후순위 코드 정리로 둘 수 있지만, 6번 Grade 빈 값 방어는 파싱 예외와 데이터 정확성에
직접 관련되므로 fixture를 먼저 둔 뒤 P0 정확성 작업으로 처리한다.

### 5차 재검증 판정 (2026-07-22)

문서 전체와 현재 코드를 다시 대조한 결과 구현 착수 판정은 계속 유효하다. 다만 4차 보완의
`revision.csv` CWD 의존 주장은 `read_version()`의 `SCRIPT_DIR` 결합을 놓친 오판이므로 구현
대상에서 제거했다. 실행 CWD 독립성 체크리스트는 실제 CWD 의존 경로인 드롭 입력과 기타 상대 경로를
대상으로 계속 유지한다.

또한 장비 Grade 보정은 `items.py:331`에서 `int(row['ItemGrade'])`를 먼저 수행하므로 빈 값이면
`items.py:368-370`의 기본값 분기에 도달하기 전에 실패한다. 이는 성능 정리가 아니라 정확성·예외
방지 작업이므로 P2에서 P0로 이동한다. 이 두 정정을 반영한 현재 문서는 조건부 구현 착수 기준으로
사용할 수 있다. 전체 계획의 일괄 구현은 여전히 승인하지 않으며 기준선 fixture와 안전장치부터
게이트 순서대로 진행한다.

### 6차 코드 검증: 5차 정정 2건 확인 (2026-07-22)

5차 재검증의 정정 두 건을 코드와 데이터로 재확인했다. 둘 다 유효하다.

1. **`revision.csv` 기각 확정.** `read_version()`은 `main.py:43`에서 인자를 항상
   `os.path.join(SCRIPT_DIR, filename)`으로 결합하므로 `join("..", 'downloader', 'revision.csv')`도
   실행 CWD와 무관하게 `SCRIPT_DIR` 기준 상위의 `downloader/revision.csv`로 해석된다. 4차 보완
   4번의 CWD 의존 주장은 이 결합을 놓친 오판이 맞고, 구현 대상에서 제외한 것이 옳다.
   `print_version()`도 같은 방식으로 `SCRIPT_DIR`을 결합함을 확인했다. 반면 드롭 경로
   (`monsters.py:255`, `maps.py:166`)는 `os.listdir`에 CWD 상대 경로를 그대로 넘기므로 실제 CWD
   의존이며, 체크리스트의 CWD 독립성 항목을 드롭 입력 대상으로 유지한 것도 맞다.
2. **Grade 빈 값 방어의 P0 이동 타당, 단 현재는 잠재 위험.** `items.py:331`의
   `int(row['ItemGrade'])`가 368-370의 기본값 분기보다 먼저 실행되는 것은 코드로 확인된다.
   추가로 현재 ktos 고유 장비 IES 4개 10,171행을 전수 확인한 결과 빈 `ItemGrade`는 0건이다.
   즉 지금 데이터로는 예외가 발생하지 않는 잠재 결함이며, P0-5는 "현재 손실 복구"가 아니라
   "미래 패치 데이터에 대한 예방" 성격이다. fixture는 빈 값 케이스를 합성 입력으로 추가해야
   하고, 기존 10,171행의 출력 동등성 확인이 회귀 기준이 된다.

P0-3에 반영된 버전 파일 개별 `os.replace` 교체(외부 리뷰 재검증 판정의 요구)도 본문과 일치함을
확인했다. 이 시점의 문서는 상호 모순 없이 정리된 상태로, 구현 착수용 최종본으로 고정할 수 있다.

### 7차 최종 재리뷰 및 구현 착수 판정 (2026-07-22)

최신 문서와 현재 코드를 다시 대조했다. 고유 장비 IES 4개는 6,768+2,144+835+424=10,171행이고
빈 `ItemGrade`는 0건으로 6차 집계와 일치한다. 현재 변경 파일은 여전히 4,048개이며 구현 대상인
`items.py`, `main.py`, `monsters.py`, `skills.py`도 이미 수정 상태다. cron 5개는 모두 parser 실패
후 import를 막는 guard가 없고, Django의 `tests.py` 12개는 총 36행의 기본 골격뿐이라 파서 회귀
테스트로 사용할 수 없다.

최종 판정은 **조건부 구현 착수 승인**이다. 다음 경계를 지키면 구현할 수 있다.

1. **착수 전 필수:** 현재 4,048개 변경 상태를 복구 가능한 스냅샷으로 고정한다. 이 조건을
   충족하지 않은 상태에서는 새 수정의 diff와 롤백을 신뢰할 수 없으므로 코드 변경을 시작하지 않는다.
2. **첫 변경 묶음:** 패키지, EXP, 큐브, `skill_mon`, Grade, CaptionRatio의 기준선·합성 fixture와
   실패 주입 테스트를 먼저 추가한다. fixture가 현재 오류를 실제로 검출하는지 확인한다.
3. **두 번째 변경 묶음:** 조기 skills export 제거, 버전 파일별 원자 교체, cron 실패 중단,
   입력 결정성과 장비 경로 중복 제거를 적용한다.
4. **이후 독립 변경:** 패키지 문법, EXP 역매핑, Grade 방어, 큐브 다중 매핑,
   `skill_mon` stable dedupe, CaptionRatio 단일 책임을 각각 승인 가능한 의미 diff로 구현한다.
5. **착수 보류:** canonical ID/DB/API 마이그레이션, GROWTH 실제 해석, 펫 장비 정책,
   `map_monsters`, 전체 툴팁 스키마, 릴리스 디렉터리 일괄 승격은 각 설계가 확정되기 전 구현하지 않는다.

따라서 기준선과 안전장치부터 시작하는 것은 승인하지만 P0 목록 전체를 한 번에 구현하는 것은
승인하지 않는다. 이 절의 단계 경계를 최종 착수 기준으로 사용한다.

### 8차 착수 직전 검증 (2026-07-22)

구현 착수 직전에 문서의 핵심 근거를 현재 worktree 코드와 다시 대조했다. 확인한 7건 모두
실제 코드·상태와 일치하며, 문서는 낡거나 과장된 상태가 아니다.

| 문서 주장 | 재확인 결과 |
|---|---|
| 변경 파일 4,048개 | `git status --porcelain` 정확히 4,048개 |
| `EQUIPMENT_IES` 대소문자 중복 2쌍 | `DB.py:33-38`에 `item_equip.ies`/`item_Equip.ies`, `item_event_equip.ies`/`item_event_Equip.ies` 그대로 존재 |
| iTOS 조기 skills export | `main.py`에 `if region == 'itos': printJSON(skills…)` 존재 |
| 버전 파일 갱신 순서·직접 쓰기 | `parser_version.csv`가 `version.json`보다 먼저 전진하고 둘 다 `open(..., 'w')` 직접 쓰기 — 일치 |
| 몬스터 EXP/JOBEXP 역매핑 | `monsters.py` 지역 보정 행에서 `EXP=JOBEXP`, `EXPClass=EXP` 대입 그대로 |
| ItemGrade 도달 불가 분기 | `int(row['ItemGrade'])` 선행 실행 후 `int` 결과를 `""`와 비교하는 죽은 분기 — 일치 |
| cron 실패 guard 부재 | `cron_ktos.sh`가 `python main.py ktos` 반환 코드 검사 없이 `importAll` 실행 — 일치 |

경로 정정 한 건: cron 스크립트 5개는 `parser_tidy/` 안이 아니라 **repo 루트**
(`/home/ubuntu/TavernofSoul/cron_*.sh`)에 있다. 수정 대상 파일 위치를 이 기준으로 잡는다.

**선행 조건 충족 상태:** 7차 판정의 착수 전 필수 조건 중 유일하게 미충족인 것은
"4,048개 변경 상태의 복구 가능한 스냅샷 고정"이다. 현재 `local-changes-backup` 브랜치에
변경들이 커밋되지 않은 채 남아 있고 별도 stash 1개(`stash@{0}`)도 존재한다. 따라서
**첫 작업은 코드 수정이 아니라 현재 상태의 커밋**이며, 그 전에는 어떤 파서/cron 수정도
시작하지 않는다.

커밋 이후 진행 순서는 7차 판정의 경계 그대로 사용한다.

1. 스냅샷 커밋 (미충족 → 최우선)
2. 기준선 fixture: 패키지 261건 오해석, EXP 역매핑(ClassName+원본 값 목록), 큐브 116/117,
   skill_mon 중복, Grade, CaptionRatio — fixture가 현재 오류를 실제로 검출하는지 먼저 확인
3. 안전장치: 조기 skills export 제거, 버전 파일 2개 개별 임시 쓰기+`os.replace`
   (version.json → parser_version.csv 순서), repo 루트 cron 5개 반환 코드 검사,
   `EQUIPMENT_IES` 중복 제거
4. 정확성 수정을 각각 독립 승인 diff로: 패키지 문법, EXP 역매핑, 큐브 다중 매핑,
   skill_mon stable dedupe, Grade 방어, CaptionRatio 단일 책임

착수 보류 항목(canonical ID/DB/API 마이그레이션, GROWTH 실제 해석, 펫 장비 정책,
`map_monsters`, 전체 툴팁 스키마, 릴리스 디렉터리 일괄 승격)은 7차 판정 그대로 유지한다.

### 현재 구현 상태 (2026-07-22)

| 범위 | 상태 | 검증 결과 |
|---|---|---|
| 기준선 fixture | 대부분 완료 | parser 테스트 75개 통과. 일부 항목은 실제 end-to-end보다 합성/소스 검증 중심 |
| 즉시 공개 안전성 | 완료 | 조기 export 제거, 버전 파일 개별 원자 교체, cron 5개 parser 실패 중단 |
| 장비 입력 중복 제거 | 완료 | `EQUIPMENT_IES` 4개와 realpath 중복 방지 적용. 성능 재측정은 미실시 |
| 패키지 파싱 | 부분 완료 | 후보 1,493개 중 코드 기준 1,486개 생성, 오해석 0건. 만료 이벤트 Item 참조 2건은 `PackageContents.unresolved`로 분리(가짜 fallback 금지). DB 직렬화는 구현됐으나 API/화면 구조화 렌더링은 미구현 |
| 큐브 링크 | 완료 | 116개 그룹이 공유 그룹을 포함한 117개 큐브에 연결 |
| 몬스터 EXP | 완료 | 지역 보정 출력 916개, EXP/EXPClass 불일치 0건 |
| skill-mon 정확성 | 완료 | 6,277개 엔트리 중 중복 0건. 사전 인덱스 최적화는 미구현 |
| ItemGrade 방어 | 완료 | 빈 값 기본값과 0~6 범위 fixture 통과 |
| CaptionRatio 단일 책임 | 완료 | parser 단독 변환, importer 단순 저장, DB 통합 테스트 통과 |
| 원자적 결과 공개 | 완료(최종 상태 원자성) | `export(version_payload)` staging 직렬화·검증 후 백업 copy + `os.replace` 일괄 교체. version.json 트랜잭션 통합(JSON/version 혼합 방지). 백업 copy 실패 시 공개 영향 없음. 교체 실패 시 백업 copy 기반 전체 롤백. 롤백 완전 성공·교체 전 실패 시 백업 폐기(다음 실행 자가 회복), 롤백 불완전 시에만 `.rollback-failed` 마커 + 백업 보존(다음 실행 중단). 시작 조건 불일치 검사로 자동 재시도. 한계: 교체 진행 중 일시적 신구 혼합 관찰 가능(최종 상태는 전부 신/구버전), importer는 cron으로 혼합 창 미도달 |
| 가디스 550 accessory | 완료 | `EQUIPMENT_REINFORCE_IES` 550 정적 등록 + file_dict 게이트(현재 지역에 파일 있을 때만 material/Lua acc 550 수행). acc-only 구조(armor/weapon 키 생략). `goddess_atk_list.clear()`/`goddess_reinf={}` stale 방어. 테스트 8개 통과 |
| 드롭 provenance | 완료 | `drop_source.py` 데이터셋 단위 fallback(iTOS 우선), `SourceRegion`/`InputVersion` 레코드 필드, `build_provenance`/`unresolved_drops` 컬렉션, 하드코딩 제거, 직접 zonedrop 유실·셰도잉·dropgroup 합계0 버그 수정. 테스트 19개 통과. 한계: importer 경로 버그 별도 태스크 |
| P0 후반 | 미구현 | canonical ID, 펫 장비 정책 |
| P1~P3 | 대부분 미구현 | 툴팁 수직 구현, 성능/증분 빌드, 운영 이력/롤백 |

검증 명령 기준으로 parser 테스트 145개가 통과했다(version.json 트랜잭션 통합 동작·롤백 copy 기반 백업
보존·공개 승급 os.replace 정확 카운트 교정·자가 회복 회귀 3건 등 신규 추가). Python 문법, cron shell 문법, `git diff --check`도 통과했다.
체크인된 `TavernofSoul/JSON_ktos/items.json`은 account_prop 수정과 unresolved 분리 전 산출물이므로
다음 전체 ktos 파서 성공 실행에서 갱신해야 한다.

## 구현 순서

### P0: 데이터 손실과 중복 계산 제거

1. 패키지 split 문법을 `item/count/(property/value)*`로 수정하고 261개 잘못된 참조를 제거한다. GROWTH는 미해석 범주로 감지·경고·보고까지만 수행하고 해석은 규칙 확정 후 진행한다.
2. 지역 보정 몬스터의 `EXP`/`EXPClass` 역매핑을 수정한다. 완료 조건은 개수가 아니라 `field_monster_status*` 대상 전체에서 원본 `EXP`↔출력 `EXP`, 원본 `JOBEXP`↔출력 `EXPClass` 불일치 0건이다.
3. 공개 안전성의 즉시 범위를 적용한다: iTOS 조기 skills export(`main.py:88-94`)를 제거하고, `c.export()` 전체 성공 후 두 버전 파일을 각각 임시 파일에 완전히 쓴 뒤 `os.replace`로 교체하며, cron 5개 스크립트가 parser 반환 코드를 검사해 실패 시 import를 중단하게 한다. **완료:** `c.export(version_payload=v)`는 이제 모든 JSON과 version.json을 `JSON_<region>.staging/` 형제 디렉터리에 완전히 직렬화·검증한 뒤, 기존 공개 파일을 백업 디렉터리로 **복사(copy)**해둔다(백업 실패 시 공개 무결). staging 파일을 공개 위치로 교체하며, 교체 도중 실패하면 백업(copy 원본)에서 공개 릴리스를 전부 구버전으로 롤백한다(신규 파일은 제거). 백업 폐기 기준: 전체 성공 시, 그리고 롤백 완전 성공·교체 전 실패 시에도 폐기해 다음 실행이 자가 회복한다. version.json이 JSON 트랜잭션에 통합되어 JSON/version 혼합을 방지한다. 롤백 불완전 시에만 `.rollback-failed` 마커와 함께 백업을 보존하고(판단은 `_rollback_promotion` 반환값 기반이라 마커 작성 실패에도 안전) 다음 실행이 비어 있지 않은 backup을 감지해 중단한다. `parser_version.csv`를 `export()`보다 먼저 갱신하고, 시작 조건에서 version.json/parser_version.csv 불일치를 검사해 실패 run을 자동 재시도한다.
4. `EQUIPMENT_IES`를 고유한 소문자 파일명 4개로 정리하고 중복 경로 assert를 추가한다.
5. 장비 `ItemGrade`를 정수 변환하기 전에 빈 값과 유효 범위를 검증하고, 도달 불가한 문자열 비교 기본값 분기를 제거한다. 빈 값 처리 정책과 대표 장비 fixture를 먼저 고정한다.
6. CaptionRatio 변환을 parser 또는 importer 한 곳만 소유하게 하고 작은 소수 합성 fixture로 이중 변환을 막는다.
7. 큐브의 잘못된 선행 조건과 키 오타를 고치고 `StringArg -> cubes[]` 다중 매핑으로 변경한다.
8. `ITEM_IES`를 결정적 list/tuple로 바꾸고, canonical ID·DB·URL/API 마이그레이션으로 Item/Recipe 충돌 49건을 해소한다.
9. 가디스 강화 수치 파일과 재료 지원 그룹을 각각 발견해 550 accessory를 포함한다. **완료:** `EQUIPMENT_REINFORCE_IES`에 `item_goddess_reinforce_550.ies` → 550을 정적 등록했다. 550 material 생성과 Lua `setting_lv_material_acc` 550 호출은 `has_550 = 'item_goddess_reinforce_550.ies' in c.file_dict` 게이트로 현재 지역에 파일이 있을 때(itos/ktos/jtos)만 수행한다 — stale twtos/ktest 수동 실행 시 잘못된 550 material이 생성되지 않는다. 550은 accessory 전용(5열 IES, Lua acc 분기만 존재)이므로 `goddess_reinf_mat[550]`은 `{'acc': {1..30}}`만 갖고 armor/weapon 키는 둘지 않는다(None이 아닌 키 생략). `parse_goddess_reinf` 시작 시 `goddess_atk_list.clear()`, `parse_goddess_EQ` 시작 시 `c.data['goddess_reinf'] = {}`로 같은 프로세스 재실행 시 이전 지역 stale 데이터가 잔존하지 않게 했다. 테스트 8개(`test_goddess_550.py`) 통과.
10. 지역별 드롭의 실제 source region과 패치버전을 기록하고 fallback 검증을 추가한다. **완료:** 새 모듈 `drop_source.py`의 `get_drop_source()`가 **데이터셋 단위** fallback으로 iTOS `ies_drop.ipf` 디렉터리를 우선 소스로 선택한다(2026-07 현재 ies_drop.ipf는 iTOS에만 존재). `monsters.py`/`maps.py`의 하드코딩 `../itos_unpack`를 제거하고 이 헬퍼로 통일했다. 각 `item_monster`/`map_item` 레코드에 `SourceRegion`/`InputVersion`(revision.csv 기반 best-effort)을 추가했고, 소스 결정 전체는 빌드 단위 `build_provenance` 컬렉션에 1회 기록한다. 미해결 참조(items_by_name에 없는 ItemClassName)는 조용히 skip 대신 `unresolved_drops` 컬렉션에 문맥(collection/엔티티 ID/item_classname/source_region)과 함께 누적해 자동 export한다. **부수 정확성 수정:** (a) maps 직접 zonedrop 유실 버그 — drops 객체에 `Money_*` 키가 없어 레코드 생성 시 `KeyError` → bare except 흡수로 직접 드롭이 전부 유실되던 것을 `Quantity_MAX/MIN=0`(수량 미제공 호환값)으로 복원; (b) 변수 셰도잉 — dropgroup이 `ies_path`/`ies_file`을 덮어써 다음 행 Unknownsanctuary chance 판정이 오염되던 것을 `zone_path`/`group_path` 분리로 수정; (c) dropgroup 합계 0 시 `ZeroDivisionError`로 파서가 사망하던 경로를 skip+경고로 수정; (d) maps의 iTOS-first+current 혼합 규칙을 단일 소스로 통일. 빌드 시 `DB.build()`가 `unresolved_drops`/`build_provenance`를 새 객체로 교체해 클래스 mutable 잔존을 방지한다. 테스트 19개(`test_drop_provenance.py`) 통과. **한계:** 파일 단위 fallback은 미구현(지역별 자체 드롭 데이터 배포 시 확장). importer 소비는 additive-safe(명시적 키 접근)이지만, 별도 버그 `map_item_path.json` vs `map_item.json` 경로 불일치로 사이트 반영이 안 되는 문제는 이 변경과 분리해 별도 태스크로 둔다.
11. `item_petequip.ies`를 포함할지 명시적으로 결정한다. 사이트에 펫 장비를 노출한다면 포함이 맞다.

### P1: 툴팁 정적 콘텐츠 보강

1. `UsageDesc`, `Desc_Sub`, `CustomToolTip`, `SkillType/SkillLevel`, 만료 정보를 additive JSON으로 정규화하고 DB/API까지 연결한다.
2. 스킬의 `CastingCategory`, `HitType`, `AffectedByAttackSpeedRate`, `TooltipType`, 자원과 버프 링크를 추가한다.
3. ARK/RELIC/BELT/EARRING/CORE 전용 스키마를 추가한다.
4. 특성의 `Desc2`, `AddSpend`, 활성/공유 그룹을 추가한다.
5. `skill_common`과 `skill_ancient`는 플레이어 스킬과 섞지 말고 별도 범주로 제공한다.
6. AdditionalOption의 611개 연결을 유지하면서 원본 키·슬롯·번역 fallback 상태를 구조화한다.
7. 맵별 값이 다른 몬스터를 `map_monsters`로 분리하고 전역 몬스터의 기준값 출처를 명시한다.
8. 패키지 JSON 문자열을 API에서 구조화 응답으로 제공하고 아이템 화면에 렌더링한다.
9. `charxp`/`petxp`/`assisterxp` 노출 여부를 결정하고, 노출 시 `exp.py`를 `main.py`에 연결하며 미노출 시 스키마와 export에서 제거한다.

### P2: 성능 최적화와 증분 빌드

1. `getMonbySkill` 인덱스를 적용하면서 기존의 2배 중복 결과를 stable dedupe한다.
2. 중복 Lua 초기화를 제거한다.
3. Lua 접근 필드를 계측해 강화/초월 공식 캐시 키를 완전히 정의한 뒤 메모이제이션한다.
4. `importAll`의 기존 delta를 스킬에도 적용하고 복합키 삭제를 수정한다.
5. JSON/DB import 단계 프로파일을 추가한 뒤 ORM bulk 처리 여부를 결정한다.
6. 고속 JSON 라이브러리를 쓸 경우 키, 숫자, 유니코드, NaN 처리의 의미 동등성 회귀 테스트를 먼저 둔다.
7. 중복 `*_by_name` 전체 객체를 `name -> id` 인덱스로 축소한다.
8. 몬스터/맵 드롭 디렉터리 인덱스를 한 번만 만들고 AdditionalOption 번역 인덱스를 패치 단위로 캐시한다.
9. `map_image.py`를 Python 3로 포팅하고, 그 전까지는 py2.7 사전 실행 전제를 운영 문서에 명시한다.
10. 깨진 standalone fallback 5곳과 importer의 미사용 `escaper()`를 정리한다.

### P3: 운영 이력과 롤백

1. 성공한 패치버전별 압축 스냅샷과 최근 N개 보존 정책을 도입한다.
2. import run에 상태, 입력/결과 해시, 변경 건수와 오류 요약을 기록한다.
3. 필요할 때 최종 객체 해시 매니페스트와 payload 포함 delta 파일을 추가한다.
4. 실패한 import가 현재 Dashboard 버전으로 노출되지 않도록 성공 시점에 버전을 전환한다.

## 자동 검증 체크리스트

매 빌드에서 아래 조건을 검사하면 최신 IES가 추가돼도 조용히 누락되지 않는다.

- [x] 정규화한 실제 경로가 중복된 장비 입력 파일이 0개다.
- [ ] 동일 소문자 파일 충돌의 선택 결과가 순회 순서와 무관하고, 새 DB 인스턴스에 이전 지역 상태가 남지 않는다.
- [x] 플레이어 스킬 결과 집합이 `skilltree.ies`의 `Type=Skill` 집합과 같다.
- [x] 대상 Item IES의 `ClassName` 집합이 `items_by_name`에 모두 존재한다.
- [x] 장비 `ItemGrade`의 빈 값·유효 범위 정책이 fixture로 고정되고 정수 변환 전에 검증된다.
- [ ] `(source_table, ClassID)`와 canonical ID가 DB까지 유일하며, comparer가 49개 Recipe를 덮어쓰지 않는다.
- [x] 발견한 가디스 강화 파일의 레벨 집합과 `goddess_reinf` 키가 같고, 550 재료는 acc만 지원한다. 550은 해당 IES가 존재하는 지역에서만 material을 생성한다(file_dict 게이트).
- [x] `reward_indun`의 해석 가능한 116개 그룹이 공유 그룹을 포함한 117개 큐브 모두에 연결된다.
- [x] 패키지의 직접 Item 참조가 모두 존재하고 오해석 참조가 0개이며, GROWTH 패키지는 일반 구성물로 해석되지 않고 미해석 범주로 전량 보고된다. 미존재 참조(만료 이벤트 2건)는 `PackageContents.unresolved`로 분리되고 가짜 fallback 이 생성되지 않는다.
- [x] `skill_mon.Monster` 배열에 중복 ID가 없다.
- [x] 지역 보정 몬스터의 `EXP`/`EXPClass`가 원본 `EXP`/`JOBEXP`와 각각 일치한다.
- [ ] 동일 ClassName의 맵별 상이한 스탯 17개가 덮어써지지 않거나 대표값 선택 출처가 명시된다.
- [x] iTOS 드롭 fallback을 쓰는 출력에 source region과 입력 버전이 기록되고, 모든 미해결 Item 참조가 `unresolved_drops`로 자동 보고된다(미해결 참조를 0으로 만드는 대신 누락 없이 보고하는 정책). 실빌드 unresolved 수치는 다음 ktos 전체 파서 실행 후 기록 예정.
- [ ] 값이 있는 `UsageDesc`, `Desc_Sub`, `CustomToolTip`의 처리율을 보고한다.
- [ ] 각 `ToolTipScp`별 원본 수, 출력 수, 전용 파서 적용 수를 보고한다.
- [ ] AdditionalOption 원본 611개가 모두 연결되고 비한국어 fallback 건수를 보고한다.
- [x] CaptionRatio 단위 변환은 한 계층에서 한 번만 수행된다.
- [ ] 골든 툴팁 필드가 parser JSON, DB, API/화면까지 같은 의미로 전달된다.
- [ ] Lua 공식 평가 실패가 0이거나 허용 목록에만 있다.
- [ ] fallback 생성 수와 이유가 이전 빌드 대비 급증하지 않는다.
- [ ] 지역별 번역 키 잔존 수와 빈 이름/설명 수를 보고한다.
- [ ] 같은 입력으로 두 번 빌드한 JSON 해시가 같다.
- [ ] 복합키 관계의 부모 삭제가 모든 자식 관계 삭제로 변환된다.
- [ ] 변경이 없는 빌드에서 스킬을 포함한 ORM write가 0건이다.
- [ ] import 실패 시 현재 버전과 `prev` 스냅샷이 전진하지 않는다.
- [x] `version.json`과 `parser_version.csv`는 각각 임시 파일 완전 쓰기 후 원자 교체되어 실패 시 빈 파일이나 부분 파일이 남지 않는다.
- [x] **설계 후 원자적 승격 완료 조건(최종 상태 기준):** parser 중간 실패 시 공개 JSON과 version.json의 최종 상태는 전부 구버전 또는 전부 신버전 둘 중 하나로만 귀결된다. `export(version_payload)`가 staging 디렉터리에 모든 JSON과 version.json을 직렬화·검증한 뒤 백업 copy + `os.replace`로 일괄 교체한다(version.json이 JSON 승급 트랜잭션에 통합되어 JSON/version 혼합 방지). 백업 copy 실패는 공개에 영향을 주지 않고, 교체 단계 실패 시 백업 copy 원본에서 공개 릴리스를 전부 구버전으로 롤백한다(copy 기반이므로 백업 소비 없음). 롤백 실패 시 `.rollback-failed` 마커로 백업 보존 + 다음 실행 중단으로 수동 복구를 보장한다. `parser_version.csv`는 `export()`보다 먼저 갱신되며, version.json/parser_version.csv 불일치(커밋 미완료)를 시작 조건에서 검사해 실패 run을 자동 재시도한다(백업 copy 실패·공개 승급 실패·롤백 실패·stale backup·version.json 트랜잭션 통합·재시도 테스트로 검증). **제한:** `BASE_PATH_OUTPUT` 고정 디렉터리로 인해 디렉터리 포인터 단위 교체는 미도입; 교체 진행 중 일시적 신구 혼합 관찰 가능(독자 관점 원자성은 아님). importer는 cron이 parser 성공 후에만 실행해 혼합 창 미도달.
- [ ] `data`에 선언된 컬렉션 중 생성 단계 없이 빈 값으로 export되는 것이 0개다(현재 `charxp`/`petxp`/`assisterxp`).
- [ ] parser가 실행 CWD와 무관하게 같은 입력을 찾고 같은 결과를 낸다.
- [ ] parser export와 DB import 시간을 별도로 측정한다.

## 완료 기준

개선 작업은 단순히 실행 시간이 줄어드는 것으로 끝내지 않는다. 다음 상태를 완료 기준으로 권장한다.

1. ktos 기준 플레이어 스킬 912개와 등록 대상 아이템이 손실 없이 결정적으로 출력된다.
2. 큐브, 패키지, 제작서의 구성물 링크와 패키지 인스턴스 옵션이 실제 IES와 일치한다.
3. 가디스 강화 550을 포함해 발견된 모든 레벨이 자동 반영된다.
4. 게임 툴팁과 비교한 대표 골든 샘플을 둔다: 일반 소비 아이템, 큐브, 젬, 카드, 일반 장비, 가디스 장비, ARK, RELIC, BELT, EARRING, CORE, 액티브 스킬, 채널링 스킬, 패시브 스킬, 특성.
5. 골든 샘플의 정적 필드가 일치하고, 인스턴스 전용 값은 명확히 `미제공` 또는 입력 필요로 표시된다.
6. 지역 보정 몬스터의 EXP/직업 EXP와 맵별 스탯 출처가 정확하고, 드롭 fallback의 source region이 추적 가능하다.
7. 실패 주입 테스트에서 이전 공개 결과와 버전이 유지된다.
8. 같은 환경의 warm run에서 전체 시간이 110초 이내이며, 결과 JSON의 의미적 diff가 승인된 변경만 포함한다.
