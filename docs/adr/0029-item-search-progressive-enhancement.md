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
실제 Control-click과 `target=_blank` 새 탭은 두 viewport에서 유지한다. context의 routing과
request/response·console·weberror 감시는 page 생성 전에 설치하며 첫 요청도 포함한다.
반복마다 클릭 직전 request·page·response 관측을 연결한다. 정확한 targetURL·GET·
isNavigationRequest·document 유형과 이번에 수집한 request의 response.request() 동일성으로
원본 탐색을 식별한다. 문서 요청 1개·새 Page 1개·기존 pages에 없는 Page를 확인한다.
GET/200·document/Content-Type/Vary header를 확인한다. 본문을 직접 취득하지 않고 예상 URL의
DOMContentLoaded/load 뒤 html doctype·검색 form/results·전용 CSS/JS·25 Results · Page 2 / 3와
10행을 검사해 fragment만 열린 경우 실패시킨다. Request/Response.frame()이나 opener()는
동일성 조건으로 쓰지 않는다. 전체 HTML/fragment 본문은 `Items.tests`와
`EquipmentPipelineTests.assert_search_pair`의 독립 GET 검사 책임이다. 정상 GET의 doctype·
html·검색 form/results·CSS/JS와 조각의 공유 결과·문서/form/script 부재·응답 header/Vary를 검사한다.
JS 없는 시나리오도 검색·페이지·공유·새로고침·빈 결과·초기화·상세 GET을 확인한다.
원래 URL·document·결과를 보존하고 대기/검증 실패에도 새 탭을 정리한다.
about:blank의 load 상태나 합성 클릭만으로 이 검증을 대체하지 않는다.
의도한 HTTP 실패 예외는 정확한 URL/status가 일치하는 비탐색 fragment 요청만 허용한다.
누락/중복·skip/xfail·flaky·미수집 거부 정책은 유지한다. 작성된 명세는 검증 통과가 아니다.

매 fresh Claude 독립 의미 검토와 수정 후 재검토는 `documentation={status,files,reason}`를
새로 판단하고 코드·문서 의미의 완전성을 확인한다. 전체 구현 문서는 architecture/harness·
이 ADR·index이며 이번 검증 책임 정정은 이 ADR에 한정한다. 승인 밖 필수 문서는
정확한 경로/이유와 기존 승인 파일 finding으로 인계한다.
필수 검증은 전체 작업의 최종 diff로 선택한다. shared harness 변경이 있으므로 기본 `GIT=1`
full `make check`를 유지한다. parent는 fresh Claude 승인 뒤 격리 candidate에서 실제 로컬
`check-browser-container`를 먼저 실행한다. 36 positive passed·zero skip/flaky/missing,
컨테이너 cleanup과 candidate fingerprint 동일성을 확인한 뒤 원래 full `make check`를 실행한다.
동일 bytes의 두 검증을 확인한 후 scoped apply·Git·새 GitHub request/commit/branch/PR로 이어간다.
실패 JSON은 native 수리 피드백으로 돌려주며 과거 성공이나 미실행 full check를 재사용하지 않는다.
게시 후 required Chromium CI도 별도로 통과해야 한다.
독립 검토·mandatory checks·scoped apply·기존 Git 역할은 workflow/orchestrator 소유다.
parent의 기존 Git bridge가 GitHub 앱 게시·세 required CI success·SHA 고정 squash merge·
자동 cleanup·archive까지 이어간다. leaf는 실행하지 않으며 추가 승인 절차를 만들지 않는다.
이 기록은 기존 실패·역사·게시 정책이나 모델·인증·비용·storage 설정을 변경하지 않는다.

이번 보완의 전달 근거: parent는 source lock 아래 원래 capture 1560개 paths/hash/mode의
동일성을 확인했다. adapter는 각 역할 최초 write 직전 이전 실제 모델의 최종 after fingerprint와
일치하는 승인 source 초안만 격리 workspace에 복원하며 root source는 바꾸지 않는다.
private report/log/config/credential은 전달하지 않는다. 이는 구현·승인·검증 성공이 아니며
복원된 후보 전체에 새 독립 검토·full check와 기존 전달 절차가 필요하다.

## 수리 이력과 검증 인계

아래는 이전 후보에 대한 parent 제공 기록이다. 당시 수치와 실패는 보존하며 이번 후보의
승인·검증 성공으로 재사용하지 않는다.

이전 기록: Claude 승인 후 full check 5882 selected/5881 passed, `applied=[]`.
종전 개별 초과 설명(127442→133152bytes)은 정정: parent 진단은 37개 합계 1576439bytes,
repair 후 1576512bytes로 전체 1572864bytes 초과다. 개별 131072bytes 한도 유지.

2026-10-24 인계: 직전 run1792847727194688105-9fe24d는 검색 CSS outline 충돌 수리 뒤
Claude JSON 파싱 실패로 `applied=[]` 종료했다. 그 응답은 보정·재사용하지 않는다.
이전 Chromium 34/36은 desktop/mobile 링크 outline 실패 이력이며 새 성공 근거가 아니다.
국소 CSS 수리는 기존 focus 가시성 계약의 복구이므로 추가 ADR은 필요 없다.
parent 제공 runtime 연구 합계는 37개·1570437bytes/1572864bytes, 개별 상한은 128KiB다.
scope/config/상한을 유지한다. fresh reviewer는 유효한 JSON 객체만 반환하며
`verdict/summary/findings/documentation={status,files,reason}`와 문자열 escape를 지킨다.
당시 full check 뒤 Chromium 확인 순서는 이번 수리에서 위의 브라우저 우선 순서로 갱신한다.
PR72의 실패 게시 흐름은 재개하지 않고 대체 완료 후 정리한다. worker는 검사를 실행하지 않았다.

최신 parent 제공 관측: run1792848314658932989-93d8ea는 새 Claude 승인·full check
5882/5882·15파일 반영이었다. 후속 실제 Chromium run1792849453368192814-723ada는
34/36이며 outline·Retry/popstate는 통과, desktop/mobile의 native 새 탭 시나리오가 실패했다.
두 문서 요청은 HTTP200으로 약 26ms였으나 desktop은 page 이벤트 대기, mobile은 page 이벤트와
interception 설정 뒤 빈 summary 대기로 실패했다. 이 관측만으로 원인은 확정하지 않는다.
현재 변경의 실제 브라우저·전체 검증·게시 성공은 아직 없으며 새 GitHub 게시 요청도 시작하지 않았다.

최신 run1792850327831107900-ca2895는 새 Claude 승인 후 실제 격리 Chromium 34/36이었다.
새 탭 생성·HTTP200은 확인됐으나 desktop/mobile 모두 `tab.opener()`가 null이라 동일성
단언이 실패했다. 원래 화면 보존·실제 새 탭의 올바른 문서가 계약이므로 이 단언만 제거한다.
opener 참조 생성이나 보안 격리 완화는 하지 않는다. timeout·retry·skip·시나리오/게이트는 유지한다.
후속 native 수리 준비는 복사 SDK의 `.bin` symlink로 `Workspace contains a symlink`에
실패해 run은 failed/`applied=[]`다. parent 준비 helper가 브라우저 성공·실패 뒤 자신이 복사한
SDK만 제거하고 native 수리/전체 검사를 계속한다. 제품 소스·공통 SDK·정책 수정 사유가 아니다.
pinned SDK 준비는 parent 검증 사본에만 한정한다.

이 수리 전 parent metadata 관측은 runtime37 합계1574584>1572864bytes(1720초과),
harness131858>131072bytes(786초과)다. 원본 합계1567890bytes, 변경 여유4974bytes이며
이번 개별 목표는 architecture<=86318, harness<=129000, harness-design<=77611,
ADR index<=35025 UTF-8 bytes다. runtime 연구37개 scope·개별128KiB/전체1.5MiB를 유지한다.
worker는 승인 문서의 bytes만 측정하며 전체 runtime 측정·SDK 정리는 parent 책임이다.
통합 후 새 Claude는 최종 소스·테스트·문서 전체 diff를 실제 읽고 독립 의미 검토와
유효 JSON·`documentation={status,files,reason}`를 새로 판단한다. 이전 승인은 재사용하지 않는다.
parent는 실제 브라우저36/36·정리·source fingerprints 불변 다음 원래 native full check를
동일 최종 bytes로 확인한다. 실패 브라우저 JSON은 수리 피드백이며 full check 성공을 대신하지 않는다.
이후 scoped apply·기존 Git 역할·새 PR의 실제 CI3 success·merge·cleanup·archive가 필수다.
PR72의 거절된 게시 흐름은 재개하지 않는다.

과거 run1792851233106376400-e58096은 동일 bytes의 Chromium 두 번 모두 35/36이다.
mobile native 새 탭의 `equipment.spec.js:355:43 response.text()`에서
`Network.getResponseBody: No resource with given identifier found`가 발생했다.
navigation 뒤 원본 body를 읽는 수명 경쟁이며 성공·일시 환경 문제로 해석하지 않는다.
중첩 location 전달 실패로 native 피드백은 unavailable, run은 no_progress/`applied=[]`였다.
당시 수리는 응답 직후 같은 promise에서 body/finished를 await해 Buffer를 보존하고,
foreground/load/닫기 전 모든 실패를 정산하는 접근이었다. 이 본문 수명 가정은 아래 실패로
폐기됐으며 현재 계약이 아니다. 기존 35개 통과도 새 검증이 아니다.

run1792852368774866329-35e2b8은 실제 Chromium 두 번 모두 34/36, 새 탭 desktop/mobile 실패,
native max_rounds 소진·failed/`applied=[]`였다. response predicate의 Request.frame()은
최초 navigation의 frame 생성 전에 throw했다. desktop timeout도 같은 예외 뒤 남은 page 대기다.
[공식 Request.frame 제약](https://playwright.dev/docs/api/class-request#request-frame)에 따라
정상 새 탭에도 가능한 API 가정 오류로 수리하며 제품 속도·timeout 문제로 해석하지 않는다.
당시 frame 의존은 제거했으나 응답 즉시 body/finished를 보존하는 가정은 남아 있었다.
frame을 필수 조건으로 삼았던 접근도 역사적 실패이며 현재 계약이 아니다.

직전 run1792853151345714208-fa9dcf는 실제 Chromium 34/36, desktop/mobile 모두
`equipment.spec.js:359 response.body()`에서 `Network.getResponseBody: No resource with given
identifier found` / `Response body is not available for a response that was navigated away from`으로
실패했다. parent는 자동 수리를 중단했으며 interrupted/`applied=[]`, root는 baseline이다.
이번 수정은 사용자 기능이 아니었던 native 최초 본문 취득 조건을 제거한다. 오류 무시나
성공 fallback·별도 fetch로 대체하지 않고 위 네트워크/로드된 문서/독립 서버 본문 책임으로 검증한다.
page·response·click 대기는 모두 정산하고 실패와 탭 정리 오류를 전파한다.
추가 fetch·frame/opener 필수 조건·합성 새 탭·retry/skip·timeout 증가는 없다.
fresh reviewer는 실제 context 감시·predicate·helper·호출 순서와 독립 서버/JS 없는 GET 검사를
새로 읽고 유효 JSON 및 `documentation={status,files,reason}`를 판단한다. 이전 승인·34개 통과는
재사용하지 않는다. parent는 실제 실패 JSON을 보존하고 승인 경로의 실제 error.location
file/line metadata만 native 진단에 연결한다. 원문 자유문자열 우회와 counts/coverageerrors 제거는
금지한다. SDK 복사본만 finally 정리하며 동일 bytes의 새 검토·36/36·정리·fingerprint·원래
native full check와 위 Git/새 PR 전달은 parent에게 남긴다. worker는 검사를 실행하지 않았다.

## 관련 코드·검증·문서

- [검색 view](../../TavernofSoul/Items/views.py), [SSR](../../TavernofSoul/templates/Items/search.html),
  [공유 결과](../../TavernofSoul/templates/Items/search_results.html),
  [검색 JS](../../TavernofSoul/static/js/item-search.js), [검색 CSS](../../TavernofSoul/static/css/item-search.css).
- [Django 검색 회귀](../../TavernofSoul/Items/tests.py), [지역 pipeline 회귀](../../harness/equipment_tests.py),
  [격리 browser fixture](../../harness/browser_tests.py), [Chromium 시나리오](../../harness/browser/equipment.spec.js),
  [manifest](../../harness/browser/manifest.json), [결과 판정 회귀](../../harness/test_browser_runner.py).
- [구조·응답·복구 경계](../architecture.md#아이템-검색의-ssr와-부분-갱신-경계),
  [검증 수집·실행 인계](../harness.md#아이템-검색-계약의-격리-검증과-인계), [ADR 목록](README.md).
