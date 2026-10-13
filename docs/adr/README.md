# 하네스 설계 결정 기록

전체 맥락은 [전체 하네스 설계](../harness-design.md), 실행 절차는 [workflow](../workflow.md),
환경·검증 범위는 [하네스 사용법](../harness.md)에 둔다. ADR는 주요 선택·비교·비용을 기록한다.

| 번호 | 결정 | 상태 | 기록일 |
| --- | --- | --- | --- |
| [0001](0001-isolated-offline-validation.md) | 오프라인 격리와 실제 검증 경로 | 승인(accepted), 현 구현 복원 | 2026-10-11 |
| [0002](0002-explicit-model-read-scope.md) | 명시적 모델 읽기 승인과 전체 로컬 검증 사본 분리 | 승인(accepted), 현 구현 복원 | 2026-10-11 |
| [0003](0003-role-routing-and-bounded-repair.md) | 경로/Jev/역할 모델 순차 배정과 제한된 실패 수정 | 승인(accepted), 현 구현 복원 | 2026-10-11 |
| [0004](0004-reviewed-and-validated-publication.md) | 새 검토·필수 검증 뒤 충돌 검사와 범위 반영 | 승인(accepted), 현 구현 복원 | 2026-10-11 |
| [0005](0005-github-connector-delivery.md) | 메인 GitHub 앱 journal·3개 CI·SHA 고정 merge | 승인(accepted), 현 구현 복원 | 2026-10-11 |
| [0006](0006-versioned-design-review.md) | Git 관리 설계·ADR와 매 검토의 문서 판단 | 승인(accepted), 이번 요청의 결정 | 2026-10-11 |
| [0007](0007-codex-warning-success-boundary.md) | Codex 성공 증거 우선과 안전한 경고 metadata | 승인(accepted), 새 결정 | 2026-10-12 |
| [0008](0008-json-validation-single-pass.md) | 모든 JSON 파일의 엄격한 검사 뒤 중복 finite_tree만 제거 | 승인(accepted), 새 결정 | 2026-10-12 |
| [0009](0009-post-merge-branch-cleanup.md) | master squash PR 유지와 메인의 증거 기반 머지 후 브랜치 정리 | 대체됨(superseded), 0010 | 2026-10-12 |
| [0010](0010-automatic-post-merge-cleanup.md) | 자동 parent Git cleanup·lease 비교 삭제·durable 복구·전체 완료 게이트 | 승인(accepted), 새 구현 결정 | 2026-10-12 |
| [0011](0011-configurable-harness-storage.md) | 설정 가능한 산출물·비인증 임시 저장, 고정 로컬 lock·인증 runtime, legacy 조회와 fallback 금지 | 제안(proposed), 구현안 검토·검증·전달 대기 | 2026-10-13 |

## 상태와 근거의 의미

0001~0005는 현 소스에서 복원한 기록이다. 승인(accepted)은 **관측된 구현 결정으로 기록한다**는
뜻이며 과거 도입 당시 승인을 증명하지 않는다. 기록일은 이번 문서 작성일이고 실제 도입일·당시 의도·
검토 과정·실행 성공 날짜를 추정하지 않는다. 대안 비교와 선택 이유는 이번 문서화 시점의 평가다.
0006은 이번 요청에 따른 문서 유지·검토 게이트 결정이며 승인 상태가 검사 통과를 뜻하지 않는다.
0007은 Codex warning과 성공/실패 판정을 분리하는 새 결정이다. 0002의 격리 결정을 바꾸거나
대체하지 않으며, 승인 상태는 수리 worker의 검사 실행·일반 workflow 성공·게시 완료를 뜻하지 않는다.
0008은 공개 메모리 검사와 파일별 엄격한 검사를 유지하면서 내부 중복 순회만 제거하는 결정이다.
승인 상태나 제공된 prototype/local diagnostic 수치는 최종 회귀·전체 파서·CI 성공·누적 개선율을 증명하지 않는다.
0009는 당시 별도 메인 정리 정책의 역사적 기록이며 본문을 보존한다. 0010이 자동 정리와 전체 완료
게이트로 대체한다. merge 성공/SHA를 보존하고 fresh proof·exact ref 삭제·prune·clean ff-only까지
complete여야 passed다. 새 repository/default_branch proof로 현재 기본 브랜치를 보존한다.
기존 github-v1/merged run은 명시적 request/resume/cleanup에서 재검증한다.
0010의 승인 상태는 worker의 검사 실행, 실제 PR/CI/merge 또는 이번 run의 cleanup 성공을 증명하지 않는다.
0011은 외부 artifacts/temp와 고정 로컬 project lock·credential runtime을 분리하는 저장 결정이다.
0010을 대체하지 않으며 기존 approved hash·expected SHA·durable snapshot·정확한 cleanup·전체 완료
게이트는 유지한다. legacy absolute 경로는 재작성하지 않고 status/latest·Git 재개에서 함께 조회한다.
proposed는 구현안의 독립 의미 검토·full checks·GitHub 전달이 대기 중임을 나타내며 main은 그 뒤에만
호스트 private 설정을 활성화한다. ADR 존재·회귀 정의·draft 복구가 승인이나 activation 증거는 아니다.

상태는 제안(proposed), 승인(accepted), 대체됨(superseded)을 사용한다. 이후 결정 변경은
기존 ADR를 삭제하거나 새 결론으로 재작성하지 않는다. 기존 상태를 superseded로 바꾸고
대체 ADR 링크를 추가하며, 새 번호의 ADR에서 이전 결정을 링크하고 변경 이유를 기록한다.
사실 오류 정정은 근거와 정정일을 덧붙여 이전 판단을 알아볼 수 있게 보존한다.

## 작성·검토 규칙

업무 시작 시 구조·책임·계약·격리·검증·실패 복구·GitHub 게시 정책의 문서 영향을 판단한다.
관련 설계·경계 문서를 갱신하고 주요 결정에 새 ADR를 작성한다. 단순 오타·동작 불변 국소 수정은
문서 생략 이유를 reviewer의 documentation.not_required에 구체적으로 기록할 수 있다.
필요 문서가 승인 읽기 scope 밖이면 자동 열람·복사·생성하지 않는다. 누락 경로를 보고하고
기존 승인 파일 finding과 documentation.missing으로 승인을 거부한다. 메인이 범위 확인 후 새 실행을 준비한다.
이번 저장 정책 변경의 매 orchestrator review는 `documentation={status,files,reason}`을 반환하고
`status=updated`를 실제 변경된 승인 Markdown 목록과 구조·격리·실패 복구·운영 명령의 의미적
완전성 판단으로 뒷받침한다. Markdown 확장자 확인은 완전성 증거가 아니다. tests/full `make check`는
orchestrator, connector 게시·필수 CI 확인·merge·정확한 cleanup은 main의 책임이다.

번호는 목록의 다음 번호를 사용하고 한 ADR에는 한 주요 결정을 둔다. 문맥·결정·비교 대안·선택 이유·
결과/비용/제약을 구분한다. 소스·설정·검증 경로·문서의 실제 링크를 포함하되 검증 경로가 있다는 것과
실행 성공을 구분한다. 키·운영 데이터·private 계획/응답/로그 원문은 ADR에 복사하지 않는다.
결정의 근거가 부족하면 부족한 파일/정보를 명시하고 검증·승인·날짜를 꾸미지 않는다.

## 템플릿

```markdown
# NNNN. 결정 제목

- 상태: 제안(proposed) / 승인(accepted) / 대체됨(superseded)
- 기록일: YYYY-MM-DD
- 기록 성격: 새 결정 / 현 구현 복원 (기록일과 도입일을 구분)
- 대체 관계: 없음 / 이전 ADR 링크 / 대체 ADR 링크

## 문맥
문제·요구·실제 근거와 불확실한 부분.

## 결정
선택한 정책·책임·경계.

## 비교 대안
고려 가능한 선택과 비용. 복원 기록이면 이번 문서화 시점의 평가임을 명시.

## 선택 이유
결정과 근거의 연결. 과거 도입 의도·승인 과정을 추정하지 않음.

## 결과·비용·제약
얻는 효과·추가 작업·남은 한계·실패와 복구 경계.

## 관련 코드·검증·문서
실제 경로 링크. 검사 명세·미실행·실제 결과를 구분.
```
