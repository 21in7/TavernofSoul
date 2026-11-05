# 0039. Trusted parent 게시·복원 명령 표준화

- 상태: 승인(accepted), 사용자 직접 승인 A1; 새 독립 의미검토·full 검사·PR/CI3 대기, merge 전 정지
- 기록일: 2026-11-05
- 기록 성격: 새 결정, 실행 성공 기록 아님
- 대체 관계: [0024](0024-immediate-batched-github-transport.md)의 parent 응답 전송·호출 책임만 부분 대체; native 게시·저장·검증 정책 유지

## 문맥

parent의 즉석 게시·복원 adapter는 응답 framing, 저장 경계와 lock 준비 책임을 흐리게 한다.
과거 `accept --stdin-base64`의 대화형 write_stdin/PTY 교착, v2 artifacts 밖 MySQL report
준비 실패, 존재하지 않는 github.lock의 stat 가정은 이번 요구의 근거이며 새 성공 증거가 아니다.
archive 이후 없는 Storage.archive_root 속성 접근과 native resume-ci 뒤 journal/transport head
hash mismatch는 A2 문제다. A1에서 속성을 추측하거나 receipt/head를 고쳐 우회하지 않는다.

## 결정

A1 parent는 Make와 Python3.8 표준라이브러리 CLI의 다음 네 상위 명령만 사용한다.
즉석 게시·복원 script는 금지한다. `harness/parent_commands.py`와 `worktree_park.py`에 상위
책임을 모으고 기존 git_publish/git_transport/git_cleanup/storage 내부 계약을 재사용한다.

| 명령 | 입력·책임 | 다음 행동과 중단 경계 |
| --- | --- | --- |
| agent-git-next | run ID; 첫 native transport request 단1회 | accept 결과의 다음 요청을 직접 사용; 기존 receipt/pending/inflight의 불명 dispatch 재반환 금지 |
| agent-git-accept-file | run ID·exact request ID·저장된 JSON 파일·예상 SHA256; 안전한 frame/READY/결과 검증 | 원응답과 native 증거 보존; stale/duplicate/부분 frame/종료불명은 재accept 없이 stop |
| agent-worktree-park | run ID; 승인 전체 검증·after snapshot·파일별 baseline 복원 | parked는 source 복원 확인일 뿐 merge 후 cleanup/완료 아님; 중단·충돌은 stop |
| storage-path | target·필요한 run/category; 기존 resolver의 resolve 또는 explicit prepare | 생성 경로를 JSON에 기록; prepare 실패 후 전달·검사 금지, fallback 없음 |

성공·실패·CLI 인자 오류 모두 단일 `parent-commands-v1` JSON이며 command/run/status/stage/code,
executed/side_effects/native_exit_code와 next_action을 보존한다. 인자 오류의 run은 null일 수 있다.
next_action은 허용 connector/명령·필수 인자 또는 승인 필요 여부와 stop을 구조화한다.
failed/needs_reconciliation/awaiting_ci와 native nonzero를 성공으로 바꾸지 않는다. stdout에는
임의 로그·소스·credential을 섞지 않으며 결과는 private parent 소비용이다.
JSON의 run은 CLI --run-id에 대응한다. 인자 오류는 stage=arguments/code=invalid_arguments이며
exit0이나 stop의 approval_required=false가 후속 게시·merge·재실행을 승인하지 않는다.
parent는 [action별 판독 계약](../workflow.md#trusted-parent-bridge와-즉시-handoff)에 따라
반환된 다음 요청의 exact ID와 필수 인자를 사용하거나 stop한다.

### 파일 accept와 bridge

trusted parent는 저장 전용 `writeResponseFile({runId,requestId,text,bytes,sha256})` capability를
주입한다. exclusive owned0600/nlink=1 파일을 private 디렉터리에 저장하고 fsync/readback 후
`{path,bytes,sha256}`을 반환한다. 원응답은 모든 결과에서 보존한다. capability는 저장만 하며
transport·임시 Python launcher·ledger 수정을 구현하지 않는다.

최신 사용자 결정으로 accept-file과 A2c external-merge의 응답 입력은 single-open immutable memory
snapshot이다. private 부모 디렉터리와 초기 no-follow fd의 owner/regular0600/nlink1/size 상한8MiB를
확인해 파일을 한 번 열고 bounded bytes를 읽는다. dup(fd)는 경로 재오픈이 아니다. 메모리 bytes의
SHA256을 parent 값과 정확히 대조한 뒤 UTF-8/duplicate key/추가 JSON/schema를 검사한다. 초기
digest 불일치는 dispatch·lock·checkpoint 전에 side effects 없이 거절한다. 이후 응답 경로를 다시
열거나 size/mtime/ino·부모 attachment를 재검사하지 않는다. disk 입력 교체·수정·삭제에도 기존
snapshot만 frame/proof/native receipt에 사용하고 이미 수락한 작업을 실패로 바꾸거나 재전송하지 않는다.
원응답 삭제는 추가하지 않는다. 내부 journal/approval/receipt freshness·private_input attachment와
source/lock identity·frame ownership/fsync/readback/cleanup은 다른 계약이며 유지한다.
명령이 owned private0600 frame에 각 줄
<=2048의 base64와 마지막 `.` 줄을 쓰고 fsync/readback한 fd를 비대화형 subprocess stdin에
연결한다. native `python -m harness.git_transport accept --stdin-base64` 호출은 shell=False
인자 배열이다. 응답 본문 shell argv·대화형 stdin·PTY·nonempty write_stdin은 금지한다.

native stdout 첫 줄 `transport-input-ready-v1` 하나만 제거한 뒤 나머지를 단일 JSON으로
파싱한다. READY 누락/추가·잘림·부분 frame·추가 JSON·자식 종료불명은 stop이다. 명령이 자기
임시 frame을 오류 때도 삭제하며 원응답·durable native receipt/attempt 증거는 삭제하지 않는다.
전체32MiB/inline32KiB/chunk12288byte와 envelope·offset/count/size/hash 검증을 유지한다.
큰 결과는 private `parent-result-file-v1` descriptor(path/bytes/sha256/encoding)로 반환할 수
있다. 주입된 readResultFile은 no-follow/owner/mode/nlink와 bytes 상한을 확인해 읽기만 하며
bridge도 전체 bytes/hash·UTF-8/JSON을 대조한다. 파일내용·원응답·private 설정을 공개하지 않는다.

[구체 parent 호출](../workflow.md#trusted-parent-bridge와-즉시-handoff)은 저장 capability 주입부터
next → allowlist connector 한 번 → private response 파일 → accept-file → 반환된 다음 요청
직접 사용까지 기존 bridge로 연결한다. GitHub connector는 trusted parent 앱만 호출한다.
tool/arguments를 eval하지 않는다. PR artifact 연결·native poll interval과 기존 allowlist를
유지하되 merge 요청 실행 전에 stop한다. bridge는 CLI 실패 stage/code를 그대로 전달한다.
빈 chars의 workflow/proc 완료 polling은 응답 입력 전송과 구별한다.

### 저장·잠금·복원

기존 pending/inflight·최신 완료 receipt의 current journal hash/run/request identity를 대조한다.
stale ID·같은/다른 응답 중복·begin/complete/inflight·legacy/transport mismatch는 보수적으로
stop한다. native claim이 race의 최종 권위다. pending 재발급·새 ID·receipt 삭제/재작성·unknown
write 재전송·자동 retry·CI/정책 bypass를 허용하지 않는다.

park는 github-approved.json 전체 scope·review/check/apply·local HEAD baseline·index/status·
파일 hash+POSIX mode·native backup before를 검증한다. 승인 after snapshot을 보관하고
add/edit/delete/mode를 파일별 baseline으로 복원한 뒤 git status clean을 확인한다.
unrelated tracked/staged/untracked와 같은 파일 사용자 변경은 source mutation 전 전부 거절하고
ignored 운영데이터는 건드리지 않는다. reset/clean/stash/전체 add/commit/branch 변경/remote Git/
서비스 실행을 금지한다. durable file별 checkpoint와 snapshot을 검증하며 충돌·중단은 stop이다.
이미 parked는 read-only 재확인만 허용하며 blind 복원하지 않는다.

project/source → GitHub lock 순서를 유지해 source 쓰기와 workflow apply를 직렬화한다.
어떤 lock도 존재한다고 가정하지 않는다. absent는 안전한 no-follow exclusive 생성 경로를 쓰고
existing은 inode/owner/regular/nlink를 검증·보존한다. cron 공통 lock inode/mode를 임의 변경하지
않으며 symlink/다른 owner/busy면 source mutation을 거절한다. native journal/receipt는 직접
덮어쓰지 않는다.

storage-path는 기존 resolver의 reports/workflows/artifacts/temporary/context만 다룬다.
v2 reports는 active artifacts 내부이며 private/absolute/no-follow/mount/floor 계약을 유지한다.
resolve는 read-only, prepare만 명시적으로 생성하며 JSON에 실행·생성 경로를 기록한다.
private storage 설정은 모델에 주지 않는다. archive root 속성을 추측하거나 자동 fallback하지 않는다.

### A2c 사용자 UI merge 이후 명령 연결

사용자가 후속 범위를 A2c 하나로 승인했다. 기존 구조/소유권을 유지하고 기존 proof/park/cleanup/archive
계약을 parent의 한 명령으로 연결한다. 표준 Make 입력은 `agent-git-external-merge RUN_ID=<run>
PR_NUMBER=<n> PROOF_FILE=<private-json> RESPONSE_SHA256=<sha256>`이며 CLI는 같은 의미의
`--run-id/--pr-number/--proof-file/--sha256`이다. GitHub GET은 parent가 수행한다. 정확한 versioned
schema와 required GET, 중단/재개 예제는 [merge cleanup](../ops/merge-cleanup.md)에 둔다.
external-merge-proof-v1은 원래 run/PR/repository/base/head/squash identity와 complete GET responses를
고정하고 native CI3/check_suite/skip·cleanup gate를 재사용한다. 원래 승인 head/base와 동일한 전체
tree·단일 parent 관계를 요구해 Update branch head나 증명 불가 base 전진을 자동 승인하지 않는다.
누락 GET은 정확한 method/url을 반환하고 mutation 없이 stop한다. 단순 merged=true로 쓰지 않는다.

현재 pending exact merge ID의 begin/complete/parent attempt/inflight/불명 dispatch가 없는 경우만
ID·merge SHA·evidence digest가 있는 durable 폐기 기록을 만든다. 다른 과거 요청의 완료 receipt와
external 소유 journal 전환은 구별하고 historical transport/attempt bytes를 고정·보존한다.
native begin_cleanup/save의 journal/report pre→post hash를 external-merge-v1 checkpoint에 연결한다.
receipt/head rewrite나 merge 응답 위조는 금지하며 external 소유 run의 native request/accept/resume/
cleanup와 parent next/accept를 막는다. A2d reconcile/resume-ci는 추가하지 않는다.

순서는 proof → 미전송 폐기 → park/복원 검증 → fetch/ff-only → exact branch compare-delete/prune/
local cleanup → 완료 검증/native save → archive 단1회 → 실제 archive 재읽기다. 기존 Cleanup.run은
바꾸지 않고 opt-in run_external에서 순서를 보장한다. source → GitHub 잠금과 기존 inode/mode를
유지하고 park와 archive는 그 mutex 밖에서 기존 API로 호출한다. 사용자 변경·origin/fetch mapping·
다른 worktree·operation·local commit 보호를 유지하며 ff 후 승인 bytes/full POSIX mode를 확인한다.

재개는 사람이 같은 identity로 새 `--resume`(Make RESUME=1)을 명시한 경우만 허용한다. 완료 쓰기는
반복하지 않고 crash 후 실제 HEAD/bytes/mode·ref 부재로 확인한다. native post journal hash와 report의 native summary/완료 status를 함께 확인한 경우만 전환을 회수하고
report hash를 history에 고정한다. partial/unknown은 stop한다. archive_attempted를 먼저 durable 기록해
pending에서도 merge/cleanup 완료를 보존한다. 별도 승인된 기존 archive 복구 후 같은 proof로 재개하면
verify_run_archive/verify_current_result만 재읽으며 archive_run을 다시 호출하지 않는다.

역사적 실패 관측도 보존한다. 이전 run은 native 2라운드 뒤 exhausted_repair/applied=[]로 끝났고,
같은 2bytes 덮어쓰기 뒤 attachment check가 input_changed를 내지 않은 테스트가 있었다. 실패 당시
stat 값이 없어 timestamp 동일성/파일시스템 원인은 미확정이다. 새 회귀는 읽기 전 same-size 변경과
명시적 mtime 복원에도 digest mismatch를 요구하고, 검증 후 변경은 old snapshot·실제 child 입력·durable
receipt 불변 성공으로 분리한다. 이전 승인/검사 결과와 #119 완료는 새 실행의 성공 근거가 아니다.

## 비교 대안

- 즉석 parent script와 PTY accept 유지: 저장·framing·오류 처리가 매 호출에 분산되고 과거 교착 경계를 반복한다.
- A1에서 reconcile/resume-ci/external-merge/archive-verify까지 구현: 승인 범위를 넓히고 불명 쓰기와 journal/receipt 불일치 복구를 함께 설계해야 한다.
- 네 명령과 보수적 stop: native 검증을 재사용하면서 명시적 입력·결과·복구 책임을 고정한다. 이번에 선택한다.

## 선택 이유

파일 전달과 버전 JSON을 명령이 소유하면 parent는 connector 호출과 저장 capability만 주입한다.
불명 결과를 재전송하지 않고 증거를 보존하므로 이후 승인 복구 판단을 흐리지 않는다.
복원 전체 사전 검증과 file별 checkpoint는 사용자 변경 보존 및 중단 원인 확인에 필요하다.

## 결과·비용·제약

A2b archive-verify는 읽기 전용 검증이며 A2c external-merge는 위 후속 결정으로 연결한다.
A2d reconcile/resume-ci는 미구현이다. 필요하면 현재 승인 복구 절차로 별도 조정하거나 stop한다.
옛 CLI/즉석 script/transport head rewrite로 우회하지 않는다.
child/discovery/unattended/read_only/demo/no_git 거절 경계와 기존 모델/예산/auth/storage/
scheduler 설정을 유지한다. 일반 native merge/cleanup/archive 문서는 A1 실행 권한이 아니다.

실행 인계는 workflow 새1회 → 새 Claude 독립 의미검토 승인 → full make check → scoped apply →
parent GitHub PR 및 필수 CI3 성공 별도 기록 → merge 전 정지다. parent는 run 전후 동일한
고정-cutoff metrics·scope/config/cron 불변을 비교한다. 실패 시 workflow/모델/검사 재실행 없이
기존 native bounded repair만 허용한다. 운영 배포·VM 이전은 없고 2026-11-10까지 배포 체계와
모델/예산/auth/storage/scheduler 설정을 유지한다. 작업자/검토자는 편집 외 검사·Git·네트워크·
운영 명령·workflow·재위임을 실행하지 않는다. 기존 사용자 편집과 미해결 제한을 parent에 인계한다.

각 리뷰에서 문서 영향을 재평가하고 최종 독립 Claude가 documentation={status,files,reason}을
새로 판단한다. Markdown 확장자 검사는 의미 완전성 증거가 아니다. protected private
`logs/harness/harness-runbook-core.json`은 모델 승인 범위에서 제외하고 열람·편집하지 않는다.
parent가 검토·검사 완료 후 “게시 단계는 이 명령만 사용, 즉석 스크립트 금지” 한 줄을 추가한다.

## 관련 코드·검증·문서

- [명령](../../harness/parent_commands.py), [park](../../harness/worktree_park.py), [Make](../../Makefile), [bridge](../../harness/git_bridge.js)
- [명령 회귀](../../harness/test_parent_commands.py), [park 회귀](../../harness/test_worktree_park.py), [bridge 회귀](../../harness/test_git_bridge.py): fake connector·격리 임시 Git 및 실제 subprocess 파일 stdin/READY 등 boundary 검증은 orchestrator 실행 책임이다. 이 문서는 검사 성공을 주장하지 않는다.
- [외부 merge 회귀](../../harness/test_external_merge.py): 자체 격리 fixture로 proof·순서·미전송 폐기·명시 재개·archive at-most-once·응답 snapshot을 검증한다. 실행은 orchestrator 책임이다.
- [설계](../harness-design.md#trusted-parent-전송과-native-검증-경계), [workflow](../workflow.md#trusted-parent-bridge와-즉시-handoff), [GitHub 전달 경계](../ops/github-transport.md)
