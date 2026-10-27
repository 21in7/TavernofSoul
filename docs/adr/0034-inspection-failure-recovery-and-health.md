# 0034. 반복 점검 JSON 실패의 경계 수리와 별도 owner-private health

- 상태: 제안(proposed)
- 최초 작성 시점: 명시 직접 개발 요청 구현안·새 의미 검토/전체 검증/운영 관측 대기였으며, 후속 구현·운영 관측은 아래 2026-10-27 최신 main 관측 절 참조
- 기록일: 2026-10-26
- 기록 성격: 새 결정
- 대체 관계: 0020의 두 전송 계약 제한을 세 번째 고정 health 계약에 한해 정밀화. 기존 보고·완료·승인 계약 유지

## 2026-10-27 최신 main 관측

### 08시 독립 검토 실패 후속: source 계약 호환 수리안

추가로 parent가 제공한 실제 관측에서 같은 scan `1793026802215716805-c162f5`는 후보2개와
01시 coordinator·03시 downloader·05시 parser·07시 django 성공 뒤 08시 reviewer가 실패했다.
08:00:01.940372~08:00:30.957424 KST, claude/claude-sonnet-5-5,
reason/cause=source_review_unverified, phase=review, error_type=ValueError,
cost0.078057(cli_estimated_usd), read_files=[]다. source_review proof·stdout·응답이 없어
거절된 실제 필드/Read/assessment와 역사적 근본 원인은 미확인이다. 09시 state의 stage_index=1,
last_slot=2026-10-27T09,pause_reason=null은 후속 reviewer 성공을 뜻하지 않는다.

[ADR0026의 이번 인계](0026-source-verified-retained-improvement-reports.md#2026-10-27-호환-수리private-검증-경계-진단-인계)는
정상 JSON 문자열의 유니코드 구분자를 splitlines가 NDJSON 경계로 잘못 나누는 소스상 결함의
LF framing 수리와 검증기 발생 경계의 고정 private field/rule을 명세한다. 새 합성 회귀는 이
결함과 진단 보존 경로의 검증 인계이며 08시 원인의 실제 재현이나 운영 성공 관측이 아니다.
진단은 기존 capability/identity/first-failure/비용 정산을 유지하고 health/public schema와
노출 코드를 늘리지 않는다. 과거 실패·frozen 보고·승인/claim도 바꾸지 않는다.
별도로 준비된 parent의 실모델 probe는 정식 workflow 밖 호출로 자동승인이 거절되어 실행되지
않았다. 이번 worker는 probe/private 설정을 읽거나 검사·모델·Git·네트워크를 실행하지 않았다.
새 전체 diff Claude 의미 검토/documentation 판단·full make check·CI3/merge/cleanup/archive와
별도 실제 hourly 후속 확인은 parent 책임이며 아직 이번 수리의 검증·후속 성공 증거는 없다.

아래 사실은 신뢰한 parent가 직접 확인해 제공했다. 이 문서를 편집·검토하는 worker/reviewer가
직접 실행하거나 검증한 결과가 아니다. 아래 문맥·수리·인계의 미검증/대기 진술은 각 작성 당시의
역사적 상태이며 현재 관측은 이 절과 [모델 문서](../agent-models.md#2026-10-27-최신-main-관측)를 따른다.
과거 실패를 새 성공으로 덮거나 이번 변경의 승인·검증 증거로 재사용하지 않는다.

### 구현 검토·개발 probe·GitHub 완료

구현 native run1793034139378468813-c521fa는 새 Claude 전체 diff/documentation 승인,
표적422/422, full6263/6263(다운로더129, parser/harness5984, Django회귀67, Django11,
연결부72), 실패/오류/skip0을 기록했다. scoped apply19개와 기본 Git 역할도 완료했다.

별도 명시 개발 GLM probe는 2026-10-27 02:15:55.183424~02:18:11.012133 KST,
elapsed135.827822초였다. provider=zai/model=glm-5.3-flash, 원래 수집담당9파일,
native 구조 budget1/transport0/low effort/8192 경로에서 succeeded와 telemetry success를
관측했고 candidate validator가2후보를 받아들였다. 이는 각 후보의 새 Claude 독립검토·공식
hourly proposal·사용자 승인·execute를 뜻하지 않는다. 이 probe는 hourly 상태를 수정하지 않았다.

구현 [PR81](https://github.com/21in7/TavernofSoul/pull/81)은 GitHub merged=true,
mergeSHA `310485c1e3303b587c1e2cb61d6484c02ca04350`이다. Offline harness (SQLite),
MySQL harness, Chromium browser harness가 모두 실제 success였다. native cleanup은
complete이며 remote deleted/local absent/prune complete/sync complete/completion complete다.
실제 terminal archive는 archived, bundle93806bytes,
SHA `a138cbfa4630538ed4c528ff1faaef24f659fb342feb7d58274dee80d1895fc0`이다.
상대 증거 참조는 `logs/harness/inspection-success-observations-evidence.json`과
`logs/harness/inspection-native-attempt-live-probe-20261027.json`이다.

### 정규03시 역할과 기존 health 전달

별도 개발 probe와 다른 실제 정규 hourly에서 2026-10-27 03:00:02.516543~03:02:23.280518 KST
수집담당 succeeded, stage index3→4, last slot03, inflight없음을 관측했다. 이 성공은 다른 stage나
새 전체9단계 완료를 뜻하지 않는다.

기존03tick의 자동 improvement-health-v1 outbox는 delivered이며 digest는
`c899d5f842d7d503156405619dcc21050ff44652ee631ce89041edb7b02c645d`다.
main의 KST03:07:22 관측(UTC2026-10-26T18:07:22.293626+00:00)에서 GET200과 outbox
frozen payload 전체 일치를 확인했다. 관측 명령이 새로 POST/모델/tick을 호출한 횟수는 각각0이다.
상대 증거 참조는 `logs/harness/inspection-hourly-03-health-observation.json`이다.

### 보존된 과거와 남은 관측 한계

원래2026-10-26 day/web/loop publication 세 원본의 bytes/SHA가 모두 불변임을 재확인했다.
원래 web digest는 `6b39c37d67fad984be50e26a582738d0a9e24ba667c05b06f984ef5aa81ede50`다.
과거00/09실패와 원문 미보존 한계, 별도18:06성공, 480.172811초 timeout, 7.437927초 CLI
budget0 실패, 최초 full검사 중단과 같은 후보의 native 재개 기록은 보존한다. 새 성공은 이들
기록을 소급 변경하거나 과거 partial 보고를 성공으로 바꾸는 근거가 아니다.

새 전체9단계와 다음09시 게시 성공은 아직 미관측이며 정규03역할 성공/health 전달과 구분한다.
Site 추가 인쇄 화면 소스는 로컬 새 Claude/6Node모듈/TS/build/A4한장·모바일 overflow0 검증을
마쳤지만 게시 자동승인검토에 막혀 사용자 응답 대기다. 추가 인쇄 화면 배포 성공은 주장하지
않는다. 기존 health 전달 성공은 위 실제 관측으로 별도 기록한다.

### 이번 관측 문서 변경의 영향과 인계

이번 변경은 docs/agent-models.md와 이 ADR의 최신 관측 정리다. 구현·구조·책임·데이터 계약·
격리·권한·실패 복구·검증정책·GitHub 게시 정책·모델/인증·스케줄·설정은 바꾸지 않으므로
다른 설계/경계 문서 갱신이나 새 ADR은 필요하지 않다. 매 review는 최종 두 문서의 의미적
완전성을 새로 판단해 `documentation={status,files,reason}`을 반환한다. 앞선
documentation.updated나 위 구현의 검사 통과를 이번 변경의 승인 근거로 삼지 않는다.
parent가 실제 baseline→candidate diff로 docs-only 여부를 판단하고 ADR0031/0022의 check-docs
및 GIT=1·기존 GitHub CI/merge/cleanup/archive 경로로 전달한다. worker/reviewer는 검사·Git·
네트워크·SSH·재위임·workflow를 실행하지 않는다.

## 문맥

parent가 제공한 실제 관측은 2026-10-26 오전 보고 partial, coordinator/parser/django/reviewer
성공과 downloader 실패다. downloader는 Z.ai의 glm-5.3-flash, index3 specialist(4/9단계)에서
CLI/telemetry success 후 `_parse_model_response`가 `role_json_invalid`, `cause=json_invalid`,
`phase=json`으로 거절했다. 첫 관측은 KST 00:00:02.024118~00:02:29.364623, elapsed147.336745초,
같은 오류가 09:00:02.491970~09:05:10.526472에도 있었다. 이 시각/elapsed는 parent가 전달한
기존 관측이며 새 health 구현이 소급 측정한 값이 아니다. 저장 scan에는 원문 result가 없어
특정 문자·fence·잘림을 확정할 수 없다. 기존 days/publication과 frozen web-v1 digest는 보존한다.

설치된 Claude CLI가 `--json-schema`를 지원한다는 parent 근거가 있다. 기존 adapter는 JSON
envelope의 result 문자열을 반환하고 discovery가 자유 JSON을 다시 파싱한다. 구문 실패를
발생 경계에서 줄이면서, 소유자에게 실패와 나중의 성공을 안전하게 구분해 전달할 계약이 필요하다.
원문·예외·임의 provider/model 문자열이나 local 상세를 기존 오전 payload에 넣을 수는 없다.

다음은 더 이전의 중단 기록이며 아래 재개 run과 구분한다.
직전 run1793023022496810528-82c64a는 coordinator900초 timeout, applied=[]이며 review/check/Git은
없었다. parent의 baseline byte 확인과20개 checkpoint 복원은 준비 작업이다. 이 문서는 복원된
초안을 완성하는21파일 작업의 결정이며 새 검토·검증·적용·실제 성공의 증거가 아니다.

## 결정

### Discovery 전용 native 후보 계약

[improvement_schema.py](../../harness/improvement_schema.py)는 trusted caller가 확보한 승인 경로,
snapshot, config에서 full canonical 후보 schema를 만든다. root는 정확한 candidates 하나이고,
후보/근거/benefit의 required와 additionalProperties=false, private 서술 및 collection 상한,
edit_files enum, 존재하는 실제 source별 원래 줄 상한을 표현한다. 빠진/빈 source는 근거로
사용할 수 없다. schema CLI 인자는 UTF-8 65536bytes 이내이며 초과 시 호출 없이 실패한다.
경로 보정·source 읽기·임의 caller JSON schema·권한 추가는 없다.

`agent_models.run/command_for`의 optional discovery_schema는 준비된 context capability만 받는다.
정확한 role/workspace/provider=zai, discovery guard, scoped read-only와 non-smoke를 확인한 뒤
`--json-schema`를 붙인다. 현재 Z.ai specialist discovery에서만 사용한다. reviewer 실제 Read
stream, 일반 구현/workflow/smoke와 미요청 `response_text(provider, output)`의 tuple 계약은 유지한다.
모델·enable-thinking·인증·compaction을 바꾸지 않는다.

#### 검증된 native 요청만의 effort·출력·재시도 제한 (2026-10-27)

아래 실제 timeout과 후속 구조화 실패에 대한 수리는 검증된 discovery_schema capability의 Z.ai specialist
child 하나에 한정한다. `--effort low`와 `CLAUDE_CODE_EFFORT_LEVEL=low`, unknown custom model에도
effort를 보내는 `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1`, 요청당 `CLAUDE_CODE_MAX_OUTPUT_TOKENS=8192`,
`MAX_STRUCTURED_OUTPUT_RETRIES=1`, `CLAUDE_CODE_MAX_RETRIES=0`을 명시한다.
환경 변수는 child_environment 정화와 telemetry 환경 구성 뒤 실제 subprocess env에 넣는다.
parent os.environ·역할 config·일반 Z.ai·Claude reviewer·Codex에는 이 제한을 적용하지 않는다.
native schema는 환경을 만들기 전 role/provider/workspace/guard/read-only/non-smoke와 canonical
내용을 검증한다. 같은 caller의 schema 완화·범위/역할/provider/guard 변조도 실행 전에 거절한다.

parent가 확인한 [thinking mode](https://docs.z.ai/guides/capabilities/thinking-mode)와
[chat completion](https://docs.z.ai/api-reference/llm/chat-completion)에 따르면 GLM5.3/Flash의
thinking은 강제이며 disabled 불가다. reasoning_effort low/high/max 중 기본 max 대신 low를
요청하는 수리이며 thinking을 끄는 구현이나 주장이 아니다.
[Claude Code 환경 변수](https://code.claude.com/docs/en/env-vars)의 force effort를 함께 사용한다.
구조 재시도 기본5·transport 재시도 기본10에 의존하지 않고 이 경로만 각각1/0으로 고정한다.
설치 CLI에서 구조 budget1은 정상 Read 대화 후 첫 구조화 시도에 도달하도록 하며 불량 구조화
응답 뒤 repair 요청은 없었다.0도 첫 응답이 바로 유효 구조화이면 성공하므로 첫 호출을 항상
막는 값으로 설명하지 않는다. 같은1 CLI invocation 안의 정상 도구 대화와 실패 뒤 새 CLI 호출/
재시도를 구분한다. 확정 재현과 실패 기록은 아래 별도 절에 둔다.
8192는 요청당 출력 제한이며 전체 요청의 합·성공·480초 완료를 보장하지 않는다. cap 잘림이나
프로토콜 거절은 실패 그대로이며 result fallback·후보 합성·임의 경로 보정·추가 호출은 없다.
실제 provider HTTP proxy·credential·provider/model·예산·quota/slot 정책은 바꾸지 않는다.
이는0034 native 계약의 bounded 실행 정밀화로 기존 ADR에 기록하며 새 전송/역할/게시 정책을
만들지 않는다. strict structured_output·최종 후보 의미·identity/context 검증은 계속 필요하다.

명시 요청 시 type=result/subtype=success/is_error=false envelope의 structured_output만 strict
JSON으로 읽고 canonical JSON을 반환한다. 누락/null/불명 root·비성공·중복키·비유한·bytes 초과·CLI
미지원은 실패다. result fallback, 문법 수선, 추가 모델 호출이나 유료 fallback은 없다.
identity/context 확인 뒤 기존 후보 validator의 한국어·중복·총 문자·근거/줄 관계·편집 scope 및
독립 의미 검토를 계속 요구한다. native 형식 자체는 의미적 정확성 증거가 아니다.
최초 실패 capability와 cost/usage/telemetry 정산 의미를 보존한다.

### 별도 순수 health 계약

[improvement_health.py](../../harness/improvement_health.py)의 project/validate는 별도
`improvement-health-v1`이다. root와 중첩 키를 고정하고 version/generated_at/roles/recent_failures/
next_stage/hold_code/digest만 허용한다. cloud5역할의 최신 관측, 9단계 위치, 고정 상태 및
reason/cause/phase/field/rule, slot, 실제 adapter 호출 전후 parent wall 시각과 최근 최대16실패를
투영한다. cloud history192 한도 안에서 각 실패 뒤 같은 역할의 별도 성공 완료 시각을 표시한다.
단계의 local 위치는 다음 순서만 알리며 local 실행 상세는 보내지 않는다.

call 시각은 admission/settlement 시각이나 모델 문자열이 아니다. adapter 진입 전 preparation
실패·과거 미측정·중단 복구는 null이며, call 내부의 CLI launch/HTTP 세부 시각과도 구분한다.
뒤집힌 wall interval은 완료 시각 미상으로 처리한다. old reason만으로 cause를 새로 추측하지
않는다. provider/model·비용·local endpoint·예외·source·prompt·원문·credential·절대 호스트 경로는
배제한다. allowlist/digest 검증은 storage나 runner의 provenance 인증을 대체하지 않는다.
후속 성공은 원래 실패를 덮거나 freshness·승인·전체 review 성공을 증명하지 않는다.

### Health wire 계약

| 필드 | 고정 의미/상한 |
| --- | --- |
| version | 정확히 improvement-health-v1 |
| generated_at | projection 생성의 aware ISO 시각, 호출 시각을 대신하지 않음 |
| roles | coordinator/downloader/parser/django/reviewer 순서의5개 `{role,latest}`. 미관측 latest=null |
| latest / attempt | 정확히 role/stage_index/stage/status/slot/call_started_at/call_finished_at/reason/cause/phase/field/rule |
| stage_index / stage | cloud는1/3/5/7 specialist 또는8 independent_reviewer. 표시4/9는 index3 |
| status | reserved/succeeded/failed/unavailable. 모델이 아니라 parent가 검증한 시도 상태 |
| slot | KST admission slot YYYY-MM-DDTHH 또는 null |
| call_started_at / call_finished_at | 실제 adapter 호출 직전·직후 parent wall 관측 또는 null |
| reason/cause/phase/field/rule | diagnostics의 고정 allowlist만. legacy 결손은 unknown/unavailable/null, 비실패는 모두 null |
| recent_failures | 최대16개 `{attempt,subsequent_success_at}`. 원래 실패와 후속 성공을 별도로 보존 |
| subsequent_success_at | 같은 역할의 별도 succeeded 호출이 실패 종료 뒤 시작했을 때 그 완료 시각. 관계 미확인은 null |
| next_stage | `{stage_index,stage,role}` 또는 null. 기존9단계의 다음 순서이며 local 상세는 제외 |
| hold_code | 고정 제어/보류 또는 cloud 실패 코드, 비허용/local 전용 세부 코드는 unknown, 보류 없음은 null |
| digest | digest를 제외한 전체 body의 canonical JSON SHA-256. unknown key/타입/코드/잘못된 digest는 거절 |

전체 body와 readback은65536bytes 이하다. 서버는 canonical payload를 wrapper 없이 같은
`/api/health`에서 반환하며 같은 digest를 idempotent하게 수용한다. digest만 일치하는 변경 body도
거절한다. next_stage의 local 위치는 순서만 알리고 실행 상세는 제외한다.

### Parent 전용 독립 전달

순수 projection에는 I/O가 없다. query는 기존 private Store를 잠가 읽고 키/HTTP 없이 투영한다.
수동 publish는 child/discovery/unattended를 거부하고 trusted parent가 직접 validated state를 읽는다.
임의 health body를 받지 않는다. 기존 stable sender→artifact sender→Store lock 경계와 private
directory0700/file0600·no-follow/소유권 정책을 사용한다. `health/outbox.json`에 frozen payload와
pending/sending/unknown/delivered/conflict 상태만 저장하며 POST 전에 sending을 durable 저장한다.

HTTP는 state/source lock 밖에서 기존 private inbox credential, HTTPS/TLS/no-redirect/bounded
transport로 수행한다. POST `/api/health` 성공 뒤 같은 endpoint GET이 strict schema·digest·전체
본문에 일치해야 delivered다. timeout/잘못된 readback은 별도 실패 또는 unknown이며 자동
POST하지 않는다. sending/unknown은 GET만, 명시 `--reconcile --digest`는 frozen digest 대조와
GET404 뒤에만 동일 bytes POST를 허용한다. 다른 유효 payload는 conflict로 보존한다.
불명 outbox를 최신 상태로 덮지 않는다. delivered 뒤 다음 publish만 새 snapshot을 만들 수 있다.

기존 CLI tick만으로 다음 관측도 전달한다. `_tick_locked`가 정상 반환한 durable 최종 상태에
한해 기존 discovery/state/source mutex와 deadline을 벗어난 뒤 `improvement_health._after_tick`이
같은 Store/policy를 재사용한다. 새 source scan·모델·readiness 복구 시도·storage fallback은 없다.
역할 실패가 정상 정산되어 저장됐어도 대상이다. 초기 config/Store/readiness/binding/lock/state/
bootstrap 실패나 final save 실패는 대상이 아니다. 이미 처리된 slot·시계 역전도 전송하지 않는다.
slot 수립 전 bootstrap 또는 이미 실패한 state-save/readiness는 파생 morning/진단 저장으로
readiness를 재시도하지 않고 최초 private stdout 진단을 남긴다. 기존 durable 예약은 보존한다.
`--no-deliver`, embedded deliver=False, status/query/publish-morning에는 health 자동 전송이 없다.

qualified 경로만 기존 unattended tick marker 아래 정제 전송을 허용한다. child/discovery는
storage 전에 거절하며 수동 parent CLI의 trusted 검사도 유지한다. CLI/환경은 인간 신원이나
approval/execute 권한이 아니다. scheduler는 기존 단일 hourly wrapper의 tick 하나 그대로다.
새 cron·Git hook·승인·실행·publication 연결이나 모델/키 설정 변경은 없다.

sender→artifact sender→Store 잠금 안에서 기존 validated state의 slot/inflight/high-water를 다시
대조한다. 다른 tick이 대체했으면 health_superseded, wall 역전이면 clock_rollback으로 보내지 않는다.
불명 outbox는 최신 상태로 덮지 않고 GET만 한다. delivered 이후 정상 다음 tick은 새 관측을
POST+GET할 수 있다. 수동 reconcile만 같은 frozen digest와 GET404 뒤 재POST할 수 있다.
health 실패는 별도 trace와 `health_publication` 결과/outbox에 남겨 원래 tick의 최초 실패·stage·
회계·예약·ledger·morning 결과·frozen 기록을 덮지 않는다. sender/storage 실패는 health_unavailable,
HTTP 실패는 delivery_failed/unknown 등 기존 고정 결과다. morning 전송 예외도 별도 publication
결과로 남기며 정산된 역할 결과와 health 전달을 막지 않는다. 전송 실패로 tick을 재실행하지 않는다.
같은 slot도 morning sender를 확인한다. 실제 잠금 충돌은 `sender_lock_busy`로 별도 처리하며
최초 역할 실패를 유지한다. health 중복 억제와 독립이고 새 process 회귀·전체 검증은 parent 대기다.
수동 키/HTTP 없는 조회와 명시 조정은 [운영 절차](../harness.md#실패-복구-health의-parent-운영)를 따른다.

## 비교 대안

자유문자열 재파싱만 유지하면 같은 구문 경계 실패를 줄일 수 없다. result fallback·자동 수선은
명시 native 요청 실패를 숨기고, 모델 retry/유료 fallback은 기존 slot·예산 의미를 바꾼다.
web-v1 확장은 frozen digest와 오전 보고 계약에 영향을 주므로 별도 health를 선택한다.
수동 일회 전달만으로는 이후 hourly 실패/후속 성공이 보이지 않아 제외한다. 저장을 완료한 tick의
잠금 밖 정제 전달과 별도 오류 경계를 선택하며 초기 실패에는 자격을 주지 않는다.

## 선택 이유

확인된 문제는 CLI exit가 아니라 discovery JSON 경계다. 승인 입력에 묶인 native 출력 요청은
그 경계를 직접 보강한다. client 검증을 남겨 모델이나 CLI의 schema 위반도 계속 실패시킨다.
별도 고정 projection과 frozen outbox는 소유자가 실패 위치·확인된 원인·후속 관측을 볼 수 있게
하면서 기존 불변 보고와 private 원문 격리를 유지한다.

## 결과·비용·제약

runtime37목록·128KiB/1.5MiB source 상한, 일24회/tick1회·GLM80% gate·예산·wrapper/cron·private
설정/키/ledger 및 일반 개발 v2 local active+remote terminal archive는 바꾸지 않는다. 새 helper를
runtime 읽기 승인에 자동 추가하지 않는다. schema 오류/미지원은 한 번 실패로 끝나며 정상 다음
slot/회차의 관측은 별도다. health history는 bounded 요약이며 전체 실패 원장은 기존 private다.

다음은 최초 작성 당시의 인계이며 후속 실제 성공은 [최신 main 관측](#2026-10-27-최신-main-관측)에 구분한다.
Sites `/api/health` 구현/배포·UI는 parent의 별도 작업이었다. 당시 parent에게 새 Claude 의미 검토와
documentation={status,files,reason}, full make check, scoped apply, 기존 Git 역할·실제 CI3 success/
merge/cleanup/archive 수행을 인계했다. 정확한 최종 코드로 GLM 실패 단계를 단1회 개발 재검증한
결과와 실제 후속 hourly 성공·동일 GET 전달은 당시 아직 미관측이었다. worker는 검사를 실행하지 않았다.

## 이전 parent 검증과 native timeout 기록 (2026-10-27)

parent 제공 run1793029835254678756-74e8c1은 새 Claude 전체diff 승인, focused68/68 및 full
make check6251/6251 통과 뒤 scoped apply19개까지 완료했다. 이 증거는 그 후보의 오프라인
검증이며 실제 GLM 성공의 증거가 아니다. 뒤이은 별도 native-schema probe는 2026-10-27
01:07:45.791706~01:15:45.965393 KST, elapsed480.172811초 timeout으로 실패했다.
hourly 상태는 바꾸지 않았고 quota ready, provider=zai/model=glm-5.3-flash 및 원래 승인된
수집담당9파일을 사용했다. timeout480초를 늘리거나 이 실패를 성공으로 바꾸지 않는다.

정제 telemetry는 모델 요청5개, retry0, Read8개 모두 성공·전체 tool753ms를 관측했다.
마지막 관측 요청416266ms에 output17391tokens, 전체 요청 output18094tokens다. 이 출력이
thinking인지 본문인지는 확인되지 않았고 원문도 보존되지 않았다. 이 숫자로 timeout의 특정
내부 원인이나 thinking 비율을 단정하지 않는다.

안전한 native Git handoff는 실패를 보고 GitHub request 전에 중단했다. 원래 journal은
events0/awaiting_connector repository 단계로 원격 쓰기가 없다. parent는 전체 후보를 private
보존한 뒤 정확한 승인 파일만 baseline으로 되돌려 새 workflow 최종전체diff를 준비한다.
이 작업은 승인21개 전체 후보를 보존하면서 위 실제 실패에 필요한 변경만 더한다.
runtime37·개별128KiB/합1.5MiB·24slots·예산과 원래 날짜의 오전 보고/자동cron/private config는
유지한다. 승인 runtime10개 밖27개 합773709bytes는 parent 제공 상수이며 worker는 그 소스를
읽지 않는다. 아래 이전 후보의 byte 수는 최신 후보의 측정 결과가 아니다.

작은 fake 회귀는 실제 subprocess 호출 인자에서 정화 후 effort/force/output/retry를 확인하고,
일반 Z.ai/Claude reviewer의 후속 실행과 Codex 환경·parent 환경 격리, 같은 caller의 요청 변조
no-call, cap/프로토콜/timeout 실패의 무재호출을 확인하도록 작성했다. worker는 실행하지 않았다.
당시 제한값의 실제 동작과 성공은 이 기록 시점에 미검증이었다. 당시 인계 순서는 표적 회귀→새 Claude 전체diff 검토→
기본 GIT=1 full make check→scoped apply→변경된 실제 입력으로 새 quota 확인→동일480초
단1회 native GLM 검증을 수행한다. 성공 증거 뒤에만 기존 Git 역할/앱CI3/merge/cleanup/archive를
진행한다. 새 실패도 최초·후속 실패와 분리해 보존하며 이후 hourly/Sites 성공을 추정하지 않는다.

문서 영향은 native 요청 예산과 실패 경계를 정밀화하는 것이므로 agent-models와 본 ADR,
설계 경계와 ADR 목록을 갱신한다. 최종전체후보의 매 새 검토는
`documentation={status,files,reason}`으로 코드와 문서의 의미적 완전성을 새로 판단해야 한다.
앞선 documentation 승인·Markdown 확장자·오프라인 통과로 이번 판단을 대신하지 않는다.

## 후속 전체검사 중단/재개·실제 구조화 실패와 CLI 호환 수리 (2026-10-27)

parent 제공 run1793031743543582459-d3598c는 기존900초 구현 뒤 새 Claude 전체diff 승인과
표적422/422를 통과했다. 최초 전체검사 프로세스가 중단돼 parent가 원본/후보/검토 digest 일치와
원래 PID/하위검사 부재를 확인한 동일 run에서 native 전체검사를 재개했다. 결과6263/6263,
실패/오류/skip0 뒤 scoped apply19개와 기존 Git 역할까지 성공했다. 이는 그 후보의 검증이며
최초 중단을 없애거나 이번 변경의 승인/검증으로 재사용하지 않는다.

GitHub request 전 실제 GLM gate는 2026-10-27 01:53:10.860694~01:53:18.299834 KST,
elapsed7.437927초에 실패했다. quota ready1%, provider=zai/model=glm-5.3-flash와 원래 수집담당
9파일을 사용했다. 정제 진단은 role_execution_failed/cli_failed였다. private 실제 CLI envelope는
terminal_reason=structured_output_retry_exhausted, subtype=error_max_structured_output_retries,
`Failed to provide valid structured output after 0 attempts`, Read1개를 관측했다.
stderr unrecognized_model 경고는 실패 원인으로 쓰지 않는다. API usage0/duration_api0은 CLI
관측 그대로이며 실제 API 미호출을 단정하지 않는다. 원격 요청 events0, PR없음으로 중단했다.
parent는 후보/검토/검사/실제 실패를 private 보존하고 같은19파일만 원래 baseline으로 복원한다.
이전480.172811초 timeout·7.437927초 실패·검사 중단 기록은 수정하거나 성공으로 전환하지 않는다.

### 설치 CLI의 확정 합성 재현과 0/1 계약

parent는 실제 설치 CLI와 localhost 합성 서버로 다음을 재현했다. 외부 모델 호출은0이며 이
worker가 재실행한 검사가 아니다.

| 구조 budget | 응답 순서 | 관측 |
| --- | --- | --- |
| 0 | 바로 유효 StructuredOutput | HTTP1회 성공 |
| 0 | 첫 응답 Read | Read1개 뒤0attempts 오류, 다음 structured 요청에 도달하지 못함 |
| 1 | Read3개→유효 StructuredOutput | HTTP4회 성공, structured_output={candidates:[]} |
| 1 | Read2개→불량 StructuredOutput | HTTP3회 후 즉시 실패, errors는1attempts/schema candidates must be array, 추가 repair 요청0 |

따라서 native Z.ai discovery의 `MAX_STRUCTURED_OUTPUT_RETRIES`만0에서1로 바꾼다. 첫 구조화
시도와 정상 Read 흐름을 허용하며 불량 structured 응답 뒤 자동 repair를 추가하지 않는 설치 CLI
호환 수리다. `CLAUDE_CODE_MAX_RETRIES=0`은 유지한다. 같은1 invocation 안의 Read 대화는
실패 후 새 CLI 호출이나 retry가 아니다. 일반 Z.ai/Codex/Claude, low effort·ALWAYS_ENABLE_EFFORT·
8192cap·forced thinking·--effort low·strict schema·최종 후보 validator·read scope·credential 분리는
그대로다. free JSON fallback·경로 보정·무조건 빈 후보·근거 합성으로 통과시키지 않는다.

기존 subprocess 환경 회귀의 기대값만1로 고치며 성공/cap/프로토콜/timeout의 단1회 CLI 호출,
일반 역할·Codex·parent 환경 격리 assertion을 보존한다. worker는 검사하지 않았다. 이번1/0 설정의
새 실제 GLM 성공은 이 절 작성 당시 아직 미검증이었다. 이후 실제 성공은
[최신 main 관측](#2026-10-27-최신-main-관측)에 별도 기록한다. 당시 parent에게 새 최종전체diff의
Claude 의미 검토와 필수 `documentation={status,files,reason}` 판단, GIT=1 full make check·
scoped apply·기존 Git 역할 수행, 새 입력 fingerprint와 quota 확인 뒤 동일480초 단1회 실제
GLM gate 검증을 인계했다.
이후 기존 앱 Git/CI3/merge/cleanup/archive도 parent 책임이었다. 과거 승인/전체검사/합성 성공은
이 새 실제 성공을 대신하지 않는다. day/frozen/publication/hourly 상태·cron/private config·예산·
모델/인증·37scope·128KiB/1.5MiB는 유지한다. runtime 승인10개 외27개 합773709bytes는 parent
제공 상수로 유지하며 그 소스를 외부 모델에 제공하지 않는다.

문서 영향은 기존 ADR0034의 native 실행 계약에 대한 호환 정정으로 이 ADR을 갱신한다.
새 역할·격리·실패 복구·게시 정책을 도입하지 않아 새 ADR은 만들지 않는다. 이번 자체 판단은
`documentation={status: updated, files: [docs/agent-models.md, docs/harness-design.md,
docs/adr/0034-inspection-failure-recovery-and-health.md, docs/adr/README.md], reason: 설치 CLI의
구조 budget0/1과 transport0 계약 및 실제 실패/검증 대기를 최종 코드에 맞춰 정정}`이다.
매 후속 검토는 최종전체diff와 문서를 새로 판단하며 이 판단이나 앞선 Markdown 승인을 재사용하지 않는다.

## 이번 재개 수리와 검증 실패 기록

최종 parent 정정에 따라 run1793024077756804485-d143a3의 전체 preseeded 후보를 이어 쓴다.
그 run은 한 차례 수리 뒤 새 Claude 승인을 받았으나 full make check는 실패했다. 실제 선택은
하위 그룹 downloader129/129, parser5942/5940, Django67/67+11/11, pipeline72/72이며 parser는
정확히2개 assertion 실패, skip0이었다. 적용 소스는 없었고 GitHub tool dispatch도 없었다.
이 검토/검사 기록은 실패로 보존하며 이번 최종 승인/검증 성공에 재사용하지 않는다.

첫 실패는 fake9단계의 non-zai cloud 호출 기대값 누락이다. 실제 coordinator/codex 외에
parser/codex·django/codex와 reviewer/claude를 순서대로 기대하고, 모든 해당 역할 및 local의
schema 부재 검사는 그대로 둔다. 역할 호출을 없애거나 assertion을 약화하지 않는다.
두 번째는 승인 밖 test_review_coverage의 snapshot_sources 총량 초과다. 이 파일/37목록은
worker가 열거나 수정하지 않는다. parent의 실제 합계1592676bytes는 ceiling1572864보다 컸고,
기존 baseline1569698도 한도에 가까웠다. 승인 runtime10파일만 합산하고 나머지27파일은
parent 검증 상수773709bytes를 사용한다. 후보 목표는1560000bytes 이하·개별131072bytes 이하다.
상한/목록/ownership을 늘리지 않고 중복 상세는 이 ADR에 모으며 아래 역사 기록은 원문 보존한다.
당시 후보의 승인10파일 UTF-8 합은785233bytes, supplied27 상수와의 합은1558942bytes였다.
당시 승인10 중 최대는 harness/test_improvements.py의126959bytes였다. 이는 당시 byte 회계이며
실제37개 재측정·docs checker·full make check 성공을 뜻하지 않는다. parent가 최종본으로 확인한다.

hourly 통합 fake/Lab 명세는 정상/역할 실패 저장 뒤 잠금·deadline 해제, 후속 같은 역할 성공,
startup/child/discovery/status/no-deliver/rollback no-send, 전송 실패의 독립성·unknown/sending
GET-only 및 frozen web/history/ledger 보존을 다룬다. worker는 검사·네트워크·Git을 실행하지 않는다.
parent의 새 full check·실제37개 재측정·새 독립 Claude documentation 판단이 필요하다.
정확한 새 코드 apply 뒤 Git 게시 전에 단1회 GLM 개발 probe를 수행하고 실제 결과를 기록한다.
그 뒤 기존 Git 역할/CI3/merge/cleanup/archive와 별도 Sites parity/build/deploy/readback도 parent
책임이다. 이 수리 기록 작성 당시에는 새 실제 GLM 성공·후속 hourly 성공·Sites 전달이 아직
미관측이었다. 이후 관측 범위와 남은 한계는 [최신 main 관측](#2026-10-27-최신-main-관측)을 따른다.

### 후속 sender 회귀 실패 수리 (2026-10-27)

parent 제공 stack에서 `test_post_tick_sender_failure_is_separate_from_completed_research`는
sender 잠금에 `forbidden`을 주입해 `pytest.fail`로 중단됐다. 이는 운영 I/O 예외가 아니므로
production catch를 BaseException으로 넓히지 않는다. 회귀는 OSError/KeyboardInterrupt를
명시 주입하고, 성공/역할 실패 각각에서 health_unavailable·최초 역할 진단·정산/회계 보존,
sender 단1회·outbox 없음·credential/HTTP 금지를 검사하도록 수정했다. 기존 forbidden 경계는
유지한다. 이 수정은 회귀의 장애 주입을 바로잡으며 실제 sender 복구 성공의 관측이 아니다.
추가 unattributed/unavailable 진단은 원인 정보가 없어 이 실패와 같은 원인으로 단정하지 않는다.
이번 worker는 검사를 실행하지 않았고 parent의 새 전체 검사와 독립 의미 검토가 필요하다.

documentation={status: updated, files: [docs/adr/0034-inspection-failure-recovery-and-health.md],
reason: 회귀 장애 주입 수정과 미관측 한계를 기록했다. 운영 구조·계약·권한은 바뀌지 않아
기존 설계/운영 문서의 sender 실패 격리 설명은 그대로 유효하다. 최종 reviewer는 새로 판단한다.}

### 동일 slot morning sender 경계 정정 (2026-10-27)

parent 제공 실제 process 회귀에서 morning POST callback 중 같은9시 slot의 중복 tick이
sender mutex를 확인하지 않아 원래 callback의 검증이 실패하고 publication_unknown이 됐다.
health 중복 방지 조건을 morning publication에 재사용한 것이 원인이다. 정상 반환한 tick의
morning 경로는 clock_rollback을 제외하고 동일 slot에서도 sender를 확인한다. 초기 config/
Store/readiness/binding/bootstrap/save 실패는 자격을 얻지 않으며 readiness 재시도도 없다.
실제 sender_lock 경계의 busy는 publication_unknown으로 뭉개지 않고 고정 진단으로 반환한다.
정산된 최초 역할 실패·history/slot/회계와 별도 health의 무전송 조건은 보존한다.

승인된 test_improvement_health에 실제 fork/process·같은 slot·morning POST callback 회귀를
추가했다. 중복의 sender_lock_busy·callback/model0회·state 보존·health 미전송과 원래
POST→GET delivered·후속 별도 health 전달을 요구한다. 기존 OSError/KeyboardInterrupt
장애 주입과 assertion은 유지한다. 승인 밖 test_project_lock은 읽거나 수정하지 않았다.
worker는 검사를 실행하지 않았다. 앞선 실패는 보존하며 parent의 표적 회귀·새 full make check·
실제37개 bytes·전체diff Claude review와 새 documentation 판단·실호출/게시/관측이 필요하다.

```text
documentation={status: updated, files: [docs/improvements.md,
docs/adr/0034-inspection-failure-recovery-and-health.md], reason: morning sender 진단과
health 자격의 경계를 정정하고 새 process 회귀의 검증 대기를 기록했다. 기존 계약 복원이므로
새 ADR 결정은 없으며 모델/권한/Git/전달 schema 정책은 유지한다. 최종 reviewer는 새로 판단한다.}
```

### process 재현 callback 위치 정정 (2026-10-27)

parent 제공 run1793028756997486802-7dbffc는 새 Claude 승인 뒤 표적68개 중66개 통과,
새 health 재현의 deliver=False/True 두 경우만 실패했다. 기존 test_project_lock process 회귀는
통과했으며 source applied=[]·GitHub 미발행이다. 이 실패 기록과 앞선 기록은 보존하며 이전
승인을 최종본에 재사용하지 않는다. 이번 worker가 실행하거나 독립 확인한 결과는 아니다.

parent의 callback 내부 추적에서 duplicate는 paused/discovery_lock_busy였고 publication은
없었다. diagnostic은 boundary=discovery_lock, reason=discovery_lock_busy,
lock_kind=discovery, errno=11이었다. 추가 post/model 호출0·state 불변·health 미전송도
확인됐다. 기존 deliver_report의 HTTP POST callback은 Store.lock(discovery+artifact)을
보유하므로 이것이 최초 실제 실패 경계다. 이 위치에서 sender_lock_busy를 기대한 assertion이
기존 전송 오류 처리에 잡혀 parent의 GET까지 진행하지 못했다. readback 프로토콜 문제가 아니다.

새 health 재현의 fork를 명시 morning publisher callback으로 옮겼다. publish가 sender mutex만
보유한 이 경계에서 실제 child의 sender_lock_busy·진단·추가 post/model0·state 불변·health
미전송을 검증한 뒤 imp.deliver_report를 호출한다. fake HTTP는 morning POST→GET 및 별도
health 전달만 처리한다. duplicate deliver=False/True와 parent morning/health delivered·동일
digest assertions는 유지하며 pipe 수신량/대기와 child 종료 대기에 상한을 두고 실패 시 kill/reap한다.
운영 코드와 legacy HTTP 잠금 설계, 승인 밖 test_project_lock은 읽거나 수정하지 않았다.

documentation={status: updated, files: [docs/adr/0034-inspection-failure-recovery-and-health.md],
reason: parent 관측에 따라 재현 위치의 사실 오류와 검증 대기를 덧붙였다. 운영 구조·책임·계약·
격리·복구·게시 정책은 그대로여서 기존 설계/경계 문서와 ADR 결정은 유효하다. worker는 검사를
실행하지 않았다. parent의 표적 회귀→새 full make check와 전체 후보/문서의 새 Claude 의미
검토·documentation 판단이 필요하며, 최종 reviewer는 이전 승인을 재사용하지 않고 새로 판단한다.}

## 관련 코드·검증·문서

- 연결: [agent_models.py](../../harness/agent_models.py), [improvements.py](../../harness/improvements.py), [improvement_loop.py](../../harness/improvement_loop.py)
- 계약: [improvement_schema.py](../../harness/improvement_schema.py), [improvement_health.py](../../harness/improvement_health.py), [diagnostics](../../harness/improvement_diagnostics.py)
- 이번 변경의 미실행 회귀 명세: [schema](../../harness/test_improvement_schema.py), [adapter](../../harness/test_agent_models.py), [loop](../../harness/test_improvement_loop.py), [health](../../harness/test_improvement_health.py)
- 기존 회귀 참고(이번 변경 없음·재실행하지 않음): [discovery](../../harness/test_improvements.py), [진단](../../harness/test_improvement_diagnostics.py)
- 경계: [AGENTS](../../AGENTS.md), [모델](../agent-models.md), [아키텍처](../architecture.md), [설계](../harness-design.md), [운영](../harness.md), [개선 계약](../improvements.md)

## 과거 인계 원문 보존 부록

원래 문서의 제목/anchor는 유지하고 이 부록으로 연결한다. 아래는 당시 기록이며 현재 계약은 위 결정과
각 원래 문서의 현재 운영 절을 따른다. 승인 밖 파일을 추가로 읽거나 복사한 기록이 아니다.

### 보존 인계 current

#### 원문 docs/improvements.md — 현재 검토·검증 인계

이관일2026-10-26. 관측일/당시 run·실패·승인 한계는 아래 원문 그대로이며 현재 성공 증거가 아니다.



문서 영향은 구조·책임·데이터 계약·격리·예산·시간·복구 전반이다. 전체33개 구현 초안의
승인 Markdown 검토 범위는
`AGENTS.md`, `docs/architecture.md`, `docs/harness-design.md`, `docs/harness.md`,
`docs/workflow.md`, `docs/agent-models.md`, `docs/improvements.md`, `docs/local-models.md`,
`docs/adr/0015-approval-gated-improvement-discovery.md`,
`docs/adr/0016-bounded-private-improvement-text.md`,
`docs/adr/0017-budgeted-continuous-improvement.md`, `docs/adr/README.md`다.
이 후속 문서 보정은 나머지10개를 정정하고 ADR0015의 승인 결정·대체 범위와 ADR0016의
기존 서술/envelope 변경·역사적 거부 기록은 그대로 보존한다. 두 ADR은 이미 최신 운영 상태를
0017/운영 문서로 연결하므로 추가 수정이 필요하지 않다.
매 reviewer는 이 최종 코드와 실제 수정 문서의 의미를 독립 평가해
`documentation={status,files,reason}`을 반환한다. updated files는 실제 changed .md만 열거하며
확장자/존재 확인만으로 내용의 완전성을 주장하지 않는다. 부족한 승인 밖 파일은 읽거나 추가하지
않고 정확 경로를 기존 승인 파일 finding에 귀속해 changes_requested/missing으로 남긴다.

기존 harness runner는 parser group에서 `harness/test_*.py`를 수집하며 pytest.ini는 이 경로를
제외하지 않는다. 따라서 test_agent_models/test_local_model/test_improvement_loop/test_improvements가
전체 make check에 자동 포함된다. 의미 있는 offline 회귀는 fake clock/modeled runner/HTTP와
isolated temporary storage로 반복/restart/동시lock/같은slot·clock rollback·자정09:00·legacy
carry-in/day 보존·publication exactly-once 확정/unknown/동시sender·실제 prompt feedback·cursor·
source/config 변경·초안 실패·reserve 실패/crash/settlement/overrun·GLM 두 형식/weekly/unknown/
80%·비밀/public 미노출·approve invariants를 다룬다. 명세 존재는 성공 결과가 아니다.

아래는 종전 기반 구현의 인계 기록이며 이번21개 파일 수리의 범위·운영 상태·검증 결과가 아니다.
worker는 실모델/네트워크/검사/테스트/Git/cron/workflow/재위임을 실행하지 않았다.
이전 run1792072384459739669-64629e의900초 timeout/applied=[] 기록은 유지한다. 그 다음
run1792078026182747557-b4f614은8개 구현 작업과 Claude 검토를 마쳤으나 NFS full check가
1800초에 timeout되어 failed/applied=[]였다. 원본은 시작 baseline 그대로이고 GitHub 게시·
당시 운영 활성화는 없었다. 메인이 bytes/mode를 확인해 당시 격리 context에 복원한33개 초안은
새 승인이나 전체 검증 성공의 증거가 아니다.

메인 제공 실제 결과는 doctor passed, downloader103/103 passed, parser+harness3502개 중
3439 passed/63 failed/skip0이다. timeout 뒤 남은 parser 결과이며 Django/pipeline 검증은
확인되지 않았다. 별도 메모리 진단에서 정상 local HTTP fixture의 JSON Content-Type만 보완한
loop138개는137 passed/1 failed였고 남은 실패는 Store 준비 예외 전파였다. 별도 합성9단계의
완료·후보4개·review_complete=true·추정비용0.04 관측도 전체 검사 성공은 아니다.

당시 좁은 수리는 정상 HTTP/Korean 후보·trusted-parent CLI 환경·독립 feedback/context 제한
fixture와 Store 준비 실패 처리, zero-idle quota 및 reviewer 대기를 다룬다. 공개 권한 거부
fixture는 합성 두 디렉터리에 chmod0755를 명시해 umask 의존성을 없애며 production 권한 검사는
유지한다. 새 full check와 umask077/022의 해당 회귀 검증은 메인/실행기가 담당한다.
메인은 이번 실행에만 agent_timeout_seconds=1800/check_timeout_seconds=3600/max_rounds=3을
선택하며 저장소 workflow-config·다른 한도·모델·기존 NFS/temporary 정책은 변경하지 않는다.
새 Claude 의미검토·전체 diff/의미 검토·full make check·scoped apply·기존 Git 역할이 모두
남아 있다. 실제 repository 첫9단계·hourly 활성화·검증된 GitHub 전달·아침 게시 확인은 메인 책임이다.

기존 create_tree의 automatic approval review 거부(명시 공개 동의 부족) 기록은 아래와 ADR0016에
보존한다. 이번 직접 요청의 구현·전달은 기존 Git 역할과 검증된 앱 요청을 메인에게 인계한다.
원격 baseline 불일치나 명시 승인 거부 시 중단하고 worker가 쓰기/공개 요청을 재실행하지 않는다.
현재 문서 편집·합성 MLX 관측·과거 doctor/check 성공을 이번 최종 검토/검사/게시 성공으로 쓰지 않는다.

이번 native schema 수리는 coordinator 단일 작업으로 승인21개만 다룬다. 세 테스트 파일의
오프라인 회귀는 실제 window/schema 일치·양쪽 evidence/편집 목록 거절·tampering no-transport·
전체 bytes/whole-line·schema overhead 초과·서버 무시 응답 거절·유효 후보/empty_draft·단1회·
v1/v2/provider/digest/loop fingerprint·specialist skip·진단 privacy를 다룬다. 실행하지 않았으며
전체 make check는 메인 하네스 대상이다. 검증 사본 이동·재사용은 parent가 NFS 원본 baseline과
같음을 재확인한 준비 절차일 뿐 검증 성공이나 local fallback이 아니다. 운영 상수·37개 scope·
승인 게이트는 보존하며 스케줄·ledger·확정 보고서·게임 cron·runtime private config는 수정하지 않는다.

전달된 회귀 실패 위치를 이번 승인 소스와 대조해 테스트 입력만 바로잡았다. schema/window
사례는 `[SOURCE,DOC,OTHER]` 순서에서 한 줄 DOC의2행을 요청했으므로 OTHER의2행으로
옮기고 DOC의1행 사례도 둔다. 정확한 요청 경계와 schema-only 초과 사례는 feedback 상한1byte가
빈 `[]`의2bytes를 거절해 본래 예산 검사에 이르지 못하므로2bytes로 바꾼다. 기존 stale cursor와
feedback 초과 거절·운영 상한은 유지한다. 예외 정보가 unavailable인 항목의 전체 원인을
확정하지 않으며 새 독립 검토·전체 make check 결과는 대기다. worker는 검사를 실행하지 않았다.


### 보존 인계 protocol

#### 원문 docs/improvements.md — 이번 프로토콜 수리의 문서 영향

이관일2026-10-26. 관측일/당시 run·실패·승인 한계는 아래 원문 그대로이며 현재 성공 증거가 아니다.

시작 시 10개 문서 모두 요청 계약·검증·책임/배포 설명의 일치 여부를 검토 대상으로 판단했다.
이번 진단 수리의 최종 자체 판단은 `updated`이며 실제 문서 수정은 local-models/harness/이 문서다.
다른 문서는 보존 초안이 이미 최종 계약과 일치해 유지했다. 독립 Claude의 승인이나 하네스
성공 판정은 아니며 각 후속 review는 최종 코드와 문서의 의미를 새로 판단한다.
이번21개는 coordinator 단일 작업으로 다룬다.

| 승인 문서 | 시작 영향·최종 자체 검토 이유 |
| --- | --- |
| AGENTS.md | 유지: 최종 protocol·작업자/메인 책임·관측 한계와 운영 상수가 이미 일치 |
| docs/adr/0017-budgeted-continuous-improvement.md | 유지: native schema·v2 이행·컴파일 제약·검증 대기를 이미 기록; 이번 입력 수리는 새 결정이 아니며 새 ADR 없음 |
| docs/adr/README.md | 유지: 결정 목록/상태가 ADR0017의 최종 경계·검증 대기와 일치 |
| docs/agent-models.md | 유지: mlx-vlm/v2/repository API model·구조화 출력과 기존 cloud 책임이 이미 일치 |
| docs/architecture.md | 유지: schema/request/source 격리·최종 client 검증·설정 digest·승인 경계에 동작 변경 없음 |
| docs/harness-design.md | 유지: prepared request 결합·두 transport seam·bytes/window·실패/진단 책임에 변경 없음 |
| docs/harness.md | 수정: 회귀의 유효 cursor·빈 feedback2bytes와 미실행/전체 make check 인계 명시 |
| docs/improvements.md | 수정: 입력 수리의 근거·미확정 예외 한계·현재 인계 및 파일별 시작/최종 판단 기록 |
| docs/local-models.md | 수정: feedback 선행 예산과 회귀 입력 수정 설명; wire/schema/config·null metadata/uniqueItems·메인 관측 한계 보존 |
| docs/workflow.md | 유지: coordinator1작업·독립 검토/full check/scoped apply/Git 순서와 검증 사본 경계에 변경 없음 |

비문서11개도 같은 시작/최종 영향 판단으로 검토했다.

| 승인 파일 | 변경/유지 이유와 문서 반영 |
| --- | --- |
| harness/local_model.py | 유지: native schema/v2/전송 결합·bytes·null 도구 구현은 계약에 일치; stale cursor/feedback 거절을 테스트에 맞춰 완화하지 않음 |
| harness/local-model-config.json.example | 유지: 이미 v2/mlx-vlm/api_model==model; 명시 이행 계약은 local-models/agent-models에 기록 |
| harness/improvement_loop.py | 유지: 새 provider 검증/참여·local digest fingerprint·당시 provider를 보존하는 중단 복구가 이미 일치 |
| harness/improvement_report.py | 유지: 새/과거 local provider의 public cloud 참여 위장 거절·공유 후보 진단/수용 계약이 이미 일치 |
| harness/improvements.py | 유지: 기존 freshness/서명 승인·cloud 후보 경로가 local config digest를 결합; 기존 승인 경계 보존 |
| harness/improvement-config.json | 기존 cloud 후보 상한·shared scope·승인 계약 보존; 운영 문서의 상수와 일치해 유지 |
| harness/improvement-loop-config.json | 하루24회/Claude$1/09:00/한 hourly slot 등 기존 운영 상수 보존으로 유지 |
| harness/improvement-scope.txt | 기존37개 읽기 승인 유지; 이번21개 개발 scope와 혼동해 늘리지 않음 |
| harness/test_local_model.py | 수정: 재정렬 목록의 실제 cursor·원문 비교·문서1행 사례, 요청/schema 예산 사례의 빈 feedback2bytes; 기존 schema/변조/privacy/v2 회귀 보존·미실행 |
| harness/test_improvement_loop.py | 유지: native fixture·specialist skip/진단 privacy·migration fingerprint·복구 provider 회귀가 이미 포함; 실행은 하네스 책임 |
| harness/test_improvements.py | 유지: public projection의 새/과거 local provider 거절·기존 승인·cloud 후보 진단/수용 회귀가 이미 포함 |


### 보존 인계 history

#### 원문 docs/improvements.md — 이전 수리의 검토·검증 인계 기록

이관일2026-10-26. 관측일/당시 run·실패·승인 한계는 아래 원문 그대로이며 현재 성공 증거가 아니다.



아래는 2026-10-15 수리 당시의 GIT=0·문서 영향·자동승인 거부 이력이다. 현재 작업의
파일 변경 목록/운영 상태/공개 전달 권한으로 재해석하지 않으며 최신 인계는 위 절을 따른다.

2026-10-15 후보·reviewer 길이/모델 transport 수리의 문서 판단은 `documentation.updated`이며 실제 변경 문서는
`docs/improvements.md`, `docs/architecture.md`, `docs/harness-design.md`,
`docs/adr/0016-bounded-private-improvement-text.md`, `docs/adr/README.md`다.
후보·reviewer 수용/표시 데이터 계약·전체 private review 승인 결합·검토 입력·모델 전용
envelope/원래 byte 검사·실패 경계를 기록한다. 아래 기반 구현의
역사적 인계 목록은 이번 변경 목록과 구분한다. `docs/harness.md`는 명령·검증 실행 책임·환경
설명이 바뀌지 않아 수정하지 않으며 AGENTS와 ADR0015의 권한 정책도 그대로 유지한다.

메인 제공 원인 관찰은 첫 실제 scan에서 419자 issue가 기존 400자 표시 한도로 거부되어
두 후보가 사라졌다는 것이다. raw 응답 64KiB 초과는 아니었다. 원문이나 credential을 fixture에
옮기지 않았다. 합성 오프라인 회귀에는 419자/279자 두 후보의 전체 독립 검토·private 저장·
재검증·명시 승인 후 task 전달, 4배 ceiling의 정확/초과 경계, 표시 말줄임과 suffix별 원본 ID,
정상 digest를 가진 oversized public 카드 거부, invalid 구조의 전체 거부·partial daily 재사용을 둔다.
기존 daily 날짜 idempotency·명시 same-day discover·human 기록 보존·authority guard 회귀도 유지한다.
새 retry·역할 호출·provider/context 예산·storage 변경은 없다. worker는 검사를 실행하지 않았다.
이번 local continuation은 `GIT=0`이다. 오케스트레이터의 새 Claude 문서/구현 검토·전체
`make check`·local apply
뒤 승인된 수동 실제 재점검과 정제 private 보고함 전달은 메인이 수행한다.
이 수리는 새 실제 점검 성공이나 보고 전달 완료의 증거가 아니며 발견 제안은 별도 사용자 승인 대상이다.

메인 제공 후속 관찰: 기존 8파일 길이 patch는 Claude 검토와 selected 3158 tests를 통과했다.
실제 재점검에서 GLM runner는 passed였지만 전체 응답이 단일 json fence여서 transport 파싱이
실패했다. 메인의 내부 strict JSON/승인 source 검사는 두 후보가 유효함을 확인했지만 이를
보고에 승격하거나 승인/claim/실행하지 않았고 partial 보고를 정직하게 전달했다. 이 worker는
그 private 원문을 읽거나 fixture에 복사하지 않았다. 이 관찰은 이번 변경의 검증 성공이 아니다.
추가 합성 명세는 bare/fenced 내용·ID/digest 동등성, fenced 419자 후보 전체 독립 review와
bounded 웹 출력, fenced reviewer, LF/CRLF·문자열 backtick, 잘못된 container/strict JSON의
partial 및 daily 재사용, wrapper/공백 포함 원래 UTF-8 byte 경계와 config/public/storage의
strict parsing을 대상으로 한다. worker는 새 명세를 실행하지 않았다.

최신 메인 제공 관찰 `1792065346555306548-d8a875`: GLM을 포함한 네 specialist는 모두
성공하고 두 후보를 만들었으며 Claude reviewer runner도 passed였다. 첫 review reason
416자가 private/display 공유 360자 검증에서 거부되어 완료 review가 되지 않았다.
두 번째 reason 351자, 전체 documentation reason 176자와 후보별 142/159자는 기존 한도
안이었고 문서 경로도 승인 scope 안이었다. 원문은 fixture로 복사하지 않았다. 후보는
승인·claim·실행되지 않았으며 partial 보고만 전달했다는 메인 제공 근거다.
이번 합성 명세는 정확히 specialist 4회+reviewer 1회의 416자 scan 완료, 세 private reason
1440자 수용/1441자 거부와 저장 후 eligibility/authorization 재검증, full review의 명시 승인
후 mocked task 전달, 표시 prefix 밖 suffix의 review_digest 결합 및 기존 승인 무효화,
public 360/361자와 재계산 digest의 검증·render 거부를 포함한다. 구조·문서 최소 길이·scope·
coverage·verdict·필수 문서 edit_files·byte/fence/short digest 회귀는 유지한다.
이전 3215 passed는 새 수리의 검증이 아니다. 새 Claude 검토·전체 make check는 실행기,
local apply·새 읽기 전용 실점검·정제 private inbox 전달은 메인 소유이며 아직 대기다.

GitHub `create_tree`는 명시적 공개 동의 부족으로 automatic approval review가 거부했다는
메인 제공 상태를 유지한다. 모든 Git 쓰기/재요청은 중단되어 있으며 이번 `GIT=0` 수리는
공개 게시 승인이나 journal 변경이 아니다. 메인은 영향 없는 local 수리/보고 전달을 마친 뒤
별도 공개 승인을 요청한다. 이 문서는 공개/CI/merge/cleanup 완료를 주장하지 않는다.

아래는 기반 구현 당시의 역사적 문서 영향 기록이며 이번 변경/열람 목록이 아니다.
당시 권한·책임·격리·schema·검증·실패 복구·게시 정책 변경은
`documentation={status:updated,files:[AGENTS.md,docs/architecture.md,docs/harness-design.md,
docs/harness.md,docs/workflow.md,docs/improvements.md,docs/adr/README.md,
docs/adr/0015-approval-gated-improvement-discovery.md],reason:...}`에 해당하는 실제 Markdown을 수정했다.
이 목록은 worker의 변경 인계이며 최종 reviewer의 의미적 승인이나 문서 완전성 증명이 아니다.
docs/agent-models.md는 참조만 했고 기존 설정을 유지하므로 수정하지 않았다.


### 보존 인계 importer

#### 원문 docs/harness.md — 이번 importer/cleanup 수리의 후보 근거와 검증 대기

이관일2026-10-26. 아래는 이전 수리의 원문이며 관측일·실패·대기·성공의 한계를 그대로 보존한다.


이번 범위는 기존 `files-repair.txt`의 정확히 31개 개별 파일이다. 원래 최적화와 추가 8개
repair 파일의 작업 승인을 유지하되 이 수리는 importer snapshot/SELECT와 호출 소유 임시
cleanup만 완료한다. `parser_tidy/items.py`·`luautil.py`는 바꾸지 않는다. 장비 Lua batching은
제공된 측정에서 4.8% 느려 제외되었으며 해당 Lua ADR은 만들거나 index하지 않는다.
기존 역할/provider/model과 후속 PAK 실행용 GLM을 유지한다. 기존 configured NFS 선택·mount·
floor도 유지하며 local storage override나 activation 변경은 없다.

`load_import_snapshot`은 모든 JSON의 strict validation/order를 유지하고 consumed collections와
version만 반환한다. 활성 handle의 staging 소비자에는 deepcopy, direct/prev에는 fresh read를
적용하며 성공·실패·retry에서 상태를 버린다. SELECT 인덱스는 canonical ID와 기존 item
분류 목록/우선순위/오류, 스킬 행별 save·update=0·created/updated·삭제 및 missing/ambiguous
예외를 보존한다. 새 snapshot API/ORM 검증은 기존 scoped `test_release_contract.py`,
`test_import_safety.py`, `harness/contract_tests.py`에 두고 기존 테스트와 제외를 유지한다.
호출 소유·nested copy·strict order·fresh direct/prev·failure/retry·state cleanup과 실제
save/audit/write 수·삭제·참조 예외를 의미 있는 기대값으로 확인해야 하며 skip을 추가하지 않는다.

아래는 메인이 제공한 **검토된 후보의 진단 근거**다. 이 worker는 재측정하거나 검사하지 않았다.

| 제공된 관측 | 범위와 한계 |
| --- | --- |
| isolated importer 3회: 첫 실행 wall 31.7%, 반복 실행 48.1% 감소 | 후보/기준의 importer 비교이며 최종 소스나 전체 pipeline 개선율이 아님 |
| 반복 SELECT 1604→100 | read 최적화; bulk write나 save 생략의 근거가 아님 |
| 33개 테이블: 자동 audit timestamp 외 값 동일 | audit 값을 제외한 DB 비교이며 모든 필드의 byte 동등성 주장이 아님 |
| 정확한 prev bytes 및 INSERT/UPDATE/DELETE 수 동일 | 후보의 비교 기준/쓰기 동등성 근거 |
| fresh isolated kTOS/iTOS/jTOS main: 지역별 41개 JSON bytes baseline과 동일 | 후보 지역 출력 비교이며 반영한 최종 소스를 다시 확인해야 함 |
| selected parser/harness 2691 tests passed, zero skips | parent의 부분 검사 기록; 전체 make check/full workflow 성공이 아님 |
| NFS statvfs probe 회복 | 제공된 장애 회복 관측; cleanup 성능·최종 validation 완료가 아님 |

prior real models와 Claude가 공급된 후보 diff를 승인했으나 새 cleanup/readiness 수리 후 최종
소스의 fresh real review가 필요하다. 이전 full workflow는 NFS RPC 대기 중 timeout했으며
old parent `shutil.rmtree`는 readonly keep에서 실패했다. selected tests 이후에도 cleanup이
매우 느렸다. **full validation은 통과하지 않았고 현재 pending이다.** 최종 수리의 cleanup
성능/성공·전체 `make check`·최종 source bytes/ORM 비교·실제 CI/merge/cleanup 성공을 꾸미지 않는다.

이번 repair 입력의 `check` diagnostic은 context unavailable·unattributed다. 이 정보만으로
실패 원인이나 특정 파일의 책임을 추정하지 않으며 기존 후보의 timeout/cleanup 실패와
같은 원인으로 합치지 않는다. 최종 소스의 새 실제 review 후 원래 필수 checks를 모두 실행하는
책임은 오케스트레이터에 남는다.

오케스트레이터가 새 실제 review, complete `make check`와 기존 tests/제외·zero-skip 확인,
31파일 scoped apply 및 기본 Git 역할을 담당한다. main은 최종 소스 근거를 확인한 뒤 정확한
GitHub 앱 journal을 실행하고 `Offline harness (SQLite)`, `MySQL harness`,
`Chromium browser harness`의 실제 success 3개, SHA 고정 merge와 cleanup 완료를 확인한다.
worker는 checks·Git·workflow·agent-run·다른 모델·cron·download·importAll을 실행하지 않는다.
외부 모델에는 승인 31파일만 주며 private config/diagnostic 파일은 주지 않는다.

### 보존 인계 parser

#### 원문 docs/improvements.md — 2026-10-20 parser 편집 목록 중복과 수리 인계

이관일2026-10-26. 아래는 이전 수리의 원문이며 관측일·실패·대기·성공의 한계를 그대로 보존한다.


parent가 제공한 최초 관측은 run `1792483202194321920-447ddb`의 2026-10-20 21:00 KST
정규 `local(parser)` 호출이다. Qwen3.5-9B-4bit가 AGENTS.md 원문1..96줄로 실제 실행된 뒤
client가 `candidate_edit_files_duplicate`로 거절했다. 이전 local(coordinator)·Codex·
local(downloader)·GLM은 실제 성공했고 GLM 후보2개가 있으나 정규 전체 성공은 아니다.

후속 run `1792500541005476257-a59052` round1은 오프라인 full4895개를 모두 통과했다.
그러나 2026-10-20 22:06 KST parent의 같은 실제 로컬 서버 parser/AGENTS.md1..96/동일 config
개발 검증 HTTP1회는 `called=true`, `reason=candidate_edit_files_duplicate`,
`verification=failed`였다. request18724bytes, 134.805초, 운영 state 불변이었다.
기존 세 문장을 보존하고 필요한 경로를 한 번 쓰라는 설명을 추가한 뒤에도 실제 중복은 지속됐다.
두 실패의 원문은 저장하지 않아 반복 경로·개수·정확한 후보 값은 알 수 없으며 추측하지 않는다.

이후 순서 지침을 반영한 PR59(`65c19f53cfaa461cd994cf61d435a32ae9b609a9`)는 오프라인
4895개를 통과했고, 2026-10-20 22:37 KST parser/AGENTS.md1..96 개발 HTTP1회에서 유효
초안2개(각각 edit_files1개)가 확인됐다. 이는 한 owner의 단일 성공이며 전체 역할의 해소가 아니다.
같은 mlx-vlm/Qwen3.5-9B-4bit 서버의 2026-10-20 23:00 정규 run
`1792504802000339115-d6a0c0`에서 local(coordinator)는 AGENTS.md1..96으로 실제 호출됐고
`called=true`, `reason=candidate_edit_files_duplicate`로 다시 거절됐다. parent 관측 시각은
시작23:00:01.927730·종료23:01:16.865115 KST다. 원문 미보존으로 이번 반복 경로·개수도
알 수 없으며 추측하지 않는다. 과거 테스트 문구 누락과 구분되는 실제 생성 중복의 재발이다.

이번 coordinator 수리는 순서 지침에 현재 owner의 실제 승인 경로로 만든 단일·두 파일 JSON
필드 예시를 추가한다. 승인 파일 하나에는 단일 예시만 제공하며 예시는 형식 설명이고 실제
후보는 필요한 편집 파일만 선택한다. 생성과 정확한 canonical system 검증을 같은 승인 목록에
맞춘다. 중복 방지나 실제 추론 성공을 보장하지 않는다. native schema/owner enum,
원문 window, enable_thinking=false, 배열1..12·문자열 합600, client 최종 검증과 고정 duplicate
진단, request24576bytes 내 whole-line 선택·canonical binding·출력·timeout은 유지한다.
uniqueItems·decoder/validator 완화·자동 dedup·경로/줄/후보 보정·원문/출력 재작성·재시도·
fallback은 추가하지 않는다. 모델·인증·예산·시간당1회/일24회·원래37개 source scope·
보고·승인·Git·스토리지 정책도 유지한다.

현재 변경의 최종 full/live 및 PR/CI/머지는 parent 관측 전까지 pending이다. 실제 정규9단계 및
2026-10-21 09:00 KST 오전 보고 성공 역시 별도로 pending이다. 작업자는 검사·모델 호출·
네트워크·SSH·서비스·Git·workflow·재위임을 실행하지 않으며 새 mirror/프롬프트 문자열 검사를
추가하지 않는다. 합성 snapshot·주입 transport로 owner 승인 범위·단일/다중 목록·실제 중복
거절·요청 변조 no-call·전체 byte 예산·whole-line 경계를 검증하는 동작 회귀를 작성하되 실행하지
않는다. parent가 full `make check`를 통과하고 과거 실패본 대비 실제 코드와 정확한 HTTP
요청이 달라졌음을 확인한 뒤에만 같은 실제 로컬 서버에 동일 coordinator/AGENTS.md1..96/config로
개발 검증 HTTP를 단1회 수행한다. 문서만 바뀐 같은 실패 요청을 재호출하지 않는다.
운영 state와 정규23시 slot을 재실행·변경하지 않으며 이 개발 검증은 전체9단계 성공을 대체하지 않는다.

parent는 raw/prompt/source를 저장하지 않고 고정 결과 코드·owner/window·해시와 필요한 경우
숫자형 중복 개수만 기록한다. client 검증을 통과한 빈 초안은 정상 빈 결과로 구분하며
후보를 강제하지 않는다. 새 live 실패는 실제 fixed reason과 owner/window를 같은 coordinator
담당자에게 돌려준다. 실제 검증·GitHub·CI·머지·정리는 parent가 담당한다.

문서 영향 판단: 기존 계약의 생성 안내를 명확히 하므로 두 운영 문서에 지침·관측·검증 대기를
기록한다. 구조·책임·데이터 계약·격리·검증·실패 복구·GitHub 게시 정책은 바뀌지 않아
`docs/harness-design.md` 수정이나 새 ADR은 필요하지 않다. 예시는 기존 owner 승인 경로만
설명하고 native schema·immutable binding·client 최종 검증·실패 시 무보정 단1회 호출을
유지하며 새로운 역할·저장 필드·승인·공개 경로를 만들지 않기 때문이다. 매 fresh reviewer는 최종 코드와
문서의 의미를 새로 평가해 `documentation={status,files,reason}`을 반환하며 앞선 문서 판단이나
회귀 통과를 재사용하지 않는다. 추가 문서가 실제 필요하면 승인 밖 파일을 읽거나 만들지 않고
정확한 경로와 기존 승인 파일에 귀속한 finding을 보고한다.

