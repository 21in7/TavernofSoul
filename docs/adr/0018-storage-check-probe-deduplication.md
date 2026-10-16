# 0018. 한 검사 경계 안의 공간 조회 공유와 실제 목적지 probe

- 상태: 제안(proposed), 최종 소스의 새 독립 검토·전체 offline 검증·전달 대기
- 기록일: 2026-10-16
- 기록 성격: 저장 검사·probe 선택의 새 결정; 성능이나 실행 성공 기록이 아님
- 대체 관계: [0011](0011-configurable-harness-storage.md)의 공간 조회와 준비 시 probe 선택만 구체화한다. 설정·격리·fallback 금지와 [0013](0013-owned-validation-temporary-cleanup.md)의 cleanup 범위는 유지한다.

## 문맥

두 application이 같은 required mount를 써도 각각 공간을 조회하고, status의 진단 조회 뒤
동일 검사를 다시 수행하면 같은 읽기 경계에서 `disk_usage`가 중복된다. 일상적인 출력·임시
준비가 두 application 전체의 `prepare()`를 반복하면 기존의 무관한 root까지 writeability
probe를 수행한다. 원격 저장에서는 이 호출들도 지연을 더한다.
사용자 요청은 기존 NFS 선택과 필수 안전 검사를 유지하며 이 중복을 줄이는 것이다.

## 결정

### 공간 조회의 수명은 한 읽기 전용 검사 경계

경로·mount·소유자 검사와 공간 측정을 분리한다. 한 `_check_ready` 또는 status의 읽기 전용
진단 경계 안에서만 required mount별 측정을 공유한다. 같은 mount를 공유해도 artifacts와
temporary 각각의 `min_free_bytes`를 검사하며 한쪽의 낮은 floor로 다른 쪽을 대신하지 않는다.
서로 다른 required mount는 각각 측정한다. 측정에 연결된 mount의 device/inode가 같은
경계 안에서 달라지면 실패한다. 경로·symlink·nested mount 검사는 생략하지 않는다.

측정과 측정 실패의 공유는 해당 경계에서 끝난다. 다음 public 호출, 별도 mkdir·probe·임시
할당 경계, cleanup의 진입/최종 경계에는 새 검사가 필요하다. 전역·객체 cache, TTL, 시간 간격에
따른 재사용이나 probe 성공 cache를 만들지 않는다. 앞선 성공은 readiness lease나 공간 예약이 아니다.
status의 읽기 측정도 뒤의 probe 쓰기에 전달하지 않는다.

모든 configured mount·각 floor·이미 존재하는 두 private root의 소유자/0700을 **첫 mutation
전에 모두** 확인한다. 이후 실제 쓰기 경계에서도 새로 확인하고 목적지 containment·경로·nested
mount 검사를 수행한다. root 생성 뒤 probe, 출력 생성 뒤 probe, 임시 할당 뒤 probe는 각각
다음 경계에서 다시 검사한다. 두 번째 spec의 장애도 첫 번째 mkdir/probe를 막는다.
올바르게 검증된 기존 디렉터리는 불필요한 mkdir를 시도하지 않는다. 잘못된 mode를 chmod해
통과시키지 않는다. no-follow·고정 descriptor와 고유 파일 생성의 기존 보호는 유지한다.

### probe는 진단 목적과 실제 쓰기 목적을 구분

| 호출 | configured 모드의 probe 대상 |
| --- | --- |
| 명시적 `prepare()` 기본값 | 필요한 두 root를 만든 뒤 둘 다 새로 probe |
| `status(probe=True)`와 CLI `status/doctor --probe` | 두 root가 모두 기존 private 디렉터리여야 하며 각각 새로 probe; root는 만들지 않음 |
| `ensure_directory(path)`와 `resolve … --prepare` | 필요한 root를 준비하고 새 root와 실제 출력 목적지를 probe; 목적지 자체가 새 root면 최종 출력 경계에서 한 번 probe |
| `mkdtemp` / `temporary_directory` 할당 | 필요한 root를 준비하며 새 root를 probe하고, 새로 할당한 실제 작업 디렉터리를 독립 probe |
| `prepare(probe=False)` / `ensure_directory(probe=False)` | 필요한 디렉터리는 준비하되 probe하지 않음; mount/floor/private/경로 검사 유지 |
| `status(probe=False)`와 기본 CLI status/doctor | 읽기 전용; mkdir·chmod·probe 없음 |

일상 준비도 두 configured root의 필요한 생성을 유지한다. 다만 이미 존재하는 무관한 root를
반복 probe하지 않는다. 그 root의 mount·floor·private 상태는 모든 쓰기 gate에서 계속 검사한다.
기존 root의 writeability를 성공했다고 간주하는 것이 아니라 이번 출력 대상으로 사용하지 않는
root의 진단 쓰기를 생략하는 것이다. 두 application 전체의 현재 writeability 확인에는 명시적
`prepare()` 또는 probe 진단을 사용한다.

부모 probe는 자식 writeability의 증거가 아니다. 출력 자식과 고유 임시 작업 디렉터리는 각자의
실제 목적지에서 probe한다. 명시적 override가 configured mount 밖이어도 모든 configured
준비 검사와 목적지의 소유자/0700·symlink 검사를 통과해야 하며, 요청한 probe는 그 override
자체에서 수행한다. probe 대상이 실패하면 성공한 부모나 다른 application으로 우회하지 않는다.
이 선택은 실제 쓰기 목적지의 fresh probe와 새 root의 검사를 보존하면서 무관한 기존 root의
반복 진단만 줄인다. `probe=False`와 미설정 local 기본 동작은 유지한다.

각 probe는 소유 0700 디렉터리에 고유 0600 파일을 배타 생성하고 write·fsync·readback·delete한다.
기존 사용자 파일을 사용하거나 덮어쓰지 않는다. mount 부재/변경·floor 미달·잘못된 소유자/mode·
symlink/nested mount·probe 실패는 fail closed하며 오류는 설정 원문이나 임의 OS 메시지 없이
고정 진단으로 노출한다. 로컬 fallback·자동 remount·새 설정 활성화는 없다.

### 진단·격리·cleanup 계약 유지

public 메서드 서명·반환 형태와 CLI JSON schema는 유지한다. 실패 status도 각 spec의
`mount_ready`, `free_bytes`, `min_free_bytes`를 유지한다. 측정에 성공한 floor 미달 값도 숨기지
않으며 공간 조회 실패의 `free_bytes`는 `null`이다. 읽기 전용 ready는 writeability 보장이 아니다.

기존 NFS 선택·private 설정 bytes/mode·mount options·required mounts·floors를 변경하지 않는다.
보고서 우선순위·legacy 조회·로컬 project lock·credential 격리, 실제 `HOME`/`CODEX_HOME`과
부모의 전역 임시 환경, 모델/provider 설정과 GitHub 게시 정책도 유지한다. 운영 자료·cron·과거
산출물을 이전하거나 정리하지 않는다.

0013의 소유 tree cleanup은 독립적인 진입 readiness와 최종 root 제거 직전 readiness를 모두
유지한다. 각 경계 안에서만 공유 mount 측정이 합쳐지며 두 경계 간 재사용은 없다. 모든 destructive
항목의 attachment·owner·no-follow·device·kernel mount identity proof, statx 미지원 시 fail
closed와 부분 정리 실패 노출은 그대로다. 공간 측정 공유로 per-entry proof를 대체하지 않는다.

## 비교 대안과 선택 이유

| 대안 | 판단 |
| --- | --- |
| 모든 spec/caller마다 disk usage와 두 root probe 반복 | 단순하지만 같은 경계의 원격 조회와 무관한 기존 root 쓰기가 중복됨 |
| TTL·public 호출 간 cache·probe 성공 lease | 다음 쓰기의 mount·공간·권한 악화를 놓칠 수 있어 제외 |
| 부모 probe만으로 자식/override 쓰기 허용 | 실제 목적지의 권한·쓰기 실패를 확인하지 못해 제외 |
| 한 읽기 경계의 공간 공유 + 실제 목적지/새 root probe | 양쪽 floor와 fresh write gate를 보존하며 중복을 줄이므로 선택 |

## 결과·비용·제약과 검증 경계

한 경계의 공간 측정 수는 spec 수가 아닌 서로 다른 required mount 수에 따른다. 기존 private
root에 대한 mkdir와 무관한 probe는 줄지만 경계별 mount/path/stat/open, 필요한 probe의
fsync/readback/delete와 NFS RPC 지연·장애 가능성은 남는다. probe 선택 분리로 분기와 회귀
명세가 늘며 일상 호출은 무관한 기존 root의 writeability 진단을 제공하지 않는다.
전체 workflow의 속도·NFS 서버 회복·지연 상한을 보장하지 않으며 검사와 syscall 사이 외부
경쟁이나 공간의 지속 확보도 보장하지 않는다. 중간 실패는 이미 만든 디렉터리를 남길 수 있다.

[test_storage.py](../../harness/test_storage.py)의 합성 FakeFS 회귀는 공유/별도 mount의 cold/warm
출력·prepare·임시 할당·읽기 status 호출 수, 서로 다른 floor, 호출 간 재검사, 첫 mutation 차단과
다음 쓰기 경계의 악화를 명세한다. 교체/symlink/nested mount, 외부 override 독립 probe,
probe 실패/고유 private 파일 정리, 실패 status 진단과 0013 cleanup proof도 포함한다.
이것은 결정적 operation-count/안전 회귀이며 실제 NFS I/O나 end-to-end benchmark가 아니다.

새 Claude 의미 검토와 최종 소스의 mandatory full offline `make check`(selected skip/xfail 0),
충돌 검사 후 scoped apply는 orchestrator 책임이다. 최종 호출 수 감소와 private 설정 bytes/mode
불변 확인, 기본 Git 역할과 기존 GitHub request/accept·세 required CI의 실제 success·고정 head
squash merge·정확한 branch cleanup은 main/orchestrator의 기존 경계를 따른다. ADR와 회귀
명세의 존재는 이 게이트들의 통과 증거가 아니다.

## 관련 코드·문서

- [storage.py](../../harness/storage.py): 검사 경계·probe 선택·status·소유 tree cleanup.
- [architecture](../architecture.md#하네스-저장-경계), [harness design](../harness-design.md#공유-저장-정책과-실패-경계): 저장 책임과 격리.
- [harness](../harness.md#하네스-저장-경로-설정과-진단), [workflow](../workflow.md#저장-위치와-기존-실행-조회), [ADR 목록](README.md): 호출별 의미와 기존 운영/검증 경계.
