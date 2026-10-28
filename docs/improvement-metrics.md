# 개선 성과 조회 계약

`make improvement-metrics [PERIOD=latest|day|7d|30d] [DATE=YYYY-MM-DD] [ROLE=역할] [FORMAT=json|text] [WORKFLOW_STORAGE_CONFIG=설정]`.
기본 latest·text, bare `make`는 help다. native `python3 -m harness.improvement_metrics`에는
`--period/--date/--role/--format/--workflow-storage-config`로 대응한다(text=한국어 요약, json=상세).

```sh
HARNESS_STORAGE_CONFIG=/path/to/improvement-storage.json make improvement-metrics PERIOD=7d DATE=YYYY-MM-DD FORMAT=json WORKFLOW_STORAGE_CONFIG=/path/to/workflow-storage.json
```

설정은 일반 절대경로 예시다. `HARNESS_STORAGE_CONFIG`는 절대경로 필수다. workflow 설정 생략 시 같은 storage,
별도 설정에는 `HARNESS_REPORT_DIR` override를 적용하지 않는다.
기존 정책은 [개선 연구](improvements.md)와 [workflow](workflow.md)를 따른다.

## 기간·모집단

latest는 최신 보존 hourly 원본의 KST 날짜 하루다(회차 하나 아님). ROLE·nonhourly로 날짜를 고르지 않는다.
hourly 날짜가 없으면 DATE(없으면 오늘)를 쓴다.
day는 DATE 하루, 7d/30d는 DATE 포함 해당 일수다. DATE 기본은 오늘이다.
기간은 [시작 KST 자정, 마지막 날 다음 자정과 현재 중 이른 시각)이다.
날짜는 Asia/Seoul 기준이다.
회차·후보는 최초 보존 admission cohort, 호출은 각 admission 기준이며 끝 이후 성공은 제외한다.
오전은 후보 cohort와 기간 내 frozen 창의 교집합이다.
ROLE=coordinator/downloader/parser/django/reviewer는 호출 owner·회차 참여·최초 후보의 명시 origin_role 기준이다.
역할 결손은 추정하지 않는다.

연구 모집단은 구형·신형 hourly 원본이다. scans/active report를 scan_id로 합치고 invalidated가 우선한다.
출처 enum: hourly/nonhourly/unknown/materialization. producer round/slot/completed/invalidated는 hourly 근거다.
participation/local_history만이면 유효 legacy-index가 필요하다. legacy/legacy_seen은 nonhourly다.
daily의 history 이동만으로 hourly나 충돌이 되지 않는다. 명시 tick/nonhourly 충돌·원본/출처 결손은 unknown이다.
publications report scan_id·report_window·morning_aggregate는 materialization으로 회차·호출에서 제외한다.
loop_dependencies·ownership fingerprint·scan version·Read는 출처 gate가 아니다. Read는 완주·검토의 별도 근거다.
호출 복원에는 원본·owner·stage·slot·시각·지원 history version이 필요하다.

coverage는 기간·역할별 출처·복제·제외 시도·nonhourly 호출이다.
시각 없는 sources_without_period_clock·attempts_without_period_clock은 날짜별 분모에서 제외한다.
0은 보존 부분집합의 관측치다. 누락은 0이 아니며 미관측=null/unavailable, 근거 부족=unknown이다.
status: available/partial/unavailable. 출처 unknown·복원 불가·개별 손상=partial, 일관성 부재=unavailable.
비율은 numerator/denominator/scope/unit/value를 낸다.
scope=같은 기간·역할 모집단, 기본 unit=fraction. 분모 0은 value=null·status=미산출. 기간 변화=unavailable.

## 지표 1: 완주

판정 순서: invalidated → completed → review_complete만 있는 unknown → superseded → active held/in_progress → failed → unknown.
completed는 Read proof·끝 전 reviewer 완료 시각으로 인증한다(local/specialist 실패·후보 0개 가능).
superseded=미검토 다음 회차, held=정책·예산·quota 보류, failed=관측 실패.
완주율 = completed / (completed + failed + superseded); 나머지는 별도 집계한다.
단계별 호출·성공·실패·원인·시간을 낸다. 호출 근거는 call_started_at, local called=true 또는 provider/model+유효 시간이다.
skipped/not_called/reserved·called=false·증거 없는 준비 실패는 제외한다.
local 유효 초안 호출 비율 = succeeded local / 실제 local 호출; 초안 수=null·유래=unknown(보존 batch 연결 시만 판별).
회차 시간=첫 실제 call~reviewer 종료. 시간은 초 단위 n·중앙값·nearest-rank p90·최댓값이며 미관측=null이다.

## 지표 2: 후보 손실

생성 원수(null: 미저장) → 검증 후 보존 → 실제 Read 검토 → eligible → frozen 오전 선택 → 카드 노출이다.
ID/digest 전이적 중복은 한 번 세고 반복 수·끝 전 최신 검증 판정을 낸다.
verdict는 eligible/needs_evidence/rejected/review_incomplete/unknown이다.
독립 검토 통과율 = eligible / (eligible + needs_evidence + rejected).
오전 손실은 frozen dependencies·원본 proof·provenance 기준
dependency_digest_mismatch/outside_window/provenance_unavailable/top8/top3와 당시 verdict를 구분한다.
priority·ID 순 8개 뒤 카드 상한을 적용한다(eligible 우선 아님). top8은 provenance/frozen projection 일치 때만 인증한다.
보고 기회 미관측은 selected/exposed=null. payload 검증 불가 시 exposed=0도 가능하므로 payload_status=unavailable을 함께 읽는다.
노출(payload.proposals)과 전달은 별개다.

## 지표 3: 전환

eligible → 명시 승인 → 실행 → 검증 → PR → 필수 CI3 → merge → cleanup이다.
단계 enum은 passed/waiting/rejected/failed/unavailable이다.
승인·claim·후보·run 연결의 끝 전 증거로 판정한다.
병합 인증: 검증·CI3·head/merge SHA 연결·cleanup proof(PR만으로 부족).
CI3는 Offline harness (SQLite), MySQL harness, Chromium browser harness의 success다.
unique_runs는 active 연결 run을 한 번 세며 과거 실패 event를 보존한다.
승인율 = 승인 passed 후보 / eligible 후보; 병합 완료율 = cleanup passed 후보 / 승인 passed 후보다.

## 지표 5: 효율

연구/연결된 구현 호출을 분리해 역할·공급자별 slot·시간(초)을 낸다. GLM logical request는 관측 부분집합이며 slot과 합치지 않는다.
입력·출력·cache token은 known_sum·known_calls/unknown_calls를 낸다.
Claude USD는 CLI 추정이며 실제 청구·예약액이 아니다. Codex/Z.ai 구독·local 호출은 USD로 합산하지 않는다.
eligible당 연구 호출 = 실제 연구 호출 / eligible 후보(unit=calls_per_candidate),
cleanup 병합당 구현 호출 = 연결된 실제 구현 호출 / cleanup passed 후보(unit=calls_per_merge)다.
admission 시각 없는 구현 호출은 분자에서 빼고 미귀속 수를 낸다.

지표 4 병합 후 효과는 제외한다.
