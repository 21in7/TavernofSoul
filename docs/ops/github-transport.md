# GitHub 전달과 응답 연결

요약: parent가 fork 대상과 원래 요청을 유지하며 파일 기반 응답을 엄격하게 수락한다.

정본은 `logs/harness/harness-runbook-core.json`이며 충돌 시 runbook core가 우선한다. 이 요약은 게시 권한이나 복구 정책을 새로 부여하지 않는다.

## 게시 대상과 소유권

PR compare 대상과 compare URL의 기준은 fork `21in7/TavernofSoul`이다. 원본 저장소로 보내지 않는다. 기존 게시 권한·필수 CI를 유지하며 모델은 게시·검사·Git 명령을 실행하지 않는다. credential은 사용자만 다룬다.

PR 설명도 자동 승인 검토 대상이다. PR #102의 설명 거절과 상한 구분은 [GitHub 복구](../lessons/github-recovery.md)를 따른다.

## 파일 기반 응답 framing

parent는 응답을 권한 0600 파일에 base64 frame으로 쓴다. 각 줄은 2048자 이하이며 마지막 줄은 `.`이다. 전달 형태는 `accept ... --stdin-base64 < 파일`이다. 이는 형식 설명이며 실제 요청·응답 값이나 파일 저장 위치를 예시로 넣지 않는다.

write_stdin/PTY 입력은 금지한다. 원문 응답이나 private 실행 설정을 공개하지 않는다. 프레임 준비만으로 외부 작업이나 응답 수락 성공을 주장하지 않는다.

accept stdout의 첫 줄이 정확히 `transport-input-ready-v1`일 때만 그 한 줄을 제거한다. 그 뒤 나머지를 단일 JSON으로 파싱한다. 첫 줄 누락·불일치, 추가 JSON, 비정상 출력은 fail-closed다. 이 실패를 재accept나 요청 재발급의 근거로 삼지 않는다. 정상 종료 결과가 없는 호출도 성공으로 세지 않는다.

## 다음 요청과 복구

`request`는 run의 첫 요청에만 사용한다. 이후 accept 결과의 다음 요청을 그대로 이어 쓰며 임의 생성·재사용하지 않는다. 이미 수락된 응답은 재accept하지 않는다.

저장된 다음 요청은 현재 ledger의 원래 요청·단계·도구를 대조해 복구한다. 대응 관계가 불명확하면 중단하고 확인된 상태만 보고한다. 실제 ledger 값·요청 ID·응답 본문은 공개하지 않는다.

쓰기 거절 뒤 같은 쓰기를 새 ID로 재발급하지 않는다. 사용자 UI에서 만든 PR은 parent가 실제 읽기 조회 결과를 원래 요청에 연결한다. 근거와 제한은 [GitHub 복구](../lessons/github-recovery.md)에 둔다.

## 완료 증거

외부 읽기 조회, 응답 수락, 다음 요청 수신, CI, 머지는 서로 다른 증거다. PR이 보인다는 사실만으로 남은 단계가 완료됐다고 쓰지 않는다. 고정 비교의 불일치와 전송 실패는 [실패 보고](failure-reporting.md)에 따라 보고하며 parent는 workflow·모델·검사를 재시도하지 않는다.

[merge와 정리](merge-cleanup.md)에서 사용자 UI merge와 이후 절차를 확인한다. 공개 범위는 [공개 근거](../lessons/public-evidence.md), 기존 상세는 읽기 승인된 [workflow](../workflow.md)를 따른다.

[index로 돌아가기](../index.md)
