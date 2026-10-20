# 제한된 로컬 MLX 탐색

Mac mini는 작은 승인 소스 부분에서 초안을 찾고, 기존 네 specialist와 Claude reviewer가
검토한다. 로컬은 기존 역할을 대체하거나 제안 실행을 승인하지 않는다. 전체 순서·보고·예산은
[improvements](improvements.md), 결정은 [ADR 0017](adr/0017-budgeted-continuous-improvement.md)에 둔다.

## 최종 프로토콜과 명시적 배포 이행

Linux `harness/local_model.py`는 Python 3.8 표준라이브러리만 사용한다. 서버는 메인이
설치한 mlx-vlm 0.7.8이며 Linux requirements에 MLX·llguidance 등 서버 의존성을 추가하지 않는다.
기존 cloud 역할/provider/model/effort/compaction/auth와 37개 읽기 scope·ownership/shared는 유지한다.

메인이 [예제](../harness/local-model-config.json.example)를 바탕으로 ignored private
`logs/harness/local-model.json`을 소유자 소유·단일 hardlink·nonsymlink·0600으로 제공한다.
ancestor symlink도 거부하며 코드가 chmod하거나 credential을 만들지 않는다. override는
`TAVERN_LOCAL_MODEL_CONFIG=/ABS/PRIVATE/local-model.json`처럼 절대 설정 파일 경로만 받는다.
모델 요청에 절대 호스트 경로를 넣는다는 뜻은 아니다.

설정은 정확히 `local-model-config-v2`, `provider=mlx-vlm`이며 `api_model == model`이어야 한다.
예제의 두 model 값은 모두 `mlx-community/Qwen3.5-9B-4bit`다. 기존 상대 repository ID 검증을
유지한다. 서버에는 `default_model` 별칭이 없으며 메인이 기존 다운로드 모델을 동일한 상대
repository ID 경로로 연결해 로드한다. 요청의 model은 이 repository ID다. API 응답의 model만으로
preload identity를 증명할 수 없으므로 실제 로드 확인은 메인 책임이다.
v1 mlx-lm 설정은 자동 변환·대체하지 않고 `config_invalid`로 보류한다. version/provider/API
identity를 포함한 config digest가 달라져 기존 loop fingerprint와 서명 승인을 재사용할 수 없다.
정확한 version/provider/model/api_model/endpoint/temperature/limits의 타입·finite·상한을 검증한다.

예제 endpoint는 `http://127.0.0.1:18080/v1/chat/completions`다. 정규형 숫자 loopback 127.0.0.1
또는 [::1]만 허용하며 DNS localhost·외부 host·0.0.0.0·userinfo·query·fragment·다른 path·
redirect·proxy를 거부한다. SSH 연결과 key는 메인만 관리하며 adapter에는 model credential이 없다.
HTTP를 인터넷에 공개하지 않는다.

실제 POST JSON은 `model=config.model`, `stream=false`, 제한된 max_tokens/temperature,
**top-level `enable_thinking=false`**와 다음 native 구조화 출력을 포함한다.

```json
{"type":"json_schema","json_schema":{"name":"local_improvement_candidates","strict":true,"schema":{}}}
```

위 객체는 `response_format`의 외형 설명이며 빈 schema를 전송하는 예제가 아니다. 실제 schema는
다음 계약 전체를 담고 mlx-vlm이 llguidance logits processor로 강제한다.

- root는 정확히 `{candidates:[...]}`다. 후보는 0..2개(호출별 더 작은 한도 가능)이며 기존
  canonical 후보 전체 필드·타입·필수 항목과 모든 객체의 `additionalProperties=false`를 명시한다.
- `edit_files.items.enum`은 현재 owner 승인 목록 전체다. 배열은 1..12개이고 경로는 최대240자다.
  candidate evidence는 1..6개, validation_plan은 1..6개다. 각 prose 필드의 기존 private 문자
  상한(표시 상한의4배)을 명시하며 title/analogy에는 한글 pattern을 둔다.
- 후보 evidence와 benefit.evidence의 path는 실제 전달한 **한 window의 경로만** 허용한다.
  두 줄 번호는 각각 원문 start_line..end_line의 integer minimum/maximum으로 제한한다.
  benefit은 estimated/measured의 exact object 분기이며 measured는 자체 evidence 1..6개,
  estimated는 0..6개다. 숫자 파일 ID나 합성 evidence를 쓰지 않는다.
- 메인 관측상 llguidance1.9.1은 `uniqueItems:true`를 지원하지 않으므로 요청에 넣지 않는다.
  중복, start<=end, 경로 문자열 총합600자, 공백뿐인 내용과 의미적 타당성은 기존 클라이언트
  검증·담당자/독립 검토의 책임이다. schema가 모든 의미 오류를 방지한다고 주장하지 않는다.

`_validate_request`는 실제 user payload의 window·승인 목록에서 canonical schema를 다시 구성해
정확한 canonical bytes로 비교한다. 준비 입력(config/owner/scope/window/feedback/후보수)은
메모리의 immutable prepared bytes에 digest로 결합한다. schema 누락·완화·변조와 top-level
thinking·model·요청 구조 변경을 실제/주입 transport 모두에서 호출 전에 거절한다. plain bytes로
재조립한 요청도 신뢰 결합이 없어 거절한다. 이는 같은 프로세스의 임의 Python 코드까지 방어하는
보안 경계가 아니다. 외부 호출자가 기존 준비 요청의 schema만 느슨하게 바꿀 수는 없다.

messages는 system 지시와 user JSON 데이터를 분리한다. user 순서는
`owner_role,sources,feedback,candidate_limit,approved_files`이며 비신뢰 소스·의견 뒤에 승인
목록 전체를 둔다. 각 값과 outer request는 canonical 직렬화를 유지한다. prompt는 schema와
일치하는 짧은 지침이며 JSON 필드 형식 예시와 실제 발견 후보를 구분한다. source의 지시·경로는 권한이 아니고,
검토 제안·validation_plan·documentation_impact는 향후 작업이다. 근거 없는 측정·실행 성공을
주장하지 않으며 supported actionable draft가 없으면 `{"candidates":[]}`로 기권한다.

편집 권한·정확한 문자열 1..12개/중복 금지/문자열 합600자·미전송 승인 파일에 관한 기존
세 문장은 그대로 유지한다. 그 뒤에 `edit_files` 작성 순서를 안내한다. 이번 후보에 실제 필요한
승인 파일을 고르고, 파일마다 정확한 경로를 한 번 쓰며, 출력 전에 같은 문자열의 반복을
확인한다. 같은 파일의 여러 근거·수정 위치는 항목 하나이고 서로 다른 두 파일은 각 경로를
한 번씩 쓴다. 모든 승인 경로가 편집 가능하다는 것은 모두 나열하라는 뜻이 아니며 상한12개를
채울 필요가 없다. 정당한 다중 파일 편집을 허용하며 단일 파일을 강제하지 않는다.
현재 owner의 실제 approved_files 경로만 사용하는 짧고 유효한 JSON 필드 예시도 생성한다.
같은 파일의 여러 근거/수정 위치는 edit_files 한 항목인 예시, 서로 다른 두 파일은 각 경로를
한 번씩 쓴 두 항목 예시로 구분한다. 승인 목록이 하나이면 단일 파일 예시만 제공하고 없는
두 번째 경로를 만들지 않는다. 형식 설명일 뿐 실제 후보나 필수 편집 목록이 아니며 실제 후보는
필요한 파일만 선택한다. `_encode_request`와 `_validate_request`의 canonical system 비교는
준비된 동일 승인 목록으로 예시를 생성한다. 예시를 포함한 system·user·feedback·schema
전체에 기존24576bytes 예산과 whole-line 선택을 적용한다.
이는 생성 지침이며 응답 후처리가 아니다. 중복 방지를 보장하지 않고 client 최종 검증을 유지한다.

모든 호출은 discovery guard 아래 단1회다. JSON Content-Type, assistant의 비어 있지 않은 text,
finish_reason=stop과 model 일치를 검사한다. 기존 bare JSON/단일 lowercase json fence parser의
엄격한 중복 키·NaN·trailing text 거절과 공통 후보 validator를 유지한다. 공유 검증 뒤 두 evidence
배열을 실제 전송 window와 대조한다. 서버가 schema를 무시하거나 잘못된 후보를 내면 그대로
거절하고 raw 예외/응답을 출력·저장하지 않는다. 경로 수정·중복 제거·잘라내기·줄 번호 보정·
근거 합성·범위 확대·재시도·fallback은 없다. cloud 후보의 수용·승인 기준도 유지한다.

메인이 확인한 정상 mlx-vlm assistant message의 `tool_calls:null`, `tool_call_id:null`만 무동작
메타데이터로 받는다. 두 필드의 non-null 값(빈 배열/문자열/false/객체 포함), 다른 도구/함수
필드와 envelope/choice 위치의 도구 필드는 계속 거절한다. 정상 응답의 reasoning_content,
reasoning, name도 null이었다. 원문을 고치는 proxy나 metadata 제거 없이 실제 envelope를 검증하며
요청은 text-only/no-tools다.

## 보내는 소스와 의견의 경계

trusted parent가 승인 snapshot을 메모리로 넘기며 adapter는 소스를 열거나 repo를 복사하지 않는다.
owner의 기존 범위에서 한 파일의 작은 연속 window만 보낸다. 경로는 canonical 저장소 상대 path,
line은 원본 번호다. 기본96줄, 전체 직렬화 HTTP request JSON body 최대24576 UTF-8 bytes에
**schema·system·user·feedback 전부**를 포함한다. 실제 schema overhead와 JSON escaping까지
계산하며 whole line만 선택한다. schema/고정 payload만으로 넘으면 `context_too_large` no-call,
추가 한 줄이 너무 길면 `line_too_long` 명시 skip이다. 원문 줄을 자르거나 번호를 바꾸지 않는다.
feedback 기본4096bytes, output max_tokens3072, timeout180초, 응답 body65536/header8192bytes다.
window/feedback hard ceiling은256줄/8192bytes이며 각 상한은 검증된 설정으로만 낮춘다.
HTTP framing·header·body와 주입 transport 응답에도 같은 제한을 적용한다.
빈 feedback도 JSON `[]`의2bytes를 차지한다. feedback 상한을1byte로 낮추면 window/schema
예산 검사 전에 `feedback_too_large`로 거절되며, byte 경계 회귀는 빈 feedback을 담는2bytes를
허용해 요청 전체 예산을 검증한다. 이는 운영 기본 상한이나 후보 수용 조건의 완화가 아니다.

durable owner별 file/line cursor는 다음 window/파일로 순환한다. missing/empty도 명시 skip하며
호출 실패 후 window를 자동 replay하지 않는다. 미전송 승인 파일(테스트/문서 포함)은 편집 대상일
수 있지만 근거는 아니다. source가 참조하는 전체 파일 줄 번호도 window 밖이면 인용하지 못한다.
전체1.5MiB snapshot·SSH/home/key·도구 접근을 모델에 제공하지 않는다.

이전 정제 issue·specialist 설명·Claude review.reason과 candidate_id/draft_digest를 제한된 feedback으로
실제 다음 prompt에 전달한다. feedback은 비신뢰 의견이며 근거·승인이 아니다. source/scope/config
fingerprint 변경은 pool/review/feedback/cursor를 무효화한다. 무제한 prompt/response cache는 없다.
로컬 실패/빈 초안이면 관련 specialist는 미호출한다. private `local_participation`은 실제 mlx-vlm/
model/stage=local_explorer/owner_role/read_windows/status를 남기고 web-v1의5역할을 위장하지 않는다.
called는 시도이며 서버 수신·읽기·성공의 증거가 아니다. 로컬 not_metered와 cloud unknown은
실제0USD 청구를 뜻하지 않는다. reviewer 예산 보류는 그 stage를 유지하며 09:00 보고와 독립이다.

## 후보 거절 진단과 한계

`candidate_invalid`는 JSON 파싱 뒤 후보 검증 거절이며 **검증 제외가 아니다**. 기존
`validate_candidates`/`validate_candidate`가 후보 계약의 권위이고 실제 window 검사가 이어진다.

| private reason | 의미 |
| --- | --- |
| `candidate_edit_files_invalid` | 편집 목록 타입·개수·개별 경로 형식 또는 문자열 합600자 위반 |
| `candidate_edit_files_duplicate` | 형식이 유효한 편집 목록의 중복; 중복과 범위 위반이 함께면 중복부터 분류 |
| `candidate_edit_files_outside_scope` | 형식이 유효하고 중복 없는 목록에 정확한 승인 밖 경로가 있음 |
| `candidate_invalid` | 위 고정 분류가 없는 후보 계약 오류; 특정 필드를 뜻하지 않음 |
| `evidence_outside_window` | 공통 후보/원본 줄 존재 검증은 통과했지만 실제 전송 window 밖 근거가 있음 |
| `empty_draft` | 빈 배열을 정상 검증했으며 관련 specialist는 미호출 |

먼저 도달한 실패만 분류한다. 원본에도 없는 줄·잘못된 evidence 구조는 공통 검증에서 먼저
`candidate_invalid`일 수 있다. 사용자 노출은 코드 allowlist만 허용하며 loop private 진단/feedback에도
원문 response·prompt·source·오류 값·임의 예외·절대 호스트 경로·endpoint·비밀을 넣지 않는다.
public web-v1에 로컬 설정·진단·원문을 추가하지 않는다. 한 후보가 잘못되면 batch를 거절한다.

후속 cloud specialist/독립 reviewer의 hourly 실패도 다음 round의 local feedback에 전달한다.
`_call_role`이 호출 준비/실행·envelope/identity·read-only context·JSON·후보/검토·cleanup의
실제 경계에서 고정 reason을 만들고 loop가 내장 str/64자 allowlist로 다시 검사한다.
공유 ValidationError의 편집 목록 reason은 정확한 타입과 위3개 코드만 유지한다.
legacy/unknown/잘못된 타입·과대 진단은 role_failed이며 원인을 추정하지 않는다.
선택적 error_type도 내장 str/32자 고정 목록만 받고 그 밖은 Exception이다.
stage/field/type·구문 위치·임의 진단 객체는 버리며 API/CLI·telemetry 성공을 후보 성공으로
해석하지 않는다. 정제 reason은 기존 specialist_reason/review_reason과 draft_digest 연결을
사용하고 feedback은 계속 비신뢰 의견이다. 진단·비밀은 web-v1 payload/digest에 추가하지 않는다.
세부 목록과 기존 result 보존의 구분은 [hourly private 계약](improvements.md#hourly-private-실패-진단과-인계)을 따른다.
이번 회귀는 미실행이며 full make check·수리 검증·PR·CI·머지는 메인/실행기의 후속 작업이다.
실제 자동 연구9단계·정규 hourly 실모델·2026-10-21 09:00 KST 보고는 메인 확인 전까지 pending이다.

### 2026-10-20 실제 duplicate 거절과 이번 생성 지침 수리

다음은 parent가 제공한 관측이며 이번 worker의 실행 결과가 아니다.

| 구분 | 관측과 한계 |
| --- | --- |
| 최초 정규21시 slot | run `1792483202194321920-447ddb`, 2026-10-20 21:00 KST `local(parser)`, Qwen3.5-9B-4bit가 AGENTS.md 원문1..96줄로 실제 실행된 뒤 client가 `candidate_edit_files_duplicate`로 거절했다. 앞선 local(coordinator)·Codex·local(downloader)·GLM은 실제 성공했고 GLM 후보2개가 있었다. 전체9단계 성공을 뜻하지 않는다. |
| 앞선 오프라인 회귀 | run `1792500541005476257-a59052` round1의 full4895개가 모두 통과했다. 다음 실제 HTTP 검증과 별개다. |
| 앞선 개발 live 검증 | 2026-10-20 22:06 KST 같은 실제 로컬 서버에 parser/AGENTS.md1..96/동일 config로 HTTP1회: `called=true`, `reason=candidate_edit_files_duplicate`, `verification=failed`, request18724bytes, 134.805초, 운영 state 불변이었다. 기존 세 문장을 보존하고 필요한 경로를 한 번 쓰도록 설명한 뒤에도 중복이 지속됐다. |
| PR59 순서 지침 회귀 | PR59(`65c19f53cfaa461cd994cf61d435a32ae9b609a9`)의 오프라인4895개 통과와 2026-10-20 22:37 KST parser/AGENTS.md1..96 개발 HTTP1회 성공: 유효 초안2개, 각각 edit_files1개. 한 owner의 단일 성공이며 전체 역할의 해소를 뜻하지 않는다. |
| 정규23시 coordinator 재발 | 2026-10-20 23:00 run `1792504802000339115-d6a0c0`의 local(coordinator), 같은 mlx-vlm/Qwen3.5-9B-4bit 서버, AGENTS.md1..96, `called=true`, `reason=candidate_edit_files_duplicate`. parent 관측 시작23:00:01.927730·종료23:01:16.865115 KST. 원문 미보존으로 반복 경로·개수는 알 수 없다. |

실제 실패의 원문을 보존하지 않아 반복된 경로·개수·정확한 후보 값은 알 수 없다.
이를 추측하거나 후보를 보정해 통과시키지 않는다. 과거 테스트 문구 누락과 이번 실제 생성
중복을 구분한다. 순서 지침 이후의 재발을 받아 이번에는 실제 owner 승인 경로로 단일·두 파일
JSON 필드 예시를 추가했다. 이번 예시 개선도 중복 방지를 보장하지 않는다.
현재 변경의 최종 full/live 및 PR/CI/머지는 parent 관측 전까지 pending이고, 실제 정규9단계 및
2026-10-21 09:00 KST 오전 보고 성공도 별도로 pending이다.

parent는 full `make check` 통과와 과거 실패본 대비 최종 코드·실제 요청 변경을 확인한 뒤,
이번 실제 실패와 동일한 coordinator/AGENTS.md1..96/config로 같은 실제 로컬 서버에 개발 검증
HTTP를 단1회 수행한다. 문서만 바꾸고 같은 추론을 재호출하지 않는다.
요청 전체24576bytes·whole-line 선택·canonical binding을 유지하며 정확한 읽기 범위를 확인한다.
raw/prompt/source를 저장하지 않고 고정 결과 코드·owner/window·해시와 필요한 경우 숫자형
중복 개수만 기록한다. client 검증을 통과한 빈 초안은 정상 빈 결과로 구분하고 후보를
강제하지 않는다. 운영 state·정규23시 slot은 재실행·변경하지 않으며 정규9단계 성공의 대체가 아니다.
새 live 실패는 실제 fixed reason과 owner/window를 같은 coordinator 담당자에게 반환한다.
GitHub·CI·머지·정리도 parent가 담당한다.

이번 수정은 기존 편집 목록 계약의 생성 안내만 명확히 한다. 구조·책임·데이터 계약·격리·검증·
실패 복구·GitHub 게시 정책을 바꾸지 않아 설계서 수정이나 새 ADR은 필요하지 않다고 판단한다.
기존 승인 경로만 설명하며 native schema·immutable binding·client 최종 검증·실패 시 무보정
단1회 호출을 유지하고 새로운 역할·저장 필드·승인·공개 경로를 만들지 않기 때문이다.
합성 snapshot과 주입 transport의 동작 회귀는 owner 승인 범위·단일/다중 목록·중복 거절·
전체 요청 예산·whole-line 및 변조 no-call을 다루도록 작성했으며 worker는 실행하지 않았다.
운영 관측과 한계는 이 문서와 [연구 문서](improvements.md#2026-10-20-parser-편집-목록-중복과-수리-인계)에 기록한다.
매 fresh reviewer는 최종 코드·문서 의미를 새로 평가하고 `documentation={status,files,reason}`을
반환한다. 이전 회귀 통과나 문서 상태를 현재 검토의 성공 근거로 재사용하지 않는다.

### 2026-10-16 과거 후보 거절 관측

2026-10-16 메인 제공 관측에서 최초 초안은 AGENTS.md 원본1–82줄 입력으로 JSON 파싱 뒤
`candidate_invalid`였다. 원문이 없어 당시 필드·값은 확정할 수 없다. 동일 입력 재현에서는
edit_files 범위 위반과 evidence 줄 범위 위반을 각각 관측했으며 최초 응답의 확정 원인은 아니다.
prompt/order 수리 두 실행은 Claude 승인 뒤 실제 추론에서 다시 승인 밖 edit_files를 만들었고
full check 중 중단되어 모두 `applied=[]`다. 성공·완료가 아니다. 보존 초안은 참고용이며 새 독립
검토·전체 검증이 필요하다. 실패한 숫자 파일 ID/window evidence 합성 실험은 구현하지 않는다.

## 메인이 제공한 서버 호환 관측과 남은 검증

다음은 문서 worker가 실행한 결과가 아니다. 기존 모델 Qwen3.5-9B-4bit 가중치를 사용한
mlx-vlm0.7.8 격리 서버에서 메인은 다음을 관측했다. raw 응답은 보존하지 않았다.

| 관측 | 근거와 한계 |
| --- | --- |
| compiler | llguidance1.9.1의 uniqueItems는 Unimplemented keys로 거절; integer minimum/maximum, string minLength/maxLength, 한글 pattern, anyOf는 컴파일 통과 |
| 범위 강제 | 승인 밖 경로·줄 번호를 요구한 합성 입력에서도 enum/integer 범위를 지킨 응답 |
| 합성 후보 | 별도3줄 결함 입력, 약17.64초·후보1개·공통 계약/전달 window 검증 통과 |
| 실제 입력 prototype | commit777a0fe의 AGENTS.md1–82줄, 요청15251bytes·약31.72초·후보1개·공통 계약/window 통과; 당시 adapter는 null 도구 metadata 때문에 tools_refused |
| 미검토 초안 경로 | local_model.py SHA256 `6d74379a76bcad08af301bdbc63a17790ac4b438be20370c33bdd14509eb7406`, prepare_request→run→http_transport→validate_response를 연결한5줄 mean_or_none 합성 입력; 요청5986bytes·42.645초·실제1회·후보2개·reason=ok |

마지막 관측에서도 HTTP 응답을 수정하지 않았고 운영 state/ledger·게시물은 바꾸지 않았다.
이는 특정 미검토 bytes의 사전 관측이다. 이번 최종 bytes의 실추론·의미 검토·전체 make check·
원본 반영·실제 repository9단계 완료를 대신하지 않으며 bytes가 바뀌면 메인의 재확인이 필요하다.
종전 mlx-lm의 약19.54초 합성 추론 성공도 이전 어댑터 관측이다.
메인 제공 기존 운영 상태는 hourly wrapper 활성과 2026-10-16 09:00 partial/제안0개 보고1회 전달이다.
그 보고를 재생성하지 않는다. 새 프로토콜의 서비스/private config 전환과 완전한9단계·다음 아침
게시 성공은 메인의 후속 확인 대상이다.

## 운영·검토 인계

설치·모델 연결·SSH·서비스·실제 추론·private config 전환은 메인이 검증 후 수행한다.
메인은 기존 서비스 하나를 mlx-vlm0.7.8 native schema 서버로 명시 이행하고 상대 repository ID로
로드한 모델과 실제 HTTP 그대로의 canonical 후보/window 검증을 확인한다. 호스트 경로·key·
계정·endpoint 원문은 작업자/모델에 제공하지 않는다. 작업자·검토자는 서비스 명령을 실행하지 않는다.
계획 정지/재개도 메인이 기존 marked job·터널·서비스 하나만 다룬다. Mac 사용자 로그인 전
LaunchAgent 실행은 보장하지 않으며 Linux linger가 이를 해결하지 않는다.

장애 시 고정 reason과 실패 참여로 관련 specialist를 보류한다. tick의 config/Store/readiness 준비
실패는 bounded paused이며 모델·키 조회·보고 확정·publisher·fallback을 하지 않는다.
child/discovery 거부는 이 처리 바깥이다. 메인이 private 환경에서 복구한 뒤 새 hourly slot을
기다린다. slot replay·state 삭제·자동 retry는 없다. 09:00 보고는 완료 review 또는 partial/failed로
불변 확정하고 전송 unknown은 [동일 digest 복구](improvements.md#비공개-http-전달)를 따른다.
NFS default·명시 daily local storage·단일 hourly cron·하루24회·Claude$1·GLM quota·승인 게이트와
GitHub 정책은 유지한다. 이 변경은 스케줄·ledger·확정 보고서·게임 cron을 편집하지 않는다.

세 승인 테스트 파일에는 fake transport/clock/runner와 임시 저장소의 오프라인 회귀를 작성한다.
실제 window/schema 일치, 편집 목록·양쪽 evidence 거절, 요청 변조 no-transport, schema 포함
byte 경계·whole-line·overhead 초과, 서버 무시 응답 거절, 유효 후보/empty_draft·단1회,
v1 거절/v2 digest·loop fingerprint/승인 무효화·specialist skip·진단 privacy를 다룬다.
worker는 실행하지 않았다. 앞선 검증 사본 재사용은 parent가 NFS 원본 baseline과 동일함을
확인한 뒤의 준비 절차일 뿐 성공이나 local fallback이 아니다.
전달된 실패 위치의 소스 검토로 회귀 입력을 수정했다. 재정렬된 승인 목록에서 한 줄 문서의
2행을 요청하던 cursor를 실제 두 줄 파일의2행으로 옮기고, 한 줄 문서의1행도 별도로 다룬다.
정확한 요청 경계·schema-only 초과 사례의 feedback 상한은 `[]`가 들어가는2bytes로 고쳤다.
예외 종류가 제공되지 않은 항목의 전체 원인을 단정하지 않으며 수정 후 결과는 하네스 확인 대기다.
Jev→필요한 Codex 계획→coordinator 단일 작업→새 Claude 독립 의미검토→전체 make check→
scoped apply→메인의 GitHub 게시/CI/머지/정리를 유지한다. 각 검토는 실제 최종 파일의
`documentation={status,files,reason}`을 새로 판단한다. 확장자나 과거 승인만으로 완료하지 않는다.
