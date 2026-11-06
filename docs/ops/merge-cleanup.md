# Merge와 cleanup·archive

요약: 사용자의 UI squash merge 뒤 parent가 실제 비교 근거를 확보하고 정리와 보관을 각각 완료한다.

정본은 `logs/harness/harness-runbook-core.json`이며 충돌 시 runbook core가 우선한다. 이 페이지는 공개 요약이며 새 merge·삭제 권한을 부여하지 않는다.

## 사용자의 UI 단계

게시 대상은 fork `21in7/TavernofSoul`이다. parent는 PR 대상과 필수 CI 결과를 확인하며, 사용자가 GitHub UI에서 Squash and merge한다. 사용자는 Delete branch를 누르지 않는다. 기존 문서의 역사적 자동 merge 지침과 다르면 이번 사용자 UI merge 지시를 적용한다. 기존 문서 본문은 고치지 않는다.

구현자·reviewer는 Git·검사·운영 명령을 실행하지 않는다. [workflow 운영](workflow.md)의 역할 경계를 유지한다.

## Parent의 비교와 삭제

UI merge 이후 trusted parent의 표준 진입점은 다음과 같다. 아직 merge하지 않은 PR에는 실행하지 않는다.

```sh
make agent-git-external-merge RUN_ID=<run> PR_NUMBER=<n> PROOF_FILE=<private-json> RESPONSE_SHA256=<sha256>
python -m harness.parent_commands agent-git-external-merge --run-id <run> --pr-number <n> --proof-file <private-json> --sha256 <sha256>
```

위 인자는 기존 `awaiting_connector/step=merge`의 정확한 미전송 merge 요청 경로다. 원래 journal이
`awaiting_ci`에서 멈췄고 현재 pending write/request가 없으면 별도 승인 head check-runs 파일도 필수다.
두 파일은 parent가 실제 GET으로 확보하며, UI merge 전에는 이 명령을 호출하지 않는다.

```sh
make agent-git-external-merge RUN_ID=<run> PR_NUMBER=<n> PROOF_FILE=<private-proof-json> RESPONSE_SHA256=<proof-sha256> CHECKS_FILE=<private-checks-json> CHECKS_SHA256=<checks-sha256>
python -m harness.parent_commands agent-git-external-merge --run-id <run> --pr-number <n> --proof-file <private-proof-json> --sha256 <proof-sha256> --checks-file <private-checks-json> --checks-sha256 <checks-sha256>
```

GitHub 앱/HTTP GET은 parent가 실제 수행하고 아래 schema의 응답 묶음을 private 파일로 저장한다.
명령은 connector·모델·workflow·검사·새 credential을 호출하거나 UI merge를 agent 응답으로 위조하지 않는다.
원응답 shell argv·대화형 stdin·PTY는 금지하며 Git fetch와 정확한 ref 삭제는 기존 git_cleanup 경로만 사용한다.
이 명령은 PR 생성/merge 권한을 추가하지 않는다. A2d2 reconcile/resume-ci/connector dispatch는 구현 범위 밖이다.

parent는 삭제 전에 정확한 브랜치·tip·보호 여부·다른 작업/PR의 사용 여부·CI·merge 증거를 비교한다. 완료된 PR과 대상이 일치해야 하며 다른 진행 작업과 사용자 변경을 보존한다. 이름이나 merge 알림만으로 삭제하지 않는다.

비교가 불충분하거나 불일치하면 확인된 증거와 남은 상태를 보고한다. private 조회 환경이나 고정 조회용 호스트 경로·식별값은 공개하지 않는다.

parent는 비교 후 해당 브랜치를 삭제하고 cleanup, archive를 수행한다. 사용자 UI merge를 자동 merge로 대체하지 않는다.

## 저장된 GET 증거 생성과 다음 요청 파일 확인

두 명령은 trusted parent 전용이며 connector를 호출하지 않는다. 기존 수동 절차의 전체 전환과
다른 운영·설계 문서의 정리는 후속 A2d2a-docs PR 범위다.

```sh
make agent-git-proof-build RUN_ID=<run> PR_NUMBER=<n> INPUT_DIR=<resolved-run>/proof-input-<label> RESPONSE_SHA256=<manifest-sha256>
make agent-git-next-file RUN_ID=<run> REQUEST_FILE=<returned-request-file-path> RESPONSE_SHA256=<returned-request-file-sha256>
```

proof 입력은 실제 resolver로 찾은 run의 직계 `proof-input-*` private 디렉터리다. owned 0600/nlink1인
`manifest.json`은 `version=parent-proof-input-v1`, `run_id`, `pr_number`, `journal_sha256`,
`approval_sha256`, `merge_sha`, `responses`를 갖는다. 각 response는 `method=GET`, 정확한 페이지 `url`,
`status=200`, `complete=true`, 디렉터리 안의 단일 파일명 `file`, 원문 `bytes`/`sha256`를 갖는다.
본문 파일에는 parent가 실제 받은 JSON을 저장한다. 아래 native proof/checks의 모든 GET 계약이 그대로
적용되며, 각 원문은 한 번 읽은 memory snapshot으로만 검증·생성한다.

반환은 `parent-commands-v1` JSON이다. 성공 `proof_built`는 `proof_build.version=parent-proof-build-v1`,
`complete=true`, exclusive 0600 `proof_file`/`checks_file`의 경로·bytes·sha256과 정확한
`agent-git-external-merge` 인자를 제공한다. 누락은 `missing_get`과 `next_action.action=collect_get`의
정확한 GET을 반환하며 출력은 생성하지 않는다. parent가 실제 GET과 manifest를 보완하고 새 manifest hash로
명시 호출한다. 충돌 파일은 보존한다. IO 실패는 `complete=false`, `executed`, `side_effects.created`,
`partial_outputs`의 실제 생성 경로·파일별 완료 여부를 남긴다. 자동 재시도하지 않으며 부분 출력은 검토 후 처리한다.

`next`/`accept-file`의 기존 native/transport/result_file/next_action에 `request_file` descriptor가 추가된다.
`parent-next-file-v1`은 run/request ID, tool/arguments 또는 큰 요청의 run-bound native stdout descriptor,
operation/journal/result/request digest와 poll interval을 연결한다. reader는 receipt와 pending 상태를 다시
검증해 `exact_request_verified`와 정확한 요청 또는 descriptor를 반환한다. 다른 run·변조·stale·전송 불명·
수락 완료·external checkpoint는 거절하고 merge/awaiting_ci/failure에서는 멈춘다. reader는 전송 허가가 아니다.
parent만 기존 권한 안에서 connector를 한 번 호출하고 원응답을 private 파일로 저장해 `accept-file`에 넘긴다.
export 실패 `next_file_write_failed`/`native_result_retained=true`는 native 결과와 receipt를 보존하고 stop한다.
이미 성공한 accept를 재accept하거나 요청을 자동 재전송하지 않는다. 본문은 shell argv·PTY·대화형 stdin에 넣지 않는다.

## Proof v1과 입력 snapshot

`external-merge-proof-v1`의 top-level은 정확히 아래 필드다. base는 승인 당시 원래 base이며 head도
원래 승인 head다. JSON의 duplicate key·추가 JSON·잘못된 UTF-8을 거절한다.

```json
{
  "version": "external-merge-proof-v1",
  "run_id": "<run>",
  "pr_number": 123,
  "repository": "21in7/TavernofSoul",
  "base": {"ref": "<base-ref>", "sha": "<original-base-40hex>"},
  "head": {"ref": "codex/<run>", "sha": "<original-head-40hex>"},
  "merge_sha": "<squash-40hex>",
  "responses": [
    {"method": "GET", "url": "https://api.github.com/repos/21in7/TavernofSoul/pulls/123", "status": 200, "complete": true, "body": {}}
  ]
}
```

예제의 빈 body는 실제 증거를 대신하지 않는다. 각 row는 정확히 method/url/status/complete/body이며
중복·불필요 URL, 오류 status, complete 누락/false를 거절한다. collection의 complete=true는 parent가
해당 페이지 전체를 실제 GET으로 읽었다는 진술이다. 필요한 URL은 같은 repository prefix의 다음 GET이다.

- `/pulls/<n>`: closed/merged, 정확한 repository/base/head와 squash SHA. PR base SHA는 original 또는 squash만 허용한다.
- `/git/commits/<original-head>`와 `/git/commits/<squash>`: 둘 다 parent 하나가 original base이며 tree가 ledger.new_tree와 같아야 한다. Git fetch 후 로컬 object 전체 tree와 scope도 다시 확인한다.
- `/commits/<head>/check-runs?filter=latest&per_page=100&page=<p>` 및 native journal에 test_merge_sha가 있으면 그 SHA의 같은 조회: total_count와 중복 없는 모든 page를 native CI3/check_suite/skip gate로 검증한다.
- `/commits/<head>/status` 및 test_merge_sha의 같은 조회: native aggregate success gate에 더해 total_count와 statuses 길이가 같아야 한다. 응답이 잘렸으면 부재로 간주하지 않고 중단한다.
- repository 자체 GET: full_name/default_branch를 확인한다.
- `/branches?per_page=100&page=<p>`: 마지막 짧은 페이지까지 모두 제공한다. 작업 branch는 보호되지 않았고 tip이 original head여야 하며, 완전 조회로 이미 부재가 증명돼도 된다.
- `/pulls?state=open&head=<owner%3Acodex%2Frun>&per_page=100&page=<p>`: 마지막 짧은 페이지까지 모두 제공하며 열린 PR이 없어야 한다.

branches/open PR의 native wrapper는 `{complete:true,page:<p>,per_page:100,truncated:false,items:[...]}`다.
REST 배열 대신 wrapper를 저장할 때도 이 coverage 필드를 빠뜨리거나 오류를 빈 items로 바꾸면 안 된다.

필수 GET이 없으면 `external_get_required`와 `next_action={action:collect_get,method,url,then}`을 반환한다. parent가 별도로
실제 조회하고 묶음을 완성해 새 hash로 저장한다. checkpoint가 생긴 뒤에는 proof를 바꿀 수 없다.
불완전 status/collection은 `stop` 후 조회 범위를 조정한다. 응답 누락·오류를 빈 collection으로 채우지 않는다.
Update branch merge commit 등 head 변경은 `external_head_mismatch`다. base 전진/추가 변경으로 승인 patch
관계가 불명하거나 fetch tip이 squash와 다르면 중단한다. merged=true 하나만으로 쓰기를 허용하지 않는다.

external-merge와 accept-file은 같은 immutable memory snapshot 계약이다. private 디렉터리를 열고
파일을 O_NOFOLLOW/O_NONBLOCK으로 한 번만 연다. 초기 fd의 owned regular/0600/nlink1/size 상한8MiB를
확인하고 bounded bytes를 읽는다. dup(fd)는 경로 재오픈이 아니다. 이 bytes의 SHA256이 parent 값과
일치해야 JSON/schema를 검사하며, digest mismatch는 dispatch·lock·checkpoint 전에 side effects 없이 거절한다.
이후 응답 경로를 재stat/재오픈하지 않는다. 검증 뒤 교체·수정·삭제돼도 이미 검증한 메모리 bytes만
proof/frame에 사용하며 입력 파일을 명령이 삭제하지 않는다. 내부 journal/approval/receipt freshness,
source/lock identity와 임시 frame ownership/fsync/readback/cleanup은 별도 계약으로 그대로 유지한다.

## Awaiting CI의 별도 check-runs 계약

`CHECKS_FILE`/`CHECKS_SHA256` (`--checks-file`/`--checks-sha256`)은 반드시 함께 제공한다.
기존 known-unsent 경로는 둘 없이도 동작한다. `awaiting_ci` 경로의 파일은 아래 정확한 top-level 필드를
갖는 `external-merge-checks-v1`이다. `head_sha`는 original approved head이며 squash/test-merge SHA가 아니다.

```json
{
  "version": "external-merge-checks-v1",
  "run_id": "<run>",
  "pr_number": 123,
  "repository": "21in7/TavernofSoul",
  "head_sha": "<original-head-40hex>",
  "responses": [
    {"method": "GET", "url": "https://api.github.com/repos/21in7/TavernofSoul/commits/<original-head-40hex>/check-runs?filter=latest&per_page=100&page=1", "status": 200, "complete": true, "body": {"total_count": 0, "check_runs": []}}
  ]
}
```

이 예제의 빈 collection은 shape 설명일 뿐 성공 근거가 아니다. 각 response의 필드는 정확히
method/url/status/complete/body다. page=1부터 순서대로 모든 실제 page를 저장한다. HTTP 200과
complete=true, 페이지당 최대100개, 일정한 total_count, 전체 길이 일치와 중복 없는 양의 check ID를
검증한다. plain REST body의 total_count가 check_runs 길이와 같으면 한 페이지 완료로 인정한다.
total_count가 더 크면 추가 page가 필수이며, truncated=true/complete=false, 누락·중복·다른 URL은 거절한다.
body는 실제 REST object 또는 기존 response_data가 해석하는 connector envelope만 허용한다.
proof의 같은 head/page GET과 normalization 후 전체 body가 같아야 하며 실패/성공·suite가 충돌하면 중단한다.
proof의 기존 head/test-merge check-runs, status와 나머지 모든 GET 계약도 그대로 필수다.

native checks_gate의 latest-name, GitHub Actions app, check-suite, selection/execution plan 및 status gate를
그대로 적용한다. `Offline harness (SQLite)`, `MySQL harness`, `Chromium browser harness` 각각이 정확한
승인 head에서 completed/success여야 한다. missing/pending/failure/cancelled/skipped/neutral을 성공으로
추정하지 않으며 다른 head의 결과나 suite metadata를 섞지 않는다. 별도 성공 증거는 merged cleanup의
진입만 허용한다. 예전 journal CI 기록이나 transport receipt를 고치거나 새 CI를 실행하지 않는다.

두 파일 각각을 위와 같은 response_snapshot으로 단 한 번 열고 bytes/hash를 메모리에 고정한다.
파일 누락·digest 불일치·malformed JSON/schema/coverage는 cleanup checkpoint나 Git mutation 전에 중단한다.
검증 후 경로를 재오픈하지 않으며 두 입력 모두 resume와 next_action의 정확한 경로/hash에 고정된다.

## Cleanup과 archive의 순서

외부 경로의 순서는 proof/필요한 checks 검증 → 현재 exact ID의 미전송 merge 요청 durable 폐기 기록
(awaiting_ci는 request_id=null/status=no_request라는 별도 disposition) → park/복원 검증 또는
already_synced readback → 필요한 fetch/ff-only → exact SHA lease 원격 compare-delete → prune → local compare-delete → 완료
검증 → native save → archive 단1회 → 실제 archive 재읽기다. 기존 Cleanup.run 기본 순서는 유지하고
run_external opt-in만 sync를 원격 삭제 앞으로 옮긴다. native begin_cleanup/accept_cleanup/save를
사용하며 external checkpoint가 journal/report 전후 해시를 연결한다. UI merge는 transport receipt가 아니다.

원래 journal/approval/report와 현재 pending merge ID를 대조한다. 그 ID의 begin/complete/parent attempt,
inflight 또는 불명 dispatch가 있으면 거절한다. 다른 과거 요청의 complete receipt는 현재 pending 전송이
아니며 모든 historical transport/attempt bytes를 보존한다. receipt/head.json을 새 journal hash로 고치거나
삭제하지 않는다. external checkpoint가 있으면 native request/accept/resume/cleanup와 parent next/accept를 차단한다.

awaiting_ci에서는 승인 PR/head를 대조하고 현재 pending write/request, incomplete begin receipt,
inflight/unknown dispatch 또는 완료 receipt로 설명되지 않는 parent attempt가 있으면 거절한다.
최신 receipt와 현재 journal의 일치도 최초 진입 때 확인한다. 완료된 과거 receipt의 nonzero exit가
awaiting_ci 종료를 나타낼 수 있으며 이를 새 pending write로 간주하지 않는다. merge 요청을 만들거나
accept하지 않고 native resume/inspection/publication을 호출하지 않으며 기존 deadline도 갱신하지 않는다.
이 허용은 기존 정확한 known-unsent merge 요청의 폐기를 없애거나 sent 요청을 허용하지 않는다.

park 호출은 source/GitHub mutex 밖에서 기존 API로 수행하며 각 critical 단계는 source → GitHub 순서로
잠근다. 없는 lock은 no-follow로 생성하고 기존 inode/mode를 보존한다. 승인 after가 checkout에 남으면
park가 전체 승인/backup을 검증하고 복원한다. 이미 parked면 before hash+full POSIX mode·HEAD·index/status·
after snapshot을 재확인한다. ff-only 후에는 승인 bytes/full POSIX mode를 검증하며 mode 보정은 정확한
승인 bytes를 다시 확인한 파일만 허용한다. 사용자 변경, staged/untracked/ignored 충돌, 다른 worktree,
operation, hidden index flags, local commit과 origin raw/effective URL·fetch mapping 보호를 유지한다.

운영 checkout이 올바른 base branch에서 **정확한 proven merge SHA**에 이미 도달했다면 park를 호출해
base로 되돌리거나 redundant merge를 하지 않는다. 승인 전체 tree/범위/blob hash/full POSIX mode,
backup/workspace, source/index/status, origin/refspec/remote base 및 존재하는 retained park snapshot을
검증하고 external `already_synced` 단계와 cleanup sync의 `already_synced_readback` 사유를 기록한다.
retained park checkpoint의 존재만으로 현재 HEAD를 원래 base로 가정하지 않는다. park 증거가 없으면
이를 만들거나 parked 상태를 위조하지 않는다. 다른 commit/branch, dirty/staged/untracked 상태,
ignored 충돌, hidden index flag, 다른 worktree의 ref 점유는 기존처럼 중단한다. mode만 다르면 정확한
승인 bytes를 다시 검증한 기존 좁은 repair만 허용하며 사용자 bytes를 교체하지 않는다.

역사적 관측: 사용자 제공 자료에는 archive가 cleanup보다 먼저 호출됐다는 문제가 있었고 당시 위치는
`harness/git_publish.py:904`였다. 줄 번호는 영구 API가 아니며 그 관측과 #119의 성공을 이번 구현의 검사
성공 근거로 재사용하지 않는다. 이번 worker는 코드를 편집했으며 실행 검증은 orchestrator 책임이다.

## 중단과 명시적 재개

`external-merge.json`은 version=`external-merge-v1`이며 run/PR/proof/checks/approval identity, original journal/report
해시, 보존된 historical transport/attempt 해시, discard exact ID 또는 no_request disposition/merge SHA/evidence digest, park hash 또는 실제 부재,
completed 단계, native journal/report pre→post intent/history와 archive_attempted를 durable 기록한다.
반환 JSON은 parent-commands-v1의 stage/code/executed/side_effects/completed_stages/next_action으로 완료와
시도·불명을 구분한다. 성공 관측된 merge/cleanup은 뒤 archive pending에도 보존한다.

자동 retry는 없다. checkpoint 없는 첫 호출에 `--resume`을 쓰면 거절하고, checkpoint 있는 run을 같은
일반 호출로 반복해도 `external_explicit_resume_required`다. 사람이 증거를 검토한 뒤 아래처럼 새 명시 호출한다.

```sh
make agent-git-external-merge RUN_ID=<same-run> PR_NUMBER=<same-n> PROOF_FILE=<same-proof> RESPONSE_SHA256=<same-sha256> RESUME=1
# awaiting_ci로 시작한 run은 완료 후 재진입에도 두 입력을 모두 그대로 제공한다.
make agent-git-external-merge RUN_ID=<same-run> PR_NUMBER=<same-n> PROOF_FILE=<same-proof> RESPONSE_SHA256=<same-proof-sha256> CHECKS_FILE=<same-checks> CHECKS_SHA256=<same-checks-sha256> RESUME=1
python -m harness.parent_commands agent-git-external-merge --run-id <same-run> --pr-number <same-n> --proof-file <same-proof> --sha256 <same-proof-sha256> --checks-file <same-checks> --checks-sha256 <same-checks-sha256> --resume
```

CLI는 같은 인자와 `--resume`이다. run/PR/proof/checks 경로·bytes·hash/approval 및 실제 상태가 다시 일치해야 한다.
완료된 ff/delete/archive 쓰기를 반복하지 않는다. write intent 후 crash가 발생하면 실제 HEAD/승인
bytes/mode나 ref 부재로 완료를 읽어 확인한다. 이전 ref가 그대로이거나 결과가 불명이면 stop한다.
재개 시 fetch/prune은 기존 cleanup의 검증 경계를 따르며 중단된 park는 기존 park의 조정 경계를 유지한다.
native save는 intent의 post journal hash와 native summary/완료 status의 report가 함께 관측될 때만 회수하고
report hash를 history에 고정한다. 일부만 쓰인 경우 중단한다.

archive는 source/GitHub lock을 해제한 뒤 기존 archive_run을 한 번 호출한다. 호출 전 archive_attempted를
기록하며 기존 archive state/transfer/frozen/payload가 있어도 새 전송하지 않는다. archive pending이면
별도 승인한 기존 archive 복구가 필요하다. external `--resume`은 archive_run을 다시 호출하지 않고
verify_run_archive 및 verify_current_result로만 재읽는다. 실제 증거가 없으면 pending을 유지한다.
완료 증거가 생긴 뒤 같은 proof로 재개하면 읽기 검증으로 verified를 반환한다. 예외/API 원문은 출력하지 않는다.

## 보고할 상태

- PR·필수 CI·UI merge: 각각 실제 조회 또는 종료 결과로 확인된 상태.
- 삭제·cleanup: 대상 비교와 정리가 완료됐는지, 아니면 pending인지.
- archive: 실제 보관 완료가 확인됐는지, 아니면 pending인지.

merge 성공과 cleanup/archive 완료를 구분한다. 하나라도 pending이면 전체 완료가 아니며 다른 단계의 결과로 완료를 추정하지 않는다. 준비 상태나 정상 종료 결과 없는 호출도 성공으로 세지 않는다.

실패 후 재시도 금지와 증거 수준은 [실패 보고](failure-reporting.md), 실행 경계는 [run 수명 교훈](../lessons/run-lifecycle.md)을 따른다. 기존 상세는 읽기 승인된 [workflow](../workflow.md)에서 확인한다.

[index로 돌아가기](../index.md)
