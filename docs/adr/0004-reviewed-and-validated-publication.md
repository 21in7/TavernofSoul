# 0004. 새 검토·필수 검증 뒤 충돌 검사와 범위 한정 반영

- 상태: 승인(accepted) — 관측된 구현 결정으로 기록한다는 의미
- 기록일: 2026-10-11
- 기록 성격: 현 구현에서 복원. 과거 도입 의도·검토·날짜는 추정하지 않는다.
- 대체 관계: 없음

## 문맥

작업 사본에 구현한 내용과 사용자 원본의 상태는 실행 도중 달라질 수 있다. reviewer CLI의
성공이나 검사 프로세스 종료 코드만으로 원본을 교체하면 미검토 변경·불완전 coverage·동시 사용자
수정을 반영하거나 덮어쓸 수 있다.

## 결정

각 구현/수정 뒤 새 구조화 reviewer 승인과 최초 필수 검사 전체 성공을 요구한다.
현재 검토는 [0006](0006-versioned-design-review.md)의 documentation 판단도 필수다.
검사는 status·exit code·selected/passed·failures/errors/skipped를 확인하고 검사 자체의 소스 변경을 거부한다.
후보 manifest를 고정하고 반영 직전 모든 복사 원본의 목록·hash·권한을 baseline과 비교한다.
충돌이 없을 때 승인 범위의 실제 변경만 backup 뒤 파일별 임시 쓰기·교체로 반영한다.
도중 실패는 자신의 변경이 아직 그대로인 파일만 역순 복구해 뒤늦은 외부 편집을 보존한다.
read_only·demo는 원본에 반영하지 않는다.

## 비교 대안

이번 문서화 시점의 평가이며 과거 실제 검토를 재현한 목록이 아니다.

| 대안 | 평가 |
| --- | --- |
| 모델이 원본을 직접 편집 | 동기화 비용은 적지만 검토·검증 실패 전에 사용자 상태를 바꾼다. |
| 변경 파일만 충돌 비교 | 간단하지만 검사 입력이었던 다른 소스의 동시 변경을 놓친다. |
| 승인 뒤 검사 없이 반영 | 의미 검토만으로 실제 회귀·coverage를 확인하기 어렵다. |
| 전체 baseline 비교·새 검토/검사·범위 반영 | 검토/검사한 입력과 반영 입력을 연결하지만 관련 없는 동시 편집도 재실행을 요구한다. |

## 선택 이유

현재 구조의 새 검토·필수 검사와 baseline 대조는 후보의 승인·검사 근거를 원본 교체에 연결한다.
기존 사용자 편집을 보존하면서 변경 범위를 제한하는 데 적합하다.

## 결과·비용·제약

전체 snapshot·hash·backup·diff 공간과 재검토 비용이 든다. 파일별 os.replace는 원자적이지만
여러 파일은 저장소 전체 원자 트랜잭션이 아니다. lock은 workflow끼리의 동시 실행을 막고,
외부 편집기와 hash 검사/교체 사이 경쟁을 완전히 제거하지 못한다.
로컬 반영 이후 git 역할/앱/CI가 실패할 수 있으며 그 상태는 게시 완료와 구분한다.

## 관련 코드·검증·문서

- [workflow.py](../../harness/workflow.py): review→validate→apply 순서와 재검토.
- [workspace.py](../../harness/workspace.py): manifest/enforce_scope/publish/replace_file.
- [failure_feedback.py](../../harness/failure_feedback.py): 구조화 검사 coverage 게이트.
- [test_workflow.py](../../harness/test_workflow.py): 충돌·후보 변경·검토/검사 거절·backup·문서 누락 차단 회귀.
- [workflow](../workflow.md), [전체 설계](../harness-design.md#충돌-검사반영과-github-게시).

검증 경로를 기록하며 이 ADR 작성 중 검사를 실행한 것으로 해석하지 않는다.
