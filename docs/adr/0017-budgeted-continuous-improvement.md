# 0017. 예산 우선의 시간별 연구와 불변 오전 보고 분리

- 상태: 제안(proposed), 사용자 승인 방향의 구현 결정 기록; mlx-vlm 최종 어댑터의 새 의미 검토·전체 검사·범위 반영·운영 검증 대기
- 기록일: 2026-10-16
- 대체 관계: [0015](0015-approval-gated-improvement-discovery.md)의 daily-only 예약·하루 한 scan/5회 호출·one-pass 정책만 대체한다. 개별 승인·claim·workflow·GitHub 권한은 유지한다. [0016](0016-bounded-private-improvement-text.md)의 private/public 서술·strict envelope 계약도 유지한다.

## 문맥

사용자는 매일 09:00 Asia/Seoul에 보고서를 한 번 게시하면서 다른 시간에는 앞선 의견을 이어
비판·보완하기를 직접 요청했다. 횟수보다 예산을 우선하며 GLM은 기존 Coding Lite 구독,
Claude 자동 탐색은 KST 하루 최대 US$1의 추정 ledger를 선택했다. 최신 결정은 항상 켜둘
Mac mini의 mlx-vlm이 작은 소스 부분에서 탐색하고 기존 역할들이 검토하는 방식이다.
이번 구현 workflow의 모델 비용은 자동 탐색 ledger 밖의 별도 비용이다. 발견된 제안의
수정·승인·실행 권한은 추가되지 않는다.

2026-10-16 프로토콜 정정: 종전 mlx-lm/default_model·prompt 준수에 의존한 초안 생성을
사용자 승인 방향인 mlx-vlm 네이티브 JSON Schema constrained generation으로 바꾼다.
최초 자동 초안은 JSON 파싱 뒤 `candidate_invalid`로 거절됐으므로 형식 검증에서 제외된 것이
아니다. 원문을 보존하지 않아 정확한 당시 실패 필드·값은 알 수 없다. 같은 입력의 별도 재현에서
edit_files 검증 거절과 evidence window 위반을 각각 관측했으나 최초 응답의 확정 원인은 아니다.
prompt/order 보강만으로 승인 범위 준수가 보장되지 않아 생성 단계에도 제약을 둔다.
이 정정은 승인된 기존 ADR0017 안에 기록하며 신규 ADR은 만들지 않는다.

## 결정

### 책임·유한 실행·범위

Python 3.8 `harness/improvement_loop.py`는 `tick/status/publish`와 durable state를,
`harness/local_model.py`는 표준라이브러리 HTTP와 작은 line window 검증만 담당한다.
`improvements.py`는 기존 private store·후보/승인·Sites 전달을, `improvement_report.py`는
순수 schema·fingerprint·web-v1 projection을 맡는다. 기존 cloud 역할/provider/model/effort/
compaction/auth/storage 설정을 바꾸지 않는다. mlx-vlm은 별도 로컬 초안 참여자다.

versioned `improvement-loop-config-v1`은 정확한 필드·타입·finite·상한과 필드 간 관계를 검사한다.
기본 hourly tick 한 번에 모델 최대 1회, 로컬 포함 KST 하루 최대 24회, 전체 tick 600초,
cloud 모델 480초, quota 15초다. cloud timeout+80초는 tick 이하여야 한다. daemon·sleep
polling·자동 retry·새 provider/balance fallback·quota 구매는 없다. lock/storage/runtime
실패를 성공한 scan으로 표시하지 않는다. tick의 설정 로드·Store 생성·readiness 준비 실패는
bounded 정제 paused(`lock_storage_or_runtime_unavailable`)로 반환하며 모델·키 조회·보고 확정·
publisher·저장소 fallback을 실행하지 않는다. child/discovery 권한 거부는 이 예외 처리 바깥에
유지하고 원문 예외는 노출하지 않는다. 호출보다 먼저 slot claim을 저장하며, 같은 slot은
실패·재시작·설정 변경 후에도 재호출하지 않는다. readiness 실패로 claim 자체를 저장하지
못할 수도 있으며 이때 모델은 실행하지 않는다. 기존 improvement/project lock을 함께 사용한다.

기본 9단계는 `local(coordinator) → coordinator → local(downloader) → downloader →
local(parser) → parser → local(django) → django → independent reviewer(Claude)`다.
한 specialist당 최대 2개, 전체 중복 없는 후보 최대 8개다. 기존 ownership+shared와
`harness/improvement-scope.txt`의 37개 읽기 승인을 늘리지 않는다. 필요한 다른 파일은 경로만
보고한다. cloud 역할은 기존 승인 소스 사본에서 근거를 확인하고 정식 후보를 만든다.
reviewer는 별도 context의 전체 승인 범위와 후보 전체를 검토한다. 자동 탐색 중 소스 수정·
검사·workflow·Git·cron·게임 파이프라인 실행은 금지한다.

### 로컬 초안·cursor·의견 계승

adapter는 owner별 승인 파일의 한 연속 line window만 전달한다. 요청 전체 UTF-8 bytes
최대 24576, 출력 max_tokens 3072, HTTP 180초, 응답 body 65536 bytes, header 8192 bytes다.
기본 window 96줄·feedback 4096 bytes이며 정확한 path와 원래 inclusive line 번호를 보낸다.
system 지시와 user JSON 데이터를 분리하고 `owner_role,sources,feedback,candidate_limit,approved_files`
순서로 비신뢰 소스·feedback 뒤에 편집 허용 목록을 둔다. 프롬프트는 스키마와 모순 없이 간결하게
유지하며 소스·feedback의 경로·지시가 권한을 만들지 않는다. strict JSON parser도 유지한다.
후보와 benefit의 evidence 모두 실제 전달 범위 안이어야 한다. basename 추정·경로 보정·
전체 파일 열람 주장은 거부한다. edit_files/문서 대상은 owner의 승인 범위 안에서만 허용한다.
큰 파일은 owner별 durable `{file_index,line}` cursor로 순환하며 호출 실패에도 앞선 window를
자동 반복하지 않는다. 긴 single line은 `line_too_long`으로 명시 skip하며 slice하지 않는다.

### 네이티브 schema·전송 전 검증·설정 이행

메인이 설치한 mlx-vlm 0.7.8은 요청의
`response_format={"type":"json_schema","json_schema":{"name":...,"strict":true,"schema":...}}`를
llguidance logits processor로 강제한다. `enable_thinking=false`는 request top-level에 둔다.
실제 전체 HTTP 요청에 다음 제약을 포함한다.

- root는 정확히 `{candidates:[...]}`이며 후보 최대2개와 빈 배열 기권을 허용한다.
  기존 canonical 후보의 모든 필드·타입·필수 항목과 객체별 `additionalProperties=false`,
  지원되는 배열·텍스트 상한을 명시한다. 후보 필드 생략·다른 축약 계약은 허용하지 않는다.
- edit_files enum은 현재 owner 승인 목록이다. 승인됐으나 미전송인 파일은 편집 대상만 될 수 있다.
  후보 evidence와 benefit.evidence의 path는 실제 전달한 단일 window 경로만 허용하고
  start_line/end_line은 그 window 원문 번호의 최소·최대 범위로 제한한다.
- `_validate_request`는 전달 window와 owner 승인 목록에서 재구성한 정확한 canonical schema와
  대조한다. schema 누락·완화·변조와 owner/window/scope·enable_thinking 변조를 transport 전에
  거절한다. 외부 호출자가 준비된 요청에 느슨한 schema를 주입해도 호출하지 않는다.
- window 선택은 schema overhead를 포함한 전체 직렬화 HTTP request24576bytes 상한을 지킨다.
  whole line만 선택하고 원문 번호를 유지한다. schema만으로 상한을 넘으면 bounded
  `context_too_large`로 호출하지 않는다. 소스 줄을 slice하거나 번호를 다시 매기지 않는다.

서버 제약은 클라이언트 검증의 대체가 아니다. `start_line<=end_line`, 중복, 문자열 총량,
비어 있거나 무의미한 내용 등 cross-field/semantic 검사와 실제 window 검증은 기존 공유
후보 validator가 최종 권위다. llguidance1.9.1이 지원하지 않는 `uniqueItems:true`는 넣지 않고
중복을 클라이언트에서 거절한다. 서버가 schema를 무시하거나 위반하면 응답을 그대로 거절한다.
자동 경로 보정·잘라내기·줄 번호 보정·근거 합성·재시도·fallback은 없다. 숫자 파일 ID나 window
evidence 합성 실험은 실패했고 어떤 소스에도 구현하지 않는다. canonical 경로·원문 번호를 유지한다.

local config는 명시적으로 `local-model-config-v2`, provider는 `mlx-vlm`으로 이행하며
`api_model == model`을 요구한다. 기존 model repository ID validation을 유지한다.
서버에는 `default_model` 별칭이 없고 메인은 기존 다운로드 모델을 같은 상대 repository ID 경로에
연결하여 로드한다. 요청의 model은 그 repository ID이며 절대 호스트 경로가 아니다.
v1 mlx-lm 설정은 자동 변환·대체하지 않고 `config_invalid`로 보류한다. config digest에 이
프로토콜 전환이 반영되어 이전 loop fingerprint·후보 승인 재사용이 불가능해야 한다.
Linux 어댑터는 Python3.8 표준라이브러리만 유지하며 서버 패키지 의존성을 추가하지 않는다.
private config·설치·SSH·서비스 전환과 실제 추론 검증은 메인 책임이다.

메인이 관측한 네이티브 서버의 assistant message에서 정확히 `tool_calls:null`과
`tool_call_id:null`은 무동작 메타데이터로 취급한다. 두 필드의 non-null 값(빈 배열/문자열 포함),
그 밖의 도구/함수 필드와 다른 위치의 도구 필드는 계속 거절한다. 요청의 text-only/no-tools
경계와 실제 응답 그대로의 검증을 유지한다.

### 초안 실패·참여·의견 계승

ADR0025로 대체: 로컬 실패·빈 초안·missing/empty/긴 줄·준비 실패에도 다음 정규 slot의
specialist는 승인 소스를 독립 분석한다. 최종 reviewer도 빈 pool의 coverage와 제안 유무를
평가한다. 실패한 local을 성공으로 바꾸거나 추가 call을 하지 않는다. reviewer 단계가 실패해도
다음 slot에 새 round를 시작한다. quota/budget 보류는 같은 단계를 다음 새 slot에서 다시
admission하며 실패한 호출을 같은 slot에서 재시도하지 않는다.

다음 round의 실제 local prompt에는 이전 정제 candidate의 issue/edit_files와 specialist 설명,
독립 `review.reason`을 전달한다. candidate_id와 draft_digest로 같은 초안에 대한 의견을 연결한다.
실패도 고정 reason으로 이어받고 feedback은 allowlist·redaction·bytes 상한을 적용한다.
완전한 요약이 안 들어가면 표시된 축약을 시도하고 전혀 담을 수 없으면 `feedback_cannot_fit`으로
보류한다. 원본 private 후보/검토는 자르지 않는다. 무제한 prompt/response 캐시는 없다.

private `local_participation`에는 `provider=mlx-vlm`, 설정된 실제 model identity,
`stage=local_explorer`, owner_role, called/status/reason/read_windows/skipped_lines를 보존한다.
시도는 서버 수신·성공의 증거가 아니다. API model과 서버가 로드한 repository ID의 일치는
메인이 별도 확인한다. local 초안을 eligible 제안이나 cloud specialist 성공으로 표시하지 않는다.
web-v1 agents에는 기존 coordinator/downloader/parser/django/reviewer 5역할의 실제 참여만 넣는다.
편집 목록 실패의 bounded reason `candidate_edit_files_invalid`, `candidate_edit_files_duplicate`,
`candidate_edit_files_outside_scope`를 유지한다. 그 외 미분류 계약 오류는 `candidate_invalid`,
공유 검증 통과 후 전달 window 위반은 `evidence_outside_window`다. 진단은 첫 실패 분류일 뿐
모든 오류나 정확한 값을 복원하지 않는다. 사용자 노출은 코드 allowlist만 허용하며 원문 응답·
프롬프트·소스·절대 호스트 경로를 로그·보고서·public web-v1에 넣지 않는다.

hourly 역할 실패도 기존 private 정제 계약 안에서 보존한다. `_call_role`이 실제 호출 준비/실행,
결과 envelope/identity, read-only 사본 확인, JSON, 후보/독립 검토와 context 종료 경계에서
고정 reason을 만들고 loop가 allowlist로 재검증해 private 참여와 다음-round local feedback으로
전달한다. API/CLI·telemetry 성공은 응답 검증 성공이 아니다. 편집 목록 reason은 정확한 공유
ValidationError의 고정3개 코드만 검증해 유지하며 외부 진단·예외문·자유 클래스명을 신뢰하지 않는다.
legacy/unknown reason은 role_failed, 미허용 error_type은 Exception이고 구문 위치는 보존하지 않는다.
신규 진단은 private에만 두며 web-v1 필드·payload·digest는 유지한다. 상세 고정 목록·상한·
fallback은 [운영 계약](../improvements.md#hourly-private-실패-진단과-인계)에 둔다.
이는 기존 실패 정제의 정밀화이며 이 ADR의 대체 범위·retry/fallback·스케줄·예산·승인·게시
결정은 바꾸지 않는다. 이번 회귀는 작성 후 미실행이며 full make check·수리 검증·PR·CI·머지는
메인과 실행기에게 인계한다. 메인이 전달한 2026-10-21 09:00 KST failed/0카드 보고는 실제
전달 관측이며 수정하지 않는다. 정확한 당시 참여·skip·reset 관측과 이를 대체하는 결정은
[ADR0025](0025-progress-preserving-improvement-reviews.md)에 둔다. 이번 최종 코드의 실제9단계·
정규 hourly 실모델·새 오전 보고 성공은 아직 관측하지 않았다.

### 비용·quota·자정·legacy 이행

Claude cap은 `min(0.20 USD, 당일 잔액, 기존 reviewer 호출 한도)`이며 호출 전에 durable
reservation과 role count를 같은 state write로 기록한다. optional downward-only
`max_budget_usd`를 `agent_models.run/command_for`에서 검증해 실제 CLI `--max-budget-usd`로
전달한다. bool·NaN/Inf·0/음수·기존 상한 증가·Claude 이외 provider를 거부한다. 일반 workflow의
reviewer 2 USD/escalation 5 USD와 다른 기본 예산은 변경하지 않는다.

성공한 호출의 finite/nonnegative CLI estimate만 정산하며 실패·timeout·비용 미상·중단은
예약액 전부를 소비한 것으로 둔다. 관측 추정이 예약액을 넘으면 초과액까지 기록하고 당일
모든 연구를 중단한다. 일반 잔액 소진은 reviewer admission에서 판단한다. 그 차례 전의
로컬/구독 역할은 다른 gate와24회 한도 내에서 진행할 수 있지만 reviewer 예산 보류는
`stage_index`를 진행시키지 않는다. 이후 새 slot에서도 같은 reviewer만 재판단하고, 대기가
풀릴 때까지 다음 round의 로컬/구독 역할도 멈춘다. 단계 건너뛰기는 없고 09:00 보고는 독립적이다.
비용 unknown을 0 USD로 표기하지 않는다. CLI estimate/cap은 실청구 강제상한 보장이 아니다.

UTC+9 calendar day로 집계하고 마지막 600초(기본 23:50 이후)는 모든 모델 admission을
거부한다. guard는 tick deadline 이상이다. durable high-water로 clock rollback·과거 slot
replay를 거부한다. 실행 중 시계 이동/다음 날 복구로 날짜를 넘으면 원래 예약을 유지하고
다음 날에도 보수적으로 count/charge한 뒤 양일 중단하여 새 allowance로 우회하지 않는다.
최근 7일 ledger는 state에, 이전 것은 `loop/ledgers/<date>.json`에 보관한다.

첫 활성화 때 같은 KST 날짜의 legacy days/scans를 scan_id로 중복 제거해 호출 수와 Claude
비용을 carry-in한다. 메인 관측 최신 0.0434664 USD도 실제 기록에서 읽으며 상수로 넣지 않는다.
한 번의 bounded migration index와 이후 정확한 day pointer의 legacy 활동을 반영하고
loop scan/projection은 비용 carry-in에서 제외한다. index 밖 scan을 계속 탐색하지 않는다. 불완전 과거 기록은
숨은 중단 호출을 고려해 당일 호출 한도를 소진 처리하며, Claude unknown은 당일 dollar
allowance를 보수적으로 소비 처리한다. 기존 day 보고는 덮어쓰거나 자동 재전달하지 않는다.

GLM은 기존 Claude Code `https://api.z.ai/api/anthropic` Coding Lite 연결을 유지한다.
매 GLM admission 직전 trusted parent만 기존 ZAI_API_KEY로 고정 HTTPS GET
`https://api.z.ai/api/monitor/usage/quota/limit`를 조회한다. timeout 최대 20초(기본 15),
응답 64KiB·header 제한·redirect/proxy/retry 금지다. key/raw body/예외 원문은 모델·로그·웹에
주지 않는다. quota 실패/unknown/malformed는 GLM을 보류하고 정제 reason만 남긴다.
`TIME_LIMIT`만으로 준비를 인정하지 않는다. `TOKENS_LIMIT`/`CREDIT_LIMIT` 모두 5시간
unit=3/number=5의 finite percentage 0..100과 미래 정수 epoch-ms reset(현재 이후·8일 이내)을
검증한다. 두 type에 동일하게, 인식된5h window의 정확한 finite numeric 0%(bool 제외)만
absent/null reset을 idle로 허용한다. 정제 private `nextResetTime=null`은 미상·미활성으로
보존하며 reset 시각을 만들거나 갱신하지 않는다. 비영 사용량의 누락 reset 및 존재하는 잘못된
reset은 거부한다. weekly unit=6/number=1은0%라도 미래 reset을 요구한다. weekly나
CREDIT_LIMIT 존재를 강제하지 않는다. envelope success/code가 있으면 각각 정확히 true/정수200을
요구한다. HTTP/응답 실패·model limit 부재·TIME_LIMIT 단독을 idle0%로 바꾸지 않는다.
중복·미지원 window·잘못된 reset은 거부한다. 반환된 모델 window 하나라도 percentage>=80이면
pause한다. 이는 개발용 명목 20% admission 여유이며 진행 중 소비까지 보장하지 않는다.
과거 1% 관측을 재사용하거나 credit 가격을 하드코딩하지 않는다. 이 budget/quota gate는
자동 탐색에만 적용하며 사람 승인 후 execute를 막거나 승인 권한을 만들지 않는다.

### 오전 보고·journal·전송 복구

보고 window는 `[전날 09:00, 당일 09:00)` KST다. 09:00 이후 첫 tick에서 현재
source/scope/discovery/loop/local/agent/workflow config fingerprints가 모두 일치하고 독립
검토가 완료된 최신 pool 하나를 선택한다. 완료시각, 동률이면 scan_id 내림차순이다.
09:00 정각 완료 review는 다음 window에 속한다. 여러 round의 후보를 섞지 않는다.
중복 ID를 제거한 최대 8개 중 priority high/medium/low 다음 exact ID 오름차순의 최대 3개를
기존 web-v1 카드로 투영한다. eligible만 우선하지 않으므로 rejected/needs_evidence도 표시될
수 있고 counts.eligible은 표시 밖을 포함한다. 긴 서술은 projection에서만 `…`로 줄인다.

보고 확정은 모델 admission보다 먼저이며 보고용 새 모델을 호출하지 않는다. 유효 review가
없으면 0카드 partial/failed로, window 밖 역할은 not_called로 사실대로 표시한다. 최신
review의 전체 provenance는 private reviewed_agents/reviewed_local_participation에 남긴다.
ADR0025에 따라 참여는 회차와 독립된 bounded durable history의 역할별 마지막 시도이며
완료/실패/무효화·새 round·재시작 뒤에도 유지한다. 옛날 참여를 오늘 전원 성공으로 표시하지 않는다. source/config 미준비 시도 storage와 lock이
가능하면 실패 이유를 담은 0카드 보고를 확정한다. storage/lock 실패는 확정을 지연할 수 있다.
date는 당일 KST, generated_at은 실제 확정 시각으로 같은 날짜를 만족한다.

`loop/publications/<date>.json`에 report/payload/digest/표시 limit를 `prepared`로 먼저 저장한
뒤 days/scans/proposals/web/latest를 materialize해 `publication_pending`으로 만든다.
중간 crash는 같은 journal 내용만 복구한다. 기존 day 충돌은 보존하며 자동 대체하지 않는다.
그날 확정은 불변이며 이후 hourly tick은 연구만 진행한다. catchup은 오늘 날짜 하나만,
과거 보고 대량 확정·모델 몰아호출은 없다.

실제 CLI tick은 deliver 기본값이며 두 state lock을 모두 해제한 뒤 기존
`improvements.deliver_report`를 호출한다. 별도 sender mutex가 callback과 수동 reconcile을
직렬화하고 callback은 자기 Store.lock을 잡으므로 lock 중첩으로 막히지 않는다. 전송 전에
`sending/attempt_id`와 delivery attempt를 저장한다. 기존 Sites POST→인증 GET의 날짜/schema/
canonical digest readback만 성공 증거다. delivery 성공 기록이 있으면 HTTP 없이 journal을
정산한다. 실패·중단·모호한 결과는 `publication_unknown`이며 자동 tick은 재전송하지 않는다.
메인이 실제 상태를 확인한 뒤 `publish --reconcile`로 같은 frozen digest만 명시 조정한다.
이것은 새 보고나 새 승인·실행 claim이 아니다. 외부 HTTP의 절대 exactly-once 도착을 보장하지
않으며 불변 날짜/digest와 receiver idempotency로 중복 내용을 막는다.

### freshness·승인·격리

ADR0025로 대체: source bytes/mode/존재 변화는 sealed snapshot 회차의 진행·pool·cursor를
유지한다. scope/ownership/config/provider/model/protocol 변경은 진행을 무효화하며 새
snapshot을 시작하되 실제 참여와 완료 review index를 보존한다. 과거 scan과 invalidated 사본은
보존한다. 호출 후 source와 loop/local을 포함한 control 의존성을 다시 확인한다.
review_complete는 snapshot 검토 완료이며 현재 source freshness나 승인 권한이 아니다.
proposal은 기존 ID/full digest와 scan provenance를 유지해
기존 status/approve/execute에서 사용할 수 있다. loop_dependencies digest를 추가
discovery_fingerprint로 proposal/서명 승인에 묶고 `_eligible/_fresh/_authorization`과 workflow
guard에서 비교한다. 동일 후보가 새 설정에서 재발견되어도 옛 승인이 재결합되지 않는다.
기존 human decisions/approvals/claims는 tick이 생성하거나 덮어쓰지 않는다.

로컬 HTTP는 숫자 loopback 127.0.0.1 또는 [::1]과 고정 path만 허용하고 DNS localhost·외부
host·0.0.0.0·userinfo/query/fragment·redirect·proxy를 거부한다. SSH/home/key/전체 repo
복사·도구·remote code를 제공하지 않는다. Linux에 MLX 의존성을 넣지 않는다. private 설정
0600과 digest는 private 경계에 남으며 public schema에 endpoint·비용·원문을 추가하지 않는다.

## 대안·선택 이유·한계

- 매 tick 전체 5역할 scan: 예산과 hourly 1회 호출 제한을 넘으므로 채택하지 않는다.
- 09:00 모델 호출로 보고 작성: 장애/지연에 보고가 종속되므로 완료 review를 재사용한다.
- 로컬 초안을 정식 제안으로 직접 승격: 실제 담당자 검토·독립 검토 경계를 잃으므로 거부한다.
- prompt/order 보강만 사용: 실제 추론에서 다시 승인 밖 edit_files를 관측하여 생성 단계 제약을 추가한다.
- 숫자 파일 ID/window evidence 합성: 실패한 실험이며 canonical 경로·원문 줄 번호 계약을 바꾸므로 채택하지 않는다.
- 실패 자동 재호출/다른 cloud balance: 예산·구독 선택을 우회하므로 거부한다.

단계별로 지속 가능한 의견 교환과 하루 한 보고를 분리한다. skip·quota 보류로 round는 9시간보다
길어질 수 있고 유효 review 부재의 partial/failed 보고가 정상적인 실패 표현이다. locks는 협력
프로세스를 직렬화하며 같은 OS 계정 탈취나 외부 편집 전체를 막는 VM/신원 경계는 아니다.
네이티브 schema는 요청 bytes와 서버의 제약 컴파일 비용을 늘린다. whole-line window가 작아질
수 있고 schema만으로 상한을 넘으면 no-call이다. 의미적 타당성과 승인 수용 기준은 완화하지 않는다.

## 운영·검증 상태와 문서 평가

정확한 명령·legacy cron 교체·상태/복구는 [improvements](../improvements.md), MLX와 서비스
운영은 [local-models](../local-models.md)에 둔다. 메인은 최종 새 Claude 의미검토·전체
make check·scoped apply 후 최종 adapter 실추론·서비스/private config 전환과 실제9단계 운영을
확인한다. 단일 hourly marked block·게임 jobs·명시 daily local storage·persistent NFS default를
보존한다. 메인 제공 기존 상태는 hourly wrapper 활성과2026-10-16 09:00 partial/제안0개 보고1회
전달이다. 확정 보고는 재생성하지 않으며 새 프로토콜의 운영/다음 아침 게시 성공과 구분한다.

메인 제공 과거 설치·서비스/터널 준비와 약19.54초 합성 소스 추론 성공은 이전 어댑터의 관측이다.
별도 mlx-vlm 0.7.8 네이티브 schema 프로토타입에서는 enum·integer 범위 준수와 canonical
후보/전달 window 검증 통과를 관측했다. 이는 서버 프로토콜의 호환 관측이며 최종 어댑터의
최종 bytes의 새 서버 실추론·회귀/전체 검증·실제 repository round의 성공이 아니다.
별도 특정 미검토 초안의 합성 HTTP 전체 경로 사전 관측도 같은 한계를 가지며 최종 변경 뒤
메인의 재확인이 필요하다. compiler 지원·null metadata·실제입력과 합성입력의 근거 수준은
위 local-models 문서의 관측을 따른다. 상세 관측은
[local-models](../local-models.md)에 두고 raw 응답은 복사하지 않는다.

prompt/order 수리 두 실행은 Claude 검토를 받았지만 실제 추론에서 다시 승인 밖 edit_files를
생성했고 full check 중 중단되어 모두 `applied=[]`다. 성공·완료로 표시하지 않는다. 기존 NFS
full check timeout이나 일부 검사 성공도 전체 성공 증거가 아니다. 현재 격리 모델 사본에
복원된 마지막 승인 범위 초안은 참고용이며 새 독립 검토·전체 검증이 필수다.
검증 사본은 parent가 NFS 원본 baseline과 같음을 재확인한 뒤 이동·재사용하는 준비 절차이며
검증 성공이나 local fallback이 아니다.
이번 worker는 검사·네트워크·Git·SSH·서비스·재위임·workflow를 실행하지 않는다.
실행기의 새 Claude 의미검토·전체 make check·두 umask077/022 권한 fixture 검증·scoped apply와
메인의 최종 어댑터 실제 추론·신규 서비스/private config 전환·실제 repository 첫9단계·다음 아침 게시가 대기다.
런타임 private config·서비스 전환은 메인이 검증 후 수행한다. 이 작업은 스케줄·ledger·이미
확정한 보고서·게임 cron을 편집하지 않는다. 기존 GitHub create_tree 자동승인 거부(명시 공개
동의 부족)는 역사적 기록으로 보존한다. 이번 직접 요청의 기존 Git 역할·검증된 앱 요청은
메인에게 인계하되 원격 baseline 불일치·명시 승인 거부 시 중단한다. 실제 CI/머지/정리 완료는
메인이 확인하며 worker가 게시 요청을 재실행하거나 공개 허가를 새로 얻지 않는다.

offline 회귀는 fake clock/runner/HTTP와 isolated temporary storage로 slot/restart/locks,
자정/09:00·legacy carry-in·reservation crash/정산·quota 두 형식·cursor/feedback·초안 실패·
fingerprint 변경·전송 unknown/동시 sender·기존 승인 불변식을 다룬다. runner의 기존
`harness/test_*.py` 수집으로 전체 make check에 포함되며 실행 결과는 별도 확인해야 한다.
네이티브 프로토콜의 오프라인 회귀 요구는 실제 window/schema 일치, 승인 밖·중복·잘못된 타입·
후보/benefit 양쪽 evidence 위반 거절, tampered/no schema의 no-transport, request byte 경계·
whole-line 선택·schema-only 초과 no-call, 서버가 schema를 무시한 응답 거절, 유효 canonical
후보·`empty_draft`, 단일 호출/no retry, v1 거절·v2/provider 이행·fingerprint 무효화,
loop specialist 독립 slot 진행과 진단 privacy다(ADR0025로 기대 교체). 이는 전체 make check의 요구 명세이며 실행 성공 기록이 아니다.

시작과 최종 자체 검토에서 문서 영향은 요청 계약·검증·책임·배포 이행 변경으로 판단했다.
이전21개 프로토콜 수리는 coordinator 단일 작업으로 이 ADR을 갱신했다. 이번32개 진행 보존
수리는 coordinator 작업 정확히 하나이며 주요 결정과 이행을 신규 ADR0025에 기록한다.
AGENTS·ADR index·모델 연결·운영·구조/격리/검증/워크플로 문서를 같은 계약으로 갱신한다.
파일별 이유는 [운영 인계](../improvements.md#이번-프로토콜-수리의-문서-영향)에 기록한다.
매 후속 review도 `documentation={status,files,reason}`을 새로 반환하고 최종 소스와 실제 수정
문서의 구조·계약·격리·검증·실패 복구·게시 설명을 의미적으로 평가한다. 앞선 updated·확장자
검사·문서 존재는 완전성 증거가 아니다. 필요한 문서가 승인 밖이면 정확한 경로와 기존 승인
파일에 귀속한 finding을 보고하며 범위를 넓히지 않고 메인이 새 실행을 준비한다.
