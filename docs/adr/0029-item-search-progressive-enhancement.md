# 0029. 아이템 검색의 SSR 기본과 HTML 조각 부분 갱신

- 상태: 제안(proposed), 사용자 직접 요청 구현안; 새 독립 Claude 의미 검토·필수 검증·반영·게시 대기
- 기록일: 2026-10-24
- 기록 성격: 새 결정, 승인된 구현·테스트 소스의 계약 기록; 실행 성공 기록 아님
- 대체 관계: 없음, 기존 검토·검증·게시 정책 유지

## 문맥

사용자는 아이템 검색 `/items/`의 모바일 대응·빈 결과 안내와 검색/페이지 부분 갱신을
하네스로 구현·검증하도록 직접 요청했다. 현재 Django SSR·GET 검색과 지역 데이터·번역·
상세 링크·게임 계산을 유지해야 한다. 이 작업은 자율 개선 proposal 실행이 아니다.
JS 없음/미지원에서도 검색·페이지·공유·새로고침이 동작해야 하며 API 전체 전환·SPA·
새 외부 라이브러리·Planner/통합검색·공통 메뉴 수리는 범위 밖이다.

## 결정

1. `Items.views.index`가 검색 조건 정규화·queryset/context·건수·페이지당 10개 항목과 인코딩된
   페이지 URL을 함께 만든다. `search.html`의 include와 fragment 응답 모두
   `search_results.html`을 사용해 결과 표시를 공유한다. 정렬은 허용 목록과 `pk` 보조 순서를
   사용한다. 비정수 page는 1, 정수 page는 유효 범위로 제한한다. 잘못된 등급/직업/유형과
   비정수·signed 32-bit 범위 밖 레벨은 빈 조건, 미지원 정렬은 `updated-dsc`로 처리한다.
   다른 화면의 공통 입력 정규화 의미는 바꾸지 않는다.
2. 같은 `/items/` GET의 명시적 `X-Item-Search: results-v1`만 `text/html` 조각을 선택한다.
   응답 header도 `results-v1`이며, header 없음/미지 값은 `document` header의 전체 SSR이다.
   양쪽 모두 기존 Vary에 `X-Item-Search`를 추가한다. 캐시는 이를 구분해야 한다.
   fragment 전용 URL flag는 없다. 조각은 `#item-search-results` section 하나와
   `data-item-search-fragment="results-v1"`, 요약 하나, canonical `data-search-url`을 제공한다.
3. 검색 전용 CSS/JS만 로드한다. JS 기능 탐지 뒤 GET 제출·동일 origin의 정확한 검색 경로에
   있는 페이지/초기화 링크를 향상한다. 제출은 page를 제거한다. 상세·수정키·새 탭·다운로드
   링크는 기본 동작을 유지한다. 결과·건수·페이지 section만 교체하고 폼·메뉴·status/error는 유지한다.
4. 성공 응답의 canonical URL을 history에 반영한 뒤 결과를 교체하고 폼을 동기화한다.
   달라진 일반 성공 URL은 push, 같은 URL은 replace, popstate 재조회는 replace만 한다.
   실패는 이전 결과를 지우지 않고 마지막 표시 URL을 복원한다. popstate 실패는 폼도 복원하며
   실패한 목표를 Retry/전체 GET 링크에 남긴다. 이 복구는 실패 entry를 replace하며 원래
   history 전체를 보존하지 않는다. popstate 재시도 성공은 일반 페이지 탐색으로 처리한다.
5. AbortController 취소와 증가하는 요청 번호를 함께 사용해 오래된 결과를 차단한다.
   12초 timeout·HTTP 오류·redirect·잘못된 HTML 응답 계약은 오류 안내로 복구한다.
   삽입 전 Content-Type/응답 header·조각 root/summary·태그/속성 허용 목록·동일 origin의
   검색/상세 및 아이콘 URL을 검사하고 전체 문서·script 등은 거부한다. template escaping·
   URL/URLSearchParams·textContent로 사용자 값을 다루며 임의 HTML 삽입 계약으로 확대하지 않는다.
6. label/fieldset과 600px/360px 이하의 필터 재배치로 390px·320px을 고려한다. 표만 가로
   스크롤하고 키보드 focus·이름 상세 링크·등급 텍스트·`aria-current`를 제공한다.
   최초 진입은 검색 안내, q가 존재하는 0건 검색은 조건 보존·변경 안내·GET 초기화다.
   busy/polite live status와 오류 alert·재시도를 제공한다. 일반 제출 focus는 유지하고
   페이지/popstate 및 교체 영역에서 시작한 성공 탐색은 요약으로 이동하되 사용자의 후속
   focus 이동을 존중한다. 필요한 JS 기능이 없으면 native GET form/link를 그대로 사용한다.
   실패한 페이지/popstate는 Retry에 focus를 주고 재시도 성공은 숨겨지는 버튼 대신 요약으로
   복구한다. 재시도 중 사용자가 다른 control로 옮긴 focus는 유지한다.

## 비교 대안

- 전체 SSR 탐색만 유지하면 단순하지만 사용자가 요청한 부분 갱신을 제공하지 못한다.
- JSON API와 별도 client 렌더링은 검색·번역·결과 표시 책임을 중복하고 이번 범위를 넓힌다.
- fragment query flag는 공유/새로고침 URL에 내부 상태를 남긴다. 명시적 header와 양쪽 Vary로
  문서/조각을 구분하고 사용자 URL은 검색 조건만 담는다.

## 선택 이유

동일 서버 조회와 결과 template을 재사용하면 지역·번역·필터 의미를 한곳에서 유지하면서
GET fallback과 부분 갱신을 함께 제공한다. 작은 응답 계약과 교체 경계는 기존 Django 화면에
국한되며 취소·순서·history·오류 복구 책임을 검색 스크립트에서 확인할 수 있다.

## 결과·비용·제약

응답 계약이 바뀌면 서버 template과 client 허용 목록·테스트를 함께 검토해야 한다.
popstate는 결과 snapshot을 저장하지 않고 서버에서 재조회하므로 재조회 시점 데이터가 보인다.
격리 테스트는 운영 프록시 캐시의 Vary 준수나 실제 모바일 기기·다른 브라우저를 입증하지 않는다.

`Items.tests`와 기존 지역별 `EquipmentPipelineTests` 수집 경로는 SSR/fragment 동등성·Vary·
조건/페이지·특수문자·0건·비정상 입력을 명세한다. 브라우저 fixture에만 검색용 25행을 추가하며
공유 원본·지역 14행·계산기/젬 기대를 보존한다. manifest는 검색 9개·장비/젬 7개·PvP 2개,
총 18개 시나리오 × desktop/mobile = 36개 조합이다. 좁은 화면 시나리오 안에서 320px도 확인한다.
기존 오류 시나리오에서 Retry 성공의 요약 focus 복구와 대기 중 사용자가 옮긴 focus 유지도 명세한다.
누락/중복·skip/xfail·flaky·미수집 거부 정책은 유지한다. 작성된 명세는 검증 통과가 아니다.

매 fresh Claude 독립 의미 검토와 수정 후 재검토는 `documentation={status,files,reason}`를
새로 판단하고 코드·문서 의미의 완전성을 확인한다. architecture/harness·이 ADR·index가
이번 갱신 대상이다. 승인 밖 필수 문서는 정확한 경로/이유와 기존 승인 파일 finding으로 인계한다.
필수 검증은 전체 작업의 최종 diff로 선택한다. shared harness 변경이 있으므로 기본 `GIT=1`
full `make check`를 유지하고 parent가 실제 `check-browser-container` 또는 required Chromium CI를 확인한다.
독립 검토·mandatory checks·scoped apply·기존 Git 역할은 workflow/orchestrator 소유다.
parent의 기존 Git bridge가 GitHub 앱 게시·세 required CI success·SHA 고정 squash merge·
자동 cleanup·archive까지 이어간다. leaf는 실행하지 않으며 추가 승인 절차를 만들지 않는다.
이 기록은 기존 실패·역사·게시 정책이나 모델·인증·비용·storage 설정을 변경하지 않는다.

이번 보완의 전달 근거: parent는 source lock 아래 원래 capture 1560개 paths/hash/mode의
동일성을 확인했다. adapter는 각 역할 최초 write 직전 이전 실제 모델의 최종 after fingerprint와
일치하는 승인 source 초안만 격리 workspace에 복원하며 root source는 바꾸지 않는다.
private report/log/config/credential은 전달하지 않는다. 이는 구현·승인·검증 성공이 아니며
복원된 후보 전체에 새 독립 검토·full check와 기존 전달 절차가 필요하다.

## 관련 코드·검증·문서

- [검색 view](../../TavernofSoul/Items/views.py), [SSR](../../TavernofSoul/templates/Items/search.html),
  [공유 결과](../../TavernofSoul/templates/Items/search_results.html),
  [검색 JS](../../TavernofSoul/static/js/item-search.js), [검색 CSS](../../TavernofSoul/static/css/item-search.css).
- [Django 검색 회귀](../../TavernofSoul/Items/tests.py), [지역 pipeline 회귀](../../harness/equipment_tests.py),
  [격리 browser fixture](../../harness/browser_tests.py), [Chromium 시나리오](../../harness/browser/equipment.spec.js),
  [manifest](../../harness/browser/manifest.json), [결과 판정 회귀](../../harness/test_browser_runner.py).
- [구조·응답·복구 경계](../architecture.md#아이템-검색의-ssr와-부분-갱신-경계),
  [검증 수집·실행 인계](../harness.md#아이템-검색-계약의-격리-검증과-인계), [ADR 목록](README.md).
