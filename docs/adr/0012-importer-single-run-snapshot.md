# 0012. 한 importer 호출이 소유하는 검증 스냅샷과 SELECT 인덱스

- 상태: 제안(proposed), 작업 승인은 있으나 최종 소스의 새 실제 검토·전체 검증·게시 대기
- 기록일: 2026-10-14
- 기록 성격: 새 구현 결정; 제공된 후보 진단과 최종 실행 증거를 구분함
- 대체 관계: 없음. [0008](0008-json-validation-single-pass.md)의 엄격한 파일/메모리 검사 경계를 확장하며 대체하지 않는다.

## 문맥

importer는 공개 JSON을 private staging에 복사해 DB 쿼리 전에 검사한다.
그 뒤 같은 현재 컬렉션을 다시 디코딩하고 스킬·직업을 행마다 조회하는 비용이 남는다.
그러나 importer 소비자는 JSON 배열 등을 수정하므로 검증 값을 그대로 공유하면 다른 소비자와
비교 기준에 mutation이 전파된다. 경로나 이전 성공에 묶인 캐시는 파일 교체·실패·재시도에
오래된 입력을 사용할 수 있다. 읽기 최적화는 기존 오류 순서와 행별 쓰기 의미를 유지해야 한다.

## 결정

`load_release(directory, require_version=True)`는 기존 version payload 또는 `None`을 반환한다.
새 `load_import_snapshot`은 같은 private `_load_release_data`를 사용해 필수 파일 존재를
기존 순서로 확인하고 정렬한 **모든** `*.json`을 `load_json`으로 엄격히 읽는다.
문법·중복 키·NaN/Infinity·지수 overflow·객체/배열 루트·전체 유한성 검사를 유지한다.
이어 보관한 값의 구조·도메인 검사로 필드·타입·범위·유일성·참조·선택적 진단 계약을 확인한다.
보조·확장 파일도 엄격히 읽고 진단 컬렉션도 검사한 후 반환값에서 제외한다.
`ContractError`의 path/code/message와 첫 오류 순서를 바꾸지 않는다.

반환값은 `REQUIRED_COLLECTIONS + REINFORCEMENT_COLLECTIONS + ('version',)` 중
실제로 제공된 importer 소비 값만 보관한다. 검사 범위를 반환값의 범위로 축소하지 않는다.
이는 검사 완료 후 snapshot의 보관 경계다. 도메인 검사를 위해 진단 컬렉션을 일시 보관하는
책임은 남으므로 모든 파일 검사 중 최대 메모리 사용량의 감소나 상한을 보장하지 않는다.
`require_version=False`는 version 부재만 허용하며 제공된 version은 계속 검사한다.
공개 `validate_release`는 독립 메모리 입력의 구조 → 전체 `finite_tree` → 도메인 순서를
유지하며 이전 파일 검사의 성공으로 우회하지 않는다.

스냅샷은 한 `handle`의 private staging에만 연결된다. `importJSON`은 활성 handle의
현재 base와 파일의 디렉터리가 그 staging이고 소비 컬렉션일 때만 값을 재사용하며
매번 `deepcopy`를 반환한다. version 소비자도 복사본을 받는다. 직접 호출, `prev/`,
다른 경로와 보관하지 않은 파일은 매번 새 `load_json`으로 읽고 검사한다.
원본/staging/prev bytes는 보정하지 않는다. 재검사 시작 전에 이전 스냅샷을 버리고,
성공·실패·재시도 경계에서 `_staged_snapshot`, `_snapshot_path`, `_previous_path`와
행 인덱스·스킬 이름·관계 재조정 상태를 정리하며 원래 base를 복원한다.
검증 실패는 DB 쿼리 전에 중단한다. DB 트랜잭션과 기존 prev 공개/복원 책임은 유지한다.

스킬과 직업은 필요한 canonical ID의 `str` 키로 호출 내 SELECT 인덱스를 만든다.
없는 스킬의 생성, 기존 스킬의 `update=0` skip, `Link_Job=None` 처리와 기존 삭제 목록
구성을 유지한다. 특히 `update=0`의 기존 skip·삭제 상호작용을 새 정책으로 바꾸지 않는다.
중복 legacy ID는 임의 행을 선택하지 않고 원래 소비 지점의 `get()`으로
`MultipleObjectsReturned`를 발생시킨다. 누락 직업도 원래 `get()`의 `DoesNotExist`를
유지하고 DB 조회 오류를 누락으로 숨기지 않는다.
기존 루프 순서·행별 `save()`·created/updated audit 의미·INSERT/UPDATE/DELETE 수를 유지한다.
동일한 값의 save를 생략하거나 bulk write로 바꾸지 않는다.

아이템 분류는 함수 안의 membership set만 만들고 호출자의 그룹 목록·행 순서·분류 우선순위와
누락 그룹의 기존 오류를 보존한다. Recipe canonical ID와 기존 item 분류 의미도 유지한다.
전역 캐시나 호출/지역 사이의 인덱스 공유는 없다. `parser_tidy/items.py`와 `luautil.py`는
이번 importer/cleanup 수리에서 변경하지 않는다. 느려진 장비 Lua batching은 제외한다.

## 비교 대안

| 대안 | 비용·판단 |
| --- | --- |
| 검증 뒤 현재 JSON을 매 소비 시 다시 디코딩 | 입력 격리는 단순하나 같은 staging 읽기가 반복됨 |
| 경로/mtime/전역 캐시 | 교체·재시도·지역 전환 무효화와 오래된 성공 문제가 생겨 제외 |
| 검증 객체를 소비자에게 그대로 반환 | mutable 소비자의 변경이 다른 소비자에 전파되어 제외 |
| 소비 파일만 검사 | 진단·보조·확장 파일과 첫 오류 계약을 약화하여 제외 |
| bulk write 또는 동일 save 생략 | signal·audit·행별 오류/쓰기 의미가 달라져 제외 |
| 호출 소유 스냅샷 + 소비자 복사 + SELECT 인덱스 | 복사·메모리 비용은 남지만 기존 검증과 쓰기 계약을 유지하여 선택 |

## 선택 이유

검증한 private staging 값의 수명과 소유자를 한 호출로 제한하면 반복 디코딩을 줄이면서
외부 입력의 새 검사와 mutable 소비자의 격리를 함께 유지할 수 있다.
SELECT membership만 최적화하면 ORM의 기존 쓰기와 예외 책임을 보존할 수 있다.

## 결과·비용·제약과 검증 상태

소비 컬렉션은 handle 동안 메모리에 남고 deepcopy 비용은 유지된다. private staging의
활성 호출 소유가 전제이며 임의 외부 파일 변경을 감시하는 캐시가 아니다.
프로세스 종료·정전 수준의 DB/파일 전체 원자성은 새로 보장하지 않는다.

메인이 제공한 **후보 근거**는 isolated importer 3회에서 첫 실행 wall 31.7%, 반복 실행
48.1% 감소, 반복 SELECT 1604→100, 33개 테이블의 자동 audit timestamp 외 값 동등성,
정확한 prev bytes와 INSERT/UPDATE/DELETE 수의 불변이다.
별도 fresh isolated kTOS/iTOS/jTOS `main`의 지역별 41개 JSON bytes도 baseline과 같았다.
2691개 selected parser/harness tests의 zero-skip 통과는 부분 검사 기록이다.
이 수치를 합산하거나 최종 소스·full workflow·전체 `make check` 통과로 확대하지 않는다.
이전 full workflow는 NFS RPC 대기 중 timeout했고 old parent `shutil.rmtree`는 readonly
keep에서 실패했다. 이후 cleanup도 매우 느렸다. NFS statvfs probe 회복은 메인의 제공된
관측이며 이 worker가 재확인한 실행 결과나 최종 검증 성공이 아니다.

새 실제 review, orchestrator의 전체 `make check`, 승인 31파일 범위 반영과 기본 Git 역할,
메인의 최종 소스 비교·정확한 GitHub 앱 journal·실제 CI 3개 success·merge·cleanup은 대기다.
기존 NFS 설정·mount·floor와 모든 역할/provider/model(GLM 포함)은 유지한다.
worker는 검사·Git·운영 import·다른 모델을 실행하지 않았다.

## 관련 코드·검증·문서

- [contracts.py](../../TavernofSoul/ipfparser/contracts.py), [importAll.py](../../TavernofSoul/ipfparser/management/commands/importAll.py): API와 staging/ORM 소유 경계.
- [test_release_contract.py](../../parser_tidy/tests/test_release_contract.py), [test_import_safety.py](../../parser_tidy/tests/test_import_safety.py), [contract_tests.py](../../harness/contract_tests.py): 엄격한 오류/순서, consumed-only·복사·fresh direct/prev·mutation/retry·state cleanup, 실제 ORM save/audit/삭제 및 missing/ambiguous 참조의 검증 대상. 명세 존재는 통과 증거가 아니다.
- [architecture](../architecture.md), [data-contracts](../data-contracts.md), [harness](../harness.md), [workflow](../workflow.md): 설계·회귀·최종 인계.
- [0013](0013-owned-validation-temporary-cleanup.md): 별개인 하네스 임시 tree 정리; importer의 prev 롤백 정책을 대체하지 않는다.
