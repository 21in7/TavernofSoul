# 설정 상속과 크기 교훈

요약: 설정 전환의 fixture 영향과 큰 수정 라운드의 비용을 미리 분리해 살핀다.

## 설정 fixture의 전제

사용자 제공 환경: 운영은 aarch64·Ubuntu 20.04·Git 2.25.1·MariaDB 11.3, 개발 VM은 x86_64·Ubuntu 24.04·Git 2.43, CI는 MySQL 8.4다. CI의 OS·CPU·Git은 미제공이며 두 DB를 동일시하지 않는다. 이번에 DB·운영 환경을 조회한 근거가 아니다. 2.28 이후 옵션(git init --initial-branch 등)은 CI를 통과해도 운영 검사에서 실패한다.

운영 설정을 상속하는 fixture는 설정 전환으로 깨질 수 있다. 사용자 제공 PR #103 관측에 따른 교훈은, 그런 PR 실행 전에 일회용 복사본에서 설정만 바꿔 전체 테스트를 사전 점검하는 것이다. 설정 전환 영향과 구현 결함을 구분할 근거를 준비한다.

이는 이번 문서 작업에서 설정을 변경하거나 테스트를 실행하라는 지시가 아니다. 검사 소유자는 workflow/parent이며 구현자·reviewer는 실행하지 않는다. 사전 점검을 했더라도 이후 실제 diff에 필요한 검증을 대체하거나 과거 결과를 이번 성공으로 재사용하지 않는다.

Makefile 기본 venv 선택을 유지하고 PYTHON 등 추가 실행 설정을 override하지 않는다. parent의 기존 실행 권한과 세션 sandbox 설정도 유지한다. 설정 경로 존재 확인과 run 생성 전후의 경계는 [run 수명](run-lifecycle.md)을 따른다.

사용자 제공 교훈: 운영 umask 0002로 Git 생성 파일이 0664가 되므로 `core.sharedRepository=0644`로 고정한다(설명용: `git config --local core.sharedRepository 0644`). [make deploy](../ops/deployment.md)의 group-write 거절은 index·잠금·배포 디렉터리 등 검사 대상에 적용된다. parent는 구현의 `.git/index`에 대한 `st_mode & 0o022` 거절을 읽기 확인했다. 모든 추적 소스에 0644를 강제하거나 설정 한 번으로 기존 파일 권한을 모두 바꾼다는 뜻은 아니다.

사용자 제공 관측: logrotate가 저장소 안 `*.log`를 회전시키면 미추적 회전 파일로 deploy의 clean 검사에서 거절된다. 저장소 안 포괄 회전을 피한다. 이번 작업에서 Git·logrotate 설정, 파일 삭제나 `.gitignore` 변경은 수행하지 않는다.

## PR과 수정 라운드의 크기

큰 구현·수정 라운드는 timeout 위험이 있다. PR #101~#103의 사용자 제공 교훈은 기능 추가와 운영 전환 PR을 나누는 것이다. commit 제목은 변경 이력의 근거이며 timeout 원인·전체 테스트·운영 성공까지 독립적으로 증명하지 않는다.

개선 scope 안 파일 증가는 연구 바이트 예산을 압박하므로 기능 분할과 함께 고려한다. 파일 수만 줄었는지 보지 말고 읽어야 할 본문 크기와 수정 라운드의 부담도 고려한다. runtime 연구 상한과 개발 workflow 상한은 별개다. PR 설명에서도 두 상한을 같은 제한처럼 표현하지 않는다.

이 교훈이 scope나 예산 설정을 임의로 바꾸는 권한은 아니다. control 변경과 scope 전체 source fingerprint는 [승인 freshness](approval-freshness.md)를 따른다. 동일한 후보라도 변경 전 승인을 재사용하지 않는다.

## Wiki의 바이트 예산

새 페이지는 UTF-8 기준 각 약 4096 bytes 이하를 목표로 한다. index는 짧은 안내와 작업별 읽기 순서를 제공하고, 긴 운영 설명은 해당 ops에 둔다. lessons는 원인·주의점과 ops 링크를 담아 같은 절차의 긴 복제를 줄인다. 한글 글자 수와 UTF-8 bytes는 같지 않다.

페이지를 나눠도 승인된 정확한 파일 이름을 유지한다. 예산을 맞추기 위해 필수 규칙을 빼거나 승인 밖 파일을 추가하지 않는다. 페이지 크기·링크와 의미적 완전성은 parent 검증 및 새 검토에서 판단하며 이번 worker는 검사를 실행하지 않는다.

[workflow 운영](../ops/workflow.md) · [GitHub 복구](github-recovery.md) · [index로 돌아가기](../index.md)
