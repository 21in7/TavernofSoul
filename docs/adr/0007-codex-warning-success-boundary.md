# 0007. Codex 성공 증거 우선과 안전한 경고 metadata

- 상태: 승인(accepted) — 이번 요청의 새 결정이며 검사 성공을 뜻하지 않는다.
- 기록일: 2026-10-12
- 기록 성격: 새 결정
- 대체 관계: 없음. [0002](0002-explicit-model-read-scope.md)의 격리 결정을 유지한다.

## 문맥

메인이 제공한 조사 사실 요약에서 일반 workflow `1791729971212631163-d0abf4`는 Jev·Codex 계획이
통과했고 coordinator 편집 실행도 exit_code=0이었다. 그러나 `agent_models.run`이 엄격한 완료 응답
검증보다 stderr PATH aliases 읽기 전용 문자열의 실패 선판정을 앞세워
`execution/path_aliases_read_only`로 종료했고 완성 초안이 반영되지 않았다.
뒤의 별도 draft 복구는 통과했지만 일반 실행 경로는 고쳐지지 않았다.
`codex_login_status`에도 같은 선판정이 있었고 기존 zero-exit 경고 회귀가 이 잘못된 정책을 고정했다.

CLI 0.161.0에서 메인이 수행한 무추론 로컬 `--no-daemon --version` 비교는 호출마다 writable private
runtime을 쓰면 exit0/경고 없음, TMPDIR 등 나머지 private 경로를 유지하고 `CODEX_HOME=/sys`로
지정하면 exit0/동일 경고 있음을 보였다. 진행 가능한 warning이라는 관측이다.
이 worker가 해당 비교나 실모델 검증을 실행한 것은 아니다.
이전 raw stderr는 보안 정책상 저장하지 않아 최초 경고를 낸 하위 프로세스까지 확정할 수 없다.
모델 도구의 runtime deny가 하위 도구 런타임 초기화 경고를 유발할 수 있다는 설명은 추론으로 남긴다.
[공식 sandbox 문서](https://learn.chatgpt.com/docs/sandboxing)의 sandbox가 spawned commands에도
적용된다는 설명은 일반 경계의 참고이며 PATH aliases 구현이나 최초 경고 발생 위치의 증거가 아니다.
private 로그는 이 사실 요약만 기록하고 모델 응답·인증·stdout/stderr 원문은 복사하지 않는다.

## 결정

성공 증거를 검증한 뒤 경고와 실패를 구분한다. `login status`는 exit0와 정확한 ChatGPT 로그인 상태
행을 요구하며 API 키 로그인(모순되는 상태 포함), 누락/잘못된 상태는 거부한다.
역할 실행은 exit0, JSON event 행 파싱과 객체 event, failed/error event(`turn.failed`/`error`) 없음,
유효한 비어 있지 않은 문자열 최종 agent_message, `turn.completed`를 모두 요구한다.
smoke는 무작위 nonce 일치까지 검사한다. PATH aliases 읽기 전용 경고 단독은 유효한 ready/passed를
실패로 만들지 않는다. warning은 어떤 성공 조건의 대체 증거도 아니다.

nonzero exit, 인증 실패/API 키 로그인, 실패 event, malformed/미완료/빈 응답, timeout, nonce 불일치,
runtime 생성·정리 실패는 계속 실패시킨다. nonzero에서 PATH aliases 메시지는 실패 category로
분류할 수 있다. exit0의 응답 검증 실패는 경고로 덮지 않으며 invalid_response(인증 오류가 확인되면
인증 실패)로 보고한다. 신뢰되지 않은 응답과 stdout/stderr 원문을 실패 보고서에 저장하지 않는다.
모든 검증을 통과한 최종 모델 응답만 기존 private 보고서에 보존한다.

private 보고서에 `warnings` 목록을 둔다. 현재 항목은 고정된 `stage`(authentication/execution)와
`category`(path_aliases_read_only)뿐이며 단계당 하나, 없으면 빈 목록이다. 경고 원문·경로·비밀은 없다.
유효 인증의 warning은 역할 실행 보고서까지 전달하고 실행 warning과 함께 보존한다.
실행 warning이나 앞선 인증 warning은 후속 실패 보고서에도 남을 수 있지만 실패를 구제하지 않는다.
`workflow.model_step`은 결과 전체를 agents에 기록하고 passed와 scope를 검사한다.
새 Claude review/documentation·필수 check·충돌 검사·apply·Git 역할·GitHub/CI/merge 게이트는 유지한다.

private runtime root/하위 디렉터리0700, auth0600, 모델 도구의 runtime deny, :root deny/:minimal read,
좁은 승인 source/CLI/셸 실행 파일 예외, network=false를 유지한다. 경고를 없애기 위해 인증 runtime의
도구 읽기/쓰기를 허용하지 않는다. no fallback/no retry/no permission expansion과 safe diagnostics,
기존 CLI/model/roles/예산/source scope는 바꾸지 않는다.

## 비교 대안

| 대안 | 평가 |
| --- | --- |
| stderr 경고만으로 실패 선판정 유지 | 유효한 exit0 완료를 거부하며 일반 workflow의 반영을 막는다. |
| 경고가 있으면 성공으로 처리 | 비정상 종료·실패 event·불완전 응답을 통과시켜 신뢰 경계를 무너뜨린다. |
| auth runtime을 모델 도구에 허용 | 경고의 근본 발생 위치도 미확정이며 인증·캐시 보호 경계를 약화한다. |
| 성공 증거 검증과 고정 경고 metadata 분리 | 유효 완료를 허용하면서 실패 조건·격리·후속 게이트와 관측을 유지한다. |

## 선택 이유

메인의 무추론 비교에서 같은 초기화 메시지가 exit0와 공존했다. 메시지 자체로 작업 실패를 확정할
근거가 부족하며 실제 CLI 성공과 엄격한 완료 응답을 확인하는 것이 판정의 근거다.
경고 metadata를 남기면 인증과 실행 중 어느 단계에서 관측됐는지 알 수 있으면서 원문·비밀을 노출하지 않는다.
발생 위치에 대한 미확정 추론을 권한 확대의 근거로 사용하지 않는다.

## 결과·비용·제약

정상 일반 workflow에서 유효한 Codex 완료는 다음 게이트로 진행할 수 있다. warning이 있어도 failed/error,
잘못된/빈/미완료 응답, nonzero, nonce 불일치는 차단된다. 성공은 모든 후속 검토·검증·반영·게시 조건을
충족해야 전체 완료가 된다. 별도 draft seed/recovery를 수리 검증이나 성공 경로로 사용하지 않는다.
원문 없는 metadata는 최초 하위 프로세스나 파일 경로를 식별하지 못하며 다른 stderr 경고의 일반 탐지기도 아니다.

오프라인 회귀는 유효 ChatGPT 로그인+경고 ready, completed+경고 passed, 인증·실행 warning 전달,
nonzero+경고 실패, 경고와 malformed/미완료/failed/error/빈 응답·nonce 불일치 실패,
원문·비밀 미노출 및 runtime 정리를 다룬다. 기존 실제 보안 제한 회귀는 유지한다.
수리 worker는 테스트·검사·workflow·실모델·Git·운영실행을 수행하지 않았다.
메인/orchestrator가 새 Claude 문서 의미 검토, full make check, 일반 Codex 도구 편집 실호출,
Git 역할과 GitHub PR/CI/merge를 별도로 수행해야 한다. Markdown 형식 검사는 문서 의미 완전성의 증명이 아니다.

## 관련 코드·검증·문서

- [agent_models.py](../../harness/agent_models.py): codex_login_status/run/codex_warnings와 실패 분류.
- [test_agent_models.py](../../harness/test_agent_models.py): offline 경고·실패·격리·정리 회귀 명세, 이 worker 미실행.
- [workflow.py](../../harness/workflow.py): model_step의 전체 보고서 보존과 후속 게이트, 소스 참조만 수행.
- [test_workflow.py](../../harness/test_workflow.py): 후속 gate 회귀 참조, 수정·실행하지 않음.
- [모델 연결](../agent-models.md), [전체 설계](../harness-design.md), [workflow](../workflow.md).
- [0002](0002-explicit-model-read-scope.md): 변경하지 않은 격리 결정, 관련 링크만 보완.
