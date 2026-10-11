# 0002. 명시적 모델 읽기 승인과 전체 로컬 검증 사본 분리

- 상태: 승인(accepted) — 관측된 구현 결정으로 기록한다는 의미
- 기록일: 2026-10-11
- 기록 성격: 현 구현에서 복원. 과거 도입 의도·검토·날짜를 추정하지 않는다.
- 대체 관계: 없음

## 문맥

담당 모델에게 일부 파일 편집을 맡겨도 원본 저장소를 cwd로 주면 승인하지 않은 소스·부모 지침·
로컬 운영 파일을 읽을 수 있다. 반대로 승인 파일만으로 로컬 전체 검증을 하면 필요한 소스와
기존 사용자 수정이 빠질 수 있다. 읽기 승인과 검사 입력은 목적이 다르다.

## 결정

FILES_FILE은 외부 모델의 개별 읽기 승인 목록이다. 저장소 부모 밖 모델 사본에는 정확한 승인
파일만 복사하고 신규 예정 파일은 경로만 유지한다. read_only도 같은 읽기 범위를 사용한다.
로컬 검증 사본에는 보호 경로를 제외한 Git 추적·무시되지 않은 새 소스와 기존 사용자 수정·삭제를
현재 상태로 복사한다. 모델 cwd/추가 읽기 경로로 이 사본을 제공하지 않는다.
모델 승인 변경만 동기화한다. AGENTS·문서도 승인 밖이면 자동 추가하지 않는다.
필요 문서가 밖에 있으면 missing finding을 기존 승인 파일에 귀속하고 메인이 범위를 확인한 새 실행을 준비한다.

Codex는 root deny와 좁은 workspace/CLI/셸 예외, 도구 network=false, 자동 지침/skill/apps 차단을
사용한다. Claude/GLM은 restricted cwd 파일 도구와 비활성 shell/MCP/자동 메모리를 사용한다.
인증·설정·고정 compaction은 신뢰한 CLI 런타임이며 모델 소스 context와 구분한다.

## 비교 대안

이번 문서화 시점의 평가이며 당시 고려 대안을 주장하지 않는다.

| 대안 | 평가 |
| --- | --- |
| 원본/전체 검증 사본을 모델에 제공 | 문맥은 풍부하지만 개별 외부 읽기 승인과 비밀·운영 데이터 보호 경계를 흐린다. |
| 승인 파일만 검사 | 읽기 경계는 좁지만 의존 소스와 사용자 변경을 포함한 전체 검사가 어렵다. |
| 두 사본과 범위 동기화 | 읽기 승인과 검사 완전성을 분리하는 대신 저장 공간·hash 검사·동기화 비용이 든다. |

## 선택 이유

현재 구조는 필요한 검사 입력을 로컬에 보존하면서 외부 모델에 제공할 파일을 명시적으로 제한한다.
소스 부족을 자동 읽기 확장 대신 새 승인 범위로 해결하는 방식이 검토 가능하다.

## 결과·비용·제약

보호 필터는 Git metadata·키·.env·운영 INI·지역 환경·patch/unpack·Translation·JSON·버전·backup 등을
제외하고 symlink·디렉터리 scope를 거부한다. 빈 일회용 Git만 만들며 host template는 복사하지 않는다.
등록 키 치환과 환경 분리도 임의 비밀 탐지의 완전성을 보증하지 않는다. 소스 자체의 외부 읽기 승인이 필요하다.
두 사본은 VM이 아니며 파일 도구 경계는 CLI 설정에 의존한다. unsupported 옵션은 넓은 권한으로 fallback하지 않는다.
실행 후 로그·검증 사본·모델 사본의 저장 공간을 관리해야 한다.

## 관련 코드·검증·문서

- [workspace.py](../../harness/workspace.py): copy_sources/copy_validation_sources/protected/sync_scope.
- [agent_models.py](../../harness/agent_models.py): scoped 권한·private Codex runtime·환경 분리.
- [test_workflow.py](../../harness/test_workflow.py): 승인 외 canary 분리·user content 보존·host template 차단·범위 검사 회귀.
- [workflow](../workflow.md), [전체 설계](../harness-design.md#두-작업-사본과-보호-범위), [0006](0006-versioned-design-review.md).
- [0007](0007-codex-warning-success-boundary.md): 2026-10-12 추가한 Codex 경고·성공 판정 결정.
  이 ADR의 격리 결정은 유지하고 런타임 도구 접근 허용으로 경고를 해결하지 않는다.

회귀 링크는 검증 명세이며 이 ADR 작성 중 실행한 결과는 아니다.
