# 승인 대기 일일 개선 점검

자동 점검은 정비사의 점검표처럼 개선 후보를 발견하고 서로 검토하여 한국어 비유를 담은
한 장 보고서를 제공한다. 실제 수리는 차주가 특정 항목을 승인한 뒤에 시작한다.
기반 기능 구현과 그 setup의 후속 검증 보정 및 GitHub 전달은 명시적으로 승인되었지만
이후 발견된 제안에는 각각 사용자의 구체적인 승인이 필요하다. 기존 직접 개발 요청의 권한과 구분한다.
권한은 [AGENTS.md](../AGENTS.md), 설계는 [전체 설계](harness-design.md)와
[ADR 0015](adr/0015-approval-gated-improvement-discovery.md)를 따른다.

## 구현 책임과 읽기 범위

Python 3.8의 [improvement_report.py](../harness/improvement_report.py)는 I/O 없는 엄격한
schema·fingerprint·정제·HTML/Markdown renderer다. [improvements.py](../harness/improvements.py)는
기존 model/storage/workspace API로 발견·기록·승인·일회성 실행·HTTP 전달을 담당한다.
[workflow.py](../harness/workflow.py)는 선택적 `_improvement_guard(run_id)`로 승인 provenance를
project lock 안에서 재확인한다. 일반 직접 요청 workflow의 권한·검증·게시 정책은 유지한다.
기존 모델/provider/effort/compaction 설정을 변경하지 않으며 Workers AI 등 새 공급자는 추가하지 않는다.
Cloudflare 자원·유료/무료 인프라·credential의 자동 생성도 없다.

[improvement-scope.txt](../harness/improvement-scope.txt)는 개별 저장소 상대 파일을 한 줄씩
명시한 승인 목록이다. glob·디렉터리 재귀·Git enumeration·모델에 의한 범위 확대는 없다.
이 목록의 경로 문자열은 향후 발견 시 읽기 권한이며 구현 worker의 현재 읽기 권한을 확대하지 않는다.
수동 `discover --scope-file PATH`도 사용자 승인 개별 목록만 받아야 한다. 절대 host 경로는
private scope provenance에만 보존하고 모델/웹에 전달하지 않는다.

| 호출 순서 | 해당 모델이 받는 개별 파일 |
| --- | --- |
| coordinator | `workflow.owner(path)==coordinator`인 공통 하네스·문서·Makefile 및 승인 shared 문서 |
| downloader | owner가 downloader인 승인 파일 및 승인 shared 문서 |
| parser | owner가 parser인 승인 파일 및 승인 shared 문서 |
| django | owner가 django인 승인 파일 및 승인 shared 문서 |
| reviewer | 별도의 격리 context에서 승인 scope 전체 |

owner는 기존 함수를 그대로 쓴다. 예를 들어 `parser_tidy/tests/test_import_safety.py`는 django다.
`shared_files`는 설정에 명시한 `AGENTS.md`, `docs/architecture.md`, `docs/harness-design.md`,
`docs/improvements.md`, `docs/data-contracts.md` 중 해당 승인 scope에도 있는 파일만 포함한다.
없는 파일은 missing으로 표시하며 근거로 인용할 수 없다. 필요한 테스트·문서가 scope 밖이면
추가 필요 경로를 승인된 파일의 finding/설명에 귀속하고 제안을 ineligible/needs_evidence로 남긴다.
메인이 범위를 확인해 새 실행을 준비하며 repair나 모델 판단으로 승인 범위를 늘리지 않는다.

각 specialist는 앞서 생성된 후보의 정제된 ID/title/issue/analogy/edit_files 요약만 받는다.
reviewer는 모든 후보의 정제된 구조화 내용과 승인 소스를 별도 context에서 독립 검토한다.
다른 역할의 의견은 근거 검증이나 성공 합의를 대신하지 않는다.
source snapshot은 symlink·비정규 파일·보호 경로·private 설정을 거부하고 UTF-8/bytes 상한을 검사한다.
존재하는 모델 사본은 0400이며 기존 runner를 `write=False, scoped=True`로 호출한다.
원본·전체 검증 사본·키·host 로그·운영 데이터·private config는 모델 context에 넣지 않는다.
기존 공급자 인증은 신뢰한 runner의 분리 runtime 책임이며 모델 도구에는 공개하지 않는다.

발견은 `workflow.execute`, checks/doctor, Git, cron, 운영 downloader/importAll이나 쓰기 모델을
호출하지 않는다. 허용 쓰기는 자체 private 기록·보고서·lock과 격리 임시 context/runtime뿐이다.
일반 workflow의 `READ_ONLY=1`은 검사를 수행하므로 일일 발견에 재사용하지 않는다.
격리는 모델 도구 권한과 신뢰한 parent에 의존한다. 같은 OS 계정을 가진 임의 프로그램까지
통제하는 범용 VM 경계나 인간 신원 증명으로 해석하지 않는다.

## 한도와 실제 참여

[improvement-config.json](../harness/improvement-config.json)의 정확한 버전은
`improvement-config-v1`, timezone은 `Asia/Seoul`이다. 알 수 없는 key/version과 상한 초과를 거부한다.

| 설정 | 현재 값 / hard ceiling |
| --- | --- |
| 한 장의 제안 / specialist당 후보 | 3 / 2, 전체 후보 최대 8 |
| 실제 역할 호출 / 호출 timeout / 자동 retry | 5 / 600초 / 0 |
| scope 파일 수 / 파일 bytes / 전체 소스 bytes | 64 / 131072 / 1572864 (1.5MiB) |
| context bytes / 모델 JSON 응답 bytes | 2097152 (2MiB) / 65536 |
| 제안의 근거 수 / 편집 파일 수 / 검증 단계 수 | 6 / 12 / 6 |
| 승인 만료 | 기본 7일, hard ceiling 7일 |
| HTTP 요청별 timeout | 현재 20초, hard ceiling 30초 |
| HTTP request/response·web JSON bytes | 최대 262144 |

context 한도는 해당 UTF-8 source bytes와 prompt bytes 합이다. snapshot·fingerprint 생성과
저장된 source fingerprint 재검증은 같은 source 상한을 사용한다. 기본 37개 scope의 실제
소스와 8개 후보 reviewer context는 전체 로컬 검증 사본에서 오프라인 회귀 대상으로 삼는다.
이 회귀는 모델에 실제 소스를 전송하지 않고 순수 Python 대역으로 context 크기를 검증하며,
운영 저장소·키·모델·네트워크·workflow·subprocess 호출은 차단하고 임시 합성 storage만 사용한다.
합성 입력으로 source/context 경계 수용과 1 byte 초과 거부도 검사한다.
source/edit 파일 목록은 개별 경로이며 한 카드의 edit_files 경로 문자열 합도 600자로 제한한다.
private 단일 기록은 1MiB 이하,
scope 입력 파일은 64KiB 이하, instruction 파일은 16KiB 이하, inbox config는 8KiB 이하이다.
한도 안이라도 기존 workflow task 크기 등 후속 기존 정책을 통과해야 실행할 수 있다.
role scope가 없거나 준비 실패하면 호출하지 못한 이유가 남으며 무제한 재시도하지 않는다.

이는 호출 수·시간·입력량 제한이며 전체 달러 비용 보장이나 성능 개선 측정이 아니다.
private 참여 기록은 실제 configured/returned role/provider/model과 실제 result, 시각·경과시간,
제공된 `cli_estimated_cost_usd`만 보존한다. 비용 미제공은 unknown이며 추정을 실청구액으로
바꾸지 않는다. 큰 raw result는 제한 metadata와 truncation 표시로 남는다.
실패·unavailable·not_called를 성공 합의로 표시하지 않는다. 기존 provider별 예산·compaction은 유지한다.

## 후보·검토·날짜 기록

specialist 응답은 추가 key 없이 `{"candidates":[...]}`다. candidate는 정확히
`title, priority, analogy, issue, evidence, benefit, risk, edit_files, validation_plan, documentation_impact`를 갖는다.
title/analogy에는 한국어가 필요하며 각각 80/200자 이하이다. issue 400자, risk 240자,
documentation_impact 360자, validation_plan은 1~6개 각 200자 이하이다.
evidence는 1~6개 `{path,start_line,end_line,summary}`로 summary는 240자 이하이고
승인된 실제 파일의 1부터 시작하는 inclusive line range여야 한다.
benefit은 `{kind,text,evidence}`이고 kind는 `estimated|measured`, text는 240자 이하이다.
measured는 적어도 한 실제 근거를 요구하지만 schema는 측정의 의미적 타당성을 증명하지 않는다.
실측이 없으면 '예상·미측정'으로 설명하고 속도·비용 수치를 만들지 않는다.

reviewer 응답은 정확히 `reviews,documentation`이다. reviews는 각 후보를 한 번씩
`{candidate_id,verdict,reason,documentation}`으로 판단하고 verdict는
`eligible|rejected|needs_evidence`, reason은 360자 이하이다.
각 후보와 전체의 documentation은 `{status,files,reason}`이며 status는
`required|missing|not_required`다. reason은 구체적인 12~360자 설명이어야 한다.
required/missing은 승인된 Markdown 경로가 필요하고 not_required는 빈 files를 요구한다.
읽기 전용 분석만 수행하여 문서를 바꾸지 않았다는 구체적인 not_required는 허용된다.
구현에 필요한 문서는 eligible 제안의 edit_files에 있어야 하며 missing과 eligible은 양립하지 않는다.
승인 밖 필요 문서는 열람하지 않고 explanation에 누락 경로를 보고한다.
이 자문 계약의 required는 '문서를 이미 수정했다'는 뜻이 아니다. 이후 실제 구현 reviewer는
기존 `documentation.updated`와 실제 changed Markdown으로 의미적 완전성을 판단한다.

JSON은 UTF-8 strict parsing으로 중복 key·NaN·fence·후행 텍스트·잘못된 필드를 거부한다.
line range/경로 검사는 구조적 검사이며 의미 판단은 실제 reviewer에게 남긴다.
실패·누락·malformed review는 실행 적격 제안을 만들지 않으며 보고는 partial/failed로 남는다.
일부 specialist 실패에도 독립 전체 review가 유효한 나머지 후보는 partial 보고의 적격 후보가
될 수 있다. 적격 판정은 사용자 승인과 별개다.

ID는 `IMP-`와 proposal digest의 앞 16개 hex이다. 전체 digest는
`{version:"improvement-proposal-v1",candidate,source_fingerprints}` canonical JSON의 SHA256이다.
전체 승인 읽기 의존성마다 `exists,mode,sha256,size`를 저장하며 missing은
`{exists:false,mode:null,sha256:null,size:0}`이다. 편집 파일뿐 아니라 공유 문서와 읽기 참조의
bytes/mode/존재도 ID와 freshness에 영향을 준다. scope 원문 bytes/mode/paths 및 config digest도 별도 기록한다.
동일 후보·동일 의존성은 같은 ID를 재사용하고 human 결정/승인/claim을 덮어쓰지 않는다.
다시 검토하여 review가 바뀌면 기존 승인 review digest가 일치하지 않아 새 승인이 필요하다.

정책 선택 improvements directory에 `scans/<scan_id>.json`, `days/<KST-date>.json`,
`latest.json`, `proposals/<ID>.json`, `web/<date>.json|html|md`를 기록한다.
사람 상태는 `decisions`, 서명 승인은 `approvals`, 일회성 실행은 `claims`/`executions`,
전달 상태는 `delivery`, 재승인 이력은 `history`로 분리한다. directory 0700·파일 0600,
원자 replace/fsync를 사용하며 local 기본 산출물은 `logs/harness/improvements`다.
storage 정책의 readiness 검사를 우회하거나 persistent 설정을 자동 변경하지 않는다.

`daily`는 KST 날짜의 기존 day record가 있으면 내용 변경 여부와 무관하게 같은 보고를 반환하고
새 모델 호출을 0회 수행한다. failed/partial도 자동 재분석하지 않는다. 분석 전 failed day를
먼저 남겨 중단을 건강한 '제안 없음'으로 오인하지 않는다. 이후 수동 `discover`는 같은 날을
명시 재점검하며 이전 scan 기록과 human 상태는 보존한다. 정상 `scanned`의 0개와
미완료 `partial|failed`의 0개는 구분한다. lock/readiness/config 실패가 초기 기록 이전에 나면
day record 자체가 없을 수 있으므로 CLI 실패 로그와 함께 확인한다.

## CLI와 신뢰한 승인·실행

모든 명령은 저장소 루트에서 실제 Python 3.8 venv를 지정한다. 아래 ID·경로는 예시다.

| Make target | Python CLI (`python -m harness.improvements` 뒤) |
| --- | --- |
| `agent-improve [SCOPE_FILE=PATH]` | `discover [--scope-file PATH]` |
| `agent-improve-daily [DELIVER=1]` | `daily [--deliver]`, target이 unattended marker 설정 |
| `agent-improve-status [DATE=YYYY-MM-DD]` | `status [--date YYYY-MM-DD]` |
| `agent-improve-approve PROPOSAL_ID=ID INSTRUCTION_FILE=PATH [LOCAL_ONLY=1]` | `approve --proposal-id ID --instruction-file PATH [--local-only]` |
| `agent-improve-reject PROPOSAL_ID=ID` | `reject --proposal-id ID` |
| `agent-improve-execute PROPOSAL_ID=ID` | `execute --proposal-id ID` |

`report [--date YYYY-MM-DD]`는 정제 web JSON만 반환한다. status는 같은 report와
scan_id·정제된 human_state·별도 delivery 결과를 반환한다. 날짜 생략은 latest record를 사용한다.
approval instruction·서명·raw response를 출력하지 않는다. Make는 각각의 인자를 단일 shell
word로 quoting하며 eval하지 않는다. 사용자는 실제 파일 경로·ID를 넘기고 shell 코드를 넣지 않는다.

```bash
make agent-improve PYTHON=/ABS/VENV/bin/python
make agent-improve-status PYTHON=/ABS/VENV/bin/python
make agent-improve-approve PYTHON=/ABS/VENV/bin/python PROPOSAL_ID=IMP-0123456789abcdef INSTRUCTION_FILE=/ABS/PRIVATE/instruction.txt
make agent-improve-execute PYTHON=/ABS/VENV/bin/python PROPOSAL_ID=IMP-0123456789abcdef
```

approve는 메인/신뢰한 운영자가 실제 사용자의 구체적인 제안 ID별 지시를 확인한 뒤에만 호출한다.
instruction은 UTF-8·비어 있지 않음·NUL 없음, 소유자 소유·nonsymlink·단일 hardlink·0600인
private 파일이어야 한다. approve-all/wildcard는 없고 모델 출력이나 보고서 boolean은 권한이 아니다.
reject도 사람의 결정이며 이미 claim한 실행을 되돌리지 않는다.
`TAVERN_WORKFLOW_CHILD` 또는 `TAVERN_IMPROVEMENT_DISCOVERY`가 있으면 개선 orchestration을 거부한다.
`TAVERN_IMPROVEMENT_UNATTENDED=1`은 approve/reject/execute와 수동 discover 재시도를 거부한다.
scheduler는 marker와 `daily`만 사용한다. discovery marker는 일반 workflow 진입도 차단하며,
unattended marker는 write workflow를 차단한다. scheduler는 일반 READ_ONLY workflow도 호출하지 않는다.

CLI는 인간을 식별할 수 없다. 신뢰한 parent가 instruction 출처를 확인한다는 운영 위협 모델이다.
승인과 claim은 최초 trusted approve가 생성한 private `authority.key`의 HMAC으로 검증한다.
이 키는 provider credential과 별개로 모델에 주지 않는다. 동일 OS 사용자 권한 탈취나
trusted parent의 고의 우회까지 차단한다는 주장은 하지 않는다.

승인은 원래 instruction·proposal/review digest·전체 source fingerprints·정확한 allowed_edit_files·
고유 authorization_id·발급/만료 시각·미소비 상태를 묶는다. 기본 유효기간은 7일이다.
publication은 `commit/pr/three-required-ci/squash-merge/cleanup`으로 고정하며 승인 시에만
`--local-only`를 선택할 수 있다. 이후 execute에서 게시 범위·task·files를 바꿀 수 없다.
approve와 execute 모두 독립 review와 source freshness를 확인하며 execute는 서명·만료·
decision·미소비도 확인한다. bytes/POSIX mode/존재·scope/config 변화는 실패시키고 새 점검을 요구한다.

자체 nonblocking lock과 기존 고정 local project lock으로 discovery/workflow/cleanup 중첩을 거부한다.
storage 선택이 달라도 동일 project lock을 유지한다. execute는 lock 아래 claim을 원자적으로
기록하고 생성한 고정 task·정확한 edit_files만 `workflow.execute`에 전달한다.
workflow가 project lock을 잡은 뒤 guard가 재검증하고 run_id를 private 기록에 남긴다.
그 뒤의 새 Claude 의미 검토·필수 checks·충돌 검사·scoped apply·기존 Git 역할과 게시 정책을 유지한다.
편집 범위에 필요한 읽기 참조/문서/테스트가 부족하면 자동 추가하지 않고 새 승인 필요로 중단한다.

중단·실패·exception 이후에도 claim은 자동 replay하지 않는다. 상태와 error_type·run_id를 보존한다.
`awaiting_github`는 non-success 인계이며 CLI가 0을 반환해도 완료가 아니다. 메인은 기록된 run의
request/accept journal로 실제 CI 3개(`Offline harness (SQLite)`, `MySQL harness`,
`Chromium browser harness`) success·SHA 고정 squash merge·cleanup complete를 확인한다.
cleanup_pending이나 모호한 GitHub 쓰기를 새 execute로 해결하지 않는다.
improvement execution record는 인계 시점 상태이며 이후 완료는 workflow/journal로 확인한다.

재승인이 필요하면 메인이 기존 run을 terminal `passed|failed|interrupted`로 조정하고 merge한
경우 cleanup도 완료한 뒤 새 명시 지시로 다음을 사용한다.

```bash
/ABS/VENV/bin/python -m harness.improvements approve --proposal-id IMP-0123456789abcdef --instruction-file /ABS/PRIVATE/new-instruction.txt --reconcile-run-id EXISTING_RUN_ID
```

workflow에 넘기기 전 중단되어 claim의 run_id가 null이면 실제 미시작을 확인한 후에만
`--reconcile-run-id unstarted`를 쓴다. 기존 claim/approval/decision/execution은 history로
archive한다. reconcile은 기존 실행을 반복하거나 승인 없이 갱신하지 않는다. source가 바뀌면
먼저 새 점검/제안이 필요하다. 서명 기록을 수작업 편집하거나 claim을 지워 replay하지 않는다.

## improvement-web-v1 계약

host는 private 보고가 존재한 뒤 명시 projection만 만든다. HTML/Markdown은 같은 payload를
검증하여 한국어 최대 3카드로 요약하며 HTML escape·Markdown 구문 escape와 A4 print style을
사용한다. 모델 raw HTML을 렌더링하지 않는다. 전체 private 후보는 최대 8개이고 한 장에서
남은 개수만 표시한다. 실제 인쇄 pagination은 브라우저/글꼴에 따라 메인이 확인해야 한다.

최상위 필드는 아래 12개만 허용한다. payload 전체는 262144 bytes 이하이다.

| 필드 | 정확한 의미와 한도 |
| --- | --- |
| `version` | 문자열 `improvement-web-v1` |
| `date` | `YYYY-MM-DD`, Asia/Seoul 날짜 |
| `generated_at` | timezone 있는 ISO8601 문자열 ≤40자, KST 변환 날짜가 date와 일치 |
| `status` | `scanned`, `partial`, `failed` |
| `headline` | 정제 문자열 ≤100자; 기본 '자동 점검 / 승인 전 변경 없음' |
| `summary` | 정제 문자열 ≤400자; 정상 0개와 실패/미완료 0개를 구분 |
| `analogy` | 정제된 일상 비유 ≤200자 |
| `proposals` | 아래 card 배열, 최대 3개, priority high/medium/low 다음 ID 순 |
| `agents` | 최대 5개 `{role,provider,model,status}`만 포함 |
| `counts` | `{candidates,reported,additional_candidates,eligible}` 정수 |
| `documentation` | `{status,files,reason}` 자문 문서 판단 |
| `digest` | digest 자신을 제외한 canonical JSON의 SHA256, 64 lowercase hex |

card의 정확한 필드는
`id,priority,title,analogy,issue,evidence,benefit,risk,edit_files,validation_plan,documentation_impact,review,approval_wording`이다.
candidate의 같은 이름 필드·배열/문자 한도를 사용한다. id는 `IMP-[0-9a-f]{16}`,
review는 `{verdict,reason,documentation}`, approval_wording은 정확히 `'제안 ' + id + ' 승인'`이다.
review verdict는 `eligible|rejected|needs_evidence`이며 누락/실패한 검토는
needs_evidence로 투영하여 독립 검토가 끝났다고 표시하지 않는다.
evidence와 benefit.evidence는 승인 상대 path와 line range/정제 summary만 포함한다.
benefit.kind는 estimated/measured로 그대로 유지하며 한 장에서는 '예상·미측정' 또는 '측정 근거 있음'을 표시한다.
edit_files는 정확한 상대 파일 목록이다. validation_plan/documentation_impact는 JSON에 보존한다.
카드에는 human 승인 instruction·실행 상태·source fingerprints·원본 proposal digest가 없다.

agents.role은 coordinator/downloader/parser/django/reviewer, provider/model은 정제된 실제
식별자(각 ≤80/120자), status는 `succeeded|failed|unavailable|not_called`다.
unavailable/not_called의 provider/model은 null일 수 있다. timing·cost·raw result는 private에만 둔다.
counts.candidates는 전체 후보 수 0~8, reported는 실제 표시 수 0~3,
additional_candidates는 candidates-reported, eligible은 **표시 밖을 포함한 전체 적격 후보 수**다.
적격은 human 승인 수가 아니다. documentation.status는 required/missing/not_required,
files는 승인 상대 Markdown 경로 최대 12개, reason은 구체적인 정제 설명 12~360자다.

canonical JSON은 Python의 `json.dumps(value, ensure_ascii=False, sort_keys=True,
separators=(',', ':'), allow_nan=False).encode('utf-8')`이며 digest 필드 없이 SHA256한다.
반드시 같은 UTF-8 key 정렬/숫자 표현으로 계산한다. digest는 전송 일치 확인이며 사용자 승인이나
서비스 신원 증명은 아니다. human/delivery 상태와 비용 metadata는 payload digest를 바꾸지 않는다.
credential·승인 지시·절대 local 경로·외부 URL·raw 응답·prompt·source text/diff·로그를 웹에
포함하지 않는다. 자유 문자열은 길이 제한과 credential/경로 정제를 적용하고 렌더링 시 escape한다.
정제는 민감한 임의 데이터를 공유할 허가가 아니며 소스 범위부터 private 내용을 제외해야 한다.

## 비공개 HTTP 전달

메인만 `logs/harness/improvement-inbox.json`을 관리한다. ignored private UTF-8 JSON은 정확히
`{origin,token}`이며 owned nonsymlink·단일 hardlink·0600이어야 한다. ancestor symlink도 거부한다.
origin은 credential/query/fragment 없는 HTTPS site origin(경로는 빈 값 또는 `/`)이고 ≤2048자,
token은 공백/제어문자 없는 ASCII 1~4096자다. 모델은 이 파일을 읽지 못하며 코드는 credential을 생성하지 않는다.

기존 로컬 web report가 있어야만 `deliver_report(date, *, inbox_config=None, transport=None, selected=None)`가
전달한다. 기본 config는 위 private 파일이다. trusted parent만 호출하며 child/discovery에서는 거부한다.
unattended daily는 전달할 수 있지만 승인/실행할 수 없다.

1. `POST /api/reports`에 canonical web JSON과 `Content-Type: application/json`,
   `Accept: application/json`, `OAI-Sites-Authorization: Bearer <token>`을 보낸다.
2. POST 2xx 후 `GET /api/reports/<date>`에 같은 인증을 보내 2xx를 요구한다.
3. GET body는 **직접 improvement-web-v1 객체**여야 하며 wrapper 없이 schema·date·재계산 digest·
   로컬 payload digest 일치를 검사한다. POST response body는 권한/결과 근거로 출력하지 않는다.

기본 HTTPS transport는 system TLS 검증을 사용하고 proxy 설정을 읽지 않으며 redirect를 따라가지 않는다.
request/response bytes는 각 262144 이하, timeout은 요청마다 현재 20초다. Content-Length와
실제 누적 read를 제한하고 읽기 deadline을 적용한다. token·header·raw remote body·예외 원문을
로그/터미널에 출력하지 않고 고정 error_type만 기록한다. 3xx·비2xx·초과·날짜/digest 불일치는
`delivery_failed`다. 로컬 보고를 보존하며 전달 상태는 별도 기록한다.

같은 date/digest의 재전달은 같은 immutable payload로 이루어지고 inbox는 이를 idempotent하게 저장해야 한다.
당일 retry는 `make agent-improve-daily DELIVER=1`로 모델 없이 수행한다. 지난 날짜 retry는
trusted parent가 `deliver_report('YYYY-MM-DD')` API만 호출한다. CLI에 별도 deliver subcommand는 없다.
보고를 재생성하기 위해 discover를 호출하지 않는다. 수동 재점검은 새 결과로 당일 보고를 명시 갱신하는 별도 행위다.

## 운영과 09시 예약

2026-10-15 **메인 제공 준비 관찰**: owner-private Sites 보고함이 배포되었고 실제 익명 API는
403, service-auth page/upload/readback/index는 200이었다. 메인이 ignored private 0600
`logs/harness/improvement-inbox.json`에 origin/token만 저장했다. 별도의 명시적 daily local 정책은
`logs/harness/improvement-storage.json`, artifacts/temporary는
`/home/ubuntu/.local/state/tavernof-soul-improvements` 아래 분리된 root, required_mount는 `/`,
free floor는 1GiB이며 storage-status ready로 보고했다. persistent NFS 설정은 그대로다.
메인은 host timezone Asia/Seoul·cron active와 09:00 wrapper 준비도 보고했다.
문서 worker는 이 private 파일/host 설정을 읽거나 HTTP/readiness를 독립 검증하지 않았다.

이 준비 관찰은 최종 구현 의미 검토·full checks·첫 실제 discovery·cron 설치/활성화·이번 구현의
GitHub CI/merge/cleanup 완료를 뜻하지 않는다. 모두 후속 대기다. 이전 single-task 900초 timeout은
source 적용 없이 정리되었고, 이후 NFS RPC hang 실행도 prepare에서 중단되어 모델/apply 전이었다는
메인 인계를 보존한다. 이번 구현 run의 명시적 one-off local `HARNESS_STORAGE_CONFIG`와 향후 daily용
local 정책은 메인이 각각 선택한 것이며 자동 fallback이 아니다. private override를 문서 worker가 검사하지 않는다.

오케스트레이터가 최종 의미 검토와 full `make check`를 마치고 메인이 GitHub journal·CI 3개·
squash merge·cleanup을 완료한 뒤, 메인이 검증된 코드·venv·경로로 scheduler를 설치한다.
메인은 실제 timezone을 재확인하고 configured storage readiness와 private credential mode를 확인한다.
KST date 계산이 cron daemon의 timezone을 바꾸지는 않는다. host가 Asia/Seoul이 아니면
예약 구현의 timezone 지원을 확인하고 메인이 명시 구성해야 하며 암묵 가정하지 않는다.

아래는 **설치하지 않은 template**다. ABS 자리표시자는 메인이 확인한 절대 경로로 바꾸고
실제 venv Python을 직접 사용한다. 기존 private 정책의 absolute path를 명시 선택한다.

```cron
# BEGIN tavern-improvement-daily (read-only discovery)
0 9 * * * cd /ABS/REPO && TAVERN_IMPROVEMENT_UNATTENDED=1 HARNESS_STORAGE_CONFIG=/ABS/REPO/logs/harness/improvement-storage.json /ABS/VENV/bin/python -m harness.improvements daily --deliver >> /ABS/PRIVATE/improvement-daily.log 2>&1
# END tavern-improvement-daily
```

메인은 준비한 trusted wrapper에 같은 working directory/venv/storage/marker를 고정해 사용할 수도 있다.
로그는 private·ignored 경로/권한으로 준비한다. token을 cron 환경/인자/로그에 넣지 않는다.
하나의 표식 있는 job만 설치하고 기존 crontab과 게임 cron을 보존한다. 이 코드/worker는 설치하지 않는다.
실제 invocation은 준비된 storage 정책을 명시하고 readiness 실패를 nonzero로 기록한다.
mount/floor 실패 시 persistent NFS나 다른 local 경로로 자동 이동하지 않는다.

실패 대응은 상태에 따라 다르다. lock 중첩은 기존 실행을 보존하며 무한 재시도하지 않는다.
partial/failed day는 보이는 결과로 남기고 필요하면 메인이 원인 확인 후 수동 discover한다.
전달 실패는 daily 재전송/날짜별 전달 API만 사용한다. claim 후 실패는 기존 workflow와 journal을
조정하고 새 사용자 지시로 재승인한다. 스케줄러는 어느 경우에도 approve/execute하거나
GitHub 게시를 시작하지 않는다. 승인된 실행도 GitHub 앱이 필요한 단계는 메인을 기다린다.

## 검토·검증 인계

이번 문서 영향은 권한·책임·격리·schema·검증·실패 복구·게시 정책 변경이므로
`documentation={status:updated,files:[AGENTS.md,docs/architecture.md,docs/harness-design.md,
docs/harness.md,docs/workflow.md,docs/improvements.md,docs/adr/README.md,
docs/adr/0015-approval-gated-improvement-discovery.md],reason:...}`에 해당하는 실제 Markdown을 수정했다.
이 목록은 worker의 변경 인계이며 최종 reviewer의 의미적 승인이나 문서 완전성 증명이 아니다.
docs/agent-models.md는 참조만 했고 기존 설정을 유지하므로 수정하지 않았다.

오프라인 회귀 명세는 [test_improvements.py](../harness/test_improvements.py)와
[test_workflow.py](../harness/test_workflow.py)에 있다. fake 모델/HTTP를 사용하여 역할별 scope,
write=False·검사/워크플로 미호출, 실패/오류 응답, 날짜 idempotency, 승인 변조/만료/staleness,
claim 경쟁/replay, 정확한 handoff, awaiting_github, private 격리, renderer/digest와 bounded
HTTPS 전달·retry를 대상으로 한다. 명세 존재는 실행 결과가 아니다. 이번 문서 worker는
검사·테스트·실모델·Git·workflow·cron·배포를 실행하지 않았다. 오케스트레이터가 최종 소스의
의미 검토·전체 checks를 수행하고 메인이 실제 게시/CI/merge/cleanup·첫 scan·스케줄 활성화를 확인한다.
