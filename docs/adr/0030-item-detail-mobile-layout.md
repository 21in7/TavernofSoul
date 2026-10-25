# 0030. 아이템 상세의 모바일 배치와 접근 가능한 표

- 상태: 제안(proposed), 직접 요청의 설계 기록·최종 검토/검증/전달 대기
- 기록일: 2026-10-25
- 기록 성격: 새 결정, 구현 승인과 실제 성공 증거를 구분
- 대체 관계: 없음. 검색의 ADR0029 계약과 기존 계산을 보존한다.

## 현재 복원 인계와 직전 전체 검증 중단

이번 parent 제공 이력에서 직전 `run1792912974194609408-61597c`의 최종 round2는
새 Claude 의미 검토 approved 뒤 세 독립 컨테이너의 실제 Chromium을 각각 46/46으로
통과했다. 이후 원래 전체 check의 downloader도 129/129를 통과했으나 상위 make가
`Terminated`로 끝났다. report는 validation running으로 남았고 실제 호스트 PID는 사라졌으며
`applied=[]`·Git 미실행이다. 전체 검증 성공·반영·완료가 아니며 원래 기록은 변경하지 않는다.
이는 parent 제공 과거 이력으로, 이번 leaf가 원본 실행 산출물을 열거나 재검증한 결과가 아니다.
아래 이전 인계의 ‘최신 45/46’, ‘수리 후 결과 없음’, ‘미실행’과 documentation JSON은
각 기록 당시 상태로 보존한다. 현재 복원 인계는 이 절을 따르며 과거 성공을 이번 gate로 쓰지 않는다.

이번 leaf가 읽은 승인 CSS·상세 template·browser manifest/config/spec에서 현재 설계와
수집 계약을 확인했다. 계산기 입력 열은 CSS-only sticky이며 최소 106px 열·88px 입력·
좌우 8px 여백·body/header z-index 2/3·계산기 전용 scroll-padding을 유지한다.
상세 template은 기존 계산 JS를 연결하며 제거된 `item-detail.js` prototype을 로드하지 않는다.
현재 `detailTableAccess`는 첫 실제 ArrowRight의 양의 이동을 확인하고 region에 hover한 뒤
실제 wheel을 최대 64회 반복한다. 매회 실제 진행을 기다리고 마지막 열 전체 도달을 요구하며,
scroll 한계·반복 상한에서도 미도달이면 실패한다. 이어 첫/끝 header·body 셀의 엄격한 rect와
pointer hit, 실제 Tab 후 입력·outline의 viewport/scrollport 전체 bounds를 검사한다.
중간 위치만 확인하던 검사나 timer·JS scroll fallback으로 되돌리지 않는다. 23×2=46조합과
기존 timeout·retries=0·누락/중복/skip/xfail/flaky/error 거부를 보존한다. 이는 소스 읽기이며
이번 실제 Chromium 또는 전체 검증 실행 결과가 아니다.

parent는 최종 소스 초안만 native owner에 복원하고 승인 39파일을 정확히 한 번씩 배정한다.
새 Claude의 동일 최종 candidate 의미 검토와 유효한
`documentation={status,files,reason}` 뒤 새 컨테이너의 실제 Chromium 3회, 기본 `GIT=1`
전체 `make check`, scoped apply·기존 Git 역할·실제 GitHub 필수 CI3 success·squash merge·
cleanup·archive/readback을 새로 완료해야 한다. 세 브라우저 실행의 전체 46조합 양수
selected=passed·zero failure/error/skip/flaky/missing·`container_removed=true`·source
fingerprint 불변 및 한 번 실패 시 즉시 native 수리로 돌아가는 gate는 그대로다.
parent는 이번 native Make 프로세스를 terminal 장기 세션 수명과 분리해 실행한다.
이번 새 검토·검증·게시·완료 판정은 모두 오케스트레이터 책임이며 이 leaf에서는 미실행이다.

문서 영향은 ADR0030의 현재 인계·중단 이력 보완에 한정한다. architecture·harness·
harness-design·ADR index의 기존 설계 연결과 46조합·검증/전달 책임은 정확하므로 byte 그대로
보존한다. 아래 네 문서 metadata와 제공된 연구37 합계 1,571,781/1,572,864bytes는 유지하며
다른 연구 파일은 읽지 않았다. 기존 정책·실패 역사·AGENTS와 승인 밖 문서는 수정하지 않는다.
매 의미 검토는 이전 JSON을 재사용하지 않고 구체적 근거의 documentation을 반환해야 한다.

```json
{"documentation":{"status":"updated","files":["docs/adr/0030-item-detail-mobile-layout.md"],"reason":"승인 소스의 CSS-only 입력 열과 실제 ArrowRight·유한 wheel·엄격한 셀/Tab bounds 검사가 기존 설계와 일치함을 확인했다. parent 제공 직전 round2 review·3×46/46 및 downloader129/129 이후 Terminated·validation running·applied=[]·Git 미실행 이력을 추가하고 이번 새 gate와 분리했다. 정확한 네 경계 문서는 그대로 보존하며 새 full check·CI·완료 성공은 주장하지 않는다."}}
```

## 문맥

사용자는 아이템 상세를 모바일에서 읽고 조작하기 편하게 개선하고 구현·검증을 기존
native workflow로 계속하도록 직접 요청했다. improvement proposal 승인/execute가 아니다.
시작 기준은 검색 PR74가 병합된 master `dce6f27274de8de2310cc25c434413385179df17`이다.
읽기 승인은 개별 39파일이며 이 문서는 승인된 신규 파일이다. 연구 읽기 37파일 범위와는 다르다.

좁은 화면에서는 고정 폭과 나란한 열, 긴 다국어 이름·수치·링크, 넓은 능력치/재료 표가
body overflow나 잘림을 일으킬 수 있다. 핵심 값·열·섹션을 숨겨 폭을 맞추는 방법은 채택하지 않는다.
초기 문서 leaf는 애플리케이션 코드를 재조사하지 않았다. 보존된 이전 문서 인계는 승인된 상세
CSS/JS·상세 template·base block·theme focus 규칙과 manifest/config/spec을 실제로 읽었다고 기록한다.
이전 문서 leaf의 인계에는 승인된 상세 CSS·template·focus JS, theme 관련 규칙과 browser
명세·manifest/config를 읽었다는 기록이 있다. 직전 문서 수리 leaf는 배정된 다섯 문서만 읽었다.
이전 계획 단계에는 ADR0030이 없어 parent가 동일 마지막 checkpoint의 승인 초안을 복원해야 했다.
현재 작업 사본에는 ADR0030과 23×2=46을 설명하는 네 경계 문서가 있다. 이전 기록을 보존하며
이를 수정한다. 원본 checkpoint와의 일치는 parent가 확인하며 누락된 역사는 추측해 재작성하지 않는다.
이전 leaf는 상세 CSS·template과 browser 명세·manifest/config도 읽었다고 기록했다.
이번 문서 leaf는 승인된 다섯 문서만 읽고 새 실제 결과는 parent 제공 근거로 구분한다.
아래 이전 구현 관측은 역사로 보존하며 정적 소스 읽기는 최종 통합 diff의 의미 검토·실제 브라우저 통과를 뜻하지 않는다.
선택 섹션까지 포함한 최종 구현 일치 여부는 reviewer가 승인 소스로 확인해야 한다.

## 결정

상세 전용 `.item-detail` wrapper와 CSS로 영향을 한정하고 SSR의 읽기 순서를 유지한다.
제목·아이콘 뒤 주요 정보를 읽을 수 있게 배치하며 긴 이름·다국어·숫자·링크는 줄바꿈한다.
넓은 공간에서는 능력치와 계산기를 나란히 두고 좁아지면 쌓는다. 1440px의 정보 밀도와
390/320px의 가독성을 함께 요구하며 ellipsis·고정 높이 잘림·body 수평 스크롤로 해결하지 않는다.
이 세 폭은 검증 지점이며 실제 CSS 전환점을 임의로 뜻하지 않는다.

능력치·강화/초월·젬·재료·레시피·참조 등 넓은 표는 각 표 영역에서만 수평 스크롤한다.
표의 caption과 header/row 연관 의미를 유지하고 필수 열·값을 삭제하거나 `display:none`으로
숨기지 않는다. 각 영역에는 의미 있는 이름, 스크롤 안내, 키보드 진입과 보이는 focus를 제공한다.
긴 재료/아이템/스킬 링크에는 읽을 수 있는 줄바꿈과 모바일 조작 공간을 확보한다.
3D·market·collection·script 등 선택 정보도 실제 데이터가 있을 때 유지한다.

기존 강화·초월 입력에는 연결된 label/접근 가능한 이름과 숫자 입력 의미, 기존 기본값·범위·step을
보존한다. 모바일에서는 입력과 링크의 터치 영역·간격을 확보하고 겹침과 화면 이탈을 막는다.
현재 브라우저 명세는 입력에 최소 44×44px, 긴 재료 링크에 높이 44px를 요구한다.
키보드 focus는 입력뿐 아니라 표 스크롤 영역과 링크에서도 보이게 한다. 실제 `style.css`는
a/button focus outline을 `!important`로 제거한다. 상세 CSS는 더 구체적인 전용 focus 규칙의
`!important`로 3px outline·1px offset을 지정한다. 최종 computed outline이 가려지면 완료가 아니다.

계산식·기본값·상한·비용·재료·selector/id 연결은 기존 `item-enhancement.js` 계약을 보존한다.
현재 상세 계산기 명세는 별도 reset/단계 버튼을 전제하지 않고 숫자 입력의 ArrowUp과 0 입력으로
계산 및 초기화를 검증한다. 없는 버튼·게임 데이터를 새로 꾸미지 않는다. 560 무기/방어구,
550 장신구, 일반 장비, 젬/스킬젬의 값과 링크 및 번역·지역 동작을 보존한다.
importer/DB/schema/파서/게임 계산은 변경 목표가 아니다.

우선 반응형 HTML/CSS로 해결한다. 새 JS는 실제 조작상 필요에 한정하며 새 메뉴·SPA·API 전환은
범위 밖이다. 기본 HTML과 JS 비활성 상태에서도 설명·능력치·젬 표·재료/관련 스킬 링크를 읽고
이동할 수 있어야 한다. 필요한 섹션을 접을 경우에도 native 접근 가능한 disclosure와 실제 읽기
흐름을 보장해야 하며, 이번 수집 명세만으로 모든 선택 섹션의 검증을 주장하지 않는다.

## 비교 대안과 선택 이유

전체 페이지를 숨김 overflow로 자르거나 열/섹션을 제거하면 긴 텍스트와 핵심 수치를 읽을 수 없다.
전역 CSS 변경은 검색과 다른 화면으로 영향을 넓힌다. 전체를 카드/JS 렌더링으로 바꾸면 기존 표
의미와 SSR·JS 없는 탐색을 다시 구현해야 한다. 전용 wrapper·줄바꿈·열 쌓기·개별 표 스크롤은
기존 데이터와 계산 연결을 유지하면서 화면 크기에 대응하므로 선택한다.

## 실제 브라우저 수집 범위

현재 `manifest.json`은 기존 18개 이름과 `desktop`/`mobile` 두 project를 보존하고 아래 5개를
추가한다. 총 **23개 scenario × 2개 project = 46개 정확한 조합**이다. 320px project를 추가한
것이 아니다. 상세 5개는 desktop에서 1440×900, mobile 내부에서 390×844와 320×740를 순회한다.
기존 좁은 화면 검색 명세는 각 project에서 두 좁은 폭도 확인한다.

| 추가 scenario 이름 | 실제 페이지/고정 fixture에서 작성된 판별 |
| --- | --- |
| `detail headings and core content fit desktop and narrow viewports` | body/document 폭, 제목·아이콘·설명·긴 수치, 제목 뒤 정보 순서, desktop 열/모바일 쌓기, 560/550/일반/젬/스킬젬/공통 상세 |
| `detail tables retain semantics and scroll with the keyboard` | caption·영역 이름/안내·tabIndex·header scope·셀 가시성, 젬 16행과 음수 값, ArrowRight 영역 스크롤·마지막 값 노출 |
| `detail calculators support touch keyboard and reset values` | label·숫자 범위·step·inputmode·focus·touch, 강화/초월 수치·비용·재료 링크와 0 초기화 |
| `detail recipes collections and long links preserve navigation` | 긴 다국어 재료·레시피·수집품·참조·생산품·스킬 링크의 focus·Enter/click 탐색 |
| `detail without JavaScript retains core content and links` | JS 없는 별도 context에서 설명·기본 능력치·젬 표·재료·스킬 링크와 body 폭 |

명세는 실제 렌더링 text rectangle과 computed focus, DOM 의미와 링크 이동을 판별하며 CSS 문자열
존재만으로 통과시키지 않는다. 예시 수치/긴 이름은 고정 fixture이며 실제 게임 밸런스가 아니다.
상세 heading/table/calculator/recipe/no-JS 스크린샷은 실행 시 폭별로 남기도록 작성되어 있다.
선택 3D/market/script의 모든 데이터 형태나 실제 기기·전체 지역·Firefox/WebKit 검증은 이 46개
수집만으로 증명되지 않는다. 실제 구현 검토와 기존 지역 회귀의 책임을 대체하지 않는다.

`test_browser_runner.py`는 검색 9개, 기존 장비/PvP 9개, 상세 5개의 이름과 46개 조합을 요구한다.
`browser_runner.py`는 manifest 기반 정확한 조합을 판정한다. 이는 정적 소스 확인이며 unit/engine
검사를 실행한 결과가 아니다. config의 retries=0, 기존 timeout과 두 project는 유지한다.
누락·중복·skip·xfail·flaky·retry 성공을 정상 통과로 바꾸지 않는다.

## 검증·실패 복구·전달 책임

### 최신 실제 45/46과 마지막 열 도달 전제조건

parent 제공 `run1792911789416890414-ee1bb8`의 새 reviewer는 현재 CSS와 prototype 제거의
문서 일치를 승인했다. 그 뒤 최신 CSS-only 후보를 실제 Chromium로 실행한 결과는 **45/46**이다.
실패는 `mobile / detail calculators support touch keyboard and reset values`의
`detailTableAccess`, `equipment.spec.js:1045:103` 마지막 열 노출 검사다. 입력과 첫 header는
실패 목록에 없었으며 최종 실패 셀은 Chance의 thead TH와 tbody `TD#god_chance` 두 개다.

320px viewport의 5초 뒤 실제 진단은 scrollport x=[8,312], scrollLeft=40,
두 마지막 셀 x=[242.859375,323], header y=[319.125,363.3125], body y=[363.3125,425.3125]다.
hit target은 각각 실제 TH와 `TD#god_chance`였다. 이 위치에서는 오른쪽 11px가 영역 밖이며,
이 관측은 입력/header sticky 실패를 보고한 것이 아니다. 한 번의 ArrowRight가 마지막 열까지
이동한다는 전제를 먼저 수리한다. scrollWidth/clientWidth·최대 scroll은 제공되지 않았으므로
추정값을 기록하지 않는다. 이 실패만으로 CSS를 되돌리거나 focus prototype을 복원하지 않는다.

테스트 수리는 실제 ArrowRight를 유한하게 반복하거나 실제 사용자 wheel을 사용하고, 기본
web-first/expect.poll로 실제 scrollLeft 진행과 마지막 셀 rect를 관찰해야 한다. scrollWidth,
clientWidth와 최대 scroll, 실제 rect를 바탕으로 도달 종료 조건·무진행·최대 반복 보호를 둔다.
wheel 검사가 중간 위치로 되돌리면 마지막 열 전체 노출·pointer hit assertion 전에 다시 실제
사용자 스크롤로 해당 열에 도달한다. 중간 위치의 자연스러운 부분 가림을 도달 상태로 판정하지 않는다.
끝까지 이동해도 가림이나 pointer 접근 실패가 남으면 엄격한 기존 assertion은 계속 실패해야 한다.

입력/첫 header의 sticky 노출, 마지막 열의 rect·hit target, 더 오른쪽으로 실제 이동한 뒤의
scroll→Tab과 input/outline의 viewport·region 전체 bounds, 계산·초기화·재료 링크 검사는 유지한다.
scrollLeft=0/reset·scrollIntoView·click focus로 입력 잘림을 우회하거나 열/행을 숨기지 않는다.
bounds/tolerance·global/test/expect timeout을 넓히거나 assertion을 삭제하거나 sleep을 넣지 않는다.
실패 시 현재 rect·scrollLeft·scrollWidth/clientWidth·최대 scroll·hit target을 구조화된 진단에 남긴다.
23개 이름·두 project의 46조합과 누락/중복/skip/xfail/flaky/retry 거부도 유지한다.
이번 문서 기록은 테스트 수리 구현·통과를 선언하지 않는다. 수리 후 새 전체 검증은 parent 책임이며
직전 review 승인이나 이 실제 45/46을 새 성공으로 재사용하지 않는다.

### 이번 입력 열 배치 결정과 현재 소스 상태

parent 제공 이전 `run1792910397205875055-c942e5`는 원본 미반영 failed·`applied=[]`로 끝났다.
첫 Chromium은 45/46이며 mobile 표 노출 검사가 실패했다. 그 뒤 Django가 입력 열 여백을
보강하고 실패한 focus prototype과 상세 template의 로딩 연결을 제거했다. 당시 Claude는
제품 수리 방향을 적절하다고 판단했으나 이 ADR의 옛 수치·남은 JS 설명·미완료 인계 문구로
`changes_requested`를 냈고 max_rounds 소진으로 종료됐다. 첫 45/46은 그 수리 전 코드의
결과이며 최신 CSS의 실패 결과가 아니다. 당시 마지막 CSS·prototype 제거 후보의 actual Chromium,
full check·새 PR CI는 pending이었다. 이후 실제 CSS-only 45/46은 위 최신 기록으로 구분하며
full check·새 PR CI는 여전히 대기다. 아래 더 이전 실패·helper 시도는 역사로 보존한다.

parent 제공 이전 `run1792909166633835633-14db9f`는 상세에서만 로드하는 두 frame focus helper
보완 뒤에도 실제 45/46이었다. 실패는 같은 mobile 계산기 scenario이며, 추가 floor/ceil 좌표
보완도 같은 실패로 native `no_progress`/`failed`·`applied=[]`였다. helper와 반올림만으로는
최종 잘림을 해결하지 못했다. 이는 원래 baseline에 없던 신규 prototype이며 source/원문은
이전 private artifacts에 보존한다.
첫 실제 실패의 5초 최종 좌표는 viewport=[0,320], Anvil scrollport=[8,312], input=[-2,86]
(폭 88px), outline=[-6,90]이었다. focused/outlineVisible/scrollportPresent는 true지만
input/outline의 viewport/region 적합 네 flag는 false였다. trace DOM metadata에는 Anvil
region의 수평 위치 5/12/18/21/23도 기록됐다. 서로 다른 trace clock을 합쳐 이동 순서나
원인을 단정하지 않으며, 이 자료는 실제 가로 scroll→Tab 뒤 지속 잘림의 근거로만 사용한다.

이번 선택은 스크롤 좌표 보정보다 계산기 입력 열의 유효 폭·배치를 먼저 수리하는 것이다.
현재 승인 소스의 CSS는 575.98px 이하에서 `.item-detail-input-table`의 첫 header/입력 셀만 sticky로
두며, 해당 class는 상세 Anvil/Transcend 두 표에만 있다. 일반 정보·설명·레시피·참조·젬 표까지
sticky로 넓히지 않는다. 이 두 표에는 col/colgroup 고정 폭이나 입력 inline 폭이 없으며,
기존 별도 `enhancement.html`의 40px text 입력을 현재 상세 숫자 입력과 혼동하지 않는다.
모바일 표는 `table-layout:auto`, separate border·spacing 0을 쓰고 첫 셀의 border-box
width/min-width/max-width를 `--calculator-input-column`으로 맞춘다. 입력 폭은
`--calculator-input-width: max(88px, 5.5rem)`이며 열 폭은 그 입력 폭에 18px를 더한다.
최소 88px 입력과 좌우 8px padding·1px씩 테두리가 들어갈 최소 106px 열을 확보하고,
각 여백에 3px outline+1px offset 공간을 보존하는 배치다.
입력의 border-box·최소 높이 44px, 표 최소 폭 22rem·셀 최대 폭 24rem과 자동 열 계산이
실제로 충돌하지 않는지는 최종 rendered geometry로 판정한다. CSS 선언만으로 보장했다고 하지 않는다.

첫 열은 `left:4px`, 중앙 정렬·불투명 배경·오른쪽 경계 shadow를 두며 body 입력 셀은
z-index 2, header는 z-index 3과 별도 배경을 쓴다. 계산기 영역은 `isolation:isolate`를 쓴다.
영역 padding 4px와 계산기 전용 `scroll-padding-left:calc(var(--calculator-input-column) + 8px)`는
outline 여유와 고정 열 뒤 링크 노출을 위한 것이다. 나머지 열·재료 링크의 읽기와 누르기,
header/label/id·region 접근성·빈 영역 탭 제외·JS 없는 핵심 정보를 보존해야 한다.
모바일 전용 규칙이므로 1440px의 기존 정보 밀도를 유지한다. 최종 reviewer는 320/390px의
입력과 outline이 viewport·scrollport 양쪽에 모두 들어오는지와 고정 열 뒤 값/링크 접근을 확인한다.

현재 candidate에는 `TavernofSoul/static/js/item-detail.js`가 없고 상세 template의 로딩 연결도
제거됐다. `Items/index.html`은 상세 CSS와 기존 `item-enhancement.js` 계산 연결을 유지한다.
이번 배치는 CSS로 처리하며 새 focus JS나 prototype 로딩을 복원하지 않는다. 제품·테스트
인계와 이전 leaf의 승인 소스 읽기에서 입력 열 배치 및 prototype 제거를 확인했다. 이는 source 확인이다.
이후 위 새 reviewer 승인과 실제 45/46이 제공됐으며 이번 테스트 수리의 새 전체 diff 승인은 별도로 필요하다.
수집 계약은 23×2=46조합이다. 현재 명세는 strict `expect.poll`·실제 scroll→Tab·입력/outline
geometry·셀 노출/포인터 접근·값/링크·기존 검색 회귀를 유지하며 timeout/retry/runner gate도
완화하지 않는다. 마지막 표 노출 진단은 실패 cell rect·scrollLeft·hit target을 남긴다.
아래 helper 설명은 실패한 이전 수리의 역사이며 이번 배치의 성공 근거가 아니다.

### 확정된 지속 잘림과 이전 helper 수리

parent 제공 `run1792908184344523146-4d4ef5`는 actual Chromium 45/46이었다.
`mobile / detail calculators support touch keyboard and reset values`가 320px에서 표를
가로 스크롤한 뒤 실제 Tab으로 Anvil에 진입하는 경로에서 다시 실패했다. 위치는
`equipment.spec.js:1003:93`, 호출 `1175:17`이다. 기본 `expect.poll` 5초 동안 focus·URL·rect·
computed outline을 다시 읽었어도 최종 focused/outlineVisible/scrollportPresent=true,
URL=`/items/110`, inputInRegion/inputInViewport/outlineInRegion/outlineInViewport=false였다.
이 근거로 아래 초기의 ‘정착 중인지 미확정’ 가설은 해소됐다. 대기 방식만의 수리는 실패했으며
사용자 동작의 지속 잘림을 실제 제품에서 보완한다. 이전 left=-12 관측도 최초 실패와 함께 보존한다.

이전 prototype `item-detail.js`는 `.item-detail`의 `focusin`을 관찰했다. 이전 예약 frame을
취소하고 두 번의 `requestAnimationFrame`을 거쳐 browser 기본 focus scroll 이후 경계를 한 번
측정한다. 측정 직전에 control/wrapper의 연결·포함 관계와 실제 activeElement를 다시 확인한다.
가장 가까운 `.item-detail-table`의 client 경계에서 border/scrollbar와 좌우 padding을 고려하고
viewport와의 교집합을 구한다. control rect에는 자체 padding/border가 포함되며 computed
outline width+offset의 바깥 여유를 더해, 잘린 방향에 필요한 만큼 그 표의 `scrollLeft`만 조정한다.
이미 들어온 요소에는 이동하지 않고 표 영역 자체의 focus는 제외한다. 전역 scroll reset·임의 delay·
polling/scroll loop·focus 재지정·기본 링크/키 동작 취소는 없다.

당시 `Items/index.html`의 `script` block은 이 JS를 기존 계산 JS와 별도로 로드하고 base는 본문 뒤에
해당 block을 뒀다. 상세 CSS는 theme 뒤에 로드하며 표에 4px padding/scroll-padding을 뒀다.
prototype의 적용은 상세 wrapper 안에 한정했다. 계산식·값·ID/label·44px 입력·표/region 의미와
JS 없는 핵심 정보 보존 계약은 그대로다. 이 보완은 focus 시점의 가로 이동에 한정하며 세로
정렬이나 이후 수동 scroll/resize를 감시하지 않는다. 요소와 outline이 가용 폭보다 큰 경우의
완전 노출은 당시 구현만으로 보장하지 못했다. 현재 후보는 이 helper를 제거한 CSS 배치이며
입력의 실제 완전 노출은 parent의 새 검증이 필요하다.

### 이전 실패·진단 수리 이력

parent 제공 `run1792906677501253890-3be9a4`의 첫 Chromium은 45/46이며 mobile 계산기
scenario가 실패했다. 320px에서 body 폭 검사와 실제 Tab, Anvil focus/부분 viewport 검사는
통과했지만 이어 한 번 읽은 rect의 left=-12였다. 원본 JSON/trace/최초 실패를 보존한다.
당시에는 지속적인 배치 문제인지 native focus/scroll 정착 중인지 미확정이었다.
이후 위 5초 재실패로 지속 잘림이 확인됐으며 이 초기 가설을 현재 판단으로 재사용하지 않는다.

`visibleDetailFocus`는 기본 `expect.poll`로 매 시도 실제 focus·URL·rect·computed outline을
다시 읽는다. 입력과 outline(width+offset 포함)은 viewport와 표 region의 border/scrollbar를
제외한 client scrollport 양쪽에서 상하좌우 모두 들어와야 한다. 큰 region 자체의 세로 부분
노출은 입력 전체 노출과 구분한다. 실제 가로 스크롤 후 Tab과 Anvil/Transcend의 계산·초기화,
URL 보존을 유지한다. 강제 scroll/focus·click 우회·가짜 event·sleep·catch fallback·bounds 완화·
timeout 증가는 없다. 정착 후에도 잘리면 계속 실패하며 제품 보완 필요성은 실제 결과로 판단한다.

당시 추가 수리 진단은 이미 poll을 사용하는 helper의 `:1003` 실패 위치만 제공했고 실제 실패 호출·
rect·outline·scrollport 값과 unattributed 오류 내용은 없었다. 당시에는 기존 -12px와 같은 원인이라고
추정하지 않고 같은 엄격 조건을 보존하며 poll 실패 diff에 요소 id, viewport/표 영역,
입력/outline rect와 경계 좌표를 남겼다. 이는 진단 보강이며 잘림 해결이나 검증 성공을 뜻하지 않는다.
당시 parent에 실제 실패 호출과 마지막 좌표 snapshot, Django 최종 checkpoint·인계를 요청했다.
현재는 위 재실패와 승인 제품 소스를 근거로 수리 필요성을 확인했다.
새 Claude review는 유효한 `documentation={status,files,reason}`을 반환하고,
parent가 아래 동일 candidate의 새 Chromium 3회 및 후속 gate를 그대로 수행한다.

이전 coordinator 작업 사본에서는 상세 CSS는 읽었지만 enhancement template은 다른 owner의
checkpoint 복원 전 구조였고 승인된 `item-detail.js`는 없었다. 그 당시 사본의 부재 자체를
결함이나 JS 필요 근거로 해석하지 않았으며 당시 후속 사본에는 위 JS와 로딩 연결이 있었다.
현재는 Django의 마지막 checkpoint와 테스트가 복원된 소스 상태를 확인했다. parent는 그 문서
정정까지 포함한 동일 최종 candidate로 새 Claude 의미 검토와 전체 Chromium 3회 게이트를 수행한다.
당시 제품 수리의 검증은 미실행이었다. 이후 최신 CSS-only의 실제 45/46은 위에 별도로 기록했다.
어느 과거 45/46, 이전 검토 승인 또는 작성된 assertion도 이번 테스트 수리의 성공 증거로 재사용하지 않는다.

이전 수리 입력과 이번 task 3 수리 입력의 `check` 진단은 모두 `exception_type=unavailable`·`context=unavailable`·
`attribution=unattributed`뿐이다. 이 진단의 원인은 알 수 없으며 위 focus 실패나 임시 자료
제거 거부와 같은 원인으로 추정하지 않는다. 새 전체 diff 검토 뒤 원래 필수 검증을 모두
실행하는 책임은 parent에 남고, 이번 문서 보완은 제품 수리 완료·검증 성공 증거가 아니다.
이번 leaf는 배정된 다섯 문서와 그 개별 bytes만 읽었다. 현재 사본에는 ADR0030과 46조합의
경계 문서가 있으므로 부재를 현재 결함으로 보고하지 않는다. 원본 baseline·retained checkpoint·
최종 통합 diff와의 동일성은 확인하지 않았으며 parent의 복원 확인과 fresh review가 필요하다.

기존 검색 SSR/fragment·JS 없는 GET과 native navigation 계약을 유지한다. 각 variant는 새 isolated
context의 첫 요청부터 감시한다. Control-click은 trusted event의 `defaultPrevented=false`, 정상
document 요청·fragment 없음·원래 화면 보존을 요구하며 background Page를 필수 await하지 않는다.
별도 `_blank`는 새 Page의 완전한 DOM을 확인한다. 과거 request.frame/opener/최초 response.body/
lifecycle wait 가정을 되살리지 않으며 기존 실패 이력은 보존한다.

parent는 새 실제 모델 구현과 fresh Claude의 최종 전체 diff·문서 의미 검토 및 유효 documentation JSON 뒤
매회 새 컨테이너에서 실제 `check-browser-container`를 3회 연속 실행한다. 현재 manifest 전체는
46조합이며, 추가 시에도 전체 46개 이상에서 양수인 selected=passed와
zero failure/error/skip/flaky/missing, `container_removed=true`, source fingerprint
불변이어야 원래 기본 `GIT=1` 전체 `make check`로 진행한다. 한 번이라도 실패하면 즉시 실제
실패를 근거로 native 최소 수리로 돌아가며 과거 보고서나 합성 결과로 대신하지 않는다.

원본 전체 baseline의 충돌·bytes·mode·존재 확인과 scoped apply, 기존 Git 역할은 유지한다.
parent는 직전 run의 원본 미반영 소스·실제 실패·review·진단을 보존하고 terminal no-apply와
baseline 전체 bytes·mode·존재·목록 및 retained checkpoint 일치를 확인한 뒤 source-only로 native
owner 복원한다. 모든 39파일은 native owner대로 정확히 한 번 배정한다. parent 제공 더 이전 run은
45/46 뒤 제품 수리 없이 중복 검사를 중단했고, owned non-credential temporary의 안전한 제거가
거부되어 native report는 failed·`applied=[]`였다. 브라우저 컨테이너 제거와 원본 Git tree clean은
제공된 과거 상태다. 제거되지 않은 이전 임시는 보존하며 원인을 추정하거나 임의 rmtree하지 않는다.
복원 후보는 baseline repository instructions를 유지하고 이전 prototype의 AGENTS 작업 메모
974bytes를 복원하지 않는다. AGENTS에는 이번 작업 이력·정책 변경을 덧붙이지 않는다.
parent의 GitHub 앱 게시·필수 CI 3종 실제 success·squash merge·cleanup·archive/readback까지가
후속 책임이다. 모델/provider/auth/storage/비용/스케줄/승인 정책은 변경하지 않는다.
worker/reviewer는 검사·실모델·네트워크·Git/SSH·workflow·재위임을 실행하지 않는다.

**이 문서 작업에서는 검증·CI·merge가 모두 미실행이다.** 기존 PR74의 local 5882/5882,
Chromium 3×36, CI3 success/merge/cleanup/archive는 과거 완료 증거이며 이번 변경의 새 성공이 아니다.
매 review는 `documentation={status,files,reason}`으로 실제 의미적 완전성을 판단한다.
이번 문서 정정은 현재 제품 계약과 실패 이력·pending 검증의 구분을 맞춘다. 다음 review는
최종 전체 diff를 새로 읽고 documentation을 독립적으로 판단한다. Markdown 파일 존재나
이전 `updated` 판단만으로 문서 완전성을 증명하지 않는다.

## 문서 byte 예산과 남은 인계

연구 37파일의 개별 128KiB·총 1.5MiB 상한은 변경하지 않는다. 제공된 시작 합계는
1,570,952bytes, 한도 1,572,864bytes, 여유 1,912bytes다. 이전 복원의 문서 metadata는 다음과 같다.

| 연구 범위 문서 | 시작 bytes | 편집 후 bytes | 상한 bytes | 증가 |
| --- | ---: | ---: | ---: | ---: |
| `docs/architecture.md` | 86252 | 86379 | 86452 | 127 |
| `docs/harness.md` | 128934 | 129333 | 129434 | 399 |
| `docs/harness-design.md` | 77603 | 77763 | 77803 | 160 |
| `docs/adr/README.md` | 35025 | 35168 | 35225 | 143 |

이 네 문서의 이전 순증은 829bytes다. 현재 복원 후보의 제공된 연구37 합계는 1,571,781bytes,
잔여는 1,083bytes다. 이번 leaf의 metadata 읽기에서도 위 네 문서 bytes는 편집 후 열과 같으며
네 문서는 수정하지 않는다. 다른 연구 파일은 합산하지 않았으므로 최종 전체 합계·목록·mode와
개별 상한의 검증은 parent 책임이다. ADR0030은 개발 승인 안에
있지만 연구 37파일 밖이므로 상세 설명을 이곳에 둔다. 기존 정책·실패·역사 문단을 지워 공간을
만들지 않는다.

이 승인 범위 안에서 관련 경계 문서를 연결했으며 현재 `docs/workflow.md` 수정이 필수라는
근거는 없다. 해당 문서를 열거나 생성하지 않았다. reviewer가 그 문서의 실제 절차 변경 필요를
확인하면 `docs/harness-design.md`에 귀속한 finding에 정확한 누락 경로 `docs/workflow.md`와
이유를 남기고 parent가 범위를 확인하여 새 run을 준비해야 한다. 수리 round는 승인을 넓히지 않는다.

최종 reviewer는 승인된 통합 소스의 selector/id·계산·선택 섹션 보존을 확인하고 parent는 위
엄격한 가로 스크롤→Tab 경로와 입력/outline의 viewport·scrollport 양쪽 완전 노출 조건을 유지한다.
false flag 무시·bounds/tolerance 완화·테스트의 scrollLeft=0/scrollIntoView/click focus 강제 정렬로
제품 결함을 대신 해결하지 않는다. 기존 검색 native navigation을 다시 수정할 근거도 아니다.
현재 46개 전체 회귀와 JS 없는 GET을 보존하며 이번 도달 전제조건 수리 후 새 검증 결과는 아직 없다.
이번 문서 worker의 영향 판단은 다음과 같다. 새 reviewer의 승인 판단을 대신하지 않는다.

```json
{"documentation":{"status":"updated","files":["docs/adr/0030-item-detail-mobile-layout.md"],"reason":"복원된 CSS·prototype 제거 설명과 이전 실패·review 이력을 보존하고 최신 CSS-only 실제 45/46 및 11px 부분 가림을 별도 기록했다. 실제 사용자 스크롤의 마지막 열 도달 전제조건과 엄격한 노출·Tab 검증, 새 review·Chromium 3회·full check·CI 이후 전달 책임을 명시했다. 네 경계 문서는 23×2=46 및 기존 책임과 일치해 유지하며 수리 구현·검증 성공은 주장하지 않는다."}}
```

추가 승인 밖 문서가 반드시 필요한 근거는 현재 없다. 매 review의 독립적인 의미 판단은 남는다.

## 관련 코드·검증·문서

- 경계: [architecture](../architecture.md), [harness-design](../harness-design.md),
  [실행·수집 범위](../harness.md#실제-브라우저-검증), [ADR index](README.md).
- 수집 근거: [manifest](../../harness/browser/manifest.json),
  [project/config](../../harness/browser/playwright.config.js),
  [실제 브라우저 명세](../../harness/browser/equipment.spec.js),
  [결과 판정](../../harness/browser_runner.py), [판정 회귀](../../harness/test_browser_runner.py).
- 구현/review 참조: [상세 template](../../TavernofSoul/templates/Items/index.html),
  [상세 CSS](../../TavernofSoul/static/css/item-detail.css),
  [기존 theme](../../TavernofSoul/static/css/style.css),
  [기존 계산 JS](../../TavernofSoul/static/js/item-enhancement.js).
- 실패한 focus prototype: `TavernofSoul/static/js/item-detail.js`와 당시 로딩 연결은 위 역사에
  기록한다. source/원문은 이전 private artifacts에 보존하며 현재 제품 파일의 존재를 전제하지 않는다.
