# 0016. 제한된 private 후보·review 원문과 공개 표시 분리, 엄격한 모델 envelope

- 상태: 제안(proposed), 명시 요청 수리·새 Claude 검토/필수 전체 검증/전달 대기
- 기록일: 2026-10-15
- 기록 성격: 새 데이터 계약 결정
- 대체 관계: 없음. [ADR 0015](0015-approval-gated-improvement-discovery.md)의 권한 경계를 유지한다.

2026-10-16 연계: 이 ADR의 private/public 서술·review digest·strict JSON envelope 결정과
아래 과거 수리/공개 자동승인 거부 기록은 보존한다. 아래의 daily/호출 정책 유지 및 `GIT=0`
인계는 당시 수리의 범위다. 최신 자동 연구의 스케줄·호출/추정 예산·MLX adapter는
[ADR 0017](0017-budgeted-continuous-improvement.md)을 따른다. 이번 직접 요청의 전달은 기존
Git 역할·검증된 앱 요청을 메인에게 인계하며 baseline 불일치·명시 승인 거부 시 중단한다.
과거 거부를 지우거나 worker가 쓰기를 재요청하지 않는다. 이번에 이 ADR을 갱신한 이유는
계약을 바꾸기 위해서가 아니라 유지되는 결정과 대체된 운영 정책의 적용 시점을 구분하기 위해서다.

## 문맥

메인이 제공한 첫 실제 점검 관찰에서 downloader runner는 passed였으나 두 후보 중 하나의
issue 419자가 기존 표시 상한 400자를 넘어 specialist 출력 전체가 거부되었다. 두 번째 issue는
279자였으며 응답 전체 64KiB 초과가 원인은 아니었다. 이는 메인 제공 관찰이며 worker가 private
원문이나 운영 설정을 읽어 검증한 결과가 아니다. fixture에는 합성 문자열만 사용한다.

같은 날 메인 제공 후속 관찰에서 기존 길이 patch는 Claude 검토와 selected 3158 tests를
통과했으나 실제 재점검의 GLM 응답 전체가 단일 json fence여서 transport 파싱이 실패했다.
runner passed와 내부 JSON/승인 source 검사의 유효성은 보고 승격·검토 완료·승인/실행의
증거로 사용하지 않았고 partial 보고를 전달했다. 원문을 worker에게 제공하거나 fixture에
복사하지 않았다. 이번 추가 수리는 같은 요청의 모델 출력 형식 호환성에 한정한다.

최신 메인 제공 scan `1792065346555306548-d8a875`에서는 GLM 포함 specialist 4명 모두
성공하여 후보 2개를 만들었고 Claude reviewer runner도 passed였다. 그러나 첫 review reason
416자가 private/public 공유 360자 검증에서 거부되었다. 두 번째 reason 351자, 전체 문서
reason 176자·후보별 문서 reason 142/159자와 승인 문서 경로는 해당 실패 원인이 아니었다.
승인·claim·실행 없이 partial 보고를 전달했다는 메인 제공 관찰이며 원문은 fixture가 아니다.
이 후속 수리는 동일한 수용/표시 결합을 reviewer 서술까지 일관되게 분리하도록 본 ADR을
확장한다. 이전 3215 passed는 새 수리의 검증이 아니며 최종 새 실제 scan 성공은 아직 없다.

표시 길이만으로 유효 후보를 버리면 점검이 partial로 남는다. 수용 전에 단순 절단하면 독립
reviewer와 proposal identity·승인 후 실행이 서로 다른 내용을 볼 수 있다. 현재 private Sites는
고정 `improvement-web-v1` public shape·상한·digest를 사용한다.

## 결정

모든 후보 narrative의 PRIVATE 수용 ceiling을 기존 PUBLIC 표시 상한의 정확히 4배로 둔다.
문자 수 기준이며 응답 전체 65536 UTF-8 bytes 상한은 그대로다.

모델 응답 `_call_role`에서 specialist/reviewer 모두 strict bare JSON 또는 전체를 차지하는
단 하나의 소문자 `json` 태그 3-backtick fence만 수용한다. 태그 직후와 닫는 fence 직전은
각각 LF 또는 CRLF이며 바깥에는 JSON 공백(space/tab/CR/LF)만 허용한다. 공백/wrapper를
제거하기 전에 원래 응답의 strict UTF-8과 설정 byte ceiling을 검사한다. 내부는 기존
`parse_json`으로 검사한다. config/storage/public 입력의 parser는 계속 fence를 거부한다.
설명문·unknown/untagged fence·여러 block·truncation·duplicate key·NaN/Infinity·숫자
overflow·invalid UTF-8은 추출·salvage·retry 없이 기존 partial 경계로 실패한다. 유효 JSON
문자열 안의 backtick은 데이터다. prompt는 여전히 bare JSON을 요청하고 이 유일한 envelope
허용을 설명한다. genuine redacted runner result는 wrapper까지 private 보존하고, parsed
candidate/review 내용·canonical proposal ID/digest는 같은 bare JSON과 동등하다.

| 필드 | PUBLIC / 간결한 작성 목표 | PRIVATE ceiling |
| --- | --- | --- |
| title | 80 | 320 |
| analogy | 200 | 800 |
| issue | 400 | 1600 |
| evidence.summary, benefit.evidence.summary | 각 240 | 각 960 |
| benefit.text, risk | 각 240 | 각 960 |
| validation_plan 각 단계 | 200 | 800 |
| documentation_impact | 360 | 1440 |
| review.reason | 360 | 1440 |
| 후보별 documentation.reason | 360 | 1440 |
| 전체 documentation.reason | 360 | 1440 |

기존 바깥 공백 정규화 이후 수용 본문을 축약 없이 보존한다. reviewer 입력에는 전체 구조화
후보를 기존 민감 정보 redaction으로 전달하며 display 절단이나 공백 합치기를 적용하지 않는다.
redaction이 길이를 늘려도 뒤의 안전한 설명을 자르지 않는다. 원본 canonical proposal ID/digest·
private 저장·재검증·후속 명시 승인/실행 task는 전체 수용 본문을 사용한다. 기존 짧은 후보의
canonical 표현과 ID는 그대로이며 공개 prefix 뒤 문자의 차이도 원본 ID/digest를 바꾼다.
review reason과 후보별·전체 documentation reason은 PRIVATE 1440 / PUBLIC 360자로 분리한다.
private review 원문은 독립 검토의 scan/proposal 기록·기존 approval `review_digest`·후속
eligibility/authorization 재검증·승인 후 task까지 보존한다. 전체 documentation 판단은
private scan에 무축약 보존하고 eligibility 때 재검증한다. 기존 짧은 review 표현/digest는
바뀌지 않으며 표시 prefix 뒤 suffix도 후보별 review 전체의 승인 digest에 반영된다.
reviewer prompt는 세 reason 모두 간결한 한국어 360자 이하 목표와 private hard 1440자를
명시한다. review reason은 비어 있으면 안 되고 문서 reason은 구체적인 최소 12자다.
문서 status·Markdown 경로·승인 scope·status/files 일치·exact coverage·verdict와 적격
후보의 필수 문서 edit_files 포함 조건을 완화하지 않는다.

PUBLIC projection에서만 allowlist로 정제·표시 공백 정규화 후 상한 안의 마지막 한 자리에
`…`를 넣어 생략을 표시한다. `validate_web_report`는 PUBLIC 상한을 별도로 엄격히 검사한다.
정상 재계산 digest가 있어도 oversized public 입력을 private 후보처럼 수용하지 않는다.
`validate_documentation`·`_review_item`·`validate_review`는 private/public 모드를 구분한다.
private `build_web_report`는 수용 상한을 재검증한 후 projection만 줄이며 public validation은
review reason·후보별 및 전체 documentation reason 모두 명시적으로 360자를 검사한다.
361자는 재계산 digest로도 허용하지 않으며 HTML/Markdown 소비자도 같은 검증을 사용한다.
private canonical 저장 전에 자르거나 잘못된 review의 eligibility를 만들어 투영하지 않는다.
web-v1 버전·shape·public maxima·canonical digest 및 HTML/Markdown escape·최대 3카드
한 장 요약을 유지한다. 현재 private Sites의 배포·API·auth 변경은 요구하지 않는다.

private ceiling 초과와 invalid 후보는 기존처럼 specialist 출력 전체를 거부하여 partial로 남긴다.
잘못된 타입·빈 텍스트·UTF-8/제어문자·exact keys·enum·개별 경로·scope·실제 evidence line·배열
상한은 완화하지 않는다. reviewer의 의미 판단을 위조하거나 출처를 정규화하여 살리지 않는다.
source/context·payload bytes·역할/provider/effort·예산·호출/재시도·storage·daily 스케줄과
authority gate는 유지한다. `daily`는 partial/failed도 당일 기록을 재사용하며 명시 수동 `discover`만
같은 날 새 scan을 만든다. 이전 scan과 human 기록은 보존한다. 새 retry 경로는 없다.

## 비교 대안

- 기존 표시 한도로 수용까지 제한: 단순하지만 419자 사례처럼 읽기 전용 점검을 불필요하게 중단한다.
- 수용 전 절단: 작은 입력을 유지하지만 근거·위험·승인 대상의 일부를 영구히 잃는다.
- private 무제한 수용 또는 응답/context 확대: 저장·review 비용 경계를 넓힌다.
- public maxima/schema 변경: 현재 Sites reader 호환성과 보고 크기를 함께 바꿔야 한다.
- 모델 재호출/추가 retry: 원인인 검증 계약을 고치지 않으며 호출 정책을 확대한다.
- 모델 응답의 fence 일괄 거부: 전체가 하나의 명시 json container인 유효 응답도 잃는다.
- 일반 Markdown 추출/JSON salvage: 설명문·여러 block의 일부를 선택하여 원래 내용과 신뢰 경계를 바꾼다.

## 선택 이유

4배의 일정한 여유는 간결한 출력을 유도하면서 표시 목표를 조금 넘은 유효 근거를 보존한다.
유한한 private 상한·기존 전체 bytes 상한을 함께 유지하고, compact projection만 웹에 내보내면
독립 검토·identity·승인 대상의 내용 일치와 기존 reader 호환성을 함께 지킬 수 있다.
모델 경계의 유일한 envelope 인식은 내용의 손실 없이 transport 차이를 수용하며 원래 bytes
상한과 내부 strict JSON 검증을 함께 유지한다. 다른 입력의 허용 언어나 권한은 넓히지 않는다.

## 결과·비용·제약

private 저장과 reviewer 입력은 늘 수 있지만 기존 record/context/task byte 한도도 계속 적용된다.
각 문자 ceiling을 만족해도 응답 전체 64KiB나 후속 기존 task 상한을 넘으면 거부될 수 있다.
display에는 일부 설명이 생략되므로 visible ellipsis로 알리고 승인/실행은 원본에 결합한다.
redaction은 임의 민감 데이터를 공유할 허가가 아니며 source scope와 기존 private 경계를 유지한다.
실제 인쇄 pagination은 브라우저/글꼴에 따라 메인이 확인한다. 길이 수리는 발견 제안의 실행 승인이
아니며 새로 발견한 개선은 개별 사용자 승인 전까지 실행하지 않는다.

합성 회귀 작성은 성공 증거가 아니다. worker는 checks·discovery·workflow·Git·스케줄러를
실행하지 않는다. 이번 소스의 새 Claude 검토와 필수 전체 `make check`는 오케스트레이터,
이번 `GIT=0` continuation의 local apply 뒤 승인된 수동 실제 재점검·정제 private 보고함 전달은
메인 책임이다. GitHub create_tree는 명시적 공개 동의 부족으로 automatic approval review가
거부했다는 메인 제공 상태를 유지한다. Git 쓰기·재요청·journal 변경 없이 영향 없는 local
수리/보고 전달을 마친 뒤 메인이 별도 공개 승인을 요청한다. 게시/CI/merge/cleanup은 완료하지 않았다.
이번 문서는 새 실제 점검 통과나 전달 완료를 주장하지 않는다.

## 관련 코드·검증·문서

- [순수 계약](../../harness/improvement_report.py): private prose 4배, 고정 public bounds, 정제/말줄임.
- [발견 실행기](../../harness/improvements.py): 간결한 한국어 목표 prompt·전체 reviewer 입력 redaction,
  모델만의 bounded strict JSON envelope와 변하지 않은 private runner result.
- [오프라인 회귀](../../harness/test_improvements.py): 합성 419자/279자 후보 보존과 전체 review,
  private 재검증·명시 승인 후 task, 모든 narrative exact/over 경계, suffix identity,
  정상 digest를 가진 과대 public 거부, invalid 후보 전체 거부·daily partial 재사용.
  bare/fenced 내용·ID/digest, fenced reviewer/419자 전체 review·bounded web, LF/CRLF와 문자열
  backtick, malformed envelope/strict JSON partial, 원래 wrapper/공백 포함 byte cap 및
  config/public/storage strict parser 명세도 추가한다. 모두 합성이며 실제 응답을 복사하지 않는다.
  기존 same-day 수동 재점검·human 기록·authority guard 명세를 재사용하며 실행은 대기다.
  reviewer 확장 합성 명세는 416자 review·문서 reasons의 전체 private 보존과 5개 실제형
  fixture runner envelope(네 specialist+reviewer), 무승인/무claim/무실행 발견·소스 불변,
  명시 합성 승인 후 mocked task 전달, 표시 prefix 밖 suffix의 review_digest 결합·기존
  승인 무효화를 다룬다. 세 reason 위치의 private 정확 1440/초과 1441 및 projection/
  저장 후 재검증, public 360/361과 재계산 digest의 validation/render 거부, 짧은 review
  표현/digest·strict 구조/문서/권한 회귀를 유지한다. worker는 실행하지 않았다.
- 실제 변경 Markdown: [improvements](../improvements.md), [architecture](../architecture.md),
  [harness-design](../harness-design.md), [ADR index](README.md), 이 ADR.
  문서 판단은 `documentation.updated`이며 데이터 계약·모델 transport·검토/표시 경계·거부 정책을 설명한다.
  [harness](../harness.md)는 CLI/검증 실행 설명 불변, [AGENTS](../../AGENTS.md)와 ADR0015는
  기존 권한 정책 불변으로 수정하지 않는다. 최종 reviewer가 의미적 완전성을 판단한다.
