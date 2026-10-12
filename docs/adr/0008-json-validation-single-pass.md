# 0008. 모든 JSON 파일의 엄격한 검사 뒤 중복 finite_tree만 제거

- 상태: 승인(accepted)
- 기록일: 2026-10-12
- 기록 성격: 새 결정; 승인 상태는 검사 실행·통과나 게시 완료를 뜻하지 않음
- 대체 관계: 없음

## 문맥

`load_release`는 릴리스의 모든 `*.json`을 엄격한 `load_json`으로 읽는다.
각 파일의 디코딩·루트 검사와 `finite_tree`가 끝난 후 공개 `validate_release`를 호출하면
보관한 컬렉션 전체에 같은 유한성 검사가 다시 수행된다.
한편 공개 API는 파일 로더를 거치지 않은 독립 메모리 입력도 받으므로 전체 검사가 필요하다.
직렬화 전 메모리와 기록 후 staging은 별개 입력이며 두 경계의 검사는 모두 필요하다.
검증 비용을 줄이면서 보조·선택·version 파일과 mutation/retry의 엄격함을 유지해야 한다.

## 결정

공개 `validate_release(data, require_version=True)`는 private `_validate_release_structure`,
`finite_tree(data, 'release')`, private `_validate_release_domain` 순서로 검사한다.
구조 함수는 릴리스 객체·필수 컬렉션·version을, 도메인 함수는 기존 필드·타입·범위·유일성·참조와
선택적 계약을 담당한다. 도메인 수치의 유한성 검사도 유지한다.

`load_release`는 필수 파일 존재 확인 뒤 정렬한 모든 `*.json`을 각각 `load_json`으로 읽는다.
도메인 검사에 보관하지 않는 보조·확장 파일도 문법·중복 키·NaN/±Infinity·`1e999` 오버플로·
객체/배열 루트·전체 유한성을 검사한다. 선택적 강화·진단 컬렉션과 제공된 version도 검사한다.
이후 보관한 데이터에 같은 private 구조·도메인 검사를 수행한다.
파일별 검사가 완료된 이 경로에서만 마지막 `finite_tree(..., 'release')` 재순회를 생략한다.
공개 API에 임의 우회 flag를 추가하지 않는다.

검사 완료의 근거는 한 `load_release` 호출에서 새로 디코딩한 값에만 유효하다.
스냅샷을 변경하거나 캐시하지 않으며, 다음 호출은 파일을 새로 열고 검사한다.
공개 메모리 API도 보조 필드와 중첩·공유 객체를 매번 검사해 이전 성공 후 mutation을 검출한다.
기존 오류 path·code·message·첫 오류 순서와 입력·alias 보존을 유지한다.
`require_version=False`는 부재만 허용하며 제공된 version의 계약과 필수 데이터 컬렉션은 계속 검사한다.

## 비교 대안

| 대안 | 비용과 판단 |
| --- | --- |
| 파일별 검사 뒤 공개 API로 전체 재순회 | 같은 정책을 유지하지만 이미 확인한 값 전체를 다시 걷는 비용이 남음 |
| 공개 `skip_finite` 등 우회 flag | 호출자가 독립 메모리·수정된 객체에도 검사 완료를 주장할 수 있어 책임 경계가 불명확해짐 |
| 도메인에 보관할 파일만 엄격히 검사 | 보조·선택·확장·version의 손상을 놓칠 수 있어 기존 모든 파일 정책을 약화함 |
| 경로·객체 identity 기반 검증 결과 캐시 | 파일 교체·중첩 mutation·재시도·지역 전환의 무효화 규칙과 장기 상태가 필요하며 오래된 성공을 재사용할 위험이 생김 |
| 메모리 검사 또는 staging 검사 제거 | 직렬화 전 잘못된 값 또는 기록한 스냅샷 손상을 놓치므로 두 입력 경계의 보장을 약화함 |
| private 구조·도메인 함수 분리 | 내부 호출 순서를 관리해야 하지만 새 공개 우회 정책·캐시 없이 확인된 중복 순회만 제거함; 채택 |

## 선택 이유

모든 파일은 같은 호출에서 엄격하게 디코딩되어 전체 유한성이 확인된다.
따라서 그 결과에 대한 마지막 전체 순회만 생략할 수 있으며 도메인 검사 정책은 공유한다.
독립 메모리 입력은 이 전제가 없으므로 공개 API의 전체 검사를 유지한다.
이 책임 분리는 성능 후보를 적용하면서도 파일 검사와 메모리 검사의 권한을 호출자에게 넘기지 않는다.

## 결과·비용·제약

정상 파일 로드의 전체 유한성 순회 횟수는 JSON 파일당 한 번이다.
정상 export는 별도의 메모리 전체 검사 한 번과 staging 파일별 검사 한 번씩을 유지한다.
모든 도메인 순회를 없애거나 메모리 검사의 결과로 staging을 신뢰하는 결정이 아니다.
private 함수는 앞선 검사 전제를 지켜 사용해야 하며 회귀 명세로 두 진입 경계를 함께 다룬다.

memory-before-write, staged-before-promotion, 백업 copy·승급 전 sentinel·파일별 교체와
이전 파일 복원·신규 파일 제거·불완전 롤백의 백업 보존 정책은 유지한다.
전체 성공·완전한 롤백 후 정리와 다음 실행의 비어 있지 않은 backup 중단도 유지한다.
version payload는 같은 승급·롤백 대상이며 별도 parser_version.csv의 불일치 재시도 정책을 바꾸지 않는다.
교체 중 독자의 혼합 버전 관찰과 정전 수준 내구성 한계는 그대로다.
importer의 복사 스냅샷 검사·DB 쿼리 전 실패·트랜잭션/prev 복원 책임도 유지한다.

이 결정은 model/provider/effort/network/worker 설정이나 기본 Git 역할을 변경하지 않는다.
검토·필수 검증과 GitHub CI 성공 확인 뒤 SHA를 고정해 merge하는 게시 흐름도 유지한다.

## 진단 근거와 검증 상태

다음은 메인이 제공한 prototype/local diagnostic 후보 사실이다.
원본·진단 스크립트·상세 logs는 이 문서 작업자에게 제공되지 않았고 독립 재측정하지 않았다.

| 후보 | 제공된 로컬 진단 |
| --- | --- |
| XML prototype의 skill_bytool 단계 | kTOS 4.65→1.36s, iTOS 9.28→4.52s, jTOS 8.42→4.41s; output bytes 동일, 기존 XML 185테스트 통과 관측 |
| load_release 중복 전체 순회 | kTOS 41파일에서 finite_tree 42회(load_json 41 + validate_release 1); profiler 없는 마지막 재순회 1.60s, 한 표본 |
| synthetic skill cleanup | shared by_name 사례 약 1.08→0.002s |
| 맵 디렉터리 인덱스 반복 구성 | directory 항목 959~961개·550 map의 반복 구성 약 0.32s |

이 수치는 측정 범위·입력·조건이 다른 부분 진단이다. 합산해 누적 개선율로 환산하지 않으며,
기존 XML 테스트 통과 관측을 최종 구현 회귀·전체 파서·CI 성공으로 기록하지 않는다.
문서 작업자는 테스트·benchmark·전체 make check·운영 파이프라인·Git·workflow를 실행하지 않았다.
최종 소스의 지역별 전체 실데이터 검증과 여태 적용한 최적화의 누적 성능 비교는 메인 `/root`가
별도로 수행한다. 검사·게시 완료는 해당 담당자의 실제 결과 확인 전까지 주장하지 않는다.

## 관련 코드·검증·문서

- [공통 JSON 계약](../../TavernofSoul/ipfparser/contracts.py), [export 경계](../../parser_tidy/DB.py).
- [release 회귀 명세](../../parser_tidy/tests/test_release_contract.py): 파일별 순회 횟수·독립 메모리 mutation·엄격한 모든 파일 역할·정확한 도메인 오류·version·수정 후 재시도.
- [atomic release 회귀 명세](../../parser_tidy/tests/test_atomic_release.py): 기존 백업·sentinel·승급·롤백·복구 정책의 유지 대상.
- [XML](../../parser_tidy/game_xml.py)과 [회귀 명세](../../parser_tidy/tests/test_game_xml.py), [skill cleanup](../../parser_tidy/skills.py)과 [독립 기대값](../../parser_tidy/tests/test_combat_source_fixture.py), [map lazy index](../../parser_tidy/maps.py)와 [독립 기대값](../../parser_tidy/tests/test_world_source_fixture.py): 함께 적용한 최적화의 별개 경계이며 이 ADR의 JSON 결정과 진단을 구분한다.
- [architecture](../architecture.md), [data-contracts](../data-contracts.md), [ADR 목록](README.md).

이 링크와 명세 설명은 문서·구현의 의미 검토이며 실제 검사 실행 결과를 뜻하지 않는다.
