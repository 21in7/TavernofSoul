# 0023. 최초 branch push의 완전한 비교 근거와 문서 검증

현재 자동 검사 선택과 작업 branch push 실행은 [0031](0031-change-scoped-automatic-validation.md)이 부분 대체한다. 아래는 당시 결정·실패·검증 관측을 보존한 기록이다. docs 검사 계약과 완전한 event diff 수집 구현은 유지한다.

- 상태: 제안(proposed), 사용자 요청 방향 기록; 새 Claude 의미 검토·전체 make check·parent GitHub/CI/merge 검증 대기
- 기록일: 2026-10-20
- 부분 대체: [0022](0022-documentation-only-validation.md)의 새 브랜치 zero-before 무조건 full 결정만 대체한다.

## 문맥

사용자가 “새 브랜치 첫 push도 문서만 바뀐 게 확인되면 전체 테스트 대신 문서 검증만 돌도록
해줘”라고 요청했다. zero-before 자체는 이전 commit이 아니므로 별도의 완전한 비교 근거가
필요하다. 마지막 docs commit만 보면 같은 branch의 이전 코드 변경을 놓친다.

## 결정

[docs_check.py](../../harness/docs_check.py)는 push.before가 정확한 40자리 zero이고 created가
bool true, deleted가 bool false인 이벤트만 새 경로로 보낸다. ref는 유효한 refs/heads/...이고
repository.default_branch와 달라야 한다. forced가 존재하면 bool만 허용한다. 생성에는 이전
ref tip이 없으므로 GitHub 생성 이벤트의 forced true/false 모두 범위 증거로 사용하지 않는다.
tag·삭제·기본 branch 생성·잘못되거나 누락된 필수 metadata/type/ref/SHA는 full이다.

기존 [checkout](../../.github/workflows/harness.yml)의 actions/checkout@v6, fetch-depth:0,
candidate SHA, contents:read, persist-credentials:false를 유지한다. ref 이름은 check-ref-format으로
검증하고 Git subprocess argument list로만 전달한다. fetched `refs/remotes/origin/<default_branch>`를
정확히 조회하여 하나의 유효한 commit SHA로 고정한다. 고정 tip과 event.after의 `merge-base --all`이
유효한 유일 공통 조상을 반환할 때만 조상→after 전체 raw diff를 기존 git_changes/classify로 보낸다.
분기 후 기본 branch가 전진해도 branch 자체의 최종 변경만 비교하며 여러 commit의 변경을 포함한다.

event head와 HEAD가 같고 history/objects가 완전하며 tracked dirty/untracked가 없는 checkout이어야
한다. default ref 없음/모호함/invalid·조상 없음/복수·shallow/missing objects·head 불일치·빈 diff는
full이다. 기존 prose·정책·mode/type·rename 양쪽 분류를 유지하므로 이전 코드 변경 뒤 최신 docs
commit만 있는 branch도 full이다. docs 삭제/rename은 raw 기록과 현재 남은 역참조를 검증한다.

일반 push before→after와 PR base→head는 유지한다. 새 JSON schema/provenance 필드를 추가하지
않으며 확정된 전체 changes를 같은 selection JSON으로 docs 검증에 전달한다. docs 보고서는 이
selection과 같아야 한다. 세 실제 required gate는 positive selected/passed·zero skip/failure/error
및 selection 일치 또는 기존 full 실행 성공을 요구하며 docs 실패/증거 누락을 전파한다.
최초 push 자체를 workflow 조건으로 skip하지 않는다.

## 대안과 선택 이유

| 대안 | 판단 |
| --- | --- |
| zero-before는 항상 full | 안전하지만 완전한 branch 비교가 가능한 문서 변경도 불필요하게 무겁다 |
| HEAD^ 또는 event.commits 목록 | 마지막 commit·잘린 목록으로 이전 코드 변경을 놓칠 수 있어 거부 |
| empty tree 기준 또는 현재 default tip→head diff | branch 변경과 기본 branch의 이후 변경을 구별하지 못해 거부 |
| 추가 fetch/API로 과거 원격 상태 추정 | 새 네트워크/권한·재구성 불확실성을 추가하므로 거부 |
| fetched default 고정 + 유일 merge base + 전체 raw diff | 기존 classifier와 문서 검증/gate 계약을 재사용하므로 채택 |

## 근거와 한계

제공된 공식 근거는 [actions/checkout README](https://github.com/actions/checkout)의
fetch-depth:0이 모든 branch/tag history를 받는다는 설명과
[git merge-base](https://git-scm.com/docs/git-merge-base)의 --all이 모든 best common ancestor를
반환한다는 설명이다. worker는 네트워크로 조회하지 않았다. 기준은 실제 checkout이 fetched한
default tip이며 최초 push 시점의 원격 상태를 재구성하지 않는다. 그 상태와의 의미 차이나
복수 조상은 추측으로 해소하지 않는다. 불명 근거는 full이며 docs 오류를 full 성공으로 덮지 않는다.

모델·역할·인증, 기존 workflow/review/full 검증·Git 게시/세 required CI/merge/cleanup,
local active storage·terminal archive 정책은 유지한다. prose 분류는 기계적 경로 선택이며
문서 의미의 완전성은 fresh Claude 검토가 판단한다.

## 회귀 명세와 실제 실행 증거

[test_docs_check.py](../../harness/test_docs_check.py)에 Python 3.8 stdlib 기반 작은 실제 임시
Git fixture를 작성했다. single/multi commit docs, 기본 branch 전진/다른 이름, 이전 코드+최신 docs,
정책/CI/권한/type/비문서 rename, 삭제/rename raw 기록·역참조, metadata/ref/SHA 경계와
default 누락·불완전 history/checkout·조상 없음/복수를 다룬다. 기존 push/PR 범위와 selection/report
equality 및 세 required gate 계약 회귀도 유지한다. 이 목록은 작성된 회귀이며 통과 관측이 아니다.

이번 실제 변경은 harness/CI 선택·정책 변경으로 docs-only 대상이 아니다. worker는 검사·Git 명령·
네트워크·게시를 실행하지 않았다. parent가 새 Claude 의미 검토, 전체 make check,
실제 GitHub/세 required CI·merge·cleanup 증거를 확보해야 한다. 과거 run/timeout/초안은 이번
구현의 성공 증거로 바꾸지 않는다. 절차는 [workflow](../workflow.md), 책임은
[harness-design](../harness-design.md), 사용법은 [harness](../harness.md)에 둔다.
