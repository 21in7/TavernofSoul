# 0001. 오프라인 격리와 실제 검증 경로

- 상태: 승인(accepted) — 관측된 구현 결정으로 기록한다는 의미
- 기록일: 2026-10-11
- 기록 성격: 현 구현에서 복원. 도입 당시 의도·검토·승인·날짜는 추정하지 않는다.
- 대체 관계: 없음

## 문맥

다운로드·파싱·적재·서빙이 이어지는 저장소에서 운영 원본이나 DB로 개발 검사를 수행하면
재현성과 운영 상태 보존을 함께 확보하기 어렵다. 순수 mock만으로는 단계 사이 형식·참조·단위와
실제 importer·ORM·HTTP 경로의 오류를 충분히 확인하지 못한다.

## 결정

기본 check는 작은 고정 fixture, 임시 파일/JSON, SQLite 메모리 DB와 새 프로세스를 사용한다.
실제 parser·Lua·export·importer·migrations·ORM·HTTP를 연결하고 failure/coverage 보고서를 남긴다.
다운로더 HTTP는 고정 응답, 네이티브 IPF는 stub이므로 그 대체 경계를 명시한다.
MySQL·Chromium·검토된 live 원본 sample·공개 site smoke는 별도 명령과 결과로 구분한다.
CI 오프라인 작업은 check와 check-live, 다른 두 작업은 MySQL·Chromium을 담당한다.
선택 테스트 0개·skip/xfail·누락 보고서를 성공으로 간주하지 않는다.

## 비교 대안

이번 문서화 시점의 평가이며 과거 검토 목록이 아니다.

| 대안 | 평가 |
| --- | --- |
| 운영 unpack/JSON/DB로 검사 | 실제 데이터 폭은 넓지만 환경 의존과 운영 변경 위험·재현 비용이 크다. |
| 모든 경계를 mock | 빠르지만 실제 export·적재·HTTP 연결의 오류를 놓치기 쉽다. |
| 고정 입력과 실제 경로, 별도 선택 환경 | 반복성과 경계 coverage를 확보하되 데이터 범위의 한계를 명시할 수 있다. |

## 선택 이유

현 구현은 실제 로직을 통과하는 작은 입력과 독립 기대값을 결합한다. 운영 데이터 없이
기본 검사를 반복하고 DB/브라우저 차이는 추가 경로로 확인하는 구조가 개발 검토에 적합하다.
이는 현재 구조에 대한 평가이며 도입자의 과거 의도를 확정하지 않는다.

## 결과·비용·제약

fixture·기대값·격리 설정을 함께 유지해야 한다. 작은 sample은 전체 게임 데이터·Lua·지역 UI,
네이티브 복호화·서버 가용성을 보증하지 않는다. 기본 check는 MySQL/Chromium/site를 실행하지 않는다.
CI 설치 단계는 네트워크를 사용할 수 있으며 오프라인은 검사 입력의 경계다.
local baseline/unpack 의존 제외 테스트는 runner의 EXCLUDED에 명시하고 성공 근거에 넣지 않는다.

## 관련 코드·검증·문서

- [runner.py](../../harness/runner.py): 그룹·격리 프로세스·EXCLUDED·보고서와 coverage 게이트.
- [django_runner.py](../../harness/django_runner.py): 실제 DB/migrations lifecycle와 skip/빈 검사 차단.
- [mysql.sh](../../harness/mysql.sh), [browser.sh](../../harness/browser.sh), [CI](../../.github/workflows/harness.yml).
- [전체 설계](../harness-design.md#고정-입력과-실제-검증-경로), [사용법·유형별 coverage](../harness.md).

링크는 구현된 검증 경로를 가리킨다. 이번 기록 자체는 검사 실행 성공을 주장하지 않는다.
