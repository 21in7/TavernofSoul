# 승인 대기 시간별 연구와 오전 개선 보고

## 반복 role_json_invalid의 경계 수리

[ADR0034](adr/0034-inspection-failure-recovery-and-health.md)에 parent 제공 실제 실패 시각/원인,
full bounded schema·native envelope·strict client 후보/evidence 검증과 실패 복구 결정을 둔다.
Z.ai specialist discovery만 opt-in하며 legacy/reviewer Read stream·모델/인증/예산은 유지한다.
result fallback·문법 수선·모델 retry는 없다. native 형식은 의미적 정확성 증거가 아니다.
과거 downloader role_json_invalid와 오전 partial/frozen digest를 새 성공으로 바꾸지 않는다.

## 별도 owner-private health 계약

세 번째 고정 `improvement-health-v1`의 wire/allowlist·privacy·outbox·동일 POST/GET·reconcile은
[ADR0034](adr/0034-inspection-failure-recovery-and-health.md#health-wire-계약)에 둔다. cloud5역할의
실패 단계·고정 원인·실제 call 시각·후속 같은 역할 성공만 투영하며 legacy 결손은
unknown/unavailable/null이다. local·provider/model 자유문자열·비용·원문·키·절대경로는 보내지 않는다.
후속 성공으로 과거 실패를 지우거나 freshness·승인·전체 review 성공을 주장하지 않는다.

단일 tick의 정상 최종 save·모든 연구 잠금/deadline 해제 뒤 정산된 역할 실패도 전달한다.
초기 config/Store/readiness/binding/lock/bootstrap 실패·rollback·같은 slot·no-deliver·조회/
publish-morning은 자동 health 대상이 아니다. 같은 slot의 morning sender 잠금 확인 및 실제
sender_lock_busy는 별개로 보존한다. health 자격은 인간 신원/approval/execute 권한이 아니다.
수동 CLI의 child/discovery/unattended 거절은 유지한다. 별도 전송 실패는 health_publication/outbox에
남기며 최초 실패·회계·stage·morning을 덮지 않는다. unknown/sending은 GET만, 명시 frozen digest
reconcile+GET404만 재POST한다. delivered 뒤 다음 정상 tick은 새 관측을 보낸다.
추가 모델/scan·storage fallback·runtime37/상한·예산/quota·wrapper/cron 변경은 없다.

### Parent 조회와 고정 digest 전달

[운영 명령](harness.md#실패-복구-health의-parent-운영)과
[전달 계약](adr/0034-inspection-failure-recovery-and-health.md#parent-전용-독립-전달)을 따른다.

### 이번 범위의 검토와 미관측 상태

run1793024077756804485-d143a3의 full check parser2실패/skip0·apply/dispatch없음과 상세 수치는
[ADR0034](adr/0034-inspection-failure-recovery-and-health.md#이번-재개-수리와-검증-실패-기록)에 보존한다.
worker는 회귀 작성만 하며 새 Claude 의미/documentation 검토·full check·실제37개 측정·apply·
개발 probe·Git/CI3/merge/cleanup/archive·Sites 배포/readback은 parent 책임이다. 이전 검토를
재사용하지 않고 후속 실제 성공은 각 해당 관측으로만 기록한다.

## 잠금 격리와 실제 실패 관측

최신 잠금/복구 계약은 [ADR0027](adr/0027-inspection-lock-isolation-and-diagnostics.md)이다.
일반 개발/READ_ONLY 모델·검토·검증은 격리 사본에서 진행한다. workflow 전용 mutex와 달리
기존 source `.lock`은 capture/apply/cleanup/current freshness 동안만 보유한다. tick의 stable
discovery→artifact 잠금은 state·slot·call 예약을 보호하므로 동시에 두 tick을 호출해도 재호출
권한이 생기지 않는다. source-only 진행 보존과 control 무효화, 실제 Read proof/coverage와 ID별
최신 verdict·original provenance는 ADR0025/0026 그대로다. 보존 source 검토는 현재 eligible이 아니다.

09시 freeze는 현재 전체 dependencies 아래 새 seal/admission 전에 수행한다. 일반 workflow의
긴 model/check 완료를 기다리지 않는다. publication은 state/source mutex 밖의 stable sender와
기존 sender 잠금으로 동일 frozen digest를 전송하고 GET으로 확인한다. prepared 복구는 exact
journal만 사용하고 sending/unknown은 자동 재전송하지 않는다. 실제 apply/cleanup·구버전 holder나
짧은 capture가 source 판단을 막으면 no-call·구체적 실패/미완료 보고다. 정상0개로 표현하지 않는다.
state·storage가 불가하면 보고 확정도 불가할 수 있다. 과거 frozen 보고는 수정하지 않는다.

private 결과의 `diagnostic`은 실제 UTC 발생시각·고정 boundary/reason·logical lock kind·allowlist
stage/hour slot·bounded 정수 errno/elapsed_ms와 아래 고정 detail을 담고 holder_pid는 미확인 null이다. config, Store,
storage readiness, 각 lock, state read/save, dependencies/snapshot/seal/stage, deadline/publication/
정산을 구분한다. bool·과대/비정수·외부 reason/예외 문자열/원문/credential/절대 경로는 배제한다.
가능하면 state 잠금 안에서 `loop/last-diagnostic.json` 마지막 한 건과 private 결과를 함께 남긴다
(`diagnostic_preservation=private_record_and_result`). 최초 잠금/설정/storage/state 읽기 실패나
진단 저장 실패는 `private_result_only`다. parent의 기존 private CLI JSON 캡처로 확인하고 설정
저장소 자체가 불가하면 persistent 진단 보존도 보장할 수 없음을 구분한다. 오류 기록 실패로 최초
실패/예약을 덮지 않고 fallback 저장소/재시도/잠금 밖 state 수정은 하지 않는다. 진단은 web-v1과
digest에 추가하지 않는다. 과거12시 충돌의 정확한 예외/holder는 새 진단으로 소급 확정하지 않는다.

기존 `.lock` inode와 artifact/sender inode를 지우지 않는다. stable discovery inode의 Store root
hash가 다른 storage로 빈 ledger를 재시작하는 것을 막는다. v1/v2/no-config/override 전환은 실행
중인 구버전 종료 확인과 기존 ledger/reservation/서명/게시의 명시 조정을 parent가 담당한다.
finished_at·stale PID만 보고 잠금을 제거하거나 새 저장소로 우회하지 않는다. 장애 복구는 기존
slot/claim/outbox를 먼저 확인하며 실패를 중복 호출/중복 POST 허가로 해석하지 않는다.

이번 승인40개/coordinator1개의 검토·검증 이력은 ADR0027, 전달 절차는 [workflow](workflow.md)를 따른다.
17시6/9단계·active sealed round는 제공된 관측이며 나머지 DAG/reviewer 완주와2026-10-23
09:00 보고·09:20 같은 채팅 알림 성공은 미관측이다. 매시00분·기존 at→codex queue job1,
runtime37개·owner/shared·model/provider/auth·9단계·slot/예산·승인 범위는 유지한다.

source Read·coverage·완료·제안 보존의 상세 계약은
[ADR0026](adr/0026-source-verified-retained-improvement-reports.md)을 따른다. parent Capture는
모든 계획 window의 실제 성공 structured Read·원본 bytes/줄 범위·ID pairing·순서별 assessment·
문서 Read·유일한 정상 final과 1회 소비를 검증한다. 빈 pool도 owner non-shared Python 본문을
테스트보다 우선하며 AGENTS/안내/설정으로 코드 점검을 인증하지 않는다. 본문96줄/문서12줄 표본은
전체 파일/저장소 완독이 아니다. 부재/빈/읽기·파싱 실패/header-only·32KiB/32window 초과는 미완료다.

정확한 BOM/LF/CR Read projection·totalLines/마지막 빈 줄과 별도의 원본 hash/mode/range 계약,
bounded rate_limit_event 무동작 예외는 ADR0026에 둔다. 안내·모델 주장은 Read/성공/비용/identity/
진단 권위가 아니며 receipt/public에 넣지 않는다. Capture와 final 응답/비용 탐색은 LF만 NDJSON
경계로 사용해 U+0085/U+2028/U+2029를 데이터로 보존한다. 빈 record·잘못된 pairing·result 뒤
도구·중복 final·unknown/malformed/과대 안내는 거절한다. 모든 documentation.files는 문서
목적 window만 고르고 창 밖 필요 경로는 reason에만 밝힌다. 상세 상태 규칙은 아래 후보·검토 절을 따른다.

proof는 private에 보존해 완료/오전 선택/approve/execute에서 재검증한다. 승인 context proof
거절은 `ImprovementError('Independent source Read evidence is required.')`로 정제하며
instruction 접근/권한 생성에 이르지 않는다. 별도 최종 prose 검증의 ValidationError는 유지한다.
실제 validator 경계의 고정 private review.* 진단만 쓰며 08시 원인 미확인·합성 명세·실제 관측은
[ADR0034 최신 관측](adr/0034-inspection-failure-recovery-and-health.md#2026-10-27-최신-main-관측)에 구분한다.

오전은 현재 의존성 일치 완료 회차의 ID별 최신 명시 verdict를 모은다. 뒤 빈/실패 회차는 앞
eligible을 지우지 않고 후속 rejected/needs_evidence는 대체한다. 원본 scan pointer로 승인하며
합성 morning은 새 검토/서명/claim을 만들지 않는다. 최신 참여 실패는 별도 표시한다. 검증된
정상0개만 `점검 완료 · 확인한 범위에서 제안 없음`이다. 과거 frozen/public·runtime37/owner/shared/
예산/slot은 유지하며 Sites는 parent 소유다. 아래32/21개 승인·미실행 인계는 당시 이력이다.
새 reviewer는 전체 diff의 Read 증빙·제안 보존·결과 구분·CLI metadata와 documentation을
독립 판단한다. 앞선 approved/5097통과·복원 초안은 새 성공 증거가 아니다. 미병합 종료 PR63의
대체 PR에는 위 동작·proof/승인 gate·provenance·metadata의 무동작/실제 result 권위와 새 검증을 적는다.

자동 점검은 정비사의 점검표처럼 개선 후보를 발견하고 서로 검토하여 한국어 비유를 담은
한 장 보고서를 제공한다. 실제 수리는 차주가 특정 항목을 승인한 뒤에 시작한다.
기반 기능 구현과 그 setup의 후속 검증 보정 및 GitHub 전달은 명시적으로 승인되었지만
이후 발견된 제안에는 각각 사용자의 구체적인 승인이 필요하다. 기존 직접 개발 요청의 권한과 구분한다.
권한은 [AGENTS.md](../AGENTS.md), 설계는 [전체 설계](harness-design.md)와
[ADR 0015](adr/0015-approval-gated-improvement-discovery.md)를 따른다. 최신 사용자의 직접 선택으로
daily-only/하루5회/one-pass를 [ADR 0017](adr/0017-budgeted-continuous-improvement.md)의 bounded
hourly 연구와 09:00 once 보고로 대체한다. 보고를 보고 고칠 항목을 승인하는 권한은 확대하지 않는다.

## 진행 보존 수리의 문서 영향과 실행기 인계

2026-10-21 결정·local/cloud/09시 관측은 [ADR0025](adr/0025-progress-preserving-improvement-reviews.md),
Read/제안 보존은 [ADR0026](adr/0026-source-verified-retained-improvement-reports.md)에 둔다.
당시 승인32/coordinator1·run1792547845263535412-a3f550의900초 종료/applied=[]와 frozen
2026-10-21 failed/0카드 전달은 과거 이력이다. parent의 baseline/checkpoint/초안 준비는 새
검토/검증/적용 증거가 아니며 worker는 private 원문을 읽거나 frozen 보고를 재작성하지 않았다.

cloud admission history192·완료 index32와 별도 private local history192를 분리한다.
최대4096 scan의 한 번 legacy 이행·exact pointer carry-in·scan_id 비용 중복 방지와 unknown의
보수적 소비를 유지한다. 과거 timestamp/local 원인을 복원하지 않는다. snapshot 두 bank의
manifest/fingerprint/no-follow/owner/mode/nlink·128KiB/1.5MiB·bounded staging/unsafe partial
no-call은 그대로다. source-only stage/pool/feedback/cursor 보존과 control 변경 무효화는 아래
freshness 절을 따른다. 유효한 seal도 live eligible/approve/execute 권한은 아니며 source
unavailable과 lock busy는 구분한다. local 실패/빈 초안은 정규 독립 점검을 생략하지 않는다.

당시 회귀 입력 정정(local-only 날 cloud 전원 not_called/failed, 초안 없는 specialist 뒤 local
진단 보존, parser codex→zai control 변경)과 snapshot/source/window/frozen/privacy 회귀는
parent full check 대상이다. 매 review는 최종 diff의 documentation={status,files,reason}을
새로 판단하고 새 Claude 검토→GIT=1 full make check→scoped apply→기존 Git 역할→parent의
GitHub/CI3/merge/cleanup을 거친다. 승인 밖 필요 문서는 정확 경로를 기존 승인 파일 finding에
귀속해 새 범위를 요청하며 leaf가 열거나 생성하지 않는다. 작성은 검사 통과가 아니다.

## 구현 책임과 읽기 범위

Python3.8 `improvement_report.py`는 I/O 없는 strict 계약/fingerprint/정제/renderer,
`improvements.py`는 기존 model/storage/workspace API의 발견/기록/승인/일회성 실행/HTTP,
`improvement_loop.py`는 tick/status/publish·ledger/9단계/오전 journal을 담당한다.
`local_model.py`는 숫자 loopback text mlx-vlm adapter이며 파일/상태/승인 권한이 없다.
workflow의 `_improvement_guard(run_id)`는 project lock 안에서 승인 provenance를 재검증한다.
completion은 parent의 run 완료 검증/별도 outbox 복구만 맡는다. 일반 직접 요청의 기존 권한과
cloud provider/model/effort/compaction/auth는 그대로며 Sites 구현/배포·로컬 설치/실추론은 parent 책임이다.
새 요금제/계정/인프라/credential 생성·유료 fallback은 없다.

[improvement-scope.txt](../harness/improvement-scope.txt)는 개별 저장소 상대 경로의 승인 목록이다.
glob/재귀/Git enumeration/모델 범위 확대는 없다. 향후 runtime 읽기 목록은 현재 worker의
승인 범위를 넓히지 않는다. discover --scope-file도 사용자 승인 개별 목록만 받으며 절대 host
경로는 private provenance에만 둔다. specialist는 `workflow.owner(path)`의 승인 파일과
shared_files 중 scope에도 있는 파일만 받고 reviewer는 별도 context에서 전체 승인 scope를 받는다.
예를 들어 parser_tidy/tests/test_import_safety.py의 owner는 django다. shared 후보는
AGENTS.md·docs/architecture.md·docs/harness-design.md·docs/improvements.md·docs/data-contracts.md다.
missing은 근거로 쓸 수 없다. 필요한 scope 밖 경로는 승인 파일 finding에 귀속해
needs_evidence/ineligible로 남기고 parent가 새 실행을 준비한다. repair는 권한을 넓히지 않는다.

legacy specialist는 앞선 정제 ID/title/issue/analogy/edit_files 요약을 받고 hourly specialist는
local 초안을 자기 승인 소스로 검증/거부/보완한다. 다음 round에 정제 issue·담당 설명·독립
review.reason을 전달하되 다른 owner 소스는 자동 추가하지 않는다. 의견은 근거나 합의를 대신하지 않는다.
source snapshot은 symlink/비정규/보호/private 경로를 거절하고 UTF-8/bytes를 검증한다.
모델 사본은0400, runner는 write=False/scoped=True이며 원본/전체 검증 사본·키·host 로그·운영
데이터/private config는 context에 넣지 않는다. 인증은 trusted runner의 분리 runtime 책임이다.
허용 쓰기는 자체 private 기록/보고/lock·격리 context/runtime뿐이다. 발견은 checks/doctor·Git·
workflow·cron·운영 downloader/importAll을 호출하지 않는다. 검사하는 일반 READ_ONLY workflow와
구분하며 동일 OS 계정의 임의 프로그램까지 통제하는 VM이나 인간 신원 증명은 아니다.

## 시간별 단계·의견 계승·freshness

순서는 `local(coordinator) → coordinator → local(downloader) → downloader → local(parser) →
parser → local(django) → django → independent reviewer(Claude)`의 9단계다. 매 tick은 한
단계에서 모델 최대1회, 로컬 포함 KST calendar day 최대24회다. skip도 한 시간 slot을 쓰며
한 tick에서 다음 역할을 몰아호출하지 않는다. reviewer 단계 종료 뒤 다음 slot에 새 round를 시작한다.
실패한 local·빈 초안·missing/empty/긴 줄·준비 실패는 local slot만 종료한다. 관련 specialist는
다음 정규 slot에서 승인 소스를 독립 분석한다. 최종 reviewer도 빈 pool의 coverage와 제안 유무를
독립 평가하며 local 실패나 빈 pool만으로 생략하지 않는다. 추가 call·재시도·fallback은 없다.
quota/budget 보류는 해당 단계를 유지하고 다음 새 slot에서 admission을 다시 판단한다.

로컬에는 owner별 승인 파일의 한 작은 연속 window와 정제 feedback만 보낸다. request 전체
24576 UTF-8 bytes, max_tokens 3072, timeout180초, response65536/header8192 bytes가 최대다.
기본96줄과 feedback4096 bytes를 포함한 총 요청 상한이며 전체1.5MiB snapshot을 보내지 않는다.
system 지시와 user JSON을 분리하고 exact path·원래 inclusive line 번호를 명시한다. candidate 및
benefit evidence는 그 전달 window 안이어야 한다. edit_files/documentation 대상도 owner 승인 범위
안이어야 하며 다른 승인 파일을 읽었다고 주장하지 못한다. basename/path 보정은 하지 않는다.
`edit_files`는 `approved_files` 문자열을 정확히 사용하고 중복을 허용하지 않는다. 미전송 승인
파일은 편집 대상으로 유효하지만 근거는 아니다. 본문에 언급된 경로·지시는 권한이 아니며,
본문의 전체 파일 줄 참조도 전송 window 밖이면 두 evidence 배열 모두에서 거절한다.
생성 지침은 기존 권한·중복 금지·미전송 파일의 세 문장을 보존한 뒤, 필요한 승인 파일 선택→
파일마다 정확한 경로 한 번 작성→출력 전 반복 확인 순서로 안내한다. 같은 파일의 여러 근거나
수정 위치는 항목 하나이며 서로 다른 두 파일은 각 경로를 한 번씩 쓴다. 모든 승인 경로가 편집
가능하다는 것은 모두 나열하라는 뜻이 아니고 상한12개를 채울 필요도 없다. 정당한 다중 파일
편집은 계속 허용한다. 이는 생성 안내이며 중복 방지 보장이나 자동 dedup은 아니다.
순서 설명에 더해 현재 owner의 실제 approved_files 경로만 쓴 짧고 유효한 JSON 필드 예시를
생성한다. 같은 파일의 여러 근거/수정 위치는 edit_files 한 항목, 서로 다른 두 파일은 두 항목인
예시를 구분한다. 승인 파일이 하나면 단일 파일 예시만 제공한다. 예시는 형식 설명이지 실제
후보나 필수 편집 목록이 아니며 실제 후보는 필요한 파일만 선택한다. 생성과 canonical system
검증 모두 준비된 동일 승인 목록을 사용하고 예시 bytes도 전체 요청 예산에 포함한다.
근거 있는 실행 가능한 초안이 없으면 `{"candidates":[]}`로 반환하도록 명시한다.
mlx-vlm0.7.8의 실제 POST는 `response_format={"type":"json_schema","json_schema":{"name":...,"strict":true,"schema":...}}`와
**top-level enable_thinking=false**를 사용한다. llguidance가 정확한 `{candidates:[...]}`와 기존
후보 전체 필드·타입·필수 항목·객체별 additionalProperties=false·최대2후보를 강제한다.
edit_files enum은 현재 owner 승인 목록이고 후보 및 benefit evidence의 path/정수 줄 범위는
실제 전달한 단일 window다. 배열/텍스트 상한도 지원 범위에서 포함한다. uniqueItems는 서버
미지원이므로 제외하고 중복·start<=end·총 문자량·공백/의미와 실제 window의 최종 판단은 기존
client validator·담당자/독립 검토에 둔다. schema가 의미 오류를 모두 막는다고 주장하지 않는다.
전송 전 준비 입력의 immutable digest 결합과 window/승인 목록에서 재구성한 canonical schema를
검사한다. schema 누락·완화·owner/scope/window/thinking 변조는 실제/주입 transport 전에 거절한다.
window 선택부터 schema 포함 전체 직렬화 request24576bytes를 계산하며 whole-line/원문 번호를
유지한다. 고정 overhead만으로 넘으면 context_too_large no-call이다. 서버가 schema를 무시하거나
위반한 후보도 그대로 거절한다. prompt는 schema와 일치하는 짧은 지침으로 단순화한다.
정상 assistant의 tool_calls:null/tool_call_id:null만 무동작 metadata로 받고 그 non-null과 다른
도구 필드는 거절한다. raw envelope를 고치지 않으며 text-only/no-tools 경계를 유지한다.

local 설정은 local-model-config-v2/provider=mlx-vlm, api_model==model인 검증된 상대 repository
ID다. default_model 별칭·절대 호스트 모델 경로를 요청하지 않는다. v1 mlx-lm은 config_invalid로
보류하고 자동 변환·대체하지 않는다. version/provider/API identity가 config digest와 loop
fingerprint/서명 승인에 반영돼 옛 승인을 재사용하지 못한다. Linux는 Python3.8 표준라이브러리만
쓰며 설치·기존 모델의 상대 ID 연결·서비스/private config 전환·실추론은 메인 책임이다.
검토 제안·검증 계획·문서 영향은 향후 작업이고 예상 효과에 사전 실행·측정을 요구하지
않는다. 측정 근거 없이 measured나 실행 성공을 주장할 수 없다. user JSON은
`owner_role,sources,feedback,candidate_limit,approved_files` 순서로 소스·의견 뒤에 전체 승인
목록을 둔다. 값·원본 줄·scope와 순서 변경 bytes 수는 유지하고 전체 요청 ceiling·구조 검증을
계속 적용한다. 전역 canonical_json·서명·보고 직렬화는 변경하지 않는다.
owner별 `{file_index,line}` cursor를 호출 전에 다음 위치로 durable 저장해 큰 파일을 여러 round에
나누고 HTTP 실패·중단 후에도 같은 window를 자동 replay하지 않는다. 긴 한 줄은 명시
`line_too_long` skip이며 slice/line 번호 변경이 없다. SSH/home/key/repo 복사·도구·remote_code는 없다.

local 출력은 초안이다. private scan의 bounded `local_participation`에 provider=mlx-vlm,
설정된 model identity·stage=local_explorer·owner_role·called/status/reason/read_windows/
skipped_lines를 남긴다. called는 시도이며 서버 수신이나 성공을 증명하지 않는다. 기존 web-v1
agents에는 실제 기존 5역할만 넣고 로컬을 cloud specialist 성공으로 위장하지 않는다.

`candidate_invalid`는 JSON 파싱 뒤 공유 후보 validator의 **검증 거절**이며 검증에서 제외됐다는
뜻이 아니다. 편집 목록 실패 지점은 private 고정 코드 `candidate_edit_files_invalid`(형식·개수·
문자열 합 상한), `candidate_edit_files_duplicate`, `candidate_edit_files_outside_scope`로
구분한다. 다른 미분류 후보 오류는 `candidate_invalid`다. 공유 후보 검증을 통과한 뒤 실제
전송 근거 window를 벗어나면 `evidence_outside_window`다. 기존 검증 순서상 먼저 도달한
실패만 분류하므로 정확한 값이나 모든 오류의 목록을 복원할 수 없다. loop는 allowlist 코드만
private 기록·의견으로 전달하며 원문 prompt/response·임의 예외문·모델 오류 값은 남기지 않는다.
실패한 초안의 진단과 web-v1 schema는 보존하며 specialist는 독립 점검한다. 경로/근거 보정·재시도·
fallback으로 성공을 만들지 않는다. 자세한 분류와 한계는 [로컬 진단](local-models.md#후보-거절-진단과-한계)을 따른다.

메인 제공 최초 초안은 JSON 파싱 뒤 candidate_invalid였으며 원문이 없어 당시 필드·값을
단정할 수 없다. 동일 입력 재현의 edit_files 범위 위반과 evidence 줄 범위 위반은 각각의 관측이며
최초 응답의 확정 원인이 아니다. prompt/order 수리 두 실행은 Claude 검토 뒤 실제 추론에서
다시 승인 밖 edit_files를 냈고 full check 중 중단/applied=[]다. 보존 초안은 새 검토/전체 검증이
필요하며 실패한 숫자 파일 ID/window evidence 합성은 구현하지 않는다.
메인의 native schema compiler/null metadata와 실제입력·합성입력 관측은
[로컬 문서](local-models.md#메인이-제공한-서버-호환-관측과-남은-검증)에 둔다. 특정 미검토 초안의
사전 실추론도 최종 bytes/full check/실제 repository9단계 성공이 아니다.
기존 hourly wrapper 활성·2026-10-16 09:00 partial/제안0개 보고1회 전달은 메인 제공 상태이며
확정 보고를 재생성하지 않는다. 새 프로토콜의 배포·최종 추론·전체 검증·첫9단계·다음 아침 게시
성공은 후속 관측 전까지 주장하지 않는다. 새 Claude 검토→전체 make check→scoped apply→
메인의 기존 Git 역할/GitHub 게시·CI·머지·정리 절차를 유지한다.

specialist가 정제한 candidate의 issue/edit_files와 설명·독립 `review.reason`을 다음 round의
실제 local prompt에 넣는다. candidate_id/draft_digest는 같은 초안 batch의 의견을 연결한다.
실패도 고정 reason으로 돌아간다. feedback은 allowlist/redaction/bytes로 제한하고 필요 시
표시된 축약을 사용한다. 하나도 담을 수 없으면 `feedback_cannot_fit`으로 보류한다. 전체 private
후보/검토는 잘라 저장하지 않는다. 무제한 prompt·response cache는 없다.

매 tick은 source 전체의 bytes/mode/존재와 scope/config/ownership/provider/model/protocol을
비교한다. source-only 변화에도 회차의 sealed snapshot과 stage/pool/feedback/cursor는
유지한다. review_complete는 그 고정 입력의 검토 완료다. 현재 freshness는 별도 비교하며
불일치 후보의 public eligible·approve·execute를 차단한다. control 변경은 진행을 무효화하고
새 snapshot을 시작하되 실제 참여와 완료 index를 보존한다. invalidated 사본과 이전 scan을
보존하며 기존 승인·claim은 재작성하지 않는다. 호출 후 loop/local 설정도 다시 읽어 비교한다.
loop_dependencies digest는 proposal의 discovery_fingerprint와 서명 승인에도
묶는다. 동일 candidate가 새 설정 아래 재발견되어도 old approval을 재결합할 수 없다.

## 한도와 실제 참여

[improvement-config.json](../harness/improvement-config.json)의 정확한 버전은
`improvement-config-v1`, timezone은 `Asia/Seoul`이다. 알 수 없는 key/version과 상한 초과를 거부한다.

| 설정 | 현재 값 / hard ceiling |
| --- | --- |
| 한 장의 제안 / specialist당 후보 | 3 / 2, 전체 후보 최대 8 |
| legacy 단일 scan 역할 호출 / timeout / 자동 retry | 5 / 600초 / 0; hourly 연구는 아래 별도 config |
| scope 파일 수 / 파일 bytes / 전체 소스 bytes | 64 / 131072 / 1572864 (1.5MiB) |
| context bytes / 모델 원래 응답 bytes (공백·wrapper 포함) | 2097152 (2MiB) / 65536 |
| 제안의 근거 수 / 편집 파일 수 / 검증 단계 수 | 6 / 12 / 6 |
| 승인 만료 | 기본 7일, hard ceiling 7일 |
| HTTP 요청별 timeout | 현재 20초, hard ceiling 30초 |
| HTTP request/response·web JSON bytes | 최대 262144 |

context 한도는 해당 UTF-8 source bytes와 prompt bytes 합이다. snapshot·fingerprint 생성과
저장된 source fingerprint 재검증은 같은 source 상한을 사용한다. 기본 37개 scope의 실제
소스와 8개 후보 reviewer context는 전체 로컬 검증 사본에서 오프라인 회귀 대상으로 삼는다.
이 회귀는 모델에 실제 소스를 전송하지 않고 순수 Python 대역으로 context 크기를 검증하며,
운영 저장소·키·모델·네트워크·workflow·subprocess 호출은 차단하고 임시 합성 storage만 사용한다.
합성 입력으로 source/context 경계 수용과 1 byte 초과 거부도 검사한다.
source/edit 파일 목록은 개별 경로이며 한 카드의 edit_files 경로 문자열 합도 600자로 제한한다.
private 단일 기록은 1MiB 이하,
scope 입력 파일은 64KiB 이하, instruction 파일은 16KiB 이하, inbox config는 8KiB 이하이다.
한도 안이라도 기존 workflow task 크기 등 후속 기존 정책을 통과해야 실행할 수 있다.
role scope가 없거나 준비 실패하면 호출하지 못한 이유가 남으며 무제한 재시도하지 않는다.

`harness/improvement-loop-config.json`의 `improvement-loop-config-v1`은 정확한 필드/타입과
finite/bounds를 검증한다. 기본 slot60분·report_hour9·하루 US$1·reviewer cap0.20·하루24회·
tick600초·cloud480초·자정 guard600초·specialist2/전체8후보·quota15초/65536bytes/80%·
완료 pool 보관16 round다. cloud timeout+80<=tick, guard>=tick 등 관계도 검사하며 알 수 없는
필드·bool 숫자·NaN/Inf·정책 상한 증가는 거부한다. model runtime은 tick보다 짧다.

이는 호출 수·시간·입력량 제한이며 전체 달러 비용 보장이나 성능 개선 측정이 아니다.
private 참여 기록은 실제 configured/returned role/provider/model과 실제 result, 시각·경과시간,
제공된 `cli_estimated_cost_usd`만 보존한다. 비용 미제공은 unknown이며 추정을 실청구액으로
바꾸지 않는다. 큰 raw result는 제한 metadata와 truncation 표시로 남는다.
실패·unavailable·not_called를 성공 합의로 표시하지 않는다. loop의 bounded participation은 raw
CLI result를 복사하지 않는다. 기존 provider별 기본 예산·compaction은 유지하며 reviewer만
아래 downward override를 사용한다. local not_metered도 실제0USD 청구의 뜻이 아니다.

## 2026-10-20 parser 편집 목록 중복과 수리 인계

[당시 인계 원문](adr/0034-inspection-failure-recovery-and-health.md#보존-인계-parser)에 실패·관측·검증 대기와
기존 요구를 그대로 보존한다. 현재 작업의 성공이나 권한으로 재해석하지 않는다.

## Hourly private 실패 진단과 인계

[ADR0027](adr/0027-inspection-lock-isolation-and-diagnostics.md)의 identity-bound private 진단을
유지한다. `detail`→`attach`/`inherit`→`exception_detail`과 adapter의 `attach_result`/`result_detail`은
실제 trusted 발생 경계만 연결한다. configured identity 확인 뒤 읽고, runner JSON/예외문/이름/
attributes·allowlist reason 자체는 provenance가 아니다. `sanitize_detail`은 저장/feedback
재검증이며 권한을 만들지 않는다. API/CLI/telemetry 성공도 후보/검토 성공이 아니다.

`improvement-failure-v1`의 9키·512bytes·exact dict/str/int·고정 코드와 실제 관측한 숫자만 허용한다.
exit0..255/errno0..4095/HTTP100..599 외 숫자나 bool은 null이며 validation field/rule이 부족하면
unavailable다. 동적 field/path·값·구문 위치·원문/소스/prompt·키·절대 호스트 경로·provider
자유문자열은 넣지 않는다. broad reason은 기존 준비/실행/응답/JSON/identity/context/cleanup/
중단/후보/Read/review를 구별하고 공통 후보 field/rule과 edit_files 세 reason을 유지한다.
명확한 nonzero CLI stderr 인증 증거만 분류하며 stdout/tool/소스/경고·모호한 provenance는
cli_failed/unavailable다. legacy나 원문 없는 과거 원인을 새 진단으로 확정하지 않는다.

Read 진단의 고정 review.* field/rule과 최종 계약 경계는
[ADR0026](adr/0026-source-verified-retained-improvement-reports.md)을 따른다. 최종 validator는
review_invalid/validation/review를 발급하고 review.documentation의 empty는 빈 required/missing,
fields는 상태/문서/eligible 모순이다. 구조/ID/verdict/reason은 review.result다. 묶인 fields 거절은
특정 값이나 근본 원인을 확정하지 않는다. allowlist·health/public은 확대하지 않는다.
PR83 이후 두 실패/두 번째 missing·빈 files 확정·첫 번째/08시 원인 미확인과 새 성공 미관측은
[ADR0034](adr/0034-inspection-failure-recovery-and-health.md#2026-10-27-최신-main-관측)에 구분한다.

`_safe_participation`은 reason(내장str/64자 allowlist)·error_type(내장str/32자 고정목록)·detail만
재정제하고 raw result를 복사하지 않는다. 미인식 reason/type은 role_failed/Exception이며
legacy 상세는 unknown/unavailable다. 성공의 허위 failure metadata는 버린다. local도 identity 뒤
표식과 shared/window validator가 권위며 두 evidence의 window 위반은 evidence_outside_window다.

scan/slot/history는 scan_id/slot/stage_index0..8/stage/owner_role에 결합한다. cloud192/local192는
별도이고 (scan_id,slot,stage_index)로 중복 제거한다. 실제 call 시각은 rollback에도 보존해
admission 집계/보수적 회계 시각과 구분한다. 과거 timestamp/local은 추정 이행하지 않는다.
status는 detached 재정제 투영이다. 정산 crash 뒤 저장된 최초 detail·draft digest·실제 시각은
복구/feedback에도 보존하고 후속 성공/cleanup/정산 오류가 덮지 못한다. 실행 결과 없는 예약은
interrupted_unknown/unavailable이며 재호출/환불 허가가 아니다. 초기 storage/lock/config 실패는
private 결과만 남을 수 있고 fallback/잠금 밖 쓰기/retry는 없다. no-call 보류는 실행 실패가 아니다.
feedback은 candidate_id/draft_digest·redaction/bytes·최대4개 요약을 유지해 다음 local prompt에
상세를 전달하며 원본 scan은 남는다. public payload/digest/journal·오전 선택은 바꾸지 않는다.
Lab의 adapter→_call_role→tick→Store 재개/status/feedback·비용/최초실패·위조/원문 배제·후속 성공
보존은 작성된 명세다. worker는 실행하지 않으며 parent의 새 전체 diff 의미/documentation 검토·
full check·실제37개 측정·scoped apply·기존 Git/게시·운영 관측을 기다린다.

## Claude 추정 ledger·GLM 구독 quota

Claude 자동 탐색은 UTC+9 자정 기준 하루 US$1 추정 ledger를 쓴다. discovery→artifact lock 아래
호출 전에 slot·role count·예약액·inflight와 local cursor를 atomic private state로 저장하고
fsync한다. 예약 저장 실패면 모델을 실행하지 않는다. cap은 `min(0.20, 잔액, 기존 reviewer 한도)`로
양수일 때만 `agent_models.run/command_for(max_budget_usd=...)`에 넘겨 실제 CLI
`--max-budget-usd`에 연결한다. optional override는 Claude 전용·finite 양수·downward-only이며
bool/NaN/Inf/0/음수/상한증가/다른 provider를 거부한다. 일반 workflow 기본 예산은 바꾸지 않는다.
**이번 기능 구현 workflow의 모델 비용은 자동 탐색 하루1달러 ledger와 별도다.**

성공과 finite/nonnegative CLI estimate가 함께 있을 때만 실제 추정으로 정산한다. 실패·timeout·
중단·비용 미상은 예약액 전부를 소비 처리하며 재시작 환급/재호출하지 않는다. estimate가 예약을
넘으면 실제 추정액을 숨기지 않고 추가 기록한 뒤 당일 전체 연구를 중단한다. 일반적인 잔액 소진은
reviewer admission에서 판단한다. 그 차례에 도달하기 전 local/구독 역할은 다른 gate와 call cap을
만족하면 진행할 수 있지만, reviewer가 예산으로 보류되면 `stage_index`는 그대로다. 이후 새 slot도
같은 reviewer admission만 다시 판단하므로 대기가 풀릴 때까지 다음 round의 local/구독 역할도
호출하지 않는다. 단계 건너뛰기는 없으며 09:00 보고 확정은 이 대기와 독립적이다.
unknown은0USD가 아니며 CLI estimate/cap은
실청구 강제상한을 보장하지 않는다. 비용/잔액은 private status에만 남고 모델/웹에 보내지 않는다.

기본23:50부터 마지막600초는 모든 provider admission을 거부한다. guard는 전체 tick deadline
이상이다. durable high-water로 clock rollback·과거 날짜/slot replay를 막는다. 중단 호출이 다음 날
복구되거나 실행 중 clock jump로 날짜를 넘으면 원래 예약/호출 수를 유지하고 다음 날도 보수적으로
count/charge하여 양일 중단한다. interrupted stage는 실패로 한 번 진행하며 모델 재호출하지 않는다.
최근7일 ledger는 state에, 이전 날짜는 `loop/ledgers/<date>.json`에 보관한다.

첫 활성화는 같은 날짜 legacy days/scans를 scan_id로 중복 제거해 기존 role calls와 성공 Claude
estimate를 한 번 carry-in한다. 메인 관측0.0434664USD도 실제 최신 기록에서 읽으며 상수가 아니다.
추가 legacy activity도 중복 없이 반영하고 loop scan/projection은 제외한다. 불완전 과거 기록은
숨은 호출 가능성 때문에 당일 call allowance 소진 처리하며 Claude 미상 비용은 하루 dollar
allowance를 소비 처리한다. 기존 보고는 보존한다. old state/claim 삭제로 재실행하지 않는다.

GLM은 기존 Z.ai Coding Lite Claude Code `https://api.z.ai/api/anthropic` 연결 그대로다.
trusted parent만 매 GLM admission 전에 기존 ZAI_API_KEY를 런타임 header로 사용해
`GET https://api.z.ai/api/monitor/usage/quota/limit`를 조회한다. 고정 host/path, timeout기본15초/
최대20초, bounded header/body64KiB, redirect/proxy/retry 금지다. key·raw body·원문 예외를
로그/모델/웹에 노출하지 않으며 정제 quota 상태와 고정 reason만 private slot에 남긴다.

legacy TOKENS_LIMIT 및 새 CREDIT_LIMIT의 5h(unit3/number5) finite percentage0..100과
미래 정수 epoch-ms reset을 검증한다. reset은 현재보다 뒤·8일 이내여야 한다. 두 model type 모두
인식된 5h window에서 정확한 finite numeric 0%(bool 제외)일 때만 absent/null reset을 idle로
허용한다. 정제 private 결과의 `nextResetTime`은 `null`(미상·미활성)로 유지하며 reset 시각을
만들거나 갱신하지 않는다. 비영 사용량의 reset 누락과 존재하는 잘못된 reset은 계속 거부한다.
weekly(unit6/number1)가 있으면 0%라도 유효한 미래 reset을 요구하며 weekly/CREDIT_LIMIT
존재는 가정하지 않는다. envelope의 success가 있으면 정확히 true, code가 있으면 정수200이어야
한다. HTTP/응답 실패·model limit 부재·TIME_LIMIT만 있는 응답을 idle 0%로 해석하지 않는다.
unknown/중복/미지원 window·malformed·조회 실패면 GLM 보류다.
하나라도 percentage>=80이면 pause해 명목20% 개발 여유를 남기며 호출 중 소비까지 절대
보장하지는 않는다. 과거1% 관측을 다음 호출에 재사용하지 않는다. credit 가격 하드코딩·한도 구매·
reset 소비·balance 자동차감/다른 공급자 fallback은 없다. 공식 근거는
[usage script](https://github.com/zai-org/zai-coding-plugins/blob/main/plugins/glm-plan-usage/skills/usage-query-skill/scripts/query-usage.mjs),
[FAQ](https://docs.z.ai/devpack/faq), [구독 quota 보존](https://docs.z.ai/devpack/notice/usage-revision)이며
메인의 읽기 전용 확인 요약을 사용했다. 이 worker는 네트워크 조회하지 않았다.
budget/quota는 자동 탐색 admission에만 적용하고 승인 실행 권한·execute에는 적용하지 않는다.

## 후보·검토·날짜 기록

specialist 응답은 추가 key 없이 `{"candidates":[...]}`다. candidate는 정확히
`title, priority, analogy, issue, evidence, benefit, risk, edit_files, validation_plan, documentation_impact`를 갖는다.
후보 서술의 PRIVATE 수용 상한과 PUBLIC 표시 상한을 분리한다.
[ADR 0016](adr/0016-bounded-private-improvement-text.md)의 결정에 따라 모든 후보 서술은
표시 상한의 정확히 4배까지 수용한다. 단위는 문자열 문자 수이며 응답 전체 64KiB UTF-8
bytes 상한과 독립적이다. specialist는 간결한 한국어로 표시 상한을 목표로 작성한다.

| 후보 서술 | PUBLIC 표시 상한 / 목표 | PRIVATE hard ceiling |
| --- | --- | --- |
| title / analogy (각 한국어 포함) | 80 / 200 | 320 / 800 |
| issue | 400 | 1600 |
| evidence.summary 및 benefit.evidence.summary | 각 240 | 각 960 |
| benefit.text / risk | 각 240 | 각 960 |
| validation_plan의 각 단계 | 200 | 800 |
| documentation_impact | 360 | 1440 |

evidence는 1~6개 `{path,start_line,end_line,summary}`이며 승인된 실제 파일의 1부터
시작하는 inclusive line range여야 한다. validation_plan은 1~6개이다.
benefit은 `{kind,text,evidence}`이고 kind는 `estimated|measured`다.
measured는 적어도 한 실제 근거를 요구하지만 schema는 측정의 의미적 타당성을 증명하지 않는다.
실측이 없으면 '예상·미측정'으로 설명하고 속도·비용 수치를 만들지 않는다.

수용된 본문은 기존 바깥 공백 정규화 이후 축약 없이 독립 reviewer 입력·canonical proposal
ID/digest·private persistence·재검증·후속 승인/실행 task까지 유지한다. reviewer에는 기존
credential/경로 redaction을 적용하되 표시 길이 제한이나 공백 합치기를 적용하지 않는다.
redaction 치환으로 길이가 늘어도 뒤의 안전한 설명을 자르지 않으며 context 상한은 그대로다.
기존 짧은 후보의 canonical 표현과 ID는 바뀌지 않고 공개 prefix 뒤 문자가 바뀌면 원본 ID/digest가
바뀐다. reviewer의 `review.reason`과 후보별·전체 `documentation.reason`도 PRIVATE
1440자 / PUBLIC 360자로 분리한다. 수용된 review 원문은 private scan/proposal에 보존하고
후보별 독립 review 전체의 기존 `review_digest` 승인 결합·재검증·승인 후 task에 사용한다.
전체 documentation 판단도 private scan에 원문 그대로 보존하고 eligibility 때 재검증한다.
짧은 review의 표현·digest는 그대로다. reviewer prompt는 세 reason 모두 간결한 한국어
360자 이하를 목표로 요청하고 private hard maximum 1440자를 명시한다.
private ceiling 초과·빈 문자열·잘못된 타입/UTF-8/제어문자·unknown key·scope/line 오류는
전체 해당 specialist 출력을 거부한다. 구조가 잘못된 후보를 잘라 살리지 않으며 기존 partial
처리를 유지한다. 나머지 source/context·배열·enum·경로·권한 상한은 그대로다.

discovery reviewer의 원래 응답은 정확히 `reviews,documentation,assessments`다. 실제 Read와
순서별 assessments를 검증한 뒤 최종 `validate_review`에 전달·보존하는 본문은
`reviews,documentation` 두 필드다. reviews는 각 후보를 한 번씩
`{candidate_id,verdict,reason,documentation}`으로 판단하고 verdict는
`eligible|rejected|needs_evidence`, reason은 비어 있지 않은 private 1440자 이하이다.
각 후보와 전체의 documentation은 `{status,files,reason}`이며 status는
`required|missing|not_required`다. reason은 구체적인 private 12~1440자 설명이어야 한다.
세 reason 모두 공개 projection에서만 redaction·표시 공백 합치기·360자 이내 `…` 생략을
적용한다. private 입력은 수용 전에 자르지 않는다. `validate_web_report`와 HTML/Markdown
소비자는 올바르게 재계산한 digest가 있어도 세 위치의 public 361자 reason을 거부한다.
특히 top-level documentation도 private validator의 확대된 상한을 사용하지 않는다.
required/missing은 승인된 Markdown 경로가 필요하고 not_required는 빈 files를 요구한다.
required/missing의 files는 반드시 비어 있지 않아야 하며 missing/빈 files는 계속 거절한다.
두 수준의 files 모두 실제 documentation Read window 경로만 담는다. 승인 밖 필요 문서는
reason에 누락 경로를 밝히고 files에는 경계 보완이 필요한 관련 승인 문서를 지목한다.
진실하게 지목할 수 없다면 scope 부족을 드러내 미완료로 남기며 경로를 합성하지 않는다.
읽기 전용 자문에서도 제안 구현의 문서 필요성을 평가한다. 필요한 변경이 없는 구체적인
analysis-only not_required는 허용되지만 문서를 실제 수정하지 않았다는 사실만으로는 부족하다.
구현에 필요한 문서는 eligible 제안의 edit_files에 있어야 하며 missing과 eligible은 양립하지 않는다.
전체 missing도 모든 eligible을 금지한다. 근거/범위 부족은 needs_evidence/rejected와 문서 판단에
일관되게 남기며 문서 필요성을 숨겨 통과시키지 않는다.
승인 밖 필요 문서는 열람하지 않고 explanation에 누락 경로를 보고한다.
이 자문 계약의 required는 '문서를 이미 수정했다'는 뜻이 아니다. 이후 실제 구현 reviewer는
기존 `documentation.updated`와 실제 changed Markdown으로 의미적 완전성을 판단한다.

prompt는 specialist/reviewer 모두 bare strict JSON을 요청한다. `_call_role`의 모델 응답
transport 경계에서만 bare JSON 또는 응답 전체를 차지하는 단 하나의 소문자 `json` 태그
3-backtick fence를 허용한다. 여는 태그 직후와 닫는 fence 직전은 각각 LF 또는 CRLF여야 한다.
바깥에는 JSON 공백(space/tab/CR/LF)만 허용한다. 공백·wrapper를 제거하기 **전에** 원래 응답의
strict UTF-8 및 설정된 전체 byte 상한(최대 65536)을 검사한다. 인식한 wrapper의 내부만
기존 `parse_json`으로 검사하며 duplicate key·NaN/Infinity·숫자 overflow·잘린 JSON을 거부한다.
untagged/다른 언어 fence·설명문·여러 block·후행 내용은 추출·복구·retry 없이 기존 partial
경계로 실패한다. 유효 JSON 문자열 안의 backtick은 데이터다. envelope는 private runner
result를 변경하지 않으며 같은 JSON의 후보/검토 내용·canonical proposal ID/digest는 같다.
config/storage/public 입력의 parser와 공용 `parse_json`은 fence를 계속 거부한다. schema·공개/비공개 문자
상한·review redaction·source/context·cardinality·비용·자동 retry 0회는 그대로다.
line range/경로 검사는 구조적 검사이며 의미 판단은 실제 reviewer에게 남긴다.
실패·누락·malformed review는 실행 적격 제안을 만들지 않으며 보고는 partial/failed로 남는다.
일부 specialist 실패에도 독립 전체 review가 유효한 나머지 후보는 partial 보고의 적격 후보가
될 수 있다. 적격 판정은 사용자 승인과 별개다.

ID는 `IMP-`와 proposal digest의 앞 16개 hex이다. 전체 digest는
`{version:"improvement-proposal-v1",candidate,source_fingerprints}` canonical JSON의 SHA256이다.
전체 승인 읽기 의존성마다 `exists,mode,sha256,size`를 저장하며 missing은
`{exists:false,mode:null,sha256:null,size:0}`이다. 편집 파일뿐 아니라 공유 문서와 읽기 참조의
bytes/mode/존재도 ID와 freshness에 영향을 준다. scope 원문 bytes/mode/paths 및 config digest도 별도 기록한다.
동일 후보·동일 의존성은 같은 ID를 재사용하고 human 결정/승인/claim을 덮어쓰지 않는다.
다시 검토하여 review가 바뀌면 기존 승인 review digest가 일치하지 않아 새 승인이 필요하다.

정책 선택 improvements directory에 `scans/<scan_id>.json`, `days/<KST-date>.json`,
`latest.json`, `proposals/<ID>.json`, `web/<date>.json|html|md`를 기록한다.
사람 상태는 `decisions`, 서명 승인은 `approvals`, 일회성 실행은 `claims`/`executions`,
전달 상태는 `delivery`, 재승인 이력은 `history`로 분리한다. directory 0700·파일 0600,
원자 replace/fsync를 사용하며 local 기본 산출물은 `logs/harness/improvements`다.
storage 정책의 readiness 검사를 우회하거나 persistent 설정을 자동 변경하지 않는다.

legacy `daily`는 KST 날짜의 기존 day record가 있으면 내용 변경 여부와 무관하게 같은 보고를 반환하고
새 모델 호출을 0회 수행한다. failed/partial도 자동 재분석하지 않는다. 분석 전 failed day를
먼저 남겨 중단을 건강한 '제안 없음'으로 오인하지 않는다. 이후 수동 `discover`는 같은 날을
명시 재점검하며 이전 scan 기록과 human 상태는 보존한다. 정상 `scanned`의 0개와
미완료 `partial|failed`의 0개는 구분한다. lock/readiness/config 실패가 초기 기록 이전에 나면
day record 자체가 없을 수 있으므로 CLI 실패 로그와 함께 확인한다.

loop state가 생긴 뒤 legacy daily는 기존 day만 반환하며 day가 없으면 새 분석을 거부한다.
delivery도 loop_managed로 넘겨 새 publication journal을 우회하지 않는다. manual discover는
기존 trusted 수동 API로 남지만 자동 ledger 경로가 아니므로 스케줄하지 않는다. frozen day나
prepared publication이 있으면 수동 scan도 그 day/web을 바꾸지 못한다. 같은 storage를 고정하고
daily/discover를 hourly와 병행 예약하지 않는다. 기존 호환 테스트 의미는 이 경계 안에서 유지한다.

## 불변 오전 보고와 후보 선택

window는 `[이전09:00, 현재09:00)` KST다. 09:00 이후 첫 tick은 모델 admission보다 먼저,
현재 전체 의존성이 일치하고 실제 source Read가 검증된 완료 회차를 bounded index에서 모은다.
완료시각·scan_id 오름차순으로 ID별 최신 명시 verdict를 적용한다. 09:00 정각 완료는 다음 window에
포함된다. 오래된 성공을 오늘 참여로 만들지 않는다. 최대8개 distinct ID를 priority high/medium/low, 그 다음
exact ID 오름차순으로 정렬해 최대3카드만 projection한다. eligible 우선정렬은 없으므로 rejected나
needs_evidence도 카드에 포함될 수 있다. counts.eligible은 표시 밖을 포함한 전체 적격 수다.

각 카드의 원래 scan/검토/전체 scope/protocol은 private retained_provenance에 결합한다.
최신 완료 회차의 원본 참여와 카드별 원본 scan을 분리한다. 공개 agents는 durable history에서 window 안 역할별 마지막
실제 시도를 집계하며 window 밖 역할만 있으면 not_called로 남긴다. 전원 성공 조건을 못 채우면
partial이다. 유효 review 부재·미완료·budget/quota/모델 실패에는 그 window의 실제 참여만 담은
0카드 partial/failed로 확정한다. config/source 유효성을 확인할 수 없어도 storage와 lock이
가능하면 0카드 실패/부분 보고를 만든다. storage/lock 실패는 확정을 지연할 수 있다.
보고용 새 모델은 호출하지 않는다. date는 당일 KST, generated_at은 실제 확정 시각으로
같은 KST 날짜여야 하고 projection validator가 window·참여 시각·schema·digest를 검사한다.

`loop/publications/<date>.json`에 frozen report/payload/digest/projection_limit를 prepared로
먼저 저장한 뒤 days/scans/web/latest를 materialize하고 publication_pending으로
전환한다. crash 후에는 journal의 같은 bytes 의미/digest만 복구한다. 기존 days/<date>.json이
있으면 legacy_preserved로 덮어쓰기/자동 재전달하지 않는다. 다른 내용의 day 충돌은
existing_day_conflict로 보존한다. 그날 후속 tick의 연구는 frozen 보고를 재생성하지 않는다.
다운타임 catchup은 09:00 이후 오늘 날짜 하나뿐이며 과거 보고 일괄 게시·모델 몰아호출은 없다.

완료 pool의 proposal과 scan provenance를 기존 API에 저장한다. 보고에 실린 ID는 원래
status/approve에서 판정할 수 있으며 아직 없는 승인/decision/실행 claim을 보고 때문에 만들지 않는다.
최신 검토 provenance를 오래된 아침 선택으로 되돌리지 않는다. 기존 human state를 덮어쓰지 않는다.

## CLI와 신뢰한 승인·실행

모든 명령은 저장소 루트에서 실제 Python 3.8 venv를 지정한다. 아래 ID·경로는 예시다.

| Make target | Python CLI (`python -m harness.improvements` 뒤) |
| --- | --- |
| `agent-improve [SCOPE_FILE=PATH]` | `discover [--scope-file PATH]` |
| `agent-improve-daily [DELIVER=1]` | `daily [--deliver]`, target이 unattended marker 설정 |
| `agent-improve-status [DATE=YYYY-MM-DD]` | `status [--date YYYY-MM-DD]` |
| `agent-improve-tick` | 별도 `python -m harness.improvement_loop tick`; 전달 기본 연결 |
| `agent-improve-loop-status` | 별도 `python -m harness.improvement_loop status`; 모델/키/quota 조회 없음 |
| `agent-improve-publish [RECONCILE=1]` | 별도 `python -m harness.improvement_loop publish [--reconcile]`; frozen 보고만 전달 |
| `agent-improve-approve PROPOSAL_ID=ID INSTRUCTION_FILE=PATH [LOCAL_ONLY=1]` | `approve --proposal-id ID --instruction-file PATH [--local-only]` |
| `agent-improve-reject PROPOSAL_ID=ID` | `reject --proposal-id ID` |
| `agent-improve-execute PROPOSAL_ID=ID` | `execute --proposal-id ID` |
| `agent-improve-completion RUN_ID=ID [RECONCILE=1]` | 별도 `python -m harness.improvement_completion --run-id ID [--reconcile]`; 같은 run의 완료 전달만 |

`harness.improvements tick/loop-status/publish [--reconcile]`도 동일 엔진에 연결된다.
raw engine API tick의 deliver 기본값은 False이므로 embedded parent는 deliver=True 또는
publisher를 명시해야 한다. 운영 CLI/Make tick은 deliver가 기본이며 기존 deliver_report에 연결된다.
별도 publish cron은 설치하지 않는다. `--no-deliver`는 수동 tick에서만 전달을 생략하는 옵션이다.

`report [--date YYYY-MM-DD]`는 정제 web JSON만 반환한다. 기존 status는 같은 report와
scan_id·정제된 human_state·별도 delivery 결과를 반환한다. 날짜 생략은 latest record를 사용한다.
approval instruction·서명·raw response를 출력하지 않는다. Make는 각각의 인자를 단일 shell
word로 quoting하며 eval하지 않는다. 사용자는 실제 파일 경로·ID를 넘기고 shell 코드를 넣지 않는다.

```bash
make agent-improve-loop-status PYTHON=/ABS/VENV/bin/python
make agent-improve-status PYTHON=/ABS/VENV/bin/python
make agent-improve-approve PYTHON=/ABS/VENV/bin/python PROPOSAL_ID=IMP-0123456789abcdef INSTRUCTION_FILE=/ABS/PRIVATE/instruction.txt
make agent-improve-execute PYTHON=/ABS/VENV/bin/python PROPOSAL_ID=IMP-0123456789abcdef
```

approve는 메인/신뢰한 운영자가 실제 사용자의 구체적인 제안 ID별 지시를 확인한 뒤에만 호출한다.
instruction은 UTF-8·비어 있지 않음·NUL 없음, 소유자 소유·nonsymlink·단일 hardlink·0600인
private 파일이어야 한다. approve-all/wildcard는 없고 모델 출력이나 보고서 boolean은 권한이 아니다.
reject도 사람의 결정이며 이미 claim한 실행을 되돌리지 않는다.
`TAVERN_WORKFLOW_CHILD` 또는 `TAVERN_IMPROVEMENT_DISCOVERY`가 있으면 개선 orchestration을 거부한다.
`TAVERN_IMPROVEMENT_UNATTENDED=1`은 approve/reject/execute와 수동 discover 재시도를 거부한다.
scheduler는 marker와 새 `tick`만 사용한다. discovery marker는 일반 workflow 진입도 차단하며,
unattended marker는 write workflow를 차단한다. scheduler는 일반 READ_ONLY workflow도 호출하지 않는다.

CLI는 인간을 식별할 수 없다. 신뢰한 parent가 instruction 출처를 확인한다는 운영 위협 모델이다.
승인과 claim은 최초 trusted approve가 생성한 private `authority.key`의 HMAC으로 검증한다.
이 키는 provider credential과 별개로 모델에 주지 않는다. 동일 OS 사용자 권한 탈취나
trusted parent의 고의 우회까지 차단한다는 주장은 하지 않는다.

승인은 원래 instruction·proposal/review digest·전체 source fingerprints·정확한 allowed_edit_files·
고유 authorization_id·발급/만료 시각·미소비 상태를 묶는다. 기본 유효기간은 7일이다.
publication은 `commit/pr/three-required-ci/squash-merge/cleanup`으로 고정하며 승인 시에만
`--local-only`를 선택할 수 있다. 이후 execute에서 게시 범위·task·files를 바꿀 수 없다.
approve와 execute 모두 독립 review와 source freshness를 확인하며 execute는 서명·만료·
decision·미소비도 확인한다. bytes/POSIX mode/존재·scope/config 변화는 실패시키고 새 점검을 요구한다.
loop 제안의 `_eligible/_fresh/_authorization`는 private scan과 proposal의 discovery_fingerprint,
현재 loop/local/agent/workflow config까지 확인한다. 서명 승인에 같은 context digest를 묶으므로
단순 live freshness 재확인만으로 이전 승인을 새 설정의 동일 ID에 재결합할 수 없다.

stable discovery와 기존 artifact nonblocking lock은 discovery/승인/claim 예약을 직렬화한다.
storage 선택이 달라도 source mutex inode를 유지하고 capture/freshness와 apply/cleanup의
경쟁을 막는다. execute는 state→source 잠금 아래 claim을 원자적으로
기록하고 생성한 고정 task·정확한 edit_files만 `workflow.execute`에 전달한다.
workflow가 state→source 잠금을 잡은 뒤 guard가 재검증하고 run_id를 private 기록에 남긴다.
모델·검증 중에는 두 잠금을 해제하며 apply 때 원래 signed claim과 freshness를 재검증한다.
그 뒤의 새 Claude 의미 검토·필수 checks·충돌 검사·scoped apply·기존 Git 역할과 게시 정책을 유지한다.
편집 범위에 필요한 읽기 참조/문서/테스트가 부족하면 자동 추가하지 않고 새 승인 필요로 중단한다.

중단·실패·exception 이후에도 claim은 자동 replay하지 않는다. 상태와 error_type·run_id를 보존한다.
`awaiting_github`는 non-success 인계이며 CLI가 0을 반환해도 완료가 아니다. 메인은 기록된 run의
request/accept journal로 실제 CI 3개(`Offline harness (SQLite)`, `MySQL harness`,
`Chromium browser harness`) success·SHA 고정 squash merge·cleanup complete를 확인한다.
cleanup_pending이나 모호한 GitHub 쓰기를 새 execute로 해결하지 않는다.
improvement execution record는 인계 시점 상태이며 이후 완료는 workflow/journal로 확인한다.

재승인이 필요하면 메인이 기존 run을 terminal `passed|failed|interrupted`로 조정하고 merge한
경우 cleanup도 완료한 뒤 새 명시 지시로 다음을 사용한다.

```bash
/ABS/VENV/bin/python -m harness.improvements approve --proposal-id IMP-0123456789abcdef --instruction-file /ABS/PRIVATE/new-instruction.txt --reconcile-run-id EXISTING_RUN_ID
```

workflow에 넘기기 전 중단되어 claim의 run_id가 null이면 실제 미시작을 확인한 후에만
`--reconcile-run-id unstarted`를 쓴다. 기존 claim/approval/decision/execution은 history로
archive한다. reconcile은 기존 실행을 반복하거나 승인 없이 갱신하지 않는다. source가 바뀌면
먼저 새 점검/제안이 필요하다. 서명 기록을 수작업 편집하거나 claim을 지워 replay하지 않는다.

## 승인 제안 자동 완료 전달

사용자의 별도 명시 허가에 따라 private Sites에는 기존 불변 `improvement-web-v1` 오전 보고와
별도 `improvement-completion-v1` 완료 레코드 두 계약만 전달한다. 보고서 원문과 digest,
publication journal은 완료 표시 때문에 수정하지 않는다. browser는 proposal_id로 별도 완료
목록을 결합해 ‘작업 완료’와 PR 링크를 표시한다. Sites 소스/API/UI 구현·배포와 credential
관리는 메인 책임이다. 이 저장소는 offline contract를 제공하며 실제 endpoint 배포/HTTP 성공을
주장하지 않는다. 기존 모델/역할/auth/스케줄/37개 discovery scope/개별 승인·일회성 claim/
원격 CI3+merge+cleanup 게이트는 유지한다. 일반 bundle 승인 API도 추가하지 않는다.

`git_publish.main`의 request/accept/resume/cleanup은 마지막 durable save 후 project/GitHub
lock을 모두 닫고 lazy import로 `complete_run`을 호출한다. Store lock 역순 deadlock을 피한다.
완료 전달 실패는 JSON의 별도 `completion={status,completions,...}`로 표시하며 workflow의
passed·merge SHA·cleanup 성공 및 Git CLI 성공 반환을 덮어쓰지 않는다.

완료 검증에는 다음 증거가 모두 필요하다.

- 현재 선택된 workflow root의 owned 0700 run directory, no-follow private 0600 report/journal/
  publication records. 다른 local/legacy root로 fallback하지 않는다. 기존 `validate_journal`로
  github-v1 run/branch/origin/config와 승인된 before/after snapshot·내용 hash/mode를 대조한다.
- report.run_id 정확 일치·status=passed, read_only/simulated/no_git=false·github_enabled=true,
  정확한 저장소/양의 PR 번호/PR URL, merge_status=merged·유효한 40lowerhex merge/head SHA,
  step=done 및 cleanup_complete. 원래 CI 3종 모두 success, cleanup_proof.verified=true와
  head_sha/merge_sha 일치 및 proof의 같은 CI 3종 success도 필요하다.
- 해당 run_id에 정확히 연결된 각 private signed claim과 signed approval을 Store.verify로
  검증한다. proposal ID/digest·review digest·source fingerprint·authorization_id·claim_id,
  claim의 running/consumed 상태와 approved decision·허용 edit scope를 대조한다. persisted
  discovery review와 실제 구현 review/documentation, applied/changed scope, 원래 required_checks의
  final validation 및 structured coverage 성공을 확인한다. 단일 claim은 아래 두 task digest를
  각각 검증한다. 같은 run의 복수 claim은 각각 검증하고 scope의 합을 대조하여 명시된 일회 bundle과
  호환한다. title/fuzzy alias나 run_id 문자열만으로 승인을 추정하지 않는다.

단일 claim에서는 persisted proposal과 signed approval로 `_task(record, approval)`를 한 번
재구성한다. `claim.task_digest`는 `improvements.execute`가 workflow에 넘기기 전에 계산한
**raw task UTF-8 bytes의 SHA256**이며, 재구성한 task를 같은 방식으로 검증한다.
`report.task_sha256`는 `workflow.execute`가 provider key redaction 후 계산한 **task 문자열의
JSON digest**다. 공개 사용점 `workflow.triage.digest(task)`로 별도 재계산해 report와 대조한다.
두 표현은 서로 다르므로 claim과 report의 digest를 직접 같다고 비교하거나 임의 digest
fallback으로 받아들이지 않는다. 이는 ADR0020의 기존 증거 결합을 바로잡는 구현 수리이며
완료 API wire 계약이나 서명·승인 기록은 바꾸지 않는다.

완료 증거 확인은 provider key나 inbox credential을 로딩하지 않는다. Store 서명용
`authority.key` 검증은 기존대로 유지하고 inbox credential은 필요한 HTTP 전달 단계에서만
읽는다. 이미 delivered인 기록의 재확인에는 inbox credential도 읽지 않는다.
workflow의 key redaction이 원래 task를 변경했다면 credential 없이 재구성한 task와
report의 digest가 달라져 **fail-closed로 blocked**가 된다. 원문이나 키를 추가로 읽어
redaction을 재현하거나 비교를 생략하거나 승인 기록을 재작성하여 이 한계를 우회하지 않는다.

`_authorization`/`_fresh`를 완료 단계에서 재호출하지 않는다. 실행 전에 수행한 freshness와
완료 증거는 별개다. claim 당시 issued_at≤claim.at<expires_at 및 최대 7일 구간을 확인하되
작업 후 source 변경이나 현재 승인 만료 때문에 승인/실행을 다시 소비하지 않는다.
현 protocol의 완료는 원래 Read proof와 signed discovery binding을 검증한다. 도입 전 loop·non-loop
서명 claim은 원래 완전한 독립 verdict·서명 approval/claim·source/review/task/scope 및 실제 실행
증거로 완료만 확인할 수 있다. 이전 loop approval에도 `discovery_fingerprint`가 있으며 원래 정의인
`digest(scan['loop_dependencies'])`를 approval과 persisted proposal provenance에 대조한다. non-loop의
원래 context는 없다. `source_review`·`source_review_binding` 또는 scan/loop dependencies의
`review_protocol` 표식은 값이 잘못됐거나 null이어도 modern 경로를 요구한다. proof/binding 누락을
호환 경로로 낮추거나 기록을 변환하지 않으며 새 승인/execute의 source Read 요구도 면제하지 않는다.
연결 claim 없는 일반 run은 키/credential/HTTP 없는 no-op이다. child/discovery/unattended,
READ_ONLY=1·GIT=0, read_only/simulated/no_git·local-only 승인에는 전송하지 않는다.

### completion-v1 wire와 Sites 서버 계약

POST `/api/completions`에는 아래 **정확히 7개 key**의 JSON 한 건만 보낸다.
GET `/api/completions/{proposal_id}`는 wrapper 없이 같은 exact payload를 반환하며 absent는 404다.
browser는 cursor paginated GET `/api/completions` (후속 cursor query)을 사용한다. 목록 응답의
page/cursor UI 연결은 메인이 구현하며 개별 payload를 변경하지 않는다.

| key | 값 |
| --- | --- |
| version | `improvement-completion-v1` |
| proposal_id | `IMP-` + 16lowerhex |
| status | `completed` |
| pr_url | `https://github.com/21in7/TavernofSoul/pull/` + 양의 십진 정수 |
| merge_sha | 40lowerhex |
| completed_at | timezone-aware UTC ISO8601 문자열; 최초 outbox 생성 시 고정 |
| digest | 위 6개 필드 전체의 canonical sorted compact JSON SHA256 (digest 제외) |

canonical은 기존 `ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False` UTF-8이다.
완료 payload/HTTP response는 각각 최대 16384 bytes, 요청 timeout은 기존 private
delivery_timeout_seconds 이하(절대 30초 이하)다. 같은 private inbox `{origin,token}`과
`OAI-Sites-Authorization: Bearer <token>`을 사용하며 기존 system TLS/no-redirect
`http_transport`를 재사용한다. 메인 parent만 credential을 다룬다. 원문·사용자 지시·키·절대경로·
source/diff/prompt/log를 payload·stdout·오류 원문으로 보내지 않는다. stdout에는 고정 상태/reason과
정제 proposal ID/digest/PR만 추가한다.

서버는 proposal ID별 immutable **atomic create-if-absent**를 구현한다. 동일 digest는 멱등
200, 다른 digest는 409이며 기존 완료를 overwrite하지 않는다. POST 성공만으로 host의 delivered가
되지 않는다. GET의 strict schema·재계산 digest·전체 payload가 frozen 값과 정확히 일치해야 한다.

### durable outbox와 동일 run 복구

선택된 improvements root의 `completions/<run_id>/<proposal_id>.json`은 한 atomic checkpoint에
canonical payload/digest와 연결 run/authorization/claim ID, journal `state/reason`을 담는다.
Store의 owned private directory/0600 replace·file fsync·directory fsync를 사용한다. 최초
completed_at을 고정한 ready record를 HTTP 전에 저장하고 sending도 POST 전에 먼저 저장한다.
payload와 journal의 생성 간격을 없애며 승인/claim·오전 보고/publication은 쓰지 않는다.

| 기존 state | 일반 재호출 | 명시 RECONCILE=1 |
| --- | --- | --- |
| ready | 최초 POST → GET readback | GET 확인, absent일 때만 같은 payload POST → GET |
| sending/unknown | GET만; 정확 일치 delivered, absent는 unknown 유지 | GET 확인, absent일 때만 같은 digest POST → GET |
| conflict | HTTP/overwrite/retry 없음 | 동일하게 차단; 메인이 실제 서버 충돌 조사 |
| delivered | HTTP 없음 | HTTP 없음 |

timeout/중단/HTTP 실패/invalid readback은 unknown과 고정 정제 reason으로 남긴다.
다른 유효 digest/payload readback 또는 POST409는 conflict다. 프로세스가 POST 직후 죽어도
durable sending으로 남아 자동 POST를 막는다. partial progress의 다른 claim들은 각자 같은
frozen payload로 재개한다. readback/retry로 completed_at/digest를 재생성하지 않는다.

메인은 원래 run과 **동일한 storage 환경**으로 `make agent-improve-completion RUN_ID=...`를
사용한다. unknown의 실제 상태를 조사한 뒤 `RECONCILE=1`을 지정할 수 있다. 이 CLI는 새
모델/승인/execute/commit/PR/merge 없이 그 run의 완료 전달만 처리하며 cron/tick에 연결하지 않는다.
완료 증거/storage가 유효하지 않으면 blocked, 전달 미확정은 pending, 전부 확인되면 delivered,
연결 claim 없으면 not_applicable, 실행 모드 금지는 disabled다. 새 승인이 필요한 기존 실행
복구와 outbox의 같은 digest 전달 복구를 혼동하지 않는다.

오프라인 회귀는 `harness/test_improvement_completion.py`에 두며 기존 full make check의
`harness/test_*.py` 수집을 따른다. worker는 검사·network·Git·서비스·재위임을 실행하지 않는다.
실행기가 새 의미 검토·기존 GitHub 회귀·full make check를 수행한다. 실제 Sites 배포/HTTP 관측은
메인의 별도 작업이다.

## improvement-web-v1 계약

host는 private 보고가 존재한 뒤 명시 projection만 만든다. HTML/Markdown은 같은 payload를
검증하여 한국어 최대 3카드로 요약하며 HTML escape·Markdown 구문 escape와 A4 print style을
사용한다. 모델 raw HTML을 렌더링하지 않는다. 전체 private 후보는 최대 8개이고 한 장에서
남은 개수만 표시한다. 실제 인쇄 pagination은 브라우저/글꼴에 따라 메인이 확인해야 한다.

최상위 필드는 아래 12개만 허용한다. payload 전체는 262144 bytes 이하이다.

| 필드 | 정확한 의미와 한도 |
| --- | --- |
| `version` | 문자열 `improvement-web-v1` |
| `date` | `YYYY-MM-DD`, Asia/Seoul 날짜 |
| `generated_at` | timezone 있는 ISO8601 문자열 ≤40자, KST 변환 날짜가 date와 일치 |
| `status` | `scanned`, `partial`, `failed` |
| `headline` | 정제 문자열 ≤100자; 기본 '자동 점검 / 승인 전 변경 없음' |
| `summary` | 정제 문자열 ≤400자; 정상 0개와 실패/미완료 0개를 구분 |
| `analogy` | 정제된 일상 비유 ≤200자 |
| `proposals` | 아래 card 배열, 최대 3개, priority high/medium/low 다음 ID 순 |
| `agents` | 최대 5개 `{role,provider,model,status}`만 포함 |
| `counts` | `{candidates,reported,additional_candidates,eligible}` 정수 |
| `documentation` | `{status,files,reason}` 자문 문서 판단 |
| `digest` | digest 자신을 제외한 canonical JSON의 SHA256, 64 lowercase hex |

card의 정확한 필드는
`id,priority,title,analogy,issue,evidence,benefit,risk,edit_files,validation_plan,documentation_impact,review,approval_wording`이다.
candidate의 같은 이름 필드·배열 한도와 위 표의 기존 PUBLIC 문자 상한을 사용한다.
PRIVATE 상한은 웹 입력에 적용하지 않는다. id는 `IMP-[0-9a-f]{16}`,
review는 `{verdict,reason,documentation}`, approval_wording은 정확히 `'제안 ' + id + ' 승인'`이다.
review verdict는 `eligible|rejected|needs_evidence`이며 누락/실패한 검토는
needs_evidence로 투영하여 독립 검토가 끝났다고 표시하지 않는다.
evidence와 benefit.evidence는 승인 상대 path와 line range/정제 summary만 포함한다.
benefit.kind는 estimated/measured로 그대로 유지하며 한 장에서는 '예상·미측정' 또는 '측정 근거 있음'을 표시한다.
edit_files는 정확한 상대 파일 목록이다. validation_plan/documentation_impact는 JSON에 보존한다.
카드에는 human 승인 instruction·실행 상태·source fingerprints·원본 proposal digest가 없다.

agents.role은 coordinator/downloader/parser/django/reviewer, provider/model은 정제된 실제
식별자(각 ≤80/120자), status는 `succeeded|failed|unavailable|not_called`다.
unavailable/not_called의 provider/model은 null일 수 있다. timing·cost·raw result는 private에만 둔다.
counts.candidates는 전체 후보 수 0~8, reported는 실제 표시 수 0~3,
additional_candidates는 candidates-reported, eligible은 **표시 밖을 포함한 전체 적격 후보 수**다.
적격은 human 승인 수가 아니다. documentation.status는 required/missing/not_required,
files는 승인 상대 Markdown 경로 최대 12개, reason은 구체적인 정제 설명 12~360자다.

canonical JSON은 Python의 `json.dumps(value, ensure_ascii=False, sort_keys=True,
separators=(',', ':'), allow_nan=False).encode('utf-8')`이며 digest 필드 없이 SHA256한다.
반드시 같은 UTF-8 key 정렬/숫자 표현으로 계산한다. digest는 전송 일치 확인이며 사용자 승인이나
서비스 신원 증명은 아니다. human/delivery 상태와 비용 metadata는 payload digest를 바꾸지 않는다.
credential·승인 지시·절대 local 경로·외부 URL·raw 응답·prompt·source text/diff·로그를 웹에
포함하지 않는다. 자유 문자열은 credential/경로 정제·표시 공백 정규화 후 길이 상한을 적용하고
렌더링 시 escape한다. 표시 상한을 넘으면 마지막 한 자리를 `…`로 사용하여 생략을 드러낸다.
이 축약은 표시 projection에만 적용되며 원본 proposal 내용을 덮어쓰지 않는다. public validator는
정제/축약 전 PUBLIC 상한을 엄격히 검사하므로 올바르게 재계산한 digest가 있어도 oversized card를
거부한다. `improvement-web-v1`의 버전·allowlist shape·public maxima·canonical digest는 유지하며
이 web-v1 표시 변경 자체는 private Sites에 새 배포/API/auth 변경을 요구하지 않는다.
별도 completion-v1 API는 아래 계약대로 메인이 구현·배포한다. HTML/Markdown은 같은 제한된
payload를 검증한 뒤 기존 최대 3카드 한 장 요약을 만든다.
정제는 민감한 임의 데이터를 공유할 허가가 아니며 소스 범위부터 private 내용을 제외해야 한다.

## 비공개 HTTP 전달

메인만 `logs/harness/improvement-inbox.json`을 관리한다. ignored private UTF-8 JSON은 정확히
`{origin,token}`이며 owned nonsymlink·단일 hardlink·0600이어야 한다. ancestor symlink도 거부한다.
origin은 credential/query/fragment 없는 HTTPS site origin(경로는 빈 값 또는 `/`)이고 ≤2048자,
token은 공백/제어문자 없는 ASCII 1~4096자다. 모델은 이 파일을 읽지 못하며 코드는 credential을 생성하지 않는다.

기존 로컬 web report가 있어야만 `deliver_report(date, *, inbox_config=None, transport=None, selected=None)`가
전달한다. 기본 config는 위 private 파일이다. trusted parent만 호출하며 child/discovery에서는 거부한다.
unattended tick/publish는 전달할 수 있지만 승인/실행할 수 없다.

1. `POST /api/reports`에 canonical web JSON과 `Content-Type: application/json`,
   `Accept: application/json`, `OAI-Sites-Authorization: Bearer <token>`을 보낸다.
2. POST 2xx 후 `GET /api/reports/<date>`에 같은 인증을 보내 2xx를 요구한다.
3. GET body는 **직접 improvement-web-v1 객체**여야 하며 wrapper 없이 schema·date·재계산 digest·
   로컬 payload digest 일치를 검사한다. POST response body는 권한/결과 근거로 출력하지 않는다.

기본 HTTPS transport는 system TLS 검증을 사용하고 proxy 설정을 읽지 않으며 redirect를 따라가지 않는다.
request/response bytes는 각 262144 이하, timeout은 요청마다 현재 20초다. Content-Length와
실제 누적 read를 제한하고 읽기 deadline을 적용한다. token·header·raw remote body·예외 원문을
로그/터미널에 출력하지 않고 고정 error_type만 기록한다. 3xx·비2xx·초과·날짜/digest 불일치는
`delivery_failed`다. 로컬 보고를 보존하며 전달 상태는 별도 기록한다.

loop 전송은 publication journal에 `sending/attempt_id`를 먼저 기록하고 **improvement와 project
lock을 모두 해제한 뒤** deliver_report를 호출한다. callback은 자체 Store.lock을 잡아 HTTP를
직렬화한다. 별도 sender mutex는 active callback과 명시 reconcile의 동시 실행도 거부한다.
Store.lock 안에서 publish/deliver_report를 callback으로 재진입시키지 않는다.
delivery/<date>.json에도 HTTP 전에 publication_attempt_id를 남기며 같은 attempt의 직접 API
호출은 재전송하지 않는다. 응답 실패/exception/crash·잘못된 digest는 publication_unknown으로
보수적으로 취급해 일반 tick이 자동 재시도하지 않는다. 기존 동일 digest delivered 기록이 있으면
다음 publish가 HTTP 없이 journal만 delivered로 정산한다.

메인은 private inbox의 실제 날짜/digest와 journal 상태를 먼저 확인한다. 확인 후에도 명시적
조정이 필요하면 `make agent-improve-publish ... RECONCILE=1` 또는 아래 CLI를 사용한다.
새 attempt_id를 부여하되 frozen digest는 고정한다. 전달 unknown을 discover/daily 재실행이나
보고 파일 수정으로 풀지 않는다. 성공 뒤에는 모델도 HTTP도 반복하지 않는다.

```bash
TAVERN_IMPROVEMENT_UNATTENDED=1 HARNESS_STORAGE_CONFIG=/ABS/REPO/logs/harness/improvement-storage.json /ABS/VENV/bin/python -m harness.improvement_loop publish --reconcile
```

같은 date/digest의 수동 재전달도 receiver가 idempotent하게 저장해야 한다. 네트워크 전체의
절대 exactly-once 도착은 보장하지 않으며 날짜별 확정과 digest 일치로 중복 내용을 통제한다.
publish는 오늘 날짜09:00 이후만 다루고 과거 일괄 복구 명령은 제공하지 않는다. legacy daily의
재전달 호환은 loop 관리 전의 기록에 한정하며 loop 관리 보고를 우회하지 않는다.

## 운영과 09시 예약

메인 제공 기존 상태는 단일 hourly wrapper 활성과2026-10-16 09:00 partial/제안0개 보고1회
전달이다. 확정 보고를 재생성하지 않는다. 새 mlx-vlm 서비스/private config의 검증 후 전환과
최종 adapter 실추론·전체 검증·실제9단계·다음 아침 게시 성공은 메인 확인 전까지 주장하지 않는다.
기존 서비스/터널 준비·이전 약19.54초 합성 추론과 native 서버/미검토 bytes의 사전 관측은
[local-models](local-models.md)에 근거 수준을 둔다. 이 worker는 private wrapper·cron·settings·
호스트를 읽거나 수정하지 않는다.

2026-10-15 메인 제공 관찰로 owner-private Site 익명 API403·service-auth page/upload/readback/
index200과 ignored0600 inbox credential 준비를 확인했다. daily용 명시 local storage는
`logs/harness/improvement-storage.json`이며 artifacts/temp를 별도 local root로, required_mount는
`/`, free floor는1GiB로 선택했다. persistent NFS default는 변경하지 않는다. 이 선택은 새 자동
fallback이 아니다. worker는 private daily.sh·cron·settings·키·호스트를 읽거나 수정하지 않았다.

아래는 기존 daily에서 단일 hourly로 이행하는 메인 전용 설치 절차다. 이미 hourly인 경우
중복 설치하지 않고 기존 wrapper·block을 유지한다. 이번 프로토콜의 서비스/private config 전환은
새 Claude 검토·전체 make check·scoped apply와 메인의 최종 HTTP 확인 뒤 수행한다. 이전 합성
추론이나 보존 초안은 이 gate들을 대신하지 않는다. 설치 예제는 worker의 실행 결과가 아니다. GitHub 전달은 기존 Git 역할/검증된 요청·baseline/승인 게이트를 별도 통과한다.

1. 실제 venv/저장소 절대 경로, host Asia/Seoul, storage readiness와 ignored local-model.json/inbox
   0600 설정, 기존 단일 marked block을 메인만 확인한다. 다른 cron과 게임 jobs는 보존한다.
   host timezone이 다르면 daemon의 timezone 지원을 명시 확인한다. Python의 KST 계산이 cron
   timezone을 바꾸지는 않는다.
2. 기존 private daily.sh의 실행 본문을 아래 **정확한 Python CLI**로 바꾼다. ABS는 메인이
   확인한 절대 경로로 치환한다. local storage 설정을 그대로 명시하며 다른 storage root로
   바꿔 ledger를 초기화하지 않는다. private wrapper/log의 기존 권한을 보존한다.
3. 기존 marked block 하나의09:00 line을 아래 hourly line 하나로 교체한다. 같은 작업의 새 block을
   추가하지 않고 기존 block 표식은 유지해 중복 설치를 피한다. discover/daily/별도 publish job을
   함께 예약하지 않는다. 설치 전후 기존 게임 jobs가 동일한지는 메인이 확인한다.
4. 첫 새 slot의 private 상태·실제 모델 참여·보고 journal을 확인한다. 오늘 기존 day가 있으면
   덮어쓰기/재전달하지 않으며 다음 날짜09:00의 frozen 보고를 확인한다. 성공을 확인하기 위해
   같은 slot 재실행·state 삭제·모델 몰아호출하지 않는다.

private wrapper 본문의 형태:

```sh
#!/bin/sh
set -eu
cd /ABS/REPO
export TAVERN_IMPROVEMENT_UNATTENDED=1
export HARNESS_STORAGE_CONFIG=/ABS/REPO/logs/harness/improvement-storage.json
exec /ABS/VENV/bin/python -m harness.improvement_loop tick
```

기존 표식을 유지한 cron 교체 예시(메인만 실행):

```cron
# BEGIN tavern-improvement-daily (read-only discovery)
0 * * * * /ABS/PRIVATE/daily.sh >> /ABS/PRIVATE/improvement-daily.log 2>&1
# END tavern-improvement-daily
```

wrapper 없이 동일 invocation을 쓰는 경우는 다음 line 하나이며 둘을 함께 설치하지 않는다.

```cron
0 * * * * cd /ABS/REPO && TAVERN_IMPROVEMENT_UNATTENDED=1 HARNESS_STORAGE_CONFIG=/ABS/REPO/logs/harness/improvement-storage.json /ABS/VENV/bin/python -m harness.improvement_loop tick >> /ABS/PRIVATE/improvement-daily.log 2>&1
```

Make의 정확한 대응은 `make agent-improve-tick PYTHON=/ABS/VENV/bin/python`이며 동일 storage
환경을 붙인다. CLI tick은 기본 Sites publisher를 연결한다. daemon/retry wrapper/sleep polling은
추가하지 않는다. tick 최대600초·cloud480초·local180초·quota15초로 시간 slot보다 짧다.
로그는 ignored private 경로에 두고 credential을 cron 인자/환경/log에 쓰지 않는다.

처음 활성화한 날은 legacy scan 비용/호출을 carry-in하고 기존 day를 보존한다. 09:00 전에는
연구만 하며 그 이후 첫 tick은 이전09:00~현재09:00의 완료 review로 오늘 보고 하나를 확정한다.
그 window에 새 엔진 완료 review가 없으면 partial/failed로 정직하게 남긴다. 다운타임 뒤에도
오늘 날짜만 catchup하며 과거날 보고나 누락 모델 호출을 몰아서 실행하지 않는다. 자정 직전
600초는 admission을 막고 날짜 전환 시 새 ledger와 기존 round/cursor는 분리해 유지한다.

운영자는 다음 모델 없는 명령으로 한국어 추정 잔액·오늘 호출 수·보류 reason·다음 역할/단계·
마지막 검토·다음 보고 시각·publication 상태를 확인한다.

```bash
HARNESS_STORAGE_CONFIG=/ABS/REPO/logs/harness/improvement-storage.json /ABS/VENV/bin/python -m harness.improvement_loop status
# 같은 상태의 Make 진입점
HARNESS_STORAGE_CONFIG=/ABS/REPO/logs/harness/improvement-storage.json make agent-improve-loop-status PYTHON=/ABS/VENV/bin/python
```

status는 ledger를 초기화하거나 keys/quota를 읽지 않으며 마지막 tick의 freshness 판단을 표시한다.
실시간 소스 유효성 재검증이나 실제 청구 잔액 조회는 아니다. 초기 잔액은 미초기화/unknown일 수 있다.
tick의 loop 설정 로드·Store 생성·readiness를 포함한 저장소/설정 준비 실패는 bounded 정제
`paused`와 실제 경계별 고정 private 진단으로 반환한다. 이 준비 실패 경로에서는 모델·
키 조회·보고 확정·publisher·저장소 fallback을 실행하지 않고 원문 예외도 내보내지 않는다.
child/discovery 거부는 이 처리 바깥에서 유지한다. 저장소와 잠금이 준비된 뒤 source/config가
미준비인 경우의 실패 보고 확정과는 구분한다. 잠금·runtime 미준비도 scanned가 아니다.
이미 claim한 failed slot은 자동
재호출하지 않는다. 저장 준비가 회복되면 다음 새 slot에서 진행한다. 다른 local/NFS로 자동 이동하지
않는다. budget/quota 보류·초안 실패는 위 단계 정책을, 전송 unknown은 동일 digest 수동 조정을,
승인 실행 실패는 기존 run/journal 확인과 새 명시 승인 절차를 따른다. scheduler는 결코 approvals/
claims/workflow/GitHub를 시작하지 않는다.

## 현재 검토·검증 인계

이번16파일 초안의 문서 보정·strict 계약은 [ADR0026](adr/0026-source-verified-retained-improvement-reports.md#2026-10-27-최종-review-문서-계약-정합-수리),
실패 이력과 미관측 상태는 [ADR0034 최신 관측](adr/0034-inspection-failure-recovery-and-health.md#2026-10-27-최신-main-관측)을 따른다.
[과거 인계 원문](adr/0034-inspection-failure-recovery-and-health.md#보존-인계-current)은 당시 기록으로 보존한다.
새 검토는 최종 코드·문서에 documentation={status,files,reason}을 독립 판단하며 과거 결과를 재사용하지 않는다.

## 이번 프로토콜 수리의 문서 영향

아래는 이전21개 프로토콜/진단 수리 당시 판단이다. 이후32개 진행 보존 수리 당시 문서 판단과
신규 ADR 여부는 [당시 인계](#진행-보존-수리의-문서-영향과-실행기-인계)에 보존한다.

[원문 인계 보존](adr/0034-inspection-failure-recovery-and-health.md#보존-인계-protocol)에 당시 기록을 옮겼다.
새 검토는 최종 코드·문서에 documentation={status,files,reason}을 독립 판단하며 과거 결과를 재사용하지 않는다.

## 이전 수리의 검토·검증 인계 기록

[원문 인계 보존](adr/0034-inspection-failure-recovery-and-health.md#보존-인계-history)에 당시 기록을 옮겼다.
새 검토는 최종 코드·문서에 documentation={status,files,reason}을 독립 판단하며 과거 결과를 재사용하지 않는다.

오프라인 회귀 명세는 [test_improvements.py](../harness/test_improvements.py)와
[test_workflow.py](../harness/test_workflow.py)에 있다. fake 모델/HTTP를 사용하여 역할별 scope,
write=False·검사/워크플로 미호출, 실패/오류 응답, 날짜 idempotency, 승인 변조/만료/staleness,
claim 경쟁/replay, 정확한 handoff, awaiting_github, private 격리, renderer/digest와 bounded
HTTPS 전달·retry를 대상으로 한다. 명세 존재는 실행 결과가 아니다. 이번 문서 worker는
검사·테스트·실모델·Git·workflow·cron·배포를 실행하지 않았다. 오케스트레이터가 최종 소스의
의미 검토·전체 checks를 수행하고 메인이 실제 게시/CI/merge/cleanup·첫 scan·스케줄 활성화를 확인한다.

## Private GLM 지연 기록 읽기

[ADR0019](adr/0019-private-glm-call-telemetry.md)의 `glm-call-telemetry-v1`은
GLM 역할의 `agents[].telemetry`에만 추가되는 선택적 private 계약이다. 전체 필드·상한·해석은
[모델 연결](agent-models.md#glm-호출의-private-지연-관측)을 따른다. 오래된 기록에 필드가 없어도
유효하며 과거 기록이나 frozen morning report를 계측 때문에 다시 만들지 않는다.

저장 위치는 기존 Store의 선택된 improvement report root다. 설정/명시 report 경로의 기존
우선순위를 그대로 사용한다. local 기본은 `logs/harness/improvements/`이며 기존 설정이 외부
artifact root나 별도 보고 위치를 선택했다면 그 선택을 따른다. 새 저장 default/fallback이나
별도 raw trace 파일은 없다. `scans/<scan_id>.json`의 agents와 진행 중 `loop/state.json`의
`round.report.agents`에 정제된 계측이 남는다. 기존 private directory0700/file0600 및
record1MiB 상한을 유지한다. 기존 morning 선택이 담은 private participation은 그때의 기록을
따르되 공개 `improvement-web-v1`, publisher 본문·digest에는 새 계측을 넣지 않는다.

`_call_role`은 context 복사·prompt 준비를 monotonic `context_preparation_ms`로,
기존 호출 뒤 읽기 전용 사본 검증을 `source_verification_ms`로 분리한다. 후자를 수행하지 못하면
null이며 GLM Read 시간이 아니다. 전체 elapsed_seconds에는 context 정리 등 다른 부모 작업도
있다. runner의 정제 telemetry는 결과 축약·CLI 실패·timeout·응답 계약 거절 전에 별도로 보존한다.
loop의 `_safe_participation`은 version·collection bounds·numeric/fixed enum만 다시 검사하고
집계를 재계산하며 임의 runner diagnostics를 받아들이지 않는다. 잘못된 계약은 제거한다.

아래는 **향후 실제로 정상 admission된 GLM 연구가 끝난 뒤** 메인이 해당 private scan을
선택해 읽을 수 있는 예다. 지금 관측이나 성공을 주장하는 출력 예시는 아니다. 경로는 이미
선택된 private report root와 실제 scan_id를 사용해야 하며 새 extra source probe를 실행하지 않는다.

```python
# 메인이 이미 선택한 private 기록 한 개를 읽는 예시; worker 실행 명령이 아님.
record = json.loads(private_scan_path.read_text(encoding='utf-8'))
glm = next(a for a in record['agents'] if a.get('provider') == 'zai')
telemetry = glm.get('telemetry')
if telemetry is None:
    print('기존 기록 또는 계측 계약 미제공')
else:
    print(telemetry['availability'], telemetry['outcome'], telemetry['completeness'])
    print(telemetry['first_request_ttft_ms'], telemetry['launch_to_first_content_ms'])
    print(telemetry['logical_requests_observed'], telemetry['transport_attempts_known'])
    print(telemetry['tool_work']['Read'], telemetry['parent'])
```

requests를 시간순으로 보고 첫 요청의 TTFT/content, 요청 수·알려진 재시도·각 lifecycle,
Read body의 count/total/max, context 준비/검증 및 CLI wall을 함께 비교한다. token·turn과
물리 HTTP 요청 수는 다르다. 서로 겹칠 수 있는 work 합계에서 정확한 overhead를 역산하지 않는다.
누락 attempt/content는 null, 무수출은 unavailable, timeout은 이미 수출된 부분만 partial이다.
CLI final JSON duration/API time/turn은 보조값이며 미수출 요청을 메우지 않는다. 이 계측만으로
provider 대기·네트워크·SDK 내부 작업을 모두 분해하거나 정확한 disk I/O를 증명할 수 없다.

현재 worker는 실연구·합성 live·검사를 실행하지 않았다. 부모가 offline/full make check와
별도 합성 검증을 수행한 다음 기존 schedule·quota80%·budget·approval·37파일 scope·fingerprint·
storage·compaction을 유지한 다음 normally admitted GLM 단계에서 관찰한다. 이를 위해 추가
호출·schedule/state 수정·과거 아침 보고 재발행·거절된 repository-source probe를 만들지 않는다.
