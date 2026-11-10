# 0040. 개발 호스트 표시와 명시 SHA 수동 배포

- 상태: 사용자 축소 계약의 구현안, 새 전체 Claude 의미 검토·full make check·scoped apply·PR/CI3 대기
- 날짜: 2026-11-10
- 범위: Makefile, host_role/deploy, 두 회귀 파일, 설명용 설정과 승인된 공개 문서

## 문맥

개발 workflow와 GitHub 게시의 잘못된 운영 호스트 진입을 줄이고, 운영자는 기존 make target과
uWSGI unit으로만 명시 SHA를 수동 배포해야 한다. 사용자 제공 사실은 운영 aarch64 Ubuntu 20.04 /
Git 2.25.1, PR #113의 collectstatic-itos 운영 사용, 2026-11-03 prepare-ipf-unpacker 빌드 성공,
세 uWSGI unit의 ExecReload와 표준 sudo systemctl reload 명령이다. 개발 VM의 Ubuntu 24.04 /
Git 2.43 / x86_64와 codex-bwrap 프로필 뒤 printf 성공은 기존 make 명령을 재구현할 근거가 아니다.
이는 사용자에게 귀속한 사실이며 운영 소스·private settings를 추가로 열람했다는 뜻이 아니다.

## 결정

`logs/harness/host-role`은 human mistake guard다. Makefile은 `MAKECMDGOALS`에 보호 goal이
있을 때만 GNU make의 `$(file <...)`로 표식을 읽고 `strip`한 값이 production이면 `$(error ...)`로
해석 단계에서 호출 전체를 거절한다. 보호 goal은 agent-workflow, agent-git-request,
agent-git-accept, agent-git-resume, agent-git-cleanup, agent-git-next, agent-git-next-file,
agent-git-accept-file, agent-git-proof-build, agent-git-external-merge, agent-worktree-park의 11개다.
병렬·다중 goal 및 check/help와의 혼합 호출도 recipe 하나 실행하기 전에 전체 거절한다.
선행 recipe/order-only prerequisite/별도 guard target은 없다. 없음/development에서는 기존
recipe와 `make -n`/`--dry-run` 출력을 그대로 보존하며 guard 명령을 추가하지 않는다. 기본 help도
유지한다. 보호 goal 없는 check/help·status·doctor·storage·deploy 호출은 marker 값과 무관하게
허용하며 거절 사유로 marker를 읽거나 검사하지 않는다. 표식은 인증 경계가 아니며 deploy 권한
검사나 hourly 루프로 확장하지 않는다. standalone host_role helper의 엄격한 malformed/unsafe/I/O
검사 계약은 이 make 동작과 별개로 보존한다. deploy가 사용하는 read_file/open_directory도 유지한다.

`make deploy COMMIT=<full40hex>`는 (1) 저장소/root/origin/master·SHA·CI·청결·고정 잠금 확인,
(2) private durable old-state 기록, (3) 정확 target ff-only, (4) gitlink 변경 때만 승인 submodule
update와 기존 make prepare-ipf-unpacker, (5) 정적 변경 때만 기존 make collectstatic-itos 및
Python/템플릿 변경 때만 itos→jtos→ktos sudo systemctl reload/단1회 is-active/HTTP 확인,
(6) 명시 cache URL 출력의 여섯 단계로 제한한다. migrations diff는 rename/delete를 포함해 거절한다.

GitHub public GET은 실제 required CI3와 추가 check/status를 검사하며 기존 checks_gate의
latest/suite/selection/execution skip 정책을 재사용한다. 응답 body 2 MiB·10초, 목록 100개 단일
완전 페이지로 제한하고 pagination/unknown/오류는 거절한다. 인증·gh·fallback·재시도는 없다.
세 고정 flock은 기존 inode/owner/mode/content를 보존하며 끝까지 nonblocking으로 유지한다.
순서는 workflow 실행 → cron → source다. 결과는 새 0600 JSONL과 fsync로 남기고 실패 뒤 실제 상태를
확인하며 후속 작업·자동 retry/rollback은 없다. 자세한 경로·설정·실패 계약은
[배포 운영 문서](../ops/deployment.md)에 둔다.

## 비교 대안과 선택 이유

host-role을 운영 권한 검사로 확장하면 표식 유무를 신뢰하는 잘못된 권한 경계가 생긴다.
새 manage.py/build 명령이나 빈 HOME/XDG 환경은 이미 운영에서 쓰는 명령과 환경 계약을 바꾼다.
자동 배포·purge·migration·rollback은 별도 운영 승인과 복구 판단이 필요하다.
이번에는 기존 명령·환경을 유지하고 명시 SHA와 변경 분기에 따라 호출만 제한한다.

## 결과·제약과 책임

Python 3.8 / Git 2.25.1 / aarch64 Ubuntu 20.04 호환 코드를 작성한다. flock과 표식은 외부 편집이나
직접 명령을 완전히 통제하지 않는다. ff 이후 실패는 부분 반영 상태로 남아 운영자의 판단이 필요하다.
ignored deploy-local.json의 명시 health/cache URL은 운영자가 준비하며 예제는 서비스 추정값이 아니다.

improvements.py/improvement_loop.py와 hourly/daily/discovery/unattended 전체 루프는 이번
읽기·구현 범위 밖이다. host-role 연동·해당 환경 marker 탐지/전파·READ_ONLY export·자동 실행 거절
요구를 추가하지 않는다. 기존 workflow의 worker 실행 금지 정책과 개인 설정/인증/모델/예산/CI/cron/
게임 데이터/서비스 unit은 유지한다. 테스트는 fake만 작성하고 실행과 검증은 workflow/parent가 맡는다.

최종 Claude는 최종 코드/문서 전체의 documentation={status,files,reason}을 새로 판단한다.
이전 실패 run 1794200817586036907-70299e와 과거 초안·검토·보관은 새 검증 성공이 아니다.
새 단일 workflow의 새 의미 검토·full make check(GIT=1)·scoped apply와 기존 git 역할 뒤
표준 parent make next/next-file/accept-file 경로로 PR과 실제 CI3 성공을 확인하고 merge 전 멈춘다.
실패 시 parent의 별도 workflow/모델/검사 재시도는 없다. 기존 native round의 실제 발생은 별도로
구분 기록한다. 실제 운영은 유지하며 운영 반영은 별도 사용자 지시를 받은 운영 세션 책임이다.
