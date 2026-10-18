# 하네스 설계 결정 기록

전체 맥락은 [전체 하네스 설계](../harness-design.md), 실행 절차는 [workflow](../workflow.md),
환경·검증 범위는 [하네스 사용법](../harness.md)에 둔다. ADR는 주요 선택·비교·비용을 기록한다.

| 번호 | 결정 | 상태 | 기록일 |
| --- | --- | --- | --- |
| [0001](0001-isolated-offline-validation.md) | 오프라인 격리와 실제 검증 경로 | 승인(accepted), 현 구현 복원 | 2026-10-11 |
| [0002](0002-explicit-model-read-scope.md) | 명시적 모델 읽기 승인과 전체 로컬 검증 사본 분리 | 승인(accepted), 현 구현 복원 | 2026-10-11 |
| [0003](0003-role-routing-and-bounded-repair.md) | 경로/Jev/역할 모델 순차 배정과 제한된 실패 수정 | 승인(accepted), 현 구현 복원 | 2026-10-11 |
| [0004](0004-reviewed-and-validated-publication.md) | 새 검토·필수 검증 뒤 충돌 검사와 범위 반영 | 승인(accepted), 현 구현 복원 | 2026-10-11 |
| [0005](0005-github-connector-delivery.md) | 메인 GitHub 앱 journal·3개 CI·SHA 고정 merge | 승인(accepted), 현 구현 복원 | 2026-10-11 |
| [0006](0006-versioned-design-review.md) | Git 관리 설계·ADR와 매 검토의 문서 판단 | 승인(accepted), 이번 요청의 결정 | 2026-10-11 |
| [0007](0007-codex-warning-success-boundary.md) | Codex 성공 증거 우선과 안전한 경고 metadata | 승인(accepted), 새 결정 | 2026-10-12 |
| [0008](0008-json-validation-single-pass.md) | 모든 JSON 파일의 엄격한 검사 뒤 중복 finite_tree만 제거 | 승인(accepted), 새 결정 | 2026-10-12 |
| [0009](0009-post-merge-branch-cleanup.md) | master squash PR 유지와 메인의 증거 기반 머지 후 브랜치 정리 | 대체됨(superseded), 0010 | 2026-10-12 |
| [0010](0010-automatic-post-merge-cleanup.md) | 자동 parent Git cleanup·lease 비교 삭제·durable 복구·전체 완료 게이트 | 승인(accepted), 새 구현 결정 | 2026-10-12 |
| [0011](0011-configurable-harness-storage.md) | 설정 가능한 산출물·비인증 임시 저장, 고정 로컬 lock·인증 runtime, legacy 조회와 fallback 금지 | 제안(proposed), 구현안 검토·검증·전달 대기 | 2026-10-13 |
| [0012](0012-importer-single-run-snapshot.md) | 호출 소유 importer snapshot·consumed-only retention·복사 소비자·fresh direct/prev·SELECT 인덱스와 ORM 의미 보존 | 제안(proposed), 최종 새 실제 검토·전체 검증·전달 대기 | 2026-10-14 |
| [0013](0013-owned-validation-temporary-cleanup.md) | 고유 임시 tree의 진입/최종 readiness와 매 destructive 작업 attachment·ownership·kernel mount proof | 제안(proposed), 최종 새 실제 검토·전체 검증·전달 대기 | 2026-10-14 |
| [0014](0014-streaming-pak-extraction.md) | PAK의 bounded read/inflate와 파일별 원자 공개·부분 실패·재시도 경계 | 제안(proposed), 새 검토·전체 검증·전달 대기 | 2026-10-14 |
| [0015](0015-approval-gated-improvement-discovery.md) | 사람의 개별 서명 승인·일회성 기존 workflow 실행; daily-only/5회/one-pass 정책은 0017로 대체 | 권한 결정 유지, 스케줄·호출 부분 대체됨 | 2026-10-15 |
| [0016](0016-bounded-private-improvement-text.md) | 표시 상한 4배의 무축약 private 후보·review(1440/360)와 web-v1 projection 분리, 모델 전용 bounded strict JSON envelope | 제안(proposed), 명시 요청 수리·새 Claude 검토/전체 검증/local 전달 대기·공개 승인 차단 유지 | 2026-10-15 |
| [0017](0017-budgeted-continuous-improvement.md) | bounded hourly 9단계·불변09:00 보고·동일 digest 복구, mlx-vlm 네이티브 JSON Schema·v2 config와 기존 후보/승인 경계 | 제안(proposed), 승인 방향 기록; 최종 adapter 새 review/full check/apply·실추론/운영 검증 대기 | 2026-10-16 |
| [0018](0018-storage-check-probe-deduplication.md) | 한 읽기 경계의 mount별 공간 조회 공유·양쪽 floor와 fresh 쓰기 gate 유지·실제 목적지/새 root probe | 제안(proposed), 새 의미 검토·전체 offline 검증·전달 대기 | 2026-10-16 |
| [0019](0019-private-glm-call-telemetry.md) | parent loopback OTLP collector·bounded numeric private GLM latency contract·public web-v1 제외 | 제안(proposed), 새 의미 검토·전체 검사·parent 합성/정상 hourly 관측 대기 | 2026-10-18 |

## 상태와 근거의 의미

0018은 0011의 공간 측정과 일상 준비 probe 선택을 정밀화한다. shared mount는 한 읽기 경계에서
한 번 측정하되 각 spec의 floor를 검사한다. 일상 출력/임시 할당은 새 root와 실제 자식·override를
독립 probe하고, 명시적 prepare와 probe 진단은 양쪽 application을 모두 검사한다. 호출·mutation·
cleanup 경계 간 cache/lease는 없으며 0013의 두 readiness와 per-entry proof는 유지한다.
기존 NFS/private 설정·인증/lock·게시 정책은 바꾸지 않는다. proposed는 최종 새 Claude 검토·full
offline check와 전달이 대기라는 뜻이며 operation-count 회귀가 실제 NFS 속도나 게이트 통과를
입증하지 않는다. 기존 ADR 상태와 아래 역사적 기록은 유지한다.

0017은 사용자의 최신 직접 선택에 따라 0015의 자동 탐색 스케줄·하루 호출 정책만 대체한다.
37개 승인 scope와 기존 역할/auth/storage·개별 승인/claim·GitHub 게이트, 0016의 서술 계약은
유지한다. hourly tick은 모델 최대1회/하루24회, Claude 추정 US$1·reviewer cap US$0.20,
GLM model quota>=80% admission 보류, 자정 guard·legacy carry-in·durable slot/reservation을
사용한다. 이전09:00~현재09:00의 현재 fingerprint 일치 완료 review로 한 번 보고하며
publication journal의 unknown 전송은 자동 재시도하지 않는다. 상세 계약·대안·한계는 ADR0017에 둔다.
잔액 검사는 reviewer admission에 적용하며 그 차례 전 역할은 다른 gate 내 진행할 수 있다.
reviewer 예산 대기는 stage_index를 유지하므로 새 slot도 reviewer를 재판단하고 이후 local/구독
역할도 대기가 풀릴 때까지 호출하지 않는다. 보고 확정은 독립적이다. TOKENS_LIMIT/CREDIT_LIMIT
모두 인식된5h의 정확한 finite numeric0%(bool 제외)에만 absent/null reset을 idle로 허용하며
private null(미상·미활성)을 유지한다. weekly에는 이 예외가 없고 잘못된 reset·실패 envelope·
model limit 부재를0%로 해석하지 않는다. tick의 설정/Store/readiness 준비 실패는 bounded 정제
paused로 반환하며 모델·키 조회·보고 확정·publisher·fallback을 하지 않는다. child/discovery 거부는 유지한다.

2026-10-16 프로토콜 정정은 승인된 기존0017에 기록하며 신규 ADR을 만들지 않는다.
로컬 초안은 mlx-vlm 0.7.8의 llguidance 네이티브 JSON Schema constrained generation을 쓴다.
`response_format.json_schema`의 strict canonical schema와 top-level `enable_thinking=false`를
요청하고 전송 전 window/owner 승인 목록에서 schema를 재구성해 변조·누락을 거절한다.
schema overhead를 포함한 전체 요청24576bytes 안에서 whole-line window를 선택한다.
후보와 benefit 양쪽 evidence는 그 단일 window의 canonical 경로·원문 줄 번호를 유지한다.
중복·줄 순서·문자 총량·의미와 실제 읽은 줄 검증은 기존 클라이언트가 최종 권위다.
schema 무시·위반도 거절하며 경로/줄 보정·근거 합성·재시도·fallback은 없다.
`local-model-config-v2`/`provider=mlx-vlm`으로 명시 이행하고 `api_model==model`인 상대
repository ID만 요청한다. `default_model`이나 절대 호스트 경로를 사용하지 않는다.
v1 mlx-lm 설정은 자동 변환하지 않고 `config_invalid`로 보류하며 config digest 전환으로
기존 loop fingerprint·승인 재사용을 막는다. Linux에는 서버 패키지를 추가하지 않는다.
uniqueItems는 llguidance1.9.1 미지원이므로 client 중복 검증을 유지한다. 정상 assistant의
정확한 tool_calls:null/tool_call_id:null만 무동작 metadata로 받고 non-null·다른 도구 필드는 거절한다.

최초 자동 초안은 JSON 파싱 후 `candidate_invalid`로 검증 거절됐다. 형식 검증 제외가 아니며
원문 미보존으로 당시 정확한 실패 필드·값은 알 수 없다. 별도 재현의 edit_files 거절과 evidence
window 위반을 최초 응답의 확정 원인으로 기술하지 않는다. 편집 목록의 bounded
`candidate_edit_files_invalid`, `candidate_edit_files_duplicate`, `candidate_edit_files_outside_scope`와
사용자 노출 코드 allowlist를 유지한다. 원문·프롬프트·소스·절대 호스트 경로를 로그·보고서·public
web-v1에 넣지 않는다. 숫자 파일 ID/window evidence 합성 실험은 실패했고 구현하지 않는다.

과거 약19.54초 합성 추론 성공과 별도 mlx-vlm 네이티브 schema 프로토타입의 메인 관측은
최종 어댑터 성공과 구분한다. prompt/order 수리 두 실행은 Claude 검토 뒤 실제 추론에서 다시
승인 밖 edit_files를 만들었고 full check 중 중단되어 모두 `applied=[]`다. 복원한 마지막 승인
범위 초안은 참고용이며 새 검토·전체 검증이 필수다. 기존 NFS timeout/일부 검사 성공도 전체
성공이 아니다. 최종 adapter 새 Claude 의미검토·전체 make check·두 umask077/022 권한
fixture 검증·scoped apply는 실행기, 서버 설치/SSH/서비스·private config 전환·실제 추론·
실제 repository 첫9단계·신규 서비스 전환·다음 아침 게시·GitHub 전달/CI/머지/정리는 메인 책임이다.
특정 미검토 초안의 사전 추론 관측도 최종 bytes의 성공이 아니며 근거는 local-models에 둔다.
검증 사본 이동·재사용은 parent가 NFS 원본 baseline과 같음을 확인한 준비로 성공이나 fallback이 아니다.
메인 제공 기존 hourly wrapper 활성·2026-10-16 09:00 partial/제안0개 보고1회 전달은 새 프로토콜의
운영 성공과 구분한다. NFS 기본·명시 daily local storage·37개 scope·예산·승인 게이트를 보존하고
이 leaf는 스케줄·ledger·확정 보고서·
게임 cron을 편집하지 않는다. 작업자·검토자는 검사·네트워크·Git·SSH·서비스·재위임·workflow를
실행하지 않는다. 구현 workflow 비용은 자동 탐색 ledger와 별도다.

이번 coordinator 단일 작업은 승인21개 안에서 AGENTS·이 index·0017·모델/운영·설계/경계
문서를 갱신한다. [파일별 판단](../improvements.md#이번-프로토콜-수리의-문서-영향)은 시작 시의
영향과 최종 자체 검토 이유를 기록하며 독립 검토의 승인이 아니다. 매 후속 검토는 실제 경로를
files에 열거하고 `documentation={status,files,reason}`으로 최종 코드와 문서의 의미적 완전성을
새로 판단한다. 이전 updated나 확장자 검사는 그 증거가 아니다.
아래0015/0016 기록은 이전 수리 당시의 이력이며 현재 전달 상태와 구분한다. 특히 과거 GitHub
자동승인 거부는 보존하며 이번 직접 요청의 검증된 인계와 구분한다.

0016은 메인이 보고한 419자 issue의 표시 한도 거부를 수리하는 데이터 계약 결정이다.
원본 private 서술은 적당한 hard ceiling 안에서 reviewer·identity·persistence·승인/실행에 유지하고
web-v1은 기존 상한을 유지한다. 0015의 권한·일회성 claim·모델 호출/재시도·storage·스케줄 정책을
대체하지 않는다. 같은 요청의 후속 transport 수리는 `_call_role`에서만 전체 단일 소문자 json
fence를 허용한다(LF/CRLF, 바깥 JSON 공백). 원래 UTF-8 byte ceiling 검사 후 기존 strict
parser에 내부를 전달하며 config/storage/public 입력은 fence를 거부한다. 후보/검토 내용·
ID/digest와 private 원래 redacted runner result를 보존한다. 설명문/다중 block/invalid JSON의
추출·복구·retry는 없다. 별도 ADR를 만들거나 0015 권한 결정을 대체하지 않는다.
같은 수용/표시 결합의 reviewer 수리도 0016을 확장한다. `review.reason`과 후보별·전체
`documentation.reason`의 private hard 1440 / public 360 계약을 적용하며 private 원문을
보존한다. 후보별 review 전체는 기존 approval review_digest·재검증·승인 후 task에 결합하고
전체 문서 판단도 scan에 보존·재검증한다. 짧은 review 표현/digest는 불변이다. public
validator와 render는 세 위치 모두 재계산 digest가 있는 361자를 거부한다. schema·문서
최소 길이/상태/Markdown/scope·coverage/verdict·eligible 필수 문서 범위는 엄격히 유지한다.
합성 명세는 416자 review의 정확히 5회 fixture 호출·전체 private 저장·발견 시 무승인/무실행,
명시 승인 뒤 mocked handoff·표시 밖 suffix 승인 무효화·private 1440/1441과 public 360/361을
다룬다. 최신 scan `1792065346555306548-d8a875`의 네 specialist(GLM 포함)/Claude runner
성공과 416자 reason 검증 실패는 메인 제공 관찰이다. raw 원문은 fixture로 복사하지 않는다.
이전 3215 passed는 새 수리 검증이 아니며 worker는 새 검사를 실행하지 않았다.
proposed는 이번 수리 승인과 별개로 새 Claude 검토·필수 전체 check·local apply/전달이 대기라는
뜻이다. 이번 `GIT=0`은 GitHub create_tree의 automatic approval review 거부(명시적 공개
동의 부족)를 유지하며 Git 쓰기·journal 변경·재요청을 하지 않는다. 메인은 local 수리/보고
전달 후 별도 공개 승인을 요청한다. 새 실제 재점검 성공이나 private 보고함 전달 완료를 주장하지 않는다.
이번 문서 변경 판단은 `documentation.updated`로 improvements·architecture·harness-design·
0016·이 index를 포함한다. harness 사용법은 명령/검증 실행 설명 불변, AGENTS/0015는 권한 정책
불변이라 수정하지 않는다. 기존 역사적 상태와 인계 기록은 아래에 보존한다.

0015는 기존 직접 개발 요청의 GitHub 허가를 자율 발견 제안에 적용하지 않는 새 권한 결정이다.
이번 기반 기능 구현·전달은 명시 승인되었지만 후속 제안은 specific ID별 인간 지시가 필요하다.
소스/전체 읽기 의존성 digest·mode·존재와 7일 이내 승인·atomic claim을 기존 workflow에 연결하며
새 의미 검토·필수 검사·journal·CI 3개·squash merge·cleanup 경계는 유지한다.
메인이 제공한 owner-private Site 배포/익명 403·service-auth 200과 별도 daily local storage ready,
Asia/Seoul·cron active는 준비 관찰이다. worker가 독립 검증한 결과가 아니며 persistent NFS는 유지한다.
최종 구현 review/full checks·구현 GitHub 전달/CI/merge/cleanup·첫 scan·job 설치/활성화는 대기다.
proposed는 기반 구현 승인을 부정하거나 기존 ADR 상태를 바꾸지 않는다. 상세 계약·운영·
문서 영향은 [일일 개선 점검](../improvements.md)에 둔다. 기존 역사적 실행의 저장 선택은 아래에 보존한다.

0001~0005는 현 소스에서 복원한 기록이다. 승인(accepted)은 **관측된 구현 결정으로 기록한다**는
뜻이며 과거 도입 당시 승인을 증명하지 않는다. 기록일은 이번 문서 작성일이고 실제 도입일·당시 의도·
검토 과정·실행 성공 날짜를 추정하지 않는다. 대안 비교와 선택 이유는 이번 문서화 시점의 평가다.
0006은 이번 요청에 따른 문서 유지·검토 게이트 결정이며 승인 상태가 검사 통과를 뜻하지 않는다.
0007은 Codex warning과 성공/실패 판정을 분리하는 새 결정이다. 0002의 격리 결정을 바꾸거나
대체하지 않으며, 승인 상태는 수리 worker의 검사 실행·일반 workflow 성공·게시 완료를 뜻하지 않는다.
0008은 공개 메모리 검사와 파일별 엄격한 검사를 유지하면서 내부 중복 순회만 제거하는 결정이다.
승인 상태나 제공된 prototype/local diagnostic 수치는 최종 회귀·전체 파서·CI 성공·누적 개선율을 증명하지 않는다.
0009는 당시 별도 메인 정리 정책의 역사적 기록이며 본문을 보존한다. 0010이 자동 정리와 전체 완료
게이트로 대체한다. merge 성공/SHA를 보존하고 fresh proof·exact ref 삭제·prune·clean ff-only까지
complete여야 passed다. 새 repository/default_branch proof로 현재 기본 브랜치를 보존한다.
기존 github-v1/merged run은 명시적 request/resume/cleanup에서 재검증한다.
0010의 승인 상태는 worker의 검사 실행, 실제 PR/CI/merge 또는 이번 run의 cleanup 성공을 증명하지 않는다.
0011은 외부 artifacts/temp와 고정 로컬 project lock·credential runtime을 분리하는 저장 결정이다.
0010을 대체하지 않으며 기존 approved hash·expected SHA·durable snapshot·정확한 cleanup·전체 완료
게이트는 유지한다. legacy absolute 경로는 재작성하지 않고 status/latest·Git 재개에서 함께 조회한다.
proposed는 구현안의 독립 의미 검토·full checks·GitHub 전달이 대기 중임을 나타낸다.
2026-10-14 최신 선택은 기존 configured NFS 설정·mount·floor 유지다. 종전의 향후 local temp
override/activation 계획은 이번 실행에 적용하지 않는다. ADR 존재·회귀 정의·draft 복구는
검증이나 activation 증거가 아니다.
0012는 0008의 strict diagnostics/order를 보존하고 한 호출의 private staging 소비만 재사용한다.
0013은 0011의 prerequisites를 한 tree 제거의 고수준 작업 경계로 구체화하며 per-entry
attachment/ownership/no-follow/device/kernel mount 증명을 유지한다. 0010의 Git cleanup은 별개다.
두 신규 ADR의 proposed는 작업 승인이나 기존 real-model/Claude 후보 검토를 부정하는 상태가
아니며 최종 소스의 새 검토·full validation·실제 게시 완료가 아직 없다는 뜻이다.
2691 selected zero-skip과 제공된 importer 성능/지역 JSON bytes는 후보 근거다.
이전 NFS RPC timeout/readonly cleanup 실패를 포함한 최종 인계는 [harness](../harness.md)와
[workflow](../workflow.md)에 둔다. 장비 Lua batching은 4.8% 느려 제외되었으며
그 결정을 위한 문서나 ADR 항목은 생성하지 않는다.
이번 repair 입력의 unavailable/unattributed `check` diagnostic은 알려진 실패 원인을
추가하지 않는다. 원인 추정이나 통과 주장을 하지 않고 [workflow 인계](../workflow.md#이번-31파일-수리의-검토검증게시-인계)에
한계를 기록한다. 최종 새 실제 검토 후 원래 필수 checks 전체를 오케스트레이터가 실행한다.

### PAK 재시도의 문서 finding

2026-10-14 정정: 이전 문서 finding은 승인 사본에
`docs/adr/0014-streaming-pak-extraction.md`가 없어 `changes_requested`로 보고했다.
이전 문서 수리는 승인 목록 안의 해당 ADR 작성을 명시하여 파일을 작성하고 예약 항목을
실제 링크로 바꿨다. 이번에는 해당 기록을 유지한다. 파일 존재는 문서 검토 통과나
validation success의 증거가 아니다.
승인 밖 문서를 자동 열람·복사·생성하지 않으며 repair round는 승인 범위를 확대하지 않는다.
필요한 승인 밖 경로가 발견되면 기존 승인 파일 finding에 정확히 기록하고
changes_requested로 보고한다. scope 확인과 새 run 준비는 메인 coordinator 책임이다.
이 작업에서 추가로 필요한 승인 밖 문서는 확인되지 않았으며 기존 설계·workflow 링크는
그 문서들을 열람했다는 뜻이 아니다.

[0014](0014-streaming-pak-extraction.md)에 기록한 주요 결정은 다음과 같다. 기존 importer 0012와 owned-temp 0013을
대체하지 않으며 두 항목과 기존 기록을 보존한다.

- 문맥: 전체 PAK/member buffering에 따른 Python peak를 archive/member 크기에
  비례하지 않는 버퍼로 줄인다. 기존 형식·checksum·경로 정책은 유지한다.
- 결정: compressed member read 64KiB와 양수 inflate `max_length` 1MiB,
  작은 header/name exact-read와 eof/실제 출력 크기 확인을 사용한다.
  파일별 `.part` flush/fsync/close/replace와 실패 정리, 전체 성공·archive close 후
  archive 삭제를 유지한다. blacklist-before-UTF8와 trailing compressed bytes 무시도 유지한다.
- 비교·이유: 전체 buffering은 단순하지만 입력·decoded member 크기에 따라 메모리가 늘어난다.
  read만 잘라도 inflate 출력이 무제한이면 목적을 달성하지 못한다. 양쪽 상한과 tail 처리는
  반복 제어·byte count 검사를 요구하지만 기존 파일별 공개 의미를 유지한다.
  전체 archive rollback은 별도 staging/복구 정책을 요구하여 이번 결정에 포함하지 않는다.
- 비용·복구: 추가 read/inflate/write 반복의 성능 효과는 아직 측정 근거가 없다.
  여러 조각·zlib/Python/file 상태가 함께 존재하여 두 chunk 상한의 합은 RSS 상한이 아니다.
  앞 파일은 뒤 레코드 실패 때도 완료 상태로 남고 기존 뒤 destination/archive는 보존한다.
  직접 unpack의 같은 경로 정상 bytes 재시도와 상위 다운로더의 손상 PAK 재다운로드는 구분한다.
  디스크 사용량·전체 archive 원자성·directory fsync·정전 복구는 보장 범위를 확대하지 않는다.
- 근거·상태: 제공된 소스 SHA256
  `ace103822ecb0496602066e25ff5d5172cff44fd471ede65e9226c002568108e`의
  격리 64MiB 합성 입력 3회와 별도 tracemalloc에서 output bytes/SHA256은 baseline과 같았고
  Python traced peak는 134851344 → 2337899 bytes였다. 이는 이전 승인 후보의 제공된 측정이며
  validation success가 아니다. 원본 Root/baseline은 전체 검토·검증 후에만 반영한다.

실제 구현 계약은 [아키텍처](../architecture.md#pak-스트리밍-추출의-메모리공개복구-경계),
여섯 작은 테스트의 현재 범위·RNG/경계 finding 정정·근거 한계·후속 책임은
[하네스 인계](../harness.md#이번-pak-스트리밍-재시도의-근거와-인계)에 기록한다.
2026-10-14 최신 인계 정정: 마지막 실제 GLM 소스·fixture·테스트와 Codex 문서는
Claude 승인을 받았지만 Python3.8 `raw_deflate`의 3인자 `zlib.compress`가
downloader 수집을 실패시켜 run은 failed였고 Root 반영은 없었다.
기존 downloader 81개는 passed/skip 0, 새 18개 회귀는 미실행이다. 승인된 7개 파일을
새 격리 사본에 재사용하고 두 순차 task로 helper 수리와 문서 확인을 수행한다.
Python3.8 raw `compressobj`의 compress+compressor flush는 작은 fixture 완성을 위한
국소 호환성 수리이며 production decompressor flush 금지·설계 결정을 바꾸지 않는다.
새 ADR은 필요하지 않으며 기존 0014와 0012·0013을 보존한다. 모두 새 review/check를 받는다.
기존 GLM `glm-5.3-flash`·모든 역할·NFS 설정·mount·floor를 유지한다.
실행기가 필수 전체 offline gate 하나를 수행하며 selected skip/xfail은 성공이 아니다.
메인은 최종 hash/측정 일치를 확인한 뒤 기존 GitHub request/accept로 원격 commit·PR,
실제 CI success 3개·squash merge·해당 run branch cleanup을 담당한다. 모두 후속 대기다.
매 review는 `documentation={status,files,reason}`으로 실제 changed docs의 의미적
완전성을 판단한다. 이번 문서 수리의 인계 상태는 `updated`이며 새 reviewer 판단과
필수 전체 검증은 대기다. ADR0014의 proposed는 작업 승인을 부정하는 상태가 아니라
최종 소스의 새 검토·전체 offline gate·실제 게시가 아직 완료되지 않았다는 뜻이다.

상태는 제안(proposed), 승인(accepted), 대체됨(superseded)을 사용한다. 이후 결정 변경은
기존 ADR를 삭제하거나 새 결론으로 재작성하지 않는다. 기존 상태를 superseded로 바꾸고
대체 ADR 링크를 추가하며, 새 번호의 ADR에서 이전 결정을 링크하고 변경 이유를 기록한다.
사실 오류 정정은 근거와 정정일을 덧붙여 이전 판단을 알아볼 수 있게 보존한다.

## 작성·검토 규칙

업무 시작 시 구조·책임·계약·격리·검증·실패 복구·GitHub 게시 정책의 문서 영향을 판단한다.
관련 설계·경계 문서를 갱신하고 주요 결정에 새 ADR를 작성한다. 단순 오타·동작 불변 국소 수정은
문서 생략 이유를 reviewer의 documentation.not_required에 구체적으로 기록할 수 있다.
필요 문서가 승인 읽기 scope 밖이면 자동 열람·복사·생성하지 않는다. 누락 경로를 보고하고
기존 승인 파일 finding과 documentation.missing으로 승인을 거부한다. 메인이 범위 확인 후 새 실행을 준비한다.
이번 importer/cleanup 변경의 매 orchestrator review는 `documentation={status,files,reason}`을 반환하고
`status=updated`를 실제 변경된 승인 Markdown 목록과 구조·격리·실패 복구·운영 명령의 의미적
완전성 판단으로 뒷받침한다. 0011/0012/0013·architecture·data-contracts·harness·workflow의
의미를 함께 판단한다. Markdown 확장자 확인은 완전성 증거가 아니다. 새 실제 review·전체
`make check`·31파일 scoped apply와 기본 Git 역할은 orchestrator, 정확한 GitHub 앱 journal·
실제 CI 3개 success·merge·정확한 cleanup은 main의 책임이다. leaf worker는 실행하지 않는다.

번호는 목록의 다음 번호를 사용하고 한 ADR에는 한 주요 결정을 둔다. 문맥·결정·비교 대안·선택 이유·
결과/비용/제약을 구분한다. 소스·설정·검증 경로·문서의 실제 링크를 포함하되 검증 경로가 있다는 것과
실행 성공을 구분한다. 키·운영 데이터·private 계획/응답/로그 원문은 ADR에 복사하지 않는다.
결정의 근거가 부족하면 부족한 파일/정보를 명시하고 검증·승인·날짜를 꾸미지 않는다.

## 템플릿

```markdown
# NNNN. 결정 제목

- 상태: 제안(proposed) / 승인(accepted) / 대체됨(superseded)
- 기록일: YYYY-MM-DD
- 기록 성격: 새 결정 / 현 구현 복원 (기록일과 도입일을 구분)
- 대체 관계: 없음 / 이전 ADR 링크 / 대체 ADR 링크

## 문맥
문제·요구·실제 근거와 불확실한 부분.

## 결정
선택한 정책·책임·경계.

## 비교 대안
고려 가능한 선택과 비용. 복원 기록이면 이번 문서화 시점의 평가임을 명시.

## 선택 이유
결정과 근거의 연결. 과거 도입 의도·승인 과정을 추정하지 않음.

## 결과·비용·제약
얻는 효과·추가 작업·남은 한계·실패와 복구 경계.

## 관련 코드·검증·문서
실제 경로 링크. 검사 명세·미실행·실제 결과를 구분.
```
