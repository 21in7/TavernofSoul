# 0011. 설정 가능한 하네스 산출물·비인증 임시 저장과 고정 로컬 잠금

- 상태: 제안(proposed), 구현안의 독립 검토·full checks·GitHub 전달 대기
- 기록일: 2026-10-13
- 기록 성격: 새 저장 경계 결정; 실행 성공이나 호스트 설정 활성화의 증거는 아님
- 대체 관계: 없음. [0002](0002-explicit-model-read-scope.md)의 승인 소스 격리,
  [0004](0004-reviewed-and-validated-publication.md)의 검토·검증 게이트,
  [0010](0010-automatic-post-merge-cleanup.md)의 cleanup·durable 복구·전체 완료 정책을 유지한다.

2026-10-14 보충: 이번 승인 실행은 importer snapshot/SELECT와 호출 소유 임시 cleanup 수리에
한정한다. 기존 configured NFS 설정·mount·floor를 유지하며 아래의 종전 activation 계획이나
local temporary override 제안은 실행하지 않는다. private host 설정은 읽거나 복사하지 않았다.
[0013](0013-owned-validation-temporary-cleanup.md)은 이 ADR를 대체하지 않고 고유 tree 정리의
readiness 경계와 매 항목 identity/mount 증명을 구체화한다.

2026-10-16 보충: [0018](0018-storage-check-probe-deduplication.md)은 아래 준비/probe 설명 중
일상 호출의 대상을 정밀화한다. 한 읽기 전용 경계에서만 shared mount의 공간 측정을 공유하며
두 spec의 floor는 각각 검사한다. `resolve … --prepare`/`ensure_directory`와 임시 할당은
새 root와 실제 목적지를 probe하고 무관한 기존 root는 반복 probe하지 않는다. 자식·외부 override는
부모 probe와 별개로 자신의 probe를 요구한다. 명시적 `prepare()`와 probe 진단은 여전히 두
application을 모두 검사한다. 각 쓰기와 다음 호출에는 fresh readiness가 필요하며 lease/cache는
없다. `status(probe=False)`의 무변경 조회와 실패 시 mount/측정 공간/floor 진단, 설정·격리·
fallback 금지와 0013 cleanup 경계는 유지한다. 아래 원래 결정과 비용 기록은 역사로 보존한다.

2026-10-19 보충: [0021](0021-local-work-and-result-archives.md)이 개발 작업의 NFS active 유지
선택을 명시 v2 local artifacts/temporary + remote terminal archive로 대체한다. 아래 v1/no-config
계약과 과거 관측은 보존하며 자동 변환하지 않는다. 옛 NFS 기록·absolute journal은 원래 v1
config를 명시 선택해 조회·재개하고 이동/재작성/삭제하지 않는다. v2 archive는 파싱 때 접근하지
않고 ARCHIVE 시점에만 mount/floor/private를 검사하며 active 검색/복구 근거에 추가하지 않는다.
private 기본값 전환은 새 검토·검증 뒤 parent 책임이다. daily/hourly/게임 cron·approval 기록·
인증/lock 경계는 유지한다. 아래 날짜별 '최신 NFS 유지' 서술은 당시 선택의 역사 기록이다.
[0022](0022-documentation-only-validation.md)는 최종 실제 diff의 prose 검증 선택만 정밀화한다.

## 문맥

사용자는 하네스 작업물이 로컬 디스크를 채워 당일 운영 cron이 중단된 문제를 보고했다.
main이 제공한 관측에서 `logs/harness/workflows`의 run/workspace 사본은 71개·약 2.3 GiB로
가장 큰 하네스 출력이었다. 호스트에는 rw NFS `/mnt/nfs-2tb`(NVMe, 제공된 시점 약 1.2 TiB free)와
`/mnt/nfs-hdd`(HDD, 약 8.9 TiB free)가 있다. 이는 요청의 배경 정보이며 이 문서의 호스트 조회나
현재 공간·writeability·mount readiness 검증 결과가 아니다. 이 경로를 새 기본값으로 고정하지 않는다.

하네스는 작업 사본·검증 임시·모델 context·보고서 외에도 credential-bearing runtime과
GitHub 승인 journal·복구 snapshot을 만든다. 모두 같은 외부 임시 정책으로 옮기면 인증 격리를
훼손하고, project lock을 artifact root와 함께 옮기면 새 실행과 legacy cleanup이 다른 lock으로
동시에 쓰게 된다. 기존 승인 기록에는 absolute workspace가 있으므로 설정 변경 때 경로를 재작성하면
검토·검증·게시의 연결 근거가 달라진다. 마운트가 없는 경로에 먼저 mkdir하면 로컬 디스크를 다시
채우므로 단순 경로 치환만으로는 요구를 충족하지 못한다.

## 결정

### 단일 resolver와 명시적 설정

[harness/storage.py](../../harness/storage.py)의 `resolve_storage(ROOT, env=..., fs=...)`를
workflow·git_publish/cleanup guard·agent_models 보고서·triage·compaction·runner·container wrapper가
공유한다. import에는 I/O를 하지 않고 호출 시점의 프로젝트 root로 해석한다.

설정은 절대 경로 `HARNESS_STORAGE_CONFIG` → 선택적 private
`ROOT/logs/harness/storage-local.json` → 기존 로컬 기본값 순으로 하나만 선택하며 병합하지 않는다.
명시적 파일 누락·빈/상대 경로, 존재하는 설정의 malformed JSON·중복/추가/누락 필드·잘못된 타입·
symlink는 오류다. 선택적 파일이 없을 때만 로컬 기본값을 유지한다. 설정 실패·mount 부재·
free-space floor 미달·private mode/probe 실패에는 로컬 fallback을 허용하지 않는다.

version 1 JSON의 필드는 정확히 `version`(정수 1), `artifacts`, `temporary`다. 두 객체는 각각
정확히 `path`, `required_mount`, `min_free_bytes`를 갖는다. 두 application path는 정규화된
절대 경로이고 symlink가 없어야 하며 서로 겹치거나 저장소의 상위/하위일 수 없다.
각 path는 자신의 required mount의 엄격한 하위이며 다른 required mount를 포함하지 않는다.
mount 공유는 허용한다. 공간 하한은 bool이 아닌 0 이상의 정수 byte 수다.

[tracked example](../../harness/storage-config.json.example)은 설명용 경로와 10 GiB floor를
제시할 뿐 활성 설정이 아니다. 실제 private 설정은 보호된 logs 아래에서 `0600`으로 준비한다.
설정 원문·secret·임의 OS 오류는 공개 진단에 넣지 않는다. 모델 승인 소스에 private 설정을 포함하지
않으며 모델 자식의 config/report 환경 override 제거는 모델 연결 계층의 필수 격리 책임이다.
신뢰한 검증은 모델 사본 밖의 private 파생 설정으로 같은 mount·floor를 전달한다.

### 외부 산출물과 로컬 인증 runtime 분리

설정이 없으면 일반 보고서는 기존 `ROOT/logs/harness`와 category, workflow는 그 아래
`workflows/<run_id>`, 모델 context는 `/tmp/tavern-model-context-*/sources`, 일반 검증 임시는
기존 `tempfile` 기본 동작을 유지한다. configured 새 run/workspace/checks/backup/journal과
보고서는 `artifacts.path` 및 category에, 비인증 context·검증 임시는 `temporary.path`에 둔다.
보고서 선택은 지원 CLI의 명시적 `--report-dir` → `HARNESS_REPORT_DIR` → configured
artifact/category → 호출자의 기존 local default다. override는 최종 디렉터리이며 readiness를
우회하거나 temporary·local lock·credential home을 변경하지 않는다.

기존 subscription authentication·key homes·실제 `HOME`/`CODEX_HOME`과 인증을 담은 Codex
`/tmp/tavern-codex-runtime-*`, `ROOT/logs/harness/{agents,compaction}/runtime`은 로컬/private로
유지한다. 전역 `TMPDIR`는 바꾸지 않는다. runner의 비인증 검증 자식만 configured
`HARNESS_WORK_DIR`·`TMPDIR/TMP/TEMP`·pytest `--basetemp`를 사용한다.
Docker 데이터베이스·운영 볼륨·컨테이너 tmpfs·mount 자체는 이동하거나 변경하지 않는다.

### 쓰기 전 prerequisites와 private probe

모든 configured required mount가 정확한 경로의 실제 mount인지, 각 mount의 free bytes가
`min_free_bytes` 이상인지 **어떤 mkdir나 probe보다 먼저** 확인한다. symlink와 application/출력까지
다른 nested mount도 거부한다. 각 쓰기 경계에서 재검사하며 이전 readiness를 lease로 간주하지 않는다.
한 호출 소유 고유 임시 tree 제거는 directory 생성/probe처럼 한 고수준 filesystem 작업이다.
cleanup 진입과 최종 root 제거 직전에 `check_ready()`를 새로 수행한다. 진입 실패는 첫 chmod/
unlink/rmdir 전에 중단하며 다음 cleanup에도 이전 성공을 재사용하지 않는다.
각 directory chmod·file/link unlink·directory rmdir 전 root·parent·ancestor·대상 attachment,
ownership·no-follow·device·kernel mount identity는 계속 새로 증명한다. readonly 소유 directory만
pinned descriptor로 접근을 복구하고 파일/외부 target chmod는 금지한다. statx mount ID 미지원/
실패는 fail closed다. 최종 readiness 실패는 일부 정리된 tree/root를 남기고 non-success로 노출한다.
global prerequisites와 per-entry containment의 책임·제약·counting 회귀는
[0013](0013-owned-validation-temporary-cleanup.md)에 기록한다.
이 경계로 제한하는 조회는 configured prerequisites의 readiness/free-space 조회다.
항목별 mount-point 및 kernel mount ID 검사 수는 제한하지 않으며 계속 새로 수행한다.
application은 프로세스 소유·`0700`이어야 한다. 새 디렉터리만 private mode로 만들고 기존 mount
root나 무관한 디렉터리는 chmod하지 않는다. private JSON·events·logs·lock은 `0600`이다.
실제 writeability probe는 private application 안의 고유 `0600` 파일을 write/fsync/readback/delete한다.
MySQL/Chromium wrapper도 초기 status·Docker 시작 전에 resolve/prepare한다.

`make storage-status`, `make storage-doctor`, `python -m harness.storage status`,
`python -m harness.storage doctor`는 유료 모델 없이 경로·mount readiness·free bytes·floor와 private
상태를 읽기 전용으로 표시한다. application이 없을 때 ready는 writeability 보장이 아니다.
`doctor --probe` 또는 `make storage-doctor PROBE=1`은 기존 private application만 probe한다.
`python -m harness.storage resolve artifacts --prepare`는 검사 후 두 configured application을
만들고 probe한다. 실패는 유용한 고정 오류와 nonzero 종료이며 로컬 출력을 만들어 숨기지 않는다.
완전한 JSON·기존 설정을 보존하는 준비 명령·override 사용법은
[하네스 사용법](../harness.md#하네스-저장-경로-설정과-진단)에 둔다.

### 고정 로컬 lock과 legacy 기록

프로젝트 lock은 항상 로컬 `ROOT/logs/harness/workflows/.lock`이다. workflow/apply와 GitHub
request/accept/resume/cleanup은 이 lock을 공유하고, 그 뒤 선택된 run의 journal 옆 `github.lock`을
획득한다. artifact 설정·report override·legacy 접근으로 별도 project lock을 만들지 않는다.
잠금 뒤 위치 검증과 외부 사용자 편집에 대한 기존 hash/권한/충돌 검사는 유지한다.

status/latest와 Git request/accept/resume/cleanup은 현재 report root, configured workflows,
호출자의 legacy REPORTS, canonical `ROOT/logs/harness/workflows`를 중복 경로 없이 함께 조회한다.
latest는 유효 pointer와 report의 수정 시각을 비교하며 기존 기록을 쓰지 않는다. 서로 다른 root의
동일 run ID는 ambiguity로 실패한다. root/run/record symlink와 escaping latest pointer·경로는
거부한다. 선택된 root의 containment·private mode·journal identity·approved hash·expected SHA·
durable snapshot 계약은 legacy에도 유지한다. status는 run/record containment와 상태 metadata를,
Git journal 처리는 이에 더해 기존 private mode·승인·SHA·snapshot을 검증한다.
임의의 과거 외부 root는 자동 탐색하지 않으며 main이 명시적으로 원래 경로를 선택해야 한다.

기존 journal/report의 absolute workspace는 선택된 run의 원래 `workspace`여야 한다.
새 artifact root로 재결합하거나 approved historical JSON/snapshot을 재작성하지 않는다.
명시적 request/accept/resume/cleanup의 진행 상태 기록은 기존 게시 계약을 따른다.
0010의 fresh proof·SHA 고정·lease 비교 삭제·prune·ff-only·cleanup complete 전 passed 금지 원칙은
그대로다. 이 ADR는 cleanup 정책을 대체하거나 symlink/journal 검증을 완화하지 않는다.

## 비교 대안

| 대안 | 효과·비용 | 판단 |
| --- | --- | --- |
| 계속 로컬 기본값만 사용 | 설정이 단순하지만 큰 새 사본의 디스크 압력을 해결하지 못한다. | 미설정 호환 모드로만 유지 |
| 호스트 NFS 경로를 기본값으로 고정 | 해당 서버에서 간단하지만 checkout/CI가 실 mount에 의존한다. | 채택하지 않음 |
| logs/workflows symlink 또는 global TMPDIR 변경 | 수정량은 적지만 경로 검증·인증·잠금·mount 부재 경계를 흐린다. | 채택하지 않음 |
| 모듈별 독립 환경 변수·자동 로컬 fallback | override와 readiness가 달라지고 unmounted 경로가 디스크를 다시 채울 수 있다. | 채택하지 않음 |
| 시작 시 과거 run 자동 이전/삭제 | 공간은 줄지만 absolute 승인·복구 근거와 기존 사용자 자료를 변경한다. | 별도 수동 승인 범위로 남김 |
| 단일 resolver·명시적 prerequisites·로컬 인증/lock 유지 | 통합·검사 비용은 늘지만 위치 변경과 승인/인증 경계를 분리한다. | 제안 구현안으로 선택 |

## 선택 이유

새 대용량 출력만 설정 경로로 보내면 운영 데이터를 이동하지 않고 로컬 압력을 줄일 수 있다.
optional absence 호환은 CI/새 checkout에 host config를 요구하지 않는다. 엄격한 configured failure는
NFS 장애를 조용한 로컬 출력으로 바꾸지 않는다. 공통 lookup과 로컬 lock은 legacy 재개와 새 실행의
직렬화를 함께 유지하며, credential runtime을 분리하면 보고서 override가 인증 저장 정책을 바꾸지 않는다.

## 결과·비용·복구 경계

mount 확인·disk usage·private probe와 반복적인 write guard 비용이 늘고 NFS 지연/장애가 하네스
실행을 중단할 수 있다. 실제 NFS의 durability·locking 성질과 mount 재설정 경쟁 전체를 원자적으로
보장하지 않는다. probe 이후 mount가 사라질 수 있으므로 단계마다 재검사하고 실패를 보존한다.
로컬 인증 runtime과 project lock은 여전히 로컬 공간을 사용한다. floor는 자동 용량 예약이나
retention 정책이 아니며 정해진 여유 공간이 향후 모든 쓰기를 보장하지 않는다.

mount·권한·floor 실패는 main이 해당 mount/접근/공간을 복구한 뒤 doctor/probe로 다시 확인한다.
duplicate run ID는 원본 경로와 승인 기록을 확인할 때까지 보류하고 임의 선택·덮어쓰기·삭제로
해결하지 않는다. configured 오류를 legacy fallback으로 회피하지 않는다. 중단 시 merge SHA·
승인 snapshot·backup·pending journal을 보존하며 readiness 복구 뒤 기존 명시적 재개를 사용한다.
복구 가능한 merge를 되돌리거나 새 모델/PR/merge를 자동 생성하지 않는다.

이 구현은 과거 artifacts의 migration·복사·archive·삭제·cron 등록을 하지 않는다. 고유 임시
context manager는 자신이 만든 작업만 정리한다. 수동 historical 정리는 프로세스 종료와 pending
게시/cleanup·snapshot 필요 여부를 main이 확인한 별도 작업이다. absolute 경로 변경은 기존 재개
검사를 깨뜨릴 수 있으므로 journal 재작성은 이 결정의 복구 수단이 아니다. 사용자 편집·운영
cron·unpack·JSON·DB는 보존한다. 과거 두 GitHub 처리 대기의 조사는 저장 구현과 별개다.

scoped worker는 승인 파일만 작성하고 checks·Git·workflow·models·운영 작업·재위임을 실행하지
않는다. tests/full `make check`와 독립 의미 검토는 orchestrator, connector 게시·필수 CI 확인·
merge·정확한 cleanup은 main이 맡는다. 종전 제안의 activation은 검토·full checks·GitHub 전달 뒤로
제한했으나 이번 실행은 최신 선택대로 기존 설정을 유지한다. draft 복구·문서 변경·회귀 정의
존재를 승인·실행 성공으로 취급하지 않는다.
매 orchestrator review는 `documentation={status,files,reason}`과 `status=updated`를 실제 변경된
승인 Markdown과 저장/격리/복구 설명의 의미적 판단으로 뒷받침한다.

## 관련 코드·검증·문서

- [storage.py](../../harness/storage.py), [tracked example](../../harness/storage-config.json.example),
  [Makefile](../../Makefile): 정책·schema·status/doctor·준비 명령.
- [workflow.py](../../harness/workflow.py), [git_publish.py](../../harness/git_publish.py),
  [git_cleanup.py](../../harness/git_cleanup.py): legacy lookup·두 잠금·승인 위치·durable guards.
- [agent_models.py](../../harness/agent_models.py), [triage.py](../../harness/triage.py),
  [compaction.py](../../harness/compaction.py), [runner.py](../../harness/runner.py),
  [mysql.sh](../../harness/mysql.sh), [browser.sh](../../harness/browser.sh): 보고서·비인증 임시·로컬 인증 통합.
- [test_storage.py](../../harness/test_storage.py), [test_workflow.py](../../harness/test_workflow.py),
  [test_git_publish.py](../../harness/test_git_publish.py),
  [test_agent_models.py](../../harness/test_agent_models.py), [test_runner.py](../../harness/test_runner.py),
  [test_mysql_safety.py](../../harness/test_mysql_safety.py),
  [test_browser_runner.py](../../harness/test_browser_runner.py): offline regression 경로.
- [architecture](../architecture.md#하네스-저장-경계),
  [전체 설계](../harness-design.md#공유-저장-정책과-실패-경계),
  [하네스 사용법](../harness.md#하네스-저장-경로-설정과-진단),
  [workflow](../workflow.md#저장-위치와-기존-실행-조회): 구조·격리·사용·재개 경계.

offline 회귀는 `tmp_path`와 fake mount/free-space/probe seam으로 default/custom 경로, private mode,
잘못된 config, mount 부재 전 mkdir 금지, floor/권한 실패, legacy/latest·duplicate/symlink·journal
location, 같은 local lock, 로컬 인증 runtime을 검증해야 한다. 실제 NFS·network·secret·운영 데이터에
의존하거나 기존 full offline coverage/CI를 줄이고 skip/xfail을 추가하지 않는다.
호출 시점의 ROOT/REPORTS와 주입한 env/fs를 사용해 테스트에서 main 저장소의 private 설정이나
실 mount를 읽지 않게 한다. 소스 context의 private 설정 제외와 모델 자식 환경 격리도 검토 대상이다.
위 링크는 검증 대상과 책임을 기록하며 이 worker의 테스트 실행·통과·호스트 활성화 결과가 아니다.

### Workflow context ownership and permanent evidence

The workflow owns its unique non-credential model context using the shared
storage policy's `temporary_directory`, with cleanup at every execution exit.
This includes completion, `awaiting_github`, failed review or checks, exceptions
and interruption. Cleanup removes only that call's context. Other temporary
directories, historical contexts and permanent artifacts are not cleanup
targets. The parent environment remains unchanged without a global `TMPDIR`
mutation; authentication runtime and the stable project lock stay local.

Before context cleanup, the permanent artifact directory contains the validation
workspace and the approved-source `model-context.json` manifest. Reports,
approval snapshots, backups and journals are retained for review, recovery and
GitHub continuation. A stored `model_workspace` path is historical once execution
has exited. Scope assertions after execution must use the permanent manifest;
assertions about model source contents can run while the model is active.

Cleanup failure is a non-successful run, with a redacted failure record under
`model_context_cleanup` in the permanent report. Cleanup and report persistence
cannot prevent releasing the stable local project lock. If report persistence
itself fails, that error is surfaced to the caller; no successful result is
returned. A surviving context after failed cleanup is not silently treated as
cleaned, and permanent evidence remains available for investigation.

### Historical local-temporary proposal (superseded host choice, 2026-10-14)

The earlier proposal for an eventual ignored private host configuration selected
`artifacts.path=/mnt/nfs-2tb/oci-tavernof-soul/harness-artifacts`,
`artifacts.required_mount=/mnt/nfs-2tb` and
`artifacts.min_free_bytes=10737418240` (10 GiB), together with
`temporary.path=/tmp/oci-tavernof-soul/harness-temporary`,
`temporary.required_mount=/` and `temporary.min_free_bytes=8589934592` (8 GiB).
That proposal would have placed permanent records and workspace copies on NVMe
NFS and temporary model sources on local storage. These historical proposed
values are not the current effective configuration or instructions to activate
an override. The latest user choice preserves existing configured NFS settings,
mounts and floors, with no local storage override or activation change in this
run. No private configuration was consulted to infer current values.
This decision neither changes the storage schema nor
authorizes mount changes, operating-data mutation, historical migration/deletion,
broader model file access or model/provider/authentication/permission changes.
The independent full-check and three-real-CI-success/merge/cleanup gate remains
in force.

### Candidate evidence and remaining gates (2026-10-14)

The supplied 2691 selected parser/harness tests passed with zero skips, but
cleanup stayed very slow. A prior full workflow timed out during NFS RPC waits
and its old parent `shutil.rmtree` failed on readonly keep. The supplied recovery
of the NFS statvfs probe is an observation, not full validation. Importer timing,
SELECT and byte comparisons are candidate evidence described in
[ADR 0012](0012-importer-single-run-snapshot.md) and [harness](../harness.md).
Full validation of the final source remains pending. Fresh real review,
orchestrator complete `make check`, scoped apply/default Git role and main-only
exact GitHub app journal, three actual CI successes, merge and cleanup are still
required. Every review records `documentation={status,files,reason}`.
