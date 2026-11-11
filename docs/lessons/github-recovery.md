# GitHub 복구 교훈

요약: 거절된 쓰기는 원래 요청에 연결해 조정하고 PR 설명도 승인 검토 대상으로 다룬다.

## 거절된 쓰기의 연결

쓰기가 거절된 뒤 같은 쓰기를 새 ID로 재발급하지 않는다. 사용자 제공 PR #102 관측에서는 사용자가 UI에서 PR을 만들고, parent가 실제 읽기 조회 결과를 원래 요청에 연결해 복구했다. UI 작업의 존재만으로 원래 요청이 자동 완료됐다고 보지 않는다.

이 관측은 같은 작업의 반복 발급이나 이미 수락된 응답의 재accept를 허용하지 않는다. parent는 원래 요청과 단계·도구가 맞는지 확인한다. 실제 요청 ID·ledger 값·응답 본문은 공개하지 않는다. 근거가 모자라면 확인된 상태와 미확인 항목을 보고한다.

[ADR0041](../adr/0041-parent-git-reconcile.md)의 `make agent-git-reconcile RUN_ID=... REQUEST_ID=...
EVIDENCE_FILE=... EVIDENCE_SHA256=... [MINIMUM_WRITE_SECONDS=300]`은 완료 오류 receipt가 있는
branch/create-PR에 한정한다. 원요청의 immutable ID/tool/arguments와 정확한 private GET 증거를
검증해 별도 receipt로 연결한다. 최초 오류·후속 보존 응답·실패 보고를 덮어쓰지 않는다. catalog
거절 뒤 branch가 실제 생긴 형태와 UI에서 유일 PR을 만든 형태는 합성 fixture로 작성하며,
과거 #102 관측을 새 구현의 성공 증거로 사용하지 않는다.

matched 관측과 delivery 완료를 구별한다. absent/mismatch/unknown은 stop이고 absent도
재전송·새 쓰기 ID의 근거가 아니다. 만료 뒤 기록 연결은 deadline 연장이나 다음 쓰기 권한을
주지 않는다. 중복 호출·inflight/부분 IO는 자동 수리하지 않는다. 정확한 입력 schema·판정·receipt
연결·기존 proof 경로와 검증 대기는 [GitHub 전달](../ops/github-transport.md#완료-오류-receipt의-관측-연결)에 둔다.

## 전달 규칙을 유지한 복구

parent는 응답을 권한 0600 파일에 base64 frame으로 쓴다. 줄당 2048자 이하, 끝 줄은 `.`이며 `accept ... --stdin-base64 < 파일`로 전달한다. write_stdin/PTY 입력은 금지한다. 실제 요청·응답 값과 파일 저장 위치는 예시에도 넣지 않는다.

accept stdout 첫 줄이 정확히 `transport-input-ready-v1`일 때만 제거하고 나머지를 단일 JSON으로 파싱한다. 누락·불일치·추가 JSON·비정상 출력은 fail-closed다. 이를 재accept나 요청 재발급의 근거로 삼지 않는다.

`request`는 run 첫 요청에만 사용하고 이후 accept 결과의 다음 요청을 그대로 이어 쓴다. 저장된 다음 요청을 복구할 때는 현재 ledger의 원래 요청·단계·도구를 대조한다. 이미 수락된 응답은 재accept하지 않는다. 전체 운영 절차는 [GitHub 전달](../ops/github-transport.md)을 따른다.

## PR 설명의 정확성

PR 설명도 자동 승인 검토 대상이다. PR #102의 사용자 제공 관측에는 runtime 연구 scope 상한과 개발 workflow 상한을 혼동한 설명 문구가 거절된 일이 포함된다. 두 상한을 구분하고 실제 변경·검증 범위를 정확히 기술한다. 설명을 고쳤다는 사실을 검증·CI 성공으로 표현하지 않는다.

fork의 PR compare 대상은 `21in7/TavernofSoul`이며 원본 저장소로 보내지 않는다. URL 설명도 같은 fork를 기준으로 한다. 이 교훈은 사용자 제공 실패·복구 관측이며 commit 제목만으로 그 원인이나 운영 성공을 재검증했다고 쓰지 않는다.

[실패 보고](../ops/failure-reporting.md) · [설정과 크기](config-and-size.md) · [공개 근거](public-evidence.md) · [index로 돌아가기](../index.md)
