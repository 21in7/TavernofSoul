# 0026: 실제 source Read 검증과 유효 제안 보존 보고

2026-10-22 [ADR0027](0027-inspection-lock-isolation-and-diagnostics.md)은 source capture와
freshness를 짧은 기존 source mutex 아래 수행하고 일반/READ_ONLY 모델·검증은 격리 사본에서
진행하도록 잠금 계약을 대체한다. 아래 Read pairing·coverage·ID별 최신 verdict·retained provenance와
과거 frozen digest는 유지한다. source 변경 중 현재 정상0개/eligible을 추정하지 않는다.

- 날짜: 2026-10-22
- 상태: 사용자 직접 요청 구현안; 새 Claude 의미 검토·full make check·scoped apply·Git/CI 전달 대기
- 문서 영향: transport 신뢰 경계, private 검증 계약, 완료/집계/승인 freshness 변경
- 대체 범위: ADR0025의 최신 완료 한 회차 선택, 최신 reviewer 실패 시 이전 eligible 강등,
  자기 보고/JSON 성공만으로 source 확인을 인정하던 완료 규칙. sealed snapshot·참여 history와
  source-only 진행 보존, ADR0015의 개별 승인/서명/일회성 claim 및 ADR0017의 예산은 유지한다.

## 제공된 관측과 문제

trusted parent가 제공한 정제 관측: 10/21 21시 회차의 cloud 5역할과 independent review가
성공했고 downloader 제안 2개가 eligible이었다. 10/22 01시 downloader는 role_json_invalid로
실패했다. 06시 reviewer는 후보 0개에 reviews=[]를 반환하고 documentation.reason에 소스를
직접 읽지 않았다고 썼지만 review_complete=true로 저장됐다. 최신 완료 한 회차 선택은 앞의
2개를 보고에서 없앴다. 이는 이 worker가 실행하거나 원문에서 재확인한 사실이 아니다.
과거 frozen 날짜별 보고·payload·digest와 승인/claim·제안 기록은 재작성하지 않는다.

## 결정: parent 소유의 작은 Read 계약

`review_coverage.py`의 source-read-review-v1은 discovery reviewer 호출에만 적용한다.
parent가 만든 Capture 객체를 `agent_models.run(discovery_review=...)`에 전달한다. ordinary
workflow, GLM telemetry, identity, compaction 훅, budget, interrupt 처리는 기존 경로를 유지한다.
전용 Claude 호출만 stream-json/verbose와 Read 단일 도구를 사용한다. 범위 밖 Read, Glob/Grep,
shell과 다른 도구는 이 증거 계약에서 허용하지 않는다. 인증/provider/model 설정은 변경하지 않는다.

parent의 Claude Code2.1.294 정적 관측에 따라 headless stream-json/verbose stdout에도 나오는
`rate_limit_event`만 bounded no-op metadata로 추가 허용한다. envelope는 정확히
`type`, object `rate_limit_info`, string `uuid`/`session_id`이며 두 문자열은 각각 UTF-8 1~128bytes다.
info의 `status`는 `allowed`/`allowed_warning`/`rejected` 중 하나여야 한다. 각 안내의 원래 JSON 줄은
UTF-8 최대8192bytes, 전체 JSON value는 최대256개·깊이8(root=0)로 제한한다. 선택 info 값은
기존 strict JSON 규칙 안의 자료로만 다루고 모두 버린다. status를 포함한 어떤 값도 source Read,
CLI 성공, 비용/예산, provider identity, 진단 코드의 권위가 아니며 receipt/report/log/public에
원문을 보존하지 않는다. `rejected` 안내도 실제 성공 result를 뒤집거나 실제 실패를 복구하지 않는다.
안내는 Read 전·tool_use/result 사이·유일한 정상 final result 뒤에도 허용한다. 완료된 pairing과
pending tool 없음, 실제 정상 result 하나는 계속 필수다. result 뒤 assistant/user/tool/system,
중복 result, unknown event와 malformed/과대 안내는 거절한다. `auth_status` 등은 추가 허용하지 않는다.

parent가 직접 받은 stdout의 top-level assistant tool_use와 user tool_result를 ID로 pairing한다.
성공 text Read의 CLI structured tool_use_result.file은 canonical 승인 경로, offset/limit,
startLine/numLines와 정확히 일치해야 한다. parent가 제공한 CLI 2.1.294 관측에 따라 content는
원본 UTF-8 문자열의 최초 BOM을 한 번만 제외하고 LF로 split한 뒤 각 줄 끝 CR 하나를 제거한
선택 줄들을 LF로 join한 값 하나만 허용한다. 마지막 선택 줄 뒤 LF를 덧붙이지 않는다.
totalLines는 전체 LF split 길이로 끝 LF 뒤 빈 줄도 센다. 그 빈 줄만 선택하면 content는 빈 문자열이며,
여러 줄 선택에 실제 빈 마지막 줄이 포함되면 join의 LF는 남는다. 원본 bytes/hash/POSIX mode와
evidence 줄 번호는 유지하며 원본 range bytes/hash와 CLI projection을 별도로 계산한다.
path alias·정규화·잘못된 줄·tool_use만 존재·실패·부분/잘림·중복 ID/result·알 수 없는
도구/형식·중복 JSON key·비정상 종료는 증거가 아니다. 소스나 응답 속 trace 문자열은 다시
event로 파싱하지 않는다. 모델의 read_files/coverage 주장과 문서 설명은 transport 권위가 아니다.
CLI의 structured text 형식이나 newline 표현이 이 계약과 다르면 추측하여 성공시키지 않는다.
실제 CLI 형식 호환은 parent 검토·검증/운영 관측 항목이며 이 구현안의 성공을 추정하지 않는다.

stdout 512KiB, stderr 16KiB와 기존 wall timeout을 pipe 수집 단계에서 제한하고 Capture는
안내를 포함한 전체 event를 최대256개로 제한한다.
초과·timeout·interrupt는 해당 자식 process group을 종료하고 retry/fallback하지 않는다.
trace와 stderr 원문은 scan에 전달하지 않으며 고정 private 진단만 남긴다. 정상 final cost는
파싱 가능한 뒤 안내를 건너뛰어 실제 result에서만 찾고 Read 증거나 안내 검증 실패에도 기존 예약 정산에
전달한다. 비용 추출은 안내 승인이나 호출 성공이 아니며 이후 전체 Capture 검증을 요구한다.
CLI estimate는 청구 강제 상한이 아니다.

## bounded 점검과 완료

전체 37개/1.5MiB를 prompt에 주입하거나 전부 완독시키지 않는다. 후보가 있으면 모든
evidence와 benefit.evidence 범위를 요구하며 후보 edit_files의 존재하는 Markdown 및 기본
문서 표본을 확인한다. 문서 판단에 명시한 files가 해당 문서 Read 계획에 없으면 완료할 수 없다.
빈 pool은 각 non-shared owner의 승인 membership 안에서 Python 프로그램을 선택한다.
영역 AGENTS.md·txt 안내·JSON 및 이름으로 식별되는 Python 설정은 코드 점검 대상이 아니다.
테스트보다 프로그램을 우선하고 동일 우선순위는 기존 owner 순서를 유지한다. 선택한 프로그램이
없거나 비었거나 읽기/파싱 불가이면 문서나 테스트로 덮지 않고 coverage를 미완료로 남긴다.
함수 본문을 우선하고, 함수가 없는 script는 import·주석·docstring·pass 외 실행문을 기준으로
앞 문맥 최대8줄을 포함한 연속 최대96줄을 명시한다. import/header만 있는 파일은 인증하지 않는다.
shared Markdown의 최대12줄 확인과 후보의 필요한 문서 Read는 코드 표본과 별개다.
shared/owner 배정과 runtime37개는 그대로이며 표본은 전체 파일·저장소 완독이 아니다.

인접/겹친 범위는 병합하며 최대32 window·각256줄·총32KiB source bytes다. 후보 evidence가
한도를 넘으면 조용히 일부만 읽지 않고 partial/failed로 남긴다. 호출/예산 여유를 보장한다는
주장이 아니라 한 call 내 읽기량 제한이다. 기존 reviewer $.20·하루$1·틱1회·9slot·하루24회와
quota/no retry/fallback을 유지한다. 각 window에 모델이 구체적인 assessment를 반환해야 한다.
이는 의미 판단 자료이며 Read 증거를 대체하지 않는다. 표본 밖이나 저장소 전체 무결함은 주장하지 않는다.

private source_review에는 protocol, 명시한 plan(원래 source fingerprint, 줄 범위, range bytes
hash/size), 성공 pairing의 ID hash, assessments, 전체 fingerprints digest와 검토 결과 digest를
저장한다. source_review_binding은 원래 scan ID·전체 scope·controls·그 검토 결과까지 결합한다.
source bytes/trace/host 경로를 이 receipt에 넣지 않는다. 생성/완료/오전 선택/재검증/approve/
execute에서 검사하고 승인 freshness는 현재 bytes로 plan도 재구성한다. legacy의 source 읽기를
추정하지 않는다. 새 protocol/control fingerprint와 서명 discovery binding은 과거 승인 또는
동일 텍스트 재발견을 새 source 검토로 자동 재결합하지 않는다. 기록은 그대로 보존한다.
private Store와 transport를 함께 다시 쓰는 동일 uid 공격은 기존 신뢰 경계 밖이다.

완료 outbox는 새 승인/실행과 구분한다. 새 protocol의 signed claim은 원래 Read proof와
서명 discovery binding을 그대로 검증한다. 도입 전 loop·non-loop 서명 claim은 원래 완전한 독립
verdict·proposal/source/review digest·scope·task·서명·실행/CI/merge/cleanup 증거로만 완료를 확인한다.
이전 loop의 `discovery_fingerprint`는 원래 `digest(scan['loop_dependencies'])`이며 signed approval과
persisted proposal provenance에 그대로 대조한다. non-loop는 원래 context 없음으로 검증한다.
`source_review`·`source_review_binding` 또는 scan/dependencies의 `review_protocol` 표식이 있으면
null/오류여도 modern proof와 binding을 요구하며 legacy로 낮추지 않는다. 이 호환은 새 승인/execute에
적용되지 않는다. 완료 후 현재 source freshness/만료를 재검사하거나 승인을 갱신하지 않는다.

## 회차별 제안 보존과 공개 표현

기존 KST `[전날09:00, 당일09:00)`와 bounded completed index(최대32개)만 읽는다.
현재 source/scope/ownership/config/local/agent/workflow/provider/model/protocol 전체가 일치하고
Read/독립 검토가 재검증된 완료 회차를 완료시각·scan ID 오름차순으로 합친다. ID별 최신
명시 verdict가 앞 verdict를 대체한다. 뒤 빈/실패/미완료 회차는 앞 제안을 삭제하지 않고,
뒤 rejected/needs_evidence를 과거 eligible로 되살리지 않는다. 중복 scan pointer는 한 번만 읽는다.
원래 저장 proposal provenance와 어긋난 후보는 제외하며 이전 verdict로 fallback하지 않는다.
전체 합집합은 high/medium/low·exact ID로 정렬해 최대8후보/3카드를 유지한다.

각 제안의 private retained_provenance는 원래 scan/review digest, scope fingerprint,
protocol, source-review binding과 전체 dependency authorization digest를 연결한다.
morning_aggregate는 새 검토 원본이 아니며 proposal pointer나 signed approval/claim을 만들지
않는다. 원본 scan은 그대로 남고 approve/execute는 원래 pointer의 검토와 현재 freshness를
검사한다. 별도 최신 participation history는 앞선 성공으로 최신 실패를 가리지 않는다.
부분 실패와 앞서 확인한 유효 제안을 함께 보여준다. stale/unknown inputs는 eligible이 아니다.

web-v1 필드는 그대로다. 새 headline/summary/status와 HTML/Markdown은 실패/불완전/미점검을
완료나 할 일 없음으로 표현하지 않는다. 정상 완료·검증된 coverage의 0개만
`점검 완료 · 확인한 범위에서 제안 없음`으로 표시하며 표본 한계를 밝힌다. 기존 frozen
payload/digest와 legacy 렌더링은 보존한다. private source/trace/diagnostic/local/cost/host 경로는
공개 계약에 추가하지 않는다. Sites 화면 변경과 별도 checkout/credential은 parent 소유다.
web-v1 validator는 최신 reviewer 실패와 앞선 eligible 카드의 공존을 구조적으로 허용한다.
원래 Read/provenance/freshness 검증은 private parent가 담당하며 공개 digest는 실행 권한이 아니다.

## 검증 인계와 한계

offline 회귀는 합성 stdout의 pairing/실패/원문 위조/범위/size/정제를 명세한다. 실제 Lab engine
tick→Store 재시작→morning→public→approve 경로에서 빈 pool/no Read/자가 주장/실패/성공,
앞2 eligible 뒤0 또는 실패·후속 reject·provenance·freshness와 frozen/privacy를 다룬다.
기존 publisher의 lock 외 전송·unknown/same-digest 복구와 window/index 회귀도 유지한다.
source/context 상한 회귀와 공통 합성 입력은 승인된 `harness/test_review_coverage.py`로 옮겨
runtime의 `harness/test_improvements.py`를 기존131072byte 상한 안에 유지한다. 검사 삭제·skip이나
상한/scope 확대는 없다. LF/CRLF/BOM/final newline의 literal Read 기대값은 구현 helper와 독립적이다.
literal wire 안내 유무/위치/세 status의 동일 Read 증거·최종 판정, metadata만의 위조 불가,
실제 CLI/Read 실패·pending/후속 tool·중복 result의 거절, malformed/과대/unknown/JSON 상한과
실제 result 비용 보존, private proof/저장 보고/public payload의 metadata 배제 회귀를 추가했다.
worker는 검사·모델·네트워크·Git·재위임·workflow·private 설정·cron·운영 pipeline을 실행하지 않았다.
parent는 매 새 Claude 검토에서 최종 코드/문서의 의미와 문서 완결성을 다시 판단하여
documentation={status,files,reason}을 받아야 한다. 앞선 updated나 Markdown 확장자 검사는
이 판단을 대체하지 않는다. 이후
full make check와 publisher 회귀, scoped apply, 기존 Git 역할, GitHub required CI·merge·cleanup을
진행해야 한다. 이전 approved/5097개 통과와 checkpoint 준비·복원은 이번 최종본의 검토/검증이
아니다. 실제 hourly9단계 완주는 미관측이다. Sites는 parent가 별도로 배포·검증한 관측이다.
