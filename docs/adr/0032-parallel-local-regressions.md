# 0032: 로컬 pytest의 고정 병렬 실행과 전체 결과 증거

상태: 구현안, 새 Claude 의미 검토·parent 실제 측정·전체 검증·전달 대기.
기록일: 2026-10-25.

## 문제와 관측 근거

parent가 baseline `8f5b1b5b59320693eb7d113fc472a19cf7e881f0`의 원래 전체 검사를
실행했다. full check 960.891초, 6056 passed이며 skip/failure/error는 0이었다.
그룹은 downloader129/parser5777/Django regressions67/Django11/pipeline72다.
parser pytest 자체는 748.933초, child는 897.481초였다. pytest 밖 마지막 소유 tree 정리는
148.296초, 그룹 내 다른 정리까지 합하면160.976초였다. test_improvement_loop185.100초,
test_improvements111.527초, test_git_cleanup101.682초 등 독립 테스트 누적이 컸고
가장 느린 단일 테스트는9.441초였다. host CPU2개, wall이 CPU보다 컸으며
`jbd2_log_wait_commit` 저장 확정 대기가 관측되었다. 이 근거로 fsync를 생략하지 않는다.
위 수치는 제공된 baseline 관측이다. PR77이나 이전 실패 초안의 시간을 새 성능 근거로 쓰지 않는다.

## 결정과 책임

큰 parser/harness 그룹만 xdist의 로컬 popen worker 2개·`load` 분산을 기본으로 한다.
각 worker는 독립 Python interpreter와 전체 collection을 가지며 controller는 실행을 분배한다.
`--pytest-workers 1`/`make check PYTEST_WORKERS=1`은 같은 경로·제외·증거 계약의 직렬 비교다.
CLI 직접 비교는 `python -m harness check-parser --pytest-workers 1`, 병렬은 기본값2다.
설치는 기존 `harness/requirements.txt` 절차를 따른다.
1·2 외 값, 원격 execnet 사양, auto/unbounded worker와 외부 plugin 인자를 받지 않는다.
`--max-worker-restart=0`으로 crash를 자동 재실행하지 않는다. 작은 downloader·Django pytest와
Django runner는 직렬로 유지한다. 테스트 항목 삭제·축소·blanket skip·fsync mocking은 없다.

Python3.8 호환으로 `pytest==7.4.4`, `pytest-xdist==3.6.1`, `execnet==2.1.1`을 정확히 고정한다.
xdist3.7부터 Python3.8을 지원하지 않는다. plugin autoload를 차단하고 ambient
PYTEST_ADDOPTS/PYTEST_PLUGINS와 ini addopts를 사용하지 않는다. 명시 controller plugin 객체와
`-p harness.pytest_support` worker bootstrap, 병렬 때 `-p xdist.plugin`만 추가한다.
controller 객체는 worker로 전달되지 않는다. worker는 전체 collection·deselected·종료 상태를
workeroutput으로 보내며 부분 실행을 전체 누락으로 판정하지 않는다.

runner의 기존 run_pytest/_run_pytest/child_check와 `from harness.runner import PytestResults`
API를 유지한다. pytest_support는 실행·bootstrap·집계를 맡고 runner는 지연 import로
docs-only/환경 진단의 stdlib 시작점을 보존한다. runtime 읽기 scope37개와 per-file128KiB/
aggregate1.5MiB 상한은 유지한다. runner와 새 helper는 그37개에 포함되지 않아 코드 이동은
scope 총량 절감 근거가 아니다. scope 문서의 중복 안내를 줄여 짧은 pointer와 Makefile 추가분을
상쇄하며 parent가 baseline 대비37개 총 bytes 비증가·개별/전체 상한을 확인한다.
scope membership·설정·모델·인증·운영 cron은 변경하지 않는다.

## 성공과 JSON 증거 계약

controller가 모든 worker의 complete selected ID 목록·순서 일치를 확인한 뒤 selected를 센다.
worker별 collection event와 종료 metadata도 대조한다. deselected는 worker 간 일치를 확인해
중복 집계하지 않고 기존 EXCLUDED의 실데이터 제외 설명을 유지한다.
선택한 각 ID의 setup/call/teardown을 같은 worker에서 정확히 한 번, 순서대로 받은 경우에만
실제 passed로 센다. skipped/xfail/XPASS·수집 오류·setup/call/teardown 실패·빈 collection·
불일치·누락·중복·알 수 없는 ID·worker crash/nonzero·불완전/잘못된 증거는 실패다.
정상 call 뒤 teardown 실패를 passed로 세지 않는다. exit code0이나 forged passed 숫자만으로
성공할 수 없다. collection이 이미 일치했다면 crash 때도 알려진 selected 수를 보존한다.

기존 runner/status/exit_code/selected/passed/failures/errors/skipped/deselected/excluded와
로그 계약을 유지한다. 부가 필드는 workers, ordered ID의 collection_sha256/passed_sha256,
timing이다. digest는 ASCII JSON 목록의 SHA256이며 전체 ID는 내부 검증에 사용한다.
결과에 전체 ID 목록·원문·환경·credential을 새로 내보내지 않는다. timing은 다음 의미다.

| 필드 | 의미 |
| --- | --- |
| pytest_elapsed_seconds | pytest.main의 controller wall time, worker 시작·collection·종료 포함 |
| test_elapsed_seconds_sum | 받은 모든 test phase duration의 합; 병렬 wall time과 다름 |
| phase_timing_complete | 모든 phase duration이 유효했는지; 잘못된 timing은 합에서 제외하고 판정에 사용하지 않음 |
| slowest_tests | phase 합 기준 내림차순 최대20개 test ID와 elapsed_seconds |
| pytest_cleanup_elapsed_seconds | run_pytest가 할당한 configured 소유 tree의 context 종료 정리; no-config는 할당하지 않아0 |
| pytest_group_elapsed_seconds | run_pytest 전체 wall, 준비와 위 정리 포함 |
| child_elapsed_seconds | child_check가 기다린 전체 subprocess wall |
| cleanup_elapsed_seconds | child_check의 바깥 소유 work tree 최종 정리 |
| group_elapsed_seconds | child_check 시작부터 결과 재작성 직전까지; 준비·실행·로그·정리 포함 |

시간은 판정 기준이 아니다. 직접 내부 API 호출은 바깥 child timing이 없고, 실행/정리 예외면
해당 완료 timing이 없을 수 있다. 예외를 성공 보고로 바꾸거나 정리 실패를 무시하지 않는다.

## 격리와 정리·복구

기존 configured local active/temp, v1/no-config와 basetemp 정책을 유지한다. configured 실행은
storage가 할당한 private 소유 tree 아래 pytest child만 넘긴다. no-config는 기존 pytest/tempfile
기본 선택을 유지한다. xdist가 각 worker에 준 basetemp 아래 private work/tmp를 만들어 cwd,
HARNESS_WORK_DIR, TMPDIR/TMP/TEMP와 tempfile 기본을 worker 프로세스에서만 분리한다.
부모 환경·credential/model context·persistent storage를 바꾸지 않고 tmpfs로 전환하지 않는다.
private cwd는 sessionstart부터 적용되어 테스트 모듈 import 시점에도 보인다. 직렬은 기존 호출
cwd를 유지한다. 따라서 checkout/invocation cwd 기준 상대 경로 읽기·쓰기나 import 시점
Path.cwd()에 의존하는 기존 테스트의 의미가 달라질 수 있다. source 자원은 __file__ 등 명시적
기준으로 접근해야 하며 이를 자동 재작성하거나 checkout으로 fallback하지 않는다.
합성 회귀는 import/runtime cwd·worker tmp 분리와 controller cwd/환경 보존을 확인하지만
기존 parser/harness 전체의 경로 호환성을 증명하지 않는다. parent는 병렬 full check와
PYTEST_WORKERS=1 비교에서 collection/passed ID와 경로 의존 assertion의 의미까지 확인해야 한다.

pytest7.4.4의 tmp_path_retention_policy=failed로 통과한 tmp_path를 일찍 제거한다.
이는 pytest fixture 정책이며 임의 경로를 지우는 새 fallback이 아니다. call 실패·crash의
tmp_path 증거는 pytest 단계 뒤 남는다. pytest의 fixture 판정 시점과 별도 setup/teardown 오류의
정리 순서에는 제약이 있으며 모든 실패 자료의 영구 보존을 약속하지 않는다. 기존 최종
storage.temporary_directory 정리는 남은 호출 소유 tree에 그대로 적용한다. 외부/다른 호출/
사용자 데이터 보존, readonly·symlink·mount·권한·ownership·fresh readiness·실제 fsync·잠금·복구
회귀와 safe cleanup은 유지한다. 실패를 감추는 강제 삭제나 retry를 추가하지 않는다.
os.scandir 등 정리에도 쓰이는 API의 모의는 production 호출·관측·assertion을 모두 포함한
명시적 monkeypatch.context() 블록으로 한정해 pytest tmp_path finalizer 전에 복원한다.

## 비교·비용·검증 인계

직렬만 유지하면 collection/worker 비용은 적지만 독립 테스트의 누적 wall을 겹칠 수 없다.
테스트 축소나 fsync 무효화는 핵심 회귀를 잃으므로 선택하지 않았다. 두 프로세스는 collection을
각각 반복하고 메모리·디스크 경쟁과 plugin 의존성을 늘린다. shared 실자원·순서 의존 테스트는
parent가 실제 full check에서 확인해야 한다. 두 worker도 디스크 대기를 없애지 않으며 속도 향상을
보장하지 않는다. 임시 경로의 실제 정리 시간도 새 관측 전에는 예측하지 않는다.

test_pytest_parallel은 작은 실제 subprocess로 직렬/병렬 ordered ID 동등성·전체 selected/passed,
실패/skip/xfail/XPASS·수집 mismatch/error/empty·worker crash, import/runtime cwd·독립 tmp와 통과 정리·실패 보존을
명세한다. 불완전/중복/순서/소유자 증거의 음성 회귀도 작성한다. test_runner는 stdlib-only docs/
진단과 기존 public import를 다룬다. 저장소 lifecycle stub의 counter-only 성공 기대는 실패로
강화하며 원래 보안/권한 assertion과 다른 모듈 핵심 회귀는 유지한다. 테스트는 작성만 했다.

parent가 의존성 설치, 새 실제 timing 및 baseline6056/추가 회귀 count 구분·zero skip 확인,
기본 GIT=1·새 Claude 의미 검토와 매 review documentation 판단·최종 전체 make check를 수행한다.
동일 환경·같은 소스/항목에서 PYTEST_WORKERS=1과 기본2의 외부 wall 및 그룹 timing을 비교한다.
wall은 외부 실제 시계로 측정하며 누적 병렬 phase 시간과 구분하고 timing을 성공 조건으로 쓰지 않는다.
후속 게시·CI3·merge·cleanup·archive는 기존 parent 허가와 gate를 따른다. 이전 timeout run과
실패 기록은 보존하며 새 검토/측정 전 개선 수치나 최종 성공을 선언하지 않는다.

기존 [0013](0013-owned-validation-temporary-cleanup.md)의 최종 소유 정리와
[0018](0018-storage-check-probe-deduplication.md)의 readiness/probe,
[0031](0031-change-scoped-automatic-validation.md)의 검사 선택·CI 증거는 변경하지 않는다.
사용법은 [harness](../harness.md), 책임 경계는 [전체 설계](../harness-design.md)와
[아키텍처](../architecture.md)를 따른다. parent가 확인한 공식 근거는
[worker/controller 수집](https://pytest-xdist.readthedocs.io/en/stable/how-it-works.html),
[분산/재시작 옵션](https://pytest-xdist.readthedocs.io/en/stable/distribution.html),
[버전 호환](https://pytest-xdist.readthedocs.io/en/stable/changelog.html)이다.
