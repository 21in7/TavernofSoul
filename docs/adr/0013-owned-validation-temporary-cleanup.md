# 0013. 호출 소유 검증 임시 tree의 안전한 정리와 readiness 경계

- 상태: 제안(proposed), 작업 승인은 있으나 최종 소스의 새 실제 검토·전체 검증·게시 대기
- 기록일: 2026-10-14
- 기록 성격: 새 정리 경계 결정; 최종 실행 성공 기록이 아님
- 대체 관계: 없음. [0011](0011-configurable-harness-storage.md)의 저장 prerequisites를 고유 임시 tree 정리의 고수준 작업 경계로 구체화한다. [0010](0010-automatic-post-merge-cleanup.md)의 Git cleanup은 별개다.

2026-10-16 참조: [0018](0018-storage-check-probe-deduplication.md)의 공간 조회 공유는 각 읽기
경계 안에만 적용한다. 이 ADR의 cleanup 진입/최종 readiness는 독립된 두 fresh 경계로 유지하고,
경계 간 측정 재사용이나 per-entry attachment·owner·kernel mount proof 생략을 허용하지 않는다.
0018의 일상 출력/할당 probe 선택은 이 ADR의 정리 대상·destructive 작업 계약을 바꾸지 않는다.

## 문맥

이전 full workflow는 NFS RPC 대기 중 timeout했으며 old parent `shutil.rmtree`는
readonly keep에서 실패했다. 소유 tree의 디렉터리 접근 복구와 안전한 삭제가 필요하다.
그러나 `root_attached` 안의 `check_ready()`는 파일·ancestor 확인마다 무관한 artifact
NFS mount의 공간/readiness도 조회해 cleanup 비용을 키운다.
전역 prerequisites와 매 삭제의 containment 증명은 서로 다른 책임이다.
속도 때문에 configured mount/floor를 생략하거나 외부 링크를 chmod해서는 안 된다.

## 결정

`temporary_directory`가 만든 **한 고유 비인증 tree의 제거를 한 고수준 filesystem 작업**으로
취급한다. directory 생성/probe처럼 다음 두 경계에서 모든 configured mount/floor를 새로 검사한다.

| 경계 | 새 증명과 실패 결과 |
| --- | --- |
| cleanup 진입 | 첫 chmod/unlink/rmdir 전에 `check_ready()`; invalid readiness면 제거·chmod 0회 |
| 최종 root 제거 직전 | `check_ready()`를 다시 호출하고 attachment를 다시 증명한 뒤 root `rmdir`; 실패면 남은 root를 보존하고 실패 노출 |
| 각 directory chmod, file/link unlink, directory rmdir | root·parent·현재 ancestor·대상 attachment, ownership, no-follow, device와 kernel mount identity를 새로 증명 |

성공한 cleanup의 readiness 조회 수는 파일 수·tree 깊이에 비례하지 않는다.
identity/mount proof는 항목 수·깊이에 따라 계속 수행한다.
여기서 bounded 조회는 configured prerequisites의 mount readiness와 free-space 조회다.
per-entry mount-point 검사와 `mount_identity` 호출 전체가 bounded라는 주장이 아니다.
다음 cleanup은 이전 성공을 재사용하지 않고 진입부터 새 readiness를 요구한다.
정리 도중 global readiness의 연속 관찰이나 공간 예약을 보장하지 않으며 마지막 재검사는
이미 완료한 일부 삭제를 되돌리지 못한다. readiness를 per-entry identity 검사 대신 쓰지 않는다.

할당 직후의 `(st_dev, st_ino)`와 열린 root descriptor를 대조하고 parent도 고정한다.
각 destructive 작업 전 pathname으로 parent를 no-follow 방식으로 다시 열어 할당 당시
parent identity/owner와 대조한다. 공용 legacy `/tmp` parent는 프로세스와 다른 소유자일 수
있지만 그 고정 소유자가 바뀌면 실패한다. tree 내부의 root·ancestor·대상은 항상 프로세스 소유다.
descriptor가 남아 있어도 allocation/root/parent pathname이 교체되거나 detached되면 거부한다.
각 ancestor/대상의 no-follow stat에서 type·device/inode·owner와 mount identity를 확인하고,
열린 directory descriptor도 해당 항목과 대조한다. mount point와 device 변경을 거부하며
kernel mount ID로 같은 device의 bind mount도 거부한다. containment를 넓히지 않는다.

readonly **소유 디렉터리**만 identity가 검증된 descriptor의 `fchmod(mode | 0700)`으로
접근을 복구한다. 이미 접근할 수 없어 안전하게 열 수 없는 directory는 실패한다.
일반 파일은 readonly여도 부모 권한으로 unlink하며 파일 chmod는 하지 않는다.
symlink는 따라가지 않고 그 항목만 unlink한다. 외부 target의 bytes/mode와 hardlink로
연결된 외부 파일의 bytes/mode를 바꾸지 않는다. foreign-owned 항목·외부 디렉터리·mount root는
chmod하지 않는다. 삭제·권한·identity 오류는 숨기거나 fallback하지 않는다.

`FileSystem.mount_identity`는 Linux `statx`의 `STATX_MNT_ID`를 사용한다.
`AT_EMPTY_PATH | AT_SYMLINK_NOFOLLOW | AT_NO_AUTOMOUNT`로 pinned descriptor 또는
descriptor-relative 항목을 확인한다. libc의 statx 부재, kernel 미지원, 호출 실패나
반환 mask에 mount ID가 없으면 `StorageError`로 fail closed한다.
device 번호나 `ismount`만 사용하는 fallback과 host mount/config 파일 열람은 없다.
이 제한 때문에 지원하지 않는 platform에서는 안전한 cleanup 성공을 주장할 수 없다.
검사와 syscall 사이 외부 변경의 모든 경쟁이나 NFS 원자성을 보장하지 않는다.

workflow context는 완료·`awaiting_github`·검토/검증 실패·예외·중단을 포함한 실행 종료에서
이 호출 소유 정리를 수행한다. permanent validation workspace, approved-source manifest,
report·approval snapshot·backup·journal은 유지한다. 실패는 permanent report의
`model_context_cleanup`에 redacted 기록을 남기고 non-success로 노출한다.
정리 또는 report persistence 실패에도 stable local project lock을 해제하며 persistence
오류도 caller에게 전달한다. 남은 context를 cleaned/passed로 기록하지 않는다.

기존 configured NFS 설정·mount·floor는 사용자 최신 선택대로 유지하며 activation 변경이나
로컬 storage override를 제안하지 않는다. 실제 `HOME`/`CODEX_HOME`, global `TMPDIR`,
인증 runtime과 local lock 경계도 유지한다. history·다른 호출의 tree·운영 데이터는 삭제 대상이 아니다.

## 비교 대안

| 대안 | 비용·판단 |
| --- | --- |
| `shutil.rmtree`와 path 기반 chmod retry | readonly 처리에 외부 target/교체 경로의 권한 변경 위험이 있어 제외 |
| 매 파일/ancestor마다 모든 configured readiness 조회 | identity와 무관한 NFS RPC를 반복하므로 제외 |
| process/global readiness cache 또는 cleanup 간 lease | 다음 호출의 장애를 놓치므로 제외 |
| device/ismount만 증명 | 같은 device의 bind mount를 구분하지 못해 제외 |
| 한 tree 작업의 fresh 진입/최종 readiness + 매 작업 identity/mount proof | 원격 prerequisite 비용을 제한하면서 containment 증명을 유지하여 선택 |

## 선택 이유

전역 mount/floor는 한 정리 작업의 prerequisite이며 대상 attachment는 실제 변경마다 필요하다.
두 책임을 분리하면 불필요한 원격 조회를 줄이면서 대상이 호출 소유 tree라는 근거를 유지한다.
고정 descriptor의 directory chmod와 no-follow unlink는 readonly 입력을 지우되 외부 파일의
권한과 내용을 보존한다.

## 결과·비용·제약과 검증 상태

per-entry stat/open/mount proof 비용과 NFS 자체 지연은 남는다. cleanup 실패는 일부 제거된
tree를 남길 수 있으며 원자 rollback은 아니다. operator는 프로세스 종료와 permanent 증거의
복구 필요를 확인한 뒤 별도 승인된 수동 정리를 판단한다. 실패를 local fallback으로 회피하지 않는다.

counting-FakeFS 회귀는 여러 파일 수에서 성공 cleanup의 readiness 경계가 정확히 2회이고
각 configured mount/floor 조회가 bounded인지, per-entry proof는 계속 늘어나는지 확인해야 한다.
이전 cleanup 성공 뒤 새 cleanup 진입의 mount/floor 실패는 unlink/rmdir/fchmod 0회를 요구한다.
최종 readiness 실패도 root 보존과 non-success로 확인한다. readonly·body exception·link/hardlink,
swapped allocation/root/parent·foreign owner·device/mount/bind mount·statx 실패 회귀를 유지한다.
synthetic env/root/FakeFS는 host private 설정·실 mount·인증과 분리하고 기존 테스트/제외를
보존하며 skip/xfail을 추가하지 않는다. 의미 있는 계측은 fixture 준비 뒤 cleanup만 대상으로 한다.
allocation/create/probe의 readiness 조회는 cleanup 계측과 구분한다. root만 있는 empty tree도
성공 cleanup의 진입/최종 2회 경계를 거치며, 새 호출 진입 실패의 0회 mutation 계측에는
unlink/rmdir뿐 아니라 readonly directory의 `fchmod`도 포함한다.

메인이 제공한 2691 selected parser/harness tests zero-skip 통과는 **후보의 부분 검사**다.
이전 timeout/readonly cleanup 실패와 이후 느린 cleanup은 full validation 통과가 아니다.
NFS statvfs probe 회복도 최종 cleanup 성능/성공 증거는 아니다. 이 worker는 검사하지 않았다.
새 실제 review·orchestrator 전체 `make check`·31파일 scoped apply·기본 Git 역할과
메인의 최종 소스 확인·정확한 GitHub 앱 journal·실제 CI 3개 success·merge·cleanup은 대기다.
모든 기존 역할/provider/model과 후속 PAK용 GLM을 보존한다.

## 관련 코드·검증·문서

- [storage.py](../../harness/storage.py), [test_storage.py](../../harness/test_storage.py): allocation·descriptor·readiness·mount proof와 counting-FakeFS 회귀 대상.
- [architecture](../architecture.md), [harness](../harness.md), [workflow](../workflow.md), [ADR 목록](README.md): 저장/정리 경계, 검증 상태와 인계.
- [0011](0011-configurable-harness-storage.md): configured 저장 prerequisites·격리·local lock을 유지함.
- [0012](0012-importer-single-run-snapshot.md): importer snapshot/SELECT의 별개 결정. 장비 Lua batching ADR은 만들거나 index하지 않는다.
