# 프로젝트 지도와 데이터 경계

잠금·복구는 [ADR0027](adr/0027-inspection-lock-isolation-and-diagnostics.md)을 따른다.
workflow 소유권과 source capture/apply/cleanup/freshness mutex를 분리하고 격리 모델/검증 중에는
source 잠금을 놓는다. 전체 baseline 충돌·외부 사용자 편집 보존과 signed claim은 유지한다.
tick은 discovery→artifact 아래 예약/정산하고 source busy면 no-call이다. publication은 잠금 밖에서
frozen digest만 전송한다. [ADR0025](adr/0025-progress-preserving-improvement-reviews.md)의 sealed
두 bank·source-only 진행/cursor와 current freshness 구분, [ADR0026](adr/0026-source-verified-retained-improvement-reports.md)의
실제 Read/프로그램 표본·coverage·ID별 verdict/provenance 및 기존 승인 gate를 유지한다.
표본 밖 무결함과 과거 원인·운영 성공은 추정하지 않는다. 실제 참여 실패와 보존 eligible은 병존한다.
private 진단·snapshot·local·cost는 공개/결과 archive에 넣지 않는다. 저장된 실패의 사유·호출 관측은
복구에도 보존하며 실제 종료 시각과 보수적 회계 시각을 구분한다. Sites와 실제 운영 관측은 parent 소유다.

## 개발 작업 저장과 검증 선택

[ADR0021](adr/0021-local-work-and-result-archives.md)은 명시 v2의 작업·검증·journal을 local
artifacts/temporary에 두고 remote archive를 terminal 결과 보관에만 사용한다. v1/no-config와
기존 NFS 기록은 보존하며 원래 v1 config로 조회·재개한다. archive는 파싱·status·find_run·
progress의 검색/준비 대상이 아니며 mount/floor/private 검사는 ARCHIVE에서만 수행한다.
Git 완료 경로의 최종 save·두 lock 해제·기존 completion hook 뒤 보관하며, 보관 pending은
passed/merge/cleanup 증거를 바꾸지 않고 별도 nonzero다.

[ADR0028](adr/0028-resumed-run-result-archives.md)은 원래 검토/diff/검증을 고정하고 실제
Git/CI3/cleanup 전이를 증명한 trusted-parent 명시 failed→passed 추가 보관만 허용한다.
원래 run mutex와 private 복구 연결을 사용하며 최초 보관은 불변, 별도 고정 세대는 같은 결과만
재개한다. 상태는 archive_original/현재 archive를 구분한다. 새 실행/승인 권한은 아니다.

로컬 freeze는 no-replace directory rename, 원격 완료는 private 결과 디렉터리와 no-replace
파일 link를 사용한다. 로컬 receipt가 디렉터리 attachment와 frozen manifest·임시 이름을 고정한다.
bounded 전송·inventory/hash 검증 후 마지막 commit.json이 게시되고 모든 최종 파일의 0600/nlink=1을
readback해야 완료다. 알려진 동일 inode의 임시/최종 nlink=2 전이만 복구하며 충돌·변조·미확인
대상은 보존한다. 원격 directory rename EINVAL과 파일 link 성공 관측은 main의 primitive 근거다.
후속 trusted parent 보고는 최종 archive.py의 실제 NFS 저장/readback/hash·동일 결과 멱등 재개
성공까지이며 일반 pipeline 전체 성공을 뜻하지 않는다. workspace/credential·raw 모델 응답은 제외한다.

[ADR0022](adr/0022-documentation-only-validation.md)는 실제 최종 baseline→candidate diff에
문서 검증과 적용·게시를 결합한다. 불명/정책/코드/mode/type 변경은 full이며 repair마다 다시
분류한다. Python 3.8 stdlib checker가 링크·fragment·삭제/rename 역참조를 검사하고 Claude가
의미를 검토한다. CI의 세 required gate는 docs 결과 또는 기존 heavy 실행의 실제 성공을 요구한다.
로컬 POSIX mode 정수는 정규화하지 않아 동일 비실행 권한(0664/0640/0600 등)을 허용하고 실제
권한 변경을 거부한다. CI raw Git mode는 기존 100644 기준이다. 여러 줄 inline code는 정확한
backtick run·escape와 block/fence 경계를 구별하며 원문 줄 번호·heading 텍스트·실제 링크 검사를 유지한다.
[ADR0023](adr/0023-new-branch-documentation-validation.md)은 정확한 zero-before와
created=true/deleted=false인 비기본 branch 최초 push에 한해 fetched default ref의 commit을
고정하고 event head와의 유일 merge base→head 전체 diff를 같은 classifier에 전달한다.
불명 metadata/ref/history·dirty/untracked/head 불일치·빈 diff는 full이다. 선택한 전체 changes는
docs 보고서와 세 required gate까지 유지한다. 이번 harness/CI 변경도 full make check 대상이다.

하네스 전체의 목표·책임·격리·검토·게시 설계는 [전체 설계서](harness-design.md),
주요 선택과 변경 이력은 [ADR 목록](adr/README.md)에 기록한다.

TavernofSoul은 다운로더, 파서, Django 적재·서빙의 세 영역으로 구성된다.
`harness/`는 개발 중 이 영역을 검증하는 공통 실행 환경이다.
개발 에이전트는 `harness/agent-models.json`의 역할별 설정으로 Codex/Claude Code CLI를 사용한다.
인증·모델 연결은 [에이전트 모델 연결](agent-models.md)에 있으며 게임 운영 파이프라인과 분리한다.
개발 작업 접수 단계의 [Jev 판단](triage.md)은 경로 규칙에 판단 응답을 더해 배정 추천을 기록한다.
단독 판단 명령은 shadow 모드다. [자동 작업 실행](workflow.md)은 이 추천을 받아
필요 시 계획 → 담당 역할 실행 → Claude 검토 → 필수 하네스 검증 → 범위 내 소스 반영을 연결한다.
기존 사용자 변경을 담은 별도 작업 사본을 사용하며 운영 파이프라인과 분리한다.
Claude Code 기반 구현·검토 역할은 [Jev 대화 기록 압축](compaction.md)을 사용한다.
작업 접수 판단과 별개의 세션 훅이며 기존 TypeSafe 키와 고정된 플러그인 소스를 사용한다.

여신 강화 IES의 발견과 지원 등록은 별개다. `EQUIPMENT_REINFORCE_IES`에 등록한 파일만
강화 수치와 Lua 조회 테이블에 제공하며, 미등록 파일은 별도 JSON 진단과 경고에 남긴다.
명시적으로 등록하지 않은 원본 IES는 파일 발견만으로 자동 지원하지 않는다.
560 재료 생성은 파일 존재를 확인한 뒤 무기/방어구 함수만 호출한다.
Gems의 스킬 FK 적재는 해당 릴리스의 스킬 적재 이후, 같은 importer 트랜잭션에서 수행한다.
강화 테이블/재료는 GoddessReinforcement에, 젬 소켓 보너스는 Gems에 적재한다.
장비의 강화 누적값은 파서가 원본 Lua로 계산하며 UseLv와 재료 그룹을 함께 저장한다.
상세 화면 계산기는 DB의 누적값·확률·재료를 사용한다. 새 컬렉션도 같은 importer 트랜잭션과 prev 롤백에 포함한다.
별도 브라우저 하네스는 이 원본 fixture를 메모리 SQLite에 적재한 임시 Django 서버와 실제 Chromium을 연결한다.
Ubuntu 20.04 ARM 호스트에서는 엔진만 지원 Ubuntu 컨테이너로 실행하며 운영 DB·JSON·cron을 사용하지 않는다.
고정 실데이터 하네스는 iTOS·kTOS 550/560 장비·젬의 원본 hash/revision을 보존하고 같은 격리 경로로 검사한다.
별도 운영 smoke는 공개 두 도메인에 GET/HEAD만 보내며 HTTPS·정적 자산·검색·계산기·젬 연결을 확인한다.
실데이터 샘플과 운영 도메인 결과는 기본 오프라인/합성 fixture 결과와 구분한다.

```text
패치 서버
  → downloader/downloader.py + IPFUnpacker / unpacker_pak
  → <region>_unpack/, Translation/, 다운로드 버전 CSV
  → parser_tidy/main.py + ToS_DB
  → TavernofSoul/JSON_<region>/*.json + version.json
  → ipfparser.management.commands.importAll
  → 지역별 Django DB + JSON_<region>/prev/
  → Django ORM / views / templates / API
```

## 책임과 소유권

| 영역 | 책임 | 주요 진입점 |
| --- | --- | --- |
| 다운로더 | 패치 조회·다운로드·복호화·압축 해제·번역 준비 | `downloader/downloader.py` |
| 파서 | 게임 형식 해석·도메인 값·관계 구성·JSON 출력 | `parser_tidy/main.py`, `DB.py` |
| Django importer | JSON 차이 계산·ID 정규화·DB 적재·비교 기준 갱신 | `importAll.py` |
| Django 서빙 | 검색·관계 조회·화면/API 제공 | `TavernofSoul/urls.py`, 각 앱 |
| 개발 하네스 | 격리 환경·검증 실행·기계가 읽을 수 있는 결과 | `Makefile`, `harness/runner.py` |
| 하네스 저장 정책 | 산출물·비인증 임시 경로 해석, 쓰기 전 mount·공간·private 검사, 기존 실행 조회와 고정 로컬 lock 경로 | `harness/storage.py` |
| 개선 발견·승인 | 개별 승인 소스의 읽기 전용 역할 점검, 독립 검토, private 승인/claim 및 기존 workflow 연결 | `harness/improvements.py` |
| 시간별 개선 연구 | durable slot/예산·9단계 local/owner 검토·오전 보고 journal과 상태 | `harness/improvement_loop.py`, `harness/improvement-loop-config.json` |
| 로컬 초안 전송 | 승인 snapshot의 작은 연속 line window·정제 feedback만 loopback text HTTP로 전송 | `harness/local_model.py` |
| 개선 보고·전달 | 불변 web-v1 오전 보고와 별도 completion-v1 완료 증거만 private Sites로 HTTP 전달 | `harness/improvement_report.py`, `harness/improvements.py`, `harness/improvement_completion.py` |

### 자율 개선의 별도 권한 경계

[시간별 연구·오전 보고](improvements.md)는 게임 데이터 흐름 밖의 개발 보조 기능이다.
최신 [ADR 0017](adr/0017-budgeted-continuous-improvement.md)에 따라 hourly tick은
local(coordinator)→coordinator→local(downloader)→downloader→local(parser)→parser→
local(django)→django→독립 Claude 검토의9단계를 한 slot에 한 단계씩 진행한다. 로컬 포함
KST 하루 최대24회·tick당 모델 최대1회다. 기존 `discover/daily`는 legacy 호환 경로이며
활성 예약은 새 tick 하나만 사용한다. 기존37개 읽기 승인은 확대하지 않는다.
cloud specialist는 `workflow.owner()`별 개별 승인 파일과 명시된 공통 문서만 별도
`write=False, scoped=True` 모델 사본에 제공한다. reviewer는 별도 사본에서 승인 scope 전체를
독립 검토한다. 다른 영역의 소스 대신 앞 역할의 정제된 후보 요약을 공유한다.
디렉터리 탐색이나 모델에 의한 scope 확대는 없으며 테스트·문서가 부족하면 추가 승인 필요로 남긴다.
점검은 소스 쓰기·검사·Git·workflow·운영 importAll을 호출하지 않는다. 기록·lock·격리 임시
context/runtime만 쓴다. discovery→artifact lock으로 예약을 직렬화하고 기존 source mutex로
capture/freshness와 workflow apply/cleanup의 경쟁을 막는다. 개발 모델·검증은 source 잠금 밖이다.

로컬 mlx-vlm0.7.8은 native JSON Schema constrained generation으로 초안을 생성한다.
실제 HTTP `response_format.json_schema`는 strict한 기존 canonical 후보 전체 계약(최대2개,
객체별 additionalProperties=false)과 owner 승인 edit_files enum을 담는다. 양쪽 evidence의
path/정수 줄 범위는 실제 전달한 한 window로 제한한다. top-level enable_thinking=false다.
전송 전 준비 입력의 결합과 재구성한 canonical schema를 검사해 누락·완화·owner/scope/window/
thinking 변조를 호출 전에 거절한다. schema 포함 전체 request 예산으로 whole-line을 선택하고
고정 overhead만으로 넘으면 context_too_large no-call이다. uniqueItems 미지원으로 중복은
client에 남기며 줄 순서·총 문자량·의미와 실제 window 검증/독립 검토가 최종 권위다.
설정은 local-model-config-v2/provider=mlx-vlm, api_model==model인 상대 repository ID다.
별칭 default_model·절대 모델 경로를 요청하지 않고 v1 mlx-lm은 config_invalid로 보류한다.
이 전환의 config digest는 기존 loop fingerprint·승인을 무효화한다. 설치·모델 연결·서비스·
private config 전환과 실제 추론은 메인 책임이며 Linux는 Python3.8 표준라이브러리만 사용한다.
로컬은 owner scope의 한 파일에서 정확한 path/원래 line 번호를 가진 작은 연속 window만 받는다. request24576bytes·output3072tokens·HTTP180초·response65536/header8192bytes 상한,
기본96줄/feedback4096bytes다. evidence와 benefit.evidence는 실제 전달 범위 안에서만 수용한다.
edit_files는 정확한 승인 문자열의 중복 없는 목록이며 미전송 승인 파일도 편집 대상은 된다.
그 파일을 근거로 쓰거나 본문에 언급된 경로·지시를 권한으로 삼을 수 없고, 전체 파일 줄 참조도
전송 window 밖이면 근거로 인용할 수 없다. 지원되는 초안이 없으면 빈 candidates를 요구한다.
기존 공유 validator의 수용 계약은 유지하며 편집 목록 형식·중복·범위 실패만 고정 private
reason으로 구분한다. `candidate_invalid`는 검증 거절이지 검증 제외가 아니다. 공유 검증 후
실제 window 위반은 `evidence_outside_window`이며 raw 값·예외문은 진단에 보존하지 않는다.
분류 한계는 [로컬 모델 문서](local-models.md#후보-거절-진단과-한계)를 따른다. retry·보정·fallback과 public 계약 변경은 없다.
durable owner cursor로 다음 window/파일을 순환하며 긴 한 줄은 slice 없이 명시 skip한다.
local 실패/빈 초안에도 관련 specialist와 최종 reviewer는 정규 slot에서 독립 점검한다. local은 초안 참여자이며
private local_participation의 mlx-vlm/model/stage/owner_role로 구분하고 web-v1 agents에 넣지 않는다.
정식 candidate는 기존 specialist가 자기 소스로 확인·보완하고 reviewer가 전체를 독립 검토한다.
다음 round의 실제 local prompt에 정제 issue·specialist 설명·review.reason을 candidate_id/
draft_digest와 함께 이어받는다. HTTP는 숫자 loopback만 허용하며 DNS/proxy/redirect/remote_code/
도구·자유 파일 접근은 없다. 정상 assistant의 tool_calls:null/tool_call_id:null만 무동작
metadata로 받고 non-null·다른 도구 필드는 거절한다. 모델/endpoint 설정은 private에 남기고
원문 응답·프롬프트·소스·절대 호스트 경로를 진단/로그/보고/public web-v1에 노출하지 않는다.
서버의 schema 무시·위반도 client가 거절한다. 메인의 서버 호환 사전 관측은 최종 bytes의
검토·전체 검증·실제9단계·다음 아침 게시 성공과 구분하며 [관측 한계](local-models.md)를 따른다.

호출 전에 discovery→artifact locks 아래 slot·호출 수·Claude reservation·cursor/inflight를
durable 기록한다. 실패 slot 자동 재호출/daemon/fallback은 없다. source bytes/mode/존재 변화는
회차의 sealed snapshot·pool·cursor를 유지하며 현재 freshness만 상실시킨다. scope/ownership·
discovery/loop/local/agent/workflow/provider/model/protocol 변경은 진행을 무효화한다. loop context digest도 proposal provenance와 HMAC 승인에 결합하여 동일 ID가
재발견되어도 옛 승인의 새 설정 재결합을 막는다. tick은 human decisions/approvals/claims를 쓰지 않는다.

Claude는 KST 하루 추정 US$1·호출 cap min(US$0.20, 잔액, 기존 역할 한도)을 사전 예약한다.
성공한 finite estimate만 정산하고 실패/중단/unknown은 예약 전부 소비, 초과 관측은 기록 후
당일 전체 중단이다. 일반 잔액 소진은 reviewer admission에서 판단한다. 그 차례 전의 로컬/구독
역할은 다른 gate와 call cap 내 진행하지만 reviewer 예산 보류는 stage_index를 유지한다.
새 slot에서도 같은 reviewer를 재판단하고 대기가 풀릴 때까지 이후 로컬/구독 역할도 멈춘다.
09:00 보고는 독립적이다. 구현 workflow 비용은 별도이며 CLI 추정 cap은 실청구 강제상한 보장이 아니다.
기본 자정600초 전에는 모든 모델을 보류하고 rollback/cross-day 중단을 보수적으로 처리한다.
legacy 동일날 비용/호출은 scan_id로 중복 제거해 carry-in하며 unknown은 소비로 처리한다.
GLM은 기존 Coding Lite 인증·anthropic endpoint를 유지하고 trusted parent가 매 admission에
고정 quota endpoint를 조회한다. TOKENS_LIMIT/CREDIT_LIMIT의5h·있으면weekly percentage/reset을
검증하고>=80%·unknown·malformed·조회 실패는 보류한다. 두 model type 모두5h의 정확한
finite numeric0%(bool 제외)에만 absent/null reset을 idle로 허용하며 private null을 미상·미활성으로
유지한다. weekly는0%라도 유효한 reset을 요구하고 비영 사용량의 누락·존재하는 잘못된 reset·
실패 envelope는 거부한다. TIME_LIMIT 단독·model limit 부재·HTTP 실패를0%로 해석하지 않는다.
명목20% 개발 여유이며 진행 중 소모까지 보장하지 않는다. 새 cloud/balance fallback은 없다.

보고는 `[전날09:00, 당일09:00)`의 현재 fingerprint 일치 검증된 완료 회차에서 ID별 최신 verdict를 선택해
09:00 이후 첫 tick에 불변 확정한다. 최대8 distinct 후보를 priority/ID순 최대3카드로 projection하며
eligible 우선은 아니다. 유효 review 없으면0카드 partial/failed이고 옛 참여를 오늘 성공으로
표시하지 않는다. journal prepared→publication_pending→sending→delivered를 사용하며
전송 unknown은 자동 retry 없이 같은 digest만 메인이 reconcile한다. CLI는 두 state lock을
해제한 뒤 기존 Sites deliver_report를 호출하고 sender mutex로 중복 callback을 막는다.
기존 day는 덮어쓰기/자동 재전달하지 않는다. catchup은 오늘 날짜 하나만이며 모델 몰아호출은 없다.
tick의 loop 설정·Store 생성·저장소 readiness 실패는 bounded 정제 paused로 반환하고 모델·키 조회·
보고 확정·publisher·fallback을 실행하지 않는다. 원문 예외를 노출하지 않으며 child/discovery
권한 거부는 이 처리 바깥에 유지한다. 저장소/lock 준비 후 source/config 미준비의 실패 보고와 구분한다.

private 원본에는 모든 읽기 의존성의 SHA256·크기·POSIX mode·존재와 scope/config fingerprint,
실제 모델 참여·실패를 보존한다. 한국어 한 장 요약과 `improvement-web-v1`은 별도 정제 projection이다.
원문·소스·승인 지시·인증은 웹 경계를 넘지 않는다. Sites 인증·UI·배포는 메인 책임이고 host는
HTTPS POST와 날짜/digest GET 확인을 수행한다. 완료 전달은 아래 별도 계약을 쓴다.
정상 제안 없음과 실패/미완료를 구분한다.

hourly 원인은 신뢰한 실제 adapter/validator와 `_call_role` 경계에서 생성한 identity-bound detail만
전달한다. loop는 broad reason·구체 cause/field/rule을 private scan/slot과 cloud192/local192 history,
status·bounded feedback에 연결한다. admission window와 실제 call_started_at/finished_at은 구별한다.
후속 성공·복구는 이전 실패를 지우지 않으며 legacy 상세는 unknown/unavailable이다. CLI 경고/모델·tool
출력 문구는 실패 원인의 증거가 아니다. 코드·숫자 상한·privacy/저장 한계는 [운영 계약](improvements.md#hourly-private-실패-진단과-인계)을 따른다.
web-v1/completion-v1·frozen payload/digest·journal·기존 스케줄/승인 정책은 유지한다.

[ADR 0016](adr/0016-bounded-private-improvement-text.md)은 후보 서술의 PRIVATE 수용과
PUBLIC 표시를 분리한다. title/analogy/issue/evidence summary/benefit text/risk/validation 단계/
documentation impact의 private 상한은 기존 표시 상한의 4배다(예: issue 1600자 / 웹 400자).
수용 본문은 기존 바깥 공백 정규화 이후 축약 없이 reviewer 입력(기존 민감 정보 redaction 적용),
canonical proposal ID/digest·private 저장·재검증·후속 명시 승인/실행으로 이어진다.
`review.reason`과 후보별·전체 `documentation.reason`은 private 1440자 / public 360자다.
후보별 review 원문 전체는 private scan/proposal·기존 approval `review_digest`·eligibility/
authorization 재검증·승인 후 task에 유지한다. 전체 documentation도 scan에 무축약 보존하고
재검증한다. 짧은 review 표현·digest는 불변이다. reviewer는 간결한 한국어 360자 목표와
private hard 1440자를 안내받으며 문서 reason 최소 12자·정확한 coverage·scope·verdict·
문서 상태/files 일치·eligible의 필요 문서 edit_files 포함 조건은 엄격히 유지한다.
웹 projection에서만 정제·공백 합치기·상한 내 `…` 생략을 적용한다. `improvement-web-v1`의
allowlist·기존 public maxima·digest는 그대로며 public validator는 정상 digest가 있어도 과대
서술을 거부한다. 이 web-v1 표시 변경 자체는 Sites API/auth/배포 변경을 요구하지 않는다.
별도 완료 API의 구현·배포 책임은 ADR0020을 따른다.

### 승인 제안 완료 전달 경계

[ADR0020](adr/0020-automatic-proposal-completion.md)의 `improvement_completion.py`는
parent의 완료 검증과 private outbox만 담당한다. 기존 GitHub final save와 project/GitHub lock
해제 뒤 자동 호출되며 Store lock을 역순으로 획득하지 않는다. 선택된 workflow root 안의
private run/report/journal/publication snapshot을 검증하고 legacy local root로 fallback하지 않는다.
각 signed claim이 정확한 run과 proposal digest/authorization_id를 묶는지, signed approval과
approved decision·독립 검토·허용 scope·실제 적용/review/final validation이 맞는지 대조한다.
`passed`·github-v1 identity/config·정확한 PR URL·merged SHA·done·원래 CI 3종 success·
head/merge SHA가 일치하는 verified cleanup proof와 cleanup complete가 모두 필요하다.
실행 전 freshness와 claim 당시 승인 유효기간은 구분하며, 완료 시 현재 source/만료로 재승인하지 않는다.

웹 경계는 기존 `improvement-web-v1`과 사용자 승인된 `improvement-completion-v1` 두 계약이다.
완료에는 proposal ID/status/PR/merge SHA/최초 고정 UTC 시각/canonical digest만 보낸다.
승인 지시·원문·키·절대경로·source/diff/prompt/log는 제외한다. 같은 inbox 인증·TLS/no-redirect
transport를 사용하고 16384 bytes·기존 private timeout 이하로 제한한다. outbox는 0600 canonical
payload와 journal을 HTTP 전에 fsync하고 POST 전 sending을 저장한다. 정확한 GET readback만
delivered로 인정한다. unknown/sending은 자동 GET만, 명시 reconcile은 GET absent 후 동일 digest
POST만 허용하며 conflict는 보존한다. 보고 본문·digest·publication journal과 workflow passed/
merge/cleanup은 전달 실패로 바뀌지 않는다. scheduler/37개 discovery scope/개별 승인·claim/
CI·merge·cleanup 게이트는 유지한다. Sites 소스/API/UI 구현·배포는 메인 책임이다.

### 기존 private 서술과 공개 projection 검증

review reason·후보별 documentation reason·전체 documentation reason도 public validator에서
명시적 360자 상한을 사용하며 재계산 digest가 있는 361자를 거부한다. private validator의
1440자 수용을 public에 적용하지 않는다. 합성 회귀는 416자 review의 5회 호출 완료·무승인
발견·전체 private 저장과 승인 후 mocked handoff·suffix 승인 무효화·세 위치의 private
1440/1441 및 public 360/361·render 경계를 다룬다. worker는 이를 실행하지 않았다.
HTML/Markdown의 최대 3카드 한 장 요약도 유지한다. 전체 응답 64KiB·source/context·구조·경로·근거 줄·배열 상한은
완화하지 않으며 private 초과나 invalid 후보는 기존 partial 경계로 거부한다.
이 서술 수리는 당시 역할·예산·재시도·storage·권한 결정을 바꾸지 않았다. 최신 자동 연구의
스케줄/추정 ledger는 위 ADR0017을 따르며 legacy daily 재사용 의미는 유지한다.
모델 응답은 `_call_role`에서만 strict bare JSON 또는 전체를 감싼 단일 소문자 `json` 태그의
3-backtick fence를 수용한다. 각 delimiter 줄 경계는 LF 또는 CRLF, 바깥 공백은
space/tab/CR/LF만 허용한다. 원래 UTF-8 bytes를 설정 상한으로 검사한 뒤 wrapper만 벗겨
기존 strict `parse_json`에 넘긴다. config/storage/public parser는 fence를 거부한다.
설명문·여러 block·알 수 없는 태그·잘린/중복 key/비유한 JSON은 기존 partial로 실패하며
추출·salvage·retry는 없다. JSON 문자열의 backtick은 보존한다. 같은 내부 JSON의 후보/검토
내용·proposal ID/digest는 같으며 genuine redacted runner result는 원래 wrapper까지 private에 둔다.
prompt는 계속 bare JSON을 요청한다. 이는 제한된 private 서술을 보존하는 transport 호환 수리다.
다음은 2026-10-15 서술 수리의 역사적 인계다. 당시 `GIT=0` continuation은 새 Claude 검토·전체 검증·local apply 후 메인의 실제 재점검과
private 보고 전달을 기다린다. GitHub create_tree의 자동 승인 거부(명시적 공개 동의 부족)는
유지되며 Git 쓰기·재요청·journal 변경은 하지 않는다. 별도 공개 승인 전 게시하지 않는다.
새 실제 점검 성공을 주장하지 않으며 발견 제안은 각각 사용자 승인 전 실행하지 않는다.
최신 메인 제공 scan `1792065346555306548-d8a875`는 GLM 포함 specialist 4명과 Claude
runner가 성공했으나 416자 review reason의 기존 360자 검증으로 partial이었다.
이전 3215 passed는 이번 수리 검증이 아니다. 새 Claude 검토·전체 검증·local apply·
읽기 전용 실제 재점검·정제 private inbox 전달은 메인/실행기의 후속 작업이다.

2026-10-16 최종 프로토콜 인계는 [운영 문서](improvements.md)·[로컬 관측](local-models.md)을 따른다.
최초 초안은 JSON 파싱 뒤 candidate_invalid였고 원문 미보존으로 필드를 알 수 없다. 동일 입력의
편집 범위·근거 줄 위반 재현을 최초 확정 원인으로 삼지 않는다. prompt/order 두 수리는 Claude
검토 뒤 full check 중단/applied=[]였고 보존 초안은 새 검토/전체 검증이 필요하다. parent가 NFS
원본 baseline과 같음을 재확인한 검증 사본 이동·재사용도 성공이나 local fallback이 아니다.
메인의 종전 합성 추론·native 서버 prototype·특정 미검토 bytes 사전 추론 관측은 이번 최종
bytes의 성공이 아니다. 새 Claude 의미검토/full make check·두 umask 권한 fixture 검증/scoped
apply는 하네스, 신규 서비스/private config 전환·최종 추론·실제9단계·다음 아침 게시와 GitHub
전달은 메인 책임이다. 기존 hourly wrapper 활성·2026-10-16 09:00 partial/제안0개 보고1회 전달은
메인 제공 상태이며 확정 보고는 보존한다. worker는 검사·실모델·네트워크·Git·cron을 실행하지 않았다.
과거 자동승인 거부는 보존하고 이번 직접 요청의 기존 Git 역할 인계는 baseline 불일치·명시
거부 시 중단한다. 매 reviewer는 실제 수정 Markdown을 documentation.files에 넣고 의미적
완전성을 평가하며 확장자 검사를 증거로 쓰지 않는다.

모델의 적격 판정과 인간의 승인은 다르다. 메인만 구체적인 사용자 지시로 서명된 private 승인을
발급하고, `execute`가 만료·원본 staleness·정확한 편집 범위·일회성 claim을 검증한 뒤 기존
workflow로 연결한다. 새 의미 검토·필수 검사·범위 반영·GitHub journal·CI 3개·squash merge·
cleanup 완료 경계는 그대로다. 기존 직접 개발 요청의 권한을 자율 제안에 재사용하지 않는다.
[ADR 0015](adr/0015-approval-gated-improvement-discovery.md)에 결정과 비용·복구 한계를 둔다.

운영에서는 로컬 파일인 `cron_<region>.sh`가 다운로드, 파싱, 적재를 순서대로 호출한다.
Git 추적 대상은 5개 지역(`itos`, `jtos`, `ktos`, `ktest`, `twtos`)의
`cron_<region>.sh.example`이며 실제 지역 cron과 settings는 서버의 로컬 운영 파일이다.
파서·import 실패 중단은 `parser_tidy/tests/test_cron_guard.py`가 추적되는 예제를 읽어 검증한다.
다운로더는 변경 0, 변경 없음 1, 실패 2를 반환한다.
모든 지역 예제의 다운로드 실패 중단은 `downloader/tests/test_downloader.py`가 검증한다.
필수 예제가 없으면 skip 대신 실패하며 운영 cron은 실행하지 않는다.
테스트는 로컬 운영 cron으로 대체하지 않는다. 다운로드·import 반환 코드 가드만 분리해
검사하고 파서 실패 가드와 지역 명령 순서를 읽어 확인하므로 운영 파일 없이도 검증할 수 있다.

## 추적되는 설정과 로컬 운영 환경

### 하네스 저장 경계

`harness/storage.py`의 `resolve_storage(ROOT, env=..., fs=...)`가 workflow·GitHub 게시/정리,
모델 보고서·triage·compaction·runner·컨테이너 wrapper의 공통 저장 정책이다.
import 시에는 저장소를 읽거나 만들지 않고 각 작업 시점의 프로젝트 root로 해석한다.
설정 우선순위는 절대 경로 `HARNESS_STORAGE_CONFIG` → 선택적 private
`ROOT/logs/harness/storage-local.json` → 기존 로컬 기본값이며 설정을 병합하지 않는다.
기본 파일이 없을 때만 `ROOT/logs/harness`, 그 아래 `workflows/<run_id>`와 기존 임시 동작을 유지한다.
모델 소스는 기본 `/tmp/tavern-model-context-*/sources`, 일반 검증 임시는 기존 `tempfile` 기본값이다.
명시한 설정의 누락, 존재하는 설정의 오류나 준비되지 않은 mount는 실패이며 로컬 fallback을 금지한다.

version 1 JSON은 정확히 `version: 1`, `artifacts`, `temporary`를 갖고 두 디렉터리 객체는 각각
`path`, `required_mount`, `min_free_bytes`를 갖는다. 경로는 정규화된 절대 경로이고 symlink를 거부한다.
두 application root는 서로 겹치지 않고 저장소의 상위·하위 밖에 있으며 각각 required mount의
엄격한 하위 디렉터리다. mount는 공유할 수 있고 공간 하한은 0 이상의 정수 byte 수다.
추적되는 [설정 예제](../harness/storage-config.json.example)는 실제 호스트 설정이 아니다.
이번 importer/임시 cleanup 수리는 기존 configured NFS 설정·mount·floor를 그대로 유지한다.
새 활성화나 로컬 storage override는 하지 않으며 private 설정을 모델 소스에 제공하지 않는다.

설정 사용 시 새 실행 사본·checks·backup·journal과 일반 보고서는 artifact root에,
비인증 검증 임시와 모델 소스 사본은 temporary root에 둔다.
보고서 선택은 명시적 `--report-dir` → `HARNESS_REPORT_DIR` → 설정 artifact/category → 기존 로컬
기본 경로 순서다. 명시적 보고서 override도 설정의 준비 검사를 우회하지 않는다.
모든 configured mount와 공간 하한을 mkdir·probe·출력 전에 확인하고 쓰기마다 다시 확인한다.
한 읽기 전용 검사 경계에서만 같은 required mount의 공간 측정을 공유하고, 공유 mount라도
두 spec의 floor를 각각 적용한다. 경로·mount·기존 private root 검사는 생략하지 않는다.
측정은 public 호출·mutation·cleanup 경계를 넘지 않으며 readiness/probe 성공 lease나 TTL은 없다.
기존의 올바른 디렉터리는 mkdir를 반복 시도하지 않고, 새 root와 실제 출력/임시 목적지를
probe한다. 무관한 기존 application은 mount/floor/소유자/0700을 계속 검사하되 일상 호출에서
반복 probe하지 않는다. 부모 성공으로 자식 writeability를 추정하지 않으며 configured mount 밖의
명시적 override도 자신의 private 목적지에서 probe해야 한다. `probe=False`는 probe를 생략한다.
명시적 `prepare()`는 두 root를 준비하고 모두 새로 probe하며 `status/doctor --probe`는 두 기존
private root를 모두 검사한다. `status(probe=False)`는 mkdir·chmod·probe 없이 조회하고 실패해도
측정 가능한 `mount_ready`·`free_bytes`(floor 미달 값 포함)·각 `min_free_bytes` 진단을 유지한다.
인터페이스/CLI schema와 로컬 기본 동작, 기존 NFS/private 설정 bytes/mode·mount options·floor는
유지한다. bounded 측정과 probe 선택의 이유·남은 NFS 지연은
[ADR 0018](adr/0018-storage-check-probe-deduplication.md)에 둔다. 호출 수 감소는 전체 실행의
속도나 검토·검증·전달 성공을 보장하지 않는다.
한 호출이 만든 고유 임시 tree의 cleanup은 하나의 고수준 filesystem 작업이다.
첫 chmod/삭제 전 진입과 최종 root 제거 직전에 모든 configured readiness를 새로 확인한다.
파일·ancestor 확인마다 무관한 artifact mount의 공간을 조회하거나 다른 cleanup의 성공을
재사용하지 않는다. 각 directory chmod·file/link unlink·directory rmdir 전에는 root·parent·
ancestor·대상 attachment/ownership/no-follow/device/kernel mount identity를 계속 새로 증명한다.
같은 device의 bind mount도 거부하며 readonly 소유 directory만 pinned descriptor로 접근을
복구한다. 파일 chmod와 외부 link target 접근은 금지한다. statx mount ID를 확보하지 못하면
fail closed하며 일부 정리 실패도 surfaced non-success다. 상세는
[ADR 0013](adr/0013-owned-validation-temporary-cleanup.md)에 둔다.
bounded 대상은 configured prerequisites의 readiness/free-space 조회다. 항목별
mount-point/kernel mount ID 검사는 파일 수와 함께 늘어나며 이를 캐시하거나 생략하지 않는다.
다른 mount를 가로지르는 출력은 거부하고 application 디렉터리는 소유자 일치·0700을 요구한다.
실제 쓰기·fsync·읽기·삭제 probe는 해당 private 디렉터리 안의 고유한 0600 파일만 사용한다.
mount root나 무관한 기존 디렉터리를 chmod하지 않으며 private JSON·이벤트·로그는 0600을 유지한다.

원본 로그인·키 home과 인증을 담은 Codex `/tmp/tavern-codex-runtime-*`, 로컬 공급자/압축 runtime은
보고서 override나 외부 temporary 정책으로 옮기지 않는다. 실제 `HOME`·`CODEX_HOME`과 전역
`TMPDIR`는 바꾸지 않고 검증 자식의 비인증 임시 환경과 pytest basetemp만 별도로 지정한다.
private 설정은 모델 승인 소스에서 제외하며 신뢰한 검증 실행기는 모델 사본 밖의 private 파생 설정으로
mount·공간 정책을 전달한다. 모델 자식에 private 설정 경로나 보고서 override 환경이 노출되지 않도록
분리하는 것은 모델 연결 계층의 책임이다.

프로젝트 직렬화 lock은 artifact 위치와 무관하게 로컬 `ROOT/logs/harness/workflows/.lock`에 유지하며,
workflow와 GitHub cleanup이 공유한다. 프로젝트 lock 다음 journal 옆 `github.lock` 순서로 잠근다.
status/latest와 Git request/accept/resume/cleanup은 현재 root와 기존 로컬 workflows root를 함께 조회한다.
서로 다른 root의 동일 run ID, symlink·탈출 경로는 거부하고 선택된 run별 containment와 승인
hash·SHA·snapshot 검사를 유지한다. 저장 정책 활성화는 과거 journal/snapshot의 절대 workspace 경로를
재작성하거나 자료를 자동 복사·이전·삭제하지 않는다. 운영 cron·unpack·JSON·DB와 사용자 편집은 보존한다.
정책의 상세 책임은 [전체 설계](harness-design.md#공유-저장-정책과-실패-경계),
운영 명령은 [하네스 사용법](harness.md)과 [workflow](workflow.md),
주요 선택은 예정 [ADR 0011](adr/0011-configurable-harness-storage.md)에 둔다.

`TavernofSoul/TavernofSoul/settings_common.py`는 공통 Django 앱·미들웨어·템플릿 등
소스에 포함할 기본 설정을 제공한다. 운영 DB·비밀값·지역 설정 파일은 읽지 않는다.
`settings_harness.py`는 이 common을 가져오며 로컬 운영 `settings_test.py`와 분리된다.
메모리 SQLite, 임시 JSON, `REGION='ktos'`, 오프라인 전용 키와 템플릿 context processor는
하네스에서 재정의한다. `settings_harness_mysql.py`도 추적되는 하네스 설정으로 유지한다.

새 서버에서 원본 운영 파일이 없는 경우에만 `settings_region.py.example`과
해당 지역 `cron_<region>.sh.example`을 `cp -n`으로 복사한다.
설정 파일명과 `TAVERN_REGION`은 같은 지역으로 맞추며, 복사한 로컬 cron의 설치 경로·
인터프리터·가상환경 경로는 새 서버 환경에 맞춰 준비한다.
예를 들어 저장소 루트에서 kTOS를 준비하는 명령은 다음과 같다.

```bash
cp -n TavernofSoul/TavernofSoul/settings_region.py.example TavernofSoul/TavernofSoul/settings_ktos.py
cp -n cron_ktos.sh.example cron_ktos.sh
```

**기존 운영 서버에서는 예제를 복사하거나 기존 파일을 덮어쓰지 않는다.**
새 설치에는 `TAVERN_REGION`, `TAVERN_DJANGO_SECRET_KEY`, `TAVERN_ALLOWED_HOSTS`와
`TAVERN_DB_NAME`, `TAVERN_DB_USER`, `TAVERN_DB_PASSWORD`, `TAVERN_DB_HOST`, `TAVERN_DB_PORT`를
서버 환경에 모두 설정해야 한다. 누락·빈 값은 명확한 설정 오류로 실패한다.
지역은 `itos`, `jtos`, `ktos`, `ktest`, `twtos`, `test`만 허용하며 `DEBUG=False`다.
`JSON_ROOT`는 `BASE_DIR / ('JSON_' + REGION)`, 변경 기록은 `BASE_DIR / 'changes' / REGION`,
정적 출력은 `BASE_DIR / 'staticfiles' / REGION`으로 분리한다.
예제 설정을 읽는 것만으로 실제 DB에 접속하지 않는다. 호스트와 웹훅 등 상세 준비는
[하네스 사용법의 신규 서버 안내](harness.md#신규-서버의-로컬-운영-파일)를 따른다.

운영 INI·지역별 가상환경(`3.8/`, `.venv/`, `venv/`)·`backups/`·빌드 파일의 Git 추적 제거는
실제 디스크 삭제가 아니다. 서버 파일은 그대로 보존하며 새 clone에는 환경 설치가 필요하다.
공통·하네스 설정, `*.example`, `harness/pytest.ini`와 고정 fixture는 계속 추적한다.
이번 정리는 과거 Git 기록을 재작성하지 않는다.
`.gitignore` 추가만으로 이미 추적 중인 파일이 Git 추적에서 해제되지는 않는다.
따라서 이 소스 준비 단계와 서버 파일을 보존하는 후속 추적 해제는 별도 작업이다.
`/challenge.json text eol=lf`는 해당 JSON의 Git 정규화만 지정하며 운영 로컬 CRLF 바이트를
변경하지 않는다. 다른 파일 전체의 줄끝 정책을 바꾸지 않는다.

현재 공개 `origin/master` 작업 사본에는 원본 서버의 개인 설정·cron·가상환경이 제공되지 않았다.
이 단계는 안전한 소스·예제·문서 준비까지이며 보호 파일의 추적 제거와 별도 IPFUnpacker 저장소의
빌드 ignore는 메인 `/root`가 별도 Git PR로 수행한다.
obsolete parsing-server CI 3개도 메인 `/root`에서 로컬에 그대로 보관하고 저장소별 private exclude로
제외할 예정이다. 이 단계에서는 공개 workflow를 만들거나 수정하지 않는다.
실행기가 전체 `make check`를 수행하며 작업자는 테스트·cron·다운로더·운영 import·Git 명령을
실행하지 않는다. 후속 검증·커밋·PR·CI 성공 확인·머지는 현재 작업자 범위 밖이다.

## IPF 추출기 준비와 이번 재실행의 경계

`IPFUnpacker/src/ipf_unpack`의 native 소스와 Git ignore 대상인 설치 바이너리
`IPFUnpacker/ipf_unpack`은 별개다. 소스가 준비되어 있어도 기존 설치 바이너리가
그 소스를 반영했다는 보장은 없다. 빌드에는 GCC, make, zlib 개발 헤더·라이브러리가
필요하며 IPFUnpacker submodule을 먼저 준비해야 한다. 새 개발 환경의 준비 담당자는
`git submodule update --init --recursive -- IPFUnpacker` 후 저장소 루트에서
`make prepare-ipf-unpacker`를 명시적으로 실행한다. 범위가 제한된 작업자는 실행하지 않는다.

독립적인 `.PHONY` 준비 타깃의 내부 호출은 정확히 다음 하나다.

```make
$(MAKE) -C IPFUnpacker/src/ipf_unpack -B release
```

이 호출은 `IPFUnpacker/ipf_unpack`에 직접 링크한다. `config=release`나
`bin/Release` 경로를 사용하지 않으며 별도 install/copy 단계도 없다.
준비 실패는 호출자에게 전파하고 기본 doctor/check/downloader에는 연결하지 않는다.

이번 strict IES CSV 게이트 호환성 수정은 승인된 `downloader/downloader.py`,
`downloader/tests/test_downloader.py`, `docs/architecture.md`, `docs/harness.md`의
4개 파일에 한정한다. 각 작업자는 배정된 파일만 수정하고 승인된 파일만 읽으며
기존 사용자 편집을 보존한다. 기존 역할·provider·model·sandbox 설정을 유지하고
새 스트리밍 전환 등 추가 최적화는 하지 않는다.
원본 IPF·patch와 기존 unpack·JSON·Translation·버전은 보존하며, 작업자는 직접 checks,
Git 명령·재위임·agent-run·harness.workflow, native 소스 열람·변경,
cron·다운로드·importAll 등 운영실행을 하지 않는다.

main이 관측한 공식 current407263 격리 입력에서는 실제 kTOS/iTOS/jTOS 전체 파서가
성공했지만 기존 게이트는 다른 지역에서도 사용하는 iTOS 드롭 표 153개를 거부했다.
이 파일들은 모두 정확히 LF 한 바이트였다. 공식 암호화 IPF 엔트리의 서로 다른 표본
3개를 크기·CRC32·SHA256으로 독립 확인한 결과, 각 binary IES는 본문 없는 156바이트
헤더로 행 0개·열 0개였고 병합된 native 추출기는 종료 코드 0과 정확히 `b'\n'`을
출력했다. 이는 main이 제공한 형식 관측 사실이며 원본 바이트는 외부 모델에 제공하지 않았다.
합성 하네스·native 변환·전체 지역 파싱은 별개 검증이며, 이 관측이 게임 엔진 동작이나
geometry 정확성을 검증하지는 않는다.

새 Claude 검토와 전체 `make check`는 오케스트레이터가, Git 작업은 git 역할이 담당한다.
main은 수정 후 세 전체 파싱에 사용한 기존 IES 경로 9239개 모두에 게이트를 재실행하여
오류 0개를 머지 조건으로 확인해야 한다. 이 수정 후 실데이터 게이트는 아직 통과로 기록하지 않는다.
main은 GitHub 앱 journal과 오프라인·MySQL·브라우저 CI 3개 성공 확인 후 머지하고,
신뢰한 parent의 자동 Git cleanup까지 담당한다. 검증·검토·CI·머지 완료는 담당자의 결과 확인 전까지 주장하지 않는다.

GitHub 게시와 Git cleanup은 권한·완료 경계를 나눈다. git_publish는 기존 앱의 쓰기 journal을 유지하고
merge 성공/SHA를 durable 기록한 뒤 새 읽기 proof와 git_cleanup을 자동 연결한다. git_cleanup만 인증된
parent Git으로 해당 run의 정확한 ref 삭제·tracking prune·clean base ff-only 동기화를 수행한다.
새 repository/default_branch 읽기 proof로 현재 기본 브랜치도 삭제 대상에서 제외한다.
expected SHA lease와 update-ref 비교 삭제는 추가 commit 경쟁을 보존하며 내용/이력 강제 push를 허용하지 않는다.
origin의 raw/effective fetch/push URL 및 rewrite를 승인 저장소와 대조하고 recursion을 명시적으로 끈다.
첫 fetch부터 모든 fetch/prune 전에 표준 origin heads → origin tracking mapping을 검증해 다른 목적지의
ref 갱신을 차단한다. 불일치는 전송·삭제 전에 prune.reason=unsafe_prune_refspec으로 보류한다.
게임 데이터·submodule/unpack·운영 설정/cron/DB는 정리 대상이 아니며 ignored/보호 경로 collision은 보류한다.
앱 반영 승인 파일만 hash/POSIX mode·Git blob/executable mode·index·baseline HEAD를 대조해 private
snapshot/checkpoint 뒤 일시 복원할 수 있다. 사용자 편집·불명확한 상태는 보존한다.
프로젝트 lock → journal lock 순서와 실제 상태 재조정으로 apply/cleanup을 직렬화하지만 외부 경쟁은 남는다.
merge 완료와 cleanup 결과는 분리하고 최종 ref 부재·prune·sync·clean 확인까지 complete여야 passed다.
cleanup_pending은 non-success이며 이전 merged/passed journal은 새 명시적 cleanup 경계에서 재검증한다.
책임·복구·검증 경로는 [하네스 설계](harness-design.md#머지-후-자동-정리와-완료-계약),
[workflow](workflow.md#머지-후-브랜치-정리), [ADR 0010](adr/0010-automatic-post-merge-cleanup.md)에 둔다.

## 다운로더 → 파서 계약

- 다운로드는 임시 `.part` 파일에서 완료한 뒤 공개한다. 비어 있거나 응답 길이가 다르면 실패한다.
- data 패치는 IPF 도구의 복호화·추출 뒤, 임시 `extract` 아래 모든 IES CSV의
  quoting·헤더·행 너비·UTF-8 검증을 통과해야 unpack 디렉터리 복사로 승급한다.
  쉼표·따옴표·줄바꿈을 포함한 필드는 인용하고 내부 따옴표는 두 번 써야 한다.
  인용된 쉼표·여러 줄 필드·헤더만 있는 표는 허용한다. binary IES는 행 0개·열 0개도
  유효하며 native CSV가 정확히 LF 하나(`'\n'`) 또는 플랫폼 CRLF 하나(`'\r\n'`)인
  완전한 파일만 zero-schema 표로 바이트 변경 없이 허용한다.
  0바이트 빈 파일, 빈 헤더 뒤 추가 레코드·여러 빈 줄·쉼표 필드가 있는 빈 헤더,
  헤더 대비 필드 수 불일치·잘못된 인용·UTF-8 오류는 계속 실패한다.
  extract 명령 성공만으로 데이터 정확성이나 승급을 보장하지 않는다.
  검증 오류는 복사·원본 IPF 폐기·버전 전진 전에 중단하며 내용을 보정하거나 행을 버리지 않는다.
- release 패치는 PAK 해제와 지역별 번역 복사를 거친다.
- 버전 CSV인 `revision.csv`와 `release.csv`는 UTF-8 텍스트로 읽고 쓴다.
- 각 스트림의 버전 CSV는 해당 패치의 해제·복사 성공 후 원자 교체로 전진한다.
  여러 패치 중 실패가 발생하면 마지막 완료 버전부터 재시도한다.
- 실패 시 cron은 파서를 실행하지 않는다. 개별 파일 복사까지는 일부 반영되었을 수 있으므로
  디렉터리 전체의 원자 교체나 데이터셋 무결성 manifest로 설명하지 않는다.
- 하네스는 실제 Python 다운로드·PAK 해제를 검사한다. 네이티브 IPF는 대체 실행 파일을 사용한다.

과거 손상 CSV는 보존한 원본 IPF에서 올바르게 준비한 추출기로 새 격리 경로에 재추출해야 한다.
기존 unpack·JSON·Translation·버전과 원본 IPF를 덮어쓰지 않으며,
따옴표나 열을 추측 보정한 결과로 정확성을 주장하지 않는다.
CSV 형식 검증 통과도 binary IES 변환·게임 값의 의미적 정확성 검증을 대신하지 않는다.

## PAK 스트리밍 추출의 메모리·공개·복구 경계

이번 PAK 재시도는 위 IPF/CSV 작업과 별개의 승인 범위다.
[`downloader/unpacker_pak.py`](../downloader/unpacker_pak.py)는 전체 PAK이나 member를
메모리에 모으지 않고 압축 member를 최대 64KiB(65536 bytes)씩 읽는다.
raw-deflate `decompressobj`의 모든 `decompress` 호출은 양수인 1MiB(1048576 bytes)
`max_length`를 전달하며 반환된 조각을 바로 파일에 쓴다. `unconsumed_tail`을 같은
상한으로 처리하고 무제한 `decompressor.flush()`는 사용하지 않는다.
14바이트 header와 이름만 exact-read loop로 모으며 짧은 read를 허용한다.
이름은 양수 native signed 16-bit 길이로 최대 32767 bytes다.
따라서 버퍼 크기는 archive/member 크기·레코드 수에 비례하지 않는다.
동시에 존재하는 입력·tail·출력 조각, 이름의 복사, Python/file buffer와 zlib 내부 상태가
추가되므로 64KiB+1MiB를 총 Python peak나 RSS의 절대 상한으로 해석하지 않는다.
출력 파일 크기와 필요한 디스크 공간의 상한을 줄이는 변경도 아니다.

header는 offset 0/2/6/10에서 각각 native signed `@h`/`@i`/`@i`/`@i`로 읽는
기존 14바이트 형식이다. endian·alignment 형식을 새로 정하지 않는다.
빈 archive, 짧은 header/name/member, 비양수 이름 길이, 음수 compressed/uncompressed
크기와 archive 끝을 넘는 레코드를 거부한다. checksum은 읽되 검증하지 않는다.
blacklist는 raw 이름 bytes에 먼저 적용하므로 해당하는 invalid UTF-8 이름도
디코딩·추출 없이 건너뛴다. 나머지 이름은 UTF-8 오류를 전파한다.
UTF-8 디코딩에 성공한 이름은 절대 경로이거나 `..` 경로 구성요소 또는 역슬래시(`\`)를
포함하면 `ValueError`로 거부한다. 이 검사는 출력 디렉터리 생성·`.part` 작성 등
출력 파일시스템 작업 전에 수행하며, 그 외 정상 이름의 경로 해석은 유지한다.
추출 member는 실제 출력 크기가 선언값과 같고 deflate `eof`에 도달해야 한다.
완전한 deflate stream으로 표현된 빈 출력은 유효하다.
빈 compressed member는 deflate `eof`에 도달하지 못하므로 실패한다.
stream 뒤의 compressed trailing bytes는 기존 `zlib.decompress`처럼 무시하고,
다음 레코드는 stream 끝이 아닌 선언된 compressed 크기의 경계로 seek한다.
checksum·blacklist·format 정책은 바꾸지 않는다.

각 destination은 같은 경로의 `.part`에 쓰고 크기·eof 확인 → 파일 flush/fsync → close →
`os.replace` 순서로 공개한다. 교체 전 실패하면 기존 destination과 archive를 보존하고
실패한 `.part`를 정리한다. 두 번째 레코드 실패 시 첫 번째 파일은 이미 완료된 상태로
남으며, 뒤의 기존 destination과 archive는 유지된다. 전체 archive rollback은 없다.
만든 디렉터리도 남을 수 있다. 모든 레코드 처리와 archive close가 성공한 뒤에만 PAK을
삭제한다. 정리·삭제 자체의 IO 오류는 전파하며, 파일 fsync만으로 directory fsync나
정전·강제 종료 전체의 원자성을 보장하지 않는다.

직접 `unpack()` 호출은 실패 PAK을 보존하며 같은 경로에 정상 bytes를 제공한 재시도는
레코드를 처음부터 다시 적용하고 전체 성공 후 archive를 삭제한다.
상위 다운로더의 기존 회귀는 손상 PAK을 폐기하고 다음 실행에 재다운로드하는 정책을
별도로 확인한다. release 버전은 해제와 번역 복사까지 성공해야 전진한다.
이 두 복구 경계를 archive 전체의 원자 갱신으로 합치지 않는다.

기존 GLM `glm-5.3-flash`, 모든 역할 설정과 NFS 저장 설정·mount·floor를 유지한다.
이전 실제 GLM 소스·fixture·테스트와 Codex 문서는 Claude 승인 후 승인된 7개 파일만
새 격리 모델 사본에 재사용했다. Python3.8 테스트 수집 실패로 이전 run은 failed였고
Root에는 반영하지 않았다. 원본 Root와 baseline은 새 전체 검토·검증 뒤에만 반영한다.
이번 수리는 테스트의 `raw_deflate` helper만 Python3.8 지원 `compressobj`의
`compress(data) + flush()`로 바꾼다. 작은 fixture를 완성하는 compressor flush이며
production decompressor flush 금지와 별개다. 생산 계약·fixture·나머지 테스트는 유지한다.
이전 승인 후보의 제공된 측정, 실행기·메인의 후속 책임과
현재 상태는 [PAK 검증 인계](harness.md#이번-pak-스트리밍-재시도의-근거와-인계)에 둔다.
주요 결정·대안·비용·증거 범위는 [ADR 0014](adr/0014-streaming-pak-extraction.md)에
기록한다. 이전 문서 수리에서 승인 경로의 누락 ADR을 작성했으며 문서 존재 자체는 검토·검증
통과를 뜻하지 않는다. importer ADR0012와 owned-temp ADR0013은 유지한다.

## 파서 → importer 계약

- 입력 JSON은 컬렉션별 객체 또는 배열이다. `version.json`에는 비어 있지 않은 `version`이 필요하다.
- 일반 엔티티는 `$ID`, `$ID_NAME`을 가진다. 관계 컬렉션은 해당 부모 ID 필드를 가진다.
- 아이템의 이름별 인덱스는 `items_by_name.json`; 유형별 분류는 `item_type.json`이다.
- 레시피 이름은 `item_type.RECIPES`에 포함되어야 한다. importer는 레시피의 ID에
  `recipe-`를 붙여 일반 아이템과 동일한 숫자 ID를 공유해도 둘을 보존한다.
- 레시피 재료·대상은 아이템의 `$ID_NAME`을 참조한다. 누락 참조는 적재 실패로 처리한다.
- 패키지 토큰은 파서가 `PackageContents`로 해석한다. importer는 이를 JSON 문자열로 저장한다.
  미해결 참조는 파서에서 `unresolved`로 구분한다.
- 파서는 JSON을 staging에 직렬화·검증한 뒤 공개 파일을 교체한다.
  교체는 파일별이며 실패 시 백업으로 롤백한다. 독자가 실행 중 항상 단일 버전을 본다는 보장은 없다.
- `parser_version.csv`와 공개 `version.json`은 저장 위치가 다르다.
  불일치 시 파서를 재실행하는 기존 로직을 유지한다.
- importer는 입력 스냅샷을 임시 디렉터리에 준비하고 DB 트랜잭션 안에서 적재와 `prev/` 공개를 수행한다.
  예외가 발생하면 이전 비교 기준을 복원한다. 프로세스 강제 종료·정전 전체의 원자성은 별도 문제다.

파서와 importer는 `ipfparser/contracts.py`의 공통 검사로 필수 컬렉션·필드·타입,
정규화한 ID 유일성·참조·수치 범위를 확인한다. 파서는 메모리와 기록한 staging 데이터를,
importer는 복사한 스냅샷을 DB 쿼리 전에 검사한다.
검사 범위·기존 sentinel과 optional 값·단위의 소유권은 [데이터 계약](data-contracts.md)을 참고한다.
모든 자산·보조 인덱스·게임 계산식의 schema를 강제하는 것은 아니다.

`DB.export`는 공통 staging 계약 검사가 일반 JSON 역직렬화 검증도 포함하므로,
그 앞에서 같은 파일을 다시 읽던 중복 pass를 제거한다. `load_release`는 도메인 검사에
보관(retain)할 컬렉션인지와 무관하게 모든 staging `*.json`을 엄격히 읽는다.
정상 export에서는 보조·비-importer JSON과 기록된 `version.json`까지 각각 한 번만
역직렬화하며, 문법 오류·중복 키·비유한 수치·객체/배열이 아닌 루트를 `ContractError`로
거부한 뒤 보관한 컬렉션의 도메인 계약을 검사한다. staging 검증 실패는 승급 전에 중단하여
기존 공개 bytes와 버전을 보존하고 staging을 정리한다. 직렬화 전 메모리 검증과
기존 백업·sentinel·파일별 승급·롤백·재시도 의미, 직렬화 bytes는 유지한다.

공개 `validate_release(data, require_version=True)`는 독립적인 메모리 입력을 받는 경계다.
private `_validate_release_structure`로 릴리스 객체·필수 컬렉션·version을 확인하고,
`finite_tree(data, 'release')`로 보조 필드까지 전체 메모리를 검사한 뒤
private `_validate_release_domain`으로 타입·범위·유일성·참조와 선택적 도메인 계약을 검사한다.
`load_release`는 필수 파일 존재를 확인하고 정렬한 모든 `*.json`에 `load_json`을 적용한다.
각 파일의 문법·중복 키·NaN/Infinity·오버플로(`1e999`)·루트 형식·전체 유한성 검사가
끝난 후 보관한 데이터에 같은 private 구조·도메인 검사를 적용한다. 이 경로에서만
이미 검사한 데이터에 대한 마지막 `finite_tree(..., 'release')` 재순회를 제거한다.
도메인 수치 검사는 유지하며 공개 우회 flag를 추가하지 않는다.
파일 검사 완료의 근거는 해당 호출에서 새로 디코딩한 값에만 유효하다.
원본 bytes는 변경하지 않고 다음 파일/메모리 API 호출은 입력을 새로 검사한다.
검증 순서의 결정은 [ADR 0008](adr/0008-json-validation-single-pass.md)에 둔다.

`load_import_snapshot`은 `load_release`와 같은 엄격한 모든 파일 검사와 구조·도메인 검사를
완료한 뒤 importer 소비 컬렉션·선택적 강화·version만 반환한다. 진단/보조 JSON은 검사하되
최종 반환값에 보관하지 않는다. 기존 `load_release`의 version/None과 `validate_release`의
독립 메모리 검사·오류 path/code/message·첫 오류 순서는 유지한다.
consumed-only는 반환 스냅샷의 수명/보관 경계이며 검증 도중 진단 값의 일시 보관이나
전체 검증의 최대 메모리 사용량을 없앤다는 뜻은 아니다.
한 활성 `handle`의 private staging 값만 재사용하며 mutable 소비자와 version에는 deepcopy를
준다. 직접 `importJSON`·`prev/`·다른 경로는 새 파일 읽기이며 재검사 전과 성공/실패/retry에서
snapshot/path·행 인덱스·스킬 이름 상태를 버린다. DB 쿼리 전 검증·트랜잭션·prev 복원도 유지한다.
스킬/직업의 canonical ID SELECT 인덱스와 로컬 item membership set은 기존 루프/분류 순서,
호출자 목록·우선순위·오류, 행별 save·update=0·created/updated·삭제와 missing/ambiguous
참조 예외를 유지한다. bulk write·동일 save 생략·전역 캐시는 없다.
책임·대안·비용은 [ADR 0012](adr/0012-importer-single-run-snapshot.md)에 둔다.
이번 수리에서 `parser_tidy/items.py`·`luautil.py`는 그대로 두며 장비 Lua batching은 제외한다.
제공된 성능/bytes/2691 selected zero-skip 결과는 후보 근거다. 이전 NFS RPC timeout과
readonly cleanup 실패가 있었고 최종 full validation은 대기다.
[하네스 근거](harness.md#이번-importercleanup-수리의-후보-근거와-검증-대기)와
[workflow 인계](workflow.md#이번-31파일-수리의-검토검증게시-인계)를 함께 확인한다.

유한성 순회 내부의 scalar fast path는 정확한 내장 `str`·`int`·`bool`와 `None` 자식의
재귀 호출만 생략하고, 정확한 내장 `float` 자식은 부모에서 `math.isfinite`로 검사한다.
타입은 `is`로 판별하여 metaclass의 `__eq__`에 의한 동등성 주장이 우회 근거가 되지 않게 한다.
컨테이너·하위 클래스·알 수 없는 객체는 기존 재귀와 `isinstance` 처리로 돌아가며,
dict·list·tuple·float 하위 클래스 지원과 알 수 없는 객체의 기존 동작을 유지한다.
scalar 루트의 비유한 float도 계속 실패한다. dict 삽입 순서·list/tuple 인덱스 순서와 깊이 우선
첫 오류 선택, key repr·인덱스 표현, `ContractError`의 path·code·message·문자열은 동일하다.
진단 경로는 첫 실패 분기에만 구성하며 정상 반환값·입력 identity·alias를 보존한다.
공유 컨테이너 identity 캐시나 전역 결과 캐시, 호출/build/지역 간 상태를 추가하지 않아
mutation·파일 교체·재시도는 현재 입력을 다시 검사한다.

이 국소 구현 개선은 ADR 0008의 책임을 바꾸지 않으며 새 ADR을 요구하지 않는다.
공개 메모리 검사와 모든 staging·보조·version 파일의 엄격한 디코딩, schema·도메인·참조·범위·
유일성 검사 및 기존 오류 순서를 유지한다. memory-before-serialization과 file-after-serialization은
별개 경계로 남고 `DB.export`의 안전 검사·직렬화 bytes·backup·sentinel·승급·롤백·version 재시도는 유지한다.
독립 의미 검토, 오케스트레이터의 전체 `make check`, 반영 후 메인의 최종 전후 실데이터 시간과
지역별 JSON bytes 동일성 확인이 필요하며 어떤 GitHub 게시 도구보다 먼저 완료해야 한다.
회귀·측정·문서 판단 요구사항은 [하네스 안내](harness.md#최적화-회귀와-성능-근거)에 둔다.

## 파서 초기화 비용과 상태 경계

`iesutil.load()`는 한 호출에서 길이 128 이하 문자열 token의 변환 결과인 immutable scalar를
최대 4096개 재사용한다. 변환은 기존 `int` → 실패 시 `float` → 실패 시 원값 순서이며,
NaN·누락 셀의 `None`·초과 필드의 mutable list는 캐시에 넣지 않는다.
문자열 cache hit은 길이 판정과 변환을 생략하며, miss에서 기존 길이 128·용량 4096 제한을 적용한다.
행과 list는 독립적으로 유지하고, 캐시는 반환·오류 시 수명이 끝난다.
매 load는 원본 파일을 다시 읽으며 호출·파일·지역 사이에 캐시를 공유하지 않는다.
이 변환은 raw 장비 CSV의 문자열 UseLv를 Lua로 전달하는 `items.parse_equips` 경로와 별개다.

`items.parse_items`와 `items.parse_equips`는 처리 완료된 원본 CSV 행을 추가 목록에 누적하지 않는다.
필요한 출력 객체와 Lua 참조는 그대로 유지한다.

`items.parse_equips`는 출력 `EQUIPMENT` 이름 목록의 기존 list 객체·순서·중복을 보존하며,
새 이름은 원본 행의 첫 등장 순서로 한 번만 추가한다.
중복 확인은 한 호출 안의 임시 set으로만 수행하고, 다음 호출은 현재 목록에서 set을 다시 구축해
호출·파일·지역 사이에 공유하지 않는다.
이름이 이미 있어도 모든 장비 행과 Lua 수식 처리를 계속 수행하며 후속 행의 값 덮어쓰기를 유지한다.

`items.parse_equips`의 legacy 강화 40단계·초월 10단계는 각 row의 RefreshScp 실행 뒤
활성 분기의 첫 사용 시 Python `LUA_RUNTIME` registry에서 callable을 조회하고 해당 루프에서만
local 참조를 재사용한다. 강화 호출은 DEF → price → ATK → price 순서를 유지하며,
양쪽 분기에서는 같은 price 참조를 두 번 호출한다. 기존 ATK/DEF 바깥 guard를 유지하므로 비활성 row의
`Reinforce_2` 원값은 보존하고, 활성 row는 단계마다 0..39를 대입한다. 초월은 각 호출 전에
`Transcend=0`을 대입하며 마지막 callable의 row 변경도 보존한다.
참조는 루프 종료 시 해제하고 다음 row·parse·init·지역으로 공유하지 않는다.
RefreshScp가 바꾼 registry 항목은 현재 row의 첫 조회에 반영하며, 루프 내부 계산 callable이
registry를 직접 교체하는 임의 동작까지 보존한다고 주장하지 않는다. 원본 CSV 문자열의 사전 변환,
Lua 함수 재컴파일·전역 alias·결과 캐시는 추가하지 않는다. 기존 인자·호출 순서·가격 fallback,
수치 필터·타입·정밀도, 비활성 분기의 lazy 조회와 RefreshScp 실패 전파·반환값을 유지한다.
회귀 경계와 실데이터 측정 책임은 [최적화 회귀와 성능 근거](harness.md#최적화-회귀와-성능-근거)에 둔다.

legacy Lua 줄 전처리는 quoted index → require 제거 → method 변환 순서와 기존 regex/replacement를
유지한다. private compiled regex를 재사용하고 각 단계의 현재 줄에 literal substring guard를
적용해 매칭이 불가능한 경우에만 치환 호출을 생략한다. 이는 전처리 비용만 줄이며,
`luautil.init()`는 매번 새 LuaRuntime을 만들고 실패 가능한 초기화 전에 레지스트리를 reset한다.
원본 로딩·함수 분리·override 보호·whole-module 실행과 필수 함수 실패 전파 계약은 유지한다.
함수 선언 감지도 기존 패턴과 기본 flags를 private compiled regex로 재사용하며,
전처리된 현재 줄에 필수 literal `function`이 없을 때만 매칭을 생략한다.
`harness/parser_fixture.py`의 `isolated_parser_state`도 새 runtime/레지스트리와 격리된
아이템·스킬·몬스터 상태를 사용하고 `finally`에서 기존 상태를 복구한다.

`TryGetProp`는 한 호출에서 `item[prop]`에 대한 `tonumber` 결과를 local 변수에 저장해 재사용한다.
행·지역·호출 사이의 값 캐시는 만들지 않으며, setter 이후 재조회는 현재 행의 값을 읽는다.
기존 attribute handler, nil/default 분기, 오류 전파와 setter 동작을 유지한다.
새 runtime과 반복 `init()`의 상태 경계도 유지하며 Lua 브리지의 수치 정밀도 정책은 변경하지 않는다.
`parser_tidy/tests/test_lua_attribute_handlers.py`의 테스트는 실제 Lupa runtime과
실제 `init_global_functions`를 사용해 독립 기대값과 기존 helper의 반환값·타입을 함께 비교한다.
`tonumber` 호출 수로 중복 변환 제거를 검증하고, 원본 IES 로딩은 격리한다.
테스트의 전역 상태·patch·변환 wrapper는 `finally`에서 복원한다.
이 helper 검증과 원본 IES를 사용하는 전체 실데이터·지역별 JSON 출력 검증은 별개다.

장비·몬스터가 공유하는 `luautil.attr_getter`는 여섯 정수 속성 이름
`Blockable`, `HPCount`, `ReinforceArmor`, `TranscendArmor`, `ReinforceWeapon`,
`TranscendWeapon`의 membership을 모듈에서 한 번 만든 immutable `frozenset`으로 조회한다.
Lua가 전달하는 문자열 이름마다 목록을 선형 탐색하던 비용을 줄이는 국소 구현 변경이다.
먼저 `name in obj`를 실행하고, 존재할 때만 `obj[name]`을 한 번 읽는 매핑 순서를 유지한다.
dict 하위 클래스의 `__contains__`·`__getitem__`도 그대로 사용하며 `dict.get`으로 우회하지 않는다.
없는 필드는 `0`, 있는 여섯 속성은 기존 `int` 변환, 그 외 속성은 raw CSV 문자열을 포함한
현재 원값을 반환한다. 존재하는 `None`·`False`·빈 문자열을 누락 값으로 취급하지 않는다.
정수 속성의 `False`는 `0`이며 `None`의 `TypeError`, 빈 문자열·잘못된 숫자 문자열의
`ValueError`, 무한대 숫자의 `OverflowError` 등 기존 변환 예외를 그대로 전파한다.
membership의 `TypeError` fallback만 이름 판정에 한정하고 매핑 접근·변환 예외는 잡거나 재시도하지 않는다.
`attr_setter`는 기존 `obj[name] = value`로 쓰며 Lua·Python의 mutation 이후 조회는 즉시 현재 행을 읽는다.

일반적인 비문자열 직접 Python 이름은 기존 원값·누락 처리를 유지한다.
해시할 수 없는 이름을 허용하는 custom mapping에서는 membership 실패 시 기존 순서의 이름 tuple로
판정하는 cold fallback을 사용한다. 일반 dict의 비해시 키 오류는 그 앞의 매핑 membership에서 그대로 발생한다.
임의 직접 Python 객체의 custom hash/equality 호출 순서·부작용까지 목록 탐색과 같다고 보장하지 않는다.
이는 문자열 이름을 전달하는 공개 Lua 프로토콜의 범위를 확장하는 변경이 아니다.
상수 이름 집합만 공유하며 행 값·테이블·계산 결과·Lua 전역·함수를 build·행·지역 사이에 캐시하지 않는다.
반복 `init()`의 새 runtime·registry reset과 fixture 상태 복원 경계는 유지한다.

장비의 RefreshScp 이후 lazy callable 조회와 분기 변화, 40단계 DEF → price → ATK → price
호출(두 price 호출 포함), 비활성 행의 기존 mutation, 10회 초월 및 grade-6 처리는 유지한다.
몬스터도 두 번의 순서 있는 상수 주입·현재 의존 값 읽기·최종 getter 호출을 유지하며,
지역 override의 EXP/JOBEXP 의미와 `All`에 내보내는 Python 행·raw 필드 순서는 바꾸지 않는다.
게임 Lua 수식·등록 방식·행 표현·수치·직렬화 정책은 유지한다.
기존 callable 참조 재사용 측정은 일관된 속도 개선을 보이지 않았으므로 성능 근거로 삼지 않는다.
이번 변경의 회귀·전체 `make check`·지역별 최종 실데이터 시간 중앙값·모든 JSON bytes 비교는
결과가 제공되기 전까지 **대기(pending)**다. 요구 증거와 문서 영향 판단은
[하네스 안내](harness.md#최적화-회귀와-성능-근거)에 둔다.

제공된 로컬 kTOS 진단에서 cProfile의 초기화 내 `iesutil.load` 41회는 self 2.84s/total 3.43s,
`init_runtime`은 total 3.99s였다. 이는 profiler를 켠 부분 실행 시간이다.
별도의 profiler 없는 fresh 6-worker 초기화 측정은 기존 중앙값 약 6.008s,
IES/Lua 결합 후보 약 3.002s였으며 매번 새 runtime을 생성했다.
전체 `LUA_SOURCE`와 로드된 IES rows의 digest, functions 12257/tables 32 일치는
제공된 로컬 진단 사실이며 최종 적용 코드의 검증 결과나 전체 pipeline wall 성능 보장이 아니다.
알려진 CSV quoting 오류 한 행은 명시된 로컬 diagnostic 복사본에서만 대체했다.
원본 게임 데이터·진단 스크립트·전체 로그는 이번 승인 문맥에 제공되지 않았으며,
최종 코드의 독립 benchmark는 `/root`가 별도로 확인한다.

## XML·관계 정리·디렉터리 인덱스의 상태 경계

`game_xml.fromstring`은 디코딩된 문자열에 `_CONTROLS`(XML 1.0 불허 ASCII 제어문자)가
전혀 없으면 `ET.fromstring(text)`로 직접 파싱한다. legacy masker·marker 충돌 검사·복원 순회를
생략하며 일반 노드·속성·text·tail과 표준 `ParseError`의 code·position·message를 유지한다.
불허 문자 참조는 원문에 직접 제어문자가 없어도 표준 파서가 거부한다.
제어문자가 있으면 기존 마스킹·문자 참조/DTD entity의 marker 충돌 검사·복원을 수행한다.
확장은 실제 시작 태그의 정확히 `ScriptName`인 quoted 속성 안에 직접 들어 있는 제어문자에만
적용한다. 다른 속성·text·tail·comments·CDATA·PI와 잘못된 markup을 복구하지 않는다.
marker와 복원 상태는 한 파싱 호출 안에서만 유지하며 원본 파일을 쓰지 않는다.
정확한 허용 문자·디코딩 경계는 [데이터 계약](data-contracts.md#스킬-엔진-xml의-제한된-확장)에 둔다.

`skills.parse_clean`은 현재 `skills`의 순서로 `Link_Job is None`인 항목을 모아 기존처럼
`skills[str($ID)]`와 `skills_by_name[$ID_NAME]`를 순서대로 삭제한다.
삭제한 원래 ID의 호출 내 임시 set으로 속성·직업과 대응하는 이름 인덱스 객체의
`Link_Skills`를 일괄 필터링한다. 객체 identity의 임시 set으로 별도 이름 객체와
여러 키·컬렉션이 공유하는 alias를 포함해 각 객체를 한 번만 처리한다.
문자열·정수 ID를 정규화하지 않고 기존 비교 의미와 생존 링크의 순서·중복을 유지한다.
새 목록을 할당하므로 외부에서 참조하는 이전 목록의 내용도 유지한다.
비활성 스킬이 없으면 링크나 이름 인덱스에 접근하지 않는다.
두 set은 반환·오류 시 수명이 끝나며 같은 객체 재호출·외부 수정·다른 지역에서도 현재 데이터로 재구성한다.

`maps.parse_links_npcs`는 map CSV의 첫 행에서 필요한 시점에 현재 `PATH_INPUT_DATA`의
`ies_mongen.ipf`를 한 번만 조회해 lowercase 이름 → 원래 파일명 인덱스를 만든다.
동일한 lowercase 이름은 `os.listdir` 반환 순서의 마지막 항목이 우선하며 정렬하지 않는다.
빈 인덱스도 그 호출에서 재사용하고, map 행이 없으면 생성점 디렉터리를 조회하지 않는다.
행이 있으면 기존 directory 조회 오류는 전파한다. anchor/gentype 조회 실패 시 기존 파일명 fallback과
누락 파일·미해결 NPC/item을 생략하는 처리, 좌표·인구 병합·respawn·아이템 canonical ID 연결을 유지한다.
인덱스는 호출 내 상태이며 다음 호출은 현재 지역·원본 경로·디렉터리 내용을 다시 조회한다.
직접 `parse_links_npcs` 재호출은 기존처럼 관계 배열에 추가한다.
상위 `maps.parse_links`가 관계와 지도 미해결 진단을 초기화하는 책임은 바뀌지 않는다.

이 네 최적화의 회귀 명세는 `test_game_xml.py`, `test_release_contract.py`,
`test_atomic_release.py`, `test_combat_source_fixture.py`, `test_world_source_fixture.py`에 있다.
문서 작업자는 실행하지 않았다. 제공된 prototype/local diagnostic 수치는 최종 회귀·전체 파서·CI 성공이나
누적 개선율의 증거가 아니며 [ADR 0008의 근거 한계](adr/0008-json-validation-single-pass.md#진단-근거와-검증-상태)에 구분해 기록한다.
최종 소스의 지역별 전체 실데이터 검증과 여태 적용한 최적화의 누적 성능 비교는 메인 `/root`가 별도로 수행한다.
모델·provider·effort·network·worker 설정과 기본 Git 역할은 유지한다.
검토·필수 검증·GitHub CI 성공 확인 뒤 SHA를 고정해 merge하는 게시 책임과 정책도 유지한다.

## 첫 검증 경로

`harness/fixtures/minimal_release.json`은 재료, 숫자 ID가 겹치는 레시피,
패키지 원시 토큰과 importer에 필요한 빈 컬렉션을 포함한다.

```text
고정 입력
  → 실제 resolve_package_contents
  → 실제 ToS_DB.export (임시 JSON 디렉터리)
  → 실제 importAll (메모리 SQLite, 실제 migrations)
  → ORM 관계 확인
  → Django test client로 아이템 검색·상세 HTML 확인
```

네트워크 다운로드, 전체 원본 파일 파싱, 아이콘/맵 생성, 운영 MySQL, 브라우저 JavaScript는
이 첫 경로의 검증 범위에 포함되지 않는다.

## 아이템 원본부터 서빙까지

`harness/fixtures/parser/`는 직접 작성한 CSV 형식 IES, XML/TSV 번역,
Lua 계산식과 독립적인 기대값을 포함한다. 입력 파일 안내는
[fixture README](../harness/fixtures/parser/README.md)를 참고한다.

```text
임시 unpack IES + 번역 XML/TSV + 공유 상수/Lua
  → 실제 parse_xac + translation.makeDictionary + items.parse
  → 실제 ToS_DB.export
  → 실제 importAll + ORM
  → 아이템·장비·레시피·패키지 검색/상세 HTTP
```

원본 ID는 문자열이고 JSON의 쿨다운은 ms를 초로, 장비 내구도는 원본의 1/100로 변환한다.
Lua 계산 결과는 JSON 숫자로 출력한다. 하네스는 장비 수치와 소수 무게·거래 플래그,
레시피 재료·대상, 패키지 정상/미해결 참조를 검사한다.
같은 입력의 반복 실행과 변경 입력의 재계산, 파싱 실패 시 공개 JSON·버전 보존 및 복구를 확인한다.
DB의 버전은 이력으로 쌓이며 같은 버전은 중복 생성하지 않는다.

이 경로는 아이템 도메인 중 작은 선택 범위를 검증한다.
네이티브 바이너리 변환, 게임 전체 Lua 계산식, 다른 도메인, 전체 `main.py` 실행은 포함하지 않는다.

## 스킬·몬스터·드롭 연결

`harness/fixtures/combat/`는 아이템 샘플에 직업·스킬트리·스킬·몬스터·드롭 IES,
스킬 도구 XML과 Lua를 더한다. 실제 파서 모듈을 운영 순서에 따라 호출하고
같은 JSON을 Django로 적재한다. 세부 입력은 [fixture 안내](../harness/fixtures/combat/README.md)에 있다.

- 직업과 플레이어 스킬의 ID는 문자열이고 스킬의 `Link_Job`은 직업 ID를 참조한다.
- 스킬 `TypeAttack`의 중복 제거는 후보의 첫 등장 순서를 보존한다.
  이는 기존 set 순회에서 발생하던 Python hash seed별 `TypeAttack` 배열 순서와
  `skills.json`·`skills_by_name.json`의 변동을 제거한다.
- 스킬 비율은 파서가 `0 < 값 < 1`인 계산 결과를 100배해 출력하고 importer는 재확대하지 않는다.
  기본 쿨다운과 레벨별 쿨다운은 ms이며 기본 쿨다운의 화면 표시는 초다.
- 몬스터 ID는 JSON에서 숫자다. 갑옷 `Iron`은 `Plate`, `WIDLING`은 `BEAST`로 변환한다.
  field status 보정은 파일명 정렬 순서로 적용하고 EXP·JOBEXP 의미를 유지한다.
- 몬스터 스킬은 `SkillType`으로 연결 ID 목록을 만들고 importer는 타수와 현재 연결 목록을 저장한다.
- 몬스터 드롭은 아이템 ClassName을 아이템의 원본 ID로 해결한다.
  확률은 `DropRatio / 100`의 퍼센트이며 수량 최소·최대는 정수다.
  미해결 참조는 DB 관계 대신 `unresolved_drops.json`에 문맥을 남긴다.
- 출처 지역·입력 버전은 `item_monster.json`과 `build_provenance.json`에 기록한다.
  입력 버전은 다운로드 revision에서 읽으며 공개 파서 버전과 다를 수 있다.
  출처 필드는 현재 ORM에 별도로 저장되지 않는다.
- 지역 보충 스킬 데이터는 `PATH_INPUT_DATA`의 프로젝트 루트 아래 JSON에서 읽는다.
  임시 원본 테스트가 코드 저장소의 운영 JSON에 의존하지 않도록 한다.

하네스는 반복 실행, 변경 수치와 관계 삭제, 파싱 실패 시 JSON 보존,
importer 실패 시 DB·이전 비교 기준·버전 복원과 재시도를 검사한다.
이는 작은 iTOS 샘플의 검증이며 전체 원본 파이프라인이나 운영 MySQL을 대신하지 않는다.

## 맵·속성·버프 연결

`harness/fixtures/world/`는 아이템·combat 원본에 지도/드롭/생성점·속성·버프 IES와 번역을 더한다.
입력과 계산 근거는 [world fixture 안내](../harness/fixtures/world/README.md)를 참고한다.

- 속성은 스킬 정리 전에 파싱·연결·정리한다. Link_Skills는 스킬 ClassName,
  스킬·직업의 Link_Attributes는 속성 ID이며 보충 연결도 같은 규칙을 쓴다.
  `attributes.parse_clean`은 기존 비활성 판정으로 삭제할 속성의 원래 ID를 호출 내 임시 set에 모아
  직업·스킬의 Link_Attributes를 일괄 필터링한다. 숫자·문자열 ID를 임의 통합하지 않으며,
  생존 링크의 순서·중복을 유지하고 새 목록을 할당하여 외부에서 참조하는 기존 목록의 내용도 보존한다.
  숫자 키·이름 양쪽 인덱스가 같은 객체이거나 별개 객체여도 정확히 정리하며,
  속성 인덱스 삭제의 기존 순서와 `str(key)` 규칙을 유지한다.
  제거할 속성이 없으면 목록 교체나 직업·스킬 접근 없이 반환한다.
  임시 삭제 집합은 호출·인스턴스·지역 사이에 공유하지 않는다.
- 맵 직접 확률은 일반 맵에서 DropRatio/100, unknownsanctuary는 /10000이다.
  그룹은 같은 기준의 맵 확률에 그룹 내 가중치/합계를 곱한다. 음수 가중치는 실패한다.
  수량은 미제공 호환값 0이고 미해결 아이템은 드롭 관계 대신 문맥과 출처를 남긴다.
- 정상 지도 ID 연결은 릴리스의 기존 지도를 참조해야 한다. 추가 층 목록에는 2층 이상을 넣고 1층 자기 참조를 만들지 않는다.
  같은 WorldMap 묶음의 1층 좌표가 없으면 파일·지도 이름·해당 좌표를 경고하고 optional floor grouping만 생략한다.
  실제 지도·ID·WorldMap·물리 연결은 유지하며 다른 ground를 추측하거나 지도를 생성하지 않는다.
  알려진 PhysicalLinkZone 토큰은 원본 순서로 연결하고, 알 수 없는 토큰은 원문·출처와 함께
  `unresolved_map_links`에 보존한다. 진단 존재가 잘못된 정상 `Link_Maps` FK를 허용하지는 않는다.
- 생성 좌표는 지도 중심·MAP_SCALE·bbox로 변환하고 생성 수를 병합한다.
  RespawnTime(ms)은 JSON TimeRespawn(초)으로 변환한다. importer는 좌표를 평탄한 문자열 배열로 저장한다.
- 버프 네 원본 파일을 정해진 순서로 읽고 같은 ID는 뒤 파일이 우선한다.
  Common_는 제외하고 optional 그룹은 null을 유지하며 ApplyTime은 ms다.
- 반복 맵 관계 구성은 생성점·층·지도 미해결 참조를 새로 만든다. 몬스터 미해결 참조는 보존한다.

하네스는 JSON부터 DB·HTTP까지 단위·관계·수치 변경·관계 삭제·보존과 재시도를 확인한다.
이 경로는 지도 이미지 생성·자르기나 브라우저 canvas를 실행하지 않는다.
전체 지역·모든 유형·속성 Lua 비용/해금 계산·운영 MySQL은 별도 검증이다.

## MySQL과 CI 경계

기본 `make check`는 네트워크나 외부 DB가 필요 없는 SQLite 검증이다.
`make check-mysql-container`는 별도의 MySQL 8.4.11 컨테이너를 만들고 같은 통합 경로를 실행한다.
전용 스키마·계정 권한·루프백 포트를 제한하며 JSON·캐시·미디어는 기존 임시 하네스 경로를 유지한다.
실제 migrations, strict SQL, InnoDB, utf8mb4, ListCharField와 검색 정규식,
DB 오류 발생 후 DB·Version·prev 보존을 확인한다.

`.github/workflows/harness.yml`의 SQLite/MySQL 작업은 각각 새 환경에서 실행하고 결과를 artifact로 보관한다.
고정 서버 프로필과 작은 fixture의 호환성 검증이며 운영 DB 접속·배포·전체 데이터 적재는 수행하지 않는다.
접속 제한·명령·보고서와 운영 환경 차이는 [하네스 사용법](harness.md)을 참고한다.

## 지역별 경로와 추가 원본 유형

`harness/fixtures/regional/`은 직접 작성한 CSV IES·XML/TSV·Lua와 지역별 공유 상수를 사용한다.
5개 지역의 번역/원문 처리, 스킬 보충 JSON과 드롭 데이터셋 출처 규칙을 같은 실행 경로에서 확인한다.
기존 아이템·combat·world 도메인에 마법 무기·방어구·카드·컬렉션을 추가하며
원본 파싱 → JSON → 실제 importer → ORM/HTTP와 실패 시 보존·재시도를 SQLite/MySQL에서 검사한다.

Vaivora 툴팁 XML 인덱스는 표준 `xml.etree.ElementTree.XMLParser`의 custom target으로
전체 파일을 끝까지 파싱하며, 전체 트리 대신 필요한 `dic_data` 속성만 저장한다.
시작 태그의 문서 순서(preorder)로 같은 이름·숫자 인덱스의 뒤 항목을 우선하고,
이름의 삽입 순서와 숫자 인덱스순 텍스트 결합을 유지한다.
`ktos`·`ktest`는 `kr` 원문을 그대로 사용하고, `itos`·`jtos`·`twtos`는 기존 TSV 번역을
사용하되 번역이 없거나 비어 있으면 `kr`로 대체한다. 앞서 유효한 툴팁을 읽었더라도
파일 뒤쪽의 XML 파싱 오류는 `ET.ParseError`로 전파한다.

정적 장비 계산에는 실제 플레이어·착용자 상태가 없으며, `GetItemOwner`는 Lua의 `nil`을 반환한다.
소유자 상태에 의존하는 맵 효과는 계산에 포함하지 않는다.
명시한 장비 RefreshScp의 계산 실패는 공개 전 파서 실패로 전파한다.
등록된 class table의 없는 ID와 table 자체가 없는 경우의 `GetClassByType` 결과는 `nil`이다.
이는 조회 대상의 부재 표현이며 원본 Lua가 자체 수식 분기를 선택하게 한다. 계산 성공을 강제하지 않으며,
기존 ID의 `math.floor` 처리·잘못된 numeric ID 오류와 필수 의존성 누락·존재하는 IES 손상 예외는 유지한다.
드롭은 iTOS 데이터셋 디렉터리가 우선이고 개별 파일을 현재 지역에서 섞어 가져오지 않는다.
선택 사유는 현재 지역 데이터셋의 존재 여부를 구분하며 실제 데이터 출처와 revision을 기록한다.
이 검증은 합성 샘플의 경로 검사다. 전체 지역 게임 데이터·schema 차이·게임 계산식을 대신하지 않는다.
입력·기대값·검증 단계별 경계는 [regional fixture 안내](../harness/fixtures/regional/README.md)를 참고한다.

## GLM private latency boundary

[ADR0019](adr/0019-private-glm-call-telemetry.md)의 `agent_telemetry`는 게임 데이터 경로와
분리된 parent 소유의 임시 loopback OTLP collector다. zai CLI에만 적용하며 model API proxy나
compaction plugin이 아니다. 원문·ID·resource/session/content를 durable 기록으로 내보내지 않고
정제한 versioned numeric/boolean/fixed-enum만 기존 private research scan/state에 남긴다.
`agent_models`는 자식 환경·수명·CLI wall, `improvements`는 context 준비/검증과 실패 보존,
`improvement_loop`는 strict 재검사, 기존 `improvement_report`는 공개 allowlist projection을
각각 소유한다. web-v1·publisher/digest에는 계측이 없다. 기존 storage 선택·scope37파일·
fingerprint·quota/budget/approval·schedule·frozen morning report는 유지한다.
무수출은 unavailable, export 관측도 partial이며 request/tool work 합계를 wall과 혼동하지 않는다.
전체 필드와 향후 실제 기록 읽기는 [모델 연결](agent-models.md#glm-호출의-private-지연-관측)과
[개선 연구](improvements.md#private-glm-지연-기록-읽기)에 둔다. parent 검증·live·정상 hourly
관측은 대기 중이며 worker가 수행하거나 성공을 주장하지 않는다.

## 독립 PvP 확률 계산기

`/planner/pvp/` (`Planner:pvp`)는 기존 Planner 다음에 연결된 클라이언트 도구다.
Django는 지역별 문구와 입력 기본값을 렌더링하고, 제공된 독립 JavaScript의 순수 함수가
입력 스탯의 기본 확률을 계산한다. DOM 연결은 입력·오류·초기화와 결과 표시를 담당한다.
페이지는 DB에 쓰지 않으며 importer·게임 데이터 적재·PvE·대미지 계산과 독립이다.
기존 Planner와 전역 번역 동작, 하네스·배포·GitHub 게시 정책은 바꾸지 않는다.
제공된 개편 공식의 구현이며 실제 게임 패치 적용의 증거는 아니다.
공식·안전 범위·언어·검증 경로와 관측 한계는 [PvP 계산기](pvp-calculator.md)에 둔다.
