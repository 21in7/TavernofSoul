# 개발 하네스 사용법

## 실패 복구 health의 parent 운영

기존 hourly wrapper는 tick 하나 그대로다. 정상 최종 save와 잠금/deadline 해제 뒤 별도 health를
자동 전송하며 정산된 역할 실패도 대상이다. 초기 config/storage/lock/bootstrap 실패·rollback·
`--no-deliver`·조회/publish-morning은 보내지 않는다. 별도 health_publication/outbox 결과는 원래
실패·ledger·frozen morning을 바꾸지 않는다. unknown/sending은 GET만 하며 자동 재POST하지 않는다.
qualified unattended 전송은 승인/실행 권한이 아니다. 수동 publish는 child/discovery/unattended를 거절한다.
parent만 기존 hourly 전용 명시 v1 local storage/report 선택과 private inbox origin/token을 유지한다.

```bash
python -m harness.improvement_health query
python -m harness.improvement_health publish
python -m harness.improvement_health publish --reconcile --digest FROZEN_HEALTH_DIGEST
```

query는 키/HTTP 없는 조회다. reconcile은 이전 outbox의 정확한 digest와 GET404 뒤에만 동일 POST를
허용한다. strict schema/digest/전체 GET 일치만 delivered다. 실패로 tick을 재실행하지 않는다.
[ADR0034](adr/0034-inspection-failure-recovery-and-health.md)의 계약/미관측 상태를 따른다.
worker는 실행하지 않으며 새 검토/full check·GLM probe와 Sites 구현/배포/readback은 parent 책임이다.

자동 검사 선택은 [ADR0031](adr/0031-change-scoped-automatic-validation.md)이 우선한다.
master push·PR·수동 CI와 핵심 회귀·수동 targets를 유지한다. 실제 CI/게시 검증은 parent 책임이다.

로컬 pytest 병렬/직렬 사용법·측정·격리·실패 의미는 [ADR0032](adr/0032-parallel-local-regressions.md)에 둔다.

잠금/진단·과거 수리 회귀는 [ADR0027](adr/0027-inspection-lock-isolation-and-diagnostics.md),
진행 보존은 [ADR0025](adr/0025-progress-preserving-improvement-reviews.md), Read/제안 보존은
[ADR0026](adr/0026-source-verified-retained-improvement-reports.md)에 둔다.
harness/test_*.py 수집·공유 offline guard를 유지한다. fake/Lab만 허용하며 모델·운영 storage·키·
네트워크·기본 검사 호출을 막는다. Lab 재사용 시 autouse fixture도 명시 import한다.
보존 resolver의 구성 오류·process/flock·source lock·signed claim replay는 해당 ADR를 따른다.

이번 test_improvement_loop는 실제 adapter→_call_role→tick→scan/slot/history/status/feedback의
고정 원인과 후보 field/rule, local 뒤 정규 cloud·후속 성공의 이전 실패 보존, identity/context/중단·
원문/위조 metadata 배제·legacy unknown·정산 crash 첫 실패·비용 보존을 명세한다.
저장된 local 실패의 복구/feedback·초안 digest·실제 종료 관측과 시계 rollback 회계의 구분도 다룬다.
Lab 조회/합성 승인 파일 helper는 반복만 줄이며 기존 assertion·offline guard를 유지한다.
기존 window/예산/quota·daily24/tick1·빈 pool reviewer·Read/provenance·제안 보존·frozen/public payload
회귀를 유지한다. 검사는 미실행이며 테스트 삭제/skip/상한/정책 완화로 해결하지 않는다.
전체 diff의 새 Claude 의미 검토·documentation 판단, GIT=1 full make check·scoped apply·기존 Git 역할과
parent 전용 게시/CI3/merge/cleanup·frozen digest/스케줄 독립 확인을 남긴다. 합성 명세는 실제 hourly 관측이 아니다.

[전체 설계](harness-design.md)·[ADR](adr/README.md)은 목표·책임·격리·검토·게시, 이 문서는 환경·명령을 다룬다.

2026-10-21 연구 진행 보존 수리는 [ADR0025](adr/0025-progress-preserving-improvement-reviews.md)와
[최신 인계](improvements.md#진행-보존-수리의-문서-영향과-실행기-인계)를 따른다. local 실패 뒤
specialist와 빈 pool reviewer의 정규 독립 slot, sealed 입력9단계와 stale 승인/execute 거부,
durable cloud 참여·09시 경계·legacy bounded 이행·snapshot 변조/crash no-call을 Lab engine→
Store 재개 경로의 합성 회귀로 작성했다. live source 읽기 불가와 control 무효화를 구분하며
current freshness를 snapshot review_complete로 대신하지 않는다. 작성·읽기 검토는 검사 통과가 아니다.
메인 제공 오늘09시 failed/0카드 보고는 불변 보존하며 복구 초안으로 고치지 않는다.

2026-10-19 현재 정책은 [ADR0021](adr/0021-local-work-and-result-archives.md)의 명시 v2 local
작업/검증 + remote terminal archive와 [ADR0022](adr/0022-documentation-only-validation.md)의
실제 최종 diff 기반 문서 검증이다. 아래 과거 실행별 NFS 유지 서술은 당시 기록이며 개발 작업의
active 저장 선택만 이번 사용자 요청으로 대체한다. daily/hourly·게임 cron·approval 기록과 기존
모델/역할/인증 설정은 유지한다. 실제 private 기본값 활성화는 코드 검토·검증 후 parent 책임이다.

모델·키 등록은 [모델 연결](agent-models.md), 배정→구현→검토→검증→반영은
[자동 작업](workflow.md)의 `make agent-workflow`를 따른다. `make agent-workflow-status`는 단계·실제 역할/모델,
`make agent-doctor`는 로컬 설정을 표시하며 실모델 요청은 `make agent-smoke`다.
[Jev 배정](triage.md)의 `make agent-triage-demo`는 키 없는 고정 응답, `make triage-smoke`는 실제 TypeSafe다.
오류 처리·필수 검증·키 격리와 오프라인 Node 테스트는 기본 `make check`에 포함한다.
Claude Code의 [Jev 압축](compaction.md)은 `make compaction-demo`로 고정 입력,
`make check-compaction-engine`으로 네이티브 훅 엔진, `make compaction-smoke`로 실제 API를 확인한다.

아래 명령은 일반 개발 환경의 사용법이다. 현재 문서·소스 준비 단계에서는 실행기가 전체
`make check`를 수행하며, 범위가 제한된 작업자는 검증이나 운영 명령을 실행하지 않는다.
일반 개발 환경에서는 저장소 루트에서 다음 명령을 실행한다.

```bash
make doctor
make check-downloader
make check-parser
make check-django
make check-pipeline
make check
make check-mysql-container
make check-browser-container
make check-live
make check-site-container
```

`make check`는 기본 오프라인 검증을 실행하고, 어느 하나라도 실패하면 0이 아닌 종료 코드를 반환한다.
MySQL과 Chromium은 각각 `make check-mysql-container`, `make check-browser-container`로 별도 실행한다.
CI workflow에는 오프라인(고정 실데이터 샘플 포함)·MySQL·브라우저 실행과 세 required final gate가
있다. prose-only complete diff는 docs 검증 증거로 gate를 실행하고 나머지는 기존 heavy 실행을
요구한다. 브랜치 보호 설정은 저장소 관리자 책임이며 이 파일만으로 설정되지 않는다.
각 검증은 새 프로세스에서 실행한다. 기존 데이터 다운로드·운영 적재·지역별 cron은 실행하지 않는다.

기존 공개 JSON의 계약 불일치는 `harness.release_repair`로 별도 새 디렉터리에서 조사·보정한다.
예를 들어 현재 지역의 unpack revision과 JSON 버전이 일치할 때 다음과 같이 준비한다.

```bash
PYTHONPATH=TavernofSoul:parser_tidy TavernofSoul/itos/3.8/bin/python -m harness.release_repair \
  --source TavernofSoul/JSON_ktos --destination /tmp/ktos-repaired-release \
  --project /home/ubuntu/TavernofSoul --region ktos
```

출력 디렉터리는 존재하지 않아야 한다. 보정은 원본 분모·ClassName으로 드롭을 다시 구성하고
전체 공통 계약을 검사한다. 운영 JSON·DB·prev·버전 CSV에는 쓰지 않는다.
공개 적용은 격리 적재·재적재·롤백 검증과 백업을 갖춘 별도 작업이다.
세부 호환 규칙과 단위는 [데이터 계약](data-contracts.md)을 따른다.

## Trusted-parent GitHub transport 검증과 운영

표준 parent 경로는 [workflow의 bridge 호출 예시](workflow.md#trusted-parent-bridge와-즉시-handoff)다.
`harness/git_bridge.js`를 make 시작 전에 읽어 eval하고, 기존 GitHub tools·private load/store·
`codex_app.attach_artifact` adapter·sleep/yield를 주입한다. 이미 시작한 exec 결과도 handoff가
짧은 poll로 추적한다. 실제 awaiting_github 준비가 끝난 같은 async 흐름에서 request를 시작하며
도구 없는 단독 make, read-only/demo/GIT=0·변경 없음·실패·불명 summary는 자동 게시하지 않는다.

`python3 -m harness.git_transport request --run-id EXACT_RUN`과
`accept --run-id EXACT_RUN --request-id EXACT_ID --stdin-base64`는 trusted-parent 전용이다.
accept의 stdout READY 이후2048문자 이하 base64 줄·dot 종료 줄을 stdin으로 보낸다.
bridge가 no-echo PTY와 write_stdin을 처리한다. 원응답을 shell command/argv에 넣지 않는다.
응답은 decoded8MiB·UTF-8 JSON 상한이며 run 안의 owned0700/0600/nlink=1 파일에 fsync한 뒤
실제 native main 전체로 검사한다. scope/hash/mode/origin/approval/CI/lock과 journal schema는 유지한다.
native stdout·코드·error/status·poll·completion/archive를 private durable 결과로 보존한다.
일반 accept는 shell 한 번으로 다음 요청까지 읽는다. 32KiB 이하 inline이며 전체 결과32MiB 한도다.
초과만 `chunk --run-id EXACT_RUN --operation-id RECEIPT_DIGEST --index N`으로12288byte씩
읽어 정확한 offset/size/hash를 확인한다. 임의 파일 읽기·잘림 복구용 request 재발급은 없다.

receipt는 native 전에 시작하며 중복·변경 응답·stale ID·symlink/hardlink·잘못된 private mode/
owner와 interruption을 거부한다. inflight 또는 complete receipt와 native pending 불일치는
parent reconciliation이다. private saved response/native journal/실제 connector 결과를 확인한 뒤
옛 `agent-git-accept`/resume/cleanup CLI를 명시 사용한다. receipt 삭제·state key 교체로 쓰기를
재전송하지 않는다. awaiting_ci는 기존 resume, archive pending은 기존 archive-only 재개다.
merged 응답만으로 완료하지 않고 cleanup proof와 archive 결과까지 보존한다. PR은 관측 직후 연결한다.

`harness/test_git_transport.py`는 native seam 및 기존 publisher prepared fixture를 명시 재사용하고,
`harness/test_git_bridge.py`는 Python wrapper에서 Node fake 도구로 같은 JS를 실행하도록 작성했다.
실제 저장소/credential/네트워크 대신 임시 fixture를 쓰며 Node 부재는 skip이 아닌 실패다.
private permission/fsync/digest·UTF-8/stdin·단일 accept·실제 native gate·v1/v2·중단/중복·
chunk/readback/잘림·handoff·정확한 도구 인자·ID-before-dispatch·same-ID 오류·poll·artifact·
native 실패/cleanup/archive 보존을 parent가 확인한다. 기존 publisher 회귀를 대체하지 않는다.
이번 harness 변경 자체는 full `make check` 필수이며 worker는 테스트를 작성만 하고 실행하지 않았다.
parent가 실제 bridge 사용·구현 PR·별도 문서 PR의 required CI·merge·cleanup/archive와 PR54
동일 구간 시간을 관측한다. [ADR0024](adr/0024-immediate-batched-github-transport.md)의 baseline은
parent 제공 관측이며 synthetic 순서 검증·부분 probe를 실제 PR 성능 개선으로 쓰지 않는다.

## 승인 대기 시간별 연구와 오전 보고

승인된 제안이 GitHub CI 3종·merge·cleanup을 모두 마치면 parent의 기존
request/accept/resume/cleanup CLI가 lock 해제 후 같은 run의 완료 전달을 자동 호출한다.
일반 run에 signed claim이 없으면 credential/HTTP 없는 no-op이다. 전달 상태는 CLI의 별도
`completion` 결과이며 실패해도 workflow passed·merge SHA·cleanup 성공은 유지한다.
`make agent-improve-completion RUN_ID=...`은 그 run의 전달만 다시 확인한다.
unknown/sending은 GET만 하며, `RECONCILE=1`은 GET absent 확인 뒤 동일 frozen digest POST를
허용한다. conflict는 재시도하지 않고 delivered는 HTTP를 반복하지 않는다. 모델·승인·execute·
commit/PR/merge·cron/tick을 시작하지 않는다. 기존과 동일한 storage 환경을 명시해야 하며
선택된 root에 run이 없으면 local fallback 없이 차단한다. child/discovery/unattended,
read_only/simulated/GIT=0/local-only에서는 보내지 않는다.
정확한 completion-v1 계약·private outbox·실패 복구는 [운영 문서](improvements.md#승인-제안-자동-완료-전달),
결정은 [ADR0020](adr/0020-automatic-proposal-completion.md)을 따른다.
`harness/test_improvement_completion.py`는 기존 `harness/test_*.py` 수집으로 full `make check`에
포함된다. 실행기는 기존 GitHub 회귀와 함께 검증한다. 이 구현 작업에서 worker는 검사나 실제
HTTP를 실행하지 않았으며 Sites API/UI 구현·배포는 메인이 별도로 담당한다.

계약·정확한 scheduler 교체·실패 복구는 [improvements](improvements.md), 로컬 준비와
서비스 운영은 [local-models](local-models.md)를 따른다. [ADR0015](adr/0015-approval-gated-improvement-discovery.md)의
개별 승인/claim 권한은 유지하고 [ADR0017](adr/0017-budgeted-continuous-improvement.md)이
기존 daily-only/하루5회/one-pass 정책을 bounded hourly 연구로 대체한다. 기존 역할/model/auth/
compaction을 유지하고 Python3.8 표준라이브러리 MLX HTTP adapter만 별도로 추가한다.
Linux requirements에 MLX를 넣지 않는다. 아래는 메인/신뢰한 운영자용이며 worker는 실행하지 않는다.

```bash
# 기존 daily용 명시 local storage를 tick/status/publish에 동일하게 사용한다.
HARNESS_STORAGE_CONFIG=/ABS/REPO/logs/harness/improvement-storage.json make agent-improve-tick PYTHON=/ABS/VENV/bin/python
HARNESS_STORAGE_CONFIG=/ABS/REPO/logs/harness/improvement-storage.json make agent-improve-loop-status PYTHON=/ABS/VENV/bin/python
HARNESS_STORAGE_CONFIG=/ABS/REPO/logs/harness/improvement-storage.json make agent-improve-publish PYTHON=/ABS/VENV/bin/python
# 전송 unknown의 실제 상태 확인 후에만 같은 frozen digest를 명시 조정
HARNESS_STORAGE_CONFIG=/ABS/REPO/logs/harness/improvement-storage.json make agent-improve-publish PYTHON=/ABS/VENV/bin/python RECONCILE=1

make agent-improve-status PYTHON=/ABS/VENV/bin/python DATE=2026-10-16
make agent-improve-approve PYTHON=/ABS/VENV/bin/python PROPOSAL_ID=IMP-0123456789abcdef INSTRUCTION_FILE=/ABS/PRIVATE/instruction.txt
make agent-improve-reject PYTHON=/ABS/VENV/bin/python PROPOSAL_ID=IMP-0123456789abcdef
make agent-improve-execute PYTHON=/ABS/VENV/bin/python PROPOSAL_ID=IMP-0123456789abcdef
```

보고/승인/실행도 메인이 선택한 동일 storage 환경을 붙여 사용한다. ID·날짜·경로는 실제 값이다.
instruction은 소유자 소유 nonsymlink·단일 hardlink·0600 UTF-8의 구체적 사용자 지시여야 한다.
한 ID씩 승인하며 LOCAL_ONLY=1은 승인 때만 선택한다. execute는 task/files override를 받지 않는다.
loop 제안의 source/scope/discovery/loop/local/agent/workflow config freshness와 independent
review·signed discovery_fingerprint·review_digest·만료·일회성 claim을 기존 API가 재검증한다.
rediscovery로 human state를 덮어쓰거나 옛 승인을 새 설정에 결합하지 않는다.

hourly tick은 local(coordinator)→coordinator→local(downloader)→downloader→local(parser)→parser→
local(django)→django→독립 Claude의9단계 중 하나만 진행하며 모델 최대1회·로컬 포함 하루24회다.
local은 owner 승인 파일의 작은 연속 numbered window만 받고 durable cursor로 순환한다.
긴 한 줄은 slice 없이 local만 skip하며 실패/빈 초안에도 관련 specialist를 정규 slot에 호출한다. 정식 후보는 기존
specialist가 소스 확인 후 만들고 다음 round의 실제 prompt에 정제 issue와 specialist/Claude
review.reason을 이어받는다. local 참여는 private에서 mlx-vlm/model/stage/owner_role로 구분한다.
web-v1 agents는 기존5역할만 담고 원문/endpoint/비용을 공개하지 않는다. 기존37개 읽기 scope를 늘리지 않는다.

로컬 프로토콜은 mlx-vlm0.7.8의 native response_format.json_schema(strict)와 top-level
enable_thinking=false다. 정확한 canonical 후보 전체 계약/최대2개/닫힌 객체와 owner 승인
edit_files enum·두 evidence의 실제 한 window 경로/원문 integer 범위를 강제한다. 요청 검증은
준비 입력 결합과 재구성한 canonical schema를 대조해 누락·완화·owner/scope/window/thinking
변조를 transport 전에 거절한다. schema 포함 request24576bytes로 whole-line을 고르고 고정
overhead 초과는 context_too_large no-call이다. uniqueItems 미지원으로 중복은 client가 검사한다.
공유 후보·실제 window 검증/독립 검토는 최종 권위이며 서버의 잘못된 후보도 거절한다.
assistant의 정확한 tool_calls:null/tool_call_id:null만 무동작 metadata이며 non-null과 다른
도구 필드는 거절한다. Linux Python3.8 표준라이브러리만 사용한다. 설정은 local-model-config-v2/
mlx-vlm, api_model==model인 상대 repository ID다. default_model/절대 모델 경로를 요청하지 않고
v1 mlx-lm을 config_invalid로 보류한다. digest 전환으로 기존 fingerprint·승인을 재사용하지 못한다.
설치·모델 연결·서비스/private config 전환·실추론은 메인 책임이다. 상세는 [로컬 계약](local-models.md).

세 테스트 파일의 fake transport/clock/runner 회귀는 native schema/window·양쪽 evidence·편집 목록,
no-schema/tampering no-transport·byte 경계/whole-line/고정 overhead 초과·schema 무시 응답 거절,
유효 후보/empty_draft·단1회/no retry·v1/v2/provider/digest/fingerprint·skip/privacy를 다룬다.
worker는 실행하지 않으며 새 Claude 의미검토 뒤 전체 make check는 메인 하네스가 수행한다.
회귀 입력의 cursor는 전달 목록 순서와 실제 원문 줄 수에 맞춘다. 빈 feedback도 직렬화한 `[]`의
2bytes가 필요하므로 요청/schema 예산 경계 사례는 feedback 상한2bytes를 허용한다. 전달된
실패 지점을 검토해 이 입력들을 수정했으며 stale cursor·feedback 초과의 기존 거절은 유지한다.
이번 수정 후 검사 결과와 전체 make check 성공은 아직 확인하지 않았다.

한 slot claim을 먼저 남기고 모델 전 count/reservation/cursor/inflight를 atomic 저장한다.
Claude는 KST 하루 추정US$1·reviewer cap min(0.20, 잔액, 기존한도)로 CLI downward override를
사용한다. 성공 finite estimate만 정산하고 실패/unknown/중단은 예약 소비, 초과액은 기록 후
당일 중단이다. 일반 소진은 reviewer admission에서 판단한다. 그 차례 전 local/구독 역할은
다른 gate와 call cap 내 진행할 수 있지만 reviewer 예산 보류는 stage_index를 유지한다.
새 slot에서도 reviewer만 재판단하며 이후 local/구독 역할도 대기가 풀릴 때까지 호출하지 않는다.
09:00 보고 확정은 독립적이다.
CLI cap은 실청구 강제상한 보장이 아니며 구현 workflow 비용은 자동 탐색 ledger와 별도다.
GLM은 기존 Coding Lite 인증/endpoint를 유지하고 trusted parent의 bounded quota 조회에서
TOKENS_LIMIT/CREDIT_LIMIT의5h·있으면weekly percentage/reset을 검증한다. >=80%·unknown/
malformed/조회 실패는 GLM 보류로 명목20% 개발 여유를 남긴다. 두 model type 모두 인식된5h의
정확한 finite numeric0%(bool 제외)에만 absent/null reset을 idle로 허용하고 private null을 미상·
미활성으로 유지한다. weekly는0%라도 유효한 미래 reset을 요구한다. 비영 reset 누락·존재하는
잘못된 reset·실패 envelope는 계속 거부하며 TIME_LIMIT 단독·model limit 부재·HTTP 실패를0%로 해석하지 않는다.
quota/budget은 자동 탐색용이며 승인 실행에 적용하지 않는다. fallback/자동 retry는 없다.

기본 자정600초 전부터 모든 admission을 막고 clock rollback/cross-day는 보수적으로 양일
count/charge/중단한다. legacy 같은날 비용/호출은 scan_id로 중복 제거 carry-in하며 unknown을
0으로 간주하지 않는다. 같은 slot은 실패·재시작 후에도 재호출하지 않는다. storage/lock/runtime
실패는 paused이며 성공 scan이 아니다. tick의 설정 로드·Store 생성·readiness 준비 실패는
실제 경계별 bounded typed private 진단을 반환하며 모델·키 조회·보고 확정·publisher·
fallback을 실행하지 않는다. child/discovery 권한 거부는 이 처리 바깥에 유지하고 원문 예외를
노출하지 않는다. daemon/무한 polling은 없다.

09:00 이후 첫 tick은 이전09:00~현재09:00의 현재 fingerprint 일치 검증된 완료 회차의 ID별 최신 verdict로
모델 없이 오늘 보고를 불변 확정한다. 최대8 distinct 후보 중 priority/ID순 최대3카드 web-v1을
사용한다. 미완료는0카드 partial/failed이며 옛날 참여를 오늘 성공으로 표시하지 않는다.
기존 days/<date>.json은 보존하고 자동 재전달하지 않는다. catchup은 오늘 하나뿐이다.
prepared publication journal로 crash를 복구하고 CLI는 두 state lock 밖에서 deliver_report를
호출한다. sender mutex·sending attempt로 중복 callback을 막는다. unknown 전송은 자동 retry하지
않고 메인이 같은 digest만 명시 reconcile한다. 별도 publish cron은 없다.
status는 모델/키/quota 없이 한국어 추정 잔액·보류·다음 역할·마지막 검토·다음 보고·journal을
보여준다. 실시간 소스 freshness/실청구 잔액 확인은 아니다.

legacy make agent-improve/discover와 daily는 수동 호환으로 남지만 활성 cron에 병행하지 않는다.
loop state가 생기면 daily는 기존 day 재사용만 가능하고 delivery는 loop_managed로 넘긴다.
manual discover도 frozen day를 덮어쓰지 못한다. tick/publish targets는 unattended marker를
설정하며 approve/reject/execute와 일반 쓰기 workflow를 거부한다. 일반 READ_ONLY workflow는
checks를 수행하지만 자동 발견은 소스 수정·검사·Git·workflow·운영 파이프라인을 호출하지 않는다.

메인의 종전 서비스/터널 준비와 약19.54초 합성 추론은 이전 adapter 관측이다. native schema
서버의 compiler/null metadata·실제입력 prototype·미검토 초안 합성 관측은 [local-models](local-models.md)의
근거 수준으로 제한한다. 이번 최종 bytes의 실추론·전체 검증·실제 repository9단계 성공은 아니다.
메인 제공 기존 상태는 hourly wrapper 활성과 2026-10-16 09:00 partial/제안0개 보고1회 전달이며
확정 보고는 보존한다. 신규 서비스/private config 전환·최종 추론·새 검토/full check/scoped apply·
첫9단계·다음 아침 게시 확인은 메인/하네스의 후속 작업이다. NFS default·명시 daily local storage·
단일 hourly cron·예산/quota·승인·GitHub 정책을 유지하고 이 worker는 스케줄/ledger를 수정하지 않는다.
이 worker는 검사/실모델/네트워크/Git/cron/재위임하지 않았다. 실행기의 새 Claude 문서 의미검토·
전체 make check·두 umask077/022 권한 fixture 검증·범위 반영, 메인의 첫9단계/운영활성화/
GitHub 전달/아침 게시 확인은 각각 대기다. 직전 run1792078026182747557-b4f614은8개 구현 작업·
Claude 검토 뒤 NFS full check1800초 timeout으로 failed/applied=[]였다. doctor/downloader103개
성공과 parser+harness3439 passed/63 failed/skip0은 전체 check 성공이 아니고 Django/pipeline은
확인되지 않았다. 원본 baseline·운영·GitHub는 그대로이며 복원 초안도 검증 완료를 뜻하지 않는다.
종전 fixture 수리는 정상 local JSON Content-Type·한국어 후보·trusted-parent CLI 환경·독립 feedback/context 제한·
umask와 무관한 chmod0755 초기 상태를 fixture에서 바로잡되 production 검증은 유지한다.
당시 메인이 agent_timeout_seconds1800/check_timeout_seconds3600/max_rounds3을 선택하며
저장소 workflow-config·다른 한도·NFS/temporary 정책은 유지한다.
기존 공개 자동승인 거부 이력은 유지하며 이번 직접 요청은 기존 Git 역할/검증된 인계로 메인이
처리한다. baseline 불일치·명시 승인 거부 시 중단한다.

runner의 parser 그룹은 harness/test_*.py를 수집하므로 신규 adapter/loop·모델 예산·기존 승인
회귀가 전체 make check에 포함된다. pytest.ini는 이를 제외하지 않는다. fake clock/runner/HTTP와
임시 isolated storage만 사용한 경계 명세이며 이 worker가 실행한 검증이 아니다. 매 reviewer는
실제 수정된 Markdown과 구조/권한/비용/복구의 의미적 완전성을 documentation={status,files,reason}으로
평가한다. 확장자 검사나 문서 존재만으로 완료를 주장하지 않는다.

## IPF 추출기 명시적 준비와 재실행 역할

native 소스 `IPFUnpacker/src/ipf_unpack`과 Git ignore 대상인 설치 바이너리
`IPFUnpacker/ipf_unpack`은 별개다. 소스 수정이나 checkout만으로 설치 바이너리가
갱신되지는 않는다. 준비 담당자는 GCC, make, zlib 개발 헤더·라이브러리를 갖추고
IPFUnpacker submodule을 준비한 뒤 저장소 루트에서 명시적으로 빌드한다.
다음은 일반 개발 환경의 준비 명령이며 범위가 제한된 작업자는 실행하지 않는다.

```bash
git submodule update --init --recursive -- IPFUnpacker
make prepare-ipf-unpacker
```

`.PHONY`와 help에 등록하는 독립 타깃 `prepare-ipf-unpacker`의 내부 호출은 정확히 다음 하나다.

```make
$(MAKE) -C IPFUnpacker/src/ipf_unpack -B release
```

`-B release`로 강제 빌드하며 `IPFUnpacker/ipf_unpack`에 직접 링크한다.
`config=release`, `bin/Release` 산출물 가정이나 별도 install/copy를 사용하지 않는다.
실패는 호출자에게 전파하며 기본 doctor/check/downloader에서 자동 호출하지 않는다.
준비 타깃의 회귀 테스트는 `tmp_path`의 작은 합성 Make 프로젝트에서 `release`가
`../../ipf_unpack`을 생성하게 하여 강제 release 호출·정확한 설치 위치·실패 전파를 검증한다.
이 테스트에는 컴파일러나 실제 native 소스가 필요하지 않으며 실제 빌드 검증과 구분한다.

이번 strict IES CSV 게이트 호환성 수정의 승인된 읽기/변경 scope는
`downloader/downloader.py`, `downloader/tests/test_downloader.py`,
`docs/architecture.md`, `docs/harness.md`의 4개 파일이다.
각 작업자는 배정된 파일만 수정하며 기존 사용자 편집을 보존한다.
기존 역할·provider·model·sandbox 설정을 유지하고 추가 최적화는 하지 않는다.
원본 IPF·patch·unpack·JSON·Translation·버전을 보존하며 작업자는 직접 checks,
Git 명령·재위임·agent-run·harness.workflow, native 소스 열람·변경,
cron·다운로드·importAll 등 운영실행을 하지 않는다.

main의 공식 current407263 격리 입력 관측에서 실제 kTOS/iTOS/jTOS 전체 파서는 성공했으나
기존 게이트는 다른 지역에서도 사용하는 iTOS 드롭 표 153개를 거부했다.
모두 정확히 LF 한 바이트이며, 공식 암호화 IPF 엔트리에서 가져온 서로 다른 표본 3개는
크기·CRC32·SHA256으로 독립 확인되었다. 각 binary IES는 본문 없는 156바이트 헤더,
행 0개·열 0개였고 병합된 native 추출기는 종료 코드 0과 정확히 `b'\n'`을 출력했다.
이는 main이 제공한 형식 관측 사실이며 원본 바이트는 외부 모델에 제공하지 않았다.
합성 하네스의 게이트·재시도 검증, 실제 native 변환, 전체 지역 파싱은 각각 별개이며
이 관측으로 게임 엔진 동작·geometry 정확성까지 검증했다고 주장하지 않는다.

새 Claude 검토와 전체 `make check`는 오케스트레이터가, Git 작업은 git 역할이 담당한다.
main은 수정 후 세 전체 파싱에 사용한 기존 IES 경로 9239개 모두에 게이트를 재실행하여
오류 0개를 머지 전에 확인해야 한다. 이 수정 후 실데이터 게이트는 아직 통과로 기록하지 않는다.
main은 GitHub 앱 journal과 오프라인·MySQL·브라우저 CI 3개 성공 확인 후 머지하고,
신뢰한 parent의 자동 Git cleanup까지 이어간다. merge는 보존하며 cleanup complete 전 passed가 될 수 없다. 이 문서 변경 자체는 검증·검토·CI 성공이나 머지 완료의 증거가 아니다.

자동 정리 회귀는 [test_git_cleanup.py](../harness/test_git_cleanup.py)에 있다. 기존 parser check 그룹이
harness/test_*.py를 발견하므로 registry를 확장하지 않는다. 임시 Git 작업 저장소/bare origin에서 실제
fetch·lease 삭제·prune·ff-only·local ref 삭제, 승인 edit/add/delete/executable 변경, squash/이미 없음/재실행,
timeout·중단·권한 실패·사용자 편집·ignored collision·tip 경쟁과 완료 게이트를 확인한다.
새 repository/default_branch proof가 없거나 작업 브랜치가 현재 기본 브랜치인 경우도 삭제를 차단한다.
GitHub proof만 합성이며 전송/허용 origin은 Python test seam으로 주입한다. production URL 검증은 유지한다.
fixture는 --template= init 후 symbolic-ref로 master를 명시해 Git 2.25에서도 동작하도록 작성한다.
ignored collision 회귀는 빈 template에서도 exclude의 부모 디렉터리를 직접 준비한다.
잘못된 fetch mapping 회귀는 첫 fetch 전에 보류하고 remote/task tracking tip을 보존하는지 확인한다.
호스트 Git config/identity/auth/hooks/template과 외부망을 사용하지 않는다. worker는 회귀를 실행하지 않으며
실제 성공은 orchestrator의 full check와 PR/세 CI/merge/cleanup 확인으로 판단한다.
`make agent-git-resume RUN_ID=...`는 CI 또는 cleanup을 재개하고 `make agent-git-cleanup RUN_ID=...`는
merged run의 명시적 재확인이다. 단계별 private snapshot/checkpoint와 대상별 보류 이유·복구는
[workflow](workflow.md#머지-후-브랜치-정리), 완료·전송 정책은 [ADR 0010](adr/0010-automatic-post-merge-cleanup.md)에 둔다.

## Python 환경

Makefile은 `harness/.venv/bin/python`, 기존 `TavernofSoul/itos/3.8/bin/python`,
`python3` 순서로 기본 인터프리터를 선택한다. 직접 지정할 수도 있다.

```bash
make doctor PYTHON=/absolute/path/to/python
make check PYTHON=/absolute/path/to/python
```

새 체크아웃에서는 현재 프로젝트의 Python 3.8 실행 환경에 맞춘 별도 venv를 준비한다.
현재 의존성 버전은 `harness/requirements.txt`에 고정되어 있다.
하네스 환경 구성은 프로젝트 전체의 런타임 업그레이드를 의미하지 않는다.

```bash
python3.8 -m venv harness/.venv
harness/.venv/bin/python -m pip install -r harness/requirements.txt
make doctor
make check
```

기본 강화 계산기 DOM 검증에는 Node.js 18 이상이 필요하며 npm 패키지를 설치하지 않는다.
실제 브라우저 검증은 별도 Playwright SDK와 Node.js 20 이상을 사용한다.
CI는 Node.js 22를 별도로 준비한다.
`doctor`는 모듈 import, Python/Node.js 버전, 고정 입력과 설정 파일의 존재 여부를 확인한다.
자동 설치, 버전 CSV 초기화, 운영 DB 접속을 수행하지 않는다.
Make 없이 실행하려면 동일 인터프리터로 `python -m harness check`를 사용한다.

## 하네스 저장 경로 설정과 진단

`harness/storage.py`는 workflow·GitHub journal/cleanup·모델 보고서·triage·compaction·runner·
MySQL/Chromium wrapper가 사용하는 하나의 저장 정책이다. 설정 없는 checkout은 기존 로컬 동작을
유지한다. [전체 설계](harness-design.md#공유-저장-정책과-실패-경계),
[ADR 0011](adr/0011-configurable-harness-storage.md)과
[ADR0021](adr/0021-local-work-and-result-archives.md)은 격리·잠금·복구 경계를 설명한다.

설정 파일은 다음 순서로 **하나만** 선택하며 필드를 병합하지 않는다.

1. `HARNESS_STORAGE_CONFIG`가 설정되어 있으면 그 정규화된 절대 경로의 JSON을 사용한다.
2. 환경 변수가 없으면 `ROOT/logs/harness/storage-local.json`이 존재할 때 사용한다.
3. 그 선택적 파일도 없으면 기존 로컬 기본값을 사용한다.

`ROOT`는 명령이 대상으로 삼는 프로젝트 root다. 명시적 파일 누락, 빈/상대 환경 경로,
존재하는 설정의 잘못된 JSON·타입·version·중복/추가/누락 필드는 오류다. 선택적 파일이 **없을 때만**
기본값으로 돌아간다. 설정 오류·mount 부재·공간/권한 실패에는 로컬 fallback이 없다.
추적되는 [storage-config.json.example](../harness/storage-config.json.example)는 설명용이며 자동으로
활성화되지 않는다. 실제 설정은 Git 제외·보호된 logs 아래에 private 파일로 두고 모델 승인 소스에
넣지 않는다. 환경 override로 선택한 private 설정도 모델 입력으로 배정하지 않는다.

현재 tracked 예제는 명시 v2다. 다음 경로는 호스트 설정이 아닌 설명용이며 archive는 별도 mount다.

```json
{
  "version": 2,
  "artifacts": {"path": "/var/tmp/tavern/harness-artifacts", "required_mount": "/", "min_free_bytes": 10737418240},
  "temporary": {"path": "/var/tmp/tavern/harness-temporary", "required_mount": "/", "min_free_bytes": 10737418240},
  "archive": {"path": "/mnt/example-archive/tavern/results", "required_mount": "/mnt/example-archive", "min_free_bytes": 10737418240}
}
```

v2는 정확히 위 네 최상위 필드를 요구한다. artifacts/temporary와 프로젝트 work root는 실제
지원 로컬 filesystem이어야 한다. Linux fstatfs 양성 allowlist이며 NFS/CIFS·미지원/미상은
거부한다. v2 보고서 override도 로컬이고 artifacts의 하위여야 한다. active root의 lexical·
symlink·mount/floor/private/no-follow 정책을 유지한다. archive spec은 **파싱 시 lexical/type/
overlap만** 검사하며 NFS stat를 하지 않는다. archive의 실제 filesystem·mount·공간·소유자·
private·symlink 검사는 ARCHIVE에서만 수행한다. 미마운트 archive는 로컬 작업/승인/검증을 막지
않고 terminal 보관을 pending/non-success로 남긴다. 이하 일반 readiness/prepare/probe의 두
configured root는 artifacts와 temporary만 뜻하며 archive는 포함하지 않는다.

호환 유지하는 version 1의 완전한 JSON 예제는 다음과 같다. 자동 변환하지 않으며 옛 NFS 실행을
조회·재개할 때 원래 v1 설정을 명시 선택한다. 경로는 실제 호스트에 맞춰 변경해야 한다.

```json
{
  "version": 1,
  "artifacts": {
    "path": "/mnt/example-fast/tavern/harness-artifacts",
    "required_mount": "/mnt/example-fast",
    "min_free_bytes": 10737418240
  },
  "temporary": {
    "path": "/mnt/example-fast/tavern/harness-temporary",
    "required_mount": "/mnt/example-fast",
    "min_free_bytes": 10737418240
  }
}
```

최상위 필드는 정확히 `version`, `artifacts`, `temporary`이며 두 디렉터리 객체는 정확히 `path`,
`required_mount`, `min_free_bytes`를 갖는다. `version`은 정수 1, 공간 하한은 bool이 아닌 0 이상의
정수 byte 수다. 위의 10737418240은 10 GiB 예시이며 고정 호스트 기본값이 아니다.
경로는 절대·정규화 경로여야 하며 `~`/환경 변수 확장, `.`/`..`, 중복/끝 구분자, symlink를 사용하지
않는다. 두 application root는 서로 같거나 포함 관계일 수 없고, 저장소 내부·저장소 자체·저장소를
포함하는 상위 경로도 안 된다. 각 root는 자신의 `required_mount`의 엄격한 하위 디렉터리여야 하며
다른 required mount를 포함할 수 없다. 두 용도가 같은 mount를 공유하는 것은 허용한다.

| 용도 | 설정 없음 | 설정 있음, 보고서 override 없음 |
| --- | --- | --- |
| 일반 검증 보고서·로그 | `ROOT/logs/harness` | `artifacts.path` |
| 모델·triage·compaction 보고서 | 기존 `logs/harness/{agents,triage,compaction}` | `artifacts.path/{agents,triage,compaction}` |
| 새 workflow 사본·checks·backup·journal | `ROOT/logs/harness/workflows/<run_id>` | `artifacts.path/workflows/<run_id>` |
| 승인 모델 소스 context | `/tmp/tavern-model-context-*/sources` | `temporary.path/tavern-model-context-*/sources` |
| 비인증 검증 임시 작업 | 기존 `tempfile` 기본 동작 | `temporary.path`의 고유 private 디렉터리 |
| 프로젝트 직렬화 lock | `ROOT/logs/harness/workflows/.lock` | 같은 로컬 경로 |
| 인증 home·키·credential runtime | 기존 로컬/private 위치 | 같은 로컬/private 위치 |

보고서 위치는 명시적 `--report-dir` → `HARNESS_REPORT_DIR` → configured artifact/category →
호출자의 기존 로컬 기본값 순이다. override는 category를 자동으로 덧붙이지 않는 최종 보고서
디렉터리다. workflow와 GitHub CLI에는 `--report-dir`가 없으므로 `HARNESS_REPORT_DIR`를 사용한다.
override는 temporary root·인증 home·로컬 project lock을 바꾸거나 configured readiness를 우회하지
않는다. 절대 경로를 사용한다. 일반 검증과 컨테이너 wrapper의 예는 다음과 같다.

```bash
python -m harness check --report-dir /absolute/private/reports
HARNESS_REPORT_DIR=/absolute/private/reports make check-mysql-container
HARNESS_REPORT_DIR=/absolute/private/reports make check-browser-container
```

다음은 검토·full checks·GitHub 전달 **이후 main이 수행할 설정 절차**다. scoped worker가 실행하는
명령이 아니다. 기존 v1 설정을 별도 보존하고 새 v2 private 파일에 active 두 경로와 archive spec의
설명용 값을 편집한다. 기존 파일을 덮어쓰지 않는다. `python`은 Make의 `PYTHON`과 같은 하네스
인터프리터를 사용한다. 아래 명령은 active 준비만 확인하며 archive readiness 증거가 아니다.

```bash
mkdir -p logs/harness
(umask 077; cp -n harness/storage-config.json.example logs/harness/storage-local.json)
# logs/harness/storage-local.json의 설명용 경로와 하한을 먼저 편집한다.
make storage-status
make storage-doctor
python -m harness.storage resolve artifacts --prepare
make storage-doctor PROBE=1
```

별도 private 파일을 사용할 때는 `export HARNESS_STORAGE_CONFIG=/absolute/private/storage.json`으로
선택한다. CLI의 `--root /absolute/project`는 대상 프로젝트를 명시한다. 읽기 전용 명령은
`python -m harness.storage status`, `python -m harness.storage doctor`다. 경로만 얻으려면
`python -m harness.storage resolve workflows` 또는 `resolve reports --category agents`를 사용한다.
`resolve reports --report-dir /absolute/private/reports --prepare`는 명시적 출력 준비도 지원한다.
쉘에서 경로를 받을 때는 `report_dir="$(python -m harness.storage resolve reports --prepare)"`처럼
인용하고 결과를 `eval`하지 않는다. 저장 명령은 모델·Docker·운영 작업을 시작하지 않는다.

status/doctor는 effective artifact/temp/context/local lock과 로컬 credential runtime 경로,
각 configured mount의 readiness·free bytes·`min_free_bytes`·private 디렉터리 상태를 JSON으로
표시한다. 기본 조회는 mkdir/probe 없이 읽기만 한다. application이 아직 없을 때 `ready`여도
쓰기 가능성을 증명하지 않는다. local 모드의 `temp_root=null`은 기존 `tempfile` 기본 선택을 뜻한다.
설정/준비 실패는 0이 아닌 종료 코드와 고정된 유용한 오류를 반환하며 설정 원문·비밀값·임의 OS
오류를 출력하지 않는다. `doctor --probe`와 `PROBE=1`은 이미 존재하는 private application만
probe하며 두 root가 모두 존재해야 한다. CLI `status --probe`도 두 root를 각각 새로 검사한다.
실패 status도 각 spec의 `mount_ready`, 측정된 `free_bytes`(floor 미달 값 포함),
`min_free_bytes`를 보존한다. 공간 측정 실패의 `free_bytes`는 null이다. 기본
`status(probe=False)`는 mkdir·chmod·probe가 없는 조회이며 JSON schema와 반환 형태는 유지한다.

`resolve artifacts --prepare`와 `ensure_directory()`는 모든 prerequisites를 검사한 뒤 필요한
두 configured root를 만들고 **새 root와 실제 요청 목적지**를 probe한다. 목적지가 새 root
자체이면 출력 경계에서 한 번 probe한다. 기존의 무관한 root는 반복 probe하지 않지만 모든 쓰기
gate에서 그 root의 mount/floor/소유자/0700은 계속 검사한다. 임시 할당도 새 root와 실제 고유
작업 디렉터리를 probe한다. 부모 probe는 자식 writeability를 증명하지 않는다. 출력 자식과
configured mount 밖의 명시적 override도 자신의 private 목적지에서 새로 probe하며 실패를
부모나 다른 application의 성공으로 대신하지 않는다. 두 application의 종합 writeability 진단은
명시적 `prepare()` 또는 기존 두 root에 대한 `status/doctor --probe`로 수행한다.
`prepare(probe=False)`/`ensure_directory(probe=False)`는 필요한 디렉터리를 준비하되 probe를
하지 않고 안전 검사를 유지한다. 미설정 local 기본 동작도 유지한다.

모든 configured mount는 단순히 존재하는 디렉터리가 아니라 정확한 경로의 실제 mount여야 한다.
공간 하한은 각 required mount의 실제 free bytes와 비교한다. 모든 mount·공간·기존 application
mode를 mkdir/probe/출력 전에 확인하고 쓰기 경계마다 재확인한다. 출력까지의 symlink와 configured
mount 아래의 다른 nested mount를 거부한다. mount 부재 시 로컬 mountpoint 아래를 만들지 않는다.
한 읽기 전용 검사 경계 안에서만 shared mount의 공간 조회를 한 번으로 합치며 두 application의
floor를 각각 적용한다. 별도 mount는 각각 조회하고 경로/mount/private 검사는 생략하지 않는다.
다음 public 호출, mkdir 뒤 probe, 임시 할당 뒤 probe, cleanup의 진입과 최종 경계에는 새 측정을
요구한다. cache/TTL/probe 성공 lease를 두지 않는다. 올바르게 검증된 기존 디렉터리에는 불필요한
mkdir를 시도하지 않는다. 중간 mount/공간/권한 악화는 다음 쓰기 gate에서 fail closed한다.
application은 실행 사용자 소유의 `0700`, probe 파일은 고유 이름의 `0600`이며 실제
write·fsync·readback·delete를 수행한다. private JSON·이벤트·로그도 `0600`을 유지한다.
기존 application mode가 다르면 실패하며 mount root나 무관한 기존 디렉터리를 chmod하지 않는다.

실패 시 명령을 중단하고 올바른 mount의 복구, 해당 사용자 권한 또는 공간 하한을 확인한 뒤
doctor와 probe를 다시 수행한다. 설정을 지우거나 다른 로컬 디렉터리로 바꿔 실패를 자동 회피하지
않는다. 기존 디렉터리는 소유자·용도를 확인해 운영자가 복구하거나 별도의 private application을
선택한다. 공간 확보도 별도 승인된 운영 작업이며 cron·unpack·JSON·DB를 정리 대상으로 삼지 않는다.
MySQL/Chromium wrapper는 초기 status 쓰기와 Docker 시작 전에 저장 준비를 수행한다.
Docker 데이터베이스·운영 볼륨·컨테이너 tmpfs를 이 설정으로 이동하지 않는다.

runner의 비인증 검증 자식은 configured 임시 경로의 `HARNESS_WORK_DIR`, 자식 전용
`TMPDIR/TMP/TEMP`, pytest `--basetemp`를 사용한다. 부모의 전역 임시 환경은 바꾸지 않는다.
원본 구독 인증·키 home·실제 `HOME`/`CODEX_HOME`은 유지한다. 인증을 담은
`/tmp/tavern-codex-runtime-*`와 `ROOT/logs/harness/{agents,compaction}/runtime`은 로컬/private다.
보고서 override가 credential runtime을 NFS로 옮기지 않는다.

새 위치 활성화는 과거 실행을 이전하지 않는다. status/latest 및 Git request/accept/resume/cleanup은
현재 root와 기존 로컬 workflows를 함께 조회하고 duplicate run ID·symlink·탈출 경로를 거부한다.
과거 absolute workspace·승인 journal·snapshot은 재작성하지 않는다. 상세 lookup·재개·수동 복구
경계는 [workflow](workflow.md#저장-위치와-기존-실행-조회)를 따른다. v2의 새 terminal 결과 보관과
과거 기록 이관은 다르다. 자동 migration·역사적 산출물 삭제나 cron 등록은 없다. 옛 NFS run은
원래 v1 config를 `HARNESS_STORAGE_CONFIG`로 명시 선택하며 absolute journal을 재작성하지 않는다.
archive는 active journal의 대체/재개 근거나 status/find_run/progress 검색 대상이 아니다.
임시 context manager는 자신이 만든 고유 작업만 정리한다. private host 설정을 모델에게
제공하지 않으며 이 문서는 mount 확인·검토·검증·GitHub 전달 완료를 주장하지 않는다.
v2 활성화는 새 검토·검증 후 parent가 담당한다. mount options·floor·모델/provider와 GitHub
권한/lock을 약화하지 않는다. 기존 v1과 active probe 선택의 안전 근거는
[ADR 0018](adr/0018-storage-check-probe-deduplication.md)에 둔다. `test_storage.py`는 공유/별도
mount와 cold/warm 호출 수 및 장애 경계를 합성 FakeFS로 명세한다. 호출 수 감소는 실제 NFS
지연이나 전체 실행 시간의 보장이 아니며 fresh review/full offline 검증을 대신하지 않는다.

### 호출 소유 임시 tree의 cleanup 경계

`temporary_directory`의 고유 비인증 tree 제거는 한 고수준 filesystem 작업이다.
첫 chmod/unlink/rmdir 전 cleanup 진입과 최종 root 제거 직전에 모든 configured mount/floor의
readiness를 새로 확인한다. 이전 cleanup의 성공을 재사용하지 않는다. 각 destructive 작업에는
root·parent·ancestor·대상 attachment, ownership, no-follow, device와 kernel mount identity의
새 proof가 필요하다. global readiness 조회는 파일 수에 비례하지 않지만 이 proof는 계속 수행한다.
이 한계는 configured prerequisites의 mount readiness/free-space 조회에 적용하며, 항목별
mount-point 검사와 statx mount ID 호출 수를 제한하거나 캐시하는 정책은 아니다.
같은 device의 bind mount도 거부한다. readonly 소유 directory만 검증된 descriptor로 owner
접근을 복구하며 파일 chmod·외부 link target 접근은 하지 않는다. hardlink의 외부 bytes/mode도
보존한다. parent의 고정 owner는 legacy 공용 `/tmp`에서 다른 사용자일 수 있지만 바뀌면 실패하며
tree 내부는 모두 프로세스 소유여야 한다.

Linux statx `STATX_MNT_ID`를 얻지 못하는 libc/platform/kernel·오류/mask는 fail closed다.
device/ismount fallback이나 host mount 설정 열람은 없다. 최종 readiness 실패는 일부 제거된
tree를 남길 수 있으며 failure를 숨기지 않는다. workflow는 permanent 증거와 redacted
`model_context_cleanup`을 유지하고 non-success로 노출한다. report persistence 실패도 caller에
전달하며 local project lock을 해제한다. 상세/대안은 [ADR 0013](adr/0013-owned-validation-temporary-cleanup.md)에 둔다.

`harness/test_storage.py`의 counting-FakeFS는 여러 파일 수에서 cleanup readiness 경계가
2회이고 configured mount/free-byte 조회가 bounded인 반면 per-entry proof는 증가함을 확인해야
한다. 새 cleanup의 invalid readiness는 removal/chmod 0회, 최종 readiness 실패는 root 보존을
확인한다. readonly·exception·link/hardlink·swapped allocation/root/parent·foreign owner·device/
mount/bind mount·statx 실패 회귀를 보존한다. synthetic env/root는 host private config·실 NFS와
분리하며 기존 tests/제외를 유지하고 skip/xfail을 추가하지 않는다. worker는 실행하지 않는다.
계측은 allocation/create/probe 이후 cleanup 자체를 대상으로 한다. empty tree도 진입/최종
2회 readiness 경계를 요구하고 invalid 새 cleanup의 0회 mutation에는 `fchmod`도 포함한다.

이 변경의 매 orchestrator review는 `documentation={status,files,reason}`을 반환하며
`status=updated`는 실제 변경된 승인 Markdown 목록과 저장·격리·복구 설명의 의미적 판단으로
뒷받침한다. 파일 확장자 확인만으로 완전성을 증명하지 않는다. tests/full `make check`는
orchestrator, connector 게시·필수 CI 확인·merge·정확한 cleanup은 main이 담당한다.

### Terminal 결과 보관과 보관만 재개

workspace/checks/logs/backup/Git journal은 local active에 둔다. [ADR0021](adr/0021-local-work-and-result-archives.md#불변-payload와-원자-공개)의
allowlist만 `archive-payload/{bundle.tar.gz,inventory.json,manifest.json}`으로 freeze하고
`archive-frozen.json`에 고정한다. 가변 `archive-state.json`은 payload에서 제외한다.
owner0600/regular/nlink1·no-follow·안전 경로/attachment·bytes/hash와 개별64MiB/총256MiB를 요구한다.
정제 report/review·diff·Git/cleanup·검증 JSON/log만 포함한다. prepare는 바로 아래, checks-1~3은
command 아래 결과를 읽는다. workspace/.git/backup·model context/manifest/raw 응답·credential·
lock·private config/파생 storage-validation.json·승인 지시는 제외한다. 공개 전송은 추가하지 않는다.

원격 `archive.path/<workflows|checks>/<run_id>/`는 private0700 exclusive mkdir로 확보한다.
로컬 transfer receipt에 manifest·목적지/device/inode/mount·임시 token·published/committed를
고정한다. receipt 없는 기존 목적지는 빈 디렉터리/같은 bytes도 채택하지 않는다. mkdir→receipt
중단은 pending으로 보존한다. 게시한 파일 누락은 재생성하지 않고 committed 뒤는 읽기만 한다.
알려진 임시 파일에 최대1MiB씩 전송하며 fresh mount/floor/private/no-follow/attachment를 검증한다.
부분 파일은 frozen prefix가 같을 때만 append한다. fsync/no-replace link 뒤 임시 alias만 제거하며
동일 inode/bytes의 정확한 nlink2 전이만 복구한다. 제3 alias·unknown entry·충돌/변조는 거부한다.
전체 inventory/hash readback 뒤 **마지막 commit.json**을 게시하고 `verify_archive`가 네 파일·
marker exact bytes·0600/nlink1을 확인해야 완료다. marker/두 링크 전이 중에는 미완료이며
readback/state 저장 장애도 pending이다. 로컬만 directory no-replace rename을 사용한다.
NFS4 directory rename EINVAL·파일 link 성공과 후속 실제 저장/readback/hash/멱등 재개는
parent의 과거 관측이며 일반 pipeline 전체 성공이 아니다. rename fallback/unknown 삭제는 없다.

terminal passed/failed/interrupted/demonstrated만 지원하며 awaiting_github/awaiting_ci/
cleanup_pending 등 중간 Git 상태는 거부한다. workflow 최종 save/실행 잠금 해제 뒤, Git은
최종 save→project/GitHub 두 lock 해제→기존 completion hook 뒤 보관한다. GIT=0·실패도
성공으로 바꾸지 않는다. v2 standalone check*는 매번 새 artifacts/checks/run_id, workflow 자식은
파생 v1/child marker로 nested archive를 막는다. terminal report 전 실패는 완료 보장이 없다.

```bash
make archive-run RUN_ID=기존_run_id KIND=workflows
make archive-run RUN_ID=기존_standalone_run_id KIND=checks
# 같은 인터프리터·같은 선택 storage에서 동등한 CLI
python -m harness.archive --run-id 기존_run_id --kind workflows
```

일반 재개는 모델/검사/Git 없이 frozen/current inventory를 전송 전후 대조하며 변경 결과를
pending으로 거부한다. 옛 payload를 새 성공으로 쓰거나 원본/receipt/잠금을 지우지 않는다.
[ADR0028](adr/0028-resumed-run-result-archives.md)의 trusted-parent 명시 추가 보관은 다음과 같다.

```bash
python -m harness.archive --run-id 원래_run_id --kind workflows --resume-failed-to-passed
```

원래 검토/diff/검증 불변과 실제 Git merge/CI3/cleanup 증거를 대조해 failed→passed만 별도
고정 세대에 보관한다. private recovery.json이 이전 manifest/receipt와 현재 inventory를 결합한다.
동일 명령만 멱등 재개하며 결과 변경/unknown 전이는 pending이다. child/discovery는 storage 전
거부한다. CLI/환경은 인간 인증이 아니다. 추가 전송도 result allowlist만 사용한다. 최초 로컬/원격
보관은 읽기만 하며 status는 archive_original과 현재 archive를 구분한다. 로컬 status는 NFS의
현재 무결성을 증명하지 않는다. archived만 CLI0이며 pending은 nonzero, merge/cleanup proof는
유지한다. workspace/backup/journal/partial은 보존하고 owned 임시 context만 정리한다. floor를
낮추지 않는다. 새 Claude 의미 검토·GIT=1 full make check·scoped apply/Git/실제 보관은 parent 책임이다.

## 문서 전용 검증 선택과 지원 범위

workflow는 최종 baseline→candidate의 실제 bytes/POSIX mode/존재 변경을 새 review 뒤 분류한다.
일반 `README.md`, `docs/**/*.md`의 비실행 regular prose만 가능하고 `AGENTS.md` 이름과
`docs/workflow.md`, `docs/harness-design.md`는 정책으로 제외한다. 공통 설정/CI/Makefile·공통 계약·
mode/type/symlink·불명/빈/모호한 증거·비문서 rename은 full이다. 읽기 scope에 참조 코드가 있어도
실제 수정이 prose뿐이면 docs-only일 수 있다. repair마다 재판단하며 read_only/nochange의 반영·
게시 금지는 유지한다. 빈 변경은 docs-only가 아니다. 삭제/rename은 양쪽 경로와 남은 역참조를 검사한다.
로컬 변경 기록은 실제 POSIX permission 정수를 보존한다. 기존 0664/0640/0600 등 비실행·special bit
없는 regular 문서는 수정 전후 권한이 같으면 허용하며, 추가/삭제는 존재하는 쪽의 권한을 확인한다.
umask 002/022/077의 일반 문서 생성도 허용한다. 0600→0644를 포함한 실제 권한 변경과 잘못된 mode는
full이다. CI raw Git mode 문자열은 기존 100644 기준이며 로컬 권한을 Git mode로 정규화하지 않는다.

parent는 complete commit 범위 또는 신뢰한 최종 selection JSON을 제공한다. Git 범위 방식은
40자리 유효 SHA·non-shallow history·HEAD=head·깨끗한 tracked/untracked 증거를 요구한다.

```bash
make check-docs BASE=실제_40자리_base_SHA HEAD=실제_40자리_head_SHA
make check-docs CHANGES_FILE=/absolute/private/complete-selection.json
python -m harness.docs_check --base 실제_base_SHA --head 실제_head_SHA --report docs-result.json
```

Python 3.8 표준라이브러리 checker만 필요하며 docs 경로에는 game doctor·Node·MySQL·브라우저/full
suite를 요구하지 않는다. UTF-8/NUL/merge-conflict, 상대 파일/이미지와 inline/reference link,
ATX/Setext heading·한국어/중복 slug·URL encoding·fragment를 검사한다. inline code는 링크 검사에서
제외하고 heading 텍스트에는 반영한다. 같은 inline block에서 줄을 넘는 code도 정확히 같은 길이의
backtick run으로 닫고, code 밖의 escape와 code 안의 literal backslash를 구별한다. paragraph·heading·
fence 경계를 넘겨 마스킹하지 않으며 원문 줄 번호와 code 뒤의 실제 링크 검사를 유지한다.
fence/indented code 예제는 실행하지 않으며 외부 HTTP도 없다.
변경된 현재 문서는 전체 검사, 남은 README/AGENTS/docs는 변경·삭제/rename 대상의 역참조와 anchor
영향만 검사한다. 무관한 과거 링크 오류를 전가하지 않으며 잠재 영향이 모호하면 오류다.
symlink/hardlink·탈출/절대 경로·private/generated/hidden 경계는 거부한다. 공개 tracked
[.github/workflows/harness.yml](../.github/workflows/harness.yml) 링크는 명시 허용 예외로 credential
경계와 다르며 그 파일의 수정은 full이다.

완전한 CommonMark/HTML/MDX 엔진은 아니다. multiline label/destination·HTML link/image/comment·
custom anchor 등 모호한 문법은 unsupported 오류로 두며 skip/성공으로 바꾸지 않는다. 문서당
4 MiB 상한이며 fragment는 Markdown heading 대상으로 제한한다. Claude가 의미적 완전성을 검토한다.
`validation_selection`의 실제 변경과 digest, 각 결과 `validation_digest`, 마지막 성공 라운드의
`delivery_validation`을 최종 반영·게시까지 결합한다. 각 checks group은 positive selected와
passed==selected, zero skip/failure/error가 필수다. 빈·누락·과거 결과나 CLI 0만으로 통과하지 않는다.
실패는 정제 feedback으로 해당 task에 귀속하고 새 review/최종 diff 선택을 반복한다.

CI는 event JSON을 shell에 보간하지 않고 complete PR base→head 또는 master push before→after의
전체 raw diff를 분류한다. 작업 branch push는 자동 실행하지 않는다. ADR0023의 직접 호출용 새 branch
비교 구현은 보존한다. 불완전 history·dirty/untracked/head 불일치·빈/불명 증거·workflow_dispatch는
전체 실행이다. 별도 execution-plan.json은 docs/offline/mysql/browser/live 선택과 경로 근거를 보존한다.
세 required 이름 Offline harness (SQLite), MySQL harness, Chromium browser harness는 실제 final gate다.
각 gate는 전체 계획과 모든 실행/live 결과를 대조하고 선택된 success·미선택 skipped만 허용한다.
docs는 기존 selection equality·positive selected=passed·zero skip/failure/error를 유지한다.
누락/잘못된 계획·선택 실행의 실패/미실행은 gate 실패다. branch protection/권한/lock은 유지한다.

2026-10-20 publisher 연결 정정을 ADR0031의 부분 선택에 확장: pre-merge와 fresh cleanup의 `checks_gate`는 정확히
`Offline execution (SQLite)`, `MySQL execution`, `Chromium browser execution`의 completed/skipped만
예외 후보로 본다. 각 skip과 같은 SHA·GitHub Actions·동일한 유효 양의 정수 check_suite.id의
최신 이름별 selection completed/success, 세 required completed/success, 세 execution의 계획상 completed/success 또는 completed/skipped
전체를 요구한다. 전체 이름별 최신 selection/required도 success여야 하므로 다른 suite의 성공을
합치거나 오래된 성공으로 최신 failure/pending을 덮지 않는다. bool/문자열/0/null/누락·잘못된
suite는 증거가 아니다. 최신 selection/required success의 suite metadata가 불명이면 옛 정상
증거로 대신하지 않고 대기한다. skip 선도착 후 gates 누락·queued·in_progress이면 waiting_for_ci로
대기하고 증거 없이는 merge하지 않는다. required skip/neutral 등 non-success, 임의 job skip,
heavy failure/neutral/cancelled 등은 계속 실패이며 추가 pending도 기다린다. cleanup은 새 proof에
같은 조건을 요구하고 미완료·불명 proof는 정리를 막되 확정 merge SHA를 보존한다.
selection/suite 없는 기존 required-only 성공, full CI, 전체 pagination·head/test-merge 우선순위·
양쪽 commit statuses·최종 PR 재확인·정확한 cleanup 계약은 유지한다.
고정 응답 회귀의 작성은 실행 증거가 아니며 이번 연결 수리는 새 Claude 의미 검토·full make check·
실제 문서 검사와 parent의 GitHub 게시·세 required CI·merge·cleanup·archive 확인이 필요하다.

이번 harness/CI 구현은 docs-only 대상이 아니며 새 전체 `make check`가 필수다. 이전 run
`1792414748889186714-9305b2`는 coordinator CLI 900초 timeout, applied=[]였고 초안/테스트 정의는
성공 근거가 아니다. parent가 새 실제 Codex 작업·Claude 의미 검토·full check·CI·새 Git 전달 증거를
확보한다. 이 문서 작업자는 검사하지 않았으며 매 review의 documentation.updated에는 실제 변경
Markdown만 포함한다. 문서 완전성은 최종 코드와 원래 요청에 대한 독립 의미 검토로 남는다.

## 신규 서버의 로컬 운영 파일

Git에 추적하는 cron은 `cron_itos.sh.example`, `cron_jtos.sh.example`, `cron_ktos.sh.example`,
`cron_ktest.sh.example`, `cron_twtos.sh.example`이다. 실제 `cron_<region>.sh`와 지역 settings는
서버에 유지하는 로컬 운영 파일이다. 새 설치에서 원본 파일이 없는 경우에만 예제를 복사한다.
다음은 저장소 루트에서 kTOS 파일을 준비하는 예다. 다른 지역은 파일명의 `ktos`를 바꾼다.
아래 파일을 준비할 때는 `TAVERN_REGION=ktos`를 사용한다. 다른 지역도 설정 파일명과
환경 변수의 지역을 일치시킨다.

```bash
cp -n TavernofSoul/TavernofSoul/settings_region.py.example TavernofSoul/TavernofSoul/settings_ktos.py
cp -n cron_ktos.sh.example cron_ktos.sh
```

`cp -n`은 기존 파일을 덮어쓰지 않는다. **기존 운영 서버에서는 이 복사 단계 자체를 수행하지 않고,
기존 cron·settings를 복사하거나 덮어쓰지 않는다.** 새로 복사한 cron은 지역 흐름·실패 가드와
실행 권한을 유지하고 설치 경로·인터프리터·가상환경 경로를 새 서버에 맞춰 준비한다.
예제에는 기존 서버의 절대 경로가 있으므로 복사만으로 실행 환경이 준비되는 것은 아니다.
하네스 검증을 위해 운영 cron을 실행하거나 등록하지 않는다.

`settings_region.py.example`은 추적되는 `settings_common.py`를 가져온다.
다음 필수 환경 변수는 새 서버의 실행 환경에서 제공하며 개인 키·비밀번호·웹훅을
소스나 예제·로그에 기록하지 않는다.

| 환경 변수 | 설정 내용 |
| --- | --- |
| `TAVERN_REGION` | 복사한 설정 파일과 일치하는 `itos`, `jtos`, `ktos`, `ktest`, `twtos`, `test` 중 하나 |
| `TAVERN_DJANGO_SECRET_KEY` | 서버별 Django 비밀 키 |
| `TAVERN_ALLOWED_HOSTS` | 쉼표로 구분한 명시적 호스트명/IP; 스킴·포트·`*` 제외 |
| `TAVERN_DB_NAME`, `TAVERN_DB_USER`, `TAVERN_DB_PASSWORD` | 운영 MySQL DB명·사용자·비밀번호 |
| `TAVERN_DB_HOST`, `TAVERN_DB_PORT` | 운영 MySQL 호스트·포트 |

누락되거나 빈 필수 값은 설정 오류로 실패하며 임의의 DB·키로 대체하지 않는다.
`DEBUG=False`이고 `JSON_ROOT=BASE_DIR / ('JSON_' + REGION)`,
`CHANGES_DIR=BASE_DIR / 'changes' / REGION`, `STATIC_ROOT=BASE_DIR / 'staticfiles' / REGION`이다.
예제 설정을 읽는 것만으로 실제 DB에 접속하지 않는다.
Discord 알림을 사용하는 iTOS·jTOS·kTOS cron의 웹훅은 기존
`TAVERN_DISCORD_WEBHOOK_URL` 환경 변수 방식으로 제공한다.
필수 운영 환경 변수는 기본 오프라인 하네스에 필요하지 않다.

운영 INI·가상환경(5개 지역의 `3.8/`, `.venv/`, `venv/`)·`backups/`·빌드 파일의
Git 추적 제거는 디스크 삭제가 아니다. 기존 서버 파일을 보존하며 clone 후 가상환경과
의존성·운영 환경 설정을 별도로 준비해야 한다. 과거 Git 기록은 재작성하지 않는다.
`.gitignore`는 이미 추적 중인 파일의 추적을 해제하지 않는다. 현재 단계에서 ignore 규칙과
안전한 소스를 준비하고 실제 추적 해제는 서버 파일을 보존하는 별도 작업으로 진행한다.
`settings_common.py`, `settings_harness.py`, `settings_harness_mysql.py`, `*.example`,
`harness/pytest.ini`와 고정 fixture는 계속 추적해 새 체크아웃의 검증에 사용한다.

현재 공개 `origin/master` 작업 사본에는 원본 서버의 개인 설정·cron·가상환경이 제공되지 않았다.
이 단계는 안전한 소스와 예제 준비까지다. 보호 파일의 Git 추적 제거와 별도 IPFUnpacker 저장소의
빌드 ignore는 메인 `/root`의 별도 Git PR 범위다.
obsolete parsing-server CI 3개는 메인 `/root`가 로컬에 그대로 보관하면서 저장소별 private exclude로
제외할 예정이며 이 단계에서는 공개 workflow를 만들거나 수정하지 않는다.
전체 `make check`는 실행기가 수행한다. 현재 작업자는 테스트·cron·다운로더·운영 import·Git 명령을
실행하지 않으며 후속 검증·커밋·PR·CI 성공 확인·머지도 담당하지 않는다.

## 실행 범위

| 명령 | 검증 내용 |
| --- | --- |
| `check-downloader` | 로컬 암호화 revision·작은 IPF 대체 입력·IES CSV 검증 게이트·합성 Make 준비 타깃·실제 PAK 해제·변경 없음·전송/도구/검증/복사 실패·버전 보존·재시도·CLI 종료 코드·cron 중단 |
| `check-parser` | 실제 CSV IES·XML/TSV·Lua → 아이템·combat·맵/속성/버프·5개 지역·560/550 장비·젬 JSON, 공통 계약·공개 차단·수치·참조·재계산·재시도와 기존 회귀 |
| `check-django` | 기존 canonical ID·import 안전성·레시피 복구 테스트와 `Items.tests`의 SSR/fragment·조건·페이지·쿼리 수 검증 |
| `check-pipeline` | 원본 IES/Lua 및 고정 JSON → 실제 importer·ORM·HTTP, 5개 지역·560/550 장비·젬·추가 유형, 계약 차단·상태 보존·재적재·관계 삭제·롤백 후 재시도 |
| `doctor-mysql` | 명시적인 테스트 서버 접속, 제한된 계정 권한, 실제 서버 버전·SQL 모드·문자셋·격리 수준 확인 |
| `check-mysql` | 실제 MySQL migrations, 전체 고정 입력 통합 경로와 아이템 검색, MySQL 저장·검색·오류 롤백 검증 |
| `check-mysql-container` | 전용 MySQL 컨테이너 생성 → 계정 권한 제한 → `check-mysql` → 컨테이너 정리 |
| `doctor-browser` | 고정 Playwright SDK 버전, Node.js 버전, 실제 Chromium 실행 또는 전용 컨테이너 연결 |
| `check-browser` | 임시 원본 파싱·DB 적재·실제 Django HTTP/정적 파일 → Chromium 23개 시나리오 × 2 project, 총 46개 실행 |
| `check-browser-container` | 지원 Ubuntu의 ARM64/amd64 브라우저 컨테이너 → `check-browser` → 컨테이너 정리 |

`check-django`는 `parser_tidy/tests/`의 importer 회귀 세 파일을 별도 프로세스에서 실행한 뒤,
Django test runner로 `Items.tests`를 실행한다. 디렉터리 위치와 검증 책임이 다른 점을 구분한다.

## 격리와 결과

- 기본 런처는 `DJANGO_SETTINGS_MODULE=TavernofSoul.settings_harness`를 강제한다.
- `settings_harness.py`는 추적되는 `settings_common.py`를 가져오며 로컬 운영
  `settings_test.py`를 import하지 않는다. common은 공통 앱·미들웨어·템플릿 설정만 제공하고
  운영 DB·비밀값·지역 파일을 읽지 않는다. 하네스의 `REGION='ktos'`, 오프라인 전용 키,
  임시 JSON과 템플릿의 `harness.context_processors.offline` 재정의는 유지한다.
- 기본 하네스는 SQLite `:memory:`를 사용한다. MySQL 명령은 `settings_harness_mysql`을 강제한다.
  두 설정 모두 실제 migrations를 적용한다.
- JSON·미디어·캐시·메일은 하네스 환경으로 분리한다. 임시 JSON과 DB는 실행 후 정리된다.
- 기존 환경의 `PYTEST_ADDOPTS`/추가 plugin 설정을 제거하고 하네스 전용 pytest 설정을 사용한다.
- 선택된 pytest/Django 테스트의 skip, xfail, 테스트 미수집은 실패로 처리한다.
- `downloader/tests/test_downloader.py`와 `parser_tidy/tests/test_cron_guard.py`는 추적되는
  5개 지역의 `cron_<region>.sh.example`을 읽는다. 예제가 없으면 실패하며 로컬 운영 cron으로
  대체하지 않는다. 다운로드·import 반환 코드 가드만 분리해 검사하고 파서 실패 가드와
  지역 명령 순서를 확인하므로 전체 cron·다운로드·웹훅·운영 import는 실행하지 않는다.
- 결과는 공유 저장 정책이 선택한 private 보고서 디렉터리에 JSON으로 남는다.
  설정이 없으면 Git에서 제외된 `logs/harness/`, 설정이 있으면 artifact root를 사용한다.
  `doctor.json`, `downloader.json`, `parser.json`, `django-regressions.json`, `django.json`, `pipeline.json` 및
  실행 명령별 집계 파일에서 성공 수·실패·오류·skip·제외 목록을 확인한다.
- 같은 명령의 다음 실행은 해당 결과 파일을 갱신한다. 실패나 프로세스 종료가 이전 성공을 재사용하지 않는다.
- 각 검증의 전체 출력은 같은 디렉터리의 `.log`에 저장한다. 실패 시 터미널에도 출력한다.
- 보고서 위치를 바꾸려면 `python -m harness check --report-dir /absolute/private/reports`를 사용한다.
  전체 우선순위와 mount/권한 prerequisites는 위의 저장 경로 설정 절을 따른다.

## MySQL 검증과 CI

Docker에 접근할 수 있는 환경에서 다음 명령 하나로 실행한다.

```bash
make check-mysql-container
```

`harness/mysql.sh`는 digest로 고정한 공식 MySQL 8.4.11 이미지를 사용한다.
새 컨테이너 이름을 만들고 루프백의 임의 포트로 연결하며 DB 파일은 컨테이너의 tmpfs에 둔다.
기존 컨테이너·호스트 MySQL·운영 볼륨을 사용하지 않는다. 성공·실패·INT/TERM 종료 시 자신이 만든
컨테이너를 정리한다. 강제 종료나 Docker 장애로 정리를 못 한 경우는 예외다.
Docker 명령에 sudo가 필요한 환경에서는 `HARNESS_DOCKER='sudo -n docker'`를 지정할 수 있다.
최초 실행은 이미지 다운로드가 필요하며 다운로드한 이미지는 다음 실행에 재사용한다.

접속 계정은 `tavern_harness`, 연결 DB는 `tavern_harness`, Django가 생성·삭제할 DB는
`test_tavern_harness`로 고정한다. `harness/mysql-init.sql`은 **새 테스트 컨테이너 안에서만** 실행하고
이 계정에 두 스키마의 권한만 준다. SQL grant의 밑줄은 escape하여 다른 DB 이름과 매칭되지 않게 한다.
하네스는 접속 후 실제 권한을 검사하고 전역 권한·다른 스키마·role·GRANT OPTION이 있으면
테스트 DB를 만들기 전에 중단한다. 컨테이너의 root 계정은 권한 준비에만 사용한다.

이미 준비된 별도의 일회용 서버에서는 다음 환경 변수 네 개를 모두 지정한다.

```bash
export HARNESS_MYSQL_HOST=127.0.0.1
export HARNESS_MYSQL_PORT=13306  # 전용 컨테이너의 실제 매핑 포트
export HARNESS_MYSQL_USER=tavern_harness
export HARNESS_MYSQL_PASSWORD=harness-only
make doctor-mysql
make check-mysql
```

루프백 이외의 호스트·기본 3306 포트·다른 사용자·누락 설정을 거부한다.
계정 권한을 위 SQL대로 준비해야 하며 동시 실행은 서로 다른 컨테이너/포트를 사용한다.
서버가 없거나 인증·migration이 실패하면 실패 보고서를 남긴다. SQLite로 대체하거나 skip하지 않는다.
PyMySQL의 MySQL 8 인증에 필요한 `cryptography`도 하네스 의존성에 고정되어 있다.

세션은 `STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION`, InnoDB, utf8mb4, read committed를 사용하고
테스트 DB collation은 `utf8mb4_unicode_ci`다. `mysql.json`과 `mysql-doctor.json`에는
실제 서버 버전과 연결 조건을 기록하며 비밀번호는 기록하지 않는다.
`mysql-container.json`은 서버 준비 단계·종료 코드·컨테이너 정리 여부를 기록한다.
서버 시작 전에 실패해도 이전 성공 결과를 그대로 사용하지 않는다.
원본 fixture부터 ORM·HTTP·재적재·삭제·DB/Version/prev 롤백을 기존 통합 테스트로 다시 검사한다.
`harness/mysql_tests.py`는 다음 MySQL 전용 동작을 추가한다.

- migration이 만든 테이블의 InnoDB·문자셋·collation과 실제 테스트 스키마.
- 한글·4바이트 이모지 저장과 collation에 따른 대소문자/악센트 검색.
- 아이템 직업 필터의 실제 MySQL 정규식 조회.
- ListCharField 정수·좌표 저장, 원소 조회, null과 빈 배열 구분.
- 실제 FK 위반의 이전 변경 롤백.
- 유효한 JSON이 배열의 VARCHAR 저장 한도를 넘을 때 truncation 대신 DB 오류,
  DB·Version·prev 보존과 수정 후 재시도.

JSON 계약 전체에 MySQL 저장 길이 검사를 추가한 것은 아니다. 저장 한도 오류는 strict SQL에서 실패한다.
고정 fixture의 작은 경로를 검증하며 운영 서버의 버전·collation·설정이 같다고 가정하지 않는다.
전체 지역 데이터·모든 계산식·운영 DB 성능은 별도 검증이다.

`.github/workflows/harness.yml`은 master push·pull request·수동 실행에 대응한다.
새 Python 3.8 환경에서 선택된 SQLite 오프라인·독립 MySQL 서비스·Chromium 작업의 의존성을 설치하고 실행한다.
MySQL 작업도 같은 digest의 서버와 제한된 계정을 사용한다. 결과 JSON·로그는 성공/실패 모두
`harness-offline`, `harness-mysql`, `harness-browser` artifact로 14일 보관하며 실패 시 진단 자료도 수집한다.
기존 서버 구축 workflow·운영 배포·cron은 이 workflow의 실행 범위에 포함하지 않는다.

## 실제 브라우저 검증

Python 하네스 환경 외에 Node.js 20 이상(CI는 22)과 고정 SDK를 준비한다.

```bash
npm ci --prefix harness/browser --ignore-scripts --no-audit --no-fund
```

**Oracle Cloud ARM64·Ubuntu 20.04 헤드리스 서버**에서는 Chromium만 공식 Ubuntu 24.04 컨테이너로 실행한다.
화면이나 X 서버, 운영 OS 업그레이드, 호스트 브라우저 설치가 필요하지 않다.
기존 Docker를 이용하며 Python/Django/Node 테스트 런처는 호스트에서 실행한다.

```bash
make check-browser-container
# Docker 접근에 sudo가 필요한 경우:
HARNESS_DOCKER='sudo -n docker' make check-browser-container PYTHON=/absolute/path/to/python
```

`harness/browser.sh`는 Playwright 1.63.0과 일치하는 공식 이미지의 multiarch digest를 고정한다.
버전을 올릴 때 `package.json`·lockfile·`container-image.txt`를 함께 갱신한다.
호스트 SDK의 `node_modules`만 읽기 전용으로 마운트하며 프로젝트·운영 JSON·환경 파일·DB 볼륨을
컨테이너에 전달하지 않는다. 엔진 연결 포트는 `127.0.0.1`의 임의 포트로 공개한다.
Django도 루프백의 임의 포트를 사용하고, Playwright 연결은 그 테스트 포트만 컨테이너에 전달한다.
클라우드 인바운드 규칙이나 공개 웹서버 설정을 바꿀 필요가 없다.
성공·실패·INT/TERM 때 자신이 생성한 컨테이너를 제거한다. SIGKILL/Docker 장애는 정리 예외다.
이미지 다운로드가 최초 한 번 필요하며 이후 실행에서 재사용한다. Ubuntu 20.04의 native 실행은 명시적으로 실패한다.

지원되는 Ubuntu 22.04/24.04 등의 환경과 CI에서는 native 실행도 가능하다.
브라우저 시스템 의존성 설치는 해당 **개발/CI 환경에서만** 수행한다.

```bash
harness/browser/node_modules/.bin/playwright install --with-deps chromium
make doctor-browser
make check-browser
```

`StaticLiveServerTestCase`가 실제 migrations와 메모리 SQLite를 준비한다.
작은 iTOS 장비 원본을 실제 파서·JSON 출력·importer로 적재하고 실제 URL/view/template/정적 파일을 제공한다.
직접 `settings_test`나 운영 `manage_<region>`을 실행하지 않으며 외부 서버 URL을 인자로 받지 않는다.
고정 입력의 가상 아이콘은 임시 PNG로 제공한다. 다운로드한 실제 아이콘 자산의 호환성은 별도 범위다.
하네스 설정에만 추가한 context processor가 광고·동의 팝업·분석·외부 폰트를 제외한다.
일반 지역 설정에서는 기존 서비스가 유지된다. 브라우저의 예기치 않은 외부 요청·HTTP 오류·console 오류·JavaScript 예외는 실패다.

`harness/browser/manifest.json`은 desktop(1440×900)과 mobile(390×844)에 다음 23개
시나리오를 각각 요구한다. 총 46개의 정확한 scenario/project 조합이며, 좁은 화면 검색은
각 project에서 390×844·320×740, 새 상세는 mobile 안에서 두 폭을 확인한다.

- 검색어·등급 유지, 검색 결과에서 상세 이동, 모바일 메뉴 열기/닫기.
- 검색 결과가 없는 경우.
- 모바일 접근성·overflow.
- 부분 갱신·조건·페이지·history.
- 기본 링크 탐색.
- 취소·응답 역전.
- 오류·Retry focus/사용자 이동.
- popstate 실패 복구.
- JS 없는 GET.
- 560 무기 +5/+6/+30/0, 확률·재료·공격력 표시, 재료 링크 이동.
- 강화/초월 입력 순서, 음수/상한 입력 처리, 0 초기화와 비용 표시.
- 560 방어구의 물리/마법 방어력과 재료.
- 550 액세서리의 해당 강화 테이블과 재료.
- 일반 장비의 강화·초월 수치와 비용.
- 젬의 레벨별 5개 슬롯 보너스·음수 페널티.
- 스킬 젬에서 연결된 스킬 화면으로 이동.
- PvP 확률·레벨 경계 계산과 메뉴 연결.
- PvP 잘못된 입력과 접근 가능한 초기화.
- 상세 제목·본문·아이콘·열 배치와 overflow.
- 표 의미·키보드 스크롤·값 보존.
- 계산 입력·touch·focus·0 초기화.
- 재료·레시피·수집품·긴 링크 탐색.
- JS 없는 상세·능력치·링크·CSS 응답 순서 양방향·엄격 geometry poll.

수치는 hand-authored fixture 기대값이며 실제 게임 밸런스 값으로 주장하지 않는다.
필수 시나리오/viewport 누락·중복, skip/xfail, 재시도로 성공한 flaky 결과, 미수집은 성공으로 처리하지 않는다.
`harness/test_browser_runner.py`의 검색 9개·전체 23×2 게이트는 중복으로 누락을 채워도 거부한다.
`make check`에는 SDK/브라우저 설치를 요구하지 않고 빠른 Node DOM 검사와 브라우저 결과 판정의 회귀만 포함한다.

`doctor-browser.json`, `browser.json`, `check-browser.json`은 실제 엔진 버전·선택/통과 수를 기록한다.
`browser-container.json`에는 컨테이너 정리 여부, `.log`에는 엔진 로그를 남긴다.
`logs/harness/browser/<run-id>/`에 Playwright JSON·HTML 보고서와 검색/무기/젬/상세 스크린샷이 남으며,
실패 시 해당 화면의 스크린샷·`trace.zip`도 저장한다. 실행별 디렉터리로 이전 성공 자료와 구분한다.

```bash
harness/browser/node_modules/.bin/playwright show-report logs/harness/browser/<run-id>/html
harness/browser/node_modules/.bin/playwright show-trace logs/harness/browser/<run-id>/results/<test>/trace.zip
```

SSH 서버에서 자료를 로컬로 복사해 열 수 있다. 이 검증은 운영 도메인의 TLS/프록시/캐시/광고 동작이나
실제 모바일 기기·Firefox/WebKit·전체 페이지·5개 지역 브라우저 검증을 포함하지 않는다.

## 아이템 검색 계약의 격리 검증과 인계

Control 통과·`_blank` 표시·검증·실패 이력은 [ADR0029](adr/0029-item-search-progressive-enhancement.md)에 모은다.
수집은 `Items.tests.SearchQueryTests`·`EquipmentPipelineTests.test_source_to_http_<region>`이다.
parent는 최종 통합 diff의 새 Claude 의미 검토·유효 JSON·`documentation={status,files,reason}` 뒤
새 컨테이너의 `check-browser-container` 3회 연속 46/46·zero failure/error/skip/flaky/missing·`container_removed=true`·source fingerprint
불변을 확인하고 원래 `GIT=1` full `make check`를 실행한다. 동일 최종 bytes 검증 뒤
scoped apply·Git·새 PR·실제 CI3 success·squash merge·cleanup·archive로 잇는다.
실패 브라우저 JSON은 native 수리 피드백이며 full check를 대신하지 않는다. leaf는 실행하지 않는다.
상세 설계·실제 CI 실패·수리 인계는 [ADR0030](adr/0030-item-detail-mobile-layout.md)에 둔다.

## 실제 게임 데이터와 운영 도메인

`make check-live`는 기본 `make check`와 별도로 실행한다. iTOS·kTOS의 550/560 장비 6종,
젬 2종과 재료를 고정한 원본 스냅샷으로 실제 파서부터 임시 SQLite·ORM·HTTP·계산기 JS까지 검사한다.
입력 SHA-256과 unpack revision은 `live.json`에 함께 남는다. skip이나 누락은 성공으로 처리하지 않는다.
캡처/기대값 근거·선택하지 않은 범위는 [실데이터 샘플 안내](../harness/fixtures/live/README.md)를 참고한다.
CI의 `Offline harness (SQLite)` 작업은 `make check`와 `make check-live`가 모두 통과해야 성공한다.

운영 HTTPS·프록시·정적 파일·검색·560 계산기·젬/스킬 연결은 별도 명령으로 확인한다.

```bash
HARNESS_DOCKER='sudo -n docker' make check-site-container PYTHON=/absolute/path/to/python
# 지원 OS에 브라우저를 설치했다면:
make check-site
```

대상은 저장소에 명시된 iTOS·kTOS 공개 도메인 두 곳이다. 데스크톱/모바일에서 각각 4개,
총 16개 시나리오를 실제 Chromium으로 실행한다. TLS 인증서 오류를 무시하지 않으며 HSTS,
검색→상세, 실제 아이콘·jQuery 로드, 560 공격력·강화 입력/초기화, 젬 보너스·스킬 링크를 확인한다.
모든 브라우저 요청은 GET/HEAD만 허용한다. 로그인·운영 적재·DB 변경·배포는 수행하지 않는다.
광고 등 외부 HTTP 오류와 차단한 telemetry는 별도 관측으로 남기고, 자체 사이트 HTTP/네트워크 오류와
JavaScript 예외는 실패다. 외부 광고 서비스 전체의 정상 동작을 보증하는 검증은 아니다.
운영 도메인이 아직 새 계산기/젬 화면을 배포하지 않았다면 해당 시나리오는 실제 실패로 남는다.
고정 데이터 CI와 운영 smoke는 서로 대체하지 않는다. 운영 smoke는 merge 필수 CI에서 제외한다.

`check-site.json`·`site-container.json`, `site-<region>-engine.json`과
`logs/harness/site-<region>/<run-id>/`의 HTML/JSON·스크린샷·trace로 결과를 확인한다.
종료 후 전용 Chromium 컨테이너를 정리하며 운영 컨테이너나 볼륨에 접속하지 않는다.

## 기본 검증에서 의도적으로 제외한 기존 테스트

| 대상 | 이유 |
| --- | --- |
| `test_baseline_json.py` | 지역별 현재 JSON/unpack 출력에 의존하며 역사적 버그 상태를 재현하는 테스트도 포함 |
| `test_package_parser.py::TestKtosRegression` | 로컬 ktos unpack 데이터 필요 |
| `test_package_unresolved.py::TestKtosUnresolvedIntegration` | 로컬 ktos unpack 데이터 필요 |

위 두 클래스는 pytest의 명시적 deselect로 제외하며 개별 테스트 목록도 보고서에 기록한다.
제외는 기본 검증의 성공 근거에 포함되지 않는다. 다른 필수 테스트의 skip은 실패다.
기존 실데이터 검증이 필요하면 환경과 입력을 확인하고 별도로 실행·보고한다.

## 다음 구축 범위

1. 실제 지역 샘플로 schema/패치 차이 확대와 운영 MySQL 프로필 차이 확인.
2. 별도 승인한 운영/스테이징 URL의 읽기 전용 smoke, 지역별 브라우저 시나리오 확대.

SQLite/MySQL 고정 입력 통과는 운영 전체 데이터 호환성이나 모든 페이지의 브라우저 동작을 보장하지 않는다.

## 공통 데이터 계약

[데이터 계약](data-contracts.md)은 15개 importer 컬렉션과 버전의 필수 형식,
ID 중복·참조·수치 범위·단위 담당 단계와 기존 optional/sentinel을 설명한다.
파서 출력 전과 importer의 DB 쿼리 전에 같은 모듈이 검사한다.

`test_release_contract.py`는 실제 파서 출력에 작은 고정 JSON을 더해 누락·타입·중복·참조·범위를 검사한다.
메모리 또는 staging의 계약 오류는 공개 파일·버전을 보존한다.
`harness/contract_tests.py`는 실제 migrations·ORM을 사용해 스냅샷 검증·DB 쿼리 0개·비교 기준 보존,
재시도와 유효한 계약 이후의 적재 실패 롤백을 확인한다.
계약 전용 fixture는 고정 JSON이며 원본 파싱 coverage와 구분한다.
맵·속성·버프 원본은 world, 카드·컬렉션 원본은 regional fixture에서 따로 검사한다.
책·업적 계약의 현재 통합 입력은 고정 JSON이다.

### 최적화 회귀와 성능 근거

이번 31파일 importer/cleanup 수리의 현재 범위·근거·pending 상태는
[별도 인계 기록](#이번-importercleanup-수리의-후보-근거와-검증-대기)에 둔다.
아래 이전 최적화별 설명은 그 작업의 회귀 요구사항이며 이번 full validation 성공 기록이 아니다.

다음은 네 최적화의 검토·검사 요구사항이며 실행 성공 기록이 아니다. 작은 합성 입력과
직접 작성한 기대값을 사용하고 기존 임시 프로젝트 준비·전역 상태 복원 정책을 유지한다.

- `parser_tidy/tests/test_game_xml.py`: 금지 ASCII 제어문자가 없는 입력이 기존 masker를
  호출하지 않고 일반 노드·속성·text·tail과 `ET.ParseError`를 보존하는지 확인한다.
  제어문자가 있는 입력에는 기존 ScriptName 한정 허용과 문자참조·DTD marker 충돌 회귀를 유지한다.
- `parser_tidy/tests/test_release_contract.py`: 파일별 `load_json`의 유한성 검사 이후
  `load_release`의 전체 재순회만 제거하는지 확인한다. 보조·선택·version JSON까지 중복 키,
  NaN/Inf·지수 overflow·잘못된 root를 거부하고 도메인 오류의 path/code/message를 유지해야 한다.
  공개 `validate_release(data, require_version=True)`의 독립 메모리 검사는 엄격해야 하며
  검증 우회 flag를 노출하지 않는다. 파일·메모리 수정 후 재호출과 실패 복구 후 재시도를 포함한다.
  호출 횟수 계측은 fixture 준비가 끝난 뒤 대상 호출에만 적용하고 기존 함수로 복원한다.
  `test_atomic_release.py`와 함께 메모리 검사 후 쓰기, staging 검사 후 승급,
  백업·롤백·버전 보존 정책을 확인한다.
  scalar fast path는 정확한 내장 `str`·`int`·`bool`와 `None` 자식만 재귀를 생략하고,
  정확한 내장 float는 부모에서 `math.isfinite`로 검사한다. `is` 기반 판별과 기존 재귀·
  `isinstance` fallback이 dict/list/tuple/float 하위 클래스 및 알 수 없는 객체의 동작을 보존해야 한다.
  primitive 잎 옆의 중첩 실패와 scalar 루트·float 하위 클래스의 비유한 값,
  내장 scalar 타입과 같다고 주장하는 metaclass의 `__eq__`, 임의 크기 정수·bool·None·
  문자열 NaN/Infinity 허용을 기존 테스트와 추가 gap 회귀로 확인한다.
  dict 삽입 순서·배열 인덱스 순서에 따른 깊이 우선 첫 오류와 key repr·인덱스 표현,
  정확한 `ContractError` path/code/message/문자열·정상 반환값·원본 identity·alias를 검증한다.
  공유 컨테이너 identity 캐시·전역 결과 캐시·호출/build/지역 간 상태 없이 공개 메모리 API의
  mutation 재검사와 두 파일 API의 교체 후 재검사·수정 재시도·bytes 보존을 확인한다.
- `parser_tidy/tests/test_combat_source_fixture.py`: 비활성 스킬의 기존 순서·삭제 동작,
  원본 문자열/정수 ID 비교, 링크 순서와 남은 중복을 독립 기대값과 비교한다.
  공유 객체·별도 by_name 객체·alias에서 객체당 한 번의 링크 필터링, 비활성 0개일 때
  링크 목록 보존, 같은 객체·다른 지역·외부 수정 후 재호출을 확인한다.
- `parser_tidy/tests/test_world_source_fixture.py`: 맵/NPC/item 관계·좌표·인구·미해결 동작을
  유지하면서 필요한 호출마다 디렉터리를 한 번 조회하는지 계측한다. 빈 map 입력에서는
  디렉터리를 조회하지 않으며, 대소문자 충돌은 제공한 디렉터리 순서의 마지막 항목을 선택해야 한다.
  지역·원본 디렉터리 변경과 파일 수정 후 반복 호출에서 인덱스를 새로 만드는지도 확인한다.

범위가 제한된 worker는 검사·benchmark·운영 데이터 파이프라인·CI·Git·workflow를 실행하지 않는다.
실제 회귀와 전체 `make check`, 지역별 전체 실데이터 출력 및 누적 성능 비교는 메인
오케스트레이터가 담당한다. XML prototype 단계 시간, 단일 JSON 순회 표본, 합성 cleanup과
디렉터리 인덱스의 로컬 진단은 최종 구현 전체 파서·CI 통과나 누적 개선율의 근거가 아니다.
누적 성능은 같은 입력·환경·측정 범위의 기준 소스와 최종 소스를 비교하고,
출력 동등성·실행한 지역·반복 측정 여부를 함께 보고한다. 서로 다른 단계의 속도 배율을
곱하거나 서로 다른 실험의 절감 시간을 더해 전체 개선율로 제시하지 않는다.

메인이 제공한 current407263 kTOS JSON의 기존 finite-tree 순회 중앙값 2.985s와
scalar 재귀를 줄인 후보 1.392s는 private in-memory prototype 진단이다. 각각 세 표본이며
profiler를 사용하지 않았다. 이 문서 작업자는 원본 측정 로그를 받거나 재측정하지 않았다.
최종 구현 시간·전체 파서 성능·회귀 테스트 통과의 증거로 사용하지 않는다.

장비 계산의 row별 local callable 참조 재사용은 별도의 국소 최적화다.
`test_equipment_source_fixture.py`는 equipment fixture의 임시 복사본과 `isolated_parser_state`를
사용하여 실제 Lupa 호출을 직접 작성한 분수·0·음수 기대 배열과 비교한다. legacy ATK/DEF/양쪽/없음,
가격 fallback, 40단계·10단계 호출과 마지막 row 상태, default·타입·정밀도, 두 row의 RefreshScp 및
계산 함수 교체, 반복 parse와 새 runtime·지역 전환을 다룬다. 계산 실패의 공개 bytes 보존·재시도는
독립 수치 기대값과 함께 확인한다. `test_lua_module_loading.py`는 비활성 함수 누락·첫 사용 실패,
RefreshScp 원인 예외·초월 부분 상태, tooltip 변경 뒤 분기 재판정을 확인한다.
준비·init 이후 대상 parse에만 적용하는 lookup 계측은 `finally`에서 registry를 복원하고,
fixture 격리도 기존 전역 상태를 복원한다. 양쪽 분기의 조회 기대값은 RefreshScp → DEF 함수 →
선택한 price 함수 → ATK 함수 → 초월 함수이며, 실제 DEF → price → ATK → price의 40단계
호출 순서·결과 assertion은 유지한다. 조회 횟수 감소는 실측 속도 개선율을 대신하지 않는다.

이번 공유 `attr_getter` 변경은 여섯 정수 속성 이름의 immutable `frozenset` membership만
최적화한다. `test_lua_attribute_handlers.py`는 실제 Lupa와 독립적으로 작성한 기대값으로
여섯 속성 각각의 정수 변환·raw 행 보존, 다른 필드의 문자열·숫자·`None`·`False`·빈 문자열,
누락 값 `0`을 확인하도록 작성되어 있다. 부호·공백·밑줄·Unicode 숫자와
`7.0`·`1e2`·`0x10`·`NaN`·`+Inf`·`1e309`·잘못된 밑줄·NUL 등 변환 실패,
숫자 NaN/무한대의 기존 예외도 다룬다. 상수 집합이나 소스 텍스트 자체를 기대값으로 삼지 않는다.
Lua setter 뒤 재조회·Python mutation·독립 행·반복 `init()`의 runtime/registry 격리,
매핑의 `__contains__` → 존재 시 `__getitem__` 순서·dict 하위 클래스 override·예외의 재시도 없는
전파를 확인한다. ordinary 비문자열 직접 Python 이름과 비해시 이름용 cold fallback도 다루되,
임의 custom hash/equality의 호출 순서·부작용 동등성은 공개 Lua 프로토콜의 보장으로 주장하지 않는다.
기존 equipment/combat·지역 fixture 검증도 유지한다. 이 브리지는 여러 파서 도메인이 공유하므로
오케스트레이터/runner의 **전체 `make check`가 필수**이며 일부 parser 검사만으로 대체하지 않는다.
테스트 작성 상태는 통과 기록이 아니다.

제공된 private CPython 3.8 진단은 일반 문자열 이름으로 helper를 300만 번 호출한
microbenchmark 중앙값 목록 0.697s, immutable frozenset 0.618s다.
이는 후보 함수의 국소 측정이며 최종 구현·전체 파서·장비/몬스터 단계의 개선 증거가 아니다.
기존 callable 참조 재사용 측정에서도 일관된 개선이 없었으므로 별도의 성능 주장으로 재사용하지 않는다.

실행기·메인 `/root`는 변경 전후 current407263 kTOS/iTOS/jTOS 전체 `main`을 격리 사본에서
동일한 지역별 입력·환경·측정 범위로 맞춘 기준 소스와 최종 소스를 각각 fresh 전체 실데이터 파서
프로세스에서 profiler 없이 독립 반복 실행한다. 지역별 반복 횟수와 장비 단계·몬스터 단계·전체 파서의
전후 wall/CPU 시간 중앙값을 보고한다. 함수 microbenchmark나 warm runtime 재사용 측정으로
대체하지 않는다. 기존 입력의 지역별 JSON 41개 비교에 한정하지 않고 실제 출력 파일 목록의 동일성과
모든 지역 JSON 파일의 정확한 bytes를 확인한다. JSON scalar 변경은 반영한 최종 소스로 유한성 순회와 JSON 출력·검증의 전후 시간을
같은 입력·환경에서 별도로 측정하고, 전체 파서 시간과 측정 범위를 구분해 보고한다.
지역별 byte 비교는 직렬화된 모든 출력 파일과 version을 포함하며 JSON 객체의 의미 비교로 대체하지 않는다.
오케스트레이터의 전체 `make check`와 메인의 반영 후 최종 실데이터 시간·지역별 bytes 비교 결과가
확인되기 전에는 어떤 GitHub 게시 도구도 호출하지 않는다. 기본 `git` 역할은 부모 흐름에서 필수이며,
메인 `/root`가 `awaiting_github`의 앱 journal 게시·세 CI의 실제 success·SHA 고정 merge·자동 정리를 맡는다.
이 문단은 회귀·측정·인계 요구사항이며 성능 개선·검사·CI·머지 완료 기록이 아니다.

이번 이름 조회 변경의 회귀 실행·전체 `make check`·최종 지역별 장비/몬스터/전체 파서 시간 중앙값·
모든 JSON bytes 비교는 실제 결과가 제공되지 않아 **대기(pending)**다.
기존 역할·모델 설정을 유지한 reviewer/runner와 기본 `git` 역할에 인계하며 worker는 호출하지 않는다.
메인은 위 증거를 확인한 뒤 정확한 GitHub 앱 journal 요청, 오프라인·MySQL·브라우저 CI 세 개의
실제 success, 확정된 merge 및 자동 cleanup 완료까지 담당한다. 이 인계는 기존 게시 정책을 변경하지 않는다.

업무 시작과 매 검토에서 이번 국소 이름 조회의 문서 영향을 재평가한다. 이번 변경의 실제 갱신 문서는
`docs/architecture.md`와 `docs/harness.md`다. JSON schema·수치·직렬화·실패 복구를 유지하므로
`docs/data-contracts.md`는 변경하지 않는다. runtime/build/지역 격리와 역할·검증·게시 책임도 유지하므로
`docs/harness-design.md`·`docs/workflow.md`는 변경하지 않는다. 새 책임·계약·주요 정책 결정이 없고
ADR 0008의 JSON 검사 경계도 유지하므로 `docs/adr/README.md`·
`docs/adr/0008-json-validation-single-pass.md` 변경이나 새 ADR은 필요하지 않다.
모든 reviewer 보고는 `documentation={status,files,reason}`을 반환하고 실제 수정된 두 `.md` 경로와
이 생략 근거를 명시해야 한다. 추가로 필요한 문서 경로가 승인되지 않았다면 정확한 경로를 보고하고
기존 승인 파일에 finding을 귀속해 `changes_requested`와 `documentation.status=missing`으로 요청한다.
메인이 범위를 확인해 새 run을 준비하며 repair 라운드에서 읽기·편집 범위를 확장하지 않는다.

이번 scalar fast path의 문서 영향은 [데이터 계약](data-contracts.md)·[architecture](architecture.md)·
이 문서의 구현·회귀·측정 근거 설명이다. ADR 0008의 엄격한 파일별 디코딩·공개 메모리 검사·
도메인 검사와 별개의 직렬화 전/후 책임을 유지하므로 새 ADR이나 기존 결정 변경은 필요하지 않다.
오케스트레이터의 독립 의미 검토는 매번 `documentation={status,files,reason}`을 반환하고
ADR 변경 필요성도 판단해야 한다. 필요한 문서가 승인 범위 밖이면 정확한 누락 경로를 보고하고
기존 승인 파일에 finding을 귀속하여 수정 요청한다. 수정 라운드에서 범위를 자동 확장하지 않는다.
문서 형식 검사와 회귀 명세의 존재만으로 의미적 완전성이나 실행 성공을 주장하지 않는다.

## 파서 원본 검증

[아이템 fixture 안내](../harness/fixtures/parser/README.md)의 작은 입력 7개 아이템으로
실제 `items.parse`와 번역·Lua 계산·JSON 출력을 실행한다.
입력은 직접 작성한 CSV 형식 IES, XML/TSV, Lua이며 바이너리 IES나 운영 게임 계산식은 포함하지 않는다.
소수 무게, 쿨다운과 내구도 단위, 등급 기본값, 레시피 참조, 패키지 options·unresolved·랜덤 묶음,
장비 공격력·강화·초월 비용을 독립적으로 작성한 기대값과 비교한다.

같은 입력의 반복 실행은 JSON을 그대로 유지한다. IES 값과 공유 상수를 바꾸면 Lua 수치를 다시 계산한다.
잘못된 등급, 필수 fixture 누락, Lua 로드 실패는 성공으로 처리하지 않으며 공개 JSON·버전을 보존한다.
실행마다 임시 파일과 새 Lua 런타임을 사용해 파서 전역 상태가 다음 테스트에 섞이지 않도록 한다.

연결 검증은 같은 원본에서 실제 importer·ORM·HTTP 화면까지 실행한다.
재료와 레시피의 숫자 ID 충돌을 `recipe-100`으로 정규화하고,
원본 수치 변경이 기존 장비를 갱신하는지, 반복 적재가 관계를 중복 생성하지 않는지 확인한다.
DB의 `Version`은 고유 버전별 이력이다. 동일 버전 재적재는 이력을 추가하지 않고 새 버전은 추가한다.
오류로 파싱이 끝나지 않으면 이전 공개 파일과 DB·화면 데이터, 적재 비교 기준을 유지한다.

카드·젬·컬렉션, 전체 `main.py`, 바이너리 해제,
자산 생성, 소수 초 쿨다운의 DB 저장은 이 원본 fixture로 검증하지 않는다.

## 스킬·몬스터·드롭 원본 검증

[combat fixture 안내](../harness/fixtures/combat/README.md)의 입력을 아이템 샘플과 함께 읽는다.
직업·스킬트리 연결, 실제 Lua의 레벨별 계수·비율·쿨다운·자원 소비,
비활성 스킬 정리, 몬스터 Lua 수치와 지역 보정, 몬스터 스킬·드롭 관계를 검사한다.
드롭은 확률 퍼센트와 수량, 출처 지역·버전, 미해결 참조를 JSON에서 확인한다.
잘못된 원본 수치·직업 참조, 누락 입력·몬스터 Lua 함수는 공개 JSON·버전을 보존한다.

통합 검증은 스킬·몬스터 검색/상세와 아이템 드롭 역참조까지 실행한다.
비율 0.4는 파서에서 40으로 변환하고 DB에서도 40이다.
물리 공격력의 최소·최대와 EXP·JOBEXP를 서로 다른 값으로 검사한다.
타수·스킬 연결 변경, 드롭 삭제, 반복 적재와 DB 적재 실패 후 롤백·재시도를 포함한다.

이번 검증에서 importer의 몬스터 물리 공격력 최소·최대 역전과 타수 누락을 수정했다.
몬스터 스킬의 연결은 새 목록으로 교체해 제거된 연결이 남지 않도록 했고 상세 HTML도 실제 타수를 출력한다.
스킬의 지역 보충 데이터 경로는 코드 저장소 대신 입력 프로젝트에서 유도한다.
importer의 비교 대상 추가·변경 행에 수정이 적용되며 기존 운영 DB 보정 작업은 실행하지 않는다.

샘플은 iTOS의 작은 선택 범위다. 모든 지역·유형·게임 계산식·브라우저 JavaScript를 검증하지 않는다.
몬스터의 다른 유형과 statbase 헤더만 있는 입력은 해당 유형의 coverage에 포함하지 않는다.
맵 zonedrop/dropgroup과 속성·버프는 아래 world fixture에서 원본부터 검사한다.

## 맵·속성·버프 원본 검증

[world fixture 안내](../harness/fixtures/world/README.md)의 작은 CSV IES·XML/TSV를
아이템·combat 입력에 덧붙여 실제 운영 순서로 파싱한다.
지도 3개·NPC·몬스터/아이템 생성 위치, 직접 드롭·가중치 그룹·f_ 파일·특수 맵 비율,
속성의 기본/보충 스킬·직업 연결과 정리, 네 버프 파일의 수치·번역을 검사한다.
생성 시간은 초, 버프 지속 시간은 ms이고 좌표·병합 인구수는 독립적인 기대값과 비교한다.

잘못된 원본 수치·지도 연결·필수 fixture 누락·중복 관계는 공개 JSON과 버전을 보존한다.
반복 파싱과 같은 DB 객체에서 맵 연결을 재구성해도 생성점·층·미해결 참조가 중복되지 않는다.
같은 입력의 재적재는 데이터와 관계를 유지한다. 스킬 updated 감사 시각은 전진할 수 있다.

통합 검증은 실제 importer·ORM·맵/속성/버프 검색·상세·아이템 맵 역참조를 실행한다.
원본 변경 시 수치·연결 갱신과 삭제, 파싱 실패 시 DB 보존,
적재 도중 오류 시 DB·Version·prev 롤백과 수정 후 재시도를 검사한다.

이번 검증으로 보충 속성 연결의 숫자 ID/스킬 이름 혼용과 역참조 누락,
잘못된 최대 레벨·지도 연결의 예외 숨김, 특수 맵 드롭그룹의 비율,
맵 생성 관계 재구성 중복·1층 자기 참조와 요구 설명이 null인 속성 상세 오류를 수정했다.
새 parser 릴리스와 importer의 추가·변경 비교 대상에 적용되며 운영 DB 일괄 보정은 실행하지 않는다.

맵/속성/버프의 이 경로는 합성 iTOS 샘플이며 MySQL 명령에서도 실행한다.
전체 유형·지역·게임 데이터는 검증하지 않는다.
지도 PNG 생성·자르기와 브라우저 canvas, 속성의 미구현 Lua 비용/해금 계산은 포함하지 않는다.

## 지역별 원본 경로와 추가 유형

[regional fixture 안내](../harness/fixtures/regional/README.md)는 공통 소스에 다섯 지역의 입력을 덧붙인다.
운영 unpack을 복사한 데이터가 아니라 작은 합성 CSV IES·XML/TSV·Lua와 독립 기대값이다.
iTOS·jTOS·twTOS는 English/Japanese/Taiwanese 번역을, kTOS·kTest는 원문의 한국어를 사용한다.
동일 프로세스에서 지역을 바꾸고 재실행해도 이름·계수·Lua 상태가 섞이지 않는지 검사한다.

추가 원본은 마법 지팡이·방어구·카드·컬렉션이다. 실제 Lua로 물리·마법 공격력과 두 방어력,
강화 배열·보너스 floor·음수 보너스·내구도 sentinel·직업 제한을 확인한다.
카드 전투 수치는 JSON까지만 검사하며 카드 유형/이미지와 컬렉션 재료·보너스는 ORM·HTTP까지 확인한다.
지역별 이름·스킬 보충의 kTOS/kTest 우선순위와 iTOS의 외국어 설명 보충 제외,
iTOS/현재 지역 드롭 데이터셋 선택·행별 출처·revision도 검사한다.

파서 5지역 검증은 `test_regional_source_fixture.py`, 통합은 `harness/regional_tests.py`에서 실행한다.
SQLite와 MySQL 양쪽에서 각 지역의 검색·상세·재적재와 수치 갱신·관계 제거·카드 삭제를 검사한다.
번역/IES 누락·손상·Lua 오류는 공개 JSON/버전을 보존하고,
적재 도중 오류는 DB·Version·prev를 보존하며 수정 후 재시도한다.

이번 범위에서 명시된 장비 RefreshScp의 실패를 숨기던 동작을 수정했다.
해당 함수가 없거나 실행에 실패하면 장비와 함수 이름을 포함한 오류로 중단한다.
전체 운영 원본에서 모든 Lua 함수가 실행 가능한지는 이 작은 샘플의 검증 범위 밖이다.
드롭 소스가 양쪽 지역에 있을 때의 사유도 실제 iTOS 우선 선택을 설명하도록 수정했다.
fixture의 `.ipf` 디렉터리는 Git에 포함하며 필수 입력이 Git에서 제외되면 검증을 실패 처리한다.

## 560 여신 장비·550 장신구·젬 원본 검증

[equipment fixture 안내](../harness/fixtures/equipment/README.md)는 regional 입력에
강화 IES·실제 테스트용 Lua·젬 CSV/XML을 추가한다. 운영 데이터에서 생성한 입력은 아니다.
5개 지역에서 560 무기/방어구 기본 수치와 초월 비용, 550 장신구 정수 공격력,
일반 젬 보너스/페널티·합쳐진 슬롯·레벨 0 제외와 스킬 젬 ID 연결을 검사한다.

강화 목록에 560을 등록하고 등록된 IES를 Lua GetClassByType에도 제공한다.
560은 해당 파일이 있을 때만 armor/weapon 재료를 생성하며 acc 그룹은 생략한다.
560의 필수 함수 누락·빈 계산·잘못된 수량과 손상된 강화 IES는 공개 전에 중단한다.
미등록 강화 파일은 경고와 goddess_reinf_unregistered.json에 기록한다. 자동 등록하지 않는다.
550 장신구는 기존 acc 전용 구조를 유지하고 BasicAccAtk를 JSON 정수로 출력한다.

importAll은 Gems 스킬 FK와 레벨/슬롯별 소켓 보너스를 스킬 적재 뒤에 반영한다. Link_Skill의 누락/null은 연결 해제이며
잘못된 참조와 다른 ORM 유형 그룹과의 중복은 공통 계약에서 DB 쿼리 전에 차단한다.
재적재·관계 변경·분류 제거·젬 삭제·적재 도중 실패의 DB/Version/prev 롤백을 확인한다.
SQLite와 MySQL에서 같은 equipment 통합 테스트를 실행한다.

강화 테이블/재료는 GoddessReinforcement에, 젬 소켓 보너스는 Gems.socket_bonuses에 적재한다.
장비 단계별 누적 강화값은 파서의 실제 Lua 결과이며 화면의 고정 여신 배열은 제거했다.
UseLv와 ItemLv를 구분하고 Trinket 배율, 550 장신구와 560 무기/방어구의 차이를 검사한다.
확률·재료만 변경된 릴리스도 DB에 반영하며 누락된 비용과 무료 단계를 구분한다.
반복 적재·젬 레벨 제거·이전 JSON의 Level 누락·강화 보조 파일 생략·DB 유일성 제약 실패의 롤백을 검사한다.
새 컬렉션과 젬 필드의 잘못된 타입/범위·중복·참조는 공통 계약에서 차단한다.

`harness/browser_calculator.js`는 Node.js에서 실제 배포할 JavaScript를 실행한다.
작은 DOM 어댑터로 실제 HTTP 응답의 컨트롤 ID와 JSON 데이터를 연결해 강화/초월 입력 이벤트,
초기화·경계값·이벤트 순서·확률 단위·비용·재료 링크·문자열의 안전한 표시를 확인한다.
`harness/test_enhancement_browser.py`의 독립 기대값 검증은 check-parser에,
5개 지역 HTTP 데이터와의 연결 검증은 SQLite/MySQL 통합 테스트에 포함한다.
실제 브라우저 엔진·레이아웃·모바일 조작·모든 운영 Lua 계산식의 검증은 수행하지 않는다.
기존 초월 비율을 유지하며 진화·세트 효과·다른 착용 장비에 따른 방어구 공격력 전환은 계산하지 않는다.
추가 로컬 확인은 iTOS/kTOS 실제 560 CSV와 네 재료 함수 본문만 읽어서 실행했으며
logs/harness/equipment-live-probe.json에 결과·원본 hash를 기록했다. 전체 운영 파서/실데이터 회귀는 실행하지 않았다.
추가로 `logs/harness/reinforcement-live-probe.json`에는 iTOS/kTOS의 실제 550/560 IES와
추출한 IS_WEAPON_TYPE·SCR_GET_GODDESS_REINFORCE 함수로 새 파서 계산 헬퍼를 확인한 결과를 기록했다.
검·트링킷·갑옷·방패·목걸이·반지의 누적값을 CSV 합계와 대조했다. 이 확인도 전체 Lua 초기화나
운영 파서 빌드/DB 적재를 수행하지 않았으며 기본 하네스와 CI에는 포함하지 않는다.

## 다운로더 검증과 재시도

고정 입력은 [다운로더 fixture 안내](../harness/fixtures/downloader/README.md)를 참고한다.
테스트는 실제 인터넷 연결을 차단하고 `urllib` 응답을 메모리의 고정 데이터로 대체한다.
서버 통신·다운로드 파일 저장·PAK raw deflate 해제·번역 복사·버전 기록은 실제 Python 로직을 사용한다.
IPF는 임시 실행 파일로 도구 호출 순서와 종료 코드 처리를 검증한다.
실제 네이티브 IPF 복호화·IES 변환 정확성과 외부 서버 가용성은 별도 검증이 필요하다.

| 다운로더 CLI 종료 코드 | 의미 | cron 처리 |
| --- | --- | --- |
| 0 | 새 패치 처리 완료 | 다음 단계 진행 |
| 1 | 새 패치 없음 | 기존 지역별 변경 없음 처리 유지 |
| 2 | 네트워크·파일·복호화·압축 해제·IES CSV 검증·복사·버전 기록 실패 | 파싱·DB import 전에 중단 |

다운로드는 `.part`에 저장하고 비어 있거나 Content-Length와 다르면 공개하지 않는다.
완료된 파일만 캐시로 교체하며 도구 실패 시 원본 IPF를 유지한다.
data 패치는 extract 성공 뒤 임시 `extract` 아래 모든 IES CSV의 quoting·헤더·행 너비·UTF-8을
검증하고 나서 unpack 복사·원본 IPF 폐기·버전 전진으로 승급한다.
쉼표·따옴표·줄바꿈이 있는 필드는 인용하고 내부 따옴표를 두 번 써야 한다.
올바른 인용·여러 줄 필드·헤더만 있는 표는 허용한다. binary IES는 행 0개·열 0개도
유효하며 native CSV가 정확히 LF 하나(`'\n'`) 또는 플랫폼 CRLF 하나(`'\r\n'`)인
완전한 파일만 zero-schema 표로 바이트 변경 없이 허용한다.
0바이트 빈 파일, 빈 헤더 뒤 추가 레코드·여러 빈 줄·쉼표 필드가 있는 빈 헤더,
헤더와 다른 필드 수, 잘못된 인용과 UTF-8 오류는 보정이나 행 삭제 없이 계속 실패한다.
검증 실패는 기존 unpack·Translation·버전에 손대기 전에 중단하고 캐시 원본 IPF를 보존한다.
파서나 운영 import를 실행하지 않으므로 기존 JSON도 보존한다.
격리 다운로더 회귀 검증은 기존 `extract_stub`로 LF/CRLF zero-schema 표의 공개 바이트
보존·버전 전진·정리를 확인해야 한다. 기존 모든 실패 사례와 함께 `'\n\n'`,
`'\r\n\r\n'`, `'\n1,plain,NO\n'`, `'\n,,\n'`, `b''`의 거부,
기존 unpack·Translation·버전·캐시 보존과 정상 입력으로 복구 후 재시도를 확인해야 한다.
실패를 완화하거나 테스트를 skip하지 않으며 실행 결과는 오케스트레이터가 확인한다.
버전 CSV는 개별 패치의 해제·복사 성공 후 임시 파일로 기록하고 교체한다.
release 패치의 경우 번역 복사 성공도 버전 전진 조건에 포함한다.
손상된 PAK은 재사용하지 않고 다음 실행에서 다시 다운로드한다.

과거 손상 CSV는 보존 원본 IPF에서 올바르게 준비한 추출기로 새 격리 경로에 재추출해야 한다.
기존 unpack·JSON·Translation·버전이나 원본 IPF를 덮어쓰지 않고,
따옴표·열을 추측 보정해서 정확성을 주장하지 않는다. CSV 형식 검증 통과는
binary IES 변환 정확성이나 게임 값의 의미적 정확성을 증명하지 않는다.

복수 패치 중 두 번째 패치가 실패하면 첫 번째 완료 버전은 유지하며,
재실행은 실패한 패치부터 시작한다. 서로 다른 data/release 스트림도 각각 완료 버전을 유지한다.
unpack과 번역 디렉터리 전체를 롤백하는 구조는 아니므로 실패 후 일부 파일이 남을 수 있다.
실패 상태에서 cron의 후속 단계를 차단하고 다음 실행이 해당 패치를 다시 적용하는 방식이다.

## 이번 PAK 스트리밍 재시도의 근거와 인계

이번 변경의 구현·테스트 읽기 참조는
[`unpacker_pak.py`](../downloader/unpacker_pak.py),
[`conftest.py`](../downloader/tests/conftest.py),
[`test_downloader.py`](../downloader/tests/test_downloader.py)다.
64KiB compressed member read와 양수 1MiB inflate 상한, 작은 header/name exact-read,
native signed 14바이트 형식·blacklist-before-UTF8·trailing compressed bytes 호환성을 유지한다.
메모리에는 여러 조각과 zlib/Python/file 상태가 함께 존재하므로 이 상한들의 합을 RSS
상한으로 주장하지 않는다. 전체 archive/member buffering과 무제한 decompressor flush는 없다.
파일별 `.part` flush/fsync/close/replace와 실패 정리, 앞 파일 완료·뒤 destination/archive
보존 및 처음부터 재시도하는 계약은 [아키텍처](architecture.md#pak-스트리밍-추출의-메모리공개복구-경계)에 둔다.
직접 `unpack()`의 실패 archive 보존과 상위 다운로더의 손상 PAK 재다운로드는 별개다.

### 작은 회귀 명세와 정정 이력

`pak_io_guard`는 실제 파일과 `decompressobj`를 감싼 테스트 전용 fixture다.
source `read(size)`는 양수·최대 65536 bytes, inflate `max_length`는 양수·최대
1048576 bytes이며 반환 출력도 전달한 상한 이하인지 확인한다. 짧은 read를 반환할 수
있고 decompressor flush를 금지한다. pytest monkeypatch teardown으로 원래 seam을
복원하며 HTTP fixture·인증·의존성·production behavior를 바꾸지 않는다.
기존 baseline/version/redownload/CSV guard 테스트는 유지한다.

현재 추가된 테스트 함수는 여섯 개, parameterization을 포함하면 18개 회귀이며
아직 실행 결과는 없다. 필요한 오류 변형만 parameterize한다.

| 회귀 명세 | 현재 정의된 범위 |
| --- | --- |
| bounded member read/inflate | seed 20261014의 RNG 하나로 만든 200 bytes, compressed 입력 >16 bytes·decoded 출력 >32 bytes 확인, read 16 bytes·inflate 32 bytes로 축소, 출력 equality·archive 삭제·no `.part`·호출 상한 assertion |
| 짧은 read·여러 레코드 | header/name/member 짧은 read, 유효한 빈 decoded member, blacklist invalid UTF-8, trailing compressed bytes 뒤 다음 레코드 결과 |
| invalid record | 빈 archive·짧은 header·양수 이름 길이 대비 이름 bytes 부족·비양수 이름 길이·음수 compressed/uncompressed 크기·빈 compressed member·member 경계 초과·비blacklist invalid UTF-8, archive 보존·no `.part` |
| 뒤 레코드 실패 | incomplete/corrupt deflate·declared size mismatch에서 앞 파일 완료, 기존 뒤 파일과 archive 보존·part 정리 |
| 같은 경로 재시도 | 실패 archive를 정상 bytes로 다시 제공하여 정상 출력·archive 삭제·no `.part` |
| 공개 IO 오류 | fsync/replace 오류에서 기존 destination과 archive 보존·part 정리 |

2026-10-14 정정: 이전 문서 finding은 매 바이트마다 RNG를 새로 생성한 입력과
`truncated_name`·`empty_member` 사례 누락을 지적했다. 이번 승인 소스 열람에서는
`rng = random.Random(20261014)` 하나를 반복 사용하며 기존 크기 assertion이 유지되고,
두 사례가 기존 `INVALID_PAKS` parameterization에 추가된 것을 확인했다.
이전 finding의 입력·정의 문제는 현재 소스에 반영되어 있다. 문서 worker는 테스트를
수정하거나 실행하지 않았으며 이 열람 결과는 assertion 통과나 validation success를
뜻하지 않는다. 여섯 함수의 정의와 기존 deflate/size/truncated 재시도·버전·CSV 회귀를
함께 유지한다. 짧은 read와 이름/member 경계 검사는 작은 합성 입력의 회귀 명세이며
실제 운영 archive나 모든 IO 실패 형태를 검증한 결과가 아니다.

### 제공된 측정과 검증 상태

2026-10-14 최신 인계 정정: 종전 기록의 구현 단계 passed·큰 테스트 요청 900초
timeout 이후, 마지막 run은 실제 GLM 소스·fixture·테스트와 Codex 문서 작성 및
Claude 승인까지 완료했다. 그러나 Python3.8 실제 `check`에서 테스트 helper의
`zlib.compress(data, 9, -15)`가 `TypeError: compress() takes at most 2 arguments`로
downloader 수집을 실패시켜 run은 failed였다. Root에는 아무것도 반영하지 않았다.
기본 gate의 parser 실패도 같은 downloader collection error를 다시 실행하는 통합 테스트
한 건이며 django/regression/pipeline은 통과했다. 이는 메인이 제공한 이전 결과이며
이번 worker가 실행·확인한 검증 결과가 아니다.
메인은 승인된 7개 파일만 새 격리 모델 사본에 재사용했다. 원본 Root와 원래 baseline은
새 전체 검토·검증 후 반영 전까지 그대로 유지한다.

이번 국소 수리는 `raw_deflate` 한 곳을 Python3.8에서 지원하는 raw-deflate
`zlib.compressobj(9, zlib.DEFLATED, -15)` 생성 후
`compressor.compress(data) + compressor.flush()`로 바꾸는 것이다.
작은 fixture 입력을 완성하는 compressor flush이며 production decompressor flush 금지를
바꾸지 않는다. 현재 승인 테스트 소스에서 이 정의를 확인했지만 실행하지 않았다.
production source·fixture·나머지 기존 및 신규 테스트는 유지하며 weakening/deletion/skip은 없다.

| 메인이 제공한 관측 | 증거의 범위 |
| --- | --- |
| 소스 SHA256 `ace103822ecb0496602066e25ff5d5172cff44fd471ede65e9226c002568108e` | 재사용 완료 소스의 제공된 식별값; 이 worker는 hash 검사를 실행하지 않음 |
| 기존 downloader 회귀 81개 passed, skip 0 | 위 소스·fixture의 이전 결과; 새 18개 회귀나 이번 전체 gate 성공이 아님 |
| 격리 64MiB 합성 입력 3회와 별도 tracemalloc에서 output bytes/SHA256이 baseline과 동일 | 이전 승인 후보의 제공된 측정이며 최종 소스·새 회귀·전체 validation success가 아님 |
| Python traced peak 134851344 → 2337899 bytes | 위 후보의 별도 tracemalloc 관측; RSS·전체 pipeline peak·고정 메모리 상한을 증명하지 않음 |

64MiB benchmark는 기본 테스트에 넣지 않는다. 새 작은 테스트의 존재나 제공된 측정을
최종 검토·offline gate·CI 성공으로 해석하지 않는다. 현재 최종 검토·전체 검증·원격
게시·CI·merge·cleanup은 결과가 제공되지 않아 모두 대기다.

### 실행·검토·게시 책임

2026-10-14 배정 정정: 종전 세 task 대신 정확히 두 순차 task다.
(1) downloader GLM의 `unpacker_pak.py`·`conftest.py`·`test_downloader.py`에서
`raw_deflate` helper 한 곳만 수리하고 나머지를 유지한다.
(2) coordinator의 architecture/harness/ADR0014/index 문서를 확인·유지하고 필요할 때만 갱신한다.
읽기 참조 파일을 별도 task로 배정하지 않는다. 기존 GLM `glm-5.3-flash`와 모든 역할
설정, NFS 저장 설정·mount·floor를 유지하며 모델·설정·storage override를 변경하지 않는다.

worker는 승인된 정확히 7개 파일만 읽고 각 task의 배정 파일만 수정한다.
문서 worker의 편집 대상은 `docs/architecture.md`, `docs/harness.md`,
`docs/adr/README.md`, `docs/adr/0014-streaming-pak-extraction.md`다.
기존 사용자 편집을 보존하며 tests/checks·Git·운영 데이터·cron·전체다운로더·실DB·
다운로드·importAll·다른 모델·agent-run·harness.workflow를 실행하거나 위임하지 않는다.

실행기는 새 검토 뒤 필수 check 하나인 **전체 offline gate (`make check`)**를 수행한다.
기존 baseline tests·제외를 유지하며 selected skip/xfail·미수집은 성공으로 처리하지 않는다.
이 worker는 어떤 검사도 실행하지 않았고 실행기의 성공을 대신 선언하지 않는다.
매 review는 `documentation={status,files,reason}`을 반환하고 실제 changed docs가
메모리·공개·실패 복구·격리·책임을 완전히 설명하는지 의미적으로 판단한다.
Markdown 확장자 확인은 완전성 증거가 아니다. 이번 문서 수리는 승인된 네 문서에
구현 계약·현재 테스트 명세·근거 한계·후속 책임을 기록하여
`documentation.status=updated`로 인계하며, 새 reviewer의 의미적 완전성 판단은 대기다.

2026-10-14 문서 finding 정정: 이전 승인 사본에는 ADR0014가 없어
`changes_requested`, `documentation.status=missing`으로 보고했다. 이전 문서 수리는
승인된 정확한 경로의 [ADR0014](adr/0014-streaming-pak-extraction.md) 작성을 명시하여
그 파일을 작성하고 index의 예약 항목을 실제 링크로 갱신했다. 이번에는 해당 기록을 유지한다.
이는 승인 밖 파일 생성이나 scope 확대가 아니다. importer ADR0012·owned-temp ADR0013의 항목은 보존한다.
다른 문서·parent instructions·호스트 설정·credentials는 읽지 않는다.
추가로 필요한 승인 밖 문서는 현재 확인되지 않았다. 필요해지면 정확한 누락 경로를
기존 승인 파일 finding에 기록하고 changes_requested로 보고한다. scope 확인·새 run
준비는 메인 coordinator 책임이며 repair round는 승인을 확대하지 않는다.

메인은 finding 해결과 최종 검토·전체 offline gate 후 최종 소스 hash 및 제공된 측정과의
일치를 확인하고 기존 GitHub request/accept 흐름으로 원격 commit·PR을 진행한다.
`Offline harness (SQLite)`, `MySQL harness`, `Chromium browser harness`의 실제
CI success 3개를 확인한 뒤 승인 SHA에 squash merge하고 해당 run branch 정리를 완료한다.
기존 journal·정확한 ref·lease·사용자 편집 보존·cleanup 완료 계약을 유지한다.
merge와 cleanup 상태는 구분하며 cleanup complete 전 전체 성공을 선언하지 않는다.
이는 후속 책임이며 이 문서 작업의 실행 결과가 아니다.

## 공개 저장소의 운영 알림 설정

추적되는 `cron_itos.sh.example`, `cron_jtos.sh.example`, `cron_ktos.sh.example`의 Discord 웹훅은
`TAVERN_DISCORD_WEBHOOK_URL` 환경 변수에서 읽는다. 실제 지역 cron은 로컬 운영 파일이다.
운영 cron 환경에서 지역에 맞는 값을 따로 설정하며 URL을 소스나 로그에 기록하지 않는다.
`downloader/tests/test_downloader.py`와 `parser_tidy/tests/test_cron_guard.py`는 5개 지역의
추적되는 `.example`을 읽어 다운로드·파서·import 실패 가드를 검사한다.
예제가 없으면 skip하지 않고 실패하며 운영 cron은 실행하지 않는다.
서버의 기존 설정과 운영 파일은 이 소스 준비 작업에서 수정하지 않는다.

## 이번 importer/cleanup 수리의 후보 근거와 검증 대기

[당시 인계 원문](adr/0034-inspection-failure-recovery-and-health.md#보존-인계-importer)에 실패·관측·검증 대기와
기존 요구를 그대로 보존한다. 현재 작업의 성공이나 권한으로 재해석하지 않는다.

인계와 매 review의 `documentation={status,files,reason}` 요구는
[workflow](workflow.md#이번-31파일-수리의-검토검증게시-인계), 결정은
[0012](adr/0012-importer-single-run-snapshot.md)와 [0013](adr/0013-owned-validation-temporary-cleanup.md)에 둔다.

## GLM telemetry 검증 인계

[ADR0019](adr/0019-private-glm-call-telemetry.md)의 offline 명세는
`harness/test_agent_telemetry.py`, `test_agent_models.py`, `test_improvements.py`,
`test_improvement_loop.py`에 있다. synthetic OTLP, mocked subprocess, 외부망이 없는 loopback
fake peer를 사용하며 실모델·global credentials에 의존하지 않는다. chronology/TTFT/content,
multiple calls/dedup/retry/unknown, out-of-order Read body, 실패/timeout 부분 보존, 무수출·setup/
spawn 오류, 악성/과대/비밀 포함 입력, exporter/content env 제거, stalled peer와 listener 정리,
Codex/Claude 제외, 기존 기록 호환 및 web payload/digest byte 동등성을 검토한다.

worker는 이 명세나 checks를 실행하지 않았다. parent는 관련 tests와 필수 전체 `make check`를
실행하고 skip/xfail을 성공으로 취급하지 않는다. fresh reviewer는 [전체 설계](harness-design.md),
[모델 contract](agent-models.md#glm-호출의-private-지연-관측),
[private 기록 경계](improvements.md#private-glm-지연-기록-읽기), ADR0019와 최종 구현을 함께 보고
매번 documentation={status,files,reason}를 반환한다. 추가 필수 문서가 승인 밖이면 기존 승인
파일의 finding으로 정확한 경로를 요청하고 changes_requested로 남긴다.
parent의 후속 합성 live는 구현 호환 검증이며 실제204~500초 연구의 병목 판정과 구분한다.
다음 normally admitted GLM hourly 관측은 main이 기존 gate/schedule 안에서 읽는다.
추가 source probe·model call·schedule/state 편집·frozen report 재발행은 이 작업에 포함하지 않는다.

2026-10-19 복구 인계: run `1792416450941994605-2e6132`는 코드 담당 호출 passed 뒤 문서 호출 중
main이 실제 NFS 결함을 발견해 중단했고 applied=[]였다. 보존 초안과 파일 link probe는 최종 검증
증거가 아니다. 후속 run `1792417309675138078-0875f6`도 실제 docs-only 결함으로 full check 중단·
applied=[]였다. 실제 NFS 최종 어댑터의 보관/readback/hash·멱등 재개는 parent의 별도 성공 관측이다.
이 수정의 검사는 worker가 실행하지 않았으며 main의 새 Claude 의미 검토·전체 make check·실제 문서
검사·GitHub/필수 CI가 남는다. 이전 의미 검토를 최종 수정 승인 근거로 재사용하지 않는다.
