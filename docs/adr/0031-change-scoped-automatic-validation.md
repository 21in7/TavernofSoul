# 0031. 실제 변경에 따른 자동 검사 선택

- 상태: 사용자 범위 확정에 따른 구현안, 새 의미 검토·parent full make check·CI/게시 검증 대기
- 기록일: 2026-10-25
- 부분 대체: [0022](0022-documentation-only-validation.md)의 자동 CI full/문서 이분법과 로컬 읽기 범위 기반 검사 확대, [0023](0023-new-branch-documentation-validation.md)의 작업 branch push 자동 실행. 기존 관측·실패·검증 근거는 보존한다.

## 문맥

사용자는 중복·변경과 무관한 자동 검사를 제거하고 핵심 회귀는 유지하도록 범위를 확정했다.
작업 branch push와 PR의 이중 실행, MySQL 내부 환경 확인의 별도 재호출, 읽기 scope와
coordinator fallback만으로 전체 검사가 선택되는 경우를 줄인다. 이 명시 요청은 과거 모든
코드 변경의 무조건 heavy CI 정책 중 자동 선택 부분을 대체한다. 테스트 삭제·blanket
skip/xfail·임의 green·branch protection 변경은 포함하지 않는다.

## 결정

CI push는 master만 받으며 pull_request와 workflow_dispatch를 유지한다. 기본 branch 변경과
수동 실행은 검증한다. [check_selection.py](../../harness/check_selection.py)는 Python 3.8
stdlib만 사용하고 기존 [docs_check.ci_selection](../../harness/docs_check.py)의 전체 event
raw diff와 보수적 fallback을 재사용한다. PR base→head, master push before→after를 사용하며
마지막 commit이나 경로 주장으로 누락을 추정하지 않는다. 기존 새 branch 비교 구현은 수동
호출 호환용으로 보존하지만 작업 branch push가 이 workflow를 시작하지 않는다.

기존 validation-selection.json과 docs-result.json 계약은 보존한다. 별도 execution-plan.json은
version, event_name, 원래 selection, plan의 docs/offline/mysql/browser/live bool, reason과
양쪽 경로의 분류 근거(paths)를 기록하며 validation-selection artifact에 함께 보관한다.
전체 기록의 status/path/mode·삭제·rename 양쪽·중복 경로를 검사하고 혼합 변경은 합집합으로
선택한다. 빈/불명/malformed 증거, mode/type 변화와 수동/불명 이벤트는 모든 기존 실행을
선택한다. 잘못되거나 누락된 계획을 gate에서 full 성공으로 대체하지 않는다.

| 실제 CI 변경 | 선택한 기존 실행 |
| --- | --- |
| 일반 README/docs prose만 | 기존 docs 검사, heavy execution은 계획상 skipped |
| 명시 downloader 소스·단위 테스트 또는 orchestration 소스·단위 테스트와 일반 prose | offline `make check` |
| Django template/static과 위 offline 허용 변경 | offline + Chromium |
| parser/importer/models/settings/migrations, 공통 계약·fixture·runner·의존성·CI·Makefile·정책·selector 또는 미분류 경로 | offline + MySQL + Chromium + live |

좁은 소스 허용 목록은 downloader/downloader.py, downloader/tests/test_*.py의 직속 Python
테스트, harness의 workflow.py/test_workflow.py, git_publish.py/test_git_publish.py,
git_cleanup.py, triage.py다. 기존 triage의 docs/data-contracts.md 공통 계약 경로도 자동 full을 유지한다.
공통 runner/settings/fixtures/requirements/CI selector와 정책 설정은
이 예외에 포함하지 않는다. UI 예외는 TavernofSoul/templates/ 아래 html과
TavernofSoul/static/ 아래 명시된 css/js·이미지 suffix다. 과거 Items/templates·Items/static root, 유사 접두사·허용 밖 suffix·검증할 수
없는 경로는 full이다. offline은 축소한 테스트 집합이 아니라 기존 전체 `make check`다.
승인된 runner가 해당 회귀를 실행하고 문서의 downloader→parser→Django 책임 경계를 제공한다.
추가 source 의존성을 읽지 못한 경로까지 예외를 넓히지 않는다.

MySQL의 별도 make doctor-mysql은 check-mysql 내부 inspect_database와 중복이므로 자동 호출만
제거한다. Node setup은 유지한다. 승인된 runner에서 MySQL도 공통 doctor()의 Node 검사를
통과해야 하므로 불필요함이 입증되지 않았다. offline의 check-live는 계획에 따라 조건부 실행한다.
수동 make targets와 검사 구현·핵심 회귀 assertion은 유지한다.

세 required 이름과 별도 evidence gate jobs는 유지한다. 각 gate는 전체 계획을 재분류해
스키마·내용·원래 selection 일치·이벤트를 확인하고 모든 execution 및 offline live step의
실제 결과를 대조한다. 선택은 success, 미선택은 정확한 skipped만 허용한다. docs는 원래
selection equality, positive selected=passed, zero skip/failure/error를 요구한다. gate는
artifact 누락·잘못된 계획·예기치 않은 성공/skip·실패를 거부한다.

publisher와 fresh cleanup은 같은 SHA·허용 app·양의 정수 check_suite.id 안의 selection과
세 required success, 세 execution의 완전한 success/예정 skip 증거를 요구한다. check-runs에는
artifact 본문이 없으므로 정확한 계획 검증은 세 gate의 책임이며 publisher는 그 gate의 같은
suite 성공을 증거로 사용한다. 허용 형태는 docs의 세 skip, offline-only, offline+browser,
full이다. 각 현재 이름의 결과도 완전한 suite에 속해야 하며 다른 suite의 빈칸을 합치거나
최신 pending/failure/잘못된 suite metadata를 오래된 성공으로 덮지 않는다. 임의 job skip,
neutral/cancelled/실패는 계속 거부한다. required-only legacy/full 성공과 pagination·test-merge
우선순위·statuses·SHA 고정 merge·fresh cleanup 권한은 유지한다.

로컬 workflow는 새 reviewer 승인 뒤 매 round의 최초 baseline→현재 candidate 실제 bytes/mode
변경으로 기존 make targets를 다시 결정한다. 읽기만 한 문서/다른 영역과 planner/key/transport
fallback만으로 확대하지 않는다. prose만이면 check-docs, 명확한 단일 영역 코드와 일반 prose는
해당 영역 검사와 실제 변경 역할 설정·영역 추천의 추가 검사를 유지한다. 계약 영향 추천,
정책·하네스·공통 계약·미분류/mode 변화와 여러 영역 변경은 check다. full이면 영역 target을
중복 실행하지 않는다. 변경 없는 read-only/demo와 불명 증거는 기존 계획 또는 full을 유지한다.
기존 selection.mode의 docs/full 형식은 보존하며 로컬의 실제 명령은 local_checks에 따로 기록한다.
CI의 orchestration offline 예외를 로컬 영역 make target 축소와 혼동하지 않는다.
로컬 선택과 부분 CI skip 증명은 check_selection에 모은다. workflow는 owner·역할 검사 설정과
경로 규칙을 전달하고 publisher는 기존 동일 suite 증명과 execution 완전성 검사를 위임한다.
이 분리는 기존 runtime37 scope·128KiB/file·1.5MiB total을 유지하며 승인·설정·스케줄을 바꾸지 않는다.

## 대안·비용·제약

항상 전체 CI는 중복·무관 실행을 남긴다. 넓은 디렉터리 필터나 skipped=success는 계약 변경과
증거 누락을 숨기므로 채택하지 않는다. 작은 명시 허용 목록과 완전한 diff·계획 gate는 검토 가능한
근거를 남기지만 새 경로에는 보수적 full 비용이 들고 분류 정책 유지가 필요하다. 의존성을
확인할 승인 소스가 없으면 full로 남긴다. 모델/auth/운영 데이터/cron/승인 범위/storage/Git 역할과
branch protection은 바꾸지 않는다.

## 문서·회귀와 검증 한계

[test_check_selection.py](../../harness/test_check_selection.py),
[test_workflow.py](../../harness/test_workflow.py),
[test_git_publish.py](../../harness/test_git_publish.py)는 경로·삭제/rename·혼합·mode/type·불명,
계획 tamper·정확한 실행 상태·docs zero-skip·로컬 실제 diff/repair·suite/최신성/fresh cleanup
경계를 명세한다. 새 로컬 선택 회귀는 test_check_selection.py에 두고 기존 project fixture와
isolated_storage autouse guard를 명시 재사용한다. 실제 model/storage/network를 호출하지 않는다.
UI 회귀는 templates/Items/search.html·index.html, templates/Planner/pvp.html과
static/js/item-search.js·item-enhancement.js·pvp-calculator.js를 각각 TavernofSoul/ 아래에서
offline+browser로 확인하며 과거 root·유사 접두사·허용 밖 suffix는 full로 남긴다.
기존 private artifact 회귀는 보고서의 모든 실제 선택 target 디렉터리와 0700/0600·격리를 확인한다.
기존 test_docs_check의 CI 연결 assertion만 새 helper 연결에 맞춘다.
이전 run 1792921741188646683-e101ce는 full check 실패·applied=[]이며 성공 근거가 아니다.
parent 제공 측정은 runtime37 원본 1,571,837 bytes·제한 1,572,864 bytes·보존 후보
1,587,626 bytes다. 승인된 helper/회귀로 이동하고 기존 문서의 새 정책 중복만 줄여야 하며,
기능·assertion·과거 관측을 지우거나 scope/상한을 늘려 맞추지 않는다.
이번 candidate는 selector·CI·검증 정책 변경이므로 parent의 새 full make check 대상이다.
worker는 검사·Git·네트워크를 실행하지 않았다. 새 reviewer는 최종 source·문서를 새로 읽고
매번 documentation={status,files,reason}으로 의미적 완전성을 판단한다. 작성된 테스트와 문서는
실제 성공이나 성능 수치의 증거가 아니다. 관련 현재 규칙은 [workflow](../workflow.md),
[harness-design](../harness-design.md), [harness](../harness.md), [architecture](../architecture.md)에 둔다.
