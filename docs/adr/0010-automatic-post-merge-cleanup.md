# 0010. 머지 후 자동 Git 정리와 전체 완료 게이트

- 상태: 승인(accepted), 새 구현 결정; 실행 성공의 증거는 아님
- 기록일: 2026-10-12
- 대체 관계: [0009](0009-post-merge-branch-cleanup.md)의 별도 수작업 정리·완료 경계를 대체한다.
  [0005](0005-github-connector-delivery.md)의 앱 게시·CI·SHA 고정 squash merge 원칙은 유지한다.

## 문맥

머지 응답 직후 passed로 종료하면 원격·로컬 작업 브랜치와 master 동기화가 빠질 수 있다.
GitHub 앱에는 브랜치 삭제 도구가 없으며 앱 게시 후 로컬에는 승인된 파일 변경만 미커밋으로
남을 수도 있다. squash head의 조상 관계만으로 로컬 삭제를 판정할 수 없고, 사용자 편집이나
운영/ignored 데이터를 generic checkout/reset/clean으로 처리하면 손실 위험이 있다.

이미 인증된 parent Git 전송을 사용하되 새 credential을 수집하지 않는다. 구현 중 프로세스가
중단돼도 영구적인 merge 성공과 불완전 cleanup을 분리하고 실제 상태로 재개해야 한다.
Git 2.25의 worktree porcelain과 초기화 옵션도 지원한다.

## 결정

### 자동 연결과 완료 계약

merge accept가 merged/SHA를 durable github.json에 먼저 보존하고 기존 fetch 도구의 새 cleanup
proof 요청을 반환한다. 메인은 게시와 같은 journal loop로 읽기 요청을 이어 실행한다. 마지막 proof
accept가 git_cleanup을 자동 실행한다. 별도 cleanup 명령의 수동 호출을 정상 흐름에 요구하지 않는다.
게시·PR·merge는 기존 앱 journal만 사용하며 TOOLS에 새 쓰기 도구를 추가하지 않는다.

proof는 PR 번호·closed/merged·repository·base.ref·고정 head.ref/SHA·확정 merge SHA, 원래 pinned
head/test merge의 세 required CI success 및 statuses, 새 repository 조회의 default_branch,
정확한 branch tip/보호 여부·같은 head의 열린
PR 부재를 확인한다. 머지 후 base.sha 전진은 허용한다. 전체 branch 또는 정확한 open-head query의
REST 배열 페이지를 끝까지 확인하며 coverage 없는 wrapper, 빈 object, 중복·페이지 한도·읽기 실패는
fail closed다. 확정 merge SHA와 테스트 merge SHA를 혼동하지 않는다.

원격/로컬 deleted 또는 absent, tracking prune·base sync·마지막 completion 확인이 모두 끝나야
cleanup-v1 status=complete와 report.status=passed다. merge_status=merged와 merge_sha는 실패해도
보존한다. cleanup 실행 진입의 report/approval 읽기 실패도 cleanup_pending으로 처리한다.
proof 대기는 awaiting_github/cleanup_*이며 실패·보류·부분 정리는 대상별 사유가 있는
cleanup_pending/non-success다. READ_ONLY/demo/GIT=0/child/게시 비활성/변경 없음은 side effect를 차단한다.

### 신뢰한 parent의 인증 Git과 비교 삭제

대상은 원래 요청의 codex/<run_id> ref 하나다. 기본/base/master/main/dev·protected·열린 PR·미머지·
다른 worktree 점유·tip 전진 브랜치를 보존한다. raw origin URL/pushurl과 Git rewrite 이후 effective
fetch/push URL 모두 승인 repository의 credential-free 단일 대상으로 일치해야 한다. 새 계정/token,
credential 파일 읽기·수집·fallback이나 자동 권한 확대는 없다.

submodule recursion을 명시적으로 끈 fetch로 확정 merge가 origin/base 이력에 포함되는지 확인한다.
원격 삭제는 정확한 refs/heads/<branch>와 expected head SHA의 explicit force-with-lease를 붙인
빈 source refspec만 사용한다. 이는 compare-and-delete 조건이며 원격 값이 바뀌면 실패한다.
내용/이력 강제 push, --force, --no-verify, 보호 우회, 다른 ref push는 허용하지 않는다.
근거: [Git push의 explicit refname:expect 문서](https://git-scm.com/docs/git-push).

삭제 직전에 시도 identity를 checkpoint에 보존하고 응답·실패·timeout 뒤 실제 ref를 조회한다.
resume은 먼저 부재/동일 SHA/변경 SHA로 이전 결과를 재조정한다. 모호한 시도 뒤 동일 SHA가
남으면 자동 재전송하지 않는다. 안전하게 부재가 확인돼야 prune과 정확한 tracking ref 부재로 진행한다.
첫 fetch를 포함해 모든 fetch와 prune 전에 origin heads → origin tracking의 표준 fetch mapping을
검증한다. 명시적 fetch refspec도 configured refmap의 추가 목적지를 갱신할 수 있으므로 다른 mapping은
전송·삭제 전에 prune.reason=unsafe_prune_refspec의 cleanup_pending으로 보류한다.

### 로컬 승인 변경과 복구

모든 worktree의 operation·점유·dirty 상태, staged/untracked·local-only commit·base ancestry·checkout을
검사한다. worktree list --porcelain은 Git 2.25에서도 지원된다. C-quoted 경로는 바이트로 해석하며
불명확·locked/prunable 상태는 보류한다. 다른 worktree 조회는 GIT_OPTIONAL_LOCKS=0으로 읽기만 한다.
ignored 파일/디렉터리·symlink 부모·보호/운영 경로와 target tree의 collision은 보존하고 보류한다.

clean 승인 checkout은 base 전환 → fetch/prune → ff-only → 작업 ref 삭제로 진행한다. 일반 merge와
squash 모두 PR proof·merge 이력·동일 tip·추가 commit 없음·모든 worktree 미사용을 재확인하고
update-ref -d <정확한 ref> <expected SHA>로 삭제한다. branch -d 뒤 무조건 -D하는 방식보다 tip 경쟁을
원자적으로 검사한다. reset --hard/clean/전체 add/자동 stash는 사용하지 않는다.

앱이 반영한 변경만 미커밋으로 남으면 github-approved.json의 before/after full POSIX fingerprint,
현재 bytes·존재·권한·index, baseline과 local HEAD 관계, merge/fetched base의 blob 및 Git mode를
파일별로 대조한다. Git 100644/100755는 POSIX mode 전체가 아니라 executable 비트로 비교한다.
edit/add/delete/executable 변경이 승인된 결과 그대로이고 다른 변경이 없을 때만 private durable
승인 snapshot과 prepared checkpoint를 만든 뒤 개별 파일의 baseline을 일시 복원한다.
baseline/syncing/synced phase를 남기고 ff-only로 동기화한다.

중단 시 복구 snapshot을 지우거나 알 수 없는 사용자 편집을 덮어쓰지 않는다. resume은 snapshot hash와
현재 승인 after/이미 복원된 before 또는 ff-only 후 실제 HEAD/tree를 확인해 남은 단계를 이어간다.
동기화 전 baseline 복원 재개는 새 fetched base의 승인 파일 blob/mode를 다시 대조하고 불일치 시 보류한다.
권한 실패·snapshot 손상·사용자 편집은 cleanup_pending이며 parent가 충돌을 해결할 때까지 보존한다.
clean하게 이미 동기화됐고 최신 base에 해당 merge가 포함되면 idempotent 완료할 수 있다.

프로젝트/workflow lock → GitHub journal lock 순서로 apply/cleanup을 직렬화한다. github.json,
cleanup.json과 승인 snapshot은 private fsync/atomic replace로 보존한다(디렉터리 0700, 파일 0600).
Git은 shell=False 인자 배열·검증된 ref/path·60초 timeout·비대화 인증을 사용한다. stdout/stderr와
credential은 공개 오류·모델 피드백에 넣지 않고 고정 이유 코드만 반환한다. 외부 편집 경쟁은 각 위험
단계와 완료 직전에 재확인하지만 파일 전체나 저장소 전체의 원자 트랜잭션을 주장하지 않는다.

### 호환과 명시적 재개

github-v1 설정과 journal을 유지하고 cleanup-v1 필드를 확장한다. 변경 전 모듈로 prepare된 journal도
새 CLI에서 정상 게시 후 cleanup을 이어간다. 이미 merged/done/passed인 이전 run은 request/resume/cleanup의
명시적 경계에서 fresh proof부터 이행한다. 이전 passed를 cleanup 완료로 신뢰하거나 재merge하지 않는다.
status는 historical report를 덮어쓰지 않고 legacy_cleanup_required를 표시한다.

agent-git-resume은 awaiting_ci와 merged cleanup을 구분한다. cleanup 재개는 새 모델/commit/branch/PR/merge
없이 PR/ref/로컬 상태만 재확인한다. agent-git-cleanup은 이미 merged된 run의 명시적 보조 명령이다.
기존 승인 snapshot·journal identity 검사는 계속 필요하며 missing/불명확 상태를 자동 추정하지 않는다.

## 비교 대안

| 대안 | 효과·비용 | 판단 |
| --- | --- | --- |
| merge만 passed, 메인의 별도 정리 | 잔여 branch와 sync가 누락되고 재개 근거가 분산된다. | 0009의 완료 경계를 대체 |
| GitHub 자동 삭제 설정만 활성화 | local/tracking/sync·추가 commit·승인 변경을 처리하지 못한다. | 부재 확인으로 수용하되 단독 해결책으로 쓰지 않음 |
| 앱에 없는 삭제 tool 또는 새 credential | 지원 경계와 인증 책임을 늘린다. | 사용하지 않음 |
| 승인 파일을 reset/clean/stash 또는 전체 commit | 간단하지만 사용자·ignored 데이터나 index를 함께 변경할 수 있다. | 금지 |
| exact lease 삭제 + durable 파일별 복원 + ff-only | Git transport와 복구 상태가 복잡해지고 조회 비용이 늘지만 경쟁·부분 완료를 명시할 수 있다. | 채택 |
| dev 통합 또는 prefix 일괄 삭제 | 추가 통합 책임이 생기거나 작업 중 브랜치를 손실하며 정리 문제를 해결하지 못한다. | 도입하지 않음 |

## 선택 이유

머지 성공을 영구 기록하고 cleanup을 별도 완료 게이트로 연결하면 불완전 정리를 CI/merge 성공으로
덮을 수 없다. exact expected SHA의 비교 삭제는 추가 commit을 보존한다. 앱 게시와 parent Git cleanup의
권한 분리는 모델과 credential을 분리한 기존 원칙을 유지한다. 승인 snapshot·파일별 재조정은 정상적인
미커밋 앱 반영 경로를 지원하면서 다른 사용자 변경을 강제로 제거하지 않는다.

## 결과·비용·제약

fresh GitHub proof·여러 Git 조회·durable checkpoint 비용과 실패 상태가 늘어난다. 표준 prune mapping,
worktree 경로 또는 보호/운영 tree가 불명확하면 안전하게 보류한다. 모호한 원격 삭제의 동일 SHA 잔존은
자동 retry하지 않으므로 parent의 외부 결과 확인이 필요할 수 있다. 저장 공간 관리는 승인 snapshot과
복구 기록이 더 이상 필요 없는지 확인한 운영자가 맡는다. 이 흐름은 게임 데이터·cron·DB·다운로드·
importAll을 실행하거나 submodule/unpack을 정리하지 않는다.

## 관련 코드·검증·문서

- [git_publish.py](../../harness/git_publish.py), [git_cleanup.py](../../harness/git_cleanup.py),
  [workflow.py](../../harness/workflow.py), [Makefile](../../Makefile): 자동 연결·상태·재개 명령.
- [게시 정책](../../harness/git-publish-config.json): 기존 repository/base/squash/세 CI 유지.
- [test_git_cleanup.py](../../harness/test_git_cleanup.py): 임시 실제 Git/bare origin의 삭제·prune·ff-only,
  승인 변경·squash·재개·tip 경쟁·충돌·복구·권한 실패·완료 게이트.
- [test_git_publish.py](../../harness/test_git_publish.py), [test_workflow.py](../../harness/test_workflow.py):
  publication/CI/SHA/write 게이트·fresh proof·non-passed·legacy 이행·child/생략 경계.
- [AGENTS](../../AGENTS.md), [설계](../harness-design.md), [workflow](../workflow.md),
  [검증](../harness.md), [architecture](../architecture.md): 책임과 실행 경계.

real Git tests의 GitHub proof만 합성이며 file transport는 Python test seam으로 주입한다. 생산 URL 정책은
완화하지 않는다. fixture는 host config/identity/auth/hooks/template·운영 저장소·외부망과 격리한다.
worker는 회귀를 작성만 하고 새 Claude 의미 검토·full make check·충돌 검사/반영·실제 PR/세 CI/merge와
이번 run의 cleanup complete/clean master 확인은 orchestrator가 수행한다. 이 문서는 실행 성공을 주장하지 않는다.
