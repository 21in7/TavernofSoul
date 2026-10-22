# 0025. 진행을 보존하는 고정 소스 검토와 실제 참여 보고

2026-10-22 대체 범위: [ADR0026](0026-source-verified-retained-improvement-reports.md)은 source 확인을
parent의 실제 성공 Read 증거로 검증하고, 최신 단일 완료 회차 선택/최신 reviewer 실패의 일괄
eligible 강등을 ID별 최신 명시 verdict 보존과 원본 provenance 재검증으로 대체한다. 아래의
해당 규칙과 당시 관측은 역사적 기록이다. sealed snapshot/참여 history·개별 승인/claim·예산은 유지한다.

- 상태: 사용자 직접 요청에 따른 구현안, 새 Claude 의미 검토·full make check·Git/CI 전달 대기
- 기록일: 2026-10-21
- 대체 범위: ADR0017의 local 실패 specialist/reviewer gating, source-only round reset,
  선택 회차에 종속된 오전 참여 집계. ADR0015의 승인 경계와 기존 예산·격리·게시 정책은 유지한다.

## 문제와 근거 수준

메인이 private 기록에서 확인해 전달한 관측은 다음과 같다. 작업자는 원문·credential·private
파일을 받거나 읽지 않았다. 2026-10-21 local은 00/04/06시 성공, 02시 duplicate 실패였다.
01/05/07시 coordinator/parser/django는 성공했으나 정식 후보가 없었다. 03시는 초안 부재로
downloader가, 08시는 빈 specialist pool로 reviewer가 생략됐다. 09시 새 round를 먼저 만든 뒤
freeze하여 실제 참여가 모두 not_called인 failed/0카드 보고가 전달됐다. 10시에는
harness/test_workflow.py 변경으로 새 round도 초기화됐다. 전날 실제 downloader 후보 2개도
docs/improvements.md 변경으로 회차 전체가 무효화됐다. 기존 frozen 2026-10-21 보고는 수정하거나
재생성하지 않는다. 아래 합성 회귀는 이 전달 관측이나 실제 hourly 성공을 대체하지 않는다.

## 책임과 데이터 계약

`improvement_loop.py`는 slot·예약·정산과 함께 compact private participation history를 같은
atomic state write에 결합한다. 최근 192개 cloud 시도를 유지하며 최대24회/일인 현재 정책에서
최근 보고 window를 충분히 포함한다. 전체 후보·정제 실패·local 참여·telemetry·cost는 기존 private
scan/ledger에 남고, history는 역할/provider/model/status/시각과 실행 identity만 가진다.
완료 review index(최대 설정32개, 기본16개)는 후보 선택에만 사용한다. source/control 무효화로
두 index를 지우지 않는다. 새 round·실패·process restart는 실제 시도를 삭제하지 않는다.

실행 identity는 `(scan_id, KST slot, stage_index)`다. 예약 직전 admission 시각을 참여 window의
기준으로 삼고, legacy는 recorded started_at, 그것이 없으면 recorded finished_at만 사용한다.
둘 다 없거나 model identity가 없는 과거 참여를 추정하지 않는다. 중단 복구 시각으로 과거 시도를
오늘로 옮기지 않는다. 예약 상태는 성공이 아니며 보고 시 실패/불명 시도로 취급한다. 역할별
`(started_at, slot, stage_index, scan_id)` 최댓값을 표시하므로 최신 실패가 이전 성공에 가려지지
않는다. 같은 scan/day 재투영·복구는 중복 실행으로 합산하지 않는다. not_called는 실제 시도 없는
역할에만 쓴다. readiness/quota/budget 보류는 모델 참여로 만들지 않는다.

오전 window는 KST `[전날09:00, 당일09:00)`다. 실제 참여를 먼저 history에서 집계하고,
현재 전체 dependencies와 일치하며 window 안에 완료된 최신 independent review 하나의 후보만
선택한다. review 완료시각·동률 scan_id 내림차순이며 후보 pool을 합치지 않는다. 선택 review의
원본 참여는 private reviewed_agents/reviewed_local_participation, 보고 참여는 agents다.
summary는 마지막 실제 시도의 성공/실패/미호출, 검토 미완료, snapshot 완료지만 현재 유효한
제안 부재를 구분한다. 선택한 검토가 있어도 최신 역할 실패가 있으면 전체 scanned가 아니다.
선택 review 완료 뒤의 별도 회차 cloud 시도도 partial과 summary로 구분한다. 그 시도가 모두
성공이어도 이전 제안의 검토에 포함됐다고 표시하지 않는다. current 제안 provenance는 유지한다.
web-v1은 여전히5역할/4status이며 최신 reviewer가 실패하면 기존 보수적 eligible gate에 따라
카드는 needs_evidence로 투영한다. 선택된 private review와 proposal identity는 재작성하지 않는다.

## 선택적 local과 고정 snapshot

local은 보조 초안이다. duplicate/invalid/empty/exception/긴 줄/준비 실패는 local stage만
소비하며 paired specialist는 다음 정규 slot에서 자기 승인 소스를 독립 분석한다. 빈 pool이나
local 실패에도 reviewer는 최종 정규 slot에서 전달된 실제 coverage와 전체 승인 snapshot을
독립 평가한다. 후보가 없어도 strict reviews=[]와 documentation 판단은 실제 검토 출력이어야 한다.
cloud 실패·부분 coverage를 전원 정상 점검으로 표시하지 않는다. local의 실패·strict validator·
canonical path·원문 line/window·고정 진단은 그대로다. 보정·재시도·추가 call·새 provider/fallback은 없다.
초안 없는 specialist의 빈 결과·실패·중단은 이전 local 진단을 지우지 않는다. 이전 요약 최대2개와
별도 specialist 결과를 기존 feedback 상한 안에서 다음 window에 전달한다. local만 실행되고
cloud가 모두 미호출이면 오전 상태는 failed이며 local 참여를 public partial 근거로 삼지 않는다.

`improvement_snapshot.py`는 기존 runtime 승인37개만 private Store의 두 고정 bank a/b에
저장한다. 각 source는 별도 bounded JSON record(base64 bytes, 원래 POSIX mode, 명시적 존재),
manifest는 scan_id·정확한 승인 경로 순서·전체 source fingerprints를 가진다. 기존128KiB/file,
1.5MiB/전체 source 한도를 검사하며 JSON record 하나는 Store1MiB 이하다. UTF-8도 검증한다.
모델 context·credential·scope 밖 소스·전체 repository를 지속 복사하지 않는다. snapshot payload는
archive/public/진단으로 전달하지 않는다. 이 모듈은 archive 경로를 만들거나 검색하지 않는다.

inactive bank의 파일들을 fsync/atomic replace한 뒤 manifest를 atomic publication하고, 그것의
digest·bank·scan_id를 state에 결합한다. 호출 전마다 동일 manifest와 모든 파일 fingerprints를
재검증한다. 모든 조상은 no-follow로 열고 Store root 이하의 private 디렉터리는 owned0700,
record는 owned0600/nonlinked regular file,
개별/총 크기·경로·manifest 일치를 요구한다. 누락·변조·권한/owner/링크·불완전 state는 no-call이다.
실패한 bank를 신뢰하거나 live 파일로 자동 fallback하지 않는다. crash 전 inactive 파일은 다음
publication 때 정해진 최대37개 이름만 대체/정리한다. active bank는 덮어쓰지 않는다. 두 bank만
유지하므로 완료 회차의 payload가 계속 증가하지 않는다. 과거 scan에는 fingerprints만 남는다.
snapshot Store 쓰기는 record별 고정 `.pending` 이름을 사용하여 강제 종료마다 임의 임시 source가
증가하지 않는다. bank당 최대38개 staging 이름이며 유효한 owned0600/nonlinked bounded partial만
다음 쓰기에서 회수한다. unsafe staging은 보존하고 no-call로 중단하며 디렉터리를 무제한 탐색하지 않는다.
같은 OS 계정의 공격자가 state와 payload를 모두 다시 쓰는 공격은 기존 Store의 신뢰 경계 밖이다.

각 역할은 같은 pinned bytes/존재와 원래 mode metadata를 사용한다. 임시 cloud context는 기존
읽기 전용0400 projection이고 원래 mode는 prompt에 명시한다. local은 그 snapshot의 단일
연속 whole-line window만 받는다. 정식 후보·evidence validator·ID/digest는 전체 pinned 읽기
의존성에 묶는다. source-only 변화는 stage/pool/feedback/cursor를 reset하지 않는다.
review_complete는 고정 snapshot의 독립 검토 완료이며 current freshness나 사용자 승인이 아니다.
완료 후 다음 round는 현재 소스 snapshot으로 갱신한다. cursor는 회차 간 유지하며 짧아진 파일의
초과 cursor는 cursor_exhausted로 다음 파일에 한 번 진행한다. 삭제/빈 파일도 기존 bounded skip이다.

탐색 순서는 승인 membership을 바꾸지 않고 non-shared owner 파일, shared 파일 순서다.
각 그룹 안은 기존 scope 순서를 유지한다. legacy cursor_order=0의 index를 정확한 path로 찾아
새 순서의 index로 한 번 이행한다. 이후 order version1을 유지한다. mode·bytes·존재는 이 identity를
바꾸지 않는다. scope/ownership/config/provider/model/protocol 변경은 엄격한 진행 무효화 경계다.
dependencies에는 실제 ownership 배정 fingerprint와 명시적 review_protocol도 결합한다.

## freshness와 안전한 이행

현재 source/scope/config/loop/local/agent/workflow/provider/model/protocol과 불일치한 snapshot
후보는 public eligible 선택·approve·execute에서 기존 freshness 검증으로 차단한다. 호출 뒤에도
현재 fingerprints와 controls를 다시 확인한다. 검증 불가 control은 완료를 인증하지 않는다.
live source가 과대/비UTF-8/unsafe로 안전하게 읽히지 않는 경우 control은 별도로 검증한다.
control과 seal이 유효한 active 회차만 pinned source 검토를 계속하며 current freshness는 unknown으로
남긴다. 새 회차 capture·public eligible·approve·execute에는 이 예외를 적용하지 않는다.
proposal ID/full digest·전체 read dependencies·서명 discovery_fingerprint를 재결합하거나
약화하지 않는다. 옛 approvals/claims/ledgers/publications는 재작성하지 않는다. 이미 frozen된
당일 보고는 이후 source drift에도 같은 digest이며 실제 실행 권한은 매번 새 freshness를 검사한다.

첫 이행은 최대4096개 scan 이름을 한 번 읽는 bounded migration이다. 초과는 fail-closed이며
자동 무제한 탐색/삭제를 하지 않는다. private legacy-index는 정확한 legacy scan/date pointer와
compact 참여 carry-in을 atomic 저장하여 index/state 사이 crash도 복구한다. 이후 directory scan은
없고 index·현재 round·최대32개 완료 pointer·두 날짜 day pointer만 사용한다. 이후 추가 legacy
carry-in은 정확한 day pointer만 인정한다. daily와 hourly를 병행 예약하지 않는다. timestamp 없는
활동·누락 기록·index 이후 pointer 없는 scan은 새 사실로 추정하지 않는다. 비용 미상 legacy는
기존대로 보수적으로 한도를 소비한다. 읽을 수 없는 증거도 0원/성공으로 해석하지 않는다.
이후 정확한 legacy day pointer를 비용과 참여 양쪽에 이행하며 scan/slot/stage identity로 중복을 막는다.

snapshot 없는 legacy active round는 과거 참여를 먼저 이행하고 invalidated 사본으로 종료한다.
그 회차에 현재 bytes를 붙여 이어 간 척하지 않는다. 기존 완료 review/승인은 새 control freshness에
따라 판정하며 파일은 보존한다. control 변경은 cursor/feedback 진행도 reset하지만 실제 참여와
완료 이력은 남긴다. source-only 변화는 이 무효화 조건에서 제외한다.

## 대안·한계·검증 인계

freeze 순서만 바꾸는 방안은 이전 실패/무효화와 재시작 참여를 잃으므로 부족하다. 무제한 scan
재탐색은 비용과 restart 경계를 제한하지 못한다. live source만 계속 쓰는 방안은 한 회차의 서로
다른 근거를 섞으며, source 변경마다 전체 reset은 진행을 막는다. 전체 repo archive나 단일 거대
Store record는 승인 범위·privacy·1MiB 한도를 위반한다. local 재시도/대체 provider는 승인된
호출/예산 정책과 다르므로 사용하지 않는다.

이번 작업자는 검사를 실행하지 않았다. 작성한 회귀는 Lab의 실제 engine→Store 재개 경로에서
전달 관측의 합성 legacy 이행, local 실패/empty/exception과 독립 slot, source drift 속9단계,
stale 승인/execute 거절, snapshot tamper/누락/size/mode/owner/link/crash no-call, control 변경,
window 경계·여러 회차 최신 실패·중복·bounded index와 frozen digest/privacy를 명세한다.
기존 비용·slot·interrupt·strict schema·quota/readiness/child guard·승인 보안 회귀는 유지한다.
실행기는 최종 코드와 documentation={status,files,reason}을 새 Claude 의미 검토로 평가하고
full make check를 실행한다. repair reviewer도 최종 의미를 새로 평가한다. 이후 기존 Git 역할과
trusted parent의 GitHub 게시·required CI·merge·cleanup을 인계한다. leaf는 이를 실행하지 않는다.
실제 hourly·서버·모델·private config·cron은 변경/관측하지 않았다. 실제 정규9단계 성공은
메인의 별도 증거가 필요하다. Sites의 기존 web-v1 schema/digest/최대8후보·3카드와 unknown의
같은 digest 조정, Python3.8 stdlib·하루24회/틱1회·Claude$1/reviewer$.20·GLM>=80% 차단은 유지한다.
