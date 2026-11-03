# Workflow 운영

요약: parent가 별도 실행 승인을 확인한 뒤 입력 준비부터 단일 workflow와 실제 검증까지 책임진다.

정본은 `logs/harness/harness-runbook-core.json`이며 충돌 시 runbook core가 우선한다. 이 페이지는 공개 요약으로, 새 실행 권한이나 정책 변경을 부여하지 않는다.

## 승인과 입력 준비

TASK_FILE·FILES_FILE 작성·보고 승인과 workflow 실행 승인을 구분한다. 준비만 승인됐다면 parent는 사용자의 별도 실행 승인 전 모델·workflow·검사·Git 게시를 실행하지 않는다. credential은 사용자만 다루며 모델에 제공하지 않는다.

TASK에는 목표·공개 근거·정확한 파일 이름·읽기/쓰기 경계·완료 기준을 담는다. FILES_FILE은 개별 파일 읽기 승인 목록이다. 위치 지정이나 운영 설정·개선 scope·코드·테스트 변경을 섞지 않는다. [편집 범위](../lessons/editing-scope.md)를 따른다.

parent는 모든 설정 경로의 존재를 확인하고 Makefile 기본 venv·기존 실행 권한·세션 sandbox를 유지한다. PYTHON 등 추가 실행 설정을 override하지 않는다. local model 설정 경로와 run 식별은 [run 수명](../lessons/run-lifecycle.md)을 따른다.

## 단일 실행과 역할

workflow는 세션 전체에서 동시에 하나만 실행한다. 구현자·reviewer는 검사·Git·운영 명령·재위임·workflow를 실행하지 않는다. parent가 승인된 실행을 소유하며 중간에 끊지 않고 종료 상태까지 기다린다. SIGINT나 parent stop-on-failure watchdog을 사용하지 않는다.

run ID 생성 뒤 실패는 재시도하지 않는다. 진입 전 준비 결함의 제한된 1회 재시작 조건과 기록은 [run 수명](../lessons/run-lifecycle.md)을 따른다.

## 검토와 검증

시작과 매 검토에서 문서 영향을 판단한다. 구조·책임·계약·격리·검증·복구·게시 정책 변경에는 관련 설계·경계 문서가 필요하다. 승인 밖 필요 경로와 이유만 보고하고 범위를 늘리지 않는다. 이번 탐색층은 동작 변경이 없어 [하네스 설계](../harness-design.md)를 읽거나 수정하지 않고 새 ADR도 만들지 않는다.

Claude는 새 전체 diff에서 `documentation={status,files,reason}`를 다시 판단한다. 사실성·정본 관계·공개 제한·필수 규칙·상대 링크·크기와 AGENTS.md의 지정 한 줄 외 변경 여부를 검토한다. 의미적 완전성은 확장자 검사로 보장되지 않는다.

docs_check와 make check는 workflow/parent 소유다. 실제 diff 기반 기존 선택기와 실제 결과를 따르며 AGENTS.md 때문에 full이 선택돼도 생략하거나 docs-only로 강제하지 않는다. 링크 오류는 기존 native 수정 라운드의 승인 파일 안에서 고친다. 실패 뒤 parent의 모델·workflow·검사 재시도는 금지한다.

## 종료와 다음 단계

사전·사후 고정 비교와 성공 증거는 [실패 보고](failure-reporting.md)를 따른다. [GitHub 전달](github-transport.md)과 [merge·정리](merge-cleanup.md)는 별도 완료 증거가 필요하다. 준비·검토·검증·게시·머지·cleanup·archive 상태를 구분해 보고한다.

[index로 돌아가기](../index.md) · [기존 workflow 상세](../workflow.md)
