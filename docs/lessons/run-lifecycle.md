# Run 수명과 완료 순서 교훈

요약: 준비 재시작은 엄격히 제한하고 run 생성 뒤 실패와 최종 완료 상태를 분리한다.

## 실행 전 준비

parent는 실행 전 모든 설정 경로가 존재하는지 확인한다. local model 설정은 `logs/harness/local-model.json`이다. 이 경로 표기는 parent 준비를 설명하며 모델의 추가 읽기 승인이 아니다. credential은 사용자만 다루고 모델에 제공하지 않는다.

parent의 run 식별은 `triage.digest(task)` 기준이다. 단순 파일 bytes SHA-256과 구분하며 둘을 같은 값이라고 추정하지 않는다. 실행 승인과 입력이 맞는지 확인하고, Makefile의 기본 venv 선택과 기존 실행 권한 경계를 유지한다. PYTHON 등 추가 실행 설정이나 세션 sandbox를 임의로 바꾸지 않는다.

사용자 제공 사실: 이 개발 VM의 Ubuntu 24.04는 AppArmor로 unprivileged userns를 제한하므로 Codex 번들 bwrap에 `/etc/apparmor.d/codex-bwrap` 프로필이 필요하다. 점검 예: `codex sandbox -- /usr/bin/printf 'CODEX_SANDBOX_OK\n'`. 이번 문서 작업에서 OS 프로필 설치·보안 설정 변경·sandbox 점검을 수행했다는 뜻은 아니다.

Codex 샌드박스는 mount namespace가 달라 같은 NFS device/inode도 mount ID가 다를 수 있다. archive 검증을 포함한 parent make 명령은 호스트 namespace의 escalated로 실행한다. receipt/journal hash 수정이나 fallback으로 우회하지 않는다.

## 재시작 경계

native workflow 진입/run ID 생성 전 parent 준비 자체 결함만 수정 후 한 번 재시작할 수 있다. 모델·검사·seed 반영이 없음을 확인해야 하며 원인과 재시작 사실을 기록한다. 이 조건을 확인하지 못하면 준비 결함이라는 추정으로 재시작하지 않는다.

run ID 생성 뒤 실패는 재시도하지 않는다. parent가 workflow·모델·검사를 별도로 재실행하지 않으며, 하네스의 기존 native 수정 정책은 변경하지 않는다. 준비 단계의 예외를 모델 응답·검사 실패나 run 이후 복구에 확대하지 않는다.

## 세션 전체의 단일 실행

workflow는 세션을 통틀어 동시에 하나만 실행한다. 진행 중인 workflow를 중간에 끊지 않고 종료 상태까지 기다린다. SIGINT나 parent stop-on-failure watchdog을 사용하지 않는다. 구현자·reviewer는 검사·Git·운영 명령·재위임·workflow를 실행하지 않는다.

실패 후에는 실제 결과를 보고한다. 정상 종료 결과 없는 호출, 작성한 테스트, 준비 상태, 과거 성공을 이번 검증 성공으로 세지 않는다. 고정 `end`와 입력 digest 비교는 [실패 보고](../ops/failure-reporting.md)를 따른다.

기본 게시 deadline 30분은 Git 준비 시점부터 흐르며 사람 승인 대기 중에도 감소한다. native `publish_remaining_seconds`와 최소 쓰기 시간 gate를 따르고 임의 연장·재시도하지 않는다. 읽기 요청 예외 등 상세는 [GitHub 전달](../ops/github-transport.md#다음-요청과-복구)의 기존 계약을 따른다.

## Merge 이후도 별도 완료

사용자가 GitHub UI에서 Squash and merge하고 Delete branch는 누르지 않는다. parent의 비교·삭제·cleanup·archive와 알려진 순서 문제는 [merge와 정리](../ops/merge-cleanup.md)를 따른다.

merge 성공과 cleanup/archive 완료는 별도 상태다. pending을 전체 완료로 보고하지 않는다.

이 교훈은 새 실행 권한이 아니다. 승인 범위·실행 게이트를 확인하고 실제 증거에 따라 보고한다.

[workflow 운영](../ops/workflow.md) · [승인 freshness](approval-freshness.md) · [index로 돌아가기](../index.md)
