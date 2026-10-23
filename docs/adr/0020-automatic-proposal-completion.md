# ADR0020: 승인 제안의 증거 기반 자동 완료 전달

2026-10-22 [ADR0027](0027-inspection-lock-isolation-and-diagnostics.md)의 개발 workflow는
모델·검증 동안 source/Store mutex를 해제하되 signed claim과 시작/apply freshness 검증을
유지한다. Git의 최종 source/journal lock 해제 후 완료 hook이라는 순서는 같다. 이 ADR의 원래
signed approval/claim·completed outbox·도입 전 provenance와 unknown 복구를 새 승인으로 재결합하지 않는다.

날짜: 2026-10-19. 상태: 사용자 요청으로 계약/구현 방향 승인; 최종 독립 의미 검토·full make
check·scoped apply·Git 전달 및 메인의 Sites API/UI 구현·배포/HTTP 관측은 별도 대기다.

## 맥락

사용자는 승인한 제안의 작업이 끝나면 웹 보고서에 자동으로 ‘작업 완료’와 PR 링크를
반영하도록 요청했고 별도 정제 completion-v1 전송을 명시 허용했다. 기존 불변 오전 web-v1의
본문/digest/publication journal을 수정하거나 CI/merge/cleanup 완료 조건을 완화할 수 없다.
보고서의 적격 판단과 사람의 승인은 다르며 run_id나 제목만으로 완료 권한을 만들 수 없다.

## 결정

`harness/improvement_completion.py`가 parent-only 완료 검증·private durable outbox·전달/복구를
담당한다. `git_publish.main`의 request/accept/resume/cleanup은 마지막 save 및 project/GitHub
lock 해제 후 lazy import로 정확한 run만 자동 호출한다. Store→project 순서를 사용하는 execute와
역순 deadlock을 피한다. completion 실패는 별도 정제 결과로 남고 passed/merge SHA/cleanup 및
기존 Git CLI 성공 반환을 바꾸지 않는다. 새 모델·승인·execute·Git mutation·cron/tick은 없다.

선택된 root의 private run/report/journal/publication snapshot을 검증하며 legacy local root로
fallback하지 않는다. `validate_journal`을 재사용하고 report.run_id==run_id/status=passed,
github-v1 identity/config/정확한 저장소·번호·PR URL, merged 상태/40lowerhex SHA/done,
원래 CI3 success·verified cleanup_proof의 일치하는 head/merge SHA와 CI3 success 및
cleanup_complete를 모두 요구한다. 각 Store.verify signed claim/approval의 정확한 run 연결,
proposal digest/id·authorization_id·claim 상태·approved decision·허용 edit scope를 persisted
독립 review와 실제 구현 review/documentation/final validation/applied 변경에 대조한다.
현재 source freshness/승인 만료를 재검사하지 않는다. `_authorization`/`_fresh`는 실행 전
책임이며 완료 시 claim 당시 유효구간만 확인한다. 여러 signed claim도 각자 검증해 명시된 일회
bundle과 호환하되 일반 bundle 승인 정책은 신설하지 않는다. claim 없는 일반 run은
키/credential/HTTP 없는 no-op이다. child/discovery/unattended와 read_only/simulated/GIT=0/
local-only는 전달 금지다. 같은 OS 계정 자체의 장악까지 막는 인간 신원 경계는 아니다.

전송은 두 allowlist 계약으로 정밀화한다. 기존 `improvement-web-v1`은 그대로 보존하고
별도 `improvement-completion-v1`은 정확히 version/proposal_id/status=completed/pr_url/
merge_sha/completed_at/digest만 담는다. ID는 IMP-16lowerhex, PR은
https://github.com/21in7/TavernofSoul/pull/양의십진정수, SHA는 40lowerhex다. UTC aware ISO8601
completed_at은 최초 outbox 생성 시 고정한다. digest는 그 외 여섯 필드의 sorted compact canonical
UTF-8 JSON SHA256이다. 사용자 지시·원문·키·절대경로·source/diff/prompt/log는 보내지 않는다.
payload/response 각각 16384 bytes, 기존 private timeout 이하와 기존 `{origin,token}` inbox,
OAI-Sites-Authorization Bearer 및 TLS/no-redirect http_transport를 재사용한다. credential은 메인만 관리한다.

`completions/<run_id>/<proposal_id>.json`의 원자 0600 canonical checkpoint에 payload/digest와
journal을 함께 HTTP 전에 fsync하고 sending을 POST 전에 저장한다. POST 성공만으로 완료가
되지 않으며 GET `/api/completions/{proposal_id}`의 strict schema/digest/전체 payload 일치로만
delivered다. POST는 `/api/completions` JSON 한 건이다. 서버는 proposal ID별 immutable atomic
create-if-absent, same digest 200/different digest 409, absent GET404를 구현한다. browser는 cursor
paginated GET `/api/completions` 목록을 frozen 보고의 proposal_id와 결합하여 완료 표시/PR 링크를
덧붙인다. Sites API/UI 소스·배포는 메인이 별도로 맡고 이 저장소는 실제 HTTP 성공을 주장하지 않는다.

sending/unknown 자동 재호출은 GET만 하며 absent는 unknown으로 남긴다. 메인이 같은 storage로
`make agent-improve-completion RUN_ID=... RECONCILE=1`을 명시하면 GET absent 뒤 동일 frozen
digest POST만 허용한다. conflict는 overwrite/retry하지 않고 delivered는 HTTP 없이 끝난다.
timeout·중단·invalid readback은 정제 unknown reason으로 보존한다. partial progress/crash에도
completed_at/payload를 재생성하거나 승인/claim을 재소비하지 않는다.

## 대안과 비용

오전 보고 수정은 불변 digest와 publication 복구를 깨뜨리므로 채택하지 않는다. title/run 문자열
추정은 서명 승인 연결을 증명하지 못한다. POST 성공만으로 완료 처리하거나 unknown 자동 POST는
모호한 쓰기를 감추므로 채택하지 않는다. 새 scheduler 대신 기존 완료 경계에서 호출하여 정책과
운영 범위를 유지한다. Store sender lock을 bounded HTTP 동안 잡는 단순 설계라 동시 개선 작업은
잠시 보류될 수 있다. strict selected root/record 검증 실패와 서버 conflict는 메인의 조사가 필요하다.

## 검증과 문서 판단

`harness/test_improvement_completion.py`에 signed association/tamper·모드 금지·CI/cleanup 차단,
정확한 wire/durable 상태·failed POST/readback·GET 복구·explicit retry/conflict·멱등·복수 claim·
불변 오전 보고·선택 root/no fallback·자동 hook lock 해제의 offline 명세를 둔다. 기존 GitHub
회귀와 full make check는 실행기가 수행하며 worker는 검사/network/Git/서비스/재위임을 실행하지 않는다.

문서 검토 판단은 `documentation={status:"updated",files:["AGENTS.md","docs/architecture.md",
"docs/harness.md","docs/harness-design.md","docs/improvements.md","docs/workflow.md",
"docs/adr/0020-automatic-proposal-completion.md","docs/adr/README.md"],reason:"실제 수정 Markdown에
두 전송 계약·parent/worker/Sites 책임·완료 증거·lock/storage 경계·durable 실패 복구를 반영했다.
최종 의미적 완전성은 독립 reviewer가 판단하며 Markdown 확장자나 이 기록만으로 승인하지 않는다."}`다.
