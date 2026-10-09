# 에이전트 모델 연결

`harness/agent-models.json`은 역할별 공급자·모델·추론 수준과 관련 검증 명령을 지정한다.
`harness/agent_models.py`는 기존 Codex/Claude Code CLI를 실행한다. 별도 Python SDK 설치는 필요 없다.
다운로드·파싱·Django 운영 프로세스에는 연결하지 않으며 개발 작업에만 사용한다.
역할을 자동으로 배정하고 검토·검증 뒤 반영하는 실행기는 [자동 작업 실행](workflow.md)을 참고한다.
담당 역할을 선택하기 전의 Jev 판단·비교 로그는 [Jev 작업 판단](triage.md)을 참고한다.
`typesafe`는 별도 REST 판단 공급자이며 아래 구현 역할에 CLI 모델로 배정하지 않는다.
Claude Code 기반 역할은 [Jev 대화 기록 압축](compaction.md)을 기본 적용한다.
기존 TypeSafe 키를 재사용하며 `COMPACTION=0`으로 해당 실행에서 끌 수 있다.

| 역할 | 실행 도구 / 인증 | 모델 | 관련 검증 |
| --- | --- | --- | --- |
| coordinator | Codex / ChatGPT Pro 로그인 | gpt-6.1-sol, high | make check |
| downloader | Claude Code / Z.ai Coding Lite 키 | glm-5.3-flash | make check-downloader |
| parser | Codex / ChatGPT Pro 로그인 | gpt-6.1-sol, high | make check-parser |
| django | Codex / ChatGPT Pro 로그인 | gpt-6.1-sol, medium | make check-django |
| git | Codex / ChatGPT Pro 로그인 | gpt-6.1-sol, medium | 검증 결과로 커밋·PR 설명 작성; 게시·CI·머지는 메인 앱 연결 |
| reviewer | Claude Code / Anthropic API 키 | claude-sonnet-5-5, medium | make check |
| escalation | Claude Code / Anthropic API 키 | claude-opus-5-5, high | make check |

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
로그인이나 키 존재만으로 연결 성공을 보고하지 않는다. 실패 응답·미완료 이벤트·예산 초과도 실패다.
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
예를 들어 PATH aliases의 읽기 전용 파일시스템 오류는 `path_aliases_read_only`,
인증 문제는 `authentication_failed`, 생성·정리 문제는 `runtime_unavailable`이다.
그 밖에 `missing_cli`, `auth_file_unavailable`, `timeout`, `cli_failed`, `invalid_response`,
`probe_mismatch`로 구분하며 고정된 오류 설명을 제공한다. 실패한 CLI의 stdout/stderr 원문,
원격 오류 응답·인증 내용은 진단 보고서에 저장하지 않는다. 정상 모델 응답은 기존 private 보고서에 저장한다.
실패 시 더 넓은 파일 읽기나 네트워크 권한으로 자동 재시도하지 않는다.
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
scoped workflow의 담당 worker는 테스트를 실행하지 않으며 orchestrator가 검증을 수행한다.

- [Codex 인증과 헤드리스 로그인](https://learn.chatgpt.com/docs/auth)
- [Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Claude Code CLI 옵션과 비용 추정 한도](https://code.claude.com/docs/en/cli-reference)
- [Claude Code bare 실행과 API 키 인증](https://code.claude.com/docs/en/headless)
- [Z.ai Coding Lite 모델·사용량](https://docs.z.ai/devpack/overview)
- [Z.ai의 Claude Code 연결](https://docs.z.ai/devpack/tool/claude)
- [Claude 모델과 API 가격](https://platform.claude.com/docs/en/about-claude/pricing)
