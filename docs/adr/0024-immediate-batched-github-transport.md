# 0024. Trusted-parent 단일 전송과 workflow 즉시 GitHub handoff

- 상태: 채택(accepted) — 2026-10-20 구현·검증·전달 관측 완료, 문서 전용 PR 성능 관측 대기
- 기록일: 2026-10-20
- 기록 성격: 새 결정
- 대체 관계: 없음. [0005](0005-github-connector-delivery.md)의 게시·앱·CI 경계를 유지한다.

## 문맥

사용자는 게시 준비 직후 바로 이어 실행하고 응답 저장·검증·다음 요청 읽기를 묶되 필수 검증을
유지하며 실제 PR로 소요 시간 차이를 확인하도록 직접 요청했다. 옛 임시 bridge는 응답마다
base64 private 파일 저장 shell, 별도 native accept/stdout 저장 shell, envelope 길이 조회 shell,
4096문자 조각별 shell 읽기를 반복했다. parent의 결과 확인·메시지·도구 전환도 준비 이후 지연에 포함됐다.

parent 제공 PR54 관측 기준은 clean master의 merge `2331700a6b5fb32a5f028133d6daba646a5e6f03`이다.
검증 통과→준비11.448초(그중 git 모델10.848), 준비→첫 GitHub request 저장41.236초,
첫 request→PR 생성52.363초, 총105.047초다. repository/base_ref/base_commit/base_tree3개
(root/docs/docs/adr)/create_tree/create_commit/create_branch/branch_ref/create_pr의11요청이며
앞10회 응답 저장 뒤 다음 accept 결과 기록까지26.552초다. import0.089초,
identity/scope/hash/mode 검증0.043초, 로컬 두 durable JSON save0.016초는 부분 probe다.
이는 parent 관측이며 worker의 실행 성공이나 신규 bridge의 성능 수치가 아니다.

## 결정

`harness/git_transport.py`는 trusted-parent 전용 request/accept CLI/API다. selected active run과
기존 storage readiness/no-follow·v1/no-config/explicit v2 lookup을 따른다. owned0700 transport
디렉터리에0600 regular/nlink=1 응답 파일을 안전하게 저장·fsync·readback한 뒤 exact run/request ID/
saved path로 `git_publish.main` 전체를 호출한다. 검증을 복제하거나 성공을 합성하지 않는다.
origin·scope/hash/mode·approval·CI·project → GitHub lock·journal·cleanup·completion/archive와
옛 CLI 복구 경로를 보존한다. worker/reviewer·child/discovery/unattended는 호출할 수 없다.

응답은 stdin base64 frame의 decoded8MiB UTF-8 JSON 상한이다. 원문은 shell/argv에 넣지 않는다.
native stdout은32MiB까지 private durable 파일로 보존하고 코드·error/status·poll과 다음 요청을
같이 반환한다. 32KiB까지 inline으로 약17KiB create_tree를 한 번에 읽는다. 초과만12288byte
bounded chunk metadata를 반환한다. read-only chunk는 해당 run 최신 완료 결과만 읽고 정확한
offset/count·전체size/SHA256·owner/mode/no-follow/nlink·attachment를 대조한다. 임의 파일 API가 아니다.
잘림·invalid JSON은 새 request/unknown write 재전송의 근거가 아니다.

native 전에 run/operation/request ID/response digest를 묶은 immutable begin receipt와 durable
inflight를 만든다. 완료 receipt와 native journal hash/pending 상태를 대조한다. 중단·중복·변경 응답·
stale ID·불명 private 경로는 fail closed한다. 같은 operation receipt가 있으면 자동 재호출/
재발급/cached next-write 반환을 하지 않는다. parent가 원응답/native journal/실제 connector 결과를
확인하고 기존 CLI로 명시 복구한다. 추가 nonblocking claim으로 begin/응답 저장을 직렬화하고
native 진입 전에 flock을 해제한다. durable inflight가 후속 operation을 차단하며 native lock과
중첩하지 않는다. connector 및 completion/archive network wait에 추가 lock을 잡지 않는다.

`harness/git_bridge.js`는 Codex functions.exec에서 사전 eval하고 parent가 tools/load/store/
artifact/sleep/yield를 주입한다. Node fake 도구에도 같은 모듈을 쓴다. 기존 exact allowlist·도구
존재를 확인하고 request의 arguments를 그대로 실행한다. dispatch 전 ID와 상태를 private store에
등록하고 원응답을 보존한다. connector 예외도 같은 ID의 isError=true로 accept한다. ordinary 응답은
accept shell 한 번으로 저장·native 검증·다음 요청 읽기를 마친다. 큰 응답은 no-echo PTY stdin,
큰 출력만 chunk를 사용한다. PR 관측 즉시 기존 codex_app.attach_artifact adapter를 호출한다.
poll_after_seconds를 지키고 merged/cleanup_*의 다음 proof를 계속 처리한다. awaiting_ci는 기존
explicit resume다. native nonzero·실제 실패·archive pending을 임의 성공으로 바꾸지 않는다.

같은 모듈의 handoff는 이미 시작한 workflow exec의 session/output을 짧은 write_stdin poll로
추적한다. 정상 exit와 마지막 완전한 structured summary·실제 awaiting_github·게시 모드·변경을
확인한 같은 async 흐름에서 바로 request/publish한다. read-only/demo/GIT=0/실패/변경 없음/
불명 summary는 금지한다. 고정 준비 sleep·사람 확인을 추가하지 않는다. sleep은 최대30초 단위,
긴 실행은 yield로 parent가60초 이내 진행을 알릴 수 있게 한다. public 알림에는 stage metadata만 둔다.
도구 없는 단독 make의 awaiting_github와 native workflow의 책임은 바뀌지 않는다.

## 비교 대안

| 대안 | 판단 |
| --- | --- |
| 매 응답 shell 여러 번과4096문자 읽기 | 기존 검증은 유지하지만 parent 도구 전환 비용이 반복된다. |
| bridge에서 검증 복제·cached write 자동 재전송 | 검증 drift·unknown dispatch 중복 위험 때문에 거부한다. |
| 별도 HTTP client·token·daemon | 새 권한·service 운영 비용을 만들므로 도입하지 않는다. |
| native 전체 호출과 private receipt·한 번의 accept | 기존 게이트를 유지하면서 전달 왕복을 줄일 수 있어 선택한다. |

## 선택 이유

줄일 대상은 도구 사이 전달 왕복과 준비 후 handoff 간격이다. 모델·네트워크 속도 개선을 미리
주장하지 않는다. 응답 저장과 native 판단·다음 요청 반환을 같은 호출에 묶어도 origin·승인·CI·
cleanup 검증은 기존 단일 권위에 남는다. 보수적인 receipt는 중단 시 parent 복구 비용을 요구하지만
결과가 모호한 쓰기를 자동 재전송하는 비용을 피한다. 새로운 service/권한/검증 면제가 아니다.

## 결과·비용·제약

private timestamp/duration은 workflow ready·bridge start·각 connector dispatch/response·transport
start/end·PR observed를 기록한다. 원응답의 backend PR created_at와 native progress event를
사용해 같은 구간을 비교한다. public commentary/notify/terminal에 본문·credential·경로·ID를
내보내지 않는다. 세션 store를 잃어도 receipt/native pending이 새 발급을 차단한다. 프로세스
재시작까지 private 작업 상태를 유지할 parent는 durable load/store를 주입해야 한다.

Python3.8 표준라이브러리·기존 Node만 쓰며 package/dependency/service/token/HTTP client/daemon을
추가하지 않는다. 모드·모델·역할·인증·storage·CI·scope·TOOL 정책과 journal schema는 유지한다.
전체 응답/결과·receipt 개수·이벤트 개수 상한은 실패 시 명시 reconciliation을 요구한다.
same-OS-account 침해까지 막는 권한 서비스는 아니다. 원문·복구 증거는 자동 삭제하지 않는다.
PR 생성 전 NFS archive를 추가하지 않고 native의 최종 save·두 lock 해제·completion·archive를 유지한다.

이번 harness 변경의 기존 publisher 회귀와 full `make check` 요구에 대한 구현 PR 관측은 아래에 기록한다.
별도 문서 PR의 검사·required CI·merge·cleanup/archive와 성능은 아직 미관측이다.
synthetic 순서 테스트·부분 probe로 실제 PR 개선율을 쓰거나 미관측 PR/검사/성능 성공을 선기록하지 않는다.

메인은 [구현 PR55](https://github.com/21in7/TavernofSoul/pull/55)의 실제 Codex 구현,
새로운 Claude 의미 검토와 `documentation.updated`, 로컬 전체 `make check` 4786개
(`selected=passed`, skip/failure/error 각 0), 새 전송 계층 집중 검사 60개 통과를 직접 확인했다.
구현 PR의 push/PR 전체 CI와 세 필수 gate success, GitHub `merged=true`와 merge SHA
`7d4e6d443dec56db2df8e4017655eaea09e0a948`, 정확한 작업 브랜치의 `cleanup complete`와
terminal archive `archived`도 메인이 확인했다.

구현 PR에서 큰 stdin 입력은 부모 도구의 자동 승인 검토 한계로 거절됐다. 메인은 native 진입 전
중단된 입력 수신기와 원응답·원요청 ID를 확인해 복구했으며 GitHub 쓰기를 재전송하지 않았다.
이 부모 도구 환경의 `tools.write_stdin` 어댑터는 동일 base64 frame을 4096문자 이하로 분할해
전달한다. 원응답 bytes·request ID·native 저장/검증·receipt·필수 게이트는 동일하며,
입력 조각별 도구 호출 시간도 실제 성능에 포함된다.

PR55에는 이 복구 대기가 있어 PR54와 성능을 직접 비교하지 않는다. 메인은 이 문서 후속 실행을
시작하기 전에 승인된 bridge와 부모 도구 어댑터를 로드하고 workflow 종료를 같은 async handoff로
이어 새 문서 PR의 구간별 소요 시간을 측정할 예정이다. 새 실제 측정은 아직 미관측이며,
위 PR54 기준 105.047초와 구간별 수치는 그대로 유지한다.

## 관련 코드·검증·문서

- [transport](../../harness/git_transport.py), [bridge](../../harness/git_bridge.js), [native publisher](../../harness/git_publish.py).
- [transport 회귀](../../harness/test_git_transport.py), [Node wrapper 회귀](../../harness/test_git_bridge.py), [기존 publisher 회귀](../../harness/test_git_publish.py).
- [parent 호출·복구](../workflow.md#trusted-parent-bridge와-즉시-handoff), [설계 경계](../harness-design.md#trusted-parent-전송과-native-검증-경계), [검증 인계](../harness.md#trusted-parent-github-transport-검증과-운영).
