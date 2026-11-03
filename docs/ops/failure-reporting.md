# 실패와 증거 보고

요약: 실패 뒤 재시도하지 않고, 고정 비교와 실제 종료 결과에 맞춰 확인된 사실만 보고한다.

정본은 `logs/harness/harness-runbook-core.json`이며 충돌 시 runbook core가 우선한다. 공개 요약은 하네스의 기존 native 수정 정책이나 실행 권한을 바꾸지 않는다.

## 종료를 기다리고 멈추는 경계

실행 중인 workflow는 중간에 끊지 않고 종료 상태까지 기다린다. SIGINT와 parent stop-on-failure watchdog을 사용하지 않는다. 실패하면 parent가 workflow·모델·검사를 재시도하지 않고 결과를 보고한다. worker/reviewer도 검사·Git·운영 명령·재위임·workflow를 실행하지 않는다.

native workflow 진입/run ID 생성 전 parent 준비 자체 결함만 예외가 될 수 있다. 모델·검사·seed 반영이 없음을 확인한 경우 수정 후 한 번 재시작하며 원인과 재시작 사실을 기록한다. run ID 생성 뒤 실패는 재시도하지 않는다. 자세한 구분은 [run 수명](../lessons/run-lifecycle.md)에 둔다.

## 고정 기준 비교

parent의 사전·사후 조회는 workflow 밖에서 정확히 같은 `end`를 사용한다. 고정 기준 불일치 또는 입력 digest 변경이면 중단한다. `end` 없는 현재 조회는 참고값이며 고정 비교를 대신하지 않는다. 실제 기준값과 조회 환경은 공개하지 않는다.

증가분은 cutoff 이후 시각이 있는 호출로 전부 설명돼야 정상이다. 일부만 설명되거나 설명되지 않는 차이가 남으면 중단 사유다. 현재 조회의 숫자가 기대와 비슷하다는 이유로 고정 기준의 차이를 무시하지 않는다. 비교가 부족하면 성공 대신 미확인 범위를 적는다.

## 증거 수준에 맞는 문장

정상 종료 결과 없는 호출은 성공으로 세지 않는다. 과거 성공, 작성한 테스트, 실행 준비 상태를 이번 검증 성공으로 표현하지 않는다. commit 날짜·제목으로 확인되는 변경과 사용자가 제공한 실패·복구 관측도 구분한다. 제목만으로 테스트·CI·운영 성공이나 실패 원인까지 검증했다고 쓰지 않는다.

보고에는 확인된 단계와 종료 상태, 직접 확인된 결과, 사용자 제공 관측, 미확인·pending 항목을 구분해 남긴다. 확인하지 않은 PR/run 근거를 만들지 않는다. 준비 단계에서는 검증·CI·게시·merge 성공을 주장하지 않는다. merge가 확인돼도 cleanup/archive가 남으면 전체 완료로 보고하지 않는다.

## 전달 실패와 공개 범위

accept의 READY 누락·불일치, 추가 JSON, 비정상 출력은 fail-closed이며 재accept나 요청 재발급의 이유가 아니다. 이미 수락한 응답을 재accept하지 않는다. 원래 요청과 다음 요청의 연결은 [GitHub 전달](github-transport.md)을 따른다.

credential·토큰 값/저장 위치, private 절대 경로, 내부 state/lock/storage 경로, 운영 DB 접속 정보, 실제 요청 ID·응답 본문을 보고에 넣지 않는다. 원문 로그나 private 실행 설정도 옮기지 않는다. [공개 근거](../lessons/public-evidence.md)의 기준으로 정제하며 정보 부족은 필요한 경로와 이유로 보고한다.

[index로 돌아가기](../index.md) · [merge와 정리](merge-cleanup.md)
