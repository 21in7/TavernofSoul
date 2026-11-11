# 0041. 완료 오류 receipt와 실제 GitHub 관측의 parent 연결

상태: 사용자 직접 승인 A2d2b PR1 구현안, 새 전체 Claude 검토·parent full make check·실제 CI3 대기.
날짜: 2026-11-11. merge 전 stop/park하며 운영 성공을 주장하지 않는다.

## 문맥

connector catalog가 쓰기를 거절한 오류 응답을 accept하면 완료 receipt와 원 pending write가 남는다.
별도 승인된 동일 요청 전송이나 사용자 UI 작업으로 실제 branch/PR이 생겨도 accept-file은 응답
충돌을 거절해야 한다. 기존 receipt를 고치거나 legacy accept를 우회 호출하면 원 실패와 실제
관측의 구분 및 transport head/journal 검증이 깨진다. 과거 복구 관측은 새 구현의 성공 증거가 아니다.

## 결정

새 make goal은 agent-git-reconcile 하나다. RUN_ID/REQUEST_ID/EVIDENCE_FILE/EVIDENCE_SHA256와
선택적 MINIMUM_WRITE_SECONDS(기본300)를 기존 parent-commands-v1 경계로 전달한다.
CLI·환경·보고서 값은 인간 신원 증명이 아니며 기존 trusted-parent/child 금지·기본 GIT=1과
PYTHON/auth/model 정책을 유지한다. production parse-time 보호 목록에만 goal을 추가한다.

완료 오류 receipt가 있으며 원 결과를 검증할 수 있는 branch/create-PR만 지원한다. immutable
원 stdout에서 request ID/tool/arguments를 찾고 native 구성과 대조한다. 증거는 원 approval/
journal/직전 완료 receipt hash·원 tool/args digest와 정확한 GET URL/status/complete/page/coverage/body를
결합한다. private 단일-open snapshot·hash·UTF-8/중복 키·크기·owner/mode/nlink/no-follow를 재사용한다.
입력 schema와 정확한 명령은 [GitHub 전달](../ops/github-transport.md#완료-오류-receipt의-관측-연결)에 둔다.

branch는 exact ref의 원 pinned SHA를 검증한다. PR은 state=all/head query 전 페이지와 유일한
상세 GET으로 원 repository/base/head ref·SHA와 번호/state/draft/UI metadata 의미를 검증한다.
복수 후보를 선택하지 않는다. matched만 진행하고 absent/mismatch/unknown은 stop한다.
권한/조회오류·불완전 페이지는 부재가 아니다. 증거 누락은 필요한 exact GET을 반환하며 HTTP/
connector 호출·fallback·자동 retry를 하지 않는다. merged 관측은 기존 proof-build/external-merge로 보낸다.

새 operation은 원 GitHub 쓰기 request ID와 구분한다. 원 오류 response/receipt/stdout/stderr/
parent attempt 및 hash를 보존한다. 별도 before snapshot으로 원 journal/report bytes도 보존한다.
새 begin/link는 직전 완료 receipt hash·원 ID/tool/args digest·증거/approval digest·과거 파일 inventory를
고정한다. journal에 operation/link digest를 연결하고 native 순수 accept 검증/저장 API를 사용한다.
이는 legacy CLI 재수락이 아니다. source → GitHub 잠금과 transport claim 아래 durable intent를
먼저 쓰고 journal 전진 → 새 complete/fsync/readback → head 전진 순서로 기록한다.
transport/parent/reader/park/external-merge가 동일 chain을 확인한다. 옛 receipt의 journal hash를 고치지 않는다.

deadline 연장/갱신은 없다. 만료 뒤 관측 연결도 허용하되 다음 요청/descriptor 없이 PR이 있으면
awaiting_ci, 없으면 failed로 멈춘다. 최소300초의 정확한 경계와 검증·저장·export 동안 시간 감소를
확인한다. matched는 CI/merge/delivery 완료가 아니다. 시간 안의 첫 결과만 기존 표준 다음 파일과
parent connector 전송 경로로 이어간다. 실제 CI gate·정확한 expected head·stop_before_merge를 유지한다.

## 비교 대안

- 오류 response를 성공으로 교체하거나 legacy accept를 재호출하면 실패 증거와 완료 identity를 잃는다.
- 새 request ID로 재전송하면 이미 생성된 branch/PR을 중복 생성할 수 있다.
- 명령 내부 GET/retry는 connector의 parent 소유권과 승인 횟수 경계를 바꾼다.
- 광범위 journal 복구는 inflight/부분 실행의 실제 결과를 추측하게 한다.

## 결과·비용·제약

begin 미완료/inflight·legacy 변경·손상·외부 merge 소유 run과 commit/tree 등 미지원 타입은 보수적으로
stop한다. 동일/다른 증거 재호출은 새 연결/재수락/다음 요청 재반환을 하지 않는다. durable intent 뒤
crash/부분 IO는 증거와 inflight를 보존한다. 일반 손상 수리·전송 권한 발급 API가 아니다.
불변 snapshot/inventory 저장과 과거 chain 검증 비용이 늘며 기존 bounded 저장 상한을 적용한다.
기존 게시·merge·cleanup·archive·스케줄·설정·auth/storage·실행 ownership을 확장하지 않는다.
docs/workflow.md, docs/harness.md, docs/harness-design.md, docs/ops/merge-cleanup.md의 역사 설명은
보존하며 이 ADR과 허용 ops 문서가 이번 좁은 추가 계약과 기존 절차의 관계를 설명한다.

## 관련 코드·검증·문서

구현: harness/git_recovery.py, git_transport.py, parent_commands.py, worktree_park.py, Makefile.
합성 회귀: harness/test_git_recovery.py와 test_host_role.py; 기존 publisher/transport/parent/bridge/park
회귀도 parent가 검증한다. worker는 검사·Git·네트워크·workflow·모델을 실행하지 않았다.
parent는 새 전체 diff의 documentation={status,files,reason}을 판단한 검토, full make check,
scoped apply, 표준 next/next-file, catalog 대조와 실제 connector, private response/accept-file,
PR·artifact·Offline harness (SQLite)/MySQL harness/Chromium browser harness 실제 success를 구분한다.
docs 검사에서 승인 밖 문서가 필요하면 해당 경로/이유를 보고하고 중단하며 scope를 확장하지 않는다.
[복구 교훈](../lessons/github-recovery.md)과 [GitHub 전달](../ops/github-transport.md)을 함께 따른다.
