# 0037. 공통 cron의 최종 알림 1회와 로그만 남기는 정상 종료

- 상태: 승인(accepted), 2026-11-04 사용자 승인 B1.1; 구현 검토·검증·실제 운영 배포 완료를 뜻하지 않음
- 기록일: 2026-11-04
- 기록 성격: 알림 빈도 후속 결정
- 대체 관계: [0036](0036-serialized-region-cron.md)의 알림 시점·빈도만 부분 대체; 다른 B1 정책 유지

## 문맥·결정

사용자는 변경 없음·잠금 경합의 반복 알림과 map 경고/최종 결과의 중복 전송을 줄이도록 승인했다.
iTOS·jTOS·kTOS 공통 runner의 `no_changes`(downloader=1)·`skipped_lock`은 정상 exit 0으로
후속 파이프라인을 생략하고 기존 실행별 단계·파이프라인·최종 로그만 남긴다. Discord/curl 호출은
0회이며 웹훅 미설정이나 실패 stub에서도 `notification_unconfigured`/`notification_failed`로
저하시키지 않는다. 실제 갱신 성공과 단계 실패는 공통 EXIT에서 최종 알림을 1회만 시도한다.

map nonzero는 즉시 원래 `map_exit`를 로그에 남기되 중간 알림 없이 main/import를 계속한다.
후속 성공의 최종 메시지는 `status=completed_with_warnings`, 파서/import 등 후속 실패는
`status=failed`이며 둘 다 원래 `map_exit`를 반드시 포함한다. map 경고 없는 성공은 `completed`다.
map stderr만 있고 exit 0이면 실패로 합성하지 않는다. 파서 실패 뒤 import는 실행하지 않으며
후속 실패의 원래 종료 코드를 반환한다. map 경고 뒤 후속 성공은 exit 0이다.

최종 메시지는 최종 상태·단계·원래 코드·지역·revision 관측값·고유 로그 경로·map 결과를
bounded JSON으로 escape하여 보낸다. 웹훅은 기존 환경 변수만 사용하고 비밀값·전체 로그를
노출하지 않는다. curl `--fail`, 연결 5초/전체 15초 timeout, `--retry 0`을 유지한다.
전송 대상 실행에서 웹훅 미설정은 전송을 생략하고 `notification_unconfigured`, 전송 실패는
`notification_failed`를 최종 로그 상태에 기록한다. 파이프라인 원래 exit는 두 경우 모두 유지한다.

## 비교 대안·비용

- 매 실행 알림은 변경 없음·경합에서도 반복 전송을 만든다.
- map 오류 즉시 알림과 최종 알림을 함께 보내면 한 실행에서 두 번 전송한다.
- map 오류 시 중단하면 후속 파싱·적재를 계속하는 승인 정책을 바꾼다.
- 외부 이벤트/DB/상태 파일·날짜별 suppression·cooldown은 별도 상태와 복구 부담을 추가한다.

선택한 통합 알림은 실행당 전송을 줄이지만 map 오류의 Discord 통지는 후속 단계가 끝나
공통 EXIT에 도달할 때까지 지연된다. 오류 로그는 즉시 보존한다. 재시도나 추가 알림 경로는 없다.

## 범위·검토·운영 경계

제품 runner의 알림 조건·map 중간 알림 제거와 기존 Bash/가짜 단계·curl fixture 및 관련 문서만
변경한다. 공통 flock inode·전체 단계와 EXIT까지의 수명·고유 로그·단계 코드·revision 관측은 유지한다.
외부 상태·이벤트·suppression·cooldown·재시도·cron 시각 변경을 추가하지 않는다.
import 완료 상태·커서·자동 복구(B2)는 2026-11-10 이후 별도 설계이며 collectstatic도 제외한다.
하네스 실행기·입력·저장소·개발 잠금·게시·자동 검사 선택 정책은 바꾸지 않는다.

실제 운영에는 배포하지 않았다. 운영 전환은 [기존 별도 승인 절차](../harness.md#b1-공통-cron의-운영-전환과-인계)를
유지하며 이번 작업에서는 계획 보고만 한다. 운영 cron/crontab·실제 파이프라인·Discord 호출은 금지한다.
worker/reviewer는 검사·Git·게시·운영·네트워크·재위임·workflow를 실행하지 않는다.

최종 Claude는 새 전체 diff와 문서 의미를 독립 검토하고 매 검토에서
`documentation={status,files,reason}`을 새로 판단한다. 기존 승인이나 문서 확장자 검사를
의미적 검토 대신 사용하지 않는다. parent는 #112/#113 UI squash merge·external cleanup 완료를
확인하고 원본 checkout/master `9c086dc2cc4f3c6b36690a810c1b8a88b3727879` 기준으로 기존 모델·설정의
workflow를 1회만 진행한다. full `make check`·PR 생성·CI 3개 success 뒤 merge 전에 정지한다.
실패 후 parent 재실행 없이 기존 native bounded repair 정책을 유지하며 merge API는 전송하지 않는다.

## 관련 문서

- [현재 실행 계약](../architecture.md), [알림·검증·운영 인계](../harness.md#공개-저장소의-운영-알림-설정)
- [기존 B1 결정](0036-serialized-region-cron.md), [ADR 인덱스](README.md)
