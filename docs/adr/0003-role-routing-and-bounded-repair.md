# 0003. 경로/Jev/역할 모델 순차 배정과 제한된 실패 수정

- 상태: 승인(accepted) — 관측된 구현 결정으로 기록한다는 의미
- 기록일: 2026-10-11
- 기록 성격: 현 구현에서 복원. 과거 도입 의도·검토·날짜는 추정하지 않는다.
- 대체 관계: 없음

## 문맥

다운로더·파서·Django·공통 영역의 담당 모델이 다르다. 모델 추천만으로 필수 검증이나 파일
소유권을 바꾸면 책임이 불명확해지고, 실패를 무제한 재시도하면 비용과 종료 조건을 통제하기 어렵다.

## 결정

경로 규칙을 최소 기준으로 Jev 영역·복잡도·계약 영향 판단을 더한다. 명확히 일치하는 단일 영역은
담당자 직행, 여러 영역·불확실성·Jev 실패는 coordinator 계획과 전체 check로 넘어간다.
계획은 tasks와 각 role/task/files만 허용하고 각 승인 파일을 소유 역할에 정확히 한 번 배정한다.
실행은 순차다. 역할 provider/model/effort/호출 예산과 고정 compaction 설정은 모델 설정에 둔다.
현재 coordinator/parser는 Codex high, django/git는 Codex medium, downloader는 Z.ai GLM,
reviewer는 Claude Sonnet(호출별 2 USD)이다. Opus escalation(5 USD)은 자동 호출하지 않는다.

max_plan_attempts=2는 JSON 문법/schema만 복구하며 scope/owner 위반·planner 쓰기·CLI 실패는 즉시 중단한다.
max_rounds=2는 최초 구현을 포함한 총 라운드다. 승인 finding/검사 위치를 정확한 task에 보내고,
수정 뒤 새 검토와 모든 최초 필수 검사를 요구한다. 문서 finding도 같은 경로·한도를 사용한다.
read_only는 실패 수정 재시도하지 않는다. 공급자 오류로 다른 유료 모델에 자동 전환하지 않는다.

## 비교 대안

이번 기록 시점의 평가이며 도입 당시 대안 목록이 아니다.

| 대안 | 평가 |
| --- | --- |
| 모든 작업을 한 모델에 배정 | 단순하지만 기존 전문 역할과 경계 책임을 활용하지 못한다. |
| Jev만 믿고 배정/검사 선택 | 빠르지만 불확실한 추천이 소유권·필수 검사를 낮출 수 있다. |
| 병렬 task·무제한 수정 | 처리량 가능성이 있지만 공유 사본 충돌·비용·완료 조건이 복잡하다. |
| 경로 최소 기준·선택 계획·순차 실행·제한 수정 | 책임과 종료 조건을 명시하는 대신 대기 시간과 새 실행 비용이 든다. |

## 선택 이유

현 구조에서는 경로별 최소 검증을 고정하고 모델 판단을 배정 보조로 제한할 수 있다.
순차 task와 한도는 실패 원인 귀속·변경 hash·검토 결과를 추적하는 데 적합하다.

## 결과·비용·제약

Jev 키/전송/형식 오류는 planning fallback이지 연결 성공이 아니다. 계획 recovery도 모든 실패에
적용하지 않는다. 실패 진단은 승인 소스만 사용하고 private 로그 원문·런타임 값은 재전송하지 않는다.
귀속 불가 실패는 unavailable/unattributed 메타데이터를 최초 task 전체에 전달하는 보수적 fallback이다.
같은 실패·소스 무변경은 fingerprint로 기록하며 마지막 no_progress/exhausted_repair에서 종료한다.
호출 예산은 중앙 월 예산이 아니고 TypeSafe compaction 사용량도 Claude 예산과 별개다.

## 관련 코드·검증·문서

- [triage.py](../../harness/triage.py), [triage-config.json](../../harness/triage-config.json).
- [workflow.py](../../harness/workflow.py): owner/parse_plan/repair_feedback/execute와 [한도](../../harness/workflow-config.json).
- [모델 설정](../../harness/agent-models.json), [failure_feedback.py](../../harness/failure_feedback.py).
- [test_workflow.py](../../harness/test_workflow.py): 직접 배정·계획 복구·정확한 task 수정·한도·새 검토 회귀.
- [triage](../triage.md), [compaction](../compaction.md), [전체 설계](../harness-design.md#실패-복구와-필수-게이트).

이 기록은 회귀의 실제 실행 성공을 주장하지 않는다.
