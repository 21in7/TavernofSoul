# Docs wiki

요약: 모델과 사람이 작업 목적에 맞춰 필요한 문서만 고르는 탐색 진입점이다.

모델은 index부터 필요한 페이지만 선택해 읽는다. 링크는 읽기 승인이 아니며 TASK·FILES_FILE의 경계를 따른다. 근거가 부족하면 필요한 경로와 이유를 보고한다.

wiki는 `logs/harness/harness-runbook-core.json`의 공개 요약이다. 정본 확인도 해당 작업의 읽기 승인 범위를 따른다. 새 실행 권한이나 정책 변경은 없으며 기존 문서는 보존한다.

## Wiki 페이지 12개

- [index](index.md): 모든 wiki와 주요 기존 문서의 안내 및 작업별 읽기 순서.
- [작업 이력](log.md): 확인된 Git commit 날짜·제목을 근거로 정리하는 append-only 이력과 기록 원칙.
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

## harness.md 절 안내

읽기 승인 범위 안에서 필요한 절만 선택한다. 과거 인계·관측은 기록으로 구분한다.

### 운영·진입

- [개발 하네스 사용법](harness.md#개발-하네스-사용법): 개발 환경·검증·운영 인계의 전체 안내.
- [실패 복구 health의 parent 운영](harness.md#실패-복구-health의-parent-운영): 실패 health 조회·복구와 검토 근거 및 과거 관측 기록.
- [Trusted-parent GitHub transport 검증과 운영](harness.md#trusted-parent-github-transport-검증과-운영): parent의 GitHub 전달·receipt·응답 검증 절차.
- [승인 대기 시간별 연구와 오전 보고](harness.md#승인-대기-시간별-연구와-오전-보고): 시간별 연구·승인·예산·오전 보고 절차와 운영 관측 기록.

### 준비·실행

- [IPF 추출기 명시적 준비와 재실행 역할](harness.md#ipf-추출기-명시적-준비와-재실행-역할): IPF 추출기 준비와 실패 후 역할별 인계 기록.
- [Python 환경](harness.md#python-환경): 검증에 필요한 Python 환경과 의존성 준비.
- [신규 서버의 로컬 운영 파일](harness.md#신규-서버의-로컬-운영-파일): 신규 서버의 운영 파일 준비와 실행 책임 경계.
- [실행 범위](harness.md#실행-범위): 검증 실행 대상과 명령별 범위.

### 저장·복구

- [하네스 저장 경로 설정과 진단](harness.md#하네스-저장-경로-설정과-진단): 저장 설정 선택·호환성·준비 상태와 복구 진단.
- [호출 소유 임시 tree의 cleanup 경계](harness.md#호출-소유-임시-tree의-cleanup-경계): 호출 소유 임시 tree의 정리 경계와 회귀 검증 기록.
- [Terminal 결과 보관과 보관만 재개](harness.md#terminal-결과-보관과-보관만-재개): terminal 결과의 불변 보관과 보관만 재개하는 조건.

### 검증·CI

- [문서 전용 검증 선택과 지원 범위](harness.md#문서-전용-검증-선택과-지원-범위): 문서 변경 선택·링크 검사와 CI 증거 조건.
- [격리와 결과](harness.md#격리와-결과): 오프라인 검증 격리와 결과 해석.
- [MySQL 검증과 CI](harness.md#mysql-검증과-ci): MySQL 격리 검증 환경과 CI 실행 조건.
- [실제 브라우저 검증](harness.md#실제-브라우저-검증): 실제 Chromium 검증 준비와 브라우저 검사 계약.
- [아이템 검색 계약의 격리 검증과 인계](harness.md#아이템-검색-계약의-격리-검증과-인계): 아이템 검색의 격리 검증 계약과 인계 기록.
- [실제 게임 데이터와 운영 도메인](harness.md#실제-게임-데이터와-운영-도메인): 실제 게임 데이터·운영 도메인과 검증의 경계.
- [기본 검증에서 의도적으로 제외한 기존 테스트](harness.md#기본-검증에서-의도적으로-제외한-기존-테스트): 기본 검증에서 제외하는 기존 테스트와 사유.
- [다음 구축 범위](harness.md#다음-구축-범위): 후속 구축 대상으로 남긴 범위 기록.

### 계약·성능

- [공통 데이터 계약](harness.md#공통-데이터-계약): 파서·importer 공통 계약과 release 계약 회귀 안내.
- [최적화 회귀와 성능 근거](harness.md#최적화-회귀와-성능-근거): 최적화 회귀 요구사항·제공 측정·검증 대기 기록.
- [이번 importer/cleanup 수리의 후보 근거와 검증 대기](harness.md#이번-importercleanup-수리의-후보-근거와-검증-대기): importer·cleanup 수리 후보의 근거와 미완료 검증 기록.

### 원본 fixture

- [파서 원본 검증](harness.md#파서-원본-검증): 파서 기본 원본 fixture와 검증 범위.
- [스킬·몬스터·드롭 원본 검증](harness.md#스킬몬스터드롭-원본-검증): 스킬·몬스터·드롭 원본 fixture와 계약 검사.
- [맵·속성·버프 원본 검증](harness.md#맵속성버프-원본-검증): 맵·속성·버프 원본 fixture와 계약 검사.
- [지역별 원본 경로와 추가 유형](harness.md#지역별-원본-경로와-추가-유형): 지역별 원본 경로와 추가 유형의 검증 범위.
- [560 여신 장비·550 장신구·젬 원본 검증](harness.md#560-여신-장비550-장신구젬-원본-검증): 560 장비·550 장신구·젬 원본 fixture의 검증 범위.

### 다운로더·PAK

- [다운로더 검증과 재시도](harness.md#다운로더-검증과-재시도): 다운로더의 검증·캐시 보존·재시도 계약.
- [이번 PAK 스트리밍 재시도의 근거와 인계](harness.md#이번-pak-스트리밍-재시도의-근거와-인계): PAK 스트리밍 수리의 근거와 인계 기록.
- [작은 회귀 명세와 정정 이력](harness.md#작은-회귀-명세와-정정-이력): PAK 작은 회귀 명세와 과거 정정 기록.
- [제공된 측정과 검증 상태](harness.md#제공된-측정과-검증-상태): PAK 제공 측정과 실제 검증 상태를 구별한 기록.
- [실행·검토·게시 책임](harness.md#실행검토게시-책임): PAK 구현·검토·검사·게시 역할의 인계 기록.

### 관측·알림

- [공개 저장소의 운영 알림 설정](harness.md#공개-저장소의-운영-알림-설정): 공개 저장소의 운영 알림 설정 계약.
- [GLM telemetry 검증 인계](harness.md#glm-telemetry-검증-인계): GLM telemetry 검증 범위와 후속 인계 기록.

## 어떤 일을 할 때 어떤 페이지를 읽는가

index에서 시작해 필요한 순서만 따른다.

- 개발 준비: workflow 운영 → 편집 범위 교훈 → 설정과 크기 교훈. 실제 검증 환경의 상세가 필요하고 승인됐다면 harness를 읽는다.
- 개선 제안 승인: 승인 freshness 교훈 → improvements. eligible과 실행 허가를 구분한다.
- GitHub 게시·응답 연결: GitHub 전달 → GitHub 복구 교훈 → merge와 정리. 기존 상세는 workflow를 참조한다.
- 실패·중단: 실패 보고 → run 수명 교훈 → 해당 실패의 운영 페이지. 과거 성공을 이번 성공으로 대체하지 않는다.
- 공개 보고·이력 확인: 공개 근거 교훈 → 작업 이력. PR 제목이 보장하는 범위와 사용자 제공 관측을 구분한다.
- 구조·계약 변경 검토: architecture → data-contracts → harness-design → ADR 목록 중 승인된 필요한 문서만 읽는다. 개별 ADR 열람은 별도 범위 판단이 필요하다.

설계 확인이 필요한 작업은 읽기 승인 범위 안에서 harness-design을 확인한다. 문서 영향과 의미적 완전성은 매 검토에서 판단하고 링크 검사는 parent가 맡는다.
