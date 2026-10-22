# 에이전트 모델 연결

discovery reviewer의 source 확인은 [ADR0026](adr/0026-source-verified-retained-improvement-reports.md)을 따른다.
이 호출만 parent Capture와 Claude stream-json/verbose·Read 단일 도구를 쓴다. canonical 승인 경로,
성공 structured Read result와 원래 bytes/줄 범위의 pairing이 필수다. prompt/result의 read_files는
권위가 아니다. bounded 수집 실패·알 수 없는 CLI 형식은 fail-closed이며 retry/fallback하지 않는다.
Read content는 원본 UTF-8의 최초 BOM 한 번 제외 → LF split → 각 줄 끝 CR 하나 제거 → 선택 줄 LF
join의 정확한 값만 허용하며 LF를 덧붙이지 않는다. totalLines는 끝 LF 뒤 빈 줄까지 포함한 전체 split
길이다. 마지막 빈 줄만 선택하면 content는 빈 문자열이다. 원본 bytes/hash/POSIX mode·evidence 줄 번호와
range bytes/hash는 별도로 보존한다. Read 표본은 표본 밖이나 저장소 전체의 무결함을 보장하지 않는다.
빈 pool은 owner membership 안의 non-shared Python 프로그램을 테스트보다 우선 선택한다.
AGENTS·안내 문서·설정은 코드 확인으로 세지 않는다. 함수 본문(없으면 script 실행문) 주변의
연속 최대96줄과 별도 shared 문서 최대12줄을 실제 Read한다. 선택 프로그램 부재·빈 파일·읽기/
파싱 불가·header만 존재하거나 기존32KiB/32window 한도를 넘으면 coverage는 미완료다.
표본은 전체 파일·저장소 완독이 아니다. 후보가 있으면 모든 evidence/benefit.evidence와 필요한
문서 Read 요구는 그대로다.
일반 workflow/GLM telemetry·compaction·identity/cost/interrupt와 인증/provider/model/예산은 보존한다.

2026-10-21 [ADR0025](adr/0025-progress-preserving-improvement-reviews.md)에 따라 local은 선택적
참고 자료다. duplicate/empty/exception/긴 줄 때문에 paired specialist나 빈 pool reviewer를
생략하지 않으며 각 정규 slot에서 동일 sealed 승인 source를 독립 점검한다. 추가 call·재시도·
새 provider/model fallback은 없다. 실패/부분 coverage는 전체 정상 점검으로 보고하지 않는다.
source-only 변화에는 sealed 회차/cursor 진행을 유지하되 현재 freshness는 별도 검사하고,
scope/ownership/config/provider/model/protocol 변화는 진행을 무효화한다. 실제 cloud 참여는
회차와 독립된 bounded history로 오전 window에 집계한다. private local·cost·진단·원문은
web-v1에 추가하지 않는다. 기존 인증·모델·GLM>=80%·Claude$1/reviewer$.20·틱1회/하루24회와
승인/게시 경계는 유지한다. 최종 의미 검토·full check·실제 hourly 관측은 별도 증거가 필요하다.

`harness/agent-models.json`은 역할별 공급자·모델·추론 수준과 관련 검증 명령을 지정한다.
`harness/agent_models.py`는 기존 Codex/Claude Code CLI를 실행한다. 별도 Python SDK 설치는 필요 없다.
다운로드·파싱·Django 운영 프로세스에는 연결하지 않으며 개발 작업에만 사용한다.
역할을 자동으로 배정하고 검토·검증 뒤 반영하는 실행기는 [자동 작업 실행](workflow.md)을 참고한다.
담당 역할을 선택하기 전의 Jev 판단·비교 로그는 [Jev 작업 판단](triage.md)을 참고한다.
`typesafe`는 별도 REST 판단 공급자이며 아래 구현 역할에 CLI 모델로 배정하지 않는다.
Claude Code 기반 역할은 [Jev 대화 기록 압축](compaction.md)을 기본 적용한다.
기존 TypeSafe 키를 재사용하며 `COMPACTION=0`으로 해당 실행에서 끌 수 있다.

다음 표는 일반 개발 workflow의 역할·모델과 관련 검증을 정리한다.

| 역할 | 실행 도구 / 인증 | 모델 | 관련 검증 |
| --- | --- | --- | --- |
| coordinator | Codex / ChatGPT Pro 로그인 | gpt-6.1-sol, high | make check |
| downloader | Claude Code / Z.ai Coding Lite 키 | glm-5.3-flash | make check-downloader |
| parser | Codex / ChatGPT Pro 로그인 | gpt-6.1-sol, high | make check-parser |
| django | Codex / ChatGPT Pro 로그인 | gpt-6.1-sol, medium | make check-django |
| git | Codex / ChatGPT Pro 로그인 | gpt-6.1-sol, medium | 검증 결과로 커밋·PR 설명 작성; 게시·CI·머지는 메인 앱 연결 |
| reviewer | Claude Code / Anthropic API 키 | claude-sonnet-5-5, medium | make check |
| escalation | Claude Code / Anthropic API 키 | claude-opus-5-5, high | make check |

자동 개선 연구에는 다음 로컬 초안 역할이 별도로 참여한다.

| 역할 | 실행 환경 | 모델 ID (문서·설정 예제 기준) |
| --- | --- | --- |
| local_explorer | Mac mini / mlx-vlm 0.7.8 | mlx-community/Qwen3.5-9B-4bit |

모델 ID는 예제 기준이며 실제 private 설정이나 현재 실행 상태를 확인한 정보가 아니다.
로컬은 승인된 작은 소스 구간의 개선 초안을 만들고, 기존 담당 모델의 검토·정식 후보화와
Claude 독립 검토로 이어진다. 일반 구현 역할을 대체하거나 실행을 승인하지 않는다.
상세는 [로컬 모델 문서](local-models.md)와 [자동 개선 연구의 모델·비용 계약](#자동-개선-연구의-모델비용-계약)을 참고한다.

## 인증 등록

기존 `~/.codex`와 `~/.claude`의 설정·키·로그인을 덮어쓰지 않는다.
Codex는 ChatGPT 로그인만 허용하고, 자식 프로세스에서 OpenAI API 키를 제거한다.
연결용 실행은 사용자 settings를 불러오지 않는다. 압축을 켠 Claude Code 실행은 고정된
프로젝트 플러그인을 명시적으로 로드하며, Codex와 일반 모델 smoke는 기존 최소 실행을 유지한다.
Claude API와 Z.ai는 서로 다른 `CLAUDE_CONFIG_DIR`을 사용한다.
기존 Claude 구독 로그인으로 API 키 누락을 대신하지 않는다.

```bash
make agent-doctor
# Codex 로그인이 없는 헤드리스 서버에서만 실행한다.
codex login --device-auth

# 서버 터미널에서 입력한다. 입력은 화면과 셸 기록에 나타나지 않는다.
make agent-configure PROVIDER=claude
make agent-configure PROVIDER=zai
# Jev 판단 API를 사용할 때 추가한다.
make agent-configure PROVIDER=typesafe
make agent-doctor
```

키는 루트의 `.agent-keys.json`에 권한 `0600`으로 저장하며 Git에서 제외한다.
이미 환경에 등록한 `ANTHROPIC_API_KEY`, `ZAI_API_KEY`, `TYPESAFE_API_KEY`도 읽으며 환경 값이 파일보다 우선한다.
기존 `.env`는 읽거나 변경하지 않는다. 다른 프로젝트의 환경 키를 로컬 키 파일로 복사하지 않는다.
Codex/Claude Code CLI가 없는 경우 공식 설치 안내를 따른다. 현재 연결은
Codex CLI 0.161.0과 Claude Code 2.1.294에서 검증했다.
Opus 5.5 호출은 Claude Code 2.1.280 이상을 요구한다. 기존 버전은 `claude update`로 갱신한다.
GPT-6.1 Sol을 선택한 앱과 이전 서버 CLI의 모델 목록이 다를 수 있다. 모델 거부가 발생하면
계정·workspace·CLI 버전과 실제 응답을 함께 확인한다. 공식 standalone 설치는 `codex update`로 갱신한다.

`agent-doctor`는 로컬 CLI 존재·Codex private 런타임 생성과 로그인 상태·키 등록 여부를 확인한다.
Codex의 `login status`도 아래 임시 런타임에서 실행한다. 추론 요청이나 별도 DNS 탐침은 보내지 않으며,
`passed`는 외부 DNS·모델 접근 권한·실제 응답 성공을 보장하지 않는다. TypeSafe는 CLI 없이 키 등록만 확인하며
키 등록 전에는 전체 doctor가 `not_configured`를 반환한다. 기존 역할은 개별 공급자 doctor로 확인할 수 있다.
모델 접근 권한과 실제 응답은 다음 smoke로 별도 확인한다.
Codex 인증은 `login status`의 exit0와 정확한 ChatGPT 로그인 상태 행을 모두 요구한다.
API 키 로그인(서로 모순되는 로그인 상태 포함)이나 상태 누락은 거부한다. PATH aliases 읽기 전용
경고만으로 이 조건을 만족한 인증을 실패시키지 않으며 `ready` 결과의 고정 `warnings`를 보존한다.
키가 없거나 잘못된 Codex 로그인인 경우 0이 아닌 코드로 종료한다.

## Codex의 private CLI 런타임

doctor·smoke·역할 실행마다 `tavern-codex-runtime-*` 임시 디렉터리를 새로 만든다.
루트와 `home`, `tmp`, XDG 설정·캐시·데이터·상태 디렉터리는 각각 `0700`이다.
자식 프로세스의 `CODEX_HOME`, `TMPDIR`/`TMP`/`TEMP`, XDG 경로만 이곳으로 지정하여
PATH aliases 등 CLI 초기화 쓰기를 읽기 전용 설치·로그인 경로와 분리한다.
부모 환경과 기존 로그인·사용자 설정은 변경하지 않는다.

기존 `CODEX_HOME` 또는 기본 `~/.codex`에서 `auth.json`만 별도 파일로 복사하며 사본은 `0600`이다.
원본 파일의 symlink·비정규 파일·빈 파일·1 MiB 초과 파일은 거부한다. 설정·지침·skill·다른 인증 파일과
keyring 항목은 복사하지 않는다. 파일 인증을 사용할 수 없으면 `auth_file_unavailable`로 실패하며
실제 사용자 home이나 API 키 인증으로 fallback하지 않는다. 자동 로그인·설정 변경도 하지 않는다.
한 역할 호출의 로그인 확인과 모델 실행은 같은 임시 런타임을 공유한다. CLI가 인증 사본을 갱신해도
원본 로그인에 역복사하지 않는다. 다른 호출은 각자 새 사본을 사용한다.

호출이 끝나면 성공·실패·timeout 모두 임시 런타임과 인증 사본을 정리한다.
생성 또는 정리에 실패하면 `runtime_unavailable`로 실패 처리하며 성공으로 보고하지 않는다.
강제 종료 등으로 정리 코드가 실행되지 않으면 잔여 private 디렉터리가 남을 수 있으므로,
운영자가 해당 프로세스 종료를 확인한 뒤 해당 런타임만 삭제한다. 인증 내용은 진단에 출력하지 않는다.

런타임 쓰기 권한은 모델 도구의 권한과 별개다. 모델 권한 프로필은 `:root=deny`, `:minimal=read`를
기본으로 승인 작업 경로에 읽기 전용 실행은 `read`, 편집 실행은 `write`를 부여한다.
임시 `runtime_root`는 작업 경로 안에 있더라도 명시적으로 `deny`하고 원본 인증 home은 `:root=deny`로 보호한다.
설치된 CLI와 필수 셸 실행 파일에만 좁은 `read` 예외를 부여하며 설치 디렉터리 전체는 허용하지 않는다.
original auth_home에 별도 directory deny를 추가하지 않는다. Linux에서는 그 deny가 auth_home 아래
standalone 바이너리의 파일 단위 read 예외까지 가려 실제 파일 도구를 permission denied로 막을 수 있다.
workspace와 original auth_home을 모두 resolve한 뒤 workspace가 auth_home과 같거나 이를 포함하는
상위 경로이면 `unsafe_workspace`로 거부한다. symlink와 `..`로 표현한 경로에도 같은 조건을 적용한다.
모델 도구의 `network.enabled=false`를 유지한다.
승인 소스만 담은 모델 사본에는 Git metadata와 사용자 신뢰 기록이 없으므로
`--skip-git-repo-check`를 사용한다. 이 옵션은 파일 권한 프로필이나 승인 범위를 확대하지 않는다.
CLI 런타임 격리는 외부 DNS 제한을 해제하거나 Jev 연결 실패를 해결했다는 의미가 아니다.

## 실제 연결 확인

```bash
make agent-smoke PROVIDER=codex
make agent-smoke PROVIDER=claude
make agent-smoke PROVIDER=zai
# TypeSafe는 typed REST 응답을 확인한다.
make triage-smoke
```

`agent-smoke`는 짧은 응답을 실제로 요청하고 무작위 확인 문자열이 돌아왔는지 검사한다.
`triage-smoke`는 작업 판단의 타입·확률·사용량을 검사한다. 등록 뒤에 명시적으로 실행한다.
Claude/Z.ai에는 파일·셸 도구를 주지 않고, Codex에는 작업 경로 읽기만 허용하는 권한 프로필과
도구 사용 금지 지시를 사용한다. Codex 인증 런타임은 모델 도구에서 접근할 수 없으며 네트워크 제한도 유지한다.
로그인이나 키 존재만으로 연결 성공을 보고하지 않는다. Codex 역할 실행은 exit0, JSON event 행 파싱,
객체 event, 실패 event(`turn.failed`/`error`) 없음, 비어 있지 않은 문자열 최종 agent_message와
`turn.completed`를 모두 요구한다. smoke는 무작위 nonce 일치까지 검사한다.
PATH aliases 읽기 전용 경고는 이 성공 조건을 대신하지 않으며 유효한 완료를 실패로 바꾸지도 않는다.
실패 응답·malformed/미완료/빈 응답·nonce 불일치·예산 초과는 계속 실패다.
Claude smoke의 CLI 비용 한도는 $0.25이며 구독과 API 호출은 각 서비스의 사용량을 소비한다.
CLI 상태와 응답은 `logs/harness/agents/`, Jev 판단은 `logs/harness/triage/`의 private JSON 보고서에 저장한다.
Claude의 CLI 비용 추정값만 기록하며 Z.ai의 토큰 출력을 Anthropic 요금으로 계산하지 않는다.
키 등록만으로 smoke를 자동 실행하지 않으므로, 등록 뒤 해당 명령으로 확인한다.

## 실패 진단 읽기

Jev의 `network_error`와 이후 coordinator의 Codex 초기화 실패는 서로 다른 단계다.
샌드박스에서 `api.typesafe.ai` 이름 조회가 실패한 사례는
`fallback_reason=network_error`, `diagnostic={"error_type":"gaierror","errno":-3}`로 구분한다.
`gaierror`는 이름 조회 실패를 나타내며 정수 코드는 실행 환경의 OS 오류 코드다.
진단만으로 외부 서비스 장애나 정확한 DNS 정책 원인을 확정하지 않는다.

Jev의 안전한 `diagnostic`은 `error_type`(`gaierror`, `timeout`, `connection_error`, `network_error`)과
존재하는 경우 정수 `errno`만 포함한다. HTTP 실패는 별도의 정수 `http_status`만 기록한다.
예외 원문·URL/헤더·Authorization·키·원격 오류 응답 본문은 진단에 넣지 않는다.
Jev 호출은 제한된 단일 요청이며 진단을 위해 추가 DNS 탐침이나 권한 확대를 하지 않는다.

TypeSafe 공식 OpenAPI는 probability 합을 approximately 1, score를 level index의 weighted average로
설명한다. 관찰된 두 자리 반환값의 독립적인 반올림을 허용하기 위해 다음 **절대 오차** 한도만 적용한다.

- probability 합과 1의 차이: `max(0.001, len(options) * 0.005)`.
- score와 `sum(level_index * probability)`의 차이: `max(0.001, 0.005 * (1 + sum(level indices)))`.

상대 오차를 적용하지 않아 위 한도를 확대하지 않는다. 경계값을 포함한 절대 범위로 비교한다.
정확한 경계값의 이진 부동소수점 표현 오차에만 `FLOAT_COMPARISON_EPSILON=1e-12`를 더한다.
허용 한계를 `1e-10` 초과하는 편차는 계속 거부하며, 원본 반환 숫자는 변경하지 않는다.
score level이 `0, 1, 2`인 경우
합 오차는 최대 `0.015`, score 오차는 최대 `0.02`다. 예를 들어 score `0.07`, probabilities
`{'0': 0.94, '1': 0.06, '2': 0.0}`, confidence `0.91`은 정확한 legend가 있으면 허용한다.
가중평균 `0.06`과의 차이 `0.01`이 한도 안이기 때문이다. 반올림된 합 `0.99`와 `1.01`도 허용하지만
큰 불일치나 한도를 넘는 모순은 `invalid_response`다. 범위 밖 숫자·bool·NaN·Inf·다른 legend·
누락/추가 label·choice가 확률 최댓값이 아닌 응답은 계속 거부한다.
원본 probability·score·confidence를 그대로 반환하며 재정규화하거나 가중평균으로 score를 대체하지 않는다.
기존 라우팅 임계값도 그대로 적용한다. 자동 재시도·모델 변경·네트워크 확대는 하지 않는다.
허용된 응답은 triage에서 `passed`로 기록하되 추천의 `execution_allowed=false`를 유지한다.
`invalid_response` fallback은 coordinator 계획과 전체 `check`를 요구하며 검증 통과를 뜻하지 않는다.

Codex 실패의 `diagnostic`은 `stage`(`runtime`, `authentication`, `execution`)와 고정 `category`만 포함한다.
인증 문제는 `authentication_failed`, 생성·정리 문제는 `runtime_unavailable`이다.
그 밖에 `missing_cli`, `auth_file_unavailable`, `timeout`, `cli_failed`, `invalid_response`,
`probe_mismatch`로 구분하며 고정된 오류 설명을 제공한다. nonzero exit에서 PATH aliases 읽기 전용
메시지가 있으면 실패 진단을 `path_aliases_read_only`로 분류할 수 있다. exit0여도 응답 검증이 실패하면
경고로 구제하지 않고 `invalid_response`(인증 오류가 확인되면 `authentication_failed`)로 실패한다.
CLI stdout/stderr 원문, 원격 오류 응답·인증 내용은 진단 보고서에 저장하지 않는다.
모든 검증을 통과한 정상 모델 최종 응답만 기존 private 보고서에 저장한다.

Codex 보고서의 `warnings`는 원문·경로·비밀 없는 고정 metadata 목록이다. 현재 항목은
`{"stage":"authentication","category":"path_aliases_read_only"}` 또는
`{"stage":"execution","category":"path_aliases_read_only"}`이며 단계당 하나만 기록한다.
경고가 없으면 빈 목록이다. 유효 인증의 경고는 해당 역할 실행 보고서까지 전달하고 실행 stderr의
경고도 기록하므로 후속 실패가 생겨도 관측할 수 있다. warning은 성공 판정이나 재시도 근거가 아니다.
nonzero exit, 인증 실패/API 키 로그인, 실패 event, 잘못된/미완료/빈 응답, timeout, nonce 불일치,
런타임 생성·정리 실패는 계속 실패다. runtime deny와 network=false, CLI/model/roles/예산·source scope는
유지하며 실제 home fallback·권한 확대·자동 재시도는 하지 않는다.

2026-10-12 원인 기록: 메인이 제공한 조사 요약에 따르면 이전 일반 workflow
`1791729971212631163-d0abf4`의 Jev와 Codex 계획은 통과했고 coordinator 편집은 exit0이었다.
그러나 `agent_models.run`이 완료 응답 검증 전에 stderr 문자열로 `execution/path_aliases_read_only`를
선판정해 완성 초안의 반영을 막았다. 뒤의 별도 draft 복구 성공은 일반 실행 경로 수리의 증거가 아니다.
CLI 0.161.0의 메인 무추론 `--no-daemon --version` 비교에서 매 호출 writable private runtime은
exit0/경고 없음, 다른 private 임시 경로를 유지하고 `CODEX_HOME=/sys`만 지정하면 exit0/동일 경고가
관측되었다. 이는 진행 가능한 warning의 관측이며 이 worker가 실행한 검증이 아니다.
이전 raw stderr는 보안 정책상 저장하지 않아 최초 경고를 낸 하위 프로세스는 미확정이다.
모델 도구의 runtime deny가 하위 도구 초기화에도 경고를 유발할 수 있다는 설명은 추론이다.
[공식 sandbox 문서](https://learn.chatgpt.com/docs/sandboxing)의 spawned commands 경계는 일반 참고이며
PATH aliases 구현이나 최초 발생 프로세스를 증명하지 않는다. 새 판단 경계는
[ADR 0007](adr/0007-codex-warning-success-boundary.md)에 기록한다. private 로그는 이 사실 요약만
기록하며 모델 응답·인증 원문을 문서에 복사하지 않는다.
Jev fallback과 workflow 종료 상태의 관계는 [자동 작업 실행](workflow.md)을 참고한다.

## 역할 실행

작업을 텍스트 파일에 작성하고 해당 역할로 전달한다.

```bash
make agent-plan ROLE=parser
make agent-run ROLE=parser TASK_FILE=/tmp/parser-task.txt
make agent-run ROLE=downloader TASK_FILE=/tmp/downloader-task.txt WRITE=1
make agent-run ROLE=reviewer TASK_FILE=/tmp/review-task.txt
```

`agent-plan`은 실행할 인자만 표시하고 API 요청을 하지 않는다.
기본은 읽기 전용이다. `WRITE=1`이면 Codex 권한 프로필의 작업 경로 쓰기 또는 Claude Code의 파일 편집 도구를 사용한다.
reviewer·escalation·git은 편집 요청을 거부한다. Claude/GLM에는 셸 도구와 MCP를 제공하지 않는다.
개별 실행에서는 역할별 AGENTS.md와 운영 실행 금지 지침을 함께 전달하며, 자동 재위임은 사용하지 않는다.
scoped workflow에서는 승인 목록 밖 지침을 읽거나 추가하지 않으며 worker의 테스트·workflow·agent-run·
cron·다운로드·운영 import·재위임을 금지한다. 검증은 orchestrator가 수행한다.
CLI 출력은 모델 응답 성공 여부다. 코드 변경의 검증 통과를 의미하지 않으므로 운영자가 결과를 확인한 뒤
관련 `make check-*`를 실행하고 연결부 변경은 `make check`로 확인한다.

reviewer의 호출별 CLI 한도는 $2, escalation은 $5다. 이 한도는 CLI 비용 추정값 기준이며
Anthropic 청구액이나 월 합계를 보장하지 않는다. 월 $100 관리는 Claude Console의 사용량·지출 설정으로
별도 확인해야 한다. Jev 추천은 shadow 모드의 판단 기록이다.
이 개별 호출 도구는 자동 배정·수정 후 검증을 하지 않는다. `agent-workflow`가 별도로 담당한다.
중앙 월 예산 집계는 별도 범위다. 개별 `agent-run`은 GitHub에 게시하지 않는다.
기본 쓰기 `agent-workflow`는 검증 후 Git 설명 역할을 호출하고 메인 Codex의 GitHub 앱으로
커밋·브랜치 게시·PR·CI 성공 후 머지를 이어 처리한다. 세부 흐름은 [자동 작업 실행](workflow.md)을 따른다.
Git 역할에 GitHub 인증을 전달하지 않고 모델·검증 자식 환경에서도 GitHub 토큰을 제거한다.
서버 CLI만 실행하면 앱 연결을 호출할 메인이 없어서 `awaiting_github`에 대기한다.

Z.ai는 공식 지원 도구인 Claude Code에서 `https://api.z.ai/api/anthropic`을 사용한다.
Coding Lite를 자체 범용 HTTP 클라이언트로 호출하거나 일반 API 엔드포인트로 대체하지 않는다.
한도 소진·인증 실패 시 다른 유료 공급자로 자동 전환하지 않는다.
지원 모델을 계정에서 사용할 수 없으면 보고서의 실패를 확인하고 manifest를 명시적으로 수정한다.

## 자동 개선 연구의 모델·비용 계약

최신 직접 선택은 [ADR0017](adr/0017-budgeted-continuous-improvement.md)의 hourly 연구와
09:00 once 보고다. 기존 cloud roles/provider/model/effort/compaction/auth를 변경하지 않는다.
Codex는 기존 ChatGPT 로그인, GLM은 Claude Code의 기존 Coding Lite
`https://api.z.ai/api/anthropic` 연결이다. 새 요금제/계정/유료 balance fallback은 없다.
별도 [mlx-vlm adapter](local-models.md)는 Mac의 preload text model 초안을 담당하며 cloud
역할이나 독립 reviewer로 배정하지 않는다. Linux Python3.8 표준라이브러리 HTTP만 사용한다.

기본 round는 local(coordinator)→coordinator→local(downloader)→downloader→local(parser)→parser→
local(django)→django→independent Claude reviewer다. 한 hourly tick에서 모델 최대1회·로컬 포함
KST 하루24회이며 specialist는 local 초안을 기존 승인 소스로 검증해 정식 후보로 만든다.
local 실패/빈 초안에도 관련 specialist와 빈 pool의 reviewer를 정규 slot에 호출한다. 다음 round prompt에 정제 issue와
specialist/Claude review.reason을 이어받는다. private local_participation은 provider=mlx-vlm,
설정된 실제 model identity/stage=local_explorer/owner_role을 보존하며 기존5역할 참여를 위장하지 않는다.
설정은 `local-model-config-v2`/`provider=mlx-vlm`, `api_model == model`인 검증된 상대
repository ID다. 서버에 `default_model` 별칭은 없고 요청에 절대 호스트 모델 경로를 넣지 않는다.
v1 mlx-lm 설정은 자동 변환·대체하지 않고 `config_invalid`로 보류한다. version/provider/API
identity가 config digest에 포함되어 이전 loop fingerprint와 서명 승인을 재사용하지 못한다.
메인이 기존 다운로드 모델을 같은 상대 repository ID 경로로 연결해 로드·확인한다.

mlx-vlm0.7.8은 실제 요청의 `response_format={"type":"json_schema","json_schema":{"name":...,"strict":true,"schema":...}}`를
llguidance logits processor로 강제하며 `enable_thinking=false`는 top-level이다. schema는 기존
canonical 후보 전체 필드·타입·필수 항목·additionalProperties=false, 최대2후보, owner 승인
edit_files enum, candidate/benefit 양쪽 evidence의 실제 단일 window 경로·원문 줄 범위를 담는다.
전송 전 canonical schema를 재구성하고 준비 입력 결합을 검증해 schema/owner/scope/window/
thinking 변조를 호출 전에 거절한다. schema 포함 전체 request24576bytes로 whole-line을 선택하며
고정 overhead 초과는 `context_too_large` no-call이다. uniqueItems는 서버 미지원이므로 넣지 않는다.
중복·줄 순서·총 문자량·의미와 실제 window의 최종 판단은 기존 client 검증·독립 검토에 남는다.
서버가 schema를 무시해도 거절하며 보정·합성·재시도·fallback은 없다. assistant의 정확한
`tool_calls:null`/`tool_call_id:null`만 무동작 metadata로 받으며 non-null과 다른 도구 필드는 거절한다.

Claude 탐색은 KST calendar day 추정 ledger US$1·reviewer1회 cap<=US$0.20이다.
호출 직전 durable reservation/count를 저장하고 cap=`min(0.20, 잔액, 기존 role cap)`를
`run(..., max_budget_usd=...)`와 `command_for(..., max_budget_usd=...)`에 넘겨 실제 CLI
`--max-budget-usd`로 연결한다. optional override는 Claude 전용 finite 양수·downward-only다.
bool/NaN/Inf/0/음수/기존 cap 증가/다른 provider를 거부하며 smoke에는 기존0.25 cap도 적용한다.
override 생략 시 reviewer2USD/escalation5USD 등 공통 설정과 다른 workflow 예산은 그대로다.
**이 기능 구현 workflow의 모델 비용은 자동 탐색 하루1USD ledger와 별도다.**

성공한 finite/nonnegative CLI estimate만 settlement하며 실패/timeout/unknown/중단은 예약을
전액 소비 처리한다. 관측 estimate가 예약을 넘으면 실제 추정을 기록하고 당일 전체 연구를
중단한다. 일반 잔액 소진은 reviewer admission에서 판단한다. 그 차례 전 local/구독 역할은
다른 gate와 일일 call cap 내에서 진행할 수 있다. reviewer 예산 보류는 stage_index를 유지해
새 slot에서도 reviewer를 다시 판단하며 이후 local/구독 역할은 대기가 풀릴 때까지 호출하지
않는다. 09:00 보고 확정은 독립적이다. unknown 비용을0USD로 표기하지 않는다. CLI estimate/cap·ledger는 실청구
강제상한 보장이 아니다. 자정600초 guard·rollback 방지·cross-day 보수적 이중 count/charge·
당일 legacy 비용/호출의 scan_id 중복 제거 carry-in은 [운영 계약](improvements.md)을 따른다.
이 budget/quota gate는 자동 탐색에만 적용하며 사람 승인 후 execute에는 적용하지 않는다.

GLM admission마다 trusted parent만 기존 ZAI_API_KEY로 고정
`GET https://api.z.ai/api/monitor/usage/quota/limit`를 조회한다. 기본15초/최대20초·response64KiB·
bounded headers·redirect/proxy/retry 금지이며 key/raw body/원문 예외를 모델/로그/웹에 주지 않는다.
legacy TOKENS_LIMIT/신형 CREDIT_LIMIT의5h(unit3/number5) finite percentage0..100·미래 정수
epoch-ms reset을 검증한다. 두 type 모두5h의 정확한 finite numeric0%(bool 제외)에만 absent/null
reset을 idle로 허용하고 private nextResetTime=null(미상·미활성)을 유지한다. 그 외 유효한 미래
reset을 요구하며 weekly(unit6/number1)는0%라도 예외가 없다. weekly/CREDIT_LIMIT 존재는
가정하지 않는다. envelope success/code가 있으면 true/정수200을 요구한다. TIME_LIMIT 단독·
model limit 부재·HTTP/응답 실패를0%로 해석하지 않으며 unknown/중복/미지원 window·malformed/
조회 실패는 GLM 보류다. 모델 window 하나라도>=80%면 pause해 명목20% 개발 여유를 남긴다.
호출 도중 사용까지 절대 보장하지 않는다. 과거1% 관측 재사용·새 credit 가격 하드코딩·quota 구매·
reset 소비는 없다. 공식 FAQ에 따라 Coding Plan 소진 시 balance 자동 차감으로 전환하지 않는다.

기존37개 읽기 승인과 role ownership/shared는 유지한다. 로컬은 exact path/원래 line 번호의
작은 연속 window와 sanitized feedback만 받으며 전체 소스·SSH/home/key·도구·remote_code를
받지 않는다. private0600 endpoint/model config digest도 loop freshness와 signed authorization에
결합한다. source-only 변화는 sealed snapshot 회차의 진행을 유지하고 현재 freshness만 잃는다.
control 변경은 진행을 무효화하지만 실제 참여는 보존한다. 실제 원문이나
비용/로컬 설정을 기존 web-v1 public shape에 추가하지 않는다.

메인의 기존 서비스/터널 준비와 약19.54초 합성 추론은 이전 adapter 관측이다.
mlx-vlm0.7.8의 compiler/null metadata·실제입력 prototype·합성 후보 관측은
[로컬 모델 문서](local-models.md#메인이-제공한-서버-호환-관측과-남은-검증)에 한계를 명시한다.
특정 미검토 초안의 실제 HTTP 경로 사전 관측도 최종 bytes/전체 검증 성공을 뜻하지 않는다.
최초 초안은 파싱 뒤 candidate_invalid였고 원문이 없어 당시 필드는 알 수 없다. 재현의 편집 범위·
evidence 위반은 최초 원인의 확정이 아니다. prompt/order 두 실행은 full check 중단/applied=[]이며
보존 초안·검증 사본 재사용도 성공이나 fallback이 아니다. 최종 새 검토·전체 검증이 필요하다.
메인 제공 기존 상태는 hourly wrapper 활성·2026-10-16 09:00 partial/제안0개 한 번 전달이며
확정 보고는 보존한다. 신규 서비스/private config 전환·최종 추론·실제9단계·다음 아침 게시 확인은 대기다.
worker는 실모델/네트워크/검사/Git/cron을 실행하지 않았다.
새 Claude 의미검토/full make check·두 umask 권한 fixture 검증/scoped apply는 실행기, 첫9단계/예약/GitHub 전달/보고
게시 확인은 메인 책임이다. 매 review는 실제 변경 Markdown과 계약의 의미적 완전성을
documentation={status,files,reason}으로 평가하며 확장자 검사로 대체하지 않는다.

## 검증과 공식 근거

`make check`의 오프라인 테스트는 키 파일 보호·공급자 간 인증 분리·API 과금 로그인 거부·오류 응답·
확인 문자열·진단 출력의 키 제거를 검증한다. 실모델 호출은 오프라인 기본 검증에서 제외하며
`agent-smoke`와 `triage-smoke`로 따로 실행한다.
연결부 회귀 테스트에는 Jev 전송 오류의 안전한 분류·추가 DNS 탐침 금지와 Codex 런타임 권한·
인증 사본 분리·원본 보존·호출별 수명·오류/timeout 정리·정리 실패 처리·원문 진단 차단이 포함된다.
source-only 실행 옵션·auth_home 아래 실행 파일 예외·resolve 후 unsafe_workspace 거부와
Jev 반올림 오차 한계 안팎·원본 숫자에 따른 임계값 판단·invalid_response fallback도 오프라인 회귀 대상으로 둔다.
정상 실행·전송 실패·응답 검증 회귀의 workspace는 original auth_home을 포함하지 않는 별도 소스
디렉터리를 사용한다. 인증 home을 포함하는 경로는 unsafe_workspace 거부 회귀에서만 사용하여,
실행 단계의 실패가 workspace 거부로 가려지지 않도록 한다.
PATH aliases 회귀는 ChatGPT 로그인+경고의 ready, completed+경고의 passed, 인증·실행 경고 전달,
nonzero+경고의 실패, 경고가 있는 malformed/미완료/failed/error/빈 응답·nonce 불일치의 실패와
원문·비밀 미노출·runtime cleanup을 다룬다. 기존 실제 권한 경계 회귀도 유지한다.
2026-10-12 수리 worker는 테스트·검사·실모델·workflow를 실행하지 않았다. 새 Claude 문서 의미 검토,
full `make check`, 일반 Codex 도구 편집 실호출, Git 역할·PR/CI/merge는 메인/orchestrator의 남은 검증이다.
scoped workflow의 담당 worker는 테스트를 실행하지 않으며 orchestrator가 검증을 수행한다.

- [Codex 인증과 헤드리스 로그인](https://learn.chatgpt.com/docs/auth)
- [Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Codex sandbox 경계와 spawned commands](https://learn.chatgpt.com/docs/sandboxing)
- [Claude Code CLI 옵션과 비용 추정 한도](https://code.claude.com/docs/en/cli-reference)
- [Claude Code bare 실행과 API 키 인증](https://code.claude.com/docs/en/headless)
- [Z.ai Coding Lite 모델·사용량](https://docs.z.ai/devpack/overview)
- [Z.ai의 Claude Code 연결](https://docs.z.ai/devpack/tool/claude)
- [Z.ai 공식 quota 조회 script](https://github.com/zai-org/zai-coding-plugins/blob/main/plugins/glm-plan-usage/skills/usage-query-skill/scripts/query-usage.mjs)
- [Coding Plan FAQ·balance 자동차감 없음](https://docs.z.ai/devpack/faq)
- [기존 구독 quota 보존](https://docs.z.ai/devpack/notice/usage-revision)
- [Claude 모델과 API 가격](https://platform.claude.com/docs/en/about-claude/pricing)

## GLM 호출의 private 지연 관측

`provider=zai` 실행만 [agent_telemetry.py](../harness/agent_telemetry.py)의 Python 3.8
표준라이브러리 collector를 사용한다. 부모가 호출마다 `127.0.0.1`의 임시 포트와 192bit
비밀 경로를 만들고 Claude Code built-in OTLP http/json traces만 받는다. 프록시나 inference
API 우회가 아니며 기존 `subprocess.run` 최종 JSON, 모델·인증 runtime·요청된 compaction은 유지한다.
Codex/Anthropic Claude에는 이 collector나 새 telemetry 필드가 없다.

자식 한 번에만 `CLAUDE_CODE_ENABLE_TELEMETRY=1`,
`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`, `OTEL_TRACES_EXPORTER=otlp`,
`OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json`, random-token loopback
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_TRACES_EXPORT_INTERVAL=1000`을 설정한다.
`OTEL_LOGS_EXPORTER`와 `OTEL_METRICS_EXPORTER`는 `none`이며 `OTEL_LOG_`의
USER_PROMPTS/ASSISTANT_RESPONSES/TOOL_DETAILS/TOOL_CONTENT/RAW_API_BODIES/MANAGED_SETTINGS는
모두 `false`다. 상속 OTEL·beta tracing·propagation·content/destination/raw-log overrides를
먼저 제거한다. `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`을 유지하고 자식 `no_proxy`와
`NO_PROXY`에 loopback을 추가한다. 기존 모델 HTTP proxy·부모 환경·설정 파일은 바꾸지 않는다.
bind/setup 실패는 exporter를 모두 끈 채 원래 CLI를 한 번 실행하고 unavailable로 남긴다.
계측 오류를 이유로 retry/fallback/추가 모델 호출을 하지 않는다.

private `telemetry.version=glm-call-telemetry-v1` 계약은 다음과 같다. 숫자는 finite·비음수이며
bool을 숫자로 받지 않는다. 시간은 ms, 결측은 `null`이다. 설명 없는 0으로 결측을 채우지 않는다.

| 필드 | 의미 |
| --- | --- |
| availability / completeness | completed request 관측 시 observed, 없으면 unavailable; export 누락을 증명할 수 없어 completeness는 항상 partial |
| outcome | success / child_failed / timeout / interrupted / spawn_failed / invalid_response; 연구 후보 유효성은 별도 participation.status |
| setup_failed / invalid_input / limited | 고정 boolean 진단; 원문 오류·endpoint·ID·경로는 보존하지 않음 |
| requests | 시작 시각 순 최대128개 unique completed llm_request; start_offset_ms는 parent launch 기준, duration_ms는 재시도 포함 lifecycle, ttft_ms·first_content_ms는 그 요청의 latency, attempt는 총 transport 시도 수, success와 네 token counter는 결측 허용 |
| logical_requests_observed | retained completed request 수; 무관측이면 null, 제한 시 전체의 하한 |
| transport_attempts_known / retries_known | attempt가 알려진 요청만 합산 / 각 attempt-1 합산; 전부 미상이면 null |
| requests_with_unknown_attempts / unexported_requests_unknown | 보존 요청의 attempt 결측 수 / unfinished·미수출·숨은 CLI/SDK 요청 존재 여부를 알 수 없다는 true |
| first_request_ttft_ms / first_request_content_ms | 시작이 가장 이른 요청의 값; 나중 요청 값으로 대체하지 않음 |
| launch_to_first_ttft_ms / launch_to_first_content_ms | 그 첫 요청의 launch-relative start offset + 해당 latency; process 완료 시간이 아님 |
| request_work | duration/TTFT/content/token별 known_count·total·max; 미관측 total/max는 null |
| tools / tool_work | 최대128개 tool parent와 memory-only parentSpanId로 연결한 execution; Read/Glob/Grep/other만 보존 |
| unmatched_execution_spans | parent가 없는 execution 수; 누락/여러 execution의 불확실성을 wall로 메우지 않음 |
| cli_wall_ms / cli | 부모 subprocess wall / 별도 final JSON duration_ms·duration_api_ms·num_turns·네 token counter; span의 대체값 아님 |
| parent | 연구 부모의 context_preparation_ms·source_verification_ms; GLM Read 실행과 별개 |

네 token counter는 input_tokens/output_tokens/cache_read_tokens/cache_creation_tokens다.
`tools[].execution_observed=true`는 execution child가 하나로 연결되었다는 뜻이며 결측/모호함은
null이다. `tool_work.Read.execution_count_observed`는 이렇게 연결된 실제 body span 수다.
execution_known_count/execution_total_ms/execution_max_ms는 duration이 알려진 body 관측이며
execution_unknown_timing_count는 body span은 있으나 duration이 미상인 수다. wall_known_count/wall_total_ms/wall_max_ms는 권한 대기+실행이며
missing_execution_count는 body 관측이 없는 parent 수다. Glob/Grep은 검색으로 따로 집계한다.
Read 도구 body도 정확한 물리 disk I/O 시간이 아니다. 병렬 tool/request 합계는 겹칠 수 있어
wall에서 work 합계를 빼서 정확한 overhead라고 부르지 않는다. num_turns와 tool 수는 API 호출 수가 아니다.

요청 body 256KiB, 전체 입력4MiB(header 포함), 처리 span4096개, memory-only ID map2048개,
request/tool rows 각각128개, header8KiB, peer 절대 읽기 기한0.5초와 socket timeout0.1초를 둔다.
collector 수명은 호출 timeout+1초(최대3601초)이며 CLI 종료 경로에서 즉시 닫는다.
시간 값은 개별3600000ms, token/turn counter는10억, attempt는1..1000까지 받는다.
따라서 각 telemetry의 JSON 크기도 고정된 row/field 상한으로 제한된다. 초과는 limited 또는
invalid_input/결측으로 남는다. POST·정확한 비밀 경로·명시 Content-Length·JSON만 받고
압축/chunked/중복 header·잘못된 envelope는 거부한다. 정상 수신 응답은 `{}`다.
ID는 join/dedup 뒤 메모리에서만 사라지고 raw payload/events/resource/session/content는 저장하지 않는다.
성공·실패·spawn 오류·timeout·interrupt 모두 socket/thread를 닫으며 stalled peer도 정리를 붙잡지 못한다.

기본 GLM 실행 report와 [기존 연구 private 기록](improvements.md#private-glm-지연-기록-읽기)에만
정제된 관측이 남는다. timeout 때 현재 요청은 아직 export되지 않을 수 있고 완료한 이전 요청만
남는다. 무응답은 unavailable이지 0회 측정이 아니다. 계측은 모델 실패·응답 파싱 실패·후보
검증 실패를 성공으로 바꾸지 않는다. 새 raw stdout/stderr 보존도 추가하지 않는다.

메인이 제공한 Claude Code2.1.294/Z.ai glm-5.3-flash 합성 Read 관측은 built-in exporter의
호환 근거다. 이 구현의 검사 성공이나 실제204~500초 연구의 병목 원인을 증명하지 않는다.
새 offline 검사·full make check와 합성 live 확인은 parent, 이후 정상 admission된 GLM hourly
관측은 main 책임이다. 이번 worker는 실행하지 않았다. 공식 참조는
[monitoring usage](https://code.claude.com/docs/en/monitoring-usage)이며 worker는 browse하지 않았다.
결정은 [ADR0019](adr/0019-private-glm-call-telemetry.md)에 기록한다.
