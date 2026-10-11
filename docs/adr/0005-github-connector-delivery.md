# 0005. 메인 GitHub 앱 journal과 3개 required CI 뒤 SHA 고정 merge

- 상태: 승인(accepted) — 관측된 구현 결정으로 기록한다는 의미
- 기록일: 2026-10-11
- 기록 성격: 현 구현에서 복원. 과거 도입 의도·검토·날짜는 추정하지 않는다.
- 대체 관계: 없음

## 문맥

로컬 승인·검증된 변경을 GitHub에 게시할 때 기존 사용자 index/staged 변경과 원격 기준을 보존해야 한다.
모델에 게시 자격증명·명령 결정을 맡기거나 모호한 쓰기를 재시도하면 범위 밖 커밋·중복 PR·
검증하지 않은 SHA의 merge가 발생할 수 있다.

## 결정

git 역할은 읽기 전용으로 commit_message/pr_title/pr_body만 반환한다. 메인 Codex의 인증된
GitHub 앱이 허용 도구·인자로 실제 쓰기를 수행하고 실행기가 request_id·응답·private journal을 검사한다.
현재 대상은 21in7/TavernofSoul, master, squash다. 로컬 Git index/refs를 변경하지 않고 원격
기준 tree와 시작 파일 blob SHA/권한이 같아야 승인 변경만 tree·commit·branch·PR로 만든다.
github-approved.json의 고정 hash/권한/정책과 github.json을 매 요청 대조한다.
이미 발급한 쓰기의 결과가 모호하면 needs_reconciliation으로 중단하고 자동 재발급하지 않는다.

github-actions의 `Offline harness (SQLite)`, `MySQL harness`, `Chromium browser harness` 세
required check가 실제 success여야 한다. check-runs 페이지·최신 ID·head/test merge SHA와
commit statuses를 확인한다. test merge 검사 존재 시 그 결과, 없으면 head 검사를 판단한다.
최종 PR의 base/head·test merge SHA·clean 상태를 다시 확인하고 expected_head_sha로 merge한다.
앱이 merged=true와 merge SHA를 확인해 준 뒤 완료다. 30분 제한은 기존 PR의 awaiting_ci/resume로 다룬다.

## 비교 대안

이번 기록 시점의 평가이며 과거 고려 목록을 주장하지 않는다.

| 대안 | 평가 |
| --- | --- |
| 모델이 gh/token/Git 명령으로 게시 | 빠르지만 자격증명·index·파일 범위·모호한 쓰기 통제가 어려워진다. |
| 로컬 커밋만 완료로 보고 | 원격 CI·머지 결과를 요청의 완료 조건과 연결하지 못한다. |
| CI 이름/PR 상태만 확인해 merge | 다른 앱·stale SHA·누락/skip·불완전 페이지를 성공으로 잘못 판단할 수 있다. |
| 메인 앱·journal·3개 CI·고정 SHA | 통제와 복구 상태를 기록하지만 메인 앱 권한·응답 검증·대기 관리가 필요하다. |

## 선택 이유

현 구조는 모델 설명과 게시 권한을 분리하고 검토/검사한 파일·원격 기준·실제 머지 SHA를 연결한다.
커넥터 결과가 불확실한 쓰기를 성공이나 자동 재시도로 처리하지 않는 방식이 상태 추적에 적합하다.

## 결과·비용·제약

CLI 단독 실행은 앱이 없어 awaiting_github에서 대기한다. CI 실패·누락·skip/neutral·취소·충돌·
권한/보호 규칙은 PR을 남기고 merge하지 않는다. 보호 설정의 required 등록은 관리자 책임이며
YAML만으로 설정되지 않는다. force·관리자 우회·보호 설정 변경·배포는 제공하지 않는다.
원격 기준과 기존 미게시 수정이 다르면 별도 승인 게시 범위가 필요하다.
read_only·demo·GIT=0·변경 없음·게시 비활성은 GitHub 흐름을 생략한다.

## 관련 코드·검증·문서

- [git_publish.py](../../harness/git_publish.py): prepare/request/accept/checks_gate/validate_journal.
- [게시 정책](../../harness/git-publish-config.json), [workflow.py](../../harness/workflow.py).
- [CI](../../.github/workflows/harness.yml): 세 작업과 오프라인 check-live 포함.
- [test_workflow.py](../../harness/test_workflow.py): 메인 handoff·git 읽기 전용·마지막 성공 라운드·게시 생략 회귀.
- [workflow의 게시 절차](../workflow.md#github에-자동-반영), [전체 설계](../harness-design.md#충돌-검사반영과-github-게시).

링크는 정책과 검증 경로다. 이 기록은 실제 PR·CI success·merge SHA를 새로 확인한 결과가 아니다.
