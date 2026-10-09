# Jev 대화 기록 압축

[fast-jev-compaction](https://github.com/tamaratran/fast-jev-compaction)을
이 프로젝트의 Claude Code 실행에 연결한다. 오래된 도구 호출·결과를 Jev가 판단해
보존하거나 결과의 앞부분만 남기거나 호출과 결과를 함께 제거한다.
출력에서 사용자·에이전트의 텍스트는 원문과 순서를 유지하고 첫 메시지와 최근 6개 메시지는 보존한다.
현재 역할은 `downloader`(GLM), `reviewer`·`escalation`(Claude)에 적용한다.
기존 `coordinator`·`parser`·`django`의 Codex 실행 인자는 유지한다.
게임 운영 파이프라인에는 연결하지 않는다.

## 사용

이미 등록한 `TYPESAFE_API_KEY`를 재사용한다. 키 등록 없이도 고정 입력을 실행할 수 있다.

```bash
make compaction-doctor
make compaction-demo
make check-compaction-engine

# 원래 역할 실행에 프로젝트 플러그인이 자동으로 붙는다.
make agent-plan ROLE=downloader
make agent-run ROLE=downloader TASK_FILE=/tmp/downloader-task.txt
make agent-run ROLE=reviewer TASK_FILE=/tmp/review-task.txt

# 이 실행에서만 기존 최소 모드와 기본 압축을 사용한다.
make agent-run ROLE=downloader TASK_FILE=/tmp/downloader-task.txt COMPACTION=0
```

전체 기본값은 `harness/agent-models.json`의 `compaction.enabled`로 변경한다.
`COMPACTION=1`은 해당 실행에서 명시적으로 켠다. 공급자 범위는 manifest의 `providers`를 따른다.
일반 `agent-smoke`는 인증·모델 응답 확인을 위해 기존 최소 모드로 실행한다.
`COMPACTION=1`을 지정하면 smoke에도 플러그인을 로드한다.
기존 읽기 전용·편집 범위·공급자 인증 분리·Claude 호출별 비용 한도는 같은 옵션을 사용한다.

Claude Code **2.1.287 이상**을 요구하며 2.1.294에서 검증한다.
이 버전에서는 mods가 기본 활성화되어 초기 접근용 `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS`가 필요 없다.
압축을 켠 실행은 훅을 차단하는 `--bare`/`--safe-mode` 대신 명시적 `--plugin-dir`을 사용한다.
사용자·프로젝트 settings 자동 로딩은 `--setting-sources ''`로 제외하고 MCP도 빈 설정으로 제한한다.
공급자별 기존 `CLAUDE_CONFIG_DIR`을 사용하므로 전역 플러그인 설치나 설정 수정은 필요 없다.

## 압축 설정

`harness/compaction/.claude-plugin/plugin.json`의 `userConfig.*.default`가 초기 설정이다.

| 항목 | 값 | 의미 |
| --- | --- | --- |
| model | jev-1.13.0 | 판단 모델 고정 |
| compactAtPercent | 60 | turn.complete에서 컨텍스트 사용률을 확인해 압축 요청 |
| preserveRecentMessages | 6 | 최신 6개 메시지의 호출·결과 보존 |
| keepThreshold | 0.5 | 도구 호출 또는 결과를 남기는 확률 기준 |
| truncateHeadChars | 300 | 결과를 줄일 때 남기는 앞부분 길이 |
| minReductionRatio | 0.25 | 예상 문자 감소가 25%보다 작으면 기본 압축으로 복귀 |
| maxStateTokens | 25000 | Jev에 보내는 상태의 추정 토큰 상한 |
| maxRequestTokens | 30000 | 상태와 질문을 합친 추정 토큰 상한 |

도구 결과 원문은 Jev 상태에서 크기·오류 여부를 나타내는 메모로 대체한다.
**대화 텍스트와 도구 입력은 TypeSafe로 전송한다.** 상태가 크면 Jev가 볼 입력을 단계적으로 줄이고
질문을 여러 요청으로 나눈다. 유지할 실제 대화의 텍스트를 요약하거나 다시 쓰지는 않는다.
토큰 수와 감소 비율은 추정값이며 작업마다 절감량이 달라진다.
여러 요청이면 같은 상태가 반복 전송되어 TypeSafe 사용량을 각각 소비한다.
Claude CLI의 달러 비용 한도에는 별도의 TypeSafe 사용량을 합산하지 않는다.

키 누락·HTTP/네트워크 오류·잘못된 응답·상태 크기 초과·낮은 감소율은 업스트림 훅이
`next(event)`로 Claude Code 기본 압축에 맡긴다. 다른 구현 모델이나 유료 공급자로 전환하지 않는다.
남은 호출만 있고 결과가 아직 없는 진행 중 작업은 압축 후보에서 제외한다.
Jev가 삭제한 오래된 도구 결과는 필요할 때 다시 읽거나 실행해야 한다.

프로젝트 HTTP 어댑터는 등록된 키를 Jev 상태에서 제거하고, HTTP 오류 본문과 전송 예외 내용을
진단에 노출하지 않는다. 응답의 질문 목록·Noul 타입·0~1 확률·모델 버전도 검사한다.
어댑터 오류 역시 기본 압축으로 복귀한다. 키는 소스·플러그인 설정·명령 인자에 저장하지 않는다.

## 고정 버전과 검증

업스트림 커밋은 `e3f262a7f4d42bd8dd32ced30d26176f7cb545b0`이다.
원본 TypeScript, 컴파일한 JavaScript, MIT 라이선스와 hash를 `harness/compaction/vendor/`에 보관한다.
`UPSTREAM.json`에는 컴파일러 버전과 소스·산출물 hash도 기록한다.
실행·진단 전 hash를 검사한다. 자동 다운로드나 업스트림 자동 업데이트는 없다.
실행에 npm 의존성이 없으며 기본 검증은 기존 Node.js 18 이상으로 가능하다.

프로젝트의 `hooks/register.js`는 원본 컴파일 훅의 패치 사본이다.
import 경로를 vendor로 바꾸고 HTTP 호출에 `hooks/transport.js`를 넣었다.
라이브러리의 판단·메시지 재구성 코드는 수정하지 않는다.
manifest는 작성자 정보를 추가하고 기본 모델을 고정했다.
다음 업데이트는 원본 TypeScript에서 다시 빌드하고 이 패치·hash·검증을 함께 갱신한다.
원본 빌드에는 고정 커밋의 `package-lock.json`과 `tsconfig.hooks.json`을 사용했고,
`noEmit: false`, `rootDir: <checkout>`, `outDir: <temporary output>`, `include: hooks/fast-jev.ts`로 산출물을 만들었다.

`make check`에는 Node의 오프라인 압축 테스트와 Python의 역할·인증·실행 옵션 검증을 포함한다.
실제 Claude Code가 없어도 동작하며 테스트의 skip/todo나 미실행은 실패 처리한다.
추가 `make check-compaction-engine`은 설치된 Claude Code의 테스트 엔진으로 훅을 로드하고
압축·기본 압축 위임 이벤트를 실행한다. 모델·로그인·외부 요청은 사용하지 않는다.
`make compaction-doctor`는 고정 소스·CLI 버전·엄격한 플러그인 검증·키 등록 여부를 확인한다.

실제 TypeSafe 연결은 다음 별도 명령으로 확인한다.

```bash
make compaction-smoke
```

이 명령은 직접 작성한 합성 대화만 Jev에 보내고 타입 검사·텍스트 보존·압축 결과를 확인한다.
실제 개발 대화나 저장소 파일을 읽어 보내지 않으며 구현 에이전트를 실행하지 않는다.
실제 긴 코딩 세션의 자동 압축을 검증한 것으로 간주하지 않는다.
데모의 판단 값·감소율·사용량은 고정 입력 결과이고 smoke는 실제 API 응답이다.
데모·진단·엔진·smoke 보고서는 `logs/harness/compaction/`의 권한 `0600` JSON에 저장한다.
`agent-run`의 `compaction.status=requested`는 로드를 요청했다는 뜻이다.
CLI가 훅 거부·실패를 알리면 `unavailable`로 기록한다. 모델 응답 성공과 압축 성공을 구분한다.

공식 근거:

- [업스트림 고정 커밋](https://github.com/tamaratran/fast-jev-compaction/tree/e3f262a7f4d42bd8dd32ced30d26176f7cb545b0)
- [Claude Code mods 실행 범위와 최소 버전](https://code.claude.com/docs/en/plugins/mods/overview)
- [mods 테스트 엔진](https://code.claude.com/docs/en/plugins/mods/test)
- [훅이 로드되지 않는 이유](https://code.claude.com/docs/en/plugins/mods/troubleshoot)
