# 0006. Git 관리 설계·ADR와 매 검토의 문서 판단

- 상태: 승인(accepted) — 이번 요청에 따른 설계·구현 결정이며 검사 통과를 뜻하지 않음
- 기록일: 2026-10-11
- 기록 성격: 이번 요청의 새 결정. 0001~0005와 달리 과거 구현 복원 기록이 아니다.
- 대체 관계: 없음

## 문맥

architecture·harness·workflow는 현재 구조와 사용법을 설명하지만 전용 전체 설계서와 주요 선택의
기록이 없었다. 계획 schema는 role/task/files 배정만 검사하며 모델 계획·응답은 Git 제외 private
logs에 남는다. 기존 reviewer verdict/summary/findings만으로는 문서 영향을 매번 판단했는지 확인할 수 없다.

## 결정

한국어 docs/harness-design.md와 docs/adr/의 목록·개별 결정 기록을 Git 관리한다.
업무 시작과 매 검토에서 문서 영향을 판단한다. 구조·책임·데이터 계약·격리·검증·복구·GitHub 게시
정책 변경은 관련 설계·경계 문서를 갱신하고 주요 선택에 신규/대체 ADR를 작성한다.
오타·동작 불변 국소 수정의 문서 생략은 구체적 이유로 기록할 수 있다.
planner·worker·reviewer 지침에 이 기준을 연결하고 직접 Jev 배정도 worker·reviewer 지침을 받는다.
필요 문서가 scope 밖이면 자동 열람·복사·생성하지 않는다. missing 경로를 보고하고 기존 승인 파일
finding으로 승인을 거부한다. 메인이 범위를 확인·승인한 새 실행을 준비하며 repair가 scope를 넓히지 않는다.

reviewer 최상위 JSON은 정확히 verdict/summary/findings/documentation이다. 기존 verdict/summary/findings
게이트를 유지하고 documentation을 필수로 한다. documentation은 정확히 status/files/reason,
status는 updated/not_required/missing, reason은 공백 제외 비어 있지 않은 문자열,
files는 중복 없는 승인 범위 `.md` 경로 목록이다.

| status | 조건 |
| --- | --- |
| updated | 실제 변경 `.md` 최소 하나를 요구하고 scope 밖·비문서·미변경 참조를 거부한다. 다른 finding이 있으면 changes_requested다. |
| not_required | files=[]와 문서 갱신이 불필요한 구체적 이유를 요구한다. 코드 finding과 함께 쓸 수 있다. |
| missing | changes_requested와 기존 승인 파일에 귀속 가능한 비어 있지 않은 findings를 요구한다. approved를 금지한다. files는 빈 목록 또는 승인 `.md` 경로다. |

필드 누락·잘못된 schema·verdict 모순은 fail closed다. 판단은 review.documentation과 private
모델 응답에 보존한다. 의미적 문서 영향·완전성·생략 이유의 적절성은 reviewer가 판단한다.
확장자·변경 목록 검사로 완전성을 주장하지 않는다. read_only·demo도 같은 판단을 반환하되
원본 변경·외부 호출을 추가하지 않는다. 문서 finding은 기존 정확한 task·max_rounds·새 검토/필수 검사를 따른다.

## 비교 대안

이번 요청 시점의 평가다.

| 대안 | 평가 |
| --- | --- |
| private 모델 계획/응답만 보관 | 실행 조사는 가능하지만 Git에서 장기 설계·결정 이유를 검토하기 어렵다. |
| 문서 갱신을 prompt 권고만으로 처리 | 간단하지만 필수 판단 누락과 문서 증거 모순을 구조적으로 차단하지 못한다. |
| 모든 수정에 문서/ADR 강제 | 기록량은 많지만 오타·동작 불변 수정까지 불필요한 결정 이력을 만든다. |
| Git 설계/ADR와 필수 문서 판단 게이트 | 필요 갱신과 근거 있는 생략을 구분하되 reviewer의 의미 판단 비용을 유지한다. |

## 선택 이유

실행 로그와 장기 설계를 구분하고 매 검토의 문서 판단을 승인 근거로 남길 수 있다.
단순 수정은 이유를 남겨 생략하고 경계/정책 변경은 문서·ADR와 함께 검토하는 기준이 요청에 부합한다.

## 결과·비용·제약

모든 reviewer fixture·demo와 응답 schema를 갱신해야 하며 이전 schema 응답은 거부된다.
잘못된 review JSON은 계획처럼 자동 복구하지 않는다. scope 밖 문서 누락은 새 범위 승인과 새 실행
비용이 든다. 형식 게이트는 문서 내용의 정확성을 자동 증명하지 않는다.
기존 ADR 변경 결정은 삭제/재작성 대신 superseded와 대체 ADR 링크로 보존한다.
역할·모델·예산·순차 실행·읽기 승인·검사·실패 한도·게시 정책은 유지한다.
private 로그·비밀·운영 데이터 원문을 설계서/ADR에 옮기지 않는다.

## 관련 코드·검증·문서

- [workflow.py](../../harness/workflow.py): DOCUMENTATION_GUIDANCE/parse_review/execute/demo.
- [test_workflow.py](../../harness/test_workflow.py): schema 누락·잘못된 문서 참조·모순·반영/게시 차단,
  실제 문서 갱신→승인→검증→반영, missing 수정 task/한도/새 검토·direct/read_only/demo 회귀.
- [AGENTS.md](../../AGENTS.md), [workflow schema](../workflow.md#검토와-검증-기준), [전체 설계](../harness-design.md).
- [목록·템플릿·이력 보존](README.md), [0002 읽기 승인](0002-explicit-model-read-scope.md),
  [0003 제한 수정](0003-role-routing-and-bounded-repair.md), [0004 반영 게이트](0004-reviewed-and-validated-publication.md).

회귀를 작성했으며 작업자는 검사를 실행하지 않는다. 전체 make check와 실제 reviewer→검증→git 결과는
오케스트레이터 보고서로 확인하고 메인이 PR·3개 CI·merge SHA를 이어 확인한다.
