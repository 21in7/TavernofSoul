# GitHub 전달과 응답 연결

요약: parent가 fork 대상과 원래 요청을 유지하며 파일 기반 응답을 엄격하게 수락한다.

일반 운영 정본은 `logs/harness/harness-runbook-core.json`이다. 이번 A1에는 사용자 직접 승인한
네 명령·file accept·merge 전 stop 경계가 적용되며, 과거 runbook 지시로 PTY 입력이나 즉석
게시·복원을 허용하지 않는다. 이 요약은 게시 권한이나 복구 정책을 새로 부여하지 않는다.

사용자 직접 승인 A1은 [ADR0039](../adr/0039-standard-parent-git-commands.md)를 따른다. parent는
`agent-git-next`·`agent-git-accept-file`·`agent-worktree-park`·`storage-path` 네 상위 명령만 사용하며
즉석 게시·복원 script는 금지한다. Make와 Python3.8 표준라이브러리 CLI의 호출·capability 주입 예제는
[workflow](../workflow.md#trusted-parent-bridge와-즉시-handoff)에 둔다. runbook core는 protected
private logs여서 모델 승인 범위에서 제외하고 열람·편집하지 않는다. parent가 검토·검사 완료 후
“게시 단계는 이 명령만 사용, 즉석 스크립트 금지” 한 줄을 추가할 책임을 진다.

## 게시 대상과 소유권

PR compare 대상과 compare URL의 기준은 fork `21in7/TavernofSoul`이다. 원본 저장소로 보내지 않는다. 기존 게시 권한·필수 CI를 유지하며 모델은 게시·검사·Git 명령을 실행하지 않는다. credential은 사용자만 다룬다.

PR 설명도 자동 승인 검토 대상이다. PR #102의 설명 거절과 상한 구분은 [GitHub 복구](../lessons/github-recovery.md)를 따른다.

## 파일 기반 응답 framing

parent는 저장 전용 `writeResponseFile` capability로 원응답을 owned private 디렉터리의 exclusive
0600/nlink=1 JSON 파일에 보존하고 fsync/readback한 `{path,bytes,sha256}`을 받는다. capability는
transport·임시 Python launcher·ledger를 구현하지 않는다. `agent-git-accept-file`에 run ID·exact
request ID·response-file·예상 SHA256만 전달한다. 명령이 no-follow/owner/mode/nlink/size·UTF-8/JSON/
hash와 실행 중 파일/부모 교체를 검증한다. 입력 상한8MiB이며 원응답은 오류 때도 보존한다.

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
parent는 읽기 전용 capability로 제한된 bytes를 읽고 hash·UTF-8/JSON을 대조한다.

상위 명령은 성공·실패·인자 오류 모두 단일 `parent-commands-v1` JSON이다.
command/run/status/stage/code·executed/side_effects·native_exit_code·next_action을 보존하며
next_action의 허용 명령/필수 인자 또는 승인 필요/stop에 따른다. failed/needs_reconciliation/
awaiting_ci를 구별하고 bridge가 CLI 실패 단계를 그대로 전달한다. 정상 종료불명을 성공으로 세지 않는다.
종료 코드0이나 `approval_required=false`만으로 다음 작업을 시작하지 않는다. action별 필수 인자와
정확한 stop 처리는 [parent 결과 판독](../workflow.md#trusted-parent-bridge와-즉시-handoff)을 따른다.

## 다음 요청과 복구

`agent-git-next`는 run의 첫 요청에만 native request를 단1회 호출한다. 이후 accept-file 결과의
다음 요청을 그대로 이어 쓰며 next를 다시 호출하지 않는다. bridge는 next → allowlist connector
한 번 → private response 파일 → accept-file → 다음 요청 직접 사용으로 진행한다. 요청 인자는
eval하지 않으며 실제 GitHub connector는 trusted parent 앱만 호출한다. PR artifact 연결과 native
poll interval을 유지한다. child/discovery/unattended/read_only/demo/no_git에서는 거절한다.

기존 pending/inflight·최신 완료 receipt의 current journal hash/run/request identity를 대조한다.
stale ID·같은/다른 응답 중복·begin/complete/inflight·legacy/transport mismatch는 보수적으로 stop한다.
race의 최종 권위는 native claim이다. pending 재발급·새 ID·unknown dispatch 재전송·receipt 삭제/
재작성·자동 retry를 금지한다. 실제 ledger 값·요청 ID·응답 본문은 공개하지 않는다.

reconcile/resume-ci/external-merge/archive-verify는 A2 미구현이다. 필요하면 현재 승인된
[GitHub 복구](../lessons/github-recovery.md) 절차로 별도 조정하거나 stop한다. 옛 CLI나 즉석 script로
우회하지 않으며 native resume 뒤 journal/transport head mismatch를 head rewrite로 해결하지 않는다.

park는 승인 전체 scope/review/check/apply·HEAD baseline·index/status·hash+POSIX mode·native backup
before를 검증한 뒤 approved after snapshot과 file별 durable checkpoint를 보관하고 baseline 복원·
git status clean을 확인한다. unrelated tracked/staged/untracked·사용자 변경은 source mutation 전
거절하고 ignored 운영데이터를 보존한다. project/source → GitHub lock 순서와 기존 inode/mode를
유지하고 없는 lock도 안전한 no-follow 생성 경로로 처리한다. busy/다른 owner/symlink lock은 거절한다.
snapshot 충돌·중단은 stop, 이미 parked는 read-only 재확인이다. parked는 merge 후 완료가 아니다.
storage-path는 read-only resolve와 explicit prepare를 구분하고 생성 경로를 JSON에 기록한다.
v2 reports는 active artifacts 내부이며 private/absolute/no-follow/mount/floor·no fallback을 유지한다.
archive root 속성을 추측하지 않고 prepare 실패 시 전달·검사를 실행하지 않는다.

## 완료 증거

외부 읽기 조회, 응답 수락, 다음 요청 수신, CI, 머지는 서로 다른 증거다. PR이 보인다는 사실만으로 남은 단계가 완료됐다고 쓰지 않는다. 고정 비교의 불일치와 전송 실패는 [실패 보고](failure-reporting.md)에 따라 보고하며 parent는 workflow·모델·검사를 재시도하지 않는다.

A1 인계는 workflow 새1회 → 새 Claude 독립 의미검토 승인 → full make check → scoped apply →
parent GitHub PR/필수CI3 성공 별도 기록 → merge 전 정지다. 실패 시 parent는 workflow·모델·검사를
재실행하지 않고 기존 native bounded repair만 허용한다. run 전후 같은 고정-cutoff metrics·
scope/config/cron 불변을 비교한다. 운영 배포·VM 이전은 없고 2026-11-10까지 배포 체계와
모델/예산/auth/storage/scheduler 설정을 유지한다. worker/reviewer는 검사·Git·네트워크·운영 명령·
workflow·재위임을 실행하지 않는다. 매 리뷰의 문서 영향과 최종 독립 Claude의 새
`documentation={status,files,reason}` 판단은 필수이며 Markdown 검사가 의미 완전성을 증명하지 않는다.

[merge와 정리](merge-cleanup.md)의 후속 절차는 A1 실행 권한이 아니다. 공개 범위는
[공개 근거](../lessons/public-evidence.md), 기존 상세는 읽기 승인된 [workflow](../workflow.md)를 따른다.

[index로 돌아가기](../index.md)
