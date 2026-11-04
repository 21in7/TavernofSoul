# 0036. 세 지역 cron의 공통 잠금과 종료·알림 정책

- 상태: 승인(accepted), 사용자 승인 B1 정책 결정; 알림 시점·빈도만 [0037](0037-cron-final-notifications.md), 로그 누적 정책만 [0038](0038-cron-log-retention.md)로 부분 대체. 구현 검토·검증·운영 전환 완료를 뜻하지 않음
- 기록일: 2026-11-04
- 기록 성격: 새 결정
- 대체 관계: 알림 시점·빈도만 [0037](0037-cron-final-notifications.md), 로그 누적 정책만 [0038](0038-cron-log-retention.md)로 부분 대체; 아래 결정 본문·과거 기록은 보존하며 다른 B1 정책은 유지

## 문맥

iTOS·jTOS·kTOS는 공통 가상환경과 다운로드·map·파서·import 자원을 사용한다.
지역 간 중첩 실행을 막고 단계 실패·map 경고·알림 전달 문제를 구분할 공통 실행부가 필요하다.
실제 운영 cron과 crontab은 이번 PR에서 읽거나 수정·실행하지 않는다.

## 결정

세 추적 예제는 정확한 지역을 `scripts/run_region_cron.sh`에 전달한다. runner는 자신의 위치로
repo 루트를 정하고 세 지역만 허용한다. 기존 공통 `TavernofSoul/itos/3.8` 활성화와 각 cwd에서
downloader → `python2.7 map_image.py` → `python main.py` → 지역별 `importAll` 순서를 보존한다.
최소 경로·로그 준비 뒤 `logs/cron-tos.lock`의 비차단 공통 flock을 획득하여 EXIT 처리까지
유지한다. 수동 실행도 동일하다. 파일은 삭제하지 않으며 경합은 파이프라인 없이
`skipped_lock`으로 종료하고 flock 자체 오류는 실패로 구분한다.

downloader 0은 계속, 1은 변경 없음 성공 종료로 후속을 생략하고 그 밖의 코드는 실패로 보존한다.
setup·cd·venv·파서·import 실패는 공통 EXIT에서 단계와 원래 코드를 남긴다. 파서 실패 뒤 import는
금지한다. map nonzero는 기록·Discord 경고 후 계속하고 후속 성공은 경고 포함 완료다.
map exit 0의 stderr는 실패로 합성하지 않으며 map 로직은 변경하지 않는다.

mktemp 고유 실행 로그에 stdout/stderr·단계 시간·코드·최종 상태를 보존한다. 실패/최종 시점의
`downloader/revision.csv` 지역 값을 재관측하며 CRLF를 허용하고 불명은 `unknown`이다.
Discord는 환경 변수 `TAVERN_DISCORD_WEBHOOK_URL`만 사용하며 URL·전체 로그를 노출하지 않는다.
단계·원래 코드·지역·revision·로그 경로를 bounded JSON 요약으로 escape하여 전송한다.
curl HTTP 실패 처리·연결 5초/전체 15초 timeout·재전송 없음 정책을 사용한다.
웹훅 미설정과 전송 실패는 최종 로그 상태를 저하시킨다. 원래 파이프라인 종료 코드는 유지하고
map 경고 전달 실패도 후속 실행을 막지 않는다. exit 0만으로 알림까지 완전 성공으로 보지 않는다.

cron 시각 표현은 유지한다. 운영 전환은 PR 밖에서 parent가 별도 사용자 승인 후 비패치 시간에
수행한다. 실제 writer 없음과 공통 잠금 확보 아래 운영 스크립트 교체 및 세 crontab 줄의 바깥
flock 접두사 제거를 함께 준비·검증한다. 같은 inode에 외부·내부 flock을 별도로 중복 획득하면
자체 충돌하므로 둘을 그대로 겹쳐 두지 않는다. 다른 cron 줄과 ktest/twtos는 변경하지 않는다.

## 비교 대안

- 지역별 잠금은 지역 간 공통 자원 충돌을 막지 못한다. 바깥 crontab 잠금만으로는 수동 실행을 보호하지 못한다.
- map 실패 즉시 중단은 map을 경고로 취급하고 후속 파싱·적재를 계속하라는 사용자 승인과 다르다.
- 기존 공유 출력 비교/삭제는 동시 실행의 원인 추적과 로그 보존에 부적합하다.
- import 완료 상태·자동 복구를 함께 도입하면 B2의 별도 상태/복구 설계를 선행하게 된다.

## 선택 이유

내부 공통 잠금은 세 지역의 cron·수동 진입에 같은 경계를 적용한다. 원래 종료 코드와 고유 로그는
실패 원인을 보존하며 map 경고와 전달 실패를 분리 기록하면 성공 상태의 의미를 명확히 할 수 있다.
시각 유지와 별도 운영 승인은 소스 구현·검증과 실제 운영 전환의 책임을 구분한다.

## 결과·비용·제약

지역 간 실행은 직렬화되며 경합 실행은 대기/자동 재시도 없이 건너뛴다. 고유 로그는 누적된다.
revision은 다운로드 관측값으로 import 완료 증거가 아니다. downloader 변경 없음 1에서는 이전
파싱 실패를 복구하지 않는다. import 완료 상태·커서·retry/자동 복구 B2는 2026-11-10 이후 별도 설계다.
collectstatic·unique 제약도 범위 밖이다. 운영 배포 성공은 주장하지 않는다.

세 지역은 복사한 예제+runner와 가짜 단계·activate·revision·curl의 임시 repo에서 실제 Bash/flock으로
검증하고 ktest/twtos는 기존 본문 기반 fixture를 유지한다. 실제 게임 데이터·운영 Python 관리 명령·
네트워크·Discord는 사용하지 않는다. 파일 누락은 skip 없이 실패한다. 이 작업자는 검사를 실행하지 않는다.
최종 전체 diff와 문서 의미에 대한 reviewer의 `documentation={status,files,reason}` 판단 및
parent/workflow의 전체 검사·PR 생성·CI 3개 성공 확인이 필요하며 merge 전에 중지한다.
하네스 실행기·입력·저장소·개발 잠금·게시·자동 검사 선택 정책 변경이 없어
`docs/harness-design.md`는 범위 밖이다. 기존 runner의 제품 Bash fixture만 바뀐다.

## 관련 코드·검증·문서

- [공통 runner](../../scripts/run_region_cron.sh), [iTOS](../../cron_itos.sh.example), [jTOS](../../cron_jtos.sh.example), [kTOS](../../cron_ktos.sh.example)
- [Bash/legacy fixture](../../parser_tidy/tests/test_cron_guard.py), [다운로더 회귀](../../downloader/tests/test_downloader.py)
- [아키텍처](../architecture.md), [격리·알림·운영 전환과 인계](../harness.md#공개-저장소의-운영-알림-설정)
