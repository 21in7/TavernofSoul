# ADR0035: 제품 scope와 교차 경계 검토 활성화

- 기록일: 2026-11-02
- 상태: 사용자 실행 승인. 새 Claude 전체 diff 의미 검토·parent full check/scoped apply·PR/CI3 대기.
- 운영 관측: 적용 전후 state와 다음 정상 tick·새9단계/최종 reviewer 성공은 이 leaf에서 미관측.

## 결정과 책임

PR-0의 35개 연구 scope를 [improvement-scope.txt](../../harness/improvement-scope.txt)의
정확한 제품37개 경로와 순서로 전환한다. 이 파일이 목록의 기준이며 경로 문자열의 추가는
현재 개발 모델에 제품 소스 읽기를 승인하는 행위가 아니다. 제품 코드·테스트·역할 AGENTS와
`docs/data-contracts.md` 자체는 이번 변경에서 편집하지 않는다.

B′의 `shared_files`는 `docs/data-contracts.md` 하나다. PR-1이 제공한 선택 계약 C를
운영 `coordinator_cross_boundary_files`로 활성화하며 목록과 순서는 다음과 같다.

1. `TavernofSoul/ipfparser/contracts.py`
2. `TavernofSoul/ipfparser/management/commands/importAll.py`
3. `parser_tidy/DB.py`

이 세 경로는 scope 안의 비공유·비coordinator 소유 제품 프로그램이어야 하며 기존
`validate_config` 의미 검증을 그대로 사용한다. coordinator는 세 프로그램과 공통 계약
문서만 읽고 다운로드→파싱→계약→적재 사이 입력·출력 계약 문제만 제안한다. downloader,
parser, django의 읽기·후보 범위를 임의 확장하지 않는다. reviewer는 별도 격리 사본에서
전체 승인 scope를 검토한다. 실제 실행 소유권은 `workflow.owner()` 그대로다. DB.py는
parser, contracts.py/importAll.py는 django, 공통 문서는 coordinator가 편집한다.

## 실제 검토와 표본 한계

후보 유무와 무관하게 최종 Claude reviewer는 최소1개 교차 프로그램 본문 window를 실제
Read하고 assessment해야 한다. 문서·헤더·coordinator 자기 보고·local 초안·specialist의
Read만으로 완료를 인정하지 않는다. 빈 후보일 때 coordinator 자체 프로그램 표본 하나만
교차 window로 대체하며 downloader/parser/django 비공유 프로그램 표본과 문서 판단·Read는
계속 필수다. 후보가 있으면 기존 evidence·문서 Read에 교차 window를 더한다.

교차 window도 병합 후 최대96줄, 전체 MAX_WINDOWS 32·MAX_SOURCE 32768B 합산에 포함한다.
기존 Read pairing·bytes·ranges·Capture와 위변조 거절을 유지한다. 한 표본은 전체 파일이나
표본 밖의 결함 부재를 보증하지 않는다. 매 최종 Claude 검토는 최종 diff에 대해
`documentation={status,files,reason}`를 새로 판단한다.

## 의도한 제외와 대안

scope에서 제거한 하네스 파일은 더 이상 유효한 후보의 근거나 편집 대상이 아니다. 이는 제품
계약 검토에 연구를 집중하려는 의도된 하네스 제안 제거다. 과거 제안·실패·승인과 frozen
오전 보고는 보존하며 PR-0/PR-1 및 기존 ADR의 수치·실패·관측을 다시 쓰지 않는다.

기존 혼합35개 scope 유지는 하네스 제안을 계속 생성하므로 채택하지 않는다. shared5개
유지는 제품 검토에 불필요한 공통 문서를 남기며, coordinator에 모든 제품 파일을 주는
대안은 읽기 경계를 넓힌다. 교차 읽기를 편집 소유권으로 바꾸는 대안도 기존 역할 배정을
깨므로 채택하지 않는다. 문서나 자기 보고만 받는 대안은 실제 본문 검토를 입증하지 못한다.

9단계·호출 수·96줄과 source/context 상한·역할·timeout·모델·인증·예산·스케줄·개별
승인/실행 scope·서명·claim은 유지한다. 기능 코드는 변경하지 않는다. 두 lab fixture와
byte ceiling 합성 테스트는 각각 기존 shared5개를 명시하고 C 필드를 제거해 기존 합성
설정만 고정한다. 공용 helper·후보·Read·문서-only 거절·기존 C 전용7개 사례는 유지한다.

## 신선도와 전환 절차

scope/config 변경은 다음 정상 tick의 control 비교에서 진행을 무효화하고 호출 도중 변경은
기존 호출 후 검증에서 거절한다. 기존 eligible/승인은 새 구성에 재사용할 수 없다. 미확정
오전 선택은 현재 전체 dependency가 일치하는 완료 회차만 사용한다. 제품 파일 하나의 변경도
전체 `source_fingerprints` 신선도에 영향을 주며 scope 밖 control 설정 fingerprint도 유지한다.

다음 절차는 parent의 승인된 실행 책임이다. leaf의 작성은 검증이나 적용 증거가 아니다.

1. 승인된 runbook과 PR #102 squash merge `63aceab8d4051811e695d5c6b19bb5d20c664bc4`,
   cleanup/archive/readback 및 clean master를 재확인한다. TASK/FILES UTF-8 bytes·SHA256·0600과
   개별 범위를 기록하고 준비 코드가 참조하는 설정 경로의 존재부터 확인한다. local 설정은
   `logs/harness/local-model.json`이다.
2. workflow 직전 loop state를 읽기만 하여 관측 시각·bytes/hash/mode와 `scan_id`,
   `stage_index`, `last_slot`, `inflight`, `high_water_at`, `current_fresh_at_last_tick`,
   `dependency_digest`, report의 `loop_dependencies` 및 scope/config/workflow/loop/local/agent
   설정 fingerprint를 private 기록한다. 원문·credential은 모델/public 보고에 보내지 않으며
   조회를 원자적 정지로 간주하지 않는다.
3. 현재35개와 예정37개 각각 존재·중복·순서·bytes·mode와 파일별 최대·총합·여유를 측정한다.
   정확히37개, 파일별<=131072B, 전체<=1572864B와 shared1개·교차3개의 의미 검증을 확인한다.
   준비 시 843729B·여유729135B·최대82333B는 참고값이며 적용 시 다시 측정한다.
4. 기본 Make Python/GIT=1과 기존 workflow로 새 Claude 전체 diff 의미 검토→full make check→
   scoped apply를 수행한다. 적용 직전 state와 합계·여유·37개 상한을 별도 재기록하고 기존
   source mutex·전체 baseline 충돌 검증으로 승인 세트만 적용한다. source busy·외부 편집·검증
   실패는 기존 fail-closed 경계를 유지한다. state/lock/cron 수동 수정·잠금 삭제·모델 종료는 없다.
5. 적용 직후 state·scope/config bytes/hash·역할 범위와 실제 `load_config` 의미 검증 결과를
   다시 기록해 전환 시점을 구분한다. 이번 보고는 apply 시점까지의 state 기록만 포함한다.
   다음 정상 scheduler tick은 PR merge 이후 별도 단계로 durable state/history를 읽기만 하여
   control 변경 무효화·새 dependencies/scope37/B′/교차3개·stage/slot을 관측한다. 강제 tick·추가
   scan·별도 모델 호출·오전 보고 재생성은 없다. 예산/quota/source busy로 보류되면 실제 이유와
   미관측을 남기며 전체 새9단계나 최종 reviewer 성공을 관측 전에 주장하지 않는다.
6. runbook 고정 cutoff 사전/사후 비교와 기존 Git 역할→PR 생성→CI3 실제 success를 확인하고
   merge 전에 멈춘다. GitHub 응답은0600 파일 리다이렉션만 사용하며 write_stdin/PTY 입력이나
   이미 생성한 쓰기 요청 재발급은 하지 않는다. 실패 시 workflow·모델·검사를 재시도하지 않고
   최초 실패와 원인을 보고한다.

`_reconcile`, archive 순서 버그와 제안별 freshness는 계속 제외한다. private config/credential/
state/lock/cron/서비스는 편집하지 않는다. PR-1 설계 기록은 보존하고 현재 운영 활성화는
이 ADR과 운영/경계 문서에서 설명한다. PR/CI 성공과 실제 운영 tick 성공은 각각의 관측으로만
기록하며 현재 문서 작성이나 과거 성공을 이번 운영 성공으로 대체하지 않는다.
