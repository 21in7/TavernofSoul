# Docs wiki

요약: 모델과 사람이 작업 목적에 맞춰 필요한 문서만 고르는 탐색 진입점이다.

모델은 index부터 필요한 페이지만 선택해 읽는다. 링크는 읽기 승인이 아니며 TASK·FILES_FILE의 경계를 따른다. 근거가 부족하면 필요한 경로와 이유를 보고한다.

wiki는 `logs/harness/harness-runbook-core.json`의 공개 요약이다. 정본은 읽으러 가지 않는다. 새 실행 권한이나 정책 변경은 없으며 기존 문서는 보존한다.

## Wiki 페이지 12개

- [index](index.md): 모든 wiki와 주요 기존 문서의 안내 및 작업별 읽기 순서.
- [작업 이력](log.md): 제공된 Git commit 날짜·제목 근거로 정리한 PR #86~#103과 append-only 기록 원칙.
- [workflow 운영](ops/workflow.md): 승인, 입력 준비, 단일 실행, 검토와 검증의 책임 순서.
- [GitHub 전달](ops/github-transport.md): fork 게시, 파일 기반 응답 framing, accept와 다음 요청 연결.
- [merge와 정리](ops/merge-cleanup.md): 사용자 UI squash merge 이후 parent의 비교, 삭제, cleanup과 archive.
- [실패 보고](ops/failure-reporting.md): 중단과 재시도 금지, 고정 비교, 증거 수준에 맞는 보고.
- [편집 범위 교훈](lessons/editing-scope.md): provider별 부분 편집과 정확한 이름으로 파일 지정하기.
- [설정과 크기 교훈](lessons/config-and-size.md): 설정 상속 fixture 사전 점검, PR 분할과 바이트 예산.
- [GitHub 복구 교훈](lessons/github-recovery.md): 거절된 쓰기의 원래 요청 연결과 PR 설명 검토.
- [run 수명 교훈](lessons/run-lifecycle.md): run 생성 전후의 재시작 경계, 단일 실행과 완료 순서.
- [승인 freshness 교훈](lessons/approval-freshness.md): 전체 scope source fingerprint와 control 변경에 따른 승인 무효화.
- [공개 근거 교훈](lessons/public-evidence.md): 공개 정보 한계, fork 대상, 관측과 추정의 구분.

## 기존 읽기 참조 7개

읽기 승인된 문서만 확인한다.

- [architecture](architecture.md): 프로젝트와 데이터 흐름.
- [harness](harness.md): 검증·환경 준비.
- [workflow](workflow.md): workflow·게시·복구의 기존 상세.
- [harness-design](harness-design.md): 하네스 책임·격리·설계.
- [improvements](improvements.md): 개선 연구·승인·freshness.
- [data-contracts](data-contracts.md): parser/importer 데이터 계약.
- [ADR 목록](adr/README.md): 설계 결정 목록.

## 어떤 일을 할 때 어떤 페이지를 읽는가

index에서 시작해 필요한 순서만 따른다.

- 개발 준비: workflow 운영 → 편집 범위 교훈 → 설정과 크기 교훈. 실제 검증 환경의 상세가 필요하고 승인됐다면 harness를 읽는다.
- 개선 제안 승인: 승인 freshness 교훈 → improvements. eligible과 실행 허가를 구분한다.
- GitHub 게시·응답 연결: GitHub 전달 → GitHub 복구 교훈 → merge와 정리. 기존 상세는 workflow를 참조한다.
- 실패·중단: 실패 보고 → run 수명 교훈 → 해당 실패의 운영 페이지. 과거 성공을 이번 성공으로 대체하지 않는다.
- 공개 보고·이력 확인: 공개 근거 교훈 → 작업 이력. PR 제목이 보장하는 범위와 사용자 제공 관측을 구분한다.
- 구조·계약 변경 검토: architecture → data-contracts → harness-design → ADR 목록 중 승인된 필요한 문서만 읽는다. 개별 ADR 열람은 별도 범위 판단이 필요하다.

탐색층 추가이므로 harness-design은 링크만 안내하며 읽거나 수정하지 않는다. 의미적 완전성은 매 검토에서 판단하고 링크 검사는 parent가 맡는다.
