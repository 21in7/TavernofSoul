# 0038. 실행 지역 cron 로그의 엄격한 30일 보존

- 상태: 승인(accepted), 2026-11-04 사용자 직접 승인 결정; 최종 독립 검토·전체 검사·PR/CI3 대기, merge 전 중지
- 기록일: 2026-11-04
- 기록 성격: 새 결정
- 대체 관계: [0036](0036-serialized-region-cron.md)의 고유 로그 누적 정책만 부분 대체; 나머지 B1 정책과 [0037](0037-cron-final-notifications.md)의 B1.1 알림 정책은 유지

## 문맥

세 지역 공통 runner의 고유 실행 로그가 누적된다. 사용자는 2026-11-04 실행 로그의 30일
보존 정책 PR을 승인했다. 기준은 원본 checkout/master `cc879782cf465a96716707619a6bd60dc32f4ac4`다.
보존 정리는 기존 공통 잠금 안에 두고 실패가 운영 파이프라인이나 알림 의미에 영향을 주지 않게 한다.

## 결정

`scripts/run_region_cron.sh`는 iTOS·jTOS·kTOS의 공통 flock 획득 성공 직후에만 실행 지역의
`logs/cron-${region}.*.log`와 일치하는 직하위 일반 파일을 정리한다. 잠금 획득 실패와
`skipped_lock`에서는 정리하지 않는다. 한 실행의 현재 시각을 한 번 고정하고
`mtime < 기준 시각 - 2592000초`인 파일만 삭제한다. 초 미만 정밀도도 비교하여 정확히
30×24시간인 파일과 그보다 새 파일은 보존한다. 현재 `run_log`는 mtime과 무관하게 명시 제외한다.

다른 지역·패턴 밖 파일·잠금 파일·하위 디렉터리와 그 안의 파일·심볼릭 링크와 대상은 보존한다.
탐색은 비재귀이며 링크를 따라가지 않고 삭제 전 stat으로 일반 파일 여부를 다시 확인한다.
후보는 NUL 경계로 전달하고 경로 인용과 `--`로 공백·개행·특수문자 및 파일명 인자 경계를 유지한다.
재귀 삭제나 glob 전체 삭제는 하지 않는다. 삭제 명령이 실제 성공한 파일 수만
`event=log_cleanup region=… deleted=… retention_seconds=2592000`으로 실행 로그에 기록한다.

시간 기준 확보·후보 조회·stat·삭제 실패는 `event=log_cleanup_warning`으로만 남긴다.
시간 기준이 없으면 정리를 건너뛰고, 부분 조회나 개별 파일 실패 뒤에도 가능한 정리를 끝낸 후
정상 파이프라인을 계속한다. 정리 상태는 파이프라인과 격리하여 `status`·`stage_code`·
파이프라인 종료 코드·`map_exit` 및 Discord 내용·횟수를 바꾸지 않는다. 정리 경고만으로
`completed_with_warnings`를 만들지 않으며 B1.1의 변경 없음·경합 알림 0회, 갱신 성공·단계 실패의
공통 EXIT 최종 알림 1회와 기존 단계 실패 정책을 유지한다.

## 비교 대안과 선택 이유

- `find -mtime +30`은 경과 일수를 버리므로 엄격한 2592000초 경계와 다르다. 고정 시각과 mtime을 직접 비교한다.
- 재귀·전역 정리나 glob 전체 삭제는 다른 지역·하위 파일·비대상을 침범한다. 현재 실행 지역의 직하위 일반 파일로 제한한다.
- 별도 스케줄·cooldown·상태 파일은 실행·복구 경계를 늘린다. 기존 잠금 성공 경로에만 정리를 둔다.
- 정리 실패를 단계 실패나 추가 알림으로 전파하면 제품 파이프라인과 B1.1 정책이 달라진다. 경고 로그만 남긴다.
- 무기한 누적은 디스크 사용을 계속 늘린다. 최근 30일과 현재 실행 로그를 보존한다.

## 결과·비용·제약과 운영 반영

정리는 해당 지역의 다음 잠금 획득 성공 때 수행하므로 정확히 30일에 즉시 삭제하는 스케줄은 아니다.
삭제 실패 파일은 남을 수 있으며 조회·삭제 비용은 잠금 유지 시간에 포함된다. 잠금은 공통 runner
진입을 직렬화하며 외부 프로세스의 임의 파일 교체까지 막는 경계는 아니다.
B2/import 복구·지역 추가·전역 로그 삭제·별도 스케줄과 상태 파일은 범위 밖이다.

이번 반영은 B1 초기 wrapper/crontab 전환 기록과 구분한다. 운영 wrapper는 이미 저장소 runner를
exec하므로 사용자 merge 후 기존 native cleanup의 ff-only 동기화로 해당 소스가 갱신되면 반영된다.
별도 wrapper/crontab 교체나 서비스 reload는 필요 없다. 현재 wrapper 연결의 실제 읽기 확인은
parent 책임이며 이 문서 작업자는 운영 파일을 읽지 않는다. 이번 workflow에서는 운영 cron·
실제 로그 정리·운영 파일 직접 실행·배포를 수행하지 않으며 운영 정리나 배포 완료를 주장하지 않는다.

## 검증·검토 인계

기존 실제 Bash와 가짜 단계·curl의 임시 repo fixture에서 세 지역의 삭제 수, 고정 시각의
정확히 30일·1ns 전후, 현재 로그·비대상·링크 보존, 잠금 미획득 시 삭제 0을 검증 대상으로 삼는다.
결정적인 조회/stat/삭제 실패 stub으로 가능한 정리 후 계속 진행과 원래 성공·실패 코드·map_exit·
알림 정책 유지를 관찰한다. root에서 무효일 수 있는 chmod나 flaky sleep에 의존하지 않는다.
운영 경로·운영 로그·실제 파이프라인은 사용하지 않으며 이 문서 작업자는 검사를 실행하지 않았다.

parent/workflow는 기존 모델·설정으로 workflow 1회, 최종 전체 diff의 Claude 독립 검토와
`documentation={status,files,reason}` 판단, full `make check`, PR 게시·실제 CI 3개 success 확인을
수행하고 merge 전에 중지한다. parent 재시도 없이 기존 native bounded repair 정책을 유지하며
merge API는 전송하지 않는다. 하네스 실행기·입력·저장소·개발 잠금·게시·자동 검사 선택 정책은
바꾸지 않으므로 `docs/harness-design.md`와 `docs/workflow.md`는 이번 변경 범위 밖이다.
필수 문서가 승인 밖이면 reviewer는 정확한 경로를 기존 승인 파일의 finding에 귀속해
`changes_requested`로 보고하고 main coordinator가 범위를 확인해 새 run을 준비한다.

관련 구현과 계약은 [runner](../../scripts/run_region_cron.sh),
[Bash fixture](../../parser_tidy/tests/test_cron_guard.py), [architecture](../architecture.md),
[운영 반영과 인계](../harness.md#b1-공통-cron의-운영-전환과-인계)에 둔다.
