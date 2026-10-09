# Jev 오프라인 판단 fixture

`task.txt`와 `files.txt`는 한국어 읽기 전용 다운로더 조사 작업이다.
`response.json`은 TypeSafe REST 응답 형식을 따라 직접 작성한 고정 입력이다.
실제 API 결과나 모델 성능 측정값이 아니다. 토큰 수 역시 예시 값이다.

`make agent-triage-demo`는 이 응답으로 담당 영역·소수 복잡도·계약 영향과
다운로더 배정 추천을 확인한다. 키·네트워크·운영 데이터가 필요 없고 에이전트를 시작하지 않는다.
오류·불확실성·영역 불일치 등은 `harness/test_jev_client.py`와 `harness/test_triage.py`에서 검사한다.
질문의 복잡도 척도를 변경하면 fixture의 `legend`도 같은 척도로 갱신한다.
