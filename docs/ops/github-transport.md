# GitHub 전달과 응답 연결

요약: parent가 fork 대상과 원래 요청을 유지하며 파일 기반 응답을 엄격하게 수락한다.

일반 운영 정본은 private `logs/harness/harness-runbook-core.json`이다. 사용자 직접 승인한
표준 parent 명령·file accept·merge 전 stop 경계를 적용하며, 과거 지시로 PTY 입력이나 즉석
게시·복원을 허용하지 않는다. 이 요약은 게시 권한이나 복구 정책을 새로 부여하지 않는다.

[ADR0039](../adr/0039-standard-parent-git-commands.md)의 게시·park 경계와 이미 merge된 #117~#122의
명령을 기본 운영 절차로 사용한다. 실제 인자명은 `Makefile`, 결과 필드는 `harness/parent_commands.py`가
권위다. Make와 Python3.8 표준라이브러리 CLI의 호출·capability 주입 예제는
[workflow](../workflow.md#trusted-parent-bridge와-즉시-handoff)에 둔다. runbook core는 모델 읽기·편집
대상에서 제외한다. 이번 문서 PR의 사용자 UI merge 뒤 parent가 별도로 갱신한다.

## 게시 대상과 소유권

PR compare 대상과 compare URL의 기준은 fork `21in7/TavernofSoul`이다. 원본 저장소로 보내지 않는다. 기존 게시 권한·필수 CI를 유지하며 모델은 게시·검사·Git 명령을 실행하지 않는다. credential은 사용자만 다룬다.

PR 설명도 자동 승인 검토 대상이다. PR #102의 설명 거절과 상한 구분은 [GitHub 복구](../lessons/github-recovery.md)를 따른다.

## 파일 기반 응답 framing

parent는 저장 전용 `writeResponseFile` capability로 원응답을 owned private 디렉터리의 exclusive
0600/nlink=1 JSON 파일에 보존하고 fsync/readback한 `{path,bytes,sha256}`을 받는다. capability는
transport·임시 Python launcher·ledger를 구현하지 않는다. `agent-git-accept-file`에 run ID·exact
request ID·response-file·예상 SHA256만 전달한다. 명령이 private 부모 디렉터리와 초기 fd의
no-follow/owner/regular0600/nlink1/size 상한8MiB를 확인하고 파일을 단1회 열어 bounded bytes를 읽는다.
dup(fd)는 경로 재오픈이 아니다. 메모리 bytes의 SHA256을 parent 값과 대조한 뒤 UTF-8/duplicate key/
추가 JSON을 검사한다. 초기 hash 불일치는 dispatch·lock·checkpoint 전 side effects 없이 거절한다.
검증 후 파일/부모 경로를 재stat/재오픈하지 않는다. 입력이 교체·수정·삭제돼도 검증된 snapshot만
frame/native receipt에 사용하며 이미 수락한 작업을 응답 경로 변화 때문에 실패로 바꾸거나 재전송하지 않는다.
명령은 원응답을 삭제하지 않는다. internal journal/attempt의 private_input attachment/freshness와
lock/frame의 ownership/fsync/readback/cleanup은 응답 snapshot과 별개로 유지한다.

명령이 owned private0600 frame에 각 줄<=2048의 base64와 마지막 `.` 줄을 쓰고 fsync/readback한다.
검증된 fd를 `python -m harness.git_transport accept --stdin-base64`의 stdin으로 연결하는
비대화형 subprocess 파일 리다이렉션은 명령 내부 책임이다. 명령이 자기 임시 frame을 삭제하며
durable native receipt/attempt 증거는 보존한다. parent는 frame/READY/hash/delete를 재구현하지 않는다.

응답 본문 shell argv·대화형 stdin·nonempty write_stdin/PTY 입력은 금지한다. 기존 workflow/proc의
빈 chars 완료 polling은 입력 전송과 구별한다. 원문 응답·credential·private 설정·파일내용을
공개 terminal에 출력하지 않는다. 프레임 준비만으로 외부 작업이나 응답 수락 성공을 주장하지 않는다.

명령은 native accept stdout의 첫 줄이 정확히 `transport-input-ready-v1`일 때 그 한 줄만 제거하고
나머지를 단일 JSON으로 파싱한다. READY 누락/추가·불일치·잘림·부분 frame·추가 JSON·자식 종료불명은
stop이며 재accept하지 않는다. 전체32MiB/inline32KiB/chunk12288byte와 size/hash 검증을 유지한다.
큰 결과는 검증된 `parent-result-file-v1` descriptor(path/bytes/sha256/encoding)로 반환할 수 있다.
parent는 현재 run의 명령이 검증한 descriptor만 읽기 전용 capability로 읽고 bounded bytes·hash·
UTF-8/JSON과 run/request identity를 대조한다. 이전 run의 경로를 재사용하지 않는다.

상위 명령은 성공·실패·인자 오류 모두 단일 `parent-commands-v1` JSON이다.
command/run/status/stage/code·executed/side_effects·native_exit_code·next_action을 보존하며
next_action의 허용 명령/필수 인자 또는 승인 필요/stop에 따른다. failed/needs_reconciliation/
awaiting_ci를 구별하고 bridge가 CLI 실패 단계를 그대로 전달한다. 정상 종료불명을 성공으로 세지 않는다.
종료 코드0이나 `approval_required=false`만으로 다음 작업을 시작하지 않는다. action별 필수 인자와
정확한 stop 처리는 [parent 결과 판독](../workflow.md#trusted-parent-bridge와-즉시-handoff)을 따른다.

## 다음 요청과 복구

`agent-git-next`는 run의 첫 요청에만 native request를 단1회 호출한다. 이후 accept-file 결과의
다음 요청 파일을 검증해 이어 쓰며 next를 다시 호출하지 않는다. standalone parent의 기본 순서는
next → next-file reader → exact connector 한 번 → private response → accept-file → 반환된 다음 파일
reader 반복 → 실제 CI3 확인 → stop_before_merge → park다.

```sh
make storage-path TARGET=workflows RUN_ID=<run>
make agent-git-next RUN_ID=<run>
make agent-git-next-file RUN_ID=<run> REQUEST_FILE=<returned-request_file.path> RESPONSE_SHA256=<returned-request_file.sha256>
make agent-git-accept-file RUN_ID=<run> REQUEST_ID=<exact-id> RESPONSE_FILE=<owned-0600-json> RESPONSE_SHA256=<exact-bytes-sha256>
make agent-worktree-park RUN_ID=<run>
```

각 connector 호출 전에 reader의 `exact_request` 또는 큰 `exact_request_file` descriptor를 현재 run에
결합해 bounded bytes/hash/UTF-8/JSON을 확인하고 기존 `next_action/tool/arguments`와 대조한다.
reader는 run/request/native result/journal SHA와 receipt를 연결하며 old-run 경로·ID·stale·변조·
begin/inflight/unknown dispatch·수락 완료를 거절한다. `redispatch_authorized=false`이며 전송 승인이나
native request 재발급이 아니다. `next_file_write_failed`이면 보존된 native 결과를 재accept하지 않고 멈춘다.
큰 요청의 reader는 transport chunk의 operation/index/offset/bytes·`chunk_sha256`과 전체
bytes/`sha256`을 구별해 검증한 뒤 현재 resolved run의 `parent-exact-<request_id>.json`에
정확한 `{tool,arguments,request_id}` JSON을 exclusive owned0600/nlink1로 저장·fsync/readback한다.
`exact_request_file`은 `version=parent-exact-request-v1`, path/bytes/sha256/encoding,
run_id/request_id/operation_id/request_sha256과 `request_from=verified_exact_request`를 반환한다.
parent는21개 조각을 직접 조립하지 않고 이 파일 하나의 경로·권한·크기·hash·UTF-8/JSON·identity를
확인해 tool/arguments를 connector에 전달한다(`arguments_from=verified_exact_request.arguments`).
같은 현재 요청은 기존 파일의 정확한 bytes/hash/identity 재검증만 허용한다. 충돌·변조·부분 파일은
보존하고 stop하며 수락된 요청이나 오래된 run의 재전송 권한은 생기지 않는다.

next/next-file/accept-file의 `--minimum-write-seconds`(Make `MINIMUM_WRITE_SECONDS`, 기본300)는
유한 양수인 로컬 입력이다. 0/음수/bool/NaN/무한을 거절하며 ledger/config/deadline에는 저장하지 않는다.
next-file/accept-file 결과의 `publish_remaining_seconds`는 현재 journal의 Unix epoch 초 `deadline`에서
현재 wall clock 초를 뺀 값(0 미만은0), `minimum_write_seconds`는 이번 명령의 최소 초다.
deadline 누락/잘못된 값은 추정하지 않고 fail-closed한다. 게시 단계에서는 사람 승인을 기다리는 동안에도
deadline이 흐른다. 남은 초가 최소값 **미만**이면 다음 쓰기를 `code=deadline_insufficient`,
`next_action.action=stop`으로 막고 dispatch 가능한 요청·파일 descriptor·native/transport payload를
반환하지 않는다. 정확히 최소값이면 허용하고 read 요청은 잔여 초를 표시하되 이 기준으로 막지 않는다.
첫 next와 finish 내부 reader도 조립 전후 상태·시간을 재검증한다. stop이면 자동 연장·재시도 없이 멈춘다.
예: `make agent-git-next-file ... MINIMUM_WRITE_SECONDS=300`(next/accept-file에도 같은 변수).
이미 실행한 connector 응답은 accept-file로 한 번 수락하고 증거를 보존한 후 다음 쓰기만 gate한다.
`native_result_retained=true`는 native 결과(accept라면 현재 응답 수락 결과)가 보존됐다는 뜻이며
재accept·재전송 승인이 아니다.
native timeout/terminal 실패와 merge 직전 stop 정책은 그대로 유지한다.
기존 bridge는 next/accept 상위 CLI를 호출하고 그 CLI의 `finish`에서 다음 파일 생성·검증을 거친다.
새 bridge 메서드나 connector-dispatch CLI는 없다. 요청 인자는 eval하지 않으며 실제 connector는
trusted parent만 호출한다. 새 PR URL은 parent artifact에 연결하고 native `poll_after_seconds`를 지킨다.
worker/reviewer/child/discovery/unattended는 실행 권한이 없고 read_only/demo/no_git에서도 게시하지 않는다.

기존 pending/inflight·최신 완료 receipt의 current journal hash/run/request identity를 대조한다.
stale ID·같은/다른 응답 중복·begin/complete/inflight·legacy/transport mismatch는 보수적으로 stop한다.
race의 최종 권위는 native claim이다. pending 재발급·새 ID·unknown dispatch 재전송·receipt 삭제/
재작성·자동 retry를 금지한다. 실제 ledger 값·요청 ID·응답 본문은 공개하지 않는다.

`make archive-verify RUN_ID=<run>` 또는
`python -m harness.parent_commands archive-verify --run-id <run>`은 독립 확인이 필요할 때의 읽기 전용 검증이다.
external-merge 성공의 `archive_verify`가 실제 재읽기를 완료했으면 같은 재검증을 중복 필수 단계로 요구하지 않는다.
resolved active run의 local archived state·frozen payload·receipt를 대조하고, receipt 목적지가
resolved archive 경계의 `workflows/<run>`인지 확인한 뒤 원격 manifest/inventory·bundle·완료
marker를 실제로 다시 읽는다. `verified` 결과의 run·destination·inventory_sha256·bundle_sha256/
bundle_bytes·receipt_sha256은 이 재읽기 근거이며 Git 전달 성공이나 재시도 권한을 뜻하지 않는다.
pending/미완료 state, 누락, hash/marker 불일치, 목적지 해석 실패는 non-success JSON의 stage/code와
실패 종료 코드로 구별한다. mount 확인 뒤 목적지 경로 누락은 `archive_evidence_missing`으로,
mount 확인 실패는 `archive_integrity_failed`로 stop한다. 예외 원문과 source/workspace 내용은 출력하지 않는다. 실행 여부와
side_effects는 읽기뿐임을 기록하며 prepare·lock/임시 파일·전송·freeze/repack·journal/receipt/state
쓰기·fallback·자동 retry 없이 증거를 보존한다. 실패 시 next_action의 stop에 따라 별도 조정한다.

사용자 UI squash merge signal 뒤 parent는 실제 connector의 PR/check-runs 전 페이지와 필수 GET 원문을
현재 run의 private 파일로 보존하고 manifest를 준비한다. 명령은 connector를 호출하지 않는다.

```sh
make agent-git-proof-build RUN_ID=<run> PR_NUMBER=<n> INPUT_DIR=<resolved-run>/proof-input-<label> RESPONSE_SHA256=<manifest-sha256>
make agent-git-external-merge RUN_ID=<run> PR_NUMBER=<n> PROOF_FILE=<returned-path> RESPONSE_SHA256=<returned-proof-sha> CHECKS_FILE=<returned-path> CHECKS_SHA256=<returned-checks-sha>
```

proof-build가 exclusive0600 생성·해시·재읽기한 `proof_file`/`checks_file` 경로·sha256 및
`next_action.required_arguments`를 그대로 external-merge에 전달한다. missing page/URL/head 등은
native 계약대로 거절한다. manifest·출력·partial IO 계약 및
external-merge-proof-v1의 정확 schema·필수 GET·단계별 절차는 [merge cleanup](merge-cleanup.md)에 둔다.
응답 입력은 위 accept-file과 동일한 single-open immutable memory snapshot이다. parent가 실제 읽은
PR/head/squash/CI/status/repository/branch protection/tip/open PR 전체 조회를 native gate로 검증하고
누락 시 `next_action={action:collect_get,method,url,then}`과 stop을 반환한다. 불완전 페이지·오류는 부재가 아니다.
원래 승인 head/base와 squash 전체 tree/단일 parent 관계를 증명해야 하며 Update branch head 변경과
base 전진/추가 patch는 보수적으로 stop한다. GitHub 앱/HTTP 호출은 parent만 수행한다.

proof/별도 checks → 현재 exact pending 미전송 merge ID의 durable 폐기(또는 awaiting_ci의 no_request) →
park/이미 parked/이미 synced 확인 → 필요한 fetch/ff-only →
exact SHA lease remote delete/prune/local delete → cleanup 검증/native save → archive 단1회 → 실제
archive-verify 재읽기 순서다. 현재 pending begin/complete/parent attempt/inflight/unknown dispatch는
거절한다. 과거 다른 요청의 완료 receipt는 현재 전송으로 오인하지 않으며 historical transport bytes를
고정·보존한다. UI merge를 agent 응답으로 위조하지 않는다. external checkpoint가 journal/report
pre/post hash를 연결하고, 해당 run의 native request/accept/resume/cleanup와 parent next/accept를 막는다.
parent는 임의 restore를 선행하지 않는다. 정확한 proven merge SHA이면 `already_synced`가 정상이며
다른 commit은 거절한다. deployed 명령이 없는 신규 구현 PR의 최초 적용에만 사용자 명시 승인의
사전 ff-only 예외를 허용한다. 일반 운영에서 수동 ff-only를 선행하지 않는다.

checkpoint 이후 일반 재호출은 중단한다. 별도 사용자 승인 복구에서 같은 run/PR/proof/checks/approval
identity로 `RESUME=1`(CLI `--resume`) 재진입만 허용하며 자동 재시도·unknown 쓰기 재전송이 아니다.
실제 상태로 완료된 ff/ref 삭제만 회수하고 불명 쓰기를 반복하지 않는다. archive intent를
먼저 기록하며 pending이면 merge/cleanup 증거를 유지한다. 기존 archive 복구를 별도 승인받아 완료한 뒤
external --resume은 verify_run_archive/verify_current_result만 재읽고 archive_run을 재전송하지 않는다.
parent-commands-v1의 stage/code/executed/side_effects/completed_stages/next_action을 읽어 남은 필수 인자와
중단 단계를 구별한다. reconcile은 아래 좁은 추가 계약을 따른다. resume-ci는 미구현 A2d2b 후속이며 필요하면 사용자 승인된
[GitHub 복구](../lessons/github-recovery.md)로 별도 조정한다. 옛 CLI나 즉석 script로 우회하지 않으며
native resume 뒤 journal/transport head mismatch를 head rewrite로 해결하지 않는다.

명령이 거절하면 stage/code/executed/next_action과 실제 상태부터 기록한다. `missing_get`의
`collect_get`도 현재 task의 승인 호출 횟수·중단 조건을 늘리지 않는다. 재시도 금지 지시가 있으면
새 hash로 재호출하지 않는다. legacy CLI·수동/즉석 script는 거절 뒤 별도 사용자 승인 복구에서만
다루며 자동 우회·새 ID로 같은 쓰기·receipt/journal 삭제나 hash 재작성은 금지한다.
exact 원요청 ID와 보존 응답의 실제 결과 확인도 그 승인 복구에서만 수행한다.

park는 승인 전체 scope/review/check/apply·HEAD baseline·index/status·hash+POSIX mode·native backup
before를 검증한 뒤 approved after hash/full POSIX mode snapshot과 file별 durable checkpoint를 보관하고 baseline 복원·
git status clean을 확인한다. unrelated tracked/staged/untracked·사용자 변경은 source mutation 전
거절하고 ignored 운영데이터를 보존한다. project/source → GitHub lock 순서와 기존 inode/mode를
유지하고 없는 lock도 안전한 no-follow 생성 경로로 처리한다. busy/다른 owner/symlink lock은 거절한다.
snapshot 충돌·중단은 stop, 이미 parked는 read-only 재확인이다. parked는 merge 후 완료가 아니다.
미merge PR 게시·CI 확인 뒤 park로 운영 baseline clean을 복원한다. known-unsent merge 대기는
허용하지만 begin/inflight/전송불명 쓰기는 거절한다. UI merge 뒤의 park·복원 확인은 external-merge가 담당한다.
storage-path는 read-only resolve와 explicit prepare를 구분하고 생성 경로를 JSON에 기록한다.
v2 reports는 active artifacts 내부이며 private/absolute/no-follow/mount/floor·no fallback을 유지한다.
`Storage.archive_root` 같은 속성을 추측하거나 이전 run prefix를 재사용하지 않으며 prepare 실패 시 멈춘다.

## 완료 오류 receipt의 관측 연결

[ADR0041](../adr/0041-parent-git-reconcile.md)은 기존 A1/A2 역사 설명에 좁은 추가 계약을 둔다.
trusted parent만 다음 명령을 호출한다. 모델 worker/reviewer는 증거 파일·실제 journal을 읽지 않는다.

```sh
make agent-git-reconcile RUN_ID=<original-run> REQUEST_ID=<original-write-id> EVIDENCE_FILE=<absolute-private-json> EVIDENCE_SHA256=<sha256-of-exact-file-bytes> MINIMUM_WRITE_SECONDS=300
```

Make 변수는 각각 CLI `--run-id`, `--request-id`, `--evidence-file`, `--evidence-sha256`,
`--minimum-write-seconds`에 대응한다. EVIDENCE_FILE은 원응답 대체 파일이 아니라 아래 GET 묶음이다.
부모0700·owned0600/nlink1 regular·no-follow·8MiB·UTF-8·duplicate-key 거절·SHA256 및
single-open memory snapshot은 accept-file과 동일하다. 원문 argv/PTY/nonempty write_stdin·임의 저장/
게시 script를 사용하지 않는다. parent는 기존 private 저장 capability를 사용하고 원본을 보존한다.

top-level 필드는 정확히 `version="git-reconcile-evidence-v1"`, `run_id`, `request_id`,
`target`, `tool_arguments_sha256`, `approval_sha256`, `journal_sha256`, `previous_receipt_sha256`,
`responses`다. target은 `{repository,base:{ref,sha},head:{ref,sha}}`이며 승인 repository/base와
원 pinned branch/head SHA다. tool digest는 immutable 원요청 stdout에서 찾은
`{tool,arguments}`를 기존 transport.encode의 UTF-8 compact JSON으로 인코딩한 SHA256이다.
나머지 hash는 각각 승인 파일·직전 journal·직전 완료 오류 receipt의 **정확한 bytes**다.
caller target만 신뢰하지 않고 보존된 원 ID/tool/arguments와 native 요청 구성을 다시 대조한다.

각 responses row의 정확한 필드는 `{method:"GET",url,status,complete,page,coverage,body}`다.
body는 실제 REST JSON 본문이며 connector 오류를 정상 body나 빈 배열로 바꾸지 않는다.
object는 page=null/coverage="object", collection은 실제 정수 page/coverage="page"다.
complete=true는 parent가 해당 응답 전체를 읽었다는 진술이며 인간 신원의 증명은 아니다.

- branch: 같은 repository `/git/ref/heads/<exact-branch>`의 ref/type/원 SHA를 확인한다.
- create-PR: 위 ref와 `/pulls?state=all&head=<percent-encoded-owner:branch>&per_page=100&page=<p>`를
  마지막 100개 미만 페이지까지 확인하고 유일한 후보의 `/pulls/<n>`을 확인한다. closed PR도
  후보에서 빼지 않는다. 번호·repository/base/head ref와 SHA·open/non-draft·title/body/
  maintainer_can_modify가 원요청과 같아야 한다. UI metadata 변경도 별도 승인 없이 수용하지 않는다.

결과는 기존 parent-commands-v1에 `decision=matched|absent|mismatch|unknown`을 더한다.
완전한 exact-ref 404/Not Found와 같은 repository GET의 200/full_name 증거, 또는 완전한 PR
전 페이지의 빈 결과만 absent다. private repository 접근 실패의 404를 부재로 추정하지 않는다. 403/조회오류/
불완전 페이지는 unknown, 대상/SHA/의미 불일치·복수 후보는 mismatch이며 모두 stop이다.
필수 GET 누락은 unknown 및 `next_action={action:collect_get,method,url,...}`로 정확한 URL을
반환하고 멈춘다. 명령 내부 HTTP/connector/fallback/자동 retry는 없다. merged PR은 unknown과
`required_route=[agent-git-proof-build,agent-git-external-merge]`로 기존 proof 경로를 안내한다.
commit/tree 등 검증하지 않는 타입, begin 미완료/inflight, legacy 변경·손상·external-merge 소유 run은 중단한다.

matched만 별도 reconcile operation identity로 journal을 전진시킨다. 새 GitHub 쓰기 ID가 아니다.
원 begin/complete/response/stdout/stderr/parent attempt와 hash를 보존하며 새 receipt의 link는
직전 완료 hash·원 요청 ID/tool/args digest·증거/approval digest·과거 immutable 파일 hash를 연결한다.
별도 before snapshot은 원 journal/report bytes를 보존한다. native 순수 검증/저장 API와 source →
GitHub lock 순서를 사용하며 legacy accept CLI를 호출하지 않는다. journal의 operation/link digest,
전후 journal hash·새 begin hash·stdout hash를 검증하고 새 complete를 durable 생성한 뒤 head를 전진시킨다.
transport/parent evidence/next-file/park/external-merge가 같은 연결을 검증한다.
durable intent 이후 부분 IO/interrupt는 inflight를 남겨 stop하며 fake complete·자동 재실행하지 않는다.
같은/다른 증거 재호출은 already_reconciled/stop이고 첫 증거·다음 요청을 재반환하지 않는다.
기존 accept-file의 conflicting_response/executed=false도 유지한다.

deadline은 갱신하지 않는다. 만료 뒤에도 matched 관측을 기록할 수 있지만 다음 요청/descriptor는
발급하지 않는다. PR이 있으면 awaiting_ci, 없으면 failed로 게시를 중단한다. 기본 최소300초의
정확한 경계는 허용하고 검증·저장·export 중 시간 감소를 다시 검사한다. 부족하면 다음 쓰기를
내보내지 않는다. 연결 성공은 delivery 완료·CI 성공·merge가 아니다. 시간 안의 첫 matched 결과만
기존 next-file → catalog 대조 → 실제 connector → private response → accept-file 순서로 이어간다.
실제 CI3/expected head/stop_before_merge와 park·사용자 UI merge proof·cleanup/archive 계약을 유지한다.
이 회귀는 합성 작성 상태다. 새 전체 Claude 검토의 documentation 판단·parent full make check와
실제 필수 CI3 성공을 별도로 관측해야 하며 이 문서는 실행 성공을 주장하지 않는다.

## 완료 증거

외부 읽기 조회, 응답 수락, 다음 요청 수신, CI, 머지는 서로 다른 증거다. PR이 보인다는 사실만으로 남은 단계가 완료됐다고 쓰지 않는다. 고정 비교의 불일치와 전송 실패는 [실패 보고](failure-reporting.md)에 따라 보고하며 parent는 workflow·모델·검사를 재시도하지 않는다.

현재 인계는 `make agent-workflow` 새1회 → 새 Claude 전체 diff 독립 의미검토 → 실제 diff 기준 ADR0031
자동 정책의 필수 검증 → scoped apply →
parent GitHub PR/필수CI3 성공 별도 기록 → merge 전 정지 → park로 #122 기준 baseline clean 확인이다. 실패 시 parent는 workflow·모델·검사를
재실행하지 않고 기존 native bounded repair만 허용한다. run 전후 같은 고정-cutoff metrics·
scope/config/cron 불변을 비교한다. 운영 배포·VM 이전은 없고 2026-11-10까지 배포 체계와
모델/예산/auth/storage/scheduler 설정을 유지한다. worker/reviewer는 검사·Git·네트워크·운영 명령·
workflow·재위임을 실행하지 않는다. 매 리뷰의 문서 영향과 최종 독립 Claude의 새
`documentation={status,files,reason}` 판단은 필수이며 Markdown 검사가 의미 완전성을 증명하지 않는다.

[merge와 정리](merge-cleanup.md)는 사용자 UI merge signal 뒤 절차이며 이번 작업의 자동 merge 승인이 아니다. 공개 범위는
[공개 근거](../lessons/public-evidence.md), 기존 상세는 읽기 승인된 [workflow](../workflow.md)를 따른다.

[index로 돌아가기](../index.md)
