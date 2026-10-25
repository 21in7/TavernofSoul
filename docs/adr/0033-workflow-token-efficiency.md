# 0033. Workflow의 중복 입력 제거와 실제 CLI usage 관측

- 상태: 제안(proposed), 새 Claude 의미 검토·parent full check·실제 usage 관측·Git 전달 대기
- 기록일: 2026-10-25
- 기록 성격: 새 결정
- 대체 관계: 없음. 모델·역할·effort·인증·예산·승인·검토·검증·Git 정책을 유지한다.

## 문맥

parent가 제공한 직전 성공 `1792933618990220491-1bd1b1`은 계획/구현/검토/Git의
역할 모델 호출이 4회였으며 actual usage는 기록되지 않았다. 이전 실패 실행의 검토에는
여러 구현 시도 결과가 누적됐다. 이 관측은 새 구현의 성공·절감량 증거가 아니다.
원요청을 배정 지시로 다시 넣는 direct 경로, 반복 scope와 JSON escape도 입력을 늘린다.
CLI가 보고하는 토큰을 응답 문자 수나 로컬 추정치로 대체하지 않고 별도 관측해야 한다.

## 결정

`workflow.execute`가 관측한 Jev recommendation의 role과 **모든 승인 경로의 owner가
동일한 한 역할**일 때만 planner를 생략한다. coordinator도 같은 조건을 적용해 원요청과
전체 승인 파일을 가진 task 하나로 직접 배정한다. 읽기 참고 파일도 이 task의 files에 둔다.
추천 불일치 또는 mixed ownership이면 기존 planner·strict parse·plan repair·ownership 및
실패 gates를 유지한다. Jev 판단, 구현, 새 Claude 검토와 Git 역할은 계속 실행한다.
수리 없는 all-coordinator의 역할 모델 호출은 4→3회다. 이를 토큰 25% 절감으로 해석하지 않는다.

프롬프트 구성은 `workflow_prompts.py`에 추출한다. 원요청을 항상 유지하며 배정 문자열이
원요청과 완전히 같을 때만 두 번째 삽입을 생략한다. 다른 배정은 공백 차이까지 보존한다.
JSON은 `ensure_ascii=False`, `separators=(',', ':')`로 렌더링한다. 경로 문자열·목록 순서·
개별 edit/read scope를 바꾸지 않는다. edit와 read 목록이 같으면 한 목록을 명시적으로 참조하고,
다르면 각각 그대로 제공한다. review의 읽기 목록은 공통 첨부 한 번으로 제공한다.
원요청·repair feedback·현재 전체 diff·문서 판단 계약·편집 scope는 생략하거나 요약하지 않는다.

review에는 실제 task 목록에 속한 명시적 정수 task_id별 최신 구현 응답을 각각 한 번 제공한다.
ID가 없거나 null/잘못된 형식/알 수 없는 ID인 항목은 같은 task라고 추정하지 않고 각각 보존한다.
여러 task의 결과를 합치지 않는다. 원본 agents/report·repairs·events의 이전 시도와 실패는
삭제하지 않는다. reviewer는 매번 최종 전체 diff·코드·문서를 독립 판단하고 이전 승인을
정답 근거로 쓰지 않는다. 매 review의 `documentation={status,files,reason}`은 필수이며,
문서 완전성은 semantic reviewer가 판단한다. Git에도 현재 full diff를 제공한다.

scoped leaf에는 필요한 승인 파일의 관련 부분부터 읽고 이미 전달된 diff·결과의 중복 대량
출력/재읽기를 피하도록 안내한다. 필요하면 승인 파일 전체를 읽을 수 있고 전체 검토 scope는
유지한다. source를 요약으로 바꾸거나 추가 유료 요약 호출을 만들지 않는다.
기존 `project_doc_max_bytes=0` 등 CLI·보안 설정은 변경하지 않는다.

## Usage 데이터 계약

stdlib 전용 `agent_usage.py`는 실제 stdout의 알려진 top-level final만 읽는다. Codex는
유일한 마지막 `turn.completed`, Claude/Z.ai는 명시적 정상 `type=result`, `subtype=success`,
`is_error=false` final의 usage만 관측한다. discovery stream도 유일한 result를 요구하며
뒤의 알려진 rate_limit_event 안내만 허용한다. 기존 Read proof 검증을 대체하지 않는다.
중복 JSON key/완료, 불명 envelope, tool/stdout 내부의 usage·자유 텍스트는 근거가 아니다.

private 역할 결과와 workflow agents에 `usage`(agent-usage-v1)를 기록한다. source·status·
input_tokens_semantics는 고정 enum이고 숫자 필드는 유효한 0..1,000,000,000 정수만 받는다.
bool·음수·float·비유한·과대값은 관측값이 아니다. legacy/누락/모호한 자료는 unavailable,
unknown 또는 null이다. 부분 관측은 partial이며 누락을 0으로 채우지 않는다.

- Codex `input_tokens`는 캐시 포함이다. `cached_input_tokens`는 그 부분집합,
  `output_tokens`와 optional `reasoning_output_tokens`는 별도 보존한다. reasoning은 output의
  부분집합으로 다루며 다시 더하지 않는다. total_input=input, uncached=input−cached이며,
  각각 필요한 숫자가 있을 때만 계산한다. total=input+output으로 캐시를 이중 합산하지 않는다.
- Claude/Z.ai `input_tokens`는 캐시 제외다. `cache_read_input_tokens`,
  `cache_creation_input_tokens`, `output_tokens`를 구분한다. total_input은 input+read+creation을
  모두 관측했을 때만, total은 여기에 output까지 있을 때만 계산한다. uncached는 관측 input이다.
- `prompt_size={characters,utf8_bytes}`는 실제 CLI stdin prompt 문자열의 크기다. CLI가 더하는
  system/tool/file 문맥이나 전체 요청의 token 수를 뜻하지 않으며 billed tokens가 아니다.

원문 응답·경로·credential·전체 JSON을 새 관측 필드에 보관하지 않는다. 측정 실패는 모델
성공/실패·기존 cost·진단·승인 판단을 바꾸지 않는다. 기존 `response_text(provider, output)`의
서명과 `(response,cost)` 반환, CLI 연결, discovery Read proof, GLM telemetry collector와
cost ledger는 유지한다. public web/completion payload에는 새 필드를 추가하지 않는다.
실패한 CLI 호출의 사용량도 근거가 없으면 unavailable이며 무료였다고 해석하지 않는다.

## 비교 대안

planner를 항상 호출하면 단일 소유권 재배정에도 호출이 든다. 모든 coordinator 추천에서
무조건 생략하면 mixed ownership의 배정 검사를 잃는다. 응답을 별도 모델로 요약하면 추가
비용과 손실 위험이 생긴다. 문자 수나 비용에서 토큰을 역산하면 캐시·구독 의미를 혼동한다.

## 선택 이유

이미 결정된 단일 역할의 배정만 직접 만들고 기존 planner 실패 경계를 그대로 남긴다.
입력 중복만 제거하고 원본 기록과 fresh full review를 보존해 감사와 수리 근거를 유지한다.
실제 CLI 수치를 별도로 기록해야 호출 감소, prompt 크기 변화와 토큰 사용을 구별할 수 있다.

## 결과·비용·제약

캐시 입력/출력의 청구 단가는 다를 수 있고 CLI usage는 청구서나 구독 잔여량 증명이 아니다.
Claude의 기존 CLI dollar estimate와 Codex ChatGPT/Z.ai Coding Lite 구독·quota는 서로 다르다.
usage를 비용상한/인증/admission 판단에 연결하지 않는다. 모르는 CLI 버전·과대한 stdout은
관측 불가로 두며 실제 사용량을 꾸미지 않는다. 추가 paid 측정 호출은 만들지 않는다.

runtime 읽기 승인 37개·각128KiB/전체1.5MiB는 그대로 유지한다. 기존 runtime 파일의 프롬프트를
새 helper로 추출해 여유를 확보하며 목록에서 파일을 빼거나 상한을 올리지 않는다.
새 회귀는 작성만 했고 실행하지 않았다. parent가 full `make check`, 37파일 크기 상한,
동일 입력 전후 prompt 크기/로컬 추정치와 별도 actual usage, 새 Claude 의미 검토를 확인한다.
기존 6084 pass는 새 검증 근거가 아니다. GitHub/CI3/merge/cleanup/archive도 parent 책임이다.

## 관련 코드·검증·문서

- [workflow](../../harness/workflow.py), [prompt builder](../../harness/workflow_prompts.py),
  [usage helper](../../harness/agent_usage.py), [CLI adapter](../../harness/agent_models.py)
- 작성한 회귀: [workflow](../../harness/test_workflow.py),
  [prompts](../../harness/test_workflow_prompts.py), [usage](../../harness/test_agent_usage.py),
  [adapter 호환](../../harness/test_agent_models.py). worker는 검사·Git·네트워크를 실행하지 않았다.
- [전체 설계](../harness-design.md), [workflow](../workflow.md), [agent-models](../agent-models.md)
- parent 제공 공식 근거: [Codex JSONL turn.completed usage](https://learn.chatgpt.com/docs/non-interactive-mode),
  [로컬 token 추정과 전체 입력 계수](https://developers.openai.com/api/docs/guides/token-counting).
  worker는 네트워크 조회하지 않았다.
