# 0019. Private GLM call telemetry through a parent loopback collector

- 상태: 제안(proposed), 구현안의 새 의미 검토·전체 검사·parent 합성 검증 대기
- 기록일: 2026-10-18
- 기록 성격: 사용자 직접 요청에 따른 새 결정; 관측 성공 기록이 아님
- 대체 관계: 없음. 0017의 schedule/admission, 기존 인증·compaction·storage 결정을 유지

## 문맥

연구의 전체 elapsed_seconds와 최종 CLI JSON만으로는204~500초가 걸린 실제 호출에서
첫 응답, 요청/재시도, Read body와 부모 filesystem 준비 비용을 구분할 수 없다.
메인이 제공한 Claude Code2.1.294/Z.ai Coding Lite glm-5.3-flash 합성 Read fixture는
nonessential traffic 차단·compaction 요청을 유지하면서 built-in OTLP http/json exporter가
작동함을 보였다. 이는 이 구현의 검증 또는 실연구의 병목 관측이 아니다.
사용자는 첫 응답 시간·API 호출 수·파일 읽기 시간의 정확한 관측 근거를 요청했다.

## 결정

[agent_telemetry.py](../../harness/agent_telemetry.py)는 Python3.8 표준라이브러리만 사용해
한 GLM 자식 수명에 속한 임시 `127.0.0.1` collector를 소유한다. random secret path의
정확한 POST JSON만 허용한다. traces exporter만 활성화하고 logs/metrics/content capture는
비활성화한다. 상속 exporter·content·raw-log·legacy tracing·propagation overrides를 제거하고
loopback만 proxy bypass에 추가한다. 기존 model HTTP routing과 credential/runtime isolation은
유지한다. bind/setup 실패는 unavailable과 exporters none으로 원래 모델 호출을 계속한다.
성공·spawn 실패·timeout·interrupt 모두 socket/thread를 정리하고 telemetry 실패에 모델
재시도·fallback을 추가하지 않는다. Codex/Anthropic Claude에는 이 동작을 적용하지 않는다.

수신 raw JSON과 ID는 파일로 남기지 않는다. bounded in-memory ID로 unique completed
llm_request를 dedup하고 tool.execution을 parent에 연결한다. chronological request row에
launch-relative start·lifecycle·TTFT/content·attempt·success·token counters를 보존한다.
Read/Glob/Grep/other fixed categories의 permission-inclusive wall과 실제 body execution을
분리한다. 겹친 작업 합계를 wall에서 빼서 exact overhead/disk I/O로 해석하지 않는다.

[agent_models.py](../../harness/agent_models.py)는 final JSON transport를 유지하며 별도
부모 CLI wall·정제 final JSON metrics를 기록한다. [improvements.py](../../harness/improvements.py)는
parent context 준비/검증 시간을 추가하고 실패·축약·invalid candidate에도 관측을 보존한다.
[improvement_loop.py](../../harness/improvement_loop.py)는 엄격한 version/enum/numeric/row
allowlist로 재검사하고 집계를 재구성한다. [improvement_report.py](../../harness/improvement_report.py)의
기존 공개 projection은 유지하여 telemetry·diagnostics 유무와 무관하게 동일한 web bytes와
digest를 생성한다. private scan/state에 선택적 `glm-call-telemetry-v1`을 보존하며 기존 record
버전·fingerprint·path selection·1MiB 상한·frozen report를 변경하지 않는다.

## 비교 대안과 선택 이유

- streaming CLI transport 전환: 이번 요청에는 불필요하며 기존 final JSON 실패 계약을 더 넓게 바꾼다.
- 모델 API proxy/직접 inference 호출: 인증·compaction·라우팅 의미가 달라진다.
- raw debug logs/trace 파일: 비밀·content 보존 위험과 disk 수명/정제 부담이 크다.
- 전체 wall/final JSON만 기록: 요청 순서·실제 first content·Read body를 알 수 없다.
- 외부 telemetry server: 현재 private 격리 요구에 불필요한 전송 경계를 추가한다.

built-in exporter와 parent loopback은 검증된 CLI 프로토콜을 활용하면서 자식 호출의
telemetry destination과 데이터 보존을 부모가 제한할 수 있어 선택한다. plugin rewrite나
계측을 위한 별도 model call은 없다.

## 결과·비용·제약과 실패 복구

한 listener thread와 임시 socket, 최대4MiB 입력/4096 span/2048 memory IDs,
각128 request/tool row, body256KiB/header8KiB, peer0.5초/socket0.1초 및 호출 timeout+1초
수명(최대3601초)을 추가한다. 정확한 필드·numeric 한도는 [agent-models](../agent-models.md#glm-호출의-private-지연-관측)에 둔다.
알 수 없는 key·resource/session/events·임의 이름/오류·content·경로·header·endpoint는
사라진다. malformed/압축/chunked/unauthenticated/과대 입력은 고정 응답으로 거부한다.
로그나 raw 예외를 출력하지 않는다.

관측 logical request는 export된 completed span 수로 한정된다. transport attempt/retry는
알려진 필드만 합산하며 숨은 CLI/SDK 요청이나 미완료/미수출 요청은 미상이다.
성공도 completeness=partial이며 silence는 unavailable/null이지 측정된0이 아니다.
limit 도달 시 보존된 prefix의 하한만 남는다. 실패/timeout에는 이전에 받은 관측만 남기며
final JSON metrics로 빈 span을 합성하지 않는다. exporter 비용·CLI export 지연·강제 종료로
일부 데이터가 빠질 수 있다. 동일 OS 사용자 공격을 격리하는 보안 VM은 아니다.

계측은 otherwise successful CLI를 실패로 만들거나 CLI/후보 실패를 성공으로 만들지 않는다.
계측 실패 시 추가 호출·fallback·scope 확대·schedule/state 수정이나 frozen day 재발행을
하지 않는다. 다음 정상 admission된 GLM 연구만 관찰한다.

## 관련 코드·검증·문서

[collector fixtures](../../harness/test_agent_telemetry.py),
[model fixtures](../../harness/test_agent_models.py),
[scan fixtures](../../harness/test_improvements.py),
[loop fixtures](../../harness/test_improvement_loop.py)는 synthetic OTLP·mocked subprocess·
loopback fake peer만 사용한다. chronological first selection, dedup/retry/unknown,
child-first Read join, 실패/timeout, 무수출/bind/spawn 오류, malformed/flood/privacy/env,
stalled peer cleanup, provider exclusion, 실패 기록 보존과 공개 bytes 동등성을 명세한다.
worker는 실행하지 않았다. parent가 relevant tests와 full `make check`를 skip/xfail 없이
검사하고 새 의미 검토 및 합성 live를 담당한다. 메인은 그 뒤 기존 gate가 허용한 GLM hourly
기록을 읽으며 production 성공을 꾸미지 않는다. [개선 기록 읽기](../improvements.md#private-glm-지연-기록-읽기),
[전체 설계](../harness-design.md), [검증 책임](../harness.md), [workflow](../workflow.md)를 함께 따른다.
공식 API 근거는 메인이 확인한 [monitoring usage](https://code.claude.com/docs/en/monitoring-usage)다.
