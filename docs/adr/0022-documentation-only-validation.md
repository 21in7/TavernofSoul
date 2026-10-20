# 0022. 실제 최종 변경에 결합한 문서 전용 검증과 CI gate

- 상태: 채택(accepted), 2026-10-20 구현·검증·전달 완료 (메인 제공 관측 근거는 아래 기록)
- 기록일: 2026-10-19
- 부분 대체: 2026-10-20 사용자 직접 요청에 따른 [0023](0023-new-branch-documentation-validation.md)이 새 브랜치 zero-before의 무조건 full 결정만 대체한다. 아래 해당 문단은 당시 결정의 역사이며 다른 docs-only 정책은 유지한다.
- 정밀화: [0004](0004-reviewed-and-validated-publication.md)의 필수 검증 선택과 [0005](0005-github-connector-delivery.md)의 CI 실행 경로. 승인 범위·모델·branch protection·GitHub 권한·lock·merge/cleanup 완료 계약은 유지한다.

## 문맥

parent의 조사에서 문서 13줄 수정도 coordinator의 full check로 643초가 걸렸다. 사용자는 문서만
바뀔 때 필요한 문서 검증을 요청했다. 파일 읽기 scope나 모델의 docs-only 주장으로 검증을 줄이면
코드·정책·실행 mode 변경이 빠질 수 있어 실제 변경 증거를 선택 권위로 삼는다.

## 결정

### 로컬 선택과 최종 후보 결합

workflow는 새 reviewer 승인 후 전체 로컬 baseline→candidate manifest의 실제 차이를 분류한다.
읽기 scope에 참조 코드가 있어도 변경이 prose뿐이면 docs-only가 가능하다. scope가 Markdown뿐이어도
정책·mode·type 변화나 불명 증거면 full이다. 허용 prose는 루트 `README.md`와 `docs/**/*.md` 중
`AGENTS.md` 이름 및 명시 정책 `docs/workflow.md`, `docs/harness-design.md`를 제외한 regular
비실행 파일이다. 다른 루트 README 변형·임의 `.md`는 허용하지 않는다.

로컬 manifest의 `old_mode`/`new_mode`는 POSIX permission 정수를 그대로 보존한다. regular 파일임은
workspace fingerprint 단계에서 확인하며 실행·special bit가 없는 유효 권한만 허용한다. 수정/rename은
양쪽 권한이 정확히 같아야 하므로 기존 0664·0640·0600 문서도 권한 유지 시 허용한다. 추가/삭제는
존재하는 쪽의 유효 비실행 권한과 반대쪽 부재를 확인한다. umask 002/022/077로 생성된 새 문서도
같은 기준이다. 0600→0644처럼 Git mode로는 구별되지 않는 실제 권한 변경을 정규화로 숨기지 않는다.
CI raw Git diff의 mode는 별도 문자열 증거로 유지하여 추가/삭제의 존재하는 쪽과 수정/rename 양쪽에
기존 `100644` 기준을 적용한다. 잘못된 값·로컬/Git mode 혼용은 full이다. 코드·설정·CI·Makefile·
혼합 변경, executable/POSIX mode/type/symlink 변화, 빈/중복/불명 경로·증거, 비문서 rename·
지원하지 않는 change type은 full이다. scope 계층에서 symlink 등을 먼저 거부할 수도 있으며
이때 docs-only를 부여하지 않는다. 삭제·rename은 양쪽 경로와 현재 남은 역참조를 검증한다.
로컬 manifest의 rename은 보수적으로 삭제+추가로 표현되며 Git raw diff는 R의 양쪽을 유지한다.

허용 prose 변경만 있으면 `required_checks=['check-docs']`로 선택하고 game dependency doctor,
Node·브라우저·MySQL/full suite를 불필요하게 요구하지 않는다. 그 외에는 기존 경로·Jev·역할의
최소 필수 검사를 유지한다. doctor는 full 경로가 필요한 시점에 수행한다. repair마다 최종 diff를
다시 분류하므로 prose→code 수정이면 full로 돌아간다. read_only/nochange는 원본 반영·게시를
추가하지 않으며 빈 diff는 docs-only 근거가 아니므로 기존 검증 경로를 유지한다.

`validation_selection`은 changes·mode·reason과 baseline/candidate digest를, 각 검증 결과는
`validation_digest`를 기록한다. 전체 시도 이력은 `validation`, 전달에 쓰는 마지막 성공 라운드는
`delivery_validation`에 둔다. 반영은 검증 사본 불변성과 원본 baseline 충돌 검사를 요구하고
Git 게시 준비도 실제 candidate·최종 diff·selection 및 check digest를 다시 확인한다.
CLI 0이나 모델의 성공 설명만으로 부족하다. 구조화 checks는 비어 있지 않고 각 group의
`selected`가 양의 정수(bool 제외), `passed==selected`, `status=passed`, failures/errors/skipped가
모두 비어 있어야 한다. 빈/skip·옛 보고서 재사용은 통과가 아니다. docs 실패도 기존 정제
failure feedback과 정확한 task 귀속·새 review/repair 한도를 따른다.

### Python 3.8 오프라인 checker

[docs_check.py](../../harness/docs_check.py)는 Python 3.8 표준라이브러리만 사용한다. 변경 문서의
UTF-8·NUL·merge conflict marker·닫히지 않은 fence와 지원 링크/heading을 검사한다. 상대 파일·
이미지·inline/reference 링크(정의 포함), ATX/Setext heading, 한국어/Unicode slug와 중복 heading의
`-1` 등 suffix, URL percent encoding, inline code와 fenced/indented code 제외를 지원한다.
inline code는 같은 inline block의 soft line break를 포함할 수 있다. 정확히 같은 길이의 backtick
run으로 닫으며, code 밖의 backslash escape와 code 안에서 escape가 작동하지 않는 규칙을 구별한다.
paragraph·heading·fence 경계를 넘어 code를 연결하지 않는다. code 안의 가짜 링크·HTML은 마스킹하되
원문 줄 번호와 뒤의 실제 링크 검사는 유지한다. heading code의 literal 텍스트는 slug에 기여하며
줄바꿈은 공백으로 반영한다. fragment는 Markdown heading 대상만 지원한다.
HTTP/HTTPS/mailto/tel 등 외부 링크는 방문하지 않고 코드 예제도 실행하지 않는다.

변경된 현재 문서는 전체를 검사한다. 현재 README·AGENTS·docs Markdown의 역참조 조사에서는
바뀐/삭제/rename된 대상과 그 anchor에 대한 참조만 검사하여 무관한 과거 오류를 새 수정에
전가하지 않는다. basename prefilter와 URL/Markdown decoding 뒤 잠재 영향 문법이 모호하면
거짓 통과시키지 않고 오류로 남긴다. 삭제만 있고 참조가 없어도 complete change evidence와
역참조 조사가 하나의 실제 structural assertion이므로 selected 0으로 생략하지 않는다.

임의 절대/root-relative 경로·저장소 탈출·symlink/hardlink/non-regular 대상은 거부한다.
각 ancestor와 대상은 no-follow descriptor로 열고, hidden 경로 및 logs/node_modules/__pycache__
경계를 거부한다. 공개 Git 관리 소스 [.github/workflows/harness.yml](../../.github/workflows/harness.yml)은
명시 예외인 정상 링크 대상이다. 이 예외는 credential/private 설정 읽기나 CI 파일 변경의 docs-only
허가가 아니다. 모델 읽기 승인은 별도 개별 파일 목록이며 checker의 로컬 링크 검증 권한과 다르다.

checker는 완전한 CommonMark/HTML/MDX 엔진이 아니다. multiline link destination/label,
HTML link/image·comment·custom anchor 등 검사 중 모호한 문법은 unsupported 오류다.
일부 단순 명시 HTML id/name anchor를 인식해도 임의 HTML 문서를 지원한다는 뜻은 아니다.
문서별 상한은 4 MiB다. unsupported를 skip/성공으로 바꾸지 않는다. parent가 지원 문법으로
고치거나 범위를 명확히 하여 full 검증과 Claude 의미 검토로 조정해야 한다. 자동으로 full을
실행해 문서 오류를 성공으로 덮는 기능은 없다. prose 허용 목록은 기계적 검증 경로를 정할 뿐
설계·운영 의미의 안전성을 보장하지 않으므로 Claude의 독립 의미 검토를 유지한다.

### CLI와 CI

parent는 `make check-docs BASE=<40자리 SHA> HEAD=<40자리 SHA>` 또는 신뢰한 complete selection
JSON을 `CHANGES_FILE`로 제공한다. 변경 경로 몇 개를 적은 목록은 증거가 아니다. 직접
`python -m harness.docs_check --base ... --head ... --report ...`도 가능하다. Git 범위는 현재
checkout HEAD가 head와 같고 tracked diff/untracked가 없으며 complete history여야 한다.
일반 runner의 v2 standalone 결과 보관은 [0021](0021-local-work-and-result-archives.md)을 따른다.

CI는 공개 [.github/workflows/harness.yml](../../.github/workflows/harness.yml)의 selection job에서
`pull_request`의 base.sha→head.sha, `push`의 before→after **전체 raw git diff**를 같은 classifier에
전달한다. rename/deletion/mode와 완전성을 확인하고 event JSON은 Python으로 읽는다. untrusted
event 값을 shell code에 직접 보간하지 않는다. checkout은 event head이고 fetch-depth=0이다.

2026-10-19 당시 결정(새 브랜치 zero-before 부분은 0023으로 대체):
complete PR diff가 prose뿐이면 docs 검증 경로다. **새 브랜치 push의 before=000…000은 full
fallback**이며 같은 변경의 PR docs-only 경로와 다르다. shallow·zero/invalid/unavailable SHA·
dirty/mismatched checkout·unknown event·workflow_dispatch도 full이다. PR이라는 이유만으로
CI를 생략하거나 새 브랜치 push의 full을 docs-only로 강제하지 않는다.

세 required 이름 `Offline harness (SQLite)`, `MySQL harness`, `Chromium browser harness`는
항상 실행되는 실제 final gate job의 success/failure다. docs일 때 heavy execution jobs는
생략하되 final gate는 selection job 성공, selection 일치, docs 결과의 positive selected/passed·
zero skip/failure/error를 artifact에서 확인한 뒤 성공한다. heavy job의 skipped/neutral을
required success로 간주하는 방식이 아니다. docs 실패·증거 누락은 세 gate 실패다.
full일 때 SQLite는 기존 `make check`와 `make check-live`, MySQL과 Chromium은 각각 기존
실행/gate를 요구하고 실패·미실행은 대응 final gate 실패로 전파된다. 게시·merge는 세 실제
success와 고정 head SHA·branch protection·기존 권한/lock 계약을 모두 유지한다.

### 2026-10-20 publisher 연결 정정

`git_publish.checks_gate`가 모든 completed non-success를 일괄 거부하여 정상 docs-only의
heavy skip까지 pre-merge와 fresh cleanup에서 막던 연결 오류를 고친다. 새 검증 면제나 권한
정책이 아니며 위 실제 final gate 계약을 publisher에 연결한다. 예외는 정확히 `Offline execution (SQLite)`,
`MySQL execution`, `Chromium browser execution`의 completed/skipped만 대상으로 한다.
각 skip과 같은 SHA·허용 GitHub Actions app·동일 check_suite.id의 최신 이름별 결과에 selection
`Select actual change validation` completed/success, 세 required completed/success, 세 heavy
completed/skipped 전체가 있어야 한다. suite id는 양의 int만 인정하고 bool·문자열·0·null·누락·
잘못된 객체는 증거가 아니다. 전체 이름별 최신 selection/required success도 요구하여 오래된
성공이나 다른 suite/SHA/app을 섞거나 최신 failure/pending을 우회하지 않는다.
최신 selection/required success의 suite metadata가 잘못되거나 누락돼도 대기한다. 옛 정상 suite
증거로 최신 결과의 불명 metadata를 보완하지 않는다. 이 조건은 예정 skip 예외에만 적용한다.

skip이 먼저 보이고 selection/required가 누락·queued·in_progress이면 기존 `waiting_for_ci`로
기다린다. 불완전·불일치·malformed 증거도 fail-closed이며 merge/cleanup 성공을 허용하지 않는다.
required의 skipped/neutral 등 모든 non-success, 임의 job의 skip, heavy의 failure/neutral/cancelled
등은 계속 거부하고 추가 pending job도 기다린다. selection/suite 없는 정상 required-only legacy와
full 성공은 유지한다. cleanup은 동일 판정을 fresh CI에 적용하며 잘못되거나 미완료인 proof는
기존 cleanup 보류/재개 경계를 따르고 확정 merge SHA를 보존한다. 전체 pagination, head/test-merge
우선순위, 양쪽 commit statuses, 최종 PR 확인과 journal schema는 유지한다. ADR0023의 새 branch
전체 diff 선택 결정도 바꾸지 않는다.

고정 응답 회귀는 skip 선도착→대기→실제 gate 성공과 fresh cleanup, suite/최신성/페이지/SHA
경계를 위한 명세다. 작성만 한 fixture나 PR52의 이전 검증은 이번 실행 성공의 증거가 아니다.
최종 코드·문서의 새 Claude 검토와 fresh documentation={status,files,reason}, full
`make check`, 실제 문서 검사·GitHub 게시·세 required CI·merge·cleanup·archive의 완료 관측은 아래에 기록한다.

## 비교 대안과 선택 이유

| 대안 | 판단 |
| --- | --- |
| scope 확장자·모델 주장·경로 필터로 CI 전체 생략 | 최종 코드/mode/삭제·required check 증거를 잃으므로 거부 |
| 문서도 항상 game/full suite | 무관한 dependency와 대기 비용이 있어 일반 prose 변경에는 대체 |
| 실제 complete diff + 오프라인 docs + 실제 required gates | 최종 변경에 결합하고 불명 증거를 full로 보내므로 채택 |

## 검증과 근거 한계

[test_docs_check.py](../../harness/test_docs_check.py), workflow·triage·failure_feedback·git_publish·runner
회귀는 실제 umask 002/022/077의 추가/수정/삭제·혼합 변경, 동일 0664/0640/0600 권한과 실제
권한 변경·invalid mode 거부, workflow의 docs-only/repair 최종 digest 결합을 포함한다. 승인된
workflow의 여러 줄 warnings code와 합성 fixture로 backtick 길이·escape·block 경계·원문 줄 번호·
code 뒤 깨진 링크·역참조도 다룬다. docs/mixed/policy/mode/type·삭제/rename·fragment·unsupported·공개 workflow 링크와
private 경계·empty/skip 거부·repair/최종 digest·CI 선택을 검증할 명세다. full check에는 새
policy/checker/archive 회귀가 포함된다. **이번 구현은 harness·CI 변경이므로 full `make check`
필수**다. 문서 작업자는 검사·네트워크·Git을 실행하지 않았으며 이전 timeout run/초안/테스트
정의를 성공 근거로 쓰지 않는다. 새 실제 구현·Claude 의미 검토·full check·CI·GitHub
전달의 완료 근거는 아래 메인 관측으로 구분한다. 매 review의 `documentation={status,files,reason}`에서 updated에는 실제
변경 Markdown만 기록하고 최종 코드와 문서의 의미적 완전성을 새로 판단한다.

관련 절차: [harness](../harness.md), [workflow](../workflow.md), 책임 설계: [harness-design](../harness-design.md).

2026-10-20 메인 제공 관측: 아래는 문서 작업자나 reviewer가 직접 실행한 결과가 아니다.
[PR51](https://github.com/21in7/TavernofSoul/pull/51)은 로컬 작업·검증/terminal 결과의 NFS archive와
최종 diff 기반 문서 검증을, [PR52](https://github.com/21in7/TavernofSoul/pull/52)는 ADR0023의
새 브랜치 zero-before에서 검증 가능한 기본 브랜치 공통 조상→head 전체 diff 선택을 구현했다.
두 PR은 새 역할 검토·로컬 전체 검사·세 필수 CI 성공과 merge·cleanup·archive를 완료했다.
[PR53](https://github.com/21in7/TavernofSoul/pull/53)은 동일 suite의 selection success·세 필수 gate
success·세 예정 heavy skip을 확인하도록 publisher 연결을 정정했다. 실제 Codex 구현과 새 Claude
승인·문서 갱신, 최종 로컬 전체 `make check` 4726개 통과(selected=passed, skip/failure/error 0),
별도 변경 문서 링크·역참조 검사 22개 통과를 확인했다. 메인은 실제 push와 PR의 세 필수 CI 성공,
merged=true·merge SHA, 정확한 branch cleanup complete, terminal archive archived를 관측했다.

세 구현 PR은 코드·하네스 변경으로 full 경로를 거쳤으므로 별도 문서 전용 실행의 관측을 대신하지
않는다. 이 단일 문서 후속 PR의 실제 local selection·새 브랜치 첫 push·GitHub docs-only·자동
merge·cleanup은 메인의 후속 확인 대상이며, 아직 성공을 관측하거나 완료로 기록하지 않는다.
