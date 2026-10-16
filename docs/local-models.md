# 제한된 로컬 MLX 탐색

Mac mini는 작은 승인 소스 부분에서 초안을 찾고, 기존 네 specialist와 Claude reviewer가
검토한다. 로컬은 기존 역할을 대체하거나 제안 실행을 승인하지 않는다. 전체 순서·보고·예산은
[improvements](improvements.md), 결정은 [ADR 0017](adr/0017-budgeted-continuous-improvement.md)에 둔다.

## 준비 관측과 남은 검증

다음은 메인이 제공한 관측이며 문서 worker가 호스트를 조회한 결과가 아니다.

| 항목 | 제공된 상태 |
| --- | --- |
| Mac | Darwin arm64, macOS 27.0, M4 24GB(25769803776 bytes), Python 3.12 |
| 독립 venv | mlx-lm 0.32.0, mlx 0.32.4, transformers 5.19.0 설치 완료 |
| 모델 | mlx-community/Qwen3.5-9B-4bit, revision `8b2b98c00a6b4d291155e4890773ca8f769aee53`, 가중치 5950221072 bytes 다운로드 완료 |
| Mac 서비스 | 사용자 launchd, 127.0.0.1:18080만 listen; 메인 설치·재시작 확인 |
| Linux 터널 | 사용자 systemd SSH local forward, 127.0.0.1:18080만 listen, auto-restart/linger 설정; 메인 설치·재시작 확인 |
| 합성 응답 | API model=default_model, assistant text, finish_reason=stop, usage token counts; tools/functioncall 없음 |
| 새 adapter 합성 소스 실제 추론 | 메인 성공 확인, 약19.54초·정확한 승인 경로/줄 범위·후보1개 |
| 실제 repository 첫9단계 | 새 review/full check/scoped apply·메인 운영 검증 대기 |
| 연구 예약 | 기존 09:00 daily 유지; hourly 새 의견 교환·새 보고 활성화 대기 |

작은 합성 후보는 602 prompt/382 output tokens·23.18초에 기존 strict validator를 통과했다.
큰 합성 입력은 basename `example.py`를 반환해 거부되었고, system 지시/user JSON과 exact
path를 명시한 합성은 5727 prompt/387 output·44.61초에 `harness/example.py` 481..482를
반환해 통과했다. 이 이전 합성 관측 뒤 메인은 새 local_model adapter 자체로 합성 소스의 실제
추론 성공도 확인했다(위 표). 두 관측 모두 실제 repository 첫9단계 자동 검토나 아침 게시 전체를
검증한 결과는 아니다. 경로를 임의로 보정해 성공으로 바꾸지 않는다. NFS recovery 후 make doctor
통과도 메인 제공 관측이다.

## adapter와 private 설정

Linux `harness/local_model.py`는 Python 3.8 표준라이브러리만 사용한다. Linux 서버/테스트
requirements에 MLX를 추가하지 않는다. [공식 mlx-lm](https://github.com/ml-explore/mlx-lm)의
OpenAI형 text server를 사용하며 [모델](https://huggingface.co/mlx-community/Qwen3.5-9B-4bit)은
mlx-vlm 변환이지만 mlx-lm의 qwen3_5 text 지원을 사용한다. 이미지/향후 mlx-vlm 검토는 별도 범위다.

메인이 [예제](../harness/local-model-config.json.example)를 바탕으로 ignored private
`logs/harness/local-model.json`을 소유자 소유·단일 hardlink·nonsymlink·0600으로 제공한다.
ancestor symlink도 거부하며 코드가 chmod하거나 credential을 만들지 않는다. override는
`TAVERN_LOCAL_MODEL_CONFIG=/ABS/PRIVATE/local-model.json`처럼 절대 파일 경로만 받는다.
정확한 version/provider/model/api_model/endpoint/temperature/limits와 finite·타입·상한을 검증하고
config digest를 loop freshness와 서명 승인에 포함한다.

예제 endpoint는 `http://127.0.0.1:18080/v1/chat/completions`, provider는 `mlx-lm`,
model identity는 `mlx-community/Qwen3.5-9B-4bit`, API alias는 `default_model`이다.
정규형 숫자 loopback 127.0.0.1 또는 [::1]만 허용하며 localhost DNS·외부 host·0.0.0.0·
userinfo·query·fragment·다른 path·redirect·proxy를 거부한다. SSH 연결과 key는 메인만 관리하고
adapter에는 model credential이 필요 없다. API alias만으로 preload identity를 증명할 수 없어
메인이 실제 서비스의 모델을 확인해야 한다. HTTP를 인터넷에 공개하지 않는다.

POST는 messages의 system 지시와 user JSON 데이터를 분리한다. `model=default_model`,
`stream=false`, 제한된 max_tokens/temperature, `chat_template_kwargs={enable_thinking:false}`를
고정하며 tools/remote_code를 요청하지 않는다. 모든 endpoint 호출은 discovery guard 아래다.
`choices[0].message.content`의 비어 있지 않은 text와 `finish_reason=stop`을 요구한다.
length/tool_calls·empty·malformed·oversize·timeout·모델 mismatch는 실패하며 고정 reason만
반환한다. 원문 예외/응답을 저장·출력하거나 즉시 재시도·cloud fallback하지 않는다.
실제 MLX 정상 응답처럼 `Content-Type: application/json`을 요구하며 정상 합성 HTTP fixture도
같은 header를 제공해야 한다. header 누락을 허용해 fixture를 맞추지 않는다.
본문은 기존 bare JSON/단일 json fence parser와 strict 후보 validator를 사용한다.

## 보내는 소스와 의견의 경계

trusted parent가 승인 snapshot을 메모리로 넘기며 adapter는 파일을 열거나 repo를 복사하지 않는다.
owner의 기존 ownership+shared 범위에서 한 파일의 작은 연속 window만 보내며 경로는 정확한
저장소 상대 path, line은 원본 번호다. 기본 window 96줄, wire request 전체 최대 24576 UTF-8
bytes(지시/feedback 포함), feedback 4096 bytes, output max_tokens 3072, timeout 180초,
응답 body 65536 bytes·headers 8192 bytes다. 각 상한은 검증된 설정으로만 낮춘다.
window_lines와 feedback에는 각각 hard ceiling 256줄·8192 bytes가 있고 request 총상한은 유지한다.
HTTP framing/header/body와 주입 transport 응답에도 같은 제한을 적용한다.

durable owner별 file/line cursor는 다음 window/파일로 순환한다. 긴 한 줄은 `line_too_long`으로
skip하고 임의 slice하지 않는다. missing/empty도 명시 skip한다. candidate와 benefit evidence는
보낸 exact path+inclusive line 범위 안에서만 받는다. 나머지 승인 파일은 edit/documentation
대상일 수 있지만 읽은 근거로 주장하지 못한다. source 전체 1.5MiB를 로컬에 보내지 않는다.

이전 정제 issue·specialist 설명·Claude review.reason과 candidate_id/draft_digest를 제한된
feedback으로 실제 다음 prompt에 전달한다. feedback은 비신뢰 데이터이며 권한이 아니다.
소스/scope/config fingerprint 변경 시 이전 feedback·pool·cursor를 무효화한다. 무제한
prompt/model 캐시·자유 파일 접근·도구 실행·SSH/home/key 제공은 없다.

로컬 초안은 아직 eligible proposal이 아니다. 실패·빈 초안이면 관련 specialist를 호출하지 않고
정확한 보류로 기록한다. private scan의 bounded local_participation에서 실제 mlx-lm/model/
stage/owner_role/read_windows/상태를 확인하며 cloud 성공이나 웹의 여섯 번째 역할로 위장하지 않는다.
GLM/Claude 비용 unknown과 로컬 not_metered를 실제 0 USD 청구로 해석하지 않는다.
고정9단계의 reviewer 예산 admission 전에 local/구독 역할은 다른 gate 내 진행할 수 있지만
reviewer 예산 보류는 stage_index를 유지한다. 새 slot도 같은 reviewer를 재판단하므로 대기가
풀리기 전 다음 local/구독 역할은 호출하지 않는다. 보고 확정은 이 대기와 독립적이다.

## 메인 소유 서비스 운영

아래는 메인이 기존 서비스의 실제 label/unit과 절대 경로로 바꿔 사용할 절차 예제다.
이 worker는 SSH·서비스 상태·private 설정을 읽거나 명령을 실행하지 않는다. SSH 주소·계정·
key/path는 문서에 적지 않으며 기존 private 서비스 설정에서만 관리한다.

Mac의 별도 venv와 다운로드된 snapshot을 쓰는 text server 명령의 형태는 다음과 같다.
새 설치/다운로드를 뜻하지 않으며 이미 운영 중인 서비스의 인자와 버전 지원은 메인이 확인한다.

```bash
/ABS/MLX/VENV/bin/python -m mlx_lm.server --model /ABS/PRIVATE/MODEL/SNAPSHOT --host 127.0.0.1 --port 18080
```

서비스 restart/stop 예제의 UID·label·unit은 일반 placeholder다. 정확한 기존 서비스 하나만
대상으로 하며 새 서비스나 tunnel을 중복 생성하지 않는다.

```bash
# Mac, 현재 로그인한 사용자의 GUI session에서 기존 서비스 재시작
launchctl kickstart -k gui/USER_UID/PRIVATE_MLX_SERVICE_LABEL
# Mac, 정지: 다시 시작하려면 아래 bootstrap 필요
launchctl bootout gui/USER_UID /ABS/PRIVATE/MLX_SERVICE.plist
launchctl bootstrap gui/USER_UID /ABS/PRIVATE/MLX_SERVICE.plist

# Linux, 기존 SSH forward 사용자 unit 재시작/정지
systemctl --user restart PRIVATE_MLX_TUNNEL.service
systemctl --user stop PRIVATE_MLX_TUNNEL.service
```

계획 정지는 메인이 기존 improvement marked job을 비활성화한 뒤 tunnel과 Mac 서비스를
정지한다. 재개는 Mac 로그인·기존 서비스·터널·private config/storage 준비를 확인하고 동일
job을 복원한다. 현재 Mac GUI 로그인 중이라는 관측만 있으며, 재부팅 후 사용자 로그인 전
LaunchAgent 실행은 보장하지 않는다. Linux linger가 Mac 로그인 문제를 해결하지 않는다.

로컬 호출 장애 시 tick은 고정 reason과 private 실패 참여를 남기고 관련 specialist를 보류한다.
그보다 앞선 loop 설정·Store 생성·readiness 준비 실패는 bounded 정제 paused로 반환하며 모델·
키 조회·보고 확정·publisher·fallback을 하지 않는다. child/discovery 거부는 이 처리 바깥에 유지한다.
메인은 서비스·터널·로그인·준비 상태를 private 환경에서 확인하고 복구한 뒤 다음 새 hourly
slot을 기다린다. 이미 시작한 slot 강제 replay·state 삭제·자동 retry·cloud fallback은 하지 않는다.
보고 시각에는 기존 완료 review를 쓰거나 partial/failed로 확정하며 모델 재가동을 기다려
당일 보고를 새로 만들지 않는다. 보고 전송 unknown은 [동일 digest 복구](improvements.md#비공개-http-전달)를 따른다.

## 검토·검증 인계

`harness/test_local_model.py`와 `harness/test_improvement_loop.py`는 fake transport/clock/runner와
임시 저장소로 URL·private config·bytes/header/framing·evidence·cursor·feedback·실패·guard를
검증하도록 작성됐다. 기본 make check의 기존 harness test 수집에 포함되며 worker는 실행하지
않았다. 새 Claude reviewer가 실제 변경된 이 문서·설계/운영 문서·ADR의 의미를 평가하고
`documentation={status,files,reason}`을 반환한다. 확장자/fixture 존재로 완료를 주장하지 않는다.
직전 NFS full check1800초 timeout/failed/applied=[]와 그 부분 결과는 전체 검증 성공이 아니며
원본 baseline·GitHub·운영은 반영되지 않았다. 복원 초안도 검증 완료 증거가 아니다.
실행기의 새 review/full check·두 umask077/022 권한 fixture 검증/scoped apply와 메인의 실제
repository 첫9단계·운영 활성화·GitHub 인계·보고 게시 검증은 각각 별도로 남아 있다.
