# 여신 장비·젬 원본 fixture

`prepare_equipment_workspace`가 regional 샘플 위에 이 디렉터리의 CSV IES·XML·Lua를 덧붙인다.
원본과 `expected_equipment.json`은 직접 작성했다. 운영 파서 출력이나 실제 게임 수치에서 생성한 샘플이 아니다.
5개 지역에서 같은 선택 경로를 실행하며 기존 11개 아이템에 550 목걸이·일반 젬·스킬 젬을 추가한다.

## 등록과 Lua 경계

강화 파일은 `ToS_DB.EQUIPMENT_REINFORCE_IES`의 명시적 목록과 현재 지역 `file_dict`를 함께 사용한다.
560 등록을 추가했고 Lua의 `GetClassByType`에도 등록된 강화 테이블을 제공한다.
550은 장신구 전용 5열, 560은 무기·방어구의 8열 입력이다.
샘플 강화 행은 30개이며 560 첫 행은 BasicAtk 7000·BasicDef 9000·AddAtk 100이다.
실제 Lua 조회로 검 최소/최대 7000/7100, 갑옷 물리/마법 방어력 9000/4500을 얻는다.
550 목걸이의 BasicAccAtk 3300은 JSON 정수로 변환해 세 공격력 필드에 적용한다.
여신 장비의 초월 비용 샘플은 `[3,6,…,33]`이다.

fixture의 580 파일은 미등록 입력 감지용이다. 파서는 경고와
`goddess_reinf_unregistered.json`의 파일명→레벨 진단을 남기며 자동 등록하지 않는다.
실제 unpack에도 더 높은 레벨 파일이 있을 수 있으므로 파일 존재만으로 지원 범위나 만렙을 정하지 않는다.

560 재료는 `armor`·`weapon`, 550 재료는 `acc` 그룹만 만든다.
560 IES가 없는 지역에서는 560 재료 함수 호출과 그룹 생성을 생략한다.
등록을 제거한 파일도 호출하지 않으며 미등록 진단에 남긴다.
560의 필수 함수 누락·빈 계산 결과·음수/소수/비유한 수량은 공개 전에 실패한다.
기존 550 이하의 Lua 함수 부재 호환 정책은 유지한다.

샘플 Lua에서 1~5 단계는 무료이고 6~30 단계에 원석·먼지가 필요하다.
560 무기 6단계는 원석 36·먼지 12, 방어구는 18·6, 550 장신구는 12·7이다.
이는 테스트용 계산이다. 실제 게임의 낮은 단계에도 다른 재료가 필요할 수 있다.
JSON에서 레벨·단계 dict 키는 문자열이 되며 550/560의 지원하지 않는 그룹은 키를 생략한다.

## 젬 XML과 ORM

`item_gem.ies`는 일반 젬 230과 `Gem_Harness_Fire` 스킬 젬 240을 담는다.
socket XML은 레벨 0 제외, 1·2 레벨의 양수 보너스와 음수 페널티,
MainOrSubWeapon/HandOrFoot 슬롯 분리를 검사한다.
JSON은 기존 슬롯 배열을 유지하며 각 값에 원본 Level을 추가한다.
스킬 젬 설명의 OptDesc 접두를 제거하고 원본 ClassName으로 스킬 ID 400을 연결한다.

importer는 `item_type.GEMS`의 실제 `Gems` 행과 socket_bonuses JSON 문자열을 스킬 적재 후 생성·갱신한다.
Link_Skill은 ID 참조이며 없거나 null이면 연결하지 않는다.
공통 계약은 참조 오류와 다른 ORM 유형 그룹과의 중복을 DB 쿼리 전에 차단한다.
재적재는 사라진 Gems 행을 복구하고, 분류 제거는 기본 Items를 유지하며 subtype만 제거한다.
스킬 변경·연결 해제·원본 젬 삭제·늦은 적재 오류의 DB/Version/prev 롤백도 검사한다.

## 실행과 coverage

- `test_equipment_source_fixture.py`: 실제 파서·Lua·CSV/XML·출력, 반복 실행·지역 전환과 실패 후 재시도.
- `harness/equipment_tests.py`: 5개 지역 각각 실제 importer·ORM·검색·상세, 재계산·관계 갱신·삭제·보존.
- 실행: 루트에서 `make check`; 같은 통합 테스트는 `make check-mysql-container`에도 포함한다.

560/550 장비·강화 테이블/재료·젬 스킬 FK와 레벨/슬롯별 보너스를 ORM·HTTP까지 검사한다.
미등록 진단은 보조 JSON으로 유지한다. fixture의 Lua 강화 함수는 IES 증가값을 누적하여
무기 100~3000, 방어구 200~6000, 장신구 80~2400을 계산한다.
Trinket은 0.3 배율, UseLv와 ItemLv가 다른 경우도 별도 검사한다.
누적값은 장비 필드에, 확률/원본 행/재료는 GoddessReinforcement의 레벨·단계 행에 저장한다.
1~5단계 빈 재료 객체와 그룹/단계 누락을 구분한다. 460의 기존 armor wrapper는 공유 비용으로 적재한다.
소켓 배열에서 레벨을 제거하면 DB/화면에서도 제거하며 이전 JSON의 Level 누락은 추측하지 않는다.

화면의 고정 여신 배열을 제거하고 실제 HTTP JSON과 컨트롤 ID로 배포 JavaScript를 Node.js에서 실행한다.
하네스의 DOM 어댑터는 입력 이벤트·계산·텍스트·재료 링크 검증용이며 실제 브라우저 엔진은 아니다.
예: +6 검은 7600~7700, 갑옷 PDEF 10200, 장신구 MATK 3780, 성공 확률 98%다.
단계별 비용은 원본 Lua 재료 출력을 사용하며 반복 적재·변경·제거·실제 DB 제약 실패 롤백을 검사한다.
기존 초월 비율은 유지하고 진화·착용/세트 조건별 효과·방어구 공격력 전환은 제외한다.
이미지 생성·전체 main.py·모든 운영 Lua·실제 브라우저 레이아웃은 검증하지 않는다.

구축 시 추가 확인한 `logs/harness/equipment-live-probe.json`은 로컬 iTOS·kTOS의 실제 560 CSV와
무기/방어구/장신구/기타 재료 함수 본문만 읽어서 실행한 결과다. 원본 파일 hash도 기록했다.
전체 Lua 초기화·전체 파서 빌드·기존 실데이터 회귀 테스트는 실행하지 않았다.
이 확인은 로컬 데이터에 의존하므로 기본 하네스와 CI에 포함하지 않는다.
별도의 `logs/harness/reinforcement-live-probe.json`은 실제 iTOS/kTOS의 550/560 테이블과
IS_WEAPON_TYPE·SCR_GET_GODDESS_REINFORCE 함수 본문으로 새 파서 헬퍼의 누적값을 확인한다.
검·트링킷·갑옷·방패·목걸이·반지의 +6/+30을 포함하며 전체 Lua 초기화/빌드/적재 검증은 아니다.
