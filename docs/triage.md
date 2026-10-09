# Jev 작업 판단

개발 작업을 받은 직후, 구현 담당자를 정하기 전에 TypeSafe AI의 Jev로 세 가지를 판단한다.
`harness/triage.py`는 명시한 파일 경로의 규칙을 먼저 적용하고 Jev 결과를 비교한다.
단독 `agent-triage`는 **shadow 모드**다. 배정 추천과 비교 로그를 기록하며 에이전트를 실행하거나 코드를 수정하지 않는다.
`agent-run`의 기존 동작은 유지된다. [자동 작업 실행](workflow.md)의 `agent-workflow`는
동일한 판단 함수를 호출하고 추천을 실제 계획·담당 모델 실행·검토·검증으로 연결한다.
다운로더·파서·Django 운영 프로세스에 API 호출을 넣지 않는다.
구현 세션 중 오래된 도구 기록을 줄이는 [대화 기록 압축](compaction.md)은 별도 경로다.
같은 TypeSafe 키를 사용하되 접수 판단의 shadow 모드와 압축 훅의 실행을 구분한다.

```text
작업 설명 + 예상 수정 파일 목록
  → 파일 경로 규칙: 담당 영역 / 필수 검증 / 계약 검토
  → Jev: 영역 Choice / 복잡도 Score / 계약 영향 Noul
  → 영역 담당자 또는 Codex coordinator 추천 + private JSON 보고서
  → 사람이 결과를 검토한 뒤 기존 agent-run과 make check-* 사용
```

## 설정과 키 등록

모델·질문·기준값은 `harness/triage-config.json`, 엔드포인트와 인증 환경 변수는
`harness/agent-models.json`의 `typesafe` 공급자에 둔다. Jev는 별도 REST 판단 서비스이며
Codex/Claude Code의 구현 역할 모델을 대체하지 않는다.

모델은 `jev-1.13.0`으로 고정한다. 응답의 실제 모델 버전도 로그에 남긴다.
Python 3.8의 표준 라이브러리로 REST를 호출하므로 Ubuntu 20.04 ARM 서버에서도 별도 SDK가 필요 없다.

```bash
# 키 없이 고정 응답으로 먼저 확인한다. 외부 요청을 보내지 않는다.
make agent-triage-demo

# 사용자가 서버의 대화형 터미널에서 키를 입력한다.
make agent-configure PROVIDER=typesafe
make agent-doctor PROVIDER=typesafe

# 등록 후 실제 연결을 확인할 때만 실행한다. TypeSafe 요청 1회가 발생한다.
make triage-smoke
```

`TYPESAFE_API_KEY`를 환경 변수로 등록해도 된다. 환경 값이 로컬 파일보다 우선한다.
등록 명령은 기존 Claude/Z.ai 키를 보존하면서 Git에서 제외한 `.agent-keys.json`에 권한 `0600`으로 저장한다.
키를 명령 인자나 작업 파일에 적지 않는다. TypeSafe 키는 압축을 켠 Claude Code 실행에만 전달한다.
Codex와 압축을 비활성화한 자식 프로세스에서는 제거한다.
키 등록은 API 요청을 실행하지 않으며 `agent-doctor`도 등록 여부만 확인한다.
전체 `make agent-doctor`는 TypeSafe도 확인하므로 등록 전에는 `not_configured`로 종료한다.
개별 공급자는 `PROVIDER=codex`, `claude`, `zai`로 각각 확인할 수 있다.

TypeSafe는 별도 API 키가 필요하며 실제 판단 요청은 해당 계정의 사용량을 소비한다.
이 저장소의 키 없는 검증에는 실제 모델 호출을 포함하지 않는다.

## 작업별 추천 기록

작업 설명을 UTF-8 텍스트 파일에, 예상 수정 파일을 한 줄에 하나씩 작성한다.
파일은 저장소 상대 경로나 저장소 안의 절대 경로를 사용한다. 새로 만들 예정인 파일도 가능하다.
범위 목록에 있는 소스 파일의 내용이나 전체 Git diff를 자동 전송하지 않는다.
현재 저장소에 다른 작업의 변경이 있어도 작업 범위는 이 목록으로 한정한다.

```bash
# 기본은 파일 경로 규칙만 기록한다. 키가 등록돼 있어도 외부 요청이 없다.
make agent-triage TASK_FILE=/tmp/task.txt FILES_FILE=/tmp/task-files.txt

# Jev 판단을 요청하고 사람이 예상한 역할과 비교한다.
make agent-triage TASK_FILE=/tmp/task.txt FILES_FILE=/tmp/task-files.txt EXPECTED_ROLE=parser LIVE=1

# 추천 검토 후 기존 역할 실행을 별도로 선택한다.
make agent-run ROLE=parser TASK_FILE=/tmp/task.txt
```

`EXPECTED_ROLE`은 선택 사항이며 `coordinator`, `downloader`, `parser`, `django` 등의 기존 역할 이름을 사용한다.
비교의 `agrees`는 사람이 입력한 역할과의 일치 여부다. 샘플 한 번의 일치만으로 정확도를 평가하지 않는다.
범위가 없거나 담당 영역을 정할 수 없으면 coordinator를 추천한다.

## 판단 기준과 필수 검증

영역 Choice는 `downloader`, `parser`, `django`, `cross_boundary`, `unknown` 중 하나를 고른다.
복잡도 Score는 0(명확한 국소 작업), 1(조사·조정 필요), 2(설계·여러 영역 조정 필요)의
확률 가중 평균이다. `0.1`처럼 소수일 수 있으며 정수로 반올림하지 않는다.
계약 영향 Noul은 ID·단위·JSON 구조·참조 관계의 변경 가능성을 0~1로 평가한다.

| 조건 | 초기 기준 | 결과 |
| --- | --- | --- |
| 영역 confidence | 0.75 미만 | coordinator 계획 |
| 복잡도 confidence | 0.70 미만 | coordinator 계획 |
| 복잡도 score | 0.50 초과 | coordinator 계획 |
| 계약 영향 noul | 0.20 초과 | coordinator 계획 + 검토 필요 |
| 영역이 경로 규칙과 다름 / 여러 영역 / unknown | 항상 | coordinator 계획 |
| 키 없음 / 시간 초과 / HTTP 오류 / 응답 형식 오류 | 항상 | coordinator 계획 |

confidence는 답의 분포에서 계산한 지표이며 정답률이 아니다. 이 기준값은 실제 프로젝트 작업으로
보정하지 않은 초기값이다. 한국어 요청, 단일 영역 작업, 계약 변경, 여러 영역 작업의 비교 로그를
충분히 모은 뒤 기준값을 조정한다. 모델과 질문이 바뀌면 다시 확인한다.

다운로더·파서·Django 경로는 각각 `make check-downloader`, `make check-parser`, `make check-django`를 요구한다.
여러 영역, 공통 계약, importer, 파서 `DB.py`/`main.py`, 하네스, cron 경로는 `make check`를 요구한다.
Jev가 단순 작업으로 판단해도 경로 규칙을 낮출 수 없다. coordinator 추천은 `make check`를 요구한다.
모델·migration·계산 관련 핵심 파일과 계약 영향은 `review_required`에 표시한다.
보고서는 검증 실행 여부를 주장하지 않으며 실제 변경 후 해당 검증을 실행해야 한다.

운영 unpack/patch/Translation/JSON, 버전 CSV, 인증·Git 설정 등 보호 경로가 포함되면
Jev 요청도 보내지 않고 coordinator에 범위 확인을 맡기도록 표시한다.
작업 최대 24,000 UTF-8 바이트, 파일 최대 128개이며 초과 입력을 조용히 자르지 않는다.
네트워크 소켓 timeout은 기본 8초, 응답은 최대 64 KiB다.
오류 시 재시도나 다른 유료 API 호출 없이 즉시 계획 단계로 돌아간다.
HTTP 리다이렉트도 따라가지 않는다.

## 보고서와 검증

결과는 `logs/harness/triage/`의 권한 `0600` JSON 파일에 저장한다.
정책 버전·hash, 요청 상태 hash, 요청/응답 모델, 입력 경로, 판단 값·확률·confidence,
토큰 사용량, 소요 시간, 추천 역할·필수 검증·검토 여부, 선택적 역할 비교를 기록한다.
원문 작업 설명과 인증 헤더·서버 오류 본문은 저장하지 않는다.
등록된 키가 작업 설명에 포함되면 전송 전에 제거한다.

`source`는 `fixture`, `rules_only`, `api`를 구분한다. `api_called`와 `agent_started`도 별도로 기록한다.
`status=passed`는 형식이 유효한 판단 응답을 받았다는 뜻이며 추천 역할이 coordinator일 수도 있다.
`status=fallback`은 Jev 판단을 얻지 못했음을 나타낸다.
실제 요청이나 fixture 검증이 실패하면 CLI는 0이 아닌 코드로 종료하고 fallback 보고서를 남긴다.
의도적으로 요청하지 않은 기본 규칙 기록은 종료 코드 0으로 처리한다.
`agent-triage-demo`의 판단 값·토큰 수는 직접 작성한 고정 입력이며 실측치가 아니다.

`make check`는 고정 응답·가짜 HTTP 전송으로 한글 요청 인코딩, Bearer 인증, 타입·확률·소수 Score,
불확실성·계약 영향, 필수 검증 유지, 키 누락·시간 초과·429/529 오류,
키 격리·private 로그·에이전트 실행 금지를 검증한다. 실제 API 응답은 키 등록 후 `triage-smoke`로 확인한다.

공식 형식과 판단 의미:

- [TypeSafe REST API](https://docs.typesafe.ai/api)
- [Jev 모델 버전](https://docs.typesafe.ai/models)
- [Score의 확률 가중 평균](https://docs.typesafe.ai/primitives/score)
- [confidence의 의미](https://docs.typesafe.ai/confidence)
- [작업 라우팅 패턴](https://docs.typesafe.ai/patterns/intent-routing)
