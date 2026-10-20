# 개발 작업 자동 배정과 실행

## 현재 저장·검증·복구 순서

[ADR0021](adr/0021-local-work-and-result-archives.md)의 명시 v2에서 workspace/checks/logs/backup/
Git journal은 local active artifacts, 비인증 임시는 local temporary다. archive는 terminal 결과만
받고 파싱/status/find_run/progress에는 접근하지 않는다. v1/no-config와 옛 NFS journal은 보존하며
원래 v1 설정으로 조회·재개한다. private 기본 설정 활성화는 검토·검증 후 main 책임이다.

최종 report save와 project lock 해제 후 archive하며 Git request/accept/resume/cleanup은
최종 save → 두 lock 해제 → 기존 completion hook → archive 순서다. awaiting_github/awaiting_ci/
cleanup_pending은 완료 archive 대상이 아니다. GIT=0·실패/중단과 standalone checks도 지원하며
검증 자식의 파생 v1 설정은 nested archive를 하지 않는다. archive pending은 기존 outcome·merge/
cleanup 증거를 보존하고 별도 nonzero다.

원격은 local freeze와 달리 directory rename을 사용하지 않는다. exclusive private 결과
디렉터리의 attachment를 로컬 archive-transfer.json에 고정하고 bounded payload·inventory를
검증한 뒤 마지막 commit.json을 no-replace 파일 link로 게시한다. 최종 0600/nlink=1 readback
전에는 완료가 아니다. 정확한 frozen prefix만 이어 쓰고, 알려진 임시/최종 두 alias의 동일 inode/
nlink=2 전이만 복구한다. 알 수 없는 충돌·변조·교체는 삭제하거나 덮어쓰지 않는다. mkdir 뒤
receipt 전 중단은 자동 복구하지 않는다. trusted parent가 최종 archive.py의 실제 NFS 저장·
readback/hash·동일 결과 멱등 재개 성공을 보고했다. 일반 pipeline 전체 성공을 뜻하지 않는다.

main은 같은 config의 `make archive-run RUN_ID=... KIND=workflows`로 모델/검사/Git 없이 보관만
재개한다. frozen payload와 현재 terminal allowlist가 다르면 pending이며 과거 payload를 새
성공으로 쓰지 않는다. local workspace/backup과 복구 증거는 자동 삭제하지 않고 floor를 유지한다.

[ADR0022](adr/0022-documentation-only-validation.md)에 따라 새 review 뒤 실제 최종 diff를 분류하고
repair마다 다시 판단한다. 일반 README/docs prose만 docs-only이며 정책·코드·mode/type·불명은 full이다.
로컬 manifest는 POSIX permission 정수를 보존하여 0664/0640/0600 등 기존 비실행 regular 문서의
동일 권한 수정과 정상 추가/삭제를 허용한다. 실제 권한 변경(0600→0644 포함)·실행/special bit·
불명 mode는 full이며 CI raw Git mode 문자열은 기존 100644 기준을 유지한다.
check-docs는 stdlib 링크/fragment/삭제·rename 영향을 검사하고 positive selected/passed·zero skip
결과를 validation_selection/delivery_validation digest로 적용·게시까지 결합한다. CI의 세 required
gate는 docs 증거 또는 기존 heavy 검사의 실제 성공을 요구한다.
[ADR0023](adr/0023-new-branch-documentation-validation.md)에 따라 정확한 zero-before와
created=true/deleted=false인 유효한 비기본 branch 최초 push는 fetched default commit을 고정하고
유일 merge base→event head 전체 diff로 판정한다. 불명 metadata/ref/history·공통 조상 없음/복수·
dirty/untracked/head 불일치·빈 diff는 full이며 최초 push 자체를 skip하지 않는다. 선택된 changes는
docs 검증과 report/selection equality까지 유지한다. 여러 줄 inline code는 같은 길이의 backtick run과 code 안팎의 escape 규칙으로 마스킹하고
원문 줄 번호·heading 텍스트 기여·code 뒤 실제 링크 검사를 유지한다. paragraph·heading·fence 경계와
미지원 multiline link/HTML의 fail-closed 정책은 유지한다. 이번 harness/CI 수정은 shortcut 대상이 아니며 main이 새 Claude 의미 검토·전체
make check·실제 문서 검사·GitHub 전달/CI를 수행한다. worker는 이 실행을 대신하지 않는다.

`harness/workflow.py`는 작업 접수부터 검토·검증·파일 반영과 GitHub 게시 준비까지 연결한다.
메인 Codex `/root`는 파일 범위를 조사하고 요청을 전달하며, 앱 게시·머지 후 브랜치 정리와
최종 결과 보고를 맡는 조정 역할이다.
구현·검토는 `harness/agent-models.json`의 역할별 CLI와 인증을 실제로 사용한다.
Codex 앱의 내장 서브에이전트 목록과 별개인 프로세스이므로 역할의 실행 상태는
이 실행기의 터미널 출력과 private JSON 보고서에서 확인한다.

```text
/root: 사용자 요청과 개별 파일 범위 준비
  → 준비: 승인 파일 모델 사본 / 전체 로컬 검증 사본 분리 + 하네스 doctor
  → Jev: 영역·복잡도·계약 영향 판단
  → 배정: 명확한 작업은 담당자 직행, 나머지는 Codex coordinator 계획
  → 구현: downloader(GLM) / parser(Codex) / django(Codex) / 공통 영역(coordinator)
  → 검토: Claude reviewer의 구조화한 승인 또는 수정 요청
  → 검증: 실행기가 필수 오프라인 하네스 검사
  → 반영: 실행 전 원본과 충돌이 없는 검증된 파일만 교체
  → GitHub: git(Codex medium)이 설명 작성 → 메인 /root의 앱으로 커밋·브랜치 게시·PR
      → SQLite·MySQL·Chromium CI 성공 확인 → head SHA를 고정해 squash merge
      → 메인 /root: PR 증거·현재 상태 확인 → 작업 브랜치 정리·기준 브랜치 동기화 결과 별도 보고
```

공통 영역은 Makefile·하네스·문서 등이다. JSON 계약처럼 여러 영역이 연결되면
coordinator가 계획한 뒤 각 파일을 실제 소유 영역의 모델에 배정한다.
영역 담당자를 새로 실행하는 주체는 실행기이며 작업자 자신의 재위임은 끈다.
첫 버전은 담당자를 **순차 실행**한다. 모든 작업에 모든 모델을 호출하지 않는다.

## 자율 발견 제안의 별도 승인 경로

직접 요청한 개발 작업의 기존 승인과 GitHub 전달 정책은 유지한다. 자율 발견된 제안은 기존의
포괄 Git 허가에 포함되지 않는다. 이번 기반 기능 구현·전달 승인도 후속 제안의 승인을 뜻하지 않는다.
[개선 연구·오전 보고](improvements.md)의 `tick`과 legacy `discover/daily`는 일반 `READ_ONLY=1` workflow와 별도다.
일반 READ_ONLY workflow는 필수 검사도 실행하지만 일일 점검은 source write·checks·Git·
workflow.execute·운영 파이프라인을 호출하지 않고 격리된 읽기 전용 역할 분석만 수행한다.

메인은 보고서의 특정 `IMP-<16 hex>`와 실제 사용자 지시를 확인하여 private 0600 UTF-8
instruction 파일로 `approve`한다. reviewer의 `eligible`, 모델 텍스트/boolean, 웹 문구는 사람의
승인이 아니다. `execute --proposal-id ID`에는 task/files override가 없으며 승인된 제안과
정확한 편집 목록으로 고정 task를 생성한다. 기본 게시 범위는 commit/PR/필수 CI 3개/
squash merge/cleanup이고, 승인 시 `--local-only`로만 로컬 전용을 고정한다.

승인 전에 독립 검토·원본 freshness를 확인한다. execute는 HMAC 승인·proposal/review digest·
정확한 파일 목록·모든 읽기 의존성의 bytes/mode/존재·scope/config·만료·human decision·
미소비 상태를 검증하고 lock 안에서 한 번 claim한다.
loop 제안은 discovery/loop/local/agent/workflow 설정까지 freshness에 포함하며
loop_dependencies digest를 proposal provenance와 signed approval의 discovery_fingerprint로
묶는다. 동일 ID가 새 config에서 재발견되어도 기존 승인과 재결합하지 못한다.
workflow가 고정 project lock을 잡으면 `_improvement_guard(run_id)`가 준비 사본·검사·쓰기
모델 전에 재검증하고 run_id를 기록한다.
발견/승인/claim과 workflow/cleanup은 같은 project lock을 사용해 중첩을 거부한다.
guard 없는 일반 workflow는 직접 요청 권한을 유지하며 자동 제안의 우회 실행에 사용하지 않는다.

claim 이후 실패·중단·`awaiting_github`에도 승인은 소비된다. 기존 run과 GitHub journal을 먼저
조정한다. `approve ... --reconcile-run-id <정확한 run_id>`는 terminal run과 cleanup 상태를
확인하고 이전 기록을 archive한 뒤 새로운 명시적 지시로만 승인한다. workflow에 전달되지 않은
claim은 메인이 실제 미시작을 확인한 뒤 `--reconcile-run-id unstarted`로 처리한다.
소스가 바뀌었으면 새 discovery가 필요하다. reconcile은 실패 모델을 재호출하거나 실행하지 않는다.

improvement execute의 `awaiting_github` 반환/CLI exit0는 완료가 아니다. 메인은 기록된 run_id의
기존 request/accept journal을 이어 새 Claude 의미 검토·필수 하네스 checks·범위 반영 이후의
Git 역할·앱 게시·CI 3개 success·SHA 고정 squash merge·cleanup complete까지 확인한다.
지연·실패를 숨기거나 execute를 반복하지 않는다. improvement execution 기록은 인계 당시 상태이며
이후 GitHub 완료의 기준은 기존 workflow/journal의 실제 상태다.

### 승인 제안 완료를 웹 보고에 전달

[ADR0020](adr/0020-automatic-proposal-completion.md)에 따라 GitHub request/accept/resume/cleanup의
마지막 save 후 project/GitHub lock을 모두 해제하고 `improvement_completion`을 lazy import한다.
같은 run의 각 signed claim/approval·proposal digest/authorization·approved decision·독립 검토와
실제 구현 review/validation·허용 scope·applied 변경을 대조한 뒤 전달한다. 선택된 private run
경계를 지키며 local fallback하지 않는다. report.run_id/passed, github-v1 identity/config/정확한 PR URL,
merged SHA/done, CI 3종 success, head/merge SHA가 일치하는 verified cleanup proof/CI와
cleanup_complete가 필수다. 완료 시 `_authorization`/`_fresh`를 재호출하지 않고 현재 소스·만료로
승인이나 실행을 재소비하지 않는다. 여러 signed run claim은 각각 검증하며 일반 bundle 권한은 없다.
claim 없는 일반 작업은 키/credential/HTTP 없는 no-op이다. child/discovery/unattended·
read_only/simulated/GIT=0/local-only에는 전송하지 않는다.

별도 `completion` 결과가 pending/blocked여도 passed/merge SHA/cleanup은 유지한다.
기존 불변 오전 `improvement-web-v1`과 사용자 승인된 `improvement-completion-v1`은 별도 계약이다.
private 0600 canonical payload+digest/journal을 HTTP 전에 durable 저장하고 POST 전 sending을 남긴다.
정확한 GET schema/digest/payload readback만 delivered다. sending/unknown 자동 재호출은 GET만 하며
absent는 unknown이다. 메인은 같은 storage 환경에서 `make agent-improve-completion RUN_ID=...`를
사용하고, GET absent 확인 뒤 동일 frozen digest만 다시 보낼 때 `RECONCILE=1`을 명시한다.
conflict는 overwrite/retry하지 않고 delivered는 HTTP 없이 종료한다. completed_at은 최초 생성 시
고정하며 오전 보고/digest/publication journal은 변경하지 않는다. 새 모델·승인·execute·Git·cron/tick은 없다.
정확한 7개 wire key·16384 bytes·기존 inbox/TLS/timeout·immutable 서버 및 browser cursor API는
[운영 계약](improvements.md#승인-제안-자동-완료-전달)을 따른다. Sites 소스/API/UI 구현·배포는
메인 책임이며 이 저장소의 offline 명세를 실제 HTTP 성공으로 보고하지 않는다.

unattended는 approve/reject/execute를, child/discovery 세션은 개선 orchestration을 거부한다.
scheduler는 bounded hourly 연구·09:00 once 보고만 수행하며 제안의 GitHub 게시에는 승인과
메인 앱 세션이 필요하다. tick은 decisions/approvals/claims/workflow/Git을 생성하지 않는다.

### 시간별 연구는 구현 workflow와 별도

[ADR0017](adr/0017-budgeted-continuous-improvement.md)은 이전 daily-only/5회/one-pass 자동
점검 정책만 대체한다. local(coordinator)→coordinator→local(downloader)→downloader→local(parser)→
parser→local(django)→django→독립 Claude 검토의9단계를 한 hourly slot씩 진행한다.
tick당 모델 최대1회·로컬 포함 KST 하루24회, specialist2/전체8 후보이며 기존37개 scope와
ownership/shared를 유지한다. local은 정확한 path/원래 line 번호의 작은 연속 window와 정제
feedback만 받는다. 실패/빈 초안의 관련 specialist는 미호출한다. 정식 candidate는 기존
specialist가 만들고 reviewer가 독립 검토한다. 다음 round의 실제 prompt에 정제 issue와
specialist/Claude reason을 이어받으며 source/config 변경은 pool/feedback/cursor를 무효화한다.
local 참여는 private mlx-vlm/model/stage/owner로 구분하고 web-v1의5역할을 위장하지 않는다.

local은 mlx-vlm0.7.8 native response_format.json_schema(strict)와 top-level enable_thinking=false를
사용한다. schema는 기존 canonical 후보 전체 필드·타입·필수 항목·닫힌 객체·최대2개, owner 승인
edit_files enum과 양쪽 evidence의 실제 단일 window 경로/원문 정수 범위를 담는다. 전송 전에
준비 입력 결합 및 재구성 canonical schema를 대조해 누락·완화·owner/scope/window/thinking
변조를 거절한다. whole-line 선택은 schema 포함 전체 request24576bytes를 계산하며 고정 overhead
초과는 context_too_large no-call이다. uniqueItems는 서버 미지원이므로 중복 검사는 client에 둔다.
줄 순서·문자 총량·의미와 실제 window/공유 후보 검증·독립 검토가 최종 권위다. 서버가 schema를
무시해도 거절하며 보정·합성·retry/fallback은 없다. 정상 assistant의 정확한 tool_calls:null/
tool_call_id:null만 무동작 metadata이고 non-null·다른 도구 필드는 거절한다.
local-model-config-v2/provider=mlx-vlm으로 명시 이행하며 api_model==model인 상대 repository ID를
요청한다. default_model·절대 모델 경로는 쓰지 않고 v1 mlx-lm은 config_invalid로 보류한다.
config digest 전환으로 기존 loop fingerprint·승인은 무효다. Linux는 Python3.8 표준라이브러리만
유지한다. 설치·모델 연결·서비스/private config 전환·실추론은 메인 책임이다.

이번 수리는 승인21개를 coordinator task 정확히1개로 완성하며 재위임하지 않는다. 이전
prompt/order 두 실행은 full check 중단/applied=[]이고 보존 초안은 새 검토/전체 검증이 필요하다.
검증 사본 재사용은 parent가 NFS 원본 baseline과 같음을 확인한 준비이며 성공이나 fallback이 아니다.
Jev→필요한 Codex 계획→기존 설정 영역(coordinator)→새 Claude 독립 검토→전체 make check→
scoped apply→메인의 기존 Git/GitHub 게시·CI·머지·정리를 유지한다. 작업자/검토자는 검사를
실행하지 않는다. 최초 candidate_invalid의 정확한 필드는 원문 미보존으로 알 수 없으며
동일 입력의 편집 범위·근거 줄 위반 재현을 최초 원인으로 단정하지 않는다. 메인의 서버 호환
관측과 최종 bytes/전체 검사/실제9단계·다음 아침 게시 성공을 구분해 [로컬 문서](local-models.md)에 둔다.

Claude 자동 탐색 추정 ledger는 KST 하루US$1·reviewer cap0.20이며 호출 전 durable reservation과
호출 수를 기록한다. 성공 finite estimate만 정산하고 unknown/실패/중단은 전액 소비한다.
초과 관측은 실제 추정액 기록 뒤 당일 중단한다. 일반 예산 소진은 reviewer admission에서
판단한다. 그 차례 전 로컬/구독 역할은 다른 gate와 call cap 내 진행하지만 reviewer 예산 보류는
stage_index를 유지한다. 새 slot에서도 reviewer를 재판단하고 이후 로컬/구독 역할은 대기가
풀릴 때까지 호출하지 않는다. 09:00 보고는 독립적이다. CLI cap은 실청구 강제상한 보장이 아니다.
**구현 workflow의 모델 비용은 이 자동 탐색 ledger와 별도이며 기존 역할 예산은 유지한다.**
GLM은 기존 Coding Lite 인증·endpoint를 유지하며 parent의 매 quota admission에서
TOKENS_LIMIT/CREDIT_LIMIT의 percentage/reset·있으면weekly를 검증한다. >=80% 또는
unknown/malformed/조회 실패는 GLM 보류이며 명목20% 개발 여유다. 진행 중 소비의 보장은 아니다.
두 model type 모두 인식된5h window의 정확한 finite numeric0%(bool 제외)에만 absent/null reset을
idle로 허용하며 private null을 미상·미활성으로 유지한다. weekly는0%라도 유효한 미래 reset이
필요하다. 비영 reset 누락·존재하는 잘못된 reset·실패 envelope는 거부하고 model limit 부재·
TIME_LIMIT 단독·HTTP 실패를0%로 해석하지 않는다.
이 gate는 자동 탐색용이며 승인 실행을 제한하거나 허가하는 장치가 아니다.

한 slot claim을 먼저 저장하고 호출 count/예약/cursor/inflight를 atomic 저장한다. failed slot
자동 재호출·daemon·fallback은 없다. 동일 improvement/project lock을 쓰고 storage 미준비면
모델을 실행하지 않는다. tick의 설정 로드·Store 생성·readiness 실패는 bounded 정제 paused
(`lock_storage_or_runtime_unavailable`)로 반환하며 키 조회·보고 확정·publisher·fallback도 하지
않는다. child/discovery 권한 거부는 이 처리 바깥에 유지하고 원문 예외는 노출하지 않는다.
자정600초 전 admission 거부·high-water rollback 방지·날짜 초과 시
양일 보수적 count/charge/중단으로 allowance 우회를 막는다. legacy 같은날 비용/호출은
scan_id로 중복 제거 carry-in하고 unknown을 보수적으로 소비 처리한다.

보고는 이전09:00~현재09:00의 현재 fingerprint 일치 최신 완료 review 하나로 모델 없이
09:00 이후 첫 tick에 불변 확정한다. distinct 최대8후보를 priority/ID순 최대3카드로 표시하고
유효 review 부재는0카드 partial/failed다. 옛날 참여를 오늘 성공으로 표시하지 않는다.
prepared publication journal에서 crash 복구하고 CLI가 두 state lock 밖에서 기존 Sites
deliver_report를 호출한다. sender mutex와 sending/attempt_id가 중복 callback을 막는다.
unknown 전송은 자동 재시도하지 않으며 메인이 같은 digest만 publish --reconcile로 조정한다.
기존 day를 덮어쓰거나 자동 재전달하지 않고 catchup은 오늘 날짜 하나뿐이다.

실행기의 새 Claude 문서 의미검토/full make check·두 umask077/022 fixture 검증/scoped apply와
메인의 최종 adapter 실추론·신규 서비스/private config 전환·실제9단계·다음 아침 게시 확인은
별도 후속 작업이다. 단일 hourly cron·게임 jobs·명시 daily local storage·persistent NFS default를
보존한다. 기존 hourly wrapper 활성·2026-10-16 09:00 partial/제안0개 보고1회 전달은 메인 제공
상태이며 확정 보고를 재생성하지 않는다. 이전 합성 추론·native 서버/미검토 bytes 사전 관측은
이번 성공과 구분하고 [local-models](local-models.md)에 한계를 둔다. worker는 검사/실모델/Git/
cron/재위임하지 않았다. 이전 NFS full check timeout/부분 결과·보존 초안은 새 승인이나 전체
검증 성공이 아니다. workflow-config/역할/다른 한도/NFS·temporary 정책은 바꾸지 않는다.
기존 GitHub create_tree의 공개 동의 부족 자동승인 거부 이력은 보존한다. 이번 직접 요청은
기존 Git 역할·검증된 앱 요청을 메인에 인계하되 baseline 불일치·명시 승인 거부 시 중단한다.
매 reviewer는 실제 changed Markdown과 의미 완전성을 documentation={status,files,reason}으로
판단하며 확장자/존재 검사만으로 충족을 주장하지 않는다.

## 실행

작업 설명은 UTF-8 텍스트로, 모델이 읽거나 변경할 파일은 저장소 상대 경로를 한 줄에 하나씩 적는다.
`FILES_FILE`은 **외부 모델에 제공할 소스의 승인 목록**이기도 하다. 소스 외에 모델이 읽어야 할
테스트·문서·새 파일도 미리 포함한다. 디렉터리 전체를 범위로 지정하지 않는다.
`READ_ONLY=1`은 파일 변경만 막으며 읽기 승인 범위는 같은 목록으로 제한한다.
목록 밖의 AGENTS.md·아키텍처 문서·관련 소스는 자동으로 추가하거나 프롬프트에 넣지 않는다.
AGENTS.md의 조정 지침에 따라 Codex가 이 두 파일을 `logs/harness/`에 준비할 수 있다.

```bash
make agent-workflow-plan FILES_FILE=/tmp/task-files.txt
make agent-workflow TASK_FILE=/tmp/task.txt FILES_FILE=/tmp/task-files.txt

# 실행 중 다른 터미널에서도 현재 단계·역할·모델 확인
make agent-workflow-status
make agent-workflow-status RUN_ID=보고서의_run_id

# 등록된 모델을 사용해 읽기 전용 분석·검토·검증
make agent-workflow TASK_FILE=/tmp/task.txt FILES_FILE=/tmp/task-files.txt READ_ONLY=1

# Jev 접수 API만 생략; 구현·검토 모델은 실제로 호출
make agent-workflow TASK_FILE=/tmp/task.txt FILES_FILE=/tmp/task-files.txt RULES_ONLY=1

# 사용자가 로컬 작업만 요청한 경우
make agent-workflow TASK_FILE=/tmp/task.txt FILES_FILE=/tmp/task-files.txt GIT=0

# 키·네트워크 없이 단계 연결과 작업 사본의 변경만 시연
make agent-workflow-demo
```

기본 `agent-workflow`는 실제 모델을 호출하고 승인·검증 뒤 범위 내 파일을 반영한다.
`WRITE=1`을 별도로 요구하는 개별 `agent-run`과 동작이 다르다.
하네스 Python이 별도 환경이면 `PYTHON=/path/to/python`을 지정한다.
Jev는 등록된 TypeSafe 키로 접수 판단을 요청한다. 키 누락·오류·낮은 확신은
coordinator 계획과 전체 `check`로 넘어가며, 기록에서 fallback을 명시한다.
Claude/GLM의 기존 대화 압축 설정도 유지한다.

Jev 접수의 DNS/전송 실패와 이후 coordinator의 Codex 초기화 실패는 별도 단계다.
예를 들어 `api.typesafe.ai` DNS 조회의 `gaierror(-3)`는 Jev 보고서의
`fallback_reason=network_error`, `diagnostic={"error_type":"gaierror","errno":-3}`로 남는다.
fallback은 Jev 판단 대신 coordinator 계획과 전체 검증이 필요하다는 뜻이며 Jev 연결 성공을 뜻하지 않는다.
계획에 필요한 Codex까지 초기화에 실패하면 workflow는 실패하고 원본 파일은 반영하지 않는다.
필수 전체 `check`는 정상적으로 후속 단계에 도달했을 때 실행기가 수행하며, fallback 기록만으로
계획·검증이 실제 실행되었거나 통과했다고 해석하지 않는다.

Jev의 두 자리 probability·score가 독립적으로 반올림된 경우 probability 합은
`max(0.001, len(options) * 0.005)`, score와 가중평균의 차이는
`max(0.001, 0.005 * (1 + sum(level indices)))`의 절대 오차까지 경계값을 포함하여 허용한다.
상대 오차는 적용하지 않는다.
정확 경계의 이진 부동소수점 표현 오차에만 `FLOAT_COMPARISON_EPSILON=1e-12`를 더한다.
허용 한계를 `1e-10` 초과하는 편차는 계속 거부하며, 원본 반환 숫자는 변경하지 않는다.
3개 score level `0, 1, 2`에서는 각각 `0.015`, `0.02`이며, 정확한 legend를 가진
score `0.07` / probabilities `{'0': 0.94, '1': 0.06, '2': 0.0}` / confidence `0.91`은 `passed`다.
반올림된 probability 합 `0.99`·`1.01`도 이 범위 안이면 허용한다. 원본 probability·score·confidence와
기존 라우팅 임계값을 보존하며 재정규화·score 대체·자동 재시도·모델 변경·네트워크 확대는 하지 않는다.
범위 밖 숫자·bool·NaN·Inf·다른 legend·누락/추가 label·choice 최댓값 위반은 계속 거부한다.
오차 한도를 넘는 응답은 `invalid_response` fallback으로 coordinator 계획과 전체 `check`를 요구한다.
triage의 추천은 허용 응답과 fallback 모두 `execution_allowed=false`이며 에이전트를 실행하지 않는다.

Jev 진단은 허용된 `error_type`과 선택적인 정수 `errno`, HTTP 실패의 정수 `http_status`로 제한한다.
Codex 실패 진단은 `stage`와 고정 `category`로 구분한다. nonzero에서 PATH aliases의 읽기 전용
메시지가 있으면 `path_aliases_read_only`로 분류할 수 있다. 유효 성공에 동반된 경고는 실패 선판정 대신
`warnings=[{"stage":"authentication","category":"path_aliases_read_only"},
{"stage":"execution","category":"path_aliases_read_only"}]`에서 실제 관측된 단계만 기록한다.
인증 경고도 역할 실행 보고서에 전달하며 `model_step`은 결과 전체를 통합 보고서의 `agents`에 보존한다.
경고가 없으면 빈 목록이다. 키·인증 내용·예외 원문·stdout/stderr·원격 오류 응답 본문은 진단에 넣지 않는다.

2026-10-12 [ADR 0007](adr/0007-codex-warning-success-boundary.md)에 따라 인증은 exit0와 정확한
ChatGPT 로그인 상태(API 키 불가), 실행은 exit0·엄격한 JSON event·유효한 비어 있지 않은 최종 응답·
turn.completed·failed/error event 없음을 요구한다. smoke는 nonce 일치도 요구한다. 이 조건을 통과한
warning은 ready/passed를 막지 않으며 nonzero·인증 실패·잘못된/빈/미완료 응답·실패 event·timeout·
nonce 불일치·runtime 생성/정리 실패는 계속 실패다. warning 자체는 성공 근거가 아니다.
`model_step`의 passed 확인과 승인 파일 범위 검사, 후속 새 review/documentation·필수 check·충돌 검사·
apply·Git 역할·게시/CI/merge 게이트를 유지한다. auth runtime 접근 허용·API 키 fallback·재시도·권한 확대는 없다.

이전 일반 실행의 exit0 편집이 stderr 선판정으로 반영되지 않은 사실과 CLI 0.161.0의 메인 무추론 비교
관측은 [모델 연결의 원인 기록](agent-models.md#실패-진단-읽기)에 둔다. 최초 경고를 낸 하위 프로세스는
raw stderr 미보존으로 미확정이며 runtime deny로 인한 하위 초기화 경고 가능성은 추론이다.
[공식 sandbox 문서](https://learn.chatgpt.com/docs/sandboxing)는 spawned commands의 일반 경계 참고이며
PATH aliases 구현의 증거가 아니다. 별도 draft 복구는 일반 경로의 성공 검증으로 취급하지 않는다.
수리 worker는 테스트·workflow·실모델·Git을 실행하지 않았다. 메인/orchestrator가 새 Claude 문서 의미 검토,
full make check·일반 Codex 도구 편집 실호출·Git 역할·PR/CI/merge를 별도로 수행한다.
필드와 분류는 [에이전트 모델 연결](agent-models.md)의 실패 진단 설명을 참고한다.
`agent-doctor`는 로컬 설정·런타임·로그인 상태만 확인한다. 외부 DNS와 실제 모델 연결은 운영자가
명시적으로 요청한 `agent-smoke`/`triage-smoke`로 별도 확인하며, 이때도 네트워크 권한은 자동 확대하지 않는다.
private 런타임이 정상 생성되거나 doctor가 통과해도 외부 DNS 문제가 해결되었다고 보고하지 않는다.

`agent-workflow-plan`은 경로별 담당자와 단계만 보여주며 키 파일·모델을 사용하지 않는다.
`agent-workflow-demo`는 모델 응답과 검증 결과 모두 fixture다. `simulated=true`,
`status=demonstrated`, `agent_started=false`로 기록하며 실제 에이전트나 검증 성공으로 보고하지 않는다.

## 저장 위치와 기존 실행 조회

workflow와 GitHub 게시/정리는 [공유 저장 정책](../harness/storage.py)을 사용한다.
설정은 `HARNESS_STORAGE_CONFIG`의 절대 경로 → 선택적
`ROOT/logs/harness/storage-local.json` → 기존 로컬 기본값 순으로 하나만 선택한다.
추적되는 [JSON 예제](../harness/storage-config.json.example)는 활성 설정이 아니며, private 설정은
Git 제외 logs에 두고 모델 승인 목록에 넣지 않는다. version 1은 정확히 `version=1`, `artifacts`,
`temporary`이며 두 객체는 각각 `path`, `required_mount`, `min_free_bytes`를 갖는다.
절대·정규화·symlink 없는 application 경로는 저장소의 상위/하위 밖에 서로 겹치지 않게 두며
각 실제 required mount의 엄격한 하위여야 한다. 공간 하한은 0 이상의 정수 bytes이고 mount 공유는
가능하다. [하네스 사용법](harness.md#하네스-저장-경로-설정과-진단)에 완전한 JSON·설정 명령과
오류 복구 절차, [ADR 0011](adr/0011-configurable-harness-storage.md)에 결정·대안·비용을 둔다.

기본 workflow root는 `ROOT/logs/harness/workflows`다. 설정 사용 시 새 run의 `workspace/`,
`checks/`, backup·journal·events·모델 보고서는 `artifacts.path/workflows/<run_id>`에 두고,
승인 모델 context는 `temporary.path/tavern-model-context-*/sources`에 둔다.
일반 검증 임시 작업도 temporary root를 사용한다. 인증 home·키와 credential-bearing Codex
`/tmp/tavern-codex-runtime-*`, 로컬 provider/compaction runtime은 유지한다.
전역 `TMPDIR`·실제 `HOME`·`CODEX_HOME`을 NFS로 바꾸지 않는다.

보고서는 지원되는 CLI의 명시적 `--report-dir` → `HARNESS_REPORT_DIR` → artifact/category →
기존 local default 순이다. override는 최종 디렉터리이며 category를 덧붙이지 않는다.
workflow/GitHub CLI에는 `--report-dir`가 없으므로 다음처럼 환경 override를 사용한다.
override는 configured readiness 검사·temporary 경로·local lock·인증 격리를 바꾸지 않는다.

```bash
make storage-status
make storage-doctor
# 유료 모델 없이 기존 run의 상태 조회; run ID 생략 시 모든 조회 root의 latest
HARNESS_REPORT_DIR=/absolute/private/workflows make agent-workflow-status RUN_ID=보고서의_run_id
# Git journal 요청은 main이 기존 게시 흐름에서 준비한다.
HARNESS_REPORT_DIR=/absolute/private/workflows make agent-git-request RUN_ID=보고서의_run_id
```

status/latest와 Git request/accept/resume/cleanup은 현재 report override, configured
`artifacts.path/workflows`, 호출자의 legacy REPORTS, `ROOT/logs/harness/workflows`를 경로 중복 없이
함께 조회한다. latest는 각 root의 유효 `latest.json` pointer와 `report.json` 수정 시각을 비교한다.
다른 root로 탈출하는 pointer, symlink인 root/run/record, 서로 다른 root의 같은 run ID는 오류다.
동일 ID를 임의로 선택하거나 파일을 다시 써서 합치지 않는다. 구성 변경 전의 임의 외부 artifact/
override root를 자동 탐색하지 않으므로 그곳의 기록은 기존 경로를 명시적으로 선택해야 한다.
이를 main이 수행할 때도 다른 조회 root와의 중복 및 readiness 검사와 journal 승인은 유지한다.

조회는 선택된 run/record의 containment와 status metadata를 검증한다. Git journal 재개는 이에 더해
private mode·journal identity·승인 hash·expected SHA·durable snapshot을 다시 확인한다.
journal/report에 기록한 absolute workspace는 그 run의 원래
`workspace`여야 하며 새 root로 재결합하지 않는다. historical approved JSON·snapshot은 수정하지
않고 status 조회도 기존 보고서나 latest pointer를 갱신하지 않는다. 명시적 게시/재개 작업은 기존
journal 계약에 따라 진행 상태만 기록한다. 저장 설정 활성화는 migration·복사·archive·삭제가 아니다.

workflow/apply와 GitHub cleanup은 항상 로컬 `ROOT/logs/harness/workflows/.lock`을 공유한다.
그 뒤 선택한 journal 옆 `<run_id>/github.lock`을 획득한다. artifact root·report override·legacy
위치를 바꿔 별도 project lock을 만들지 않으며 잠금 뒤 run 위치를 재검증한다. 디렉터리 `0700`,
private JSON·events·logs·lock `0600` 정책을 유지한다.

모든 configured mount·free-space floor·기존 application의 소유자/0700을 mkdir나 출력 전에
확인한다. 실제 private probe는 application 안의 고유 0600 파일만 write/fsync/read/delete한다.
한 읽기 전용 경계 안에서만 shared required mount의 공간 측정을 공유하고 두 spec의 floor를
각각 적용한다. 별도 mount는 각각 측정하며 경로·nested mount·private 검사는 생략하지 않는다.
측정과 probe 성공은 public 호출·별도 쓰기·시간 간격·cleanup 경계 간 cache/lease가 아니다.
두 번째 spec 장애도 첫 mutation을 차단하며 생성 뒤 probe 등 다음 쓰기 gate에서도 새로 검사한다.

`python -m harness.storage status|doctor`와 `status(probe=False)`는 mkdir·chmod·probe 없는
조회다. 실패해도 각 spec의 `mount_ready`·측정된 `free_bytes`(floor 미달 값 포함)·
`min_free_bytes` 진단을 유지하며 공간 측정 실패는 null이다. public 반환 형태와 CLI schema는
그대로다. `status/doctor --probe`는 두 기존 private root를 요구하고 각각 새 gate에서 probe한다.
명시적 `prepare()`는 두 root를 준비해 모두 새로 probe한다.

`python -m harness.storage resolve artifacts --prepare`와 일상 `ensure_directory`/임시 할당은
필요한 두 root를 만들되 새 root와 실제 출력/고유 임시 디렉터리만 probe한다. 목적지가 새 root면
최종 출력 gate에서 한 번 probe한다. 올바른 기존 디렉터리의 mkdir 시도와 무관한 기존 root의
반복 probe는 생략하지만 모든 configured readiness/private 검사는 유지한다. 부모 probe에서
자식 writeability를 추정하지 않으며 configured mount 밖의 explicit override도 자신의 private
목적지에서 독립 probe한다. 실패는 다른 root의 성공으로 대체하지 않는다. `probe=False`는
probe를 생략하되 준비 검사는 유지하고 local 기본 동작도 유지한다. 선택 근거와 남은 NFS 지연은
[ADR 0018](adr/0018-storage-check-probe-deduplication.md)에 둔다.
없는 mount 아래 로컬 디렉터리 생성, mount root/unrelated 디렉터리 chmod,
readiness 실패의 legacy fallback을 금지한다. durable checkpoint/snapshot 쓰기 전에도 다시
확인하며 실패한 mount가 돌아올 때까지 승인·merge SHA·복구 기록을 보존하고 성공을 주장하지 않는다.

실패한 실행의 수동 정리는 프로세스 종료·pending publication/cleanup·승인 snapshot 필요 여부를
main이 확인한 별도 운영 작업이다. 역사적 absolute 경로를 임의 이동하면 재개 검사가 실패하므로
설정 작업의 부수 효과로 journal/workspace/backup을 이동·삭제하지 않는다. 기존 사용자 편집과
운영 cron·unpack·JSON·DB는 보존한다. 이번 실행은 최신 사용자 선택대로 기존 configured NFS
설정·mount·floor를 유지하며 activation 변경이나 local storage override를 하지 않는다.
private 설정 bytes/mode·mount options·required mounts·환경·모델/provider 및 기존 GitHub 정책도
유지한다. 합성 FakeFS의 공유/별도 mount·cold/warm 호출 수 회귀는 실제 NFS benchmark가 아니다.
새 Claude 의미 검토와 mandatory full offline `make check`(selected skip/xfail 0), 충돌을 확인한
scoped apply는 orchestrator가 맡는다. 최종 소스의 호출 수 감소·private 설정 불변 확인과 기본
Git 역할, 기존 request/accept·실제 required CI success 세 개·고정 head squash merge·정확한
branch cleanup은 main/orchestrator의 기존 책임 경계를 유지한다.
현재 문서 작성은 checks·CI·merge 성공의 증거가 아니다.

## 검토와 검증 기준

업무 시작 시 문서 영향을 판단한다. 구조·책임·데이터 계약·격리·검증·실패 복구·GitHub 게시
정책 변경은 관련 설계·경계 문서를 갱신한다. 주요 선택은 신규 또는 대체 ADR를 작성하고,
기존 결정은 삭제·재작성 대신 superseded와 대체 ADR 링크로 보존한다.
[전체 설계서](harness-design.md)와 [ADR 작성 규칙](adr/README.md)을 기준으로 사용한다.
단순 오타나 동작 불변 국소 수정은 문서 갱신이 불필요할 수 있지만 검토에 구체적 이유를 남긴다.
planner·worker·reviewer 모두 이 기준을 받고 Jev 직접 배정도 worker·reviewer 기준을 받는다.
이 지침은 승인 밖 문서를 읽는 허가가 아니다. 필요한 문서가 scope 밖이면 worker는 정확한
누락 경로를 보고하고 reviewer는 기존 승인 파일에 finding을 귀속하여 승인을 거부한다.
메인이 문서 범위를 확인·승인한 뒤 새 실행을 준비한다. 문서를 자동 복사·열람·생성하거나
수정 라운드에서 범위를 늘리지 않는다.

계획은 선언된 파일을 정확히 한 번씩 담당 역할에 배정해야 한다. 모델이 새로운 파일을
추가하거나 소유 영역을 바꾸면 실행을 중단한다. 범위가 부족하면 `/root`가 원인을 확인하고
필요한 소스·테스트·문서를 포함해 새 실행을 준비한다.

coordinator 계획의 JSON 문법·스키마 오류만 `max_plan_attempts=2` 안에서 coordinator에게
다시 요청한다. 이 한도는 `max_rounds`와 독립적인 정수이며 1..3만 허용한다.
재요청에는 고정된 `json_syntax`/`plan_schema` 분류와 신뢰한 스키마 안내를 넣고,
JSON 문법 오류에는 숫자 line/column/position도 넣는다. 짧고 완전한 새 JSON 객체와
올바르게 escape한 task 문자열을 요구하며 잘못된 응답 원문이나 예외 메시지를 재전송하지 않는다.
승인 파일·소유 역할과 엄격한 계획 검사를 그대로 유지한다. 범위·소유 역할 위반,
planner 쓰기, CLI 실패는 재시도 대상이 아니다. 한도 내에서도 유효한 계획을 얻지 못하면
구현·반영·게시 없이 종료한다. 시도·오류 분류·복구 여부는 private 보고서와 진행 이벤트에 남는다.

reviewer의 정상 CLI 응답만으로 승인 처리하지 않는다. 최상위 JSON은 정확히 `verdict`,
`summary`, `findings`, `documentation`을 갖는다. `summary`는 공백 제외 비어 있지 않은 문자열이며,
`findings`는 최대 32개로 각 항목에 정확히 `file`(승인 파일), `severity`(high/medium/low),
`message`(공백 제외 비어 있지 않은 문자열)를 둔다. `approved`는 빈 findings,
`changes_requested`는 비어 있지 않은 findings를 요구한다. 읽기 전용 역할이 파일을 바꾸면 실패다.

`documentation`은 정확히 `status`, `files`, `reason`을 갖는다. `reason`은 공백 제외
비어 있지 않은 문자열이고 `files`는 중복 없는 승인 범위의 `.md` 경로 목록이다.

| status | 문서 판단과 게이트 |
| --- | --- |
| `updated` | 실제 변경 `.md` 파일을 최소 하나 참조한다. scope 밖·비문서·미변경 경로는 거부한다. 문서가 수정돼도 다른 finding이 있으면 수정 요청이다. |
| `not_required` | `files=[]`이며 문서 갱신이 불필요한 구체적 이유를 적는다. 다른 코드 finding에 의한 수정 요청과도 함께 쓸 수 있다. |
| `missing` | 필요한 문서·내용 또는 승인 문서 범위가 부족하다. `changes_requested`와 기존 승인 파일에 귀속 가능한 finding을 요구하며 approved는 거부한다. files는 빈 목록 또는 승인된 `.md` 경로다. |

```json
{"verdict":"approved","summary":"검토 완료","findings":[],"documentation":{"status":"not_required","files":[],"reason":"표시 오타만 고쳤으며 구조·계약·검증·사용법은 그대로다."}}
```

필수 필드 누락·잘못된 스키마·verdict 모순은 fail closed로 종료한다. 문서 판단 형식 오류를
임의 승인이나 계획 JSON 복구 대상으로 취급하지 않는다. 파일 확장자·변경 목록 검사는
증거 경로를 제한할 뿐 문서의 의미적 완전성을 증명하지 않는다. 영향과 생략 근거의 적절성은
reviewer가 판단한다. read_only·demo도 이 필드를 반환하며 원본 변경·외부 호출을 추가하지 않는다.
통합 보고서의 `review.documentation`과 private 모델 응답에 판단을 보존한다.
이번 importer/cleanup 변경의 매 orchestrator review는 `documentation={status,files,reason}`과
`status=updated`를 요구한다. 실제 변경된 승인 Markdown을 참조하고 설정·격리·잠금·legacy 복구와
ADR0011/0012/0013 및 architecture·data-contracts·harness·workflow의 의미적 완전성을 판단한다.
기존 ADR0010의 Git cleanup·전체 완료 정책은 대체하지 않는다.
수정 요청은 finding 파일을 맡은 **정확한 구현 task**에만 전달한다. 검증 실패도 승인된
실패 파일을 찾으면 그 파일을 맡은 task에만 전달하며, 같은 역할의 다른 task나 관련 없는
downloader 작업을 다시 호출하지 않는다. 각 task에는 자기 파일의 finding·진단만 전달한다.
수정 뒤에는 **새 reviewer 검토와 최초의 모든 필수 검사**를 다시 요구한다.
문서 finding도 같은 task 범위·`max_rounds`·새 검토 규칙을 따른다.

검증 피드백은 per-check `failures`/`errors`/`skipped`와 traceback의 위치 토큰을 로컬에서
필터링하여 만든다. 허용된 명령명, 고정 분류, 허용 목록의 예외 타입, 승인 파일/줄 번호,
승인 소스에서 확인한 함수명과 줄 번호를 붙인 짧은 주변 소스만 전달한다.
소스는 이미 승인된 모델 사본에서만 읽는다. 절대 traceback 경로는 이번 로컬 검증 사본
안에 있는 정확한 경로만 인정하며 suffix 일치, `..`, symlink, 다른 root, 범위 밖 파일,
유효하지 않은 줄 번호는 거부한다. 진단은 최대 24개, 소스는 진단마다 최대 7줄·줄당 240자,
함수명은 최대 80자로 제한하며 등록된 키는 프롬프트 전송 전에 추가로 제거한다.
원래 reason/longrepr, parameter가 붙은 test identifier, 임의 예외 메시지, 로그 내용,
실행 중 값, 외부 경로, 승인 밖 소스는 전달하지 않고 private 검증 보고서에만 남긴다.
이 필터는 런타임 값을 추론하거나 원인을 확정하지 않으며, 승인 소스 자체의 내용은 모델이
읽도록 승인된 정보다. API 키 치환만으로 로그를 안전한 모델 입력으로 취급하지 않는다.

위치를 확인할 수 없는 실패는 `context=unavailable`, `attribution=unattributed`로 명시한다.
이 경우 남은 라운드 안에서 최초 task 전체에 원인 없는 고정 메타데이터만 전달하는 보수적인
fallback을 사용한다. 확인된 다른 task의 소스·진단은 섞지 않고 승인 범위를 늘리지 않는다.
로그·collection 오류에 위치가 없거나 진단 한도를 넘는 경우도 이 fallback에 포함한다.
추가 정보가 필요하면 task는 부족한 문맥을 보고하며 `/root`가 로컬 로그를 조사하고 필요한
개별 파일을 승인한 새 실행을 준비한다. 어떤 경우에도 기존 필수 검사를 줄이지 않는다.

각 실패는 이동한 줄 번호·주변 소스를 제외한 안정적인 fingerprint, 대상 파일/task,
라운드, 직전 구현 시도의 실제 소스 변경 여부와 함께 기록한다. 동일 실패 재발과 직전
소스 무변경은 해당 task의 피드백에 명시한다. private 보고서·이벤트에는 task별 피드백과
전송 여부, 구현 전후 hash도 남는다. 마지막 라운드에서도 실패하면 `no_progress`
(동일 실패와 소스 무변경) 또는 `exhausted_repair`로 종료하고 원본을 보존한다.
`harness/workflow-config.json`의 `max_rounds=2`가 총 구현 라운드 한도다.
한도를 넘거나 모델 실행·범위 검사에서 실패하면 원본을 반영하지 않고 종료한다.
검토 출력 형식 오류도 실패이며 계획 출력만 위의 제한된 복구를 허용한다.
읽기 전용 실행은 검토·검증 실패를 재수정하지 않는다.

검증 명령은 실행기의 허용 목록에서만 선택하며 모델 응답으로 셸 명령을 실행하지 않는다.
경로 규칙·Jev 추천·계획의 파일 소유 영역 중 가장 넓은 필수 검증을 유지한다.
계약·하네스·영역 간 작업과 coordinator fallback은 전체 `check`를 실행한다.
종료 코드뿐 아니라 이번 실행의 JSON에서 실제 선택된 테스트 수, 성공 수, 실패·오류·skip을 검사한다.
빈 검사·skip/xfail·누락 보고서·이전 성공 결과는 통과로 처리하지 않는다.
검증이 소스 파일을 변경한 경우에도 반영을 중단한다.

## 사용자 변경과 실행 경계

**모델 사본**은 공유 정책의 context root 아래 `tavern-model-context-*/sources/`에 명시한 파일만
현재 내용 그대로 복사한다. 설정이 없으면 `/tmp`, 설정이 있으면 `temporary.path`를 사용한다.
전체 저장소의 파일 목록을 탐색해 추가하지 않으며, 모델 실행의 cwd도 이 사본으로 제한한다.
원본 저장소의 상위 지침이 자동 발견되지 않도록 저장소 밖에 만든다.
`model-context.json`에는 승인 목록과 실제 복사한 파일의 hash·권한을 남긴다.
새 파일이나 삭제한 파일은 목록에는 남되 실행 전 사본에 내용이 없다.

Codex는 `:root=deny`, `:minimal=read`, 모델 사본에 읽기 전용 실행은 `read`, 편집 실행은 `write`인
별도 권한 프로필을 사용한다. 승인 소스만 있는 사본에는 Git metadata와 사용자 신뢰 기록이 없으므로
`--skip-git-repo-check`를 전달하며 파일 권한이나 승인 범위를 확대하지 않는다.
실행에 필요한 설치된 Codex 바이너리와 해당 셸 실행 파일만 추가로 읽게 한다. CLI 인증·하네스 설정·압축 플러그인은
실행기가 사용하는 런타임이며 원본 소스를 모델용 context로 제공하는 경로가 아니다.
Codex CLI는 호출마다 쓰기 가능한 private 임시 런타임을 사용한다. 루트·하위 런타임 디렉터리는
`0700`, 기존 로그인에서 복사한 유일한 인증 파일 `auth.json`은 `0600`이다.
자식의 `CODEX_HOME`·임시 경로·XDG 경로만 분리하고 기존 로그인·설정과 부모 환경을 보존한다.
사용자 설정·지침·skill·다른 인증 파일·keyring은 복사하지 않고 인증 사본의 갱신도 원본에 반영하지 않는다.
로그인 확인과 해당 역할 실행 동안만 사본을 유지하고 성공·실패·timeout 뒤 정리한다.
생성·정리 실패는 실행 실패이며 실제 사용자 home으로 fallback하지 않는다.
강제 종료로 남은 런타임은 프로세스 종료를 확인한 뒤 별도로 정리한다.
임시 `runtime_root`는 workspace 안에 있더라도 모델 권한 프로필에서 명시적으로 `deny`한다.
원본 인증 home(original auth_home)은 `:root=deny`로 보호하고 별도의 directory deny를 추가하지 않는다.
Linux의 directory deny는 auth_home 아래 standalone CLI·셸 실행 파일의 좁은 read 예외까지 가려
실제 파일 도구에 permission denied를 일으킬 수 있다. 실행 파일을 포함하는 디렉터리 전체를 허용하지 않는다.
workspace와 original auth_home을 resolve한 뒤 workspace가 auth_home과 같거나 이를 포함하는 상위 경로이면
`unsafe_workspace`로 거부한다. symlink와 `..`로 표현한 경로에도 이 조건을 적용한다.
모델의 승인 파일 읽기 범위와 `network.enabled=false`를 유지하며 DNS 제한을 자동 해제하지 않는다.
런타임 격리는 CLI 초기화 쓰기를 분리하는 조치이고 외부 Jev DNS 복구를 보장하지 않는다.
기존 `--sandbox read-only`는 원본 파일 읽기를 제한하지 않으므로 이 프로필과 함께 사용하지 않는다.
사용자 설정·프로젝트 지침 자동 로딩·웹 검색·앱·브라우저·컴퓨터 도구·호스트 skill 검색을 끈다.
지원하지 않는 프로필/CLI 옵션이나 샌드박스 실패는 실행 실패로 처리하며 넓은 읽기 권한으로 재시도하지 않는다.
Claude/GLM은 `--restricted`와 Read/Glob/Grep(+편집 시 Edit/Write)만 사용해 파일 도구를 cwd에 제한한다.
추가 읽기 디렉터리를 허용하지 않고 메모리·CLAUDE.md 로딩, 외부 MCP, 권한 확대 요청을 끈다.
압축 플러그인은 신뢰한 실행기 런타임에서 로딩하고 모델 소스 사본에는 복사하지 않는다.
CLI 권한 프로필의 동작은 [공식 Codex 문서](https://learn.chatgpt.com/docs/permissions)를 참고한다.

**로컬 검증 사본**에는 Git의 추적 파일과 무시되지 않은 새 소스를 현재 내용 그대로 복사한다. 커밋되지 않은
사용자 수정과 삭제를 보존하고, 원래 저장소의 Git metadata·API 키·`.env`·운영 INI·인증 파일,
게임 patch/unpack·JSON·번역·지역별 Python 환경·백업은 작업 사본에서 제외한다.
`harness/pytest.ini`는 인증 정보가 없는 필수 검증 설정이므로 복사한다.
`logs/harness/storage-local.json`과 환경 override로 선택한 private 설정은 모델 소스로 제공하지 않는다.
신뢰한 검증 실행기는 모델 사본 밖에 private `0600` 파생 `storage-validation.json`을 만들어
검증 자식에게만 전달한다. 검증 소스 root와 겹치지 않는 application 경로에 같은 required mount와
공간 하한을 적용하고 runner 자식의 비인증 TMPDIR/TMP/TEMP 및 pytest basetemp를 지정한다.
모델 연결 계층은 모델 자식의 `HARNESS_STORAGE_CONFIG`·`HARNESS_REPORT_DIR`를 제거해야 하며,
reviewer는 이 경계가 실제 구현·회귀에 반영됐는지 확인한다. 검증에 필요한 private 설정을 모델
context에 복사하거나 읽기 scope를 넓히는 것으로 해결하지 않는다.
이 사본을 모델의 cwd·추가 읽기 디렉터리로 제공하지 않는다. 모델의 범위 내 변경만 여기로 옮겨 검증한다.
작업 사본에는 기존 Git ignore 회귀 검사를 위한 빈 일회용 Git 저장소만 만들며 호스트 Git template도 복사하지 않는다.
개별 범위 파일과 복사할 소스의 symlink를 거부한다.
Claude Code가 자동 생성하는 `harness/compaction/.claude-plugin/types/`는
캐시·진행 로그처럼 실행 산출물로 제외하며 편집·반영할 파일 범위로 지정할 수 없다.

파일 반영 직전에 모든 복사한 원본 소스의 hash·권한과 목록이 실행 전 상태와 같은지 확인한다.
다른 편집이 있으면 새 내용을 보존하고 중단한다. 이전 내용은 private backup에 남기고,
파일별 임시 쓰기·교체를 사용한다. 도중 실패하면 실행기가 이미 반영한 자신의 변경만 복구한다.
여러 파일 교체는 파일별 원자 처리이며 저장소 전체의 원자 트랜잭션은 아니다.
고정 로컬 `ROOT/logs/harness/workflows/.lock`으로 workflow와 GitHub cleanup을 직렬화한다.
선택된 run의 journal lock은 그 옆에 유지한다. 외부 편집기는 hash 검사로 확인한다.

작업 사본 자체는 별도 VM이나 컨테이너가 아니다. 모델의 원본 소스 읽기 제한은 위 CLI 권한 설정에
의존하며, 인증과 신뢰한 CLI 런타임까지 격리하는 일반 목적 컨테이너를 제공하는 것은 아니다.
scoped 담당 worker는 승인 파일만 읽고 기존 사용자 수정을 보존하며 부족한 파일 범위를 보고한다.
검증은 orchestrator가 수행한다. worker는 테스트·`make check-*`·`harness.workflow`·`agent-run`·
cron·다운로드·운영 import(`importAll` 포함)·재위임을 실행하지 않는다.
기본 검증은 합성 입력·임시 JSON·SQLite 메모리 DB다. 운영 DB·실데이터·MySQL·브라우저 검증은
각각 명시적인 추가 실행으로 구분한다. 배포는 이 흐름에 포함하지 않는다.
기본 쓰기 작업의 GitHub 커밋·PR·병합은 아래 메인 Codex의 앱 연결로 이어 실행한다.
머지 후 정리도 메인 책임이며 worker·reviewer가 Git·정리·workflow를 실행하거나 재위임하지 않는다.
`READ_ONLY`·demo·`GIT=0`에서는 원격 게시·삭제 및 로컬 refs 정리를 자동 실행하지 않는다.
공급자 오류 시 유료 모델 전환이나 Opus escalation을 자동 호출하지 않는다.
호출별 Claude 예산과 라운드 한도는 유지하며 중앙 월 예산 집계는 별도 범위다.

## 진행과 결과

각 단계는 `[4/8 담당 에이전트 실행] running · parser / codex / gpt-6.1-sol`처럼 즉시 출력한다.
Jev 직접 배정에서는 계획 단계가 `direct`, Jev 실패에서는 판단 단계가 `fallback`이다.
검토의 `responded`는 모델 응답 완료이고 `approved`가 실제 승인이다.
`report.json`의 `current`와 `events.jsonl`에서 실제 실행된 역할·공급자·모델과 단계 상태를 확인한다.
메인 `/root`는 이 결과를 읽고 진행 상황을 사용자에게 알린다.

공유 정책이 선택한 workflow root의 `<run_id>/`에 보고서, baseline hash, scoped diff, 검증 JSON·로그,
로컬 검증 사본과 반영 전 backup을 보관한다. `model_workspace`는 저장소 밖 모델 사본의 위치,
`model_read_scope`는 외부 분석 승인 목록이다. 상위 디렉터리는 `0700`, 통합 보고서·진행 기록·로그는
`0600`이며 등록된 API 키 값은 보고서와 요청의 작업 텍스트에서 제거한다.
작업 본문은 hash로 기록하고 계획·모델 응답은 private 보고서 안에만 둔다.
장기 설계와 주요 결정은 Git 관리 `docs/harness-design.md`·`docs/adr/`에 별도로 남긴다.
private 계획·응답·로그는 설계 문서나 ADR를 대신하지 않으며 그대로 공개 문서에 복사하지 않는다.
실패한 작업 사본은 조사를 위해 남는다. 저장 공간 관리는 운영자가 프로세스 종료와 복구 기록의
필요 여부를 확인한 뒤 수행한다. 보고서의 실제 `model_workspace` 경로도 확인하며 configured
context가 `/tmp`에 있다고 가정하지 않는다. 저장 설정 자체가 과거 자료를 자동 정리하지 않는다.
`passed`는 해당 모드의 완료 상태이고 `failed`/`interrupted`는 실패다.
GitHub 활성 작업은 merge 응답과 확정 SHA를 보존한 뒤 cleanup까지 완료해야 passed다.
report.github의 merge_status/merge_sha와 cleanup의 remote/local/prune/sync/completion 결과를 함께 확인한다.
정리 proof 대기는 step=cleanup_*의 awaiting_github이며 실패·보류는 cleanup_pending이다.
이전 merged → passed 보고서는 새 status 조회에서 legacy_cleanup_required로 표시하며 기록을 덮어쓰지 않는다.
명시적 request/resume/cleanup으로 새 proof를 얻고 실제 정리를 수행해야 새 완료 기준을 만족한다.
`awaiting_github`는 앱 실행 대기,
`awaiting_ci`는 이미 생성한 PR의 CI 대기다. 프로세스를 강제 종료해 마지막
`running` 기록이 남았어도 상태 조회에서 PID가 더 이상 존재하지 않으면 `abandoned`로 표시한다.

## GitHub에 자동 반영

이 저장소의 기본 대상은 `21in7/TavernofSoul`, 기준 브랜치는 `master`다.
기존 `codex/<run_id>` → `master` squash PR 정책을 유지한다. [ADR 0010](adr/0010-automatic-post-merge-cleanup.md)에
따라 별도 릴리스 통합 요구가 없는 이번에는 `dev`를 만들지 않는다. `dev` 통합도 작업 브랜치 정리는
필요하며 추가 PR·CI·통합 책임을 만든다.
`harness/git-publish-config.json`에 대상과 필수 검사를 명시한다. 서버 GitHub 토큰을 새로 요구하지 않고
메인 Codex의 인증된 GitHub 앱을 사용한다. 실행 전에 메인은 해당 저장소의 앱 쓰기 권한을 확인한다.
`make agent-git-doctor`는 정책과 origin 일치만 검사하며 API 인증 성공을 뜻하지 않는다.
모델은 승인 소스를 읽어 commit_message·pr_title·pr_body만 반환한다. 저장소·브랜치·변경 파일·머지
방식은 모델 응답으로 결정하지 않는다. GitHub 토큰 환경 변수도 모델과 로컬 검증에서 제거한다.

메인은 `awaiting_github` 보고서의 run_id로 다음 요청을 읽고 반환된 앱 도구와 인자를 실행한다.
앱 응답은 private JSON 파일에 기록하여 request_id와 함께 돌려준다. 메인이 이 과정을 계속 수행하므로
사용자가 커밋·push·PR·merge 명령을 별도로 입력할 필요가 없다. CLI 단독 실행에는 앱 도구가 없어서
메인 Codex가 이어받을 때까지 대기하며, 서버의 상주 GitHub 봇을 설치하는 기능은 포함하지 않는다.

```bash
make agent-git-doctor
make agent-git-request RUN_ID=보고서의_run_id
# 메인 Codex가 반환된 request.tool(request.arguments)을 GitHub 앱으로 실행한 뒤:
make agent-git-accept RUN_ID=보고서의_run_id REQUEST_ID=요청_id RESPONSE_FILE=/private/path/response.json
make agent-git-resume RUN_ID=CI_또는_cleanup_대기중인_run_id
make agent-git-cleanup RUN_ID=이미_merged된_run_id
```

`github.json`은 대상·변경 내용·기준 SHA·단계·CI 결과를 private 로그에 기록한다. 별도 private
`github-approved.json`에 검토·검증된 파일 hash·권한과 게시 정책을 고정하며, 로드한 journal을 그 사본과
비교한다. journal과 승인 파일은 `0600`이어야 한다. 각 조회에도 새 무작위 요청 ID를 부여해 이전
조회 응답의 재사용을 막고, lock으로 동시에 같은 journal을 조작하지 못하게 한다.
응답 처리에서 반환된 다음 요청을 그대로 실행한다. 이미 전달한 쓰기의 `request`를 다시 호출하면
`needs_reconciliation`으로 중단하며 자동으로 같은 PR 생성·커밋 등을 다시 보내지 않는다.
응답 파일이 사라지거나 쓰기 결과가 모호하면 그 상태를 기록한다. 원래 요청 ID와 일치하는 실제
성공 응답이 뒤늦게 도착한 경우에는 확인 후 진행할 수 있다. PR은 실패·대기 중에도 앱 작업에 연결한다.
수정 라운드의 실패 기록은 남기되 GitHub 게이트와 PR 설명에는 마지막 성공한 라운드의 검증을 사용한다.

브랜치 생성 도구가 이름만 반환하면 실행기는 Git ref를 별도로 조회해 실제 SHA가 고정된 head와
일치하는지 확인한 뒤 PR을 생성한다. 이 확인에 실패하면 브랜치를 재생성하거나 PR을 열지 않는다.

앱 게시 단계는 로컬 index·브랜치·기존 staged 변경을 건드리지 않는다. 머지 후 로컬 정리·동기화는
아래 별도 안전 조건을 따른다. 원격 기준 tree에서 해당 작업의 시작 파일
blob SHA와 권한을 확인한 뒤 변경 파일만 새 tree에 넣는다. 기준 tree는 변경 파일에 필요한 경로만
디렉터리별로 조회하므로 큰 게임 데이터의 전체 재귀 트리를 요구하지 않는다. 조회한 tree가 잘리면 중단한다.
새 `codex/<run_id>` 브랜치를 커밋 SHA에
생성하는 방식으로 push와 같은 게시 결과를 만든다. 모델 승인 범위 밖 파일과 기존 사용자 수정은
함께 게시하지 않는다. 기준 파일이 이미 수정됐거나 원격에 없는 기존 파일이면 쓰기 전에 중단한다.
현재 로컬에서 처음 만든 하네스·CI 파일을 게시하려면 초기 등록 파일 목록을 따로 확인해야 한다.
CI 정의가 원격에 없어서 필수 검사가 실행되지 않은 경우도 성공으로 간주하지 않는다.

PR은 pinned base/head와 같은 저장소인지 재확인하며 변경되면 재검증을 요구한다.
GitHub Actions의 `Offline harness (SQLite)`, `MySQL harness`, `Chromium browser harness`가 모두 실제
`success`여야 한다. 실행 중·누락·다른 앱이 만든 동명 검사·skip·neutral·실패·취소는 머지 성공이 아니다.
check-runs의 모든 페이지를 읽고 중복 ID·불완전한 coverage를 거부하며 같은 이름의 최신 실행만 판단한다.
테스트 merge SHA에 검사가 있으면 그 결과를 사용하며 없으면 head SHA 검사로 판단한다.
head와 테스트 merge 양쪽 SHA의 commit status 실패를 차단하고, 최종 PR 조회에서 테스트 merge SHA가
달라졌으면 새 SHA의 CI를 다시 확인한다.
필수 리뷰나 저장소 규칙이 남아 있으면 `mergeable_state=clean`까지 대기한다. 충돌·기준 변경은 중단하며
force·관리자 우회·저장소 보호 설정 변경은 하지 않는다. 머지 API에도 expected_head_sha를 전달한다.
API가 `merged=true`와 유효한 merge SHA를 반환하면 merge_status=merged와 확정 merge SHA를
먼저 durable journal에 기록하고 아래 cleanup proof를 자동 요청한다. 정리 완료 전 passed가 될 수 없다.
확정 merge SHA를 테스트 merge SHA와 구분한다.
30분 동안 검사와 규칙이 완료되지 않으면 PR을 보존하고 `awaiting_ci`로 기록한다.
`agent-git-resume`은 새 모델 호출·새 커밋·새 PR 없이 그 PR을 다시 확인한다.

## 머지 후 브랜치 정리

merge accept는 다음 fetch 요청을 반환한다. 메인은 게시 때처럼 기존 GitHub 앱 읽기 요청을 계속 실행한다.
PR을 재조회해 merged=true/closed, PR 번호·repository·base.ref·head.ref/head SHA·확정 merge SHA를
확인한다. base.sha는 머지 이후 바뀔 수 있다. 고정 head/test merge의 세 required CI와 commit statuses를
다시 확인한 뒤 repository를 새로 조회해 default_branch를 확인하고 branch 전체 페이지와 정확한
head query의 열린 PR 페이지를 조회한다. 현재 default_branch가 작업 브랜치이면 정리를 보류한다.
REST 배열은 per_page=100의 명시적 query 응답으로 처리하며 100개 페이지는 다음 페이지를 요구한다.
wrapper는 complete/page/per_page/truncated coverage를 증명해야 한다. 중복 branch, 잘린 응답,
페이지 한도, malformed/실패 응답은 fail closed이며 빈 object/읽기 실패를 ref 부재로 해석하지 않는다.

마지막 proof accept가 신뢰한 parent의 `git_cleanup.execute`를 자동 호출한다. 별도 수동 명령이
기본 흐름의 필수 단계는 아니다. 정리 대상은 그 run의 codex/<run_id> 하나이며 기본/base/main/dev,
protected·열린 PR·tip 전진·다른 worktree 사용 브랜치는 보존한다. branch가 이미 없는 경우에도 실제
Git ref 부재를 확인한다. GitHub 앱의 쓰기 도구는 기존 게시·PR·merge 허용 목록 그대로다.

### 원격 전송과 prune

origin의 raw URL/pushurl과 Git URL rewrite 후 실제 fetch/push URL 모두 승인 repository의
credential-free URL 하나여야 한다. 새 계정·token·credential 파일을 요구하거나 수집하지 않는다.
Git 인자 배열(shell=False), 60초 timeout, GIT_TERMINAL_PROMPT=0와 명시적 submodule recursion 차단을
사용한다. 첫 fetch부터 모든 fetch/prune 전에 origin heads → origin tracking의 표준 mapping을 검증한다.
명시적 fetch refspec도 configured refmap의 추가 목적지를 갱신할 수 있으므로 다른 mapping은 전송·삭제
전에 prune.reason=unsafe_prune_refspec의 cleanup_pending으로 보류한다.
fetch는 base의 정확한 remote-tracking 목적지만 갱신하며 확정 merge가 그 이력에 있어야 한다.
원격 ref를 조회한 뒤 `git push --recurse-submodules=no --force-with-lease=refs/heads/<branch>:<head_sha>
origin :refs/heads/<branch>`로 삭제한다. 이는 정확한 ref의 compare-and-delete이며 내용 강제 push,
--force/--no-verify/광범위 push·보호 변경을 허용하지 않는다.

삭제 시도는 보내기 전에 checkpoint에 기록한다. 성공 응답·실패·timeout 모두 실제 ref를 재조회한다.
resume은 먼저 부재/동일 SHA/변경 SHA로 재조정한다. 모호한 시도 뒤 동일 SHA가 남으면
remote_delete_unresolved_same_sha로 보류하고 자동 재전송하지 않는다. 변경 SHA는 보존한다.
인증/조회 실패도 부재가 아니다. parent가 실제 삭제를 별도로 확정하면 다음 resume에서 부재로 이어갈 수 있다.
원격 부재 후 fetch/prune 및 remote prune을 수행하고 정확한 tracking ref 부재를 확인한다.
prune mapping은 origin의 heads를 origin tracking으로만 매핑하는 표준 refspec이어야 하며 다른 mapping은 보류한다.

### 로컬 보존과 승인 변경

worktree list는 Git 2.25의 --porcelain을 사용한다. C-quoted 특수 경로는 바이트로 해석하고
불명확·locked/prunable 기록은 보류한다. 모든 worktree의 operation 조회와 다른 worktree status는
읽기만 수행한다(GIT_OPTIONAL_LOCKS=0). base 점유, staged/untracked·사용자 편집, local-only commit,
다른 checkout/detached, diverged base와 operation 중인 상태는 해당 로컬 단계를 보류한다.
ignored 파일/디렉터리나 symlink 부모가 target tree 경로와 충돌해도 보존한다. 운영/보호 경로 변경을
동기화 부수 작업으로 적용하지 않는다. 안전한 원격 삭제의 부분 결과는 남는다.

clean한 승인 checkout은 base 전환 → submodule recursion 없는 fetch/prune → merge --ff-only →
정확한 작업 ref 삭제로 진행한다. squash에서도 GitHub proof, 동일 tip·추가 commit 없음·merge 이력·
worktree 미사용을 재확인하고 update-ref -d <ref> <expected SHA>로 원자적 비교 삭제한다.
branch -D·generic reset --hard·clean·전체 add·자동 stash는 사용하지 않는다.
로컬 작업 ref가 없으면 absent로 기록한다. 최신 clean master에 해당 merge가 포함되면 재실행도 완료할 수 있다.

앱이 반영한 edit/add/delete/executable 변경만 미커밋으로 남는 경우 github-approved.json의
before/after fingerprint·정책·index 상태, baseline과 local HEAD 관계, merge 및 fetched base tree의
blob/mode와 ROOT의 현재 bytes/POSIX permissions를 파일별로 대조한다. Git 100644/100755는 POSIX
전체 mode가 아니라 실행 비트로 비교한다. approved 밖 변경·같은 파일 사용자 편집·symlink·remote
bytes/mode 차이는 보존한다. 승인 additions만 ordinary untracked 상태로 예외 처리할 수 있다.

### 체크포인트·복구·완료

로컬 `ROOT/logs/harness/workflows/.lock` → 선택된 journal 옆 `github.lock` 순서로 apply/cleanup
동시 실행을 막는다. 설정/legacy 위치가 달라도 같은 project lock을 사용한다. github.json에 merged와
확정 SHA를 먼저 fsync/atomic replace로 보존한 뒤 cleanup.json과 cleanup-backup/에 단계·시도·승인
snapshot을 private durable 기록으로 남긴다(디렉터리 0700, 파일 0600). 승인 변경을 일시 baseline으로
되돌리는 경우 파일별 before/after 상태를 재확인하고 baseline 복원 → ff-only → synced checkpoint로 진행한다.
중단 시 backup을 지우거나 generic rollback을 실행하지 않는다. restore.phase와 snapshot hash를 확인하고
현재 파일이 승인 after 또는 이미 복원된 before인 경우만 이어간다. ff-only 직후 crash는 실제 HEAD/tree로
재조정한다. 동기화 전 baseline 복원 재개는 새 fetched base의 승인 파일 blob/mode도 다시 대조한다.
사용자 편집·snapshot 불일치·권한 실패는 보류하고 복구 근거를 남긴다. 로그에는 Git
stdout/stderr나 credential을 공개하지 않으며 고정 이유 코드만 report에 노출한다.

원격/로컬 deleted 또는 absent, prune/sync/completion complete와 마지막 clean base/ref 재확인이 모두
있어야 cleanup=complete 및 report.status=passed다. 실패·부분 정리·보존은 cleanup_pending과 non-success다.
cleanup 실행 진입의 report/approval 읽기 실패도 merged 사실과 SHA를 유지한 cleanup_pending으로 처리한다.
외부 편집/프로세스 경쟁은 완전히 잠기지 않으므로 각 위험 단계와 완료 직전에 다시 검사한다.

agent-git-resume은 awaiting_ci이면 기존 PR의 CI를 이어 확인하고, merge_sha가 있으면 새 proof부터
정리를 재개한다. 새 모델/commit/branch/PR/merge 요청을 만들지 않는다. agent-git-cleanup은 이미 merged된
run을 명시적으로 재확인한다. github-v1 설정과 journal format은 유지하며 cleanup-v1 필드를 추가한다.
이전 모듈로 prepare됐거나 merged/done/passed인 journal도 request/resume/cleanup에서 새 proof로 이행하며
이전 passed 자체는 새 완료 증거가 아니다. 기존 승인 snapshot과 journal identity 검사는 계속 필요하다.
READ_ONLY/demo/GIT=0/게시 비활성/변경 없음/child에서는 정리 side effect를 실행하지 않는다.

[실제 Git 회귀](../harness/test_git_cleanup.py)는 임시 저장소/bare origin과 synthetic GitHub proof로
삭제/fetch/prune/ff-only·승인 변경·복구·경쟁·권한 실패를 검증한다. file transport는 Python test seam에만
허용되며 production URL 검증은 완화하지 않는다. 호스트 config/identity/auth/hooks/template 및 외부망을
차단한다. scoped worker는 이 테스트를 실행하지 않는다. 새 Claude의 documentation.updated 의미 검토,
tests/full `make check`는 orchestrator, connector 게시·실제 PR/세 CI/merge 및 이번 run의
정확한 cleanup/clean 동기화 확인은 main 책임이다.
문서와 fixture 성공은 실제 정리 완료의 증거를 대신하지 않는다. 결정·대안·비용은
[ADR 0010](adr/0010-automatic-post-merge-cleanup.md)에 둔다.

### Automatic model-context cleanup

Each workflow invocation owns one uniquely created non-credential model context
through the shared storage policy's `temporary_directory`. The context contains
only approved model sources and is removed when execution exits, including a
completed run, `awaiting_github`, failed review or validation, an exception, or
`KeyboardInterrupt`. The parent environment is unchanged; there is no global
`TMPDIR` change. Cleanup targets only that invocation's context, never unrelated
sibling directories or historical contexts.

Removing that uniquely owned tree is one high-level filesystem operation, like
directory creation/probe. Fresh `check_ready()` runs at cleanup entry before any
chmod or removal, and again immediately before final root removal. It checks all
configured mounts/floors; no assurance is cached across cleanup calls. File or
ancestor checks do not repeat unrelated artifact NFS readiness queries. Before
every directory chmod, file/link unlink and directory rmdir, freshly prove root,
parent, ancestor and target attachment, ownership, no-follow status, device and
kernel mount identity. Same-device bind mounts are refused. A pinned shared
legacy parent may have a different owner, but that owner must remain unchanged;
the owned tree entries must belong to the process.
The bounded count covers configured prerequisite readiness/free-space queries;
per-entry mount-point and kernel mount identity checks still grow with the tree.
Cleanup counters exclude allocation/create/probe; even an empty successful tree
has both readiness boundaries. A failed new cleanup entry must cause zero
unlink, rmdir or directory fchmod operations.

Only an owned directory may regain owner access using its identity-checked
descriptor. Readonly files are unlinked without chmod, links are never followed,
and external hardlink/target bytes and modes stay untouched. Linux statx mount ID
support is required; absent libc/kernel support, errors or a missing returned
mask fail closed without fallback. Final-readiness failure can leave a partially
removed tree and the root; it does not undo earlier deletions. The decision and
counting-FakeFS regression requirements are in
[ADR 0013](adr/0013-owned-validation-temporary-cleanup.md), which refines
[ADR 0011](adr/0011-configurable-harness-storage.md)'s operation boundaries.
[ADR 0018](adr/0018-storage-check-probe-deduplication.md) only shares space
measurements within each read-only boundary. Cleanup entry and final readiness
remain independent; neither shares measurements with allocation, probes or the
other cleanup boundary. Per-entry identity and kernel mount proofs remain fresh.

The validation workspace, report, `model-context.json` approved-source manifest,
approval snapshots, backups and journals remain on the permanent artifact root.
The report's `model_workspace` path identifies the former temporary context; it
is not a promise that the directory still exists. Inspect source scope during
model execution or consult the permanent manifest afterward. GitHub continuation
uses permanent evidence after the temporary model context has been removed.

A cleanup error makes the run non-successful and records its type and redacted
message in `model_context_cleanup` in the permanent report. Evidence is retained,
and the stable local project lock is released even if cleanup or report
persistence fails. A report persistence error propagates to the caller rather
than returning a successful result.

The earlier future host-activation/local-temporary proposal is superseded by the
latest user choice: retain existing configured NFS settings, mounts and floors.
This run does not activate a new configuration or introduce a local storage
override. Current private values are not inferred or exposed to models.
Credential runtime and the stable project lock retain their existing local
boundaries. Configured readiness/floors and containment remain required; no
mounts, operating data or historical records are migrated or deleted.

## 이번 31파일 수리의 검토·검증·게시 인계

원래 최적화와 추가 8개 repair 파일의 작업 승인은 유지한다. 이번 수리는 기존
`files-repair.txt`의 정확히 31개 개별 파일 안에서 importer snapshot/SELECT와 호출 소유
temporary cleanup만 완료한다. 등록된 역할/provider/model과 후속 PAK용 GLM, 기존 NFS
설정/mount/floor를 보존한다. `parser_tidy/items.py`·`luautil.py`는 변경하지 않는다.
제공된 4.8% slowdown의 equipment Lua batching은 제외하고 그 ADR은 만들거나 index하지 않는다.
외부 모델은 승인 31파일만 받고 private config/diagnostic 파일을 받지 않는다.
leaf worker는 checks·Git·agent-run·harness.workflow·재위임·다른 모델·cron·download·importAll을
실행하지 않으며 기존 사용자 편집을 보존한다.

공급된 후보는 prior real models와 Claude의 승인을 받았다. importer isolated 3회에서
첫 wall 31.7%/반복 48.1% 감소, 반복 SELECT 1604→100, 자동 audit timestamp 외 33테이블
동등성, 정확한 prev bytes와 INSERT/UPDATE/DELETE 수 불변이 제공되었다.
fresh isolated kTOS/iTOS/jTOS main의 지역별 41 JSON bytes도 baseline과 같았고 parent는
2691 selected parser/harness tests zero-skip을 보고했다. 이는 **후보 근거**이며 최종 소스의
full validation 통과가 아니다. 이전 full workflow는 NFS RPC 대기 중 timeout했고 old
parent rmtree는 readonly keep에서 실패했다. 부분 검사 뒤에도 cleanup이 매우 느렸다.
NFS statvfs probe 회복은 제공된 관측일 뿐 이 worker의 재확인·full workflow 성공이 아니다.

이번 repair 입력의 `check` diagnostic은 context unavailable·unattributed로 제공되었다.
실패 원인과 담당 파일은 알 수 없으며 이를 NFS timeout이나 readonly 실패에 귀속하지 않는다.
추가 원인 판단에는 승인 source context 또는 승인 파일에 귀속된 scoped reviewer finding이
필요하다. private diagnostic 파일을 모델 읽기 scope에 추가하지 않는다. 모든 원래 필수
checks는 최종 소스의 fresh real review 뒤 오케스트레이터가 실행한다.

1. 오케스트레이터는 최종 snapshot/ORM 및 cleanup 수리에 대해 fresh **실제** review를 받는다.
   매 review는 `documentation={status,files,reason}`을 반환하고 실제 변경된 승인 문서와
   strict diagnostics/order·소유/copy/fresh reads/state cleanup·ORM semantics 및 readiness/
   per-entry proof·statx/failure 경계의 의미적 완전성을 판단한다. Markdown 검사로 대신하지 않는다.
2. 오케스트레이터는 complete `make check`를 실행하고 기존 tests/제외와 zero skips를 확인한다.
   counting-FakeFS, invalid 새 cleanup의 removal/chmod 0회, readonly/link/swap/mount/foreign-owner,
   snapshot API 및 실제 ORM 회귀를 포함한다. 부분 2691 결과나 과거 candidate approval로 대체하지 않는다.
3. 승인/전체 검증 뒤 충돌과 기존 사용자 편집을 보존하며 31파일 범위만 반영한다.
   이 leaf의 기준 인계는 아직 소스 미반영·ROOT original master clean이라는 메인의 제공 상태다.
   worker는 Git으로 확인하지 않았다. 기본 Git 역할을 생략하거나 worker가 수행하지 않는다.
   main은 반영한 최종 소스의 요구된 시간/bytes/ORM 비교를 다시 확인한 뒤 게시로 진행한다.
4. main만 `awaiting_github` run의 정확한 journal `request.tool(request.arguments)`를 앱으로
   실행하고 해당 `request_id`의 실제 응답을 accept한다. 모호한 쓰기는 reconciliation으로 남기며
   수동 대체 게시나 가공된 성공으로 넘기지 않는다.
5. main은 pinned SHA에 대한 `Offline harness (SQLite)`, `MySQL harness`,
   `Chromium browser harness`의 **실제 success 세 개**를 확인한 뒤 기존 expected-head-SHA
   squash merge와 실제 merge SHA를 확인하고 자동 cleanup을 끝낸다. ref 부재·prune·clean base
   sync·cleanup complete 전에는 passed가 아니다. merge 사실과 cleanup 실패를 분리해 보고한다.

이 문서 worker는 위 실행 단계를 수행하지 않았다. 최종 새 검토·전체 checks·apply/Git 역할·
최종 비교·앱 journal·실제 CI/merge/cleanup은 pending이다. 관련 결정은
[0012](adr/0012-importer-single-run-snapshot.md), [0013](adr/0013-owned-validation-temporary-cleanup.md),
후보 범위/한계는 [harness](harness.md#이번-importercleanup-수리의-후보-근거와-검증-대기)에 둔다.

이 leaf의 문서 영향 인계 기록은 다음과 같다. 후속 real reviewer는 최종 코드와 문서의 의미를
독립 판단해 자기 `documentation` 결과를 반환해야 하며 이 기록을 승인으로 재사용하지 않는다.
`harness-design.md`와 ADR0008은 읽기 참조이며 이 leaf의 수정 범위가 아니다.

```json
{
  "documentation": {
    "status": "updated",
    "files": [
      "docs/architecture.md",
      "docs/data-contracts.md",
      "docs/harness.md",
      "docs/workflow.md",
      "docs/adr/0011-configurable-harness-storage.md",
      "docs/adr/0012-importer-single-run-snapshot.md",
      "docs/adr/0013-owned-validation-temporary-cleanup.md",
      "docs/adr/README.md"
    ],
    "reason": "Preserved existing documentation and clarified snapshot retention after complete strict validation; bounded configured prerequisite queries versus fresh per-entry mount proof and cleanup-only mutation counters; unchanged NFS choices, statx limits and surfaced failures; candidate-only evidence, unavailable/unattributed repair diagnostics and pending fresh review/full-check/apply/main-only publication handoff."
  }
}
```

## Scoped GLM telemetry handoff

이번 shared harness 변경은 기존 coordinator 구현 task **한 개**로 준비한다. 기존 역할 설정을
사용하며 worker가 다른 역할·workflow·검사·Git·네트워크·서비스를 실행하거나 재위임하지 않는다.
[ADR0019](adr/0019-private-glm-call-telemetry.md)의 local collector/private contract는
[설계 책임](harness-design.md#private-glm-telemetry-responsibility)과
[모델 계측 계약](agent-models.md#glm-호출의-private-지연-관측)을 따른다.
provider=zai의 기존 final JSON subprocess에만 ephemeral trace collector를 붙이고 partial
measurements를 기존 private research 참여 기록에 보존한다. 공개 web-v1/publisher/digest와
기존 모델·auth/billing·compaction·37파일 read scope·fingerprint·storage·schedule·quota/budget/
approval·frozen morning report는 유지한다. 추가 probe나 telemetry retry/fallback은 없다.

parent는 새 의미 검토·관련 offline tests·full make check·별도 합성 live를 수행한다.
메인은 다음 정상 admission된 GLM hourly private scan을 읽어 실제 지연을 관찰한다.
호환 fixture·작성된 tests·worker 구현은 이 실행의 검사 통과나 성공한 production 관측을
대신하지 않는다. 매 review는 documentation={status,files,reason}로 실제 수정된 승인 문서의
의미적 완전성을 판단한다. 필수 scope가 없으면 승인 파일 finding에 정확한 추가 경로를
기록하고 changes_requested로 반환하며 repair에서 범위를 자동 확대하지 않는다.
