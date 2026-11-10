# 개발 호스트 표시와 수동 배포

이 문서는 [ADR0040](../adr/0040-development-host-and-production-deploy.md)의 축소 계약이다.
구현안·회귀 작성은 검증 성공이나 운영 배포 증거가 아니다. 첫 PR은 새 전체 Claude 의미 검토의
`documentation={status,files,reason}`, 기본 GIT=1의 full `make check`, scoped apply,
기존 git 역할 뒤 parent의 표준 `make agent-git-next` / `agent-git-next-file` /
`agent-git-accept-file` 경로로 PR과 실제 필수 CI3 성공을 확인하고 merge 전에 멈춘다.
worker/reviewer는 검사·Git·네트워크·운영 명령·모델·재위임·workflow를 실행하지 않는다.
실패 시 parent의 별도 workflow·모델·검사 재시도는 없다. 기존 native round의 실제 발생은
별도로 구분 기록한다. 이전 실패 run `1794200817586036907-70299e`의 draft/review/보관은
이번 승인·검증 성공을 대신하지 않는다. 실제 운영은 그대로 유지한다.
운영 반영은 별도 사용자 지시를 받은 운영 세션 담당자의 책임이다.

## 호스트 역할 표식

무시되는 `ROOT/logs/harness/host-role`에는 `development` 또는 `production`을 쓴다.
Makefile은 `MAKECMDGOALS`에 다음 보호 goal이 있을 때만 GNU make의 `$(file <...)`로 읽는다.
읽은 값을 `strip`한 결과가 production이면 `$(error ...)`로 해석 단계에서 호출 전체를 거절한다.
`agent-workflow`, `agent-git-request`, `agent-git-accept`, `agent-git-resume`,
`agent-git-cleanup`, `agent-git-next`, `agent-git-next-file`, `agent-git-accept-file`,
`agent-git-proof-build`, `agent-git-external-merge`, `agent-worktree-park`의 11개다.
여러 goal과 `make -j`에도 recipe가 하나도 실행되지 않는다. check/help를 먼저 나열한 혼합 호출도
전체가 거절된다. 선행 recipe/order-only prerequisite/별도 guard target은 연결하지 않는다.
파일 없음/development이면 원래 대상 recipe를 그대로 실행하며 `make -n`/`--dry-run`에도
guard 명령이 추가되지 않는다. 기본 목표는 계속 help다. 보호 goal이 없는 check/help,
workflow status/plan/demo, Git doctor, storage 진단, deploy 호출은 marker 값과 무관하게 허용하며
marker를 읽거나 거절 사유로 검사하지 않는다. 표식은 사람이 잘못된 호스트에서 진입하는 것을
줄이는 표시일 뿐 인증·권한 경계가 아니다. deploy의 production 강제나 hourly 루프로 확대하지
않으며 직접 Python 실행까지 통제하지 않는다. GNU make 4.2(Ubuntu 20.04) 범위의 기능만 쓴다.

별도 standalone `harness.host_role` helper는 정확한 두 값과 선택적인 마지막 LF 하나만 허용하고
malformed·symlink/별칭·unsafe·I/O 오류를 거절하는 기존 계약을 유지한다. 이는 새 Makefile guard의
실행 경로가 아니다. deploy의 공통 안전 파일 읽기 API인 read_file/open_directory도 보존한다.

## 운영자 준비와 설정

사용자가 이번 작업의 사실 근거로 제공한 운영 정보: 운영은 aarch64 Ubuntu 20.04 / Git 2.25.1,
`make collectstatic-itos`는 PR #113에서 추가되어 운영에서 사용됐고,
`make prepare-ipf-unpacker`로 2026-11-03 운영 IPF 빌드가 성공했다. 세 uWSGI unit 모두
ExecReload가 있고 표준 명령은 `sudo systemctl reload uwsgi@<region>`이다.
개발 VM은 Ubuntu 24.04 / Git 2.43 / x86_64이며 사용자 적용 codex-bwrap AppArmor 프로필 뒤
샌드박스 printf가 성공했다. 이는 make 자체를 바꿀 근거가 아니다. 운영 소스·private Django
settings를 추가로 읽어 검증한 사실로 주장하지 않는다.

운영자는 준비된 기존 세션 환경에서 저장소 루트의 `make deploy COMMIT=<full40hex>`를 수동 실행한다.
full40hex는 소문자 40자리 SHA다. 소스는 credential-free fork
`https://github.com/21in7/TavernofSoul.git`의 master이고 IPFUnpacker도 승인된 HTTPS origin이어야 한다.
실제 root·일반 `.git` checkout·master·표준 index·origin URL과 fetch mapping을 확인한다.
mapping은 표준 heads wildcard 또는 master→origin/master 하나만 허용하며 fetch 자체는
master→origin/master만 명시하고 tags/prune/submodule recursion을 끈다.
Git hook과 autostash도 끈다. 기존 HOME/XDG나 운영 환경을 교체·allowlist하지 않는다.

[설명용 예제](../../harness/deploy-config.json.example)를 참고해 운영자가 무시되는
`logs/harness/deploy-local.json`을 소유자 전용 일반 파일 0600으로 준비한다. 예제의 `.invalid`
주소는 실제 서비스 추정값이 아니다. version=1, health_urls(itos/jtos/ktos),
cache_urls(static/application/submodule)만 허용한다. URL은 명시적이어야 하며 인증정보·query·fragment는
허용하지 않는다. health는 HTTP/HTTPS, cache는 HTTPS다. Python/템플릿 변경에는 세 지역 health URL이
전부 필요하다. 설정이 없으면 다른 분기는 실행 가능하지만 출력할 cache URL은 없다.
존재하는 설정 오류와 필요한 URL 누락은 ff 전에 거절한다. URL 값·응답 원문은 결과에 기록하지 않는다.

## 여섯 단계와 실패 경계

1. 고정 `.workflow-lock` → `logs/cron-tos.lock` → `logs/harness/workflows/.lock` 순으로
   nonblocking exclusive flock을 획득해 끝까지 유지한다. `.workflow-lock`의 전체 경로는
   `logs/harness/workflows/.workflow-lock`이다. 기존 inode/owner/mode/content를 유지하고 새 잠금만
   0600으로 생성한다. busy·다른 owner·symlink·hardlink·group/world writable은 변경 전에 거절한다.
   unlink·강제 해제·자동 대기는 없다. dirty/staged/untracked·진행 중 Git operation·submodule
   dirty/unknown/uninitialized도 거절한다. 필요한 master만 fetch한 뒤 old HEAD→target ff 가능성과
   target→fetched origin/master 포함 관계, 정확 commit SHA, 양쪽 트리의 고정 submodule 설정을 확인한다.
   raw diff의 rename/delete 양쪽 경로를 분류하고 migrations 경로 변경은 모두 거절한다.
   migration은 실행하지 않는다. 추가·삭제·rename·타입 변경 등 구조적 submodule 변경도 거절한다.
   공개 GitHub GET으로 repository/fork·정확 SHA와 실제 Actions 필수 3종
   **Offline harness (SQLite), MySQL harness, Chromium browser harness**를 확인한다.
   `git_publish.checks_gate`의 latest run/suite/selection/허용 execution skip 계약을 그대로 재사용한다.
   추가 pending/failure와 commit status도 통과해야 한다. 각 목록은 최대 100개의 **단일 완전 페이지**만
   허용한다(filter=all checks 포함). total_count 불일치·Link·누락·unknown·오류는 거절한다.
   GET은 응답 body 최대 2 MiB, timeout/deadline 10초이며 인증·gh CLI·유료 fallback·재시도는 없다.
2. 새 private 결과 `logs/harness/deployments/<UTC>-<random>.jsonl`을 0600으로 만들고
   파일·부모 디렉터리를 fsync한다. ff 전에 old HEAD·target·master·fetched SHA·분기·CI 근거 digest와
   check IDs·submodule SHA·시각을 기록하고 매 단계 시작/완료/실패를 fsync한다. 비밀·소스·원응답은
   남기지 않는다. 네트워크 확인 후 HEAD·clean·origin을 다시 확인한다.
3. 정확 target 하나에만 `git merge --ff-only --no-edit`를 수행하고 실제 HEAD를 확인한다.
   reset/clean/stash/강제 push/자동 rollback은 없다.
4. IPFUnpacker gitlink가 바뀔 때만 승인된 HTTPS source와 checkout 방식으로 submodule update하고
   정확 gitlink·청결 상태를 확인한 뒤 저장소 루트에서 기존 `make prepare-ipf-unpacker`를 호출한다.
   빌드는 실제 운영 aarch64에서 수행한다. 개발 VM에서 운영 빌드를 실행하지 않는다.
5. 정적 파일 변경 때만 루트에서 기존 `make collectstatic-itos`를 호출한다. Python/템플릿 변경 때만
   itos→jtos→ktos 순서로 각각 `sudo systemctl reload uwsgi@itos`(이후 @jtos, @ktos),
   단 한 번의 `systemctl is-active --quiet uwsgi@<region>`, 설정한 HTTP GET의 200 응답을 확인한다.
   reload timeout은 60초, is-active는 10초이며 HTTP도 위 상한을 따른다. 한 지역 실패면 다음 지역을
   실행하지 않는다. 새 Python/manage.py 명령·환경 체계는 만들지 않는다. 정적만이면 reload 없음,
   submodule만이면 collectstatic/reload 없음, 문서만이면 기록/ff 외 서비스 동작 없음이다.
6. 변경 분기에 대응하는 설정의 명시 URL을 중복 제거해 Cloudflare 수동 캐시 삭제 후보로 출력한다.
   실제 purge API는 없다. 설정에 없는 URL은 추정하지 않는다.

모든 subprocess는 shell=False와 인자 배열이며 Python 3.8 / Git 2.25.1을 대상으로 한다.
명령 timeout/중단 때는 자신이 시작한 프로세스 그룹을 종료·회수하고 후속 단계로 가지 않는다.
이는 소스나 이미 요청된 서비스 동작을 되돌리는 rollback이 아니다. HTTP는 운영 CLI main thread의
일회성 process timer로 DNS·헤더까지 deadline에 포함하고 기존 active alarm이 있으면 거절한다.
main thread의 기존 signal handler는 복원한다.
단계 실패 시 후속 작업을 중단하고 실제 HEAD/submodule HEAD를 남긴다(확인 실패는 unknown).
결과 쓰기 실패도 후속 작업을 막는다. 부분 반영 상태와 결과를 운영자가 검토한 뒤 별도 판단한다.
flock은 협조하는 실행만 직렬화한다. 외부 편집·Git 프로세스를 완전히 차단하는 보안 경계는 아니다.

## 제외 범위와 검증 소유권

improvements.py/improvement_loop.py와 hourly/daily/discovery/unattended 전체 루프는 이번
구현·읽기 범위 밖이다. host-role을 연결하거나 deploy에 해당 환경 marker 탐지·전파·READ_ONLY export·
자동 실행 거절 요구를 추가하지 않는다. 기존 workflow의 worker 실행 금지 정책은 유지한다.
개인 설정·인증·모델·예산·CI·cron·게임 데이터·서비스 unit은 이 PR에서 변경하지 않는다.
운영 명령의 사용 사실은 기존 target 호출 근거이며 실제 settings 공개 요구가 아니다.

`test_host_role.py`와 `test_deploy.py`는 fake Python/Git/make/systemctl/HTTP 및 임시 파일만 사용한다.
실제 make는 guard의 해석 단계 거절과 dry-run 계약만 시험하며 Python recipe는 어떤 harness도
import/실행하지 않는 fixture CLI로 대체한다. production의 보호 11개 각각, development/파일 없음의
허용, marker를 읽지 않는 비보호 goal과 기본 help, -n/--dry-run의 원래 recipe 출력, 병렬·다중 goal과
혼합 호출의 전체 거절을 검증한다. standalone helper 회귀는 make 계약과 별도로 유지한다.
검사 실행·새 의미 검토·full make check·PR/CI3 확인은 workflow/parent 소유다. 매 최종 검토는
최종 코드와 문서 전체의 documentation 판단을 새로 내려야 하며 Markdown 검사만으로 완전성을
증명할 수 없다. 이 문서의 작성 자체는 어떤 검사·CI·운영 실행의 성공 주장도 아니다.
