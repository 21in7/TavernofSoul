# 0021. 로컬 작업·검증과 불변 종료 결과 보관

- 상태: 제안(proposed), 사용자 요청 방향 기록; 최종 Claude 의미 검토·full make check·CI·GitHub 전달 대기
- 기록일: 2026-10-19
- 대체 관계: [0011](0011-configurable-harness-storage.md)의 v1 저장 계약은 보존하고 명시 v2를 추가한다. 개발 작업의 NFS active 유지 선택만 대체한다. [0018](0018-storage-check-probe-deduplication.md)의 active readiness/probe와 [0013](0013-owned-validation-temporary-cleanup.md)의 owned-tree 경계는 유지한다.

## 문맥

사용자는 작업·검증을 로컬에서 수행하고 NFS에는 결과만 보관하도록 요청했다. parent가 제공한
관측은 NFS RTT 약 65ms, 20파일 최초 fingerprint 4.205초/로컬 0.002초(64 metadata RPC,
READ RPC 0), 1531파일 prepare 1172초/로컬 1.077초, 구현→review 재검사 334초/로컬
0.131초다. warm fingerprint 0.005초는 cold 비용을 없애지 않는다. 이 수치는 조사 근거이며
최종 구현 성능이나 검사 성공의 증거가 아니다. mount·네트워크 정책을 약화하지 않고 hot path를 옮긴다.

## 결정

### 명시 v2와 접근 시점

설정 없는 기존 동작과 명시 v1 `{version, artifacts, temporary}`를 유지한다. v2는 정확히
`version=2`, `artifacts`, `temporary`, `archive`를 갖고 각 spec은 정확히 `path`,
`required_mount`, `min_free_bytes`를 갖는다. 절대·정규화 경로, 정수 floor(bool 제외),
저장소 ancestry 및 application 간 overlap/required-mount 포함 금지는 공통 계약이다.
archive 파싱은 lexical/type/overlap만 검사한다. archive 경로에 stat·mount·공간·private·symlink
검사를 하지 않아 미마운트/장애가 로컬 작업·승인·검증을 막지 않는다. 실제 archive 접근은
`archive_run`의 ARCHIVE 경계에서만 한다.

v2 프로젝트 work root·artifacts·temporary와 report override는 실제 지원 로컬 filesystem을
요구한다. Linux kernel fstatfs의 양성 allowlist를 사용하며 NFS/CIFS·미지원/미상 filesystem은
거부한다. v2 report는 active artifacts 안에 있어야 하며 로컬이어도 외부 override는 거부한다.
v1 자동 변환·실패 시 fallback은 없다. 기존 local floor·private 0700/0600·no-follow·lock과
인증 runtime 경계는 유지한다. active readiness/status/find_run/progress에는 archive를 추가하지 않는다.

추적 [예제](../../harness/storage-config.json.example)는 local active + remote archive이며
자동 활성화하지 않는다. 실제 private 기본값 전환은 코드 검토·검증 후 parent가 수행한다.
옛 NFS run·absolute journal·snapshot은 이동·재작성·삭제하지 않는다. 원래 v1 config를 private로
보존해 `HARNESS_STORAGE_CONFIG`로 명시 선택하여 조회·재개한다. archive는 active journal의
대체물·재개 근거·일반 status 검색 root가 아니다. daily/hourly/게임 cron과 approval 기록은 변경하지 않는다.

### 종료와 책임 순서

workflow workspace·검증 소스·checks·logs·backup·Git journal은 active local artifacts 아래,
모델 승인 소스 context와 비인증 임시는 local temporary 아래에 둔다. 인증 home·키·원문 모델 응답은
기존 private 경계에 유지한다. terminal 지원 상태는 `passed`, `failed`, `interrupted`,
`demonstrated`이며 상태를 성공으로 고치지 않는다. `awaiting_github`, `awaiting_ci`,
`waiting_for_ci`, `awaiting_connector`, `cleanup_pending`, `needs_reconciliation` 같은 중간
Git 상태는 완료 archive에서 거부한다. Git 성공은 확정 merge와 cleanup complete proof를 요구한다.

workflow는 context cleanup·finished_at·최종 report save와 project lock 해제 뒤 terminal archive를
호출한다. Git request/accept/resume/cleanup 경로는 최종 save → GitHub 및 project lock 모두 해제 →
기존 improvement completion hook → terminal archive 순서다. completion의 전달 책임과 결과는
별도다. claim 없는 일반 run에는 completion 전송이 없다. archive 장애는 기존 passed/merge SHA/
cleanup proof를 보존하고 별도 pending과 nonzero를 노출한다.

`GIT=0`, 실패·중단도 지원 terminal 결과가 존재할 때 보관한다. standalone runner의 `check*`
명령은 v2에서 매 호출 새 `artifacts/checks/<run_id>`를 만들고 그 호출 결과만 보관한다.
workflow 검증 자식은 private 파생 v1 storage config와 child marker를 받아 nested archive를 하지 않는다.
시작/저장 자체가 실패해 terminal report를 만들지 못하면 archive 완료를 보장할 수 없다.

### 결과 allowlist와 실제 구조

archive는 디렉터리 전체 복사가 아니다. 정제 `report.json`(명시 필드만), review가 있으면 생성한
`review.json`, 존재하는 `changes.diff`, `cleanup.json`, 명시 Git 필드만 투영한 `github.json`,
허용된 검증 JSON/log만 포함한다. workflow의 실제 검증 결과 구조는 다음과 같다.

```text
workflows/<run_id>/
  prepare/doctor.json
  prepare/doctor.log
  checks-1/check/check.json
  checks-1/check/check.log
  checks-2/check-docs/check-docs.json
```

`prepare/`는 바로 아래 결과 파일을 읽는다. `checks-1`~`checks-3`는 명령 디렉터리 아래의
허용 stem·`.json`/`.log`만 읽는다. 위 구조는 가능한 예이며 모든 run이 모든 파일을 갖지는 않는다.
`prepare/storage-validation.json` 같은 파생 설정은 결과가 아니므로 제외한다.
standalone은 run 바로 아래 허용 stem의 JSON/log만 포함한다. workspace·`.git`·backup·모델
context/manifest·credential runtime·lock·private config·approval instruction·원문 agent 응답은
포함하지 않는다. raw 응답을 공개 전송하지 않으며 NFS archive도 private 결과 보관이다.

입력은 소유자 일치·0600·regular file·단일 link를 요구하고 no-follow descriptor로 읽으며
읽기 전후와 현재 경로 attachment의 identity·bytes·mode를 확인한다. symlink·hardlink·device·
탈출 경로·변조를 거부한다. JSON projection은 저장 원문 전체 대신 명시 결과 필드로 정규화한다.
개별 결과 상한은 64 MiB, 총 payload 상한은 256 MiB이며 넘으면 잘라 성공시키지 않는다.

### 불변 payload와 원자 공개

로컬 run의 `.archive-build-<unique>`에 `bundle.tar.gz`, `inventory.json`, `manifest.json` 세 파일을
만든다. inventory는 tar 구성원의 정확한 path·bytes·0600·SHA256 순서이고 manifest는 inventory와
압축 bundle의 SHA256·bundle bytes를 담는다. tar는 regular 결과만, 정규화된 mode·uid/gid·mtime으로
생성한다. 전체 구성원·중복·안전 경로·bytes·hash를 재검증한 뒤 별도 `archive-frozen.json`으로
첫 payload digest를 고정하고 `archive-payload/`로 no-replace 원자 공개한다.

원격 `archive.path/<workflows|checks>/<run_id>/`는 `mkdir`의 exclusive 생성으로 확보한 private
0700 결과 디렉터리다. 로컬 `archive-transfer.json`은 첫 frozen manifest, 목적지 경로,
category/결과 디렉터리의 device·inode·kernel mount identity와 임시 이름 token을 고정한다.
receipt의 파일별 published 목록과 committed 상태는 로컬에서만 원자 갱신한다. 이미 기록된
최종 파일이 사라지면 재생성하지 않으며 committed 뒤에는 원격을 읽기 검증만 한다.
기존 목적지가 있는데 receipt가 없으면 빈 디렉터리나 같은 bytes라도 채택하지 않는다.
mkdir 뒤 receipt 저장 전 중단은 소유권을 증명할 수 없으므로 자동 복구하지 않고 pending으로
보존한다. receipt를 지우거나 목적지를 삭제해 강제 재시도하지 말고 parent가 원인을 판단한다.

세 payload 파일은 receipt의 `.transfer-<token>-<filename>`에 최대 1 MiB block으로 전송한다.
매 block과 공개 경계에서 fresh mount/floor·소유자/private·no-follow·디렉터리 attachment/mount
identity를 확인한다. 부분 임시 파일은 정확한 frozen 원본의 prefix와 전체 일치할 때만 뒤에
이어 쓴다. bytes·type·0600·owner·nlink·attachment가 다르면 truncate/overwrite/delete하지 않는다.
완성된 임시 파일을 fsync하고 `os.link`로 각 최종 파일 이름을 no-replace 게시한 뒤 임시 이름을
unlink한다. 기존 이름의 EEXIST는 덮어쓰지 않고 pending이며 다음 명시 재개에서 다시 검증한다.
알려진 임시 이름과 최종 이름이 같은 inode이고 정확한 frozen bytes를 가지며 nlink=2인 경우만
중단된 LINK→UNLINK 전이로 인정한다. 검증 뒤 그 임시 alias만 제거한다. 제3 alias나 임시 이름이
다른 inode이면 거부하며 일반 hardlink 허용으로 확장하지 않는다. 최종 파일은 모두 0600/nlink=1이다.

payload 세 파일의 readback·정확한 inventory·SHA256·tar 구성원을 모두 검증한 뒤, version·kind·
run_id·frozen manifest를 담은 **마지막 `commit.json`**도 동일한 no-replace 파일 링크로 게시한다.
최종 readback은 `verify_archive`로 네 파일만 존재함, marker의 exact bytes와 모든 파일의
0600/nlink=1을 확인해야 한다. `verify_payload`는 로컬 freeze/전송 준비 검사이며 완료 판정이 아니다.
marker 없음·marker의 두 링크 전이·불완전 payload는 완료 결과로 읽지 않는다. marker 게시 후
readback/state 저장 실패도 로컬에서는 pending이고, 재개 시 같은 frozen 결과를 검증해 멱등 완료한다.
알 수 없는 entry·변조·교체된 디렉터리·충돌은 보존하고 자동 재귀 삭제하지 않는다.

**원격에는 directory rename을 사용하지 않는다.** parent의 실제 NFS4 관측에서
`renameat2(RENAME_NOREPLACE)` directory 게시가 errno22/EINVAL이었고, private0600 파일의
no-replace `os.link`는 성공·기존 이름 EEXIST·임시 alias 제거 후 nlink=1·fsync/readback이 관측됐다.
이는 프로토콜 선택 근거다. 후속 trusted parent 보고에서는 최종 archive.py의 실제 NFS 저장·
readback/hash와 동일 결과의 멱등 재개도 성공 관측했다. 일반 개발 pipeline 전체 성공을 뜻하지 않는다.
로컬 freeze에만 Linux directory
no-replace rename을 유지한다. 일반 rename으로 no-replace 보장을 약화하는 fallback은 없다.
NFS durability와 mount 재설정 경쟁 전체의 원자성까지 보장하지 않는다.

재개는 기존 payload와 frozen checkpoint를 검증하고 **현재 terminal 결과 allowlist inventory**를
다시 비교한다. failed→passed, review·Git/cleanup 증거·diff·검증 log 변경은 이전 payload를
새 결과의 보관 성공으로 표시할 수 없다. 전송 뒤에도 현재 결과를 재확인하며 불일치면 pending으로
남기고 로컬 증거를 보존한다. 이미 공개된 옛 payload도 덮어쓰지 않는다. 새 상태를 수동으로
덮거나 payload를 지워 재포장하지 말고 parent가 불일치 원인을 조정해야 한다.

`archive-state.json`과 반환 archive 상태는 payload에 포함하지 않는다. digest가 자신을 포함하는
순환과 상태 갱신 때문에 매번 새 archive를 만드는 문제를 피한다. archive 실패·중단은 로컬 원본,
terminal outcome, merge SHA와 cleanup proof를 보존한다. local state 저장 실패 등은 호출자 오류로
노출될 수 있으며 성공으로 삼키지 않는다.

### 재개와 공간 한계

parent는 같은 storage 설정으로 `make archive-run RUN_ID=... KIND=workflows` 또는
`python -m harness.archive --run-id ... --kind checks`를 사용한다. 모델·검사·Git을 재실행하지 않고
그 run의 보관만 시도한다. CLI는 archived만 0이고 pending/not_configured는 nonzero다. 보관 성공이
failed/interrupted run 자체를 성공으로 바꾸지 않는다. 일반 workflow status는 로컬 archive-state를 읽는다.

완성된 validation workspace·backup·journal의 자동 삭제/이관은 구현하지 않는다. 호출 소유 임시
context의 기존 owned-tree cleanup만 유지한다. exact run 소유권과 복구 증거 보존을 입증하지 못하는
부피 큰 tree는 남긴다. archive 복제 때문에 로컬 사용량이 늘 수 있고 floor 미달은 새 작업을 차단한다.
공간 부족을 숨기거나 무차별 workspace/운영 데이터 정리로 해소하지 않는다.

## 비교 대안과 선택 이유

| 대안 | 판단 |
| --- | --- |
| NFS에 workspace를 두고 metadata 조회만 줄임 | cold prepare·review 비용과 장애 의존이 남음 |
| mount/network 안전 정책 완화 | 격리·floor·실제 목적지 증명을 잃으므로 거부 |
| 전체 run 디렉터리 NFS 복사 | 소스·credential·승인 자료 노출과 작은 파일 RPC 증가로 거부 |
| 명시 v2 local active + terminal 묶음 | hot path와 보관 실패를 분리하고 기존 v1 복구를 보존하므로 채택 |

## 검증과 남은 근거

[test_archive.py](../../harness/test_archive.py), [test_storage.py](../../harness/test_storage.py),
[test_workflow.py](../../harness/test_workflow.py), Git publish/cleanup·runner 회귀는 호환성,
local-only/미접근·pending·경로/권한·partial·충돌·멱등성·prepare 구조·frozen/current 불일치·
hook/lock 순서와 standalone/nested 경계를 검증할 명세다. 원격 rename EINVAL 분리,
부분 prefix 일치/변조, 파일 LINK 전후·마지막 marker 전후 중단, nlink=2 전이와 제3 alias 거부,
완료 readback 실패 후 재개 회귀도 포함한다. 이 문서 작업자는 실행하지 않았다.
이전 run `1792414748889186714-9305b2`는 coordinator CLI 900초 timeout, `applied=[]`였고
복원 초안·미실행 tests는 통과 근거가 아니다. parent가 baseline 동일성과 checkpoint hash를 확인한
것도 준비 증거다. 새 실제 Codex 작업·Claude 의미 검토·전체 `make check`·CI·새 Git 전달 증거가
필요하다. 이번 harness/CI 구현은 [0022](0022-documentation-only-validation.md)의 docs-only 대상이 아니다.

매 review는 `documentation={status,files,reason}`으로 최종 구현과 문서의 의미적 완전성을 새로
판단한다. 범위 밖 문서가 필요하면 exact path와 승인 파일 finding으로 보고하며 자동 열람하지 않는다.

관련 운영 절차: [harness](../harness.md), [workflow](../workflow.md), 책임 설계: [harness-design](../harness-design.md).

이번 복구에 대한 parent 제공 사실: 일반 개발 run `1792416450941994605-2e6132`의 코드 담당
호출은 passed였으나 문서 호출 중 main이 실제 NFS 호환성 결함을 발견해 그 run을 중단했다.
`applied=[]`이며 승인 39개 파일의 private 보존 초안은 구현 준비 자료다. 이 worker는 private
checkpoint를 읽거나 호스트 probe를 실행하지 않았다. 새 실제 Claude 의미 검토·전체 `make check`·
GitHub 전달과 필수 CI는 main이 수행해야 한다. 후속 run `1792417309675138078-0875f6`도 구현·의미 검토
뒤 실제 docs-only 결함으로 full check 도중 중단했으며 applied=[]다. parent가 보고한 실제 NFS 최종
어댑터 저장/readback/hash·동일 결과 멱등 재개 관측은 보존하지만, 이전 의미 검토를 최종 수정의
승인 근거로 재사용하지 않는다. 새 Claude 검토·full check·실제 문서 검사·CI와 Git 전달은 남아 있다.
