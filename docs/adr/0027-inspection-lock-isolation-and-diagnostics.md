# 0027. 점검과 개발 작업의 잠금 격리 및 private 실패 진단

- 날짜: 2026-10-22
- 상태: 사용자 직접 요청 구현안; 최종 새 Claude 의미 검토·full make check·scoped apply·Git/CI 전달 대기
- 대체 범위: workflow 전체 project lock과 ADR0017의 공통 lock/storage/runtime 실패 코드.
  ADR0025의 sealed snapshot·진행 보존과 ADR0026의 실제 Read·coverage·ID별 verdict 보존은 유지한다.

## 문제와 근거

trusted parent의 정제 관측에서 2026-10-22 11:58:23.156514~12:00:06.164966 KST 개발 workflow와
12:00:01 정기 tick이 겹쳤다. workflow finished_at은 lock.close보다 먼저 기록된다. 당시 공통
`lock_storage_or_runtime_unavailable`만으로 정확한 예외나 holder를 확정할 수 없다. 다음13시
coordinator 단계는 성공했다. 이 변경은 과거 원인을 소급 복원하거나 PID를 추정하지 않는다.
별도 읽기 전용 진단의 approved/5244개 통과/applied=[]는 이번 구현의 승인·검증이 아니다.
직전 구현 run1792661613366557103-2bbee5의900초 timeout/applied=[]와 trusted parent의
bytes/mode 대조·초안 준비도 완료 증거가 아니다. 기존 timeout 정책을 유지한다.

기존 workflow는 READ_ONLY까지 prepare/model/review/check/apply/final-save 전체에서 source
flock을 보유했다. tick이 같은 잠금을 얻지 못하면 오전 보고 준비도 진행하지 못했다. 보호 잠금을
제거하면 apply/cleanup 중간의 서로 다른 파일 버전을 함께 읽게 되므로 책임과 보유 구간을 나눈다.

## 책임과 획득 순서

`project_lock.py`는 nonblocking flock만 사용한다. 기존
`ROOT/logs/harness/workflows/.lock` inode를 source mutex로 그대로 사용한다. unlink·rename·
stale PID 추정·전역 기다림·자동 retry가 없다. 인접 `.workflow-lock`은 개발 workflow 실행 소유권,
`.discovery-lock`은 저장 위치와 독립된 discovery/state/slot/call mutex, `.sender-lock`은 오전
sender mutex다. private owned regular lock은0600·nlink1이다. 프로세스/스레드 내의 내부 source
helper만 보유 잠금을 빌린다. 독립 controller는 `reentrant=False`로 별도 handle 경쟁을 한다.

| 경로 | 획득 순서와 보유 구간 |
| --- | --- |
| 일반/READ_ONLY workflow | workflow mutex는 실행과 최종 report save까지. source mutex는 전체 로컬 검증 사본 capture, 이후 apply 및 Git publication 준비에만 재획득 |
| 승인 제안 workflow | signed claim을 먼저 저장하고 Store 해제. 시작과 apply에서 state→source 순으로 원래 claim/승인/freshness 재검증 |
| tick/approve/execute | stable discovery→기존 artifact `.lock`→필요한 source mutex. tick의 예약 직렬화는 모델 중 유지하되 source mutex는 해제 |
| Git request/accept/resume/cleanup | source→선택 journal `github.lock`. refs/index/파일 변경과 최종 durable save까지 보호. 외부 앱/CI 응답 대기 전체에는 미보유 |
| 오전 publication | stable sender→기존 artifact `.publication-lock`. state는 discovery→artifact `.lock`; callback/HTTP 동안 state/source mutex 해제 |

Git은 두 잠금을 해제한 뒤 기존 completion hook과 archive를 호출한다. completion의 signed
claim/원래 검토·실행 증거 검증, 완료 outbox와 sending/unknown 복구는 유지한다. completion HTTP의
기존 Store 잠금 비용은 남는다. 새로운 source→state 중첩은 만들지 않는다.

## 일관성과 freshness

전체 로컬 검증 사본과 승인 파일만 담은 모델 사본을 분리한다. 모델·검토·doctor/full check·repair는
사본에서 실행하므로 일반/READ_ONLY의 긴 실행은 tick의 source 잠금을 소유하지 않는다. 반영 때
source 잠금을 새로 얻어 **전체** baseline의 파일 목록·bytes·mode·존재와 candidate/검증 digest,
승인 freshness를 대조한다. 충돌 시 자신의 validated 내용인 파일만 rollback하며 외부 편집을
보존한다. 저장소 전체 원자 교체를 주장하지 않는다. cleanup의 복구 snapshot·lease·refs/index와
사용자 편집 보존 조건도 유지한다. review diff 역시 live 원본을 다시 읽지 않고 capture에서
분리한 승인 파일의 private original 사본과 candidate를 비교한다. 이 사본은 모델 context나
archive로 확대 제공하지 않으며 source mutex 해제 후의 사용자 편집은 apply gate에서 거절한다.
apply의 KeyboardInterrupt도 이미 반영한 자신의 validated 파일만 baseline으로 rollback한다.
원본과 달라진 파일 목록·bytes·mode·삭제/추가 충돌과 rollback 중 외부 편집 보존을 별도로 명세한다.

tick은 state/slot을 먼저 durable claim하고 source 잠금 아래 controls와 현재 승인 source를 읽어
오전 선택을 확정한 뒤 새 round/seal을 준비한다. snapshot capture와 freshness helper도 같은
source mutex를 쓴다. 여러 파일을 읽은 뒤 앞선 파일도 다시 대조하여 비협력 편집을 감지한다.
외부 편집기는 flock에 참여하지 않으므로 악의적 동일 uid의 순간 변경까지 원자 snapshot으로
보장하지 않는다. bounded capture/seal/freeze의 storage I/O는 source 보호 안에 있다.

apply/cleanup 또는 구버전의 긴 source holder가 있으면 현재 읽기를 우회하지 않는다. no-call과
claimed slot의 구체적 실패를 남기며 Store가 안전하면 미완료 오전 보고를 freeze한다. 정상0개가
아니며 같은 slot을 재호출하지 않는다. source 읽기 불가에도 controls와 seal이 유효한 active 회차는
기존대로 보존 입력을 검토할 수 있다. source mutex 자체가 busy이면 controls도 확인하지 못하므로
그 호출은 보류한다. 보존 source의 review_complete는 live freshness/eligible/approve/execute가 아니다.

## freeze, publication과 이행

09시 freeze는 새 seal·quota·모델 admission보다 먼저 실행한다. 일반 개발 model/check 완료에
freeze/publication 의존성이 없다. 현재 전체 dependencies가 일치하는 완료 회차의 ID별 최신 명시
verdict·original provenance/실제 Claude Read proof와 최신 참여 실패를 보존한다. frozen payload와
digest는 한 번만 만들고 동일 digest GET readback으로 전달을 확인한다. prepared crash는 정확한
journal로 materialize하며 sending/unknown은 자동 POST하지 않는다. stable sender와 기존 sender
잠금이 동시 tick/수동 reconcile을 직렬화한다. 과거 frozen/delivery/승인/claim은 재작성하지 않는다.

새 discovery mutex inode에는 선택된 Store root의 SHA256과 LF만 저장한다. 최초 binding은
기존 ledger를 그대로 사용하며 artifact lock도 함께 잡는다. binding이 corrupt/부분/다른 root이면
state/call/publication을 진행하지 않는다. v1/v2/no-config/report override가 새 빈 ledger로 호출과
게시를 재허가하지 않도록 한다. 저장소 전환은 trusted parent가 구버전 실행 종료를 확인하고 기존
state/reservations/publication/claim을 명시 조정한 뒤 수행한다. PID 파일만 보고 잠금을 지우거나
새 root로 우회하지 않는다. 구버전의 source/artifact/sender inode를 유지하여 경합은 fail closed다.
구버전 자체의 저장 위치 정책은 소급 변경할 수 없으므로 이행 중 혼용된 storage 전환은 금지한다.

일반 개발의 긴 model/check와의 충돌은 해소하지만 짧은 capture/apply, 실제 source/refs/index 변경,
다른 discovery/completion, storage/config 장애는 여전히 안전한 판단을 막을 수 있다. storage 장애의
fsync/커널 I/O 지연까지 시간 보장을 주장하지 않는다. 실패/보류를 검증된 할 일 없음과 구분한다.

## 고정 private 진단과 복구

`improvement_diagnostics.py`의 invocation trace는 실제 catch 경계의 첫 실패를 보존한다.
config, Store 생성, storage readiness, source/workflow/discovery/sender lock, state read/save,
dependencies, snapshot/seal/stage, deadline, publication/정산과 diagnostic save를 구분한다.
version/실제 UTC 발생시각/고정 reason/boundary/logical lock kind/allowlist stage/hour slot,
정수 errno(0..4095), elapsed_ms(0..86400000)와 아래 고정 detail을 기록한다. bool/비정수/과대값은 null이며 외부
exception.reason·str·자유 클래스명·원문·prompt·credential·절대 호스트 경로를 복사하지 않는다.
검증한 holder 증거가 없으므로 holder_pid는 null이다. 발생시각은 logical 보고시각과 다르다.
deadline reason은 trusted alarm handler에서 생성한다. 기존 역할별 정제 실패 코드는 유지한다.

state 잠금 안에서 가능한 경우 private `loop/last-diagnostic.json` 한 건을 원자 저장하고
`diagnostic_preservation=private_record_and_result`를 반환한다. 최초 config/Store/readiness/lock/
state 읽기 실패나 진단 저장 실패는 `private_result_only`와 private CLI JSON stdout이 관측 경로다.
잠금 밖에서 state를 덮어쓰거나 fallback 저장소·로그·retry를 만들지 않는다. 설정 storage 자체가
불가하면 persistent 진단도 보장할 수 없다. parent의 기존 private CLI 캡처가 필요하며 stdout
미보존까지 복원하지 않는다. 오류 기록/정산 실패는 최초 진단과 durable 예약을 가리지 않는다.
진단은 공개 web-v1 필드·digest에 추가하지 않는다.

## 후속: 실제 원인의 private 전달

2026-10-23 정밀화는 기존 진단 결정을 완성하며 새 승인/스케줄/저장/게시 정책을 만들지 않는다.
`improvement-failure-v1`의 작은 API는 detail/attach/inherit/exception_detail과 adapter 결과의
attach_result/result_detail이다. 예외·결과 identity-bound 표식만 전달하고 runner JSON·예외문은
권위가 아니다. 저장/feedback의 sanitize_detail은 provenance를 만들지 않는다.
고정9키·allowlist·512bytes·exact dict/str/int를 요구하며 exit_code0..255,errno0..4095,HTTP100..599는
실제 경계의 관측값만 기록한다. bool/과대값은 null, validation field/rule 부족은 unavailable이다.
공유 validator가 실제 첫 거절의 field/rule을 결합하며 기존 edit_files 세 reason과 거절 기준은 유지한다.
원문·후보 값·동적 field/path·source/prompt/credential·호스트 절대 경로는 새 진단에 넣지 않는다.

adapter가 실제 CLI/transport·응답 실패를 분류하고 _call_role과 local loop는 identity 확인 뒤
표식을 전달한다. plain runner reason은 allowlist 코드여도 권위가 아니다.
stdout 모델/tool/source의 auth/readonly/401/quota 문구는 실패 증거가 아니다.
명확한 CLI 경계의 실제 증거만 분류하며 경고와 실패를 구별하고 부족하면 cli_failed/unavailable다.
기존 auth/permissions·진짜 인증 실패/timeout/응답 검증·원래 예외와 trace 첫 실패를 유지한다.

loop는 scan_id/slot/9단계 index/stage/owner_role과 admission/실제 호출 시각에 broad reason/detail을
결합해 private 참여·slot·cloud history192건과 별도 local_history192건·status·bounded feedback에 남긴다.
call_started_at/call_finished_at은 실제 clock 관측이다. finished_at은 기존 회계 시각이며 rollback 때
admission 이전으로 옮기지 않는다. 실제 종료 관측은 별도로 유지하고 legacy에 시각을 합성하지 않는다.
local history는 새 실제 예약/정산/복구만 기록하며 기존 cloud 오전 window/최신 역할 선택은 그대로다.
legacy 상세는 조회에서 unknown/unavailable로 표시하고 과거 원인/기록을 재구성하지 않는다.
후속 성공·재이행은 앞선 실패를 지우지 않는다. 정산 crash 전 저장된 local 실패도 복구가 사유·
초안 digest·호출 시각을 덮지 않으며 같은 사유/상세를 feedback에 전달한다.
후속 정산 보류는 이미 끝난 slot의 결과·사유·단계를 다음 단계 위치로 덮지 않는다.
상한 밖 전체 참여는 기존 scan 계약에 따른다. no-call gate/quota/budget/source-lock은 실제 보류 reason을
유지하며 실행 실패로 꾸미지 않는다. 모든 state 쓰기는 기존 잠금 내부이며 fallback/retry/새 scan은 없다.
feedback의 specialist_failure_detail/review_failure_detail도 같은 정제와 기존 bytes/redaction/최대4요약을 따른다.

ADR0025의 진행·sealed 입력/legacy와 ADR0026의 Read·coverage/ID별 verdict·승인 freshness는 유지한다.
web-v1/completion-v1·frozen payload/digest·journal/전달·카드·제안 보존과 runtime37/128KiB/1.5MiB는 그대로다.
22시 coordinator/02시 parser와01시 local·v3의 과거 실패 원인은 원문 미보존으로 미확정이며,
보존 path_aliases_read_only 분류만으로 실제 근본 원인을 확정하지 않는다. 기록·보고를 고쳐 쓰지 않는다.

native Lab은 실제 adapter→_call_role→tick→scan/slot/history/status/feedback·Store 재개와 후속 성공,
CLI 오류 문구/경고·실제 인증/timeout/spawn 구별·후보/검토·원문/위조/legacy·비용/중단/정산 첫 실패 및
기존 public/frozen/제안 보존을 명세한다. 검사는 미실행이다. 전체 diff 새 Claude 의미 검토와
GIT=1 full make check/scoped apply·기존 Git 역할 및 parent 게시/CI3/merge/cleanup·스케줄/frozen
독립 확인이 필요하다. 실제 향후 hourly 관측은 별도이며 인위적 운영 실패/tick으로 시험하지 않는다.

native 회귀는 collection 때 보존한 adapter callable을 시험 내부에서만 호출한다. storage는 Lab,
auth runtime·환경·CLI는 합성 경계로 대체하고 실제 CLI 경계 도달을 명시 검증한다. 공유 guard의
모델 진입·키 로드·네트워크·Popen·workflow·검사 차단은 대체 구간 안팎에서도 검증한다.
stdout 키워드만 있는 실패, 실제 stderr 인증 오류, 단순 경고, timeout/spawn은 서로 다른 fixture다.
시계가 날짜를 넘겨도 slot 조회는 원래 admission 회계일을 사용하고 실제 call_finished_at을 비교한다.

## 회귀, 문서 판단, 운영 인계

전용 `test_project_lock.py`와 `test_improvement_diagnostics.py` 및 기존 loop/workflow/storage/
snapshot/publisher/completion/cleanup 회귀는 full check의 기존 test_*.py 수집을 사용한다.
일반/READ_ONLY workflow의 실제 model/check 대기 중 tick→09시 freeze→POST/동일 digest GET,
별도 프로세스·독립 handle flock, apply/cleanup 중 snapshot/freshness 거절, 전체 baseline 충돌과
외부 편집 보존, duplicate tick/call/post 차단, legacy/storage 전환, 경계별 실패와 정제를 명세한다.
기존 bytes 상한·scope·실패 판정·skip 금지는 유지한다. worker/reviewer는 실행하지 않는다.

공용 Lab을 가져오는 새 테스트 모듈은 parent 환경 격리도 명시적으로 적용한다. 진단 모듈은 기존
offline fixture를 가져오며, 실제 workflow/flock 통합 모듈은 합성 프로세스 경로만 허용하는 별도
fixture로 실모델·키 로딩·네트워크·기본 검사 실행을 막는다. discovery 호출 중 fork한 중복 controller는
자식 사본의 marker만 제거하여 별도 scheduler parent를 모델링한다. production leaf/discovery
orchestration 금지를 완화하지 않으며 해당 marker의 진입 거절·state 무쓰기를 별도로 명세한다.
제공된 leaf guard 실패 위치와 격리 누락을 대조했다. 이후 trusted parent가 확인한
run1792663220823911214-ceb011 round2는 새 Claude approved 뒤 전체5057개 중5021통과·36실패,
applied=[]였다. 잠금·진단 전용 회귀의 통과는 보존하되 최종 수리의 승인·검증으로 재사용하지 않는다.

앞선 후속 수리는 기존 설계 안의 다음 세 호환성·fixture·기대값이었다.

- 최소 storage 패키지에서 새 진단 최상위 import가 browser19/MySQL13 사례를 막았다.
  storage는 진단 모듈을 import하지 않고 호출 시 이미 로드된 모듈의 config/readiness 경계만
  사용한다. active trace는 모듈이 로드되어 있으므로 동일한 첫 실패·정수/비밀 정제와 원래 예외를
  유지한다. 단독 import의 무I/O와 storage 오류 전파를 별도 회귀로 명세하며 import 실패를 숨기지 않는다.
- 기본37개 scope와 두 source 크기 사례는 운영 storage 해석 차단을 유지한 채 명시적 임시
  artifact/context policy를 정상 `snapshot_sources`에 전달한다. 잠금은 읽는 source root의 기존
  inode에서 실제 획득한다. bytes/mode 재확인·fingerprint·scope·초과 실패 및 무모델/무네트워크/
  무검사 계약은 유지한다. 당시에는 실제 파일 크기 실패 증거가 없었다.
- 좁은 state 잠금 아래 두 번째 execute는 durable signed claim을 보고
  `Authorization has already been claimed; automatic replay is forbidden.`로 거절한다.
  동시 요청과 후속 replay 모두 정확한 문구를 검증하고 executor handoff는 정확히 한 번만 허용한다.

runtime/test의 기존131072bytes 상한과 모든 기존 상한은 그대로다. 승인 밖 browser/MySQL
테스트는 읽거나 수정하지 않는다. 이 의존성 경계와 fixture 수리는 기존 잠금 책임/보유 구간과
ADR0025/0026의 snapshot·coverage·retention 결정을 바꾸지 않으므로 새 ADR 대신 본 결정을 보완한다.
설계·운영·root AGENTS 문서에 경계와 재검증 절차를 반영했으며 수리 후 실행 성공은 미주장이다.

최신 parent 검증 run1792666833184702773-4f087d는5060개 중5058통과·2실패/applied=[]다.
구성 오류 관측 테스트는 공유 forbidden에 먼저 막혀 collection 때 보존한 실제 resolver를 사용한다.
원래 OSError·진단 assertion과 공유 guard는 유지한다. 나머지는37파일 총1573848bytes로
상한1572864를984bytes 넘은 실패다. 중복 문서만 압축하며 개별131072bytes·scope·판정을 유지한다.
이 수정의 새 전체 검토·검증은 대기이며 이전36실패 수리와 잠금 설계는 보존한다.

매 새 독립 검토는 최종 코드·문서로 `documentation={status,files,reason}`을 새로 판단한다.
reviewer JSON은 verdict/summary/findings/documentation, finding은 file/severity/message만 사용한다
(줄 번호는 message). orchestrator의 full make check→scoped apply→기존 Git 역할, parent의 앱 게시·
CI3 success·merge/cleanup과 실제 운영 관측이 필요하다. 17시까지6/9단계 성공·active sealed round는
제공된 관측이며 나머지 DAG 역할/reviewer 완주,2026-10-23 09:00 보고와09:20 같은 채팅 알림은
미관측이다. hourly 매시00분·09시 보고 목표·기존 at→codex queue job1을 유지한다. cron/서비스/
알림 코드/private 설정은 변경하지 않는다.
