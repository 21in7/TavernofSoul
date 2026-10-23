# 0028. 재개 성공 결과의 명시적 추가 보관

- 상태: 사용자 직접 승인 구현안, 새 독립 의미 검토·full make check·scoped apply·전달 대기
- 기록일: 2026-10-23
- 관계: [0021](0021-local-work-and-result-archives.md)의 최초 보관·동일 payload 재개·변경 결과 거부는 유지한다. 변경 결과를 보존할 명시 경로가 없던 부분만 추가한다.

## 문맥과 결정

parent가 보고한 기존 run `1792668297212265849-6986a9`는 전달 기한 초과로 failed 결과를
먼저 정상 보관했다. 이후 사용자의 재개 지시에 따른 전달 창 조정과 기존 Git 경로에서 PR66의
CI 3종·merge `d5c7072d94d7df5654d173ffa120d3eb9ddfaf19`·cleanup complete·passed가
관측됐다. 첫 frozen 결과와 달라 일반 archive 재개는 거부했다. 이는 과거 관측이며 이번 구현의
검증 성공이 아니다. 옛 실패를 지우거나 덮거나 성공으로 재명명하지 않는다.

trusted parent가 **정확한 원래 run**을 지정한 archive-only 호출에서만 failed→passed 결과를
추가 보관한다. workflow 실행·모델·검사·Git·approve/execute·스케줄·보고·설정 호출은 없다.
v1/no-config와 일반 `archive_run`은 그대로다. checks·실패 후 다른 실패·새 review/diff/검증은
이 복구 대상이 아니다. 기존 실패 보관이 committed receipt와 원격 readback까지 완료돼야 한다.

## identity와 불변 경계

원래 run에 고정 세대 `resumed-v1` 하나만 허용한다. 로컬 `archive-resumed-v1/`에는
불변 `recovery.json`, 별도 payload/frozen checkpoint/transfer receipt와 가변 archive-state를 둔다.
원격 목적지는 `archive.path/workflows-resumed-v1/<원래_run_id>/`다. 원래
`workflows/<run_id>/`의 네 파일·entry·commit과 로컬 최초 payload/checkpoint/receipt는 읽기만 한다.
네 파일만 허용하는 옛 verifier에 새 entry를 넣지 않는다. 성공 payload의 run_id도 원래 값이다.

private recovery record는 intent·세대·원래 run 경로/device/inode/mount identity·이전 manifest와
그 canonical SHA256·이전 receipt SHA256·현재 terminal allowlist inventory와 SHA256·별도 목적지를
결합한다. 재개 시 현재 증거에서 다시 만든 record의 **exact bytes**가 같아야 한다. record를
바꿔 다음 결과를 채택하거나 새 세대를 자동 생성하지 않는다. 같은 run의 기존 `archive.lock`
아래 최초 보관과 추가 보관을 직렬화한다. busy는 pending이며 잠금 삭제/재시도는 없다.

## 허용 전이와 실제 증거

이전 report는 failed, Git 결과는 merge 전 failed여야 한다. 현재 report는 passed이고
read_only/simulated/no_git는 false, github_enabled는 true여야 한다. report의 status·github·
finished_at·error_type 외 allowlist 필드는 최초 보관본과 같아야 한다. 특히 원래 scope·applied·
review·validation selection·delivery validation을 변경할 수 없다. report/github/cleanup 외
inventory는 추가·삭제·변경 모두 거부하므로 diff·검증 JSON/log·review도 고정된다.

승인 review와 documentation 판단, 실제 적용 범위, positive selected/passed·zero skip/failure/error
검증 요약을 요구한다. 검증의 report 경로는 원래 run의 checks-1~3 아래 정확한 command JSON이어야
하고, 실제 JSON의 passed/check groups가 요약과 같아야 한다. 원래 Git run_id·branch/version과
이미 고정된 head/PR/base 연결을 유지한다. 현재 ledger/report는 merged/done, 유효 SHA, PR,
CI 3종 success, 동일 SHA/checks의 verified cleanup proof를 서로 대조한다. 원래 cleanup.json의
run/head/merge와 ledger의 remote/local/prune/sync/completion complete도 일치해야 한다.
중간·unknown·cleanup_pending이나 단순 status 변경은 성공 근거가 아니다.

전송은 0021의 result allowlist만 사용한다. recovery record는 로컬 private 증거이며 원격 bundle에
추가하지 않는다. source·credential·승인 지시·모델 원문·private 설정은 전송하지 않는다.
active report/Git/cleanup/review/validation을 보관 목적에 맞게 수정하지 않는다.

## 중단·변조와 관측

기존 owner0700/0600·no-follow·single-link·containment·mount/floor·bounded size/hash/attachment
검증과 최대1MiB 전송·동일 prefix 비교·no-replace 파일 link·마지막 commit/readback을 재사용한다.
이전 receipt/destination/commit을 읽기 검증한 후에만 추가 전송한다. 충돌·receipt 없는 디렉터리·
unknown entry·marker 변조는 채택/삭제/덮어쓰기하지 않는다. 복구 디렉터리 mkdir 뒤 record 저장 전
중단도 자동 채택하지 않는다. receipt 생성 전 원격 mkdir 중단은 기존처럼 pending으로 보존한다.

freeze·partial·LINK/UNLINK·commit/readback/state 저장 중단의 증거는 유지한다. 같은 명시 명령은
고정 record와 같은 결과만 재개하며 새 모델/검사/Git/세대를 만들지 않는다. 전송 전후 현재 inventory와
이전 보관 연결을 다시 검증한다. 도중/이후 결과 변경은 pending이며 옛 payload를 새 성공으로 쓰지 않는다.
이전 merge/cleanup proof는 archive 장애로 무효화하지 않는다. fallback storage·자동 재시도는 없다.

workflow status는 NFS를 조회하지 않고 로컬 최초 상태를 `archive_original`, 현재 복구 상태를
`archive`로 구분한다. 현재 inventory가 record와 다르거나 상태 증거가 없으면 pending으로 표시한다.
과거 일반 재시도의 최초 state가 pending이어도 recovery record는 이전 manifest의 failed와 현재 passed를
별도로 식별한다. 로컬 status는 원격의 현재 무결성 증명이 아니다. 명시 CLI의 전체 readback만 완료
증거이며 archived만 종료값0, pending/not_configured는 nonzero다.

CLI 옵션/환경 marker는 인간 신원을 증명하지 않는다. 호출 권한은 trusted-parent 실행 경계의
책임이다. worker/discovery/unattended·READ_ONLY=1·GIT=0은 storage resolve/접근 전에 거부한다.
로컬 private 원본이 동시에 적대적으로 통째로 위조되지 않았다는 기존 신뢰 경계가 남으며,
과거 CI/merge를 네트워크에서 다시 인증하거나 현재 Git 상태를 재검사하지 않는다. 외부 편집/마운트
경쟁 전체에 대한 원자성·NFS durability까지 보장하지 않는다.

## 운영 명령과 인계

parent는 같은 선택 storage·인터프리터에서 원래 run을 지정한다.

```bash
python -m harness.archive --run-id 1792668297212265849-6986a9 --kind workflows --resume-failed-to-passed
```

동일 명령이 명시 멱등 재개다. 일반 `make archive-run RUN_ID=... KIND=workflows`는 여전히 변경
결과를 거부한다. 실패 시 원본/receipt/잠금/목적지를 지우지 말고 보존한다. CLI는 active 결과를
바꾸지 않는다. status/find_run/progress에 archive 검색 root를 추가하지 않는다.

[회귀](../../harness/test_archive.py)는 disposable FakeFS와 기존 shared offline guard 아래
failed 최초 보관→합성 Git 성공/cleanup 증거→추가 보관→동일 재개의 원본 bytes/mode/inode/entries,
성공 증거·기본명령 거절·불충분/위조 연결·중단/동시성·storage 경계·partial/commit/current 변조·
allowlist·child/discovery 거절을 명세한다. worker는 실행하지 않았다.

기존 Jev 판단/필요 시 Codex 계획 뒤 coordinator 구현의 **최종 코드와 문서를 새로 읽는 새 Claude**가
`verdict,summary,findings,documentation`을 판단한다. finding은 file/severity/message 세 키,
documentation은 status/files/reason이며 누락은 승인 파일 finding으로 changes_requested다.
parent/orchestrator가 기본 GIT=1의 **full make check**, scoped apply, 기존 Git 역할을 수행한다.
실제 기존 run의 추가 보관/readback/원본 불변 대조와 구현 PR의 CI3/merge/cleanup/archive는 별도
잔여 단계다. 이44개 모델승인은 runtime 연구37개 scope·파일128KiB/전체1.5MiB 상한을 늘리지 않는다.
