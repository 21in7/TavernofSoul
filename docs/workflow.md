# 개발 작업 자동 배정과 실행

`harness/workflow.py`는 작업 접수부터 검토·검증·파일 반영과 GitHub 게시 준비까지 연결한다.
메인 Codex `/root`는 파일 범위를 조사하고 요청을 전달하는 조정 역할이다.
구현·검토는 `harness/agent-models.json`의 역할별 CLI와 인증을 실제로 사용한다.
Codex 앱의 내장 서브에이전트 목록과 별개인 프로세스이므로 역할의 실행 상태는
이 실행기의 터미널 출력과 private JSON 보고서에서 확인한다.

```text
/root: 사용자 요청과 개별 파일 범위 준비
  → 준비: 승인 파일 모델 사본 / 전체 로컬 검증 사본 분리 + 하네스 doctor
  → Jev: 영역·복잡도·계약 영향 판단
  → 배정: 명확한 작업은 담당자 직행, 나머지는 Codex coordinator 계획
  → 구현: downloader(GLM) / parser(Codex) / django(Codex) / 공통 영역(coordinator)
  → 검토: Claude reviewer의 구조화한 승인 또는 수정 요청
  → 검증: 실행기가 필수 오프라인 하네스 검사
  → 반영: 실행 전 원본과 충돌이 없는 검증된 파일만 교체
  → GitHub: git(Codex medium)이 설명 작성 → 메인 /root의 앱으로 커밋·브랜치 게시·PR
      → SQLite·MySQL·Chromium CI 성공 확인 → head SHA를 고정해 squash merge
```

공통 영역은 Makefile·하네스·문서 등이다. JSON 계약처럼 여러 영역이 연결되면
coordinator가 계획한 뒤 각 파일을 실제 소유 영역의 모델에 배정한다.
영역 담당자를 새로 실행하는 주체는 실행기이며 작업자 자신의 재위임은 끈다.
첫 버전은 담당자를 **순차 실행**한다. 모든 작업에 모든 모델을 호출하지 않는다.

## 실행

작업 설명은 UTF-8 텍스트로, 모델이 읽거나 변경할 파일은 저장소 상대 경로를 한 줄에 하나씩 적는다.
`FILES_FILE`은 **외부 모델에 제공할 소스의 승인 목록**이기도 하다. 소스 외에 모델이 읽어야 할
테스트·문서·새 파일도 미리 포함한다. 디렉터리 전체를 범위로 지정하지 않는다.
`READ_ONLY=1`은 파일 변경만 막으며 읽기 승인 범위는 같은 목록으로 제한한다.
목록 밖의 AGENTS.md·아키텍처 문서·관련 소스는 자동으로 추가하거나 프롬프트에 넣지 않는다.
AGENTS.md의 조정 지침에 따라 Codex가 이 두 파일을 `logs/harness/`에 준비할 수 있다.

```bash
make agent-workflow-plan FILES_FILE=/tmp/task-files.txt
make agent-workflow TASK_FILE=/tmp/task.txt FILES_FILE=/tmp/task-files.txt

# 실행 중 다른 터미널에서도 현재 단계·역할·모델 확인
make agent-workflow-status
make agent-workflow-status RUN_ID=보고서의_run_id

# 등록된 모델을 사용해 읽기 전용 분석·검토·검증
make agent-workflow TASK_FILE=/tmp/task.txt FILES_FILE=/tmp/task-files.txt READ_ONLY=1

# Jev 접수 API만 생략; 구현·검토 모델은 실제로 호출
make agent-workflow TASK_FILE=/tmp/task.txt FILES_FILE=/tmp/task-files.txt RULES_ONLY=1

# 사용자가 로컬 작업만 요청한 경우
make agent-workflow TASK_FILE=/tmp/task.txt FILES_FILE=/tmp/task-files.txt GIT=0

# 키·네트워크 없이 단계 연결과 작업 사본의 변경만 시연
make agent-workflow-demo
```

기본 `agent-workflow`는 실제 모델을 호출하고 승인·검증 뒤 범위 내 파일을 반영한다.
`WRITE=1`을 별도로 요구하는 개별 `agent-run`과 동작이 다르다.
하네스 Python이 별도 환경이면 `PYTHON=/path/to/python`을 지정한다.
Jev는 등록된 TypeSafe 키로 접수 판단을 요청한다. 키 누락·오류·낮은 확신은
coordinator 계획과 전체 `check`로 넘어가며, 기록에서 fallback을 명시한다.
Claude/GLM의 기존 대화 압축 설정도 유지한다.

Jev 접수의 DNS/전송 실패와 이후 coordinator의 Codex 초기화 실패는 별도 단계다.
예를 들어 `api.typesafe.ai` DNS 조회의 `gaierror(-3)`는 Jev 보고서의
`fallback_reason=network_error`, `diagnostic={"error_type":"gaierror","errno":-3}`로 남는다.
fallback은 Jev 판단 대신 coordinator 계획과 전체 검증이 필요하다는 뜻이며 Jev 연결 성공을 뜻하지 않는다.
계획에 필요한 Codex까지 초기화에 실패하면 workflow는 실패하고 원본 파일은 반영하지 않는다.
필수 전체 `check`는 정상적으로 후속 단계에 도달했을 때 실행기가 수행하며, fallback 기록만으로
계획·검증이 실제 실행되었거나 통과했다고 해석하지 않는다.

Jev의 두 자리 probability·score가 독립적으로 반올림된 경우 probability 합은
`max(0.001, len(options) * 0.005)`, score와 가중평균의 차이는
`max(0.001, 0.005 * (1 + sum(level indices)))`의 절대 오차까지 경계값을 포함하여 허용한다.
상대 오차는 적용하지 않는다.
정확 경계의 이진 부동소수점 표현 오차에만 `FLOAT_COMPARISON_EPSILON=1e-12`를 더한다.
허용 한계를 `1e-10` 초과하는 편차는 계속 거부하며, 원본 반환 숫자는 변경하지 않는다.
3개 score level `0, 1, 2`에서는 각각 `0.015`, `0.02`이며, 정확한 legend를 가진
score `0.07` / probabilities `{'0': 0.94, '1': 0.06, '2': 0.0}` / confidence `0.91`은 `passed`다.
반올림된 probability 합 `0.99`·`1.01`도 이 범위 안이면 허용한다. 원본 probability·score·confidence와
기존 라우팅 임계값을 보존하며 재정규화·score 대체·자동 재시도·모델 변경·네트워크 확대는 하지 않는다.
범위 밖 숫자·bool·NaN·Inf·다른 legend·누락/추가 label·choice 최댓값 위반은 계속 거부한다.
오차 한도를 넘는 응답은 `invalid_response` fallback으로 coordinator 계획과 전체 `check`를 요구한다.
triage의 추천은 허용 응답과 fallback 모두 `execution_allowed=false`이며 에이전트를 실행하지 않는다.

Jev 진단은 허용된 `error_type`과 선택적인 정수 `errno`, HTTP 실패의 정수 `http_status`로 제한한다.
Codex 진단은 `stage`와 고정 `category`로 구분하며 PATH aliases의 읽기 전용 오류는
`path_aliases_read_only`다. 키·인증 내용·예외 원문·원격 오류 응답 본문을 진단으로 노출하지 않는다.
필드와 분류는 [에이전트 모델 연결](agent-models.md)의 실패 진단 설명을 참고한다.
`agent-doctor`는 로컬 설정·런타임·로그인 상태만 확인한다. 외부 DNS와 실제 모델 연결은 운영자가
명시적으로 요청한 `agent-smoke`/`triage-smoke`로 별도 확인하며, 이때도 네트워크 권한은 자동 확대하지 않는다.
private 런타임이 정상 생성되거나 doctor가 통과해도 외부 DNS 문제가 해결되었다고 보고하지 않는다.

`agent-workflow-plan`은 경로별 담당자와 단계만 보여주며 키 파일·모델을 사용하지 않는다.
`agent-workflow-demo`는 모델 응답과 검증 결과 모두 fixture다. `simulated=true`,
`status=demonstrated`, `agent_started=false`로 기록하며 실제 에이전트나 검증 성공으로 보고하지 않는다.

## 검토와 검증 기준

계획은 선언된 파일을 정확히 한 번씩 담당 역할에 배정해야 한다. 모델이 새로운 파일을
추가하거나 소유 영역을 바꾸면 실행을 중단한다. 범위가 부족하면 `/root`가 원인을 확인하고
필요한 소스·테스트·문서를 포함해 새 실행을 준비한다.

reviewer의 정상 CLI 응답만으로 승인 처리하지 않는다. `verdict`, `summary`, `findings`의
JSON을 검사하며 `approved`는 빈 findings를 요구한다. 읽기 전용 역할이 파일을 바꾸면 실패다.
수정 요청이나 필수 검증 실패는 같은 담당자에게 전달하고 **새 검토와 검증**을 받는다.
전체 로컬 검증의 상세 로그·traceback에는 승인 밖 소스가 섞일 수 있어 모델에 전달하지 않는다.
재수정 요청에는 허용된 검사 명령명과 실패 상태만 넣는다. 진단 정보가 더 필요하면 `/root`가
로컬 로그를 조사하고, 외부 분석에 필요한 개별 파일을 승인 범위에 포함한 새 실행을 준비한다.
`harness/workflow-config.json`의 `max_rounds=2`가 총 구현 라운드 한도다.
한도를 넘거나 모델 실행·출력 형식·범위 검사에서 실패하면 원본을 반영하지 않고 종료한다.
읽기 전용 실행은 검토·검증 실패를 재수정하지 않는다.

검증 명령은 실행기의 허용 목록에서만 선택하며 모델 응답으로 셸 명령을 실행하지 않는다.
경로 규칙·Jev 추천·계획의 파일 소유 영역 중 가장 넓은 필수 검증을 유지한다.
계약·하네스·영역 간 작업과 coordinator fallback은 전체 `check`를 실행한다.
종료 코드뿐 아니라 이번 실행의 JSON에서 실제 선택된 테스트 수, 성공 수, 실패·오류·skip을 검사한다.
빈 검사·skip/xfail·누락 보고서·이전 성공 결과는 통과로 처리하지 않는다.
검증이 소스 파일을 변경한 경우에도 반영을 중단한다.

## 사용자 변경과 실행 경계

**모델 사본**은 `/tmp/tavern-model-context-*/sources/`에 명시한 파일만 현재 내용 그대로 복사한다.
전체 저장소의 파일 목록을 탐색해 추가하지 않으며, 모델 실행의 cwd도 이 사본으로 제한한다.
원본 저장소의 상위 지침이 자동 발견되지 않도록 저장소 밖에 만든다.
`model-context.json`에는 승인 목록과 실제 복사한 파일의 hash·권한을 남긴다.
새 파일이나 삭제한 파일은 목록에는 남되 실행 전 사본에 내용이 없다.

Codex는 `:root=deny`, `:minimal=read`, 모델 사본에 읽기 전용 실행은 `read`, 편집 실행은 `write`인
별도 권한 프로필을 사용한다. 승인 소스만 있는 사본에는 Git metadata와 사용자 신뢰 기록이 없으므로
`--skip-git-repo-check`를 전달하며 파일 권한이나 승인 범위를 확대하지 않는다.
실행에 필요한 설치된 Codex 바이너리와 해당 셸 실행 파일만 추가로 읽게 한다. CLI 인증·하네스 설정·압축 플러그인은
실행기가 사용하는 런타임이며 원본 소스를 모델용 context로 제공하는 경로가 아니다.
Codex CLI는 호출마다 쓰기 가능한 private 임시 런타임을 사용한다. 루트·하위 런타임 디렉터리는
`0700`, 기존 로그인에서 복사한 유일한 인증 파일 `auth.json`은 `0600`이다.
자식의 `CODEX_HOME`·임시 경로·XDG 경로만 분리하고 기존 로그인·설정과 부모 환경을 보존한다.
사용자 설정·지침·skill·다른 인증 파일·keyring은 복사하지 않고 인증 사본의 갱신도 원본에 반영하지 않는다.
로그인 확인과 해당 역할 실행 동안만 사본을 유지하고 성공·실패·timeout 뒤 정리한다.
생성·정리 실패는 실행 실패이며 실제 사용자 home으로 fallback하지 않는다.
강제 종료로 남은 런타임은 프로세스 종료를 확인한 뒤 별도로 정리한다.
임시 `runtime_root`는 workspace 안에 있더라도 모델 권한 프로필에서 명시적으로 `deny`한다.
원본 인증 home(original auth_home)은 `:root=deny`로 보호하고 별도의 directory deny를 추가하지 않는다.
Linux의 directory deny는 auth_home 아래 standalone CLI·셸 실행 파일의 좁은 read 예외까지 가려
실제 파일 도구에 permission denied를 일으킬 수 있다. 실행 파일을 포함하는 디렉터리 전체를 허용하지 않는다.
workspace와 original auth_home을 resolve한 뒤 workspace가 auth_home과 같거나 이를 포함하는 상위 경로이면
`unsafe_workspace`로 거부한다. symlink와 `..`로 표현한 경로에도 이 조건을 적용한다.
모델의 승인 파일 읽기 범위와 `network.enabled=false`를 유지하며 DNS 제한을 자동 해제하지 않는다.
런타임 격리는 CLI 초기화 쓰기를 분리하는 조치이고 외부 Jev DNS 복구를 보장하지 않는다.
기존 `--sandbox read-only`는 원본 파일 읽기를 제한하지 않으므로 이 프로필과 함께 사용하지 않는다.
사용자 설정·프로젝트 지침 자동 로딩·웹 검색·앱·브라우저·컴퓨터 도구·호스트 skill 검색을 끈다.
지원하지 않는 프로필/CLI 옵션이나 샌드박스 실패는 실행 실패로 처리하며 넓은 읽기 권한으로 재시도하지 않는다.
Claude/GLM은 `--restricted`와 Read/Glob/Grep(+편집 시 Edit/Write)만 사용해 파일 도구를 cwd에 제한한다.
추가 읽기 디렉터리를 허용하지 않고 메모리·CLAUDE.md 로딩, 외부 MCP, 권한 확대 요청을 끈다.
압축 플러그인은 신뢰한 실행기 런타임에서 로딩하고 모델 소스 사본에는 복사하지 않는다.
CLI 권한 프로필의 동작은 [공식 Codex 문서](https://learn.chatgpt.com/docs/permissions)를 참고한다.

**로컬 검증 사본**에는 Git의 추적 파일과 무시되지 않은 새 소스를 현재 내용 그대로 복사한다. 커밋되지 않은
사용자 수정과 삭제를 보존하고, 원래 저장소의 Git metadata·API 키·`.env`·운영 INI·인증 파일,
게임 patch/unpack·JSON·번역·지역별 Python 환경·백업은 작업 사본에서 제외한다.
`harness/pytest.ini`는 인증 정보가 없는 필수 검증 설정이므로 복사한다.
이 사본을 모델의 cwd·추가 읽기 디렉터리로 제공하지 않는다. 모델의 범위 내 변경만 여기로 옮겨 검증한다.
작업 사본에는 기존 Git ignore 회귀 검사를 위한 빈 일회용 Git 저장소만 만들며 호스트 Git template도 복사하지 않는다.
개별 범위 파일과 복사할 소스의 symlink를 거부한다.
Claude Code가 자동 생성하는 `harness/compaction/.claude-plugin/types/`는
캐시·진행 로그처럼 실행 산출물로 제외하며 편집·반영할 파일 범위로 지정할 수 없다.

파일 반영 직전에 모든 복사한 원본 소스의 hash·권한과 목록이 실행 전 상태와 같은지 확인한다.
다른 편집이 있으면 새 내용을 보존하고 중단한다. 이전 내용은 private backup에 남기고,
파일별 임시 쓰기·교체를 사용한다. 도중 실패하면 실행기가 이미 반영한 자신의 변경만 복구한다.
여러 파일 교체는 파일별 원자 처리이며 저장소 전체의 원자 트랜잭션은 아니다.
프로젝트별 lock으로 두 자동 실행기의 동시 실행을 막는다. 외부 편집기는 hash 검사로 확인한다.

작업 사본 자체는 별도 VM이나 컨테이너가 아니다. 모델의 원본 소스 읽기 제한은 위 CLI 권한 설정에
의존하며, 인증과 신뢰한 CLI 런타임까지 격리하는 일반 목적 컨테이너를 제공하는 것은 아니다.
scoped 담당 worker는 승인 파일만 읽고 기존 사용자 수정을 보존하며 부족한 파일 범위를 보고한다.
검증은 orchestrator가 수행한다. worker는 테스트·`make check-*`·`harness.workflow`·`agent-run`·
cron·다운로드·운영 import(`importAll` 포함)·재위임을 실행하지 않는다.
기본 검증은 합성 입력·임시 JSON·SQLite 메모리 DB다. 운영 DB·실데이터·MySQL·브라우저 검증은
각각 명시적인 추가 실행으로 구분한다. 배포는 이 흐름에 포함하지 않는다.
기본 쓰기 작업의 GitHub 커밋·PR·병합은 아래 메인 Codex의 앱 연결로 이어 실행한다.
공급자 오류 시 유료 모델 전환이나 Opus escalation을 자동 호출하지 않는다.
호출별 Claude 예산과 라운드 한도는 유지하며 중앙 월 예산 집계는 별도 범위다.

## 진행과 결과

각 단계는 `[4/8 담당 에이전트 실행] running · parser / codex / gpt-6.1-sol`처럼 즉시 출력한다.
Jev 직접 배정에서는 계획 단계가 `direct`, Jev 실패에서는 판단 단계가 `fallback`이다.
검토의 `responded`는 모델 응답 완료이고 `approved`가 실제 승인이다.
`report.json`의 `current`와 `events.jsonl`에서 실제 실행된 역할·공급자·모델과 단계 상태를 확인한다.
메인 `/root`는 이 결과를 읽고 진행 상황을 사용자에게 알린다.

`logs/harness/workflows/<run_id>/`에 보고서, baseline hash, scoped diff, 검증 JSON·로그,
로컬 검증 사본과 반영 전 backup을 보관한다. `model_workspace`는 저장소 밖 모델 사본의 위치,
`model_read_scope`는 외부 분석 승인 목록이다. 상위 디렉터리는 `0700`, 통합 보고서·진행 기록·로그는
`0600`이며 등록된 API 키 값은 보고서와 요청의 작업 텍스트에서 제거한다.
작업 본문은 hash로 기록하고 계획·모델 응답은 private 보고서 안에만 둔다.
실패한 작업 사본은 조사를 위해 남는다. 저장 공간 관리는 사용자가 끝난 실행 디렉터리와
보고서에 기록한 `/tmp/tavern-model-context-*` 디렉터리를 함께 정리한다.
`passed`만 실제 완료이고 `failed`/`interrupted`는 실패다. `awaiting_github`는 앱 실행 대기,
`awaiting_ci`는 이미 생성한 PR의 CI 대기다. 프로세스를 강제 종료해 마지막
`running` 기록이 남았어도 상태 조회에서 PID가 더 이상 존재하지 않으면 `abandoned`로 표시한다.

## GitHub에 자동 반영

이 저장소의 기본 대상은 `21in7/TavernofSoul`, 기준 브랜치는 `master`다.
`harness/git-publish-config.json`에 대상과 필수 검사를 명시한다. 서버 GitHub 토큰을 새로 요구하지 않고
메인 Codex의 인증된 GitHub 앱을 사용한다. 실행 전에 메인은 해당 저장소의 앱 쓰기 권한을 확인한다.
`make agent-git-doctor`는 정책과 origin 일치만 검사하며 API 인증 성공을 뜻하지 않는다.
모델은 승인 소스를 읽어 commit_message·pr_title·pr_body만 반환한다. 저장소·브랜치·변경 파일·머지
방식은 모델 응답으로 결정하지 않는다. GitHub 토큰 환경 변수도 모델과 로컬 검증에서 제거한다.

메인은 `awaiting_github` 보고서의 run_id로 다음 요청을 읽고 반환된 앱 도구와 인자를 실행한다.
앱 응답은 private JSON 파일에 기록하여 request_id와 함께 돌려준다. 메인이 이 과정을 계속 수행하므로
사용자가 커밋·push·PR·merge 명령을 별도로 입력할 필요가 없다. CLI 단독 실행에는 앱 도구가 없어서
메인 Codex가 이어받을 때까지 대기하며, 서버의 상주 GitHub 봇을 설치하는 기능은 포함하지 않는다.

```bash
make agent-git-doctor
make agent-git-request RUN_ID=보고서의_run_id
# 메인 Codex가 반환된 request.tool(request.arguments)을 GitHub 앱으로 실행한 뒤:
make agent-git-accept RUN_ID=보고서의_run_id REQUEST_ID=요청_id RESPONSE_FILE=/private/path/response.json
make agent-git-resume RUN_ID=CI_대기중인_run_id
```

`github.json`은 대상·변경 내용·기준 SHA·단계·CI 결과를 private 로그에 기록한다. 별도 private
`github-approved.json`에 검토·검증된 파일 hash·권한과 게시 정책을 고정하며, 로드한 journal을 그 사본과
비교한다. journal과 승인 파일은 `0600`이어야 한다. 각 조회에도 새 무작위 요청 ID를 부여해 이전
조회 응답의 재사용을 막고, lock으로 동시에 같은 journal을 조작하지 못하게 한다.
응답 처리에서 반환된 다음 요청을 그대로 실행한다. 이미 전달한 쓰기의 `request`를 다시 호출하면
`needs_reconciliation`으로 중단하며 자동으로 같은 PR 생성·커밋 등을 다시 보내지 않는다.
응답 파일이 사라지거나 쓰기 결과가 모호하면 그 상태를 기록한다. 원래 요청 ID와 일치하는 실제
성공 응답이 뒤늦게 도착한 경우에는 확인 후 진행할 수 있다. PR은 실패·대기 중에도 앱 작업에 연결한다.
수정 라운드의 실패 기록은 남기되 GitHub 게이트와 PR 설명에는 마지막 성공한 라운드의 검증을 사용한다.

브랜치 생성 도구가 이름만 반환하면 실행기는 Git ref를 별도로 조회해 실제 SHA가 고정된 head와
일치하는지 확인한 뒤 PR을 생성한다. 이 확인에 실패하면 브랜치를 재생성하거나 PR을 열지 않는다.

로컬 index·브랜치·기존 staged 변경은 건드리지 않는다. 원격 기준 tree에서 해당 작업의 시작 파일
blob SHA와 권한을 확인한 뒤 변경 파일만 새 tree에 넣는다. 기준 tree는 변경 파일에 필요한 경로만
디렉터리별로 조회하므로 큰 게임 데이터의 전체 재귀 트리를 요구하지 않는다. 조회한 tree가 잘리면 중단한다.
새 `codex/<run_id>` 브랜치를 커밋 SHA에
생성하는 방식으로 push와 같은 게시 결과를 만든다. 모델 승인 범위 밖 파일과 기존 사용자 수정은
함께 게시하지 않는다. 기준 파일이 이미 수정됐거나 원격에 없는 기존 파일이면 쓰기 전에 중단한다.
현재 로컬에서 처음 만든 하네스·CI 파일을 게시하려면 초기 등록 파일 목록을 따로 확인해야 한다.
CI 정의가 원격에 없어서 필수 검사가 실행되지 않은 경우도 성공으로 간주하지 않는다.

PR은 pinned base/head와 같은 저장소인지 재확인하며 변경되면 재검증을 요구한다.
GitHub Actions의 `Offline harness (SQLite)`, `MySQL harness`, `Chromium browser harness`가 모두 실제
`success`여야 한다. 실행 중·누락·다른 앱이 만든 동명 검사·skip·neutral·실패·취소는 머지 성공이 아니다.
check-runs의 모든 페이지를 읽고 중복 ID·불완전한 coverage를 거부하며 같은 이름의 최신 실행만 판단한다.
테스트 merge SHA에 검사가 있으면 그 결과를 사용하며 없으면 head SHA 검사로 판단한다.
head와 테스트 merge 양쪽 SHA의 commit status 실패를 차단하고, 최종 PR 조회에서 테스트 merge SHA가
달라졌으면 새 SHA의 CI를 다시 확인한다.
필수 리뷰나 저장소 규칙이 남아 있으면 `mergeable_state=clean`까지 대기한다. 충돌·기준 변경은 중단하며
force·관리자 우회·저장소 보호 설정 변경은 하지 않는다. 머지 API에도 expected_head_sha를 전달한다.
API가 `merged=true`와 merge SHA를 반환한 뒤에만 전체 상태를 `passed`로 바꾼다.
30분 동안 검사와 규칙이 완료되지 않으면 PR을 보존하고 `awaiting_ci`로 기록한다.
`agent-git-resume`은 새 모델 호출·새 커밋·새 PR 없이 그 PR을 다시 확인한다.
