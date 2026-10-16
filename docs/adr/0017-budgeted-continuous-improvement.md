# 0017. 예산 우선의 시간별 연구와 불변 오전 보고 분리

- 상태: 제안(proposed), 사용자 직접 구현·읽기 전용 예약 요청에 따른 결정; 새 의미 검토·전체 검사·범위 반영·운영 검증 대기
- 기록일: 2026-10-16
- 대체 관계: [0015](0015-approval-gated-improvement-discovery.md)의 daily-only 예약·하루 한 scan/5회 호출·one-pass 정책만 대체한다. 개별 승인·claim·workflow·GitHub 권한은 유지한다. [0016](0016-bounded-private-improvement-text.md)의 private/public 서술·strict envelope 계약도 유지한다.

## 문맥

사용자는 매일 09:00 Asia/Seoul에 보고서를 한 번 게시하면서 다른 시간에는 앞선 의견을 이어
비판·보완하기를 직접 요청했다. 횟수보다 예산을 우선하며 GLM은 기존 Coding Lite 구독,
Claude 자동 탐색은 KST 하루 최대 US$1의 추정 ledger를 선택했다. 최신 결정은 항상 켜둘
Mac mini의 mlx-lm이 작은 소스 부분에서 탐색하고 기존 역할들이 검토하는 방식이다.
이번 구현 workflow의 모델 비용은 자동 탐색 ledger 밖의 별도 비용이다. 발견된 제안의
수정·승인·실행 권한은 추가되지 않는다.

## 결정

### 책임·유한 실행·범위

Python 3.8 `harness/improvement_loop.py`는 `tick/status/publish`와 durable state를,
`harness/local_model.py`는 표준라이브러리 HTTP와 작은 line window 검증만 담당한다.
`improvements.py`는 기존 private store·후보/승인·Sites 전달을, `improvement_report.py`는
순수 schema·fingerprint·web-v1 projection을 맡는다. 기존 역할/provider/model/effort/
compaction/auth/storage 설정을 바꾸지 않는다. MLX는 별도 로컬 초안 참여자다.

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
system 지시와 user JSON 데이터(`approved_files/sources/feedback`)를 분리한다.
후보와 benefit의 evidence 모두 실제 전달 범위 안이어야 한다. basename 추정·경로 보정·
전체 파일 열람 주장은 거부한다. edit_files/문서 대상은 owner의 승인 범위 안에서만 허용한다.
큰 파일은 owner별 durable `{file_index,line}` cursor로 순환하며 호출 실패에도 앞선 window를
자동 반복하지 않는다. 긴 single line은 `line_too_long`으로 명시 skip하며 slice하지 않는다.

로컬 실패·빈 초안·missing/empty/긴 줄 skip이면 다음 slot의 관련 specialist는
`local_draft_unavailable`로 미호출한다. skip도 한 hourly slot을 쓴다. 다른 owner 단계는 이어지고,
후보도 성공한 specialist pool도 없으면 reviewer도 보류한다. reviewer 단계가 실패/skip해도
다음 slot에 새 round를 시작한다. quota/budget 보류는 같은 단계를 다음 새 slot에서 다시
admission하며 실패한 호출을 같은 slot에서 재시도하지 않는다.

다음 round의 실제 local prompt에는 이전 정제 candidate의 issue/edit_files와 specialist 설명,
독립 `review.reason`을 전달한다. candidate_id와 draft_digest로 같은 초안에 대한 의견을 연결한다.
실패도 고정 reason으로 이어받고 feedback은 allowlist·redaction·bytes 상한을 적용한다.
완전한 요약이 안 들어가면 표시된 축약을 시도하고 전혀 담을 수 없으면 `feedback_cannot_fit`으로
보류한다. 원본 private 후보/검토는 자르지 않는다. 무제한 prompt/response 캐시는 없다.

private `local_participation`에는 `provider=mlx-lm`, 설정된 실제 model identity,
`stage=local_explorer`, owner_role, called/status/reason/read_windows/skipped_lines를 보존한다.
시도는 서버 수신·성공의 증거가 아니다. API alias는 `default_model`이며 preload identity는
메인이 별도 확인한다. local 초안을 eligible 제안이나 cloud specialist 성공으로 표시하지 않는다.
web-v1 agents에는 기존 coordinator/downloader/parser/django/reviewer 5역할의 실제 참여만 넣는다.

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
추가 legacy 활동도 한 번씩 반영하고 loop scan/projection은 제외한다. 불완전 과거 기록은
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
review의 전체 provenance는 private reviewed_agents/reviewed_local_participation에 남기되
옛날 참여를 오늘 전원 성공으로 표시하지 않는다. source/config 미준비 시도 storage와 lock이
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

모든 source의 bytes/mode/존재, scope와 위 config digest가 바뀌면 old pool/review/feedback과
cursor를 무효화하고 새 round를 시작한다. 과거 scan은 보존하고 invalidated 사본을 별도 기록한다.
호출 후에도 source와 다시 읽은 discovery/agent/workflow 의존성을 재확인한다. loop/local 설정은
해당 tick에 수용한 값을 사용하며 다음 tick과 승인 freshness에서 파일을 다시 읽는다.
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
- 실패 자동 재호출/다른 cloud balance: 예산·구독 선택을 우회하므로 거부한다.

단계별로 지속 가능한 의견 교환과 하루 한 보고를 분리한다. skip·quota 보류로 round는 9시간보다
길어질 수 있고 유효 review 부재의 partial/failed 보고가 정상적인 실패 표현이다. locks는 협력
프로세스를 직렬화하며 같은 OS 계정 탈취나 외부 편집 전체를 막는 VM/신원 경계는 아니다.

## 운영·검증 상태와 문서 평가

정확한 명령·legacy cron 교체·상태/복구는 [improvements](../improvements.md), MLX와 서비스
운영은 [local-models](../local-models.md)에 둔다. 메인은 최종 새 Claude 의미검토·전체
make check·scoped apply 후 실제 repository의 첫9단계 운영을 확인하며, 기존 private daily wrapper와
단일 marked block만 hourly tick으로 교체한다. 게임 jobs·명시 daily local storage·persistent
NFS default를 보존한다. 현재 기존 09:00 daily cron은 유지 중이며 새 의견 교환은 미가동이다.

메인 제공 관측으로 Mac 전용 venv·가중치·loopback launchd 서비스/Linux SSH tunnel의 설치·
재시작을 확인했고 새 adapter로 합성 소스 실제 추론도 성공했다(약19.54초·정확한 승인 경로와
줄 범위·후보1개). 실제 repository 첫9단계·새 예약·아침 게시 검증과는 구분한다.
이 worker는 검사·실모델·네트워크·Git·cron·재위임을 실행하지 않았다. 직전 timeout run의
applied=[]도 새 검토/검사 성공으로 사용하지 않는다. 직전 run1792078026182747557-b4f614은
8개 구현 작업·Claude 검토 뒤 NFS full check1800초 timeout으로 failed였고 원본 baseline·
운영·GitHub는 반영되지 않았다. doctor/downloader 성공과 남은 parser+harness 결과
3439 passed/63 failed/skip0(3502개)는 전체 check 성공이 아니며 Django/pipeline은 확인되지 않았다.
복원 초안도 새 검토/승인 증거가 아니다. 이번만 메인이 agent_timeout_seconds1800/
check_timeout_seconds3600/max_rounds3을 선택하고 저장소 workflow-config·NFS/temporary 정책·
다른 한도는 유지한다. 실행기의 새 Claude 의미검토/full check·두 umask077/022 권한 fixture 검증/
scoped apply·기존 Git 역할과 메인의 첫9단계/예약 활성화/GitHub 전달/보고 게시가 대기다. 기존 GitHub
create_tree 자동승인 거부(명시 공개 동의 부족)는 역사적 기록으로 보존한다. 이번 직접 요청의
기존 Git 역할·검증된 앱 요청은 메인에게 인계하되 원격 baseline 불일치·명시 승인 거부 시
중단한다. 이 worker가 그 요청을 재실행하거나 공개 허가를 새로 얻지는 않는다.

offline 회귀는 fake clock/runner/HTTP와 isolated temporary storage로 slot/restart/locks,
자정/09:00·legacy carry-in·reservation crash/정산·quota 두 형식·cursor/feedback·초안 실패·
fingerprint 변경·전송 unknown/동시 sender·기존 승인 불변식을 다룬다. runner의 기존
`harness/test_*.py` 수집으로 전체 make check에 포함되며 실행 결과는 별도 확인해야 한다.
매 review는 `documentation={status,files,reason}`을 필수로 반환하고 실제 수정된 승인 Markdown과
구조·권한·비용·운영 설명의 의미적 완전성을 평가한다. 확장자 검사·문서 존재는 그 증거가 아니다.
