# 0015. 사람의 개별 승인을 기다리는 일일 개선 발견

- 상태: 제안(proposed), 기반 구현·전달은 사용자 승인됨; 최종 의미 검토·전체 검증·GitHub 전달 대기
- 기록일: 2026-10-15
- 기록 성격: 새 결정
- 대체 관계: 없음. 기존 직접 요청 workflow·공유 저장·GitHub journal/CI/cleanup 결정을 유지하며 자율 발견의 권한 경계를 추가한다.

## 문맥

사용자는 역할별 에이전트가 개선점을 찾고 서로 검토하여 쉬운 한국어 비유를 담은 한 장 보고서를
매일 제공하기를 요청했다. 보고함은 owner-private Sites이며 실제 변경·commit·PR·CI·merge·
cleanup은 사용자가 특정 제안을 승인한 뒤에만 수행한다. 직접 요청한 개발 작업의 기존 Git
허가를 자율 제안에 적용하면 발견이 곧 실행 권한이 되므로 두 경로를 구분해야 한다.
일반 `READ_ONLY=1` workflow는 필수 검사까지 실행하여 발견용 최소 권한 경로와 맞지 않는다.
기존 역할/provider/compaction·NFS 정책·명시 읽기 범위·검토/게시 안전 장치는 유지해야 한다.
명시적으로 승인된 기반 setup의 후속 검증 보정도 이 구현 범위에 속하며, 발견된 새 제안의
실행 권한을 부여하지 않는다.

## 결정

순수 Python 3.8 `improvement_report.py`를 schema·fingerprint·정제 JSON/HTML/Markdown 계약으로,
`improvements.py`를 host 발견·private 상태·신뢰한 승인/실행·HTTP 전달 경계로 둔다.
개별 승인 scope만 snapshot하여 owner별 specialist와 shared 문서에 배정하고 기존 runner의
격리된 `write=False, scoped=True`를 사용한다. 앞 역할의 정제 요약을 공유한 뒤 reviewer가 별도
context에서 승인 scope 전체와 모든 후보를 독립 검토한다. 소스 쓰기·checks·Git·workflow·
운영 파이프라인·cron은 discovery에서 호출하지 않는다.

현재 상한은 specialist당 후보 2개, 전체 8개, 보고 카드 3개, 실제 role 호출 5회,
호출당 600초, 자동 retry 0회다. 개별 128KiB(131072 bytes)·전체 source 1.5MiB(1572864 bytes)·
context 2MiB(2097152 bytes)·응답 64KiB와 scope/edit/evidence 한도도 둔다.
실제 참여·실패·시각/시간·응답 비용 추정만 private에 남긴다.
비용 미제공은 unknown이며 이 한도를 실청구액 상한이나 측정된 성능 개선으로 설명하지 않는다.
context는 UTF-8 source와 prompt의 bytes 합이며 snapshot·fingerprint 생성·저장된 fingerprint
재검증은 같은 source 상한을 사용한다. 기본 37개 scope와 8개 후보 reviewer context의 적합성은
전체 로컬 검증 사본의 독립 오프라인 회귀로 검사한다. 실제 모델 대신 순수 Python 대역과
임시 합성 storage를 사용하고 운영 저장소·키·네트워크·workflow·subprocess 호출을 차단한다.
합성 입력으로 source/context 상한의 정확한 경계 수용과 1 byte 초과 거부를 검사한다.

strict 후보 schema의 증거는 승인 파일의 실제 line range로 검증한다. 의미적 근거는 reviewer가
판단하고 모든 후보의 eligible/rejected/needs_evidence 및 필수 documentation 판단을 요구한다.
missing/malformed/failed review는 실행 적격을 만들지 않는다. 부족한 문서/테스트는 자동 읽지
않고 승인된 파일 finding으로 보고하여 메인이 새 scope/run을 준비한다.

proposal ID/digest는 후보와 **전체 읽기 의존성**의 bytes/hash·mode·존재에 묶는다.
human 결정·서명 승인·claim·delivery는 보고와 분리해 rediscovery가 덮어쓰지 않는다.
KST 날짜의 daily는 failed/partial도 재사용하고 새 모델 호출을 하지 않는다. 수동 discover만
명시 재시도한다. 자체 lock과 기존 고정 project lock으로 workflow/cleanup 중첩을 거부한다.
기존 storage readiness/private/no-fallback 정책을 그대로 사용한다.

메인/신뢰한 운영자만 특정 적격 ID와 실제 사용자의 private 0600 UTF-8 지시 파일로 승인한다.
모델 판정·보고서 문구·boolean은 승인 권한이 아니다. HMAC 승인은 원지시·proposal/review
digest·모든 source fingerprint·정확한 edit 목록·게시 범위·고유 authorization·기본 7일
만료를 고정한다. 기본 게시는 기존 commit/PR/CI 3개/squash merge/cleanup이며 local-only는
승인 시에만 선택한다. execute는 task/files override를 받지 않는다.

execute는 승인·만료·검토·원본/scope/config freshness·미소비를 검증한 뒤 lock 아래 일회성
claim을 남긴다. 기존 workflow가 project lock을 잡으면 `_improvement_guard(run_id)`가 쓰기
모델·사본·검사 전에 다시 확인한다. 이후 새 Claude 의미 검토·모든 필수 checks·범위 반영·
기존 Git 역할·awaiting_github journal·CI 3개·SHA 고정 squash merge·증거 기반 cleanup을 유지한다.
실패/중단 후 자동 replay하지 않는다. 메인은 기존 run/journal을 조정한 뒤 새 명시 승인으로만
갱신하며 이전 claim/approval을 archive한다. awaiting_github나 exit0를 전체 완료로 해석하지 않는다.

trusted parent는 지시 출처를 확인할 책임이 있다. CLI는 사람의 신원을 증명하지 못하며 HMAC도
동일 OS 계정 탈취를 막지 못한다. child/discovery session은 orchestration을, unattended는
승인/reject/execute·수동 재점검을 거부한다. scheduler는 marker를 가진 daily 보고만 실행한다.
직접 요청 workflow는 기존 권한으로 계속 실행하며 자율 제안의 우회 경로로 사용하지 않는다.

웹에는 버전 고정 `improvement-web-v1` projection만 전달한다. 최대 3카드·정제된 참여·counts·
자문 문서 판단과 digest를 포함하며 credential·승인 지시·절대 local 경로·소스/diff·로그·prompt·
raw response는 제외한다. HTML/Markdown escape와 길이 제한, A4 스타일을 적용한다.
private nonsymlink 0600 `{origin,token}`은 메인만 구성하고 모델에 주지 않는다.
host는 HTTPS POST `/api/reports`와 같은 service bearer의 GET `/api/reports/<date>`를 수행하며
redirect 금지·현재 요청별 20초·256KiB 상한·date/canonical SHA256 readback을 요구한다.
전달 실패는 보고를 보존하고 별도 delivery_failed로 남겨 모델 없이 재전송한다.

09:00 Asia/Seoul의 표식 있는 daily job 하나는 최종 검증 후 메인만 설치한다. host timezone,
실제 venv/working directory·명시 storage 선택/readiness를 확인하고 기존 jobs·게임 cron을 보존한다.
코드에서 scheduler·Site·Cloudflare 자원·provider·credential을 설치하지 않는다.

## 비교 대안

- 발견 직후 일반 workflow로 수정/게시: 호출 연결은 간단하지만 제안별 인간 승인 요구를 충족하지 못한다.
- 기존 READ_ONLY workflow로 매일 점검: 기존 검토를 재사용하지만 불필요한 전체 checks와 넓은 준비 단계를 수행한다.
- 모델의 approve boolean/웹 문구를 실행 권한으로 사용: 신뢰 경계가 모델 출력과 결합되고 replay·원본 변화를 통제하지 못한다.
- 별도 provider/전체 agent framework 추가: 새로운 비용·인증·운영 경계를 늘리므로 기존 역할의 제한된 직렬 호출을 선택한다.

## 선택 이유

읽기 전용 발견과 신뢰한 실행을 분리하면 일일 보고의 자동화와 변경 권한의 사람 소유를 함께
유지할 수 있다. content/dependency 결합과 atomic claim은 승인 이후 source drift·범위 변경·
중복 실행을 거부한다. 실제 구현은 기존 workflow에 연결하여 의미 검토·필수 검사·GitHub
전달/cleanup 정책을 별도로 재구현하거나 우회하지 않는다. 정제된 고정 schema는 private
보고함의 독립 reader와 digest readback을 가능하게 한다.

## 결과·비용·제약

최대 5회 실제 역할 호출과 private snapshot/report 보관 비용이 발생한다. 달러 실측·실제 발견
성공·완전한 semantic consensus는 호출 전 보장하지 않는다. 승인 후 모든 읽기 의존성 변화를
거부하므로 무관해 보이는 문서 편집에도 새 점검/승인이 필요할 수 있다. 실패한 claim 복구는
사람의 reconciliation을 요구한다. 잠금은 협력하는 host 경로를 직렬화하며 외부 편집까지 막지는 않는다.
문서 의미의 완전성과 인쇄 pagination은 독립 reviewer/메인의 확인이 필요하다.

2026-10-15 메인 제공 관찰로 owner-private Site는 배포되었고 익명 API 403,
service-auth page/upload/readback/index 200이었다. private inbox 설정과 별도 명시 daily local
storage 정책(ready, `/` mount·1GiB floor)을 메인이 준비했으며 persistent NFS는 유지했다.
host timezone Asia/Seoul·cron active·wrapper 준비도 제공된 관찰이다. 이 문서 worker는
private 설정/host/HTTP를 독립 검사하지 않았다. 이전 NFS hang에 따른 구현 run의 명시 local
override는 일회성 선택이며 코드의 fallback이 아니다.

최종 구현 의미 검토·full checks·구현 GitHub CI/merge/cleanup·첫 실제 discovery·일일 job 설치와
활성화는 대기다. proposed는 이번 기반 구현 승인이 없다는 뜻이 아니라 이 후속 검증이 아직
끝나지 않았다는 뜻이다. Site 배포 관찰을 host 기능 검증이나 예약 활성화의 증거로 사용하지 않는다.

## 관련 코드·검증·문서

- [improvements.py](../../harness/improvements.py), [순수 보고 계약](../../harness/improvement_report.py),
  [한도 설정](../../harness/improvement-config.json), [개별 scope](../../harness/improvement-scope.txt),
  [workflow guard](../../harness/workflow.py), [Makefile](../../Makefile).
- [오프라인 개선 회귀](../../harness/test_improvements.py), [workflow 회귀](../../harness/test_workflow.py)는
  fake 모델/HTTP 기반 명세다. worker는 실행하지 않았고 오케스트레이터가 전체 checks를 수행한다.
- 실제 변경 문서: [AGENTS](../../AGENTS.md), [architecture](../architecture.md),
  [harness-design](../harness-design.md), [harness](../harness.md), [workflow](../workflow.md),
  [improvements](../improvements.md), [ADR index](README.md)와 이 ADR.
  모델 설정 문서는 참조만 하며 기존 설정을 유지한다. 최종 reviewer가 `documentation.updated`와
  실제 변경 Markdown의 의미적 완전성을 판단한다. 파일 존재나 확장자만으로 완료를 주장하지 않는다.
