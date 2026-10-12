# 0009. Squash PR 머지 후 작업 브랜치 정리

- 상태: 대체됨(superseded) — [ADR 0010](0010-automatic-post-merge-cleanup.md)
- 기록일: 2026-10-12
- 기록 성격: 이번 사용자 요청에 따른 새 정책 결정; 정리 실행 성공 기록이 아님
- 대체 관계: [ADR 0010](0010-automatic-post-merge-cleanup.md)이 자동 정리와 전체 완료 게이트를 추가한다. 아래 본문은 당시 정책 기록으로 보존한다.

## 문맥

`codex/<run_id>` 작업 브랜치가 PR 머지 뒤에도 쌓이는 문제를 해결한다. 사용자는 머지 후
원격·로컬 작업 브랜치를 정리하는 규칙을 요청했고, `dev`로 먼저 통합한 뒤 `master`로
넘기는 대안도 제시했다. 별도의 릴리스 통합 요구는 없으므로 이번에는 `dev`를 도입하지 않는다.

[게시 설정](../../harness/git-publish-config.json)의 대상은 `21in7/TavernofSoul`, base는
`master`, merge 방식은 `squash`다. [게시 코드](../../harness/git_publish.py)는 GitHub 앱의
게시·merge 응답을 journal로 검증하지만 브랜치 삭제를 구현하지 않는다. 앱이 원격 커밋을
만들므로 로컬에 같은 작업 브랜치나 커밋이 없을 수 있고, 게시된 파일 변경만 미커밋으로
남을 수도 있다. 원격 머지와 로컬 상태를 같다고 가정하면 사용자 편집을 잃을 수 있다.

2026-10-12 메인 `/root`가 제공한 초기 관측은 clean `master` 작업 트리와 로컬 브랜치
`master`만 존재한다는 것이다. GitHub repository 응답은 `delete_branch_on_merge=false`였고,
당시 GitHub 앱에는 브랜치 삭제·저장소 설정 수정 도구가 없었다. 메인이 `make doctor` 통과를
확인한 사실도 정리 성공의 증거는 아니다. 이 관측은 자동 삭제 활성화, 원격 ref 부재,
누적 브랜치 정리 완료 또는 이번 변경의 check·CI 성공을 뜻하지 않는다. 실행 시 상태를 새로 확인한다.

## 결정

### 책임과 완료 경계

기존 `codex/<run_id>` → `master` squash PR을 유지한다. 매 쓰기 작업의 게시·CI·머지 뒤
메인 `/root`가 해당 작업의 원격 브랜치, 동일한 로컬 브랜치, 사라진 원격의 추적 ref를
정리한다. 작업자·검토자가 정리를 실행하거나 재위임하지 않는다. 이번 사용자 요청으로
확인된 기존 누적 작업 브랜치도 PR별로 동일한 증거와 안전 조건을 충족하면 정리할 수 있다.
브랜치 prefix는 후보를 식별하는 보조 정보일 뿐 삭제 승인이나 일괄 삭제 근거가 아니다.

정리 게이트는 GitHub Actions의 `Offline harness (SQLite)`, `MySQL harness`,
`Chromium browser harness` 세 CI의 실제 `success`, GitHub `merged=true`와 유효한
merge SHA 확인이다. 기존 journal의 SHA·앱·최신 검사·coverage·commit status 확인을 유지한다.
추가로 origin이 해당 저장소인지 확인하고 `origin/master`를 fetch하여 **확정된 merge SHA가
그 이력에 포함되는지** 확인해야 한다. 테스트 merge SHA를 확정 merge SHA로 대체해 쓰지 않는다.
증거 누락·불일치·fetch 실패·이력 미포함이면 관련 삭제를 보류하고 이유를 기록한다.

`READ_ONLY`, demo, `GIT=0` 작업에서는 원격 게시·삭제 또는 로컬 refs 정리를 자동 실행하지 않는다.
저장소 보호 설정 변경, 강제 push, 자격증명 수집은 정리 수단으로 허용하지 않는다.

### 삭제 대상별 증거와 보존 조건

원격·로컬 삭제 대상 각각에 대해 다음을 확인하고 별도 private 정리 기록에 남긴다.

1. repository, origin, base(`master`), head의 저장소·정확한 브랜치명, PR 번호·URL의 관계가
   해당 작업과 일치해야 한다. 열린 PR이나 다른 진행 중 작업이 그 브랜치를 사용하는지도 확인한다.
2. 해당 PR의 `merged=true`, 확정 merge SHA와 **머지 당시 PR head SHA**를 확인한다.
   누적 브랜치도 PR별 CI 성공과 merge SHA의 fetch한 `origin/master` 이력 포함을 확인한다.
3. 삭제 직전 존재하는 원격 ref와 로컬 ref의 tip을 각각 머지 당시 PR head SHA와 비교한다.
   원격 ref 부재는 부재로, 로컬 브랜치 부재는 없음으로 기록한다. 한쪽의 부재나 일치가
   다른 쪽의 안전을 증명하지 않는다. PR 증거 또는 tip이 불명확하면 해당 대상을 보존한다.
4. 현재 tip이 다르거나 이후 커밋·로컬 전용 커밋이 있으면 해당 브랜치를 보존하고 이유를 보고한다.
   삭제 직전 재조회에서 tip이 바뀌어도 보류한다. 다른 쪽은 독립적으로 안전 조건을 판단한다.

기본 `master`/`main`, 이미 존재하는 `dev`, 보호 브랜치, 작업 중·미머지 PR 브랜치,
다른 worktree에서 사용하는 브랜치는 보존한다. 이름이 `codex/`로 시작해도 예외가 아니다.
`codex/*` prefix 일괄 삭제는 금지한다. squash merge는 원래 head 커밋의 조상 관계를
보존하지 않으므로 `git branch --merged` 결과만으로 삭제를 판단하지 않는다.
GitHub PR 머지 증거와 정확한 tip 동일성이 삭제 근거다.

### 원격 정리

원격 자동 삭제가 실제 활성화됐다고 가정하지 않고 정확한 원격 ref를 조회한다.
이미 없으면 `이미 없음`으로 기록한다. ref가 남았으면 위 조건을 충족한 정확한 브랜치만
기존에 인증된 지원 도구로 삭제하고, 원격을 다시 조회하여 부재를 확인한다.
삭제 응답만으로 성공 처리하지 않는다. 도구·권한이 없거나 응답이 모호하거나 ref가 남으면
`cleanup_pending`과 대상·구체적 사유를 보고한다. 불명확한 쓰기를 무조건 반복하지 않는다.

GitHub 앱의 게시·merge journal은 계속 사용한다. 현재 앱 journal에는 브랜치 삭제가
구현돼 있지 않으며, 이 문서 변경으로 도구가 추가되거나 자동 삭제 설정이 켜지지 않는다.
저장소 설정을 바꿔 정리를 우회하지 않는다.

### 로컬 상태 보존과 동기화

로컬 변경·staged·untracked 파일, 로컬 전용 커밋, 모든 worktree의 사용 상태를 먼저 확인한다.
앱 게시 방식 때문에 로컬 변경이 미커밋으로 남을 수 있으므로 무조건 checkout/reset/clean/stash
하지 않는다. 다른 사용자 변경·로컬 전용 커밋·충돌·불명확한 상태는 모두 보존하고,
영향받는 로컬 정리·기준 브랜치 동기화를 보류한다. 안전한 원격 정리 여부는 별도로 보고한다.

일반적인 깨끗한 작업 트리에서 기준 이력과 worktree 사용이 안전하면 `master`로 전환하고
`git fetch --prune origin`, `git pull --ff-only origin master`로 동기화한다.
삭제 뒤 사라진 원격 추적 ref의 prune 결과도 확인한다. 원격 ref가 아직 남아 있다면
prune이 그 브랜치 삭제를 대신하지 않는다. fast-forward가 불가능하면 강제 동기화하지 않는다.

게시된 변경만 로컬에 남았을 때는 승인·검증된 manifest, 확정 머지 결과의 파일 상태,
현재 파일 bytes·권한이 일치하는지를 파일별로 확인한 뒤 **그 파일만** 동기화할 수 있다.
추가·삭제 파일도 해당 manifest와 실제 존재 여부를 대조하고 staged·untracked 상태를 확인한다.
manifest 밖 파일이나 사용자 변경은 포함하지 않는다. 머지 결과와 게시 내용이 다르거나
같은 파일의 다른 편집·index 상태를 구분할 수 없으면 보존하고 보류한다.

로컬 작업 브랜치가 없으면 `없음`으로 기록한다. 존재하면 tip·추가 커밋·PR 증거·worktree
미사용을 확인하고, 자신이 해당 브랜치에 있다면 안전하게 `master`로 전환한 뒤
`git branch -d <정확한 작업 브랜치>`를 우선한다. squash 이력 때문에 `-d`가 거부될 때만
PR `merged=true`, merge SHA와 `origin/master` 이력 포함, 머지 당시 head와 로컬 tip 동일성,
추가 커밋 없음, 모든 worktree에서 미사용을 다시 확인하고 그 정확한 브랜치에 한해
`git branch -D`를 허용한다. 다른 거부 사유에는 적용하지 않으며 blanket `-D`는 금지한다.

### 결과 기록

머지 결과와 정리 결과를 분리한다. 메인 최종 결과에는 PR URL, merge SHA, 원격 삭제/이미 없음,
로컬 삭제/없음, prune 결과, 기준 브랜치 동기화 결과와 대상별 보류 이유를 보고한다.
미확인·실패·보류는 삭제/없음으로 표현하지 않는다. `cleanup_pending`이면 머지는 완료됐더라도
정리까지 전체 완료했다고 주장하지 않는다. 누적 브랜치도 PR별 결과를 남긴다.

현재 `harness/git_publish.py`는 merged 확인 시 `report.status=passed`로 바꾸며 cleanup은
구현하지 않는다. 그 값은 기존 게시·머지 게이트의 결과이고 새 정리 게이트 통과를 증명하지 않는다.
이번 변경에서는 JSON 상태 schema나 실행기 동작을 바꾸지 않는다. 정리 근거·결과·보류 사유는
별도 private cleanup 기록과 메인 최종 결과로 보완한다. public ADR에는 private 작업·로그·응답
원문을 복사하지 않는다.

## 비교 대안

| 대안 | 효과와 비용 | 판단 |
| --- | --- | --- |
| 작업별 `codex/<run_id>` → `master` squash PR 후 증거 기반 정리 | 기존 PR·CI 경계를 유지하며 원격·로컬 잔여 브랜치를 직접 처리한다. 메인의 대상별 확인과 보류 보고가 필요하다. | 채택 |
| `dev`에 작업 PR 통합 후 `master`로 별도 PR | 릴리스 묶음이 필요하면 통합 지점이 될 수 있지만 작업 브랜치 정리는 여전히 필요하다. 추가 PR·CI·통합/충돌·릴리스 책임이 생긴다. | 별도 릴리스 통합 요구가 없는 이번에는 도입하지 않음 |
| 원격 자동 삭제 설정만 사용 | 활성화와 실제 ref 부재 확인이 필요하고 로컬 브랜치·추적 ref·추가 커밋 문제를 해결하지 못한다. 현재 초기 관측도 비활성이다. | 단독 해결책으로 사용하지 않음 |
| prefix 일괄 삭제 또는 `git branch --merged`만 사용 | 진행 중 작업·추가 커밋을 지울 수 있고 squash PR 머지 사실을 정확히 판정하지 못한다. | 금지 |

## 선택 이유

문제는 머지 대상 브랜치의 부족이 아니라 완료된 작업 브랜치의 정리 책임과 증거가 없다는 것이다.
작업별 메인 정리는 기존 검토·CI·merge 경계를 유지하면서 그 문제를 직접 해결한다.
`dev` 추가는 정리 의무를 없애지 않으며 요구되지 않은 릴리스 통합 책임을 늘린다.
PR 머지 증거와 exact tip 비교는 squash의 이력 차이와 머지 이후 추가 작업을 구분하고,
로컬 manifest 대조와 보류 규칙은 앱 게시 이후에도 사용자 편집을 보존한다.

## 결과·비용·제약

매 작업과 누적 PR마다 원격 조회·fetch·tip·worktree·로컬 파일 상태를 확인하는 비용이 추가된다.
지원 도구·권한 부족과 증거 불확실성은 `cleanup_pending`으로 남을 수 있다. 부분 정리 결과를
독립적으로 기록하고 재개 때 현재 상태를 다시 확인한다. 이미 없는 대상은 없음으로 처리하며
남은 대상에 같은 안전 조건을 적용한다. 브랜치 삭제 정책만으로 동시 편집 경쟁이 사라지지는 않는다.

이 ADR은 정책 결정이며 삭제 실행이나 실행기 구현 완료를 증명하지 않는다. 연계 책임·완료 경계는
`AGENTS.md`, `docs/workflow.md`, `docs/harness-design.md`에도 일관되게 반영해야 한다.
검사·CI는 실행기가 담당하고, 문서 의미 검토는 실제 변경 Markdown을 `documentation.updated`에
포함하여 기존 동작·새 정리 책임·완료 보고의 일관성을 판단한다.

## 관련 코드·검증·문서

- [GitHub 게시 설정](../../harness/git-publish-config.json): repository/base/squash와 세 required CI.
- [GitHub 게시 코드](../../harness/git_publish.py): 앱 허용 도구, journal, merged → passed 경계; cleanup 미구현.
- [작업 지침](../../AGENTS.md), [workflow](../workflow.md), [하네스 설계](../harness-design.md): 연계 책임·완료 경계.
- [ADR 목록](README.md): 결정 등록과 문서 검토 규칙.

검증 명세와 초기 관측은 실제 정리·검사·CI 실행 성공과 구분하며, 실행 결과는 별도 증거로 확인한다.
