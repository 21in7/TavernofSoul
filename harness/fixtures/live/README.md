# 실제 게임 원본 샘플

2026-10-08 로컬 iTOS·kTOS unpack에서 선택한 560 소드·트링킷·실드·천 상의,
550 네클리스·브레이슬릿, 레드 젬·에너지 볼트 젬과 강화 재료다.
`manifest.json`은 unpack Git commit, 원본 파일 SHA-256, 선택 CSV 행 ID,
샘플 SHA-256을 기록한다. Lua 6개와 강화·등급·공유 상수 테이블은 원문 전체를 사용한다.
번역과 젬 XML은 선택 항목으로 줄였다. 모델 테이블은 원본 헤더만 포함한다.

`expected.json`은 파서 출력에서 생성하지 않고 원본 숫자와 계산식을 직접 확인한 기준이다.
560 `BasicAtk=332509`, 소드의 범위는 0.97/1.03으로 각각 SyncFloor한다. 원본 lib_math.lua처럼 floor(x+0.5)로 반올림한다.
트링킷 기본값은 SyncFloor(BasicAtk×0.15), 강화는 floor(누적 AddAtk×0.3)이다.
천 상의는 floor(1836595×0.25), 마법 방어는 그 값의 계산 전 수치×2를 floor한다. 방어구는 원본 Lua의 math.floor를 따르며 무기의 SyncFloor와 다르다.
실드는 BasicAtk를 양쪽 방어력에 쓰고 무기 AddAtk를 누적한다.
무기 AddAtk의 +6/+30 누적값은 38856/142500, 방어구 AddDef는 50802/196750이다.
550 액세서리는 BasicAccAtk=5855, 누적 AddAccAtk=4818/24090이다.
레드 젬의 1~10레벨 공격력·음수 치명타 페널티는 원본 XML 값을 직접 기록했다.

`make check-live`는 이 고정 실데이터를 임시 unpack에 복사해 실제 파서·JSON export,
SQLite migrations/importer·ORM·HTTP·계산기 JavaScript까지 검사한다.
반복 실행, 원본 변경 시 재계산, Lua 실패 시 JSON/버전 보존과 복구도 검사한다.
560/550은 이 원본에서 초월 비용 목록이 비어 있어 초월 비용의 실게임 호환성을 주장하지 않는다.
스킬 본체는 선택하지 않았으므로 스킬 젬의 실제 스킬 FK는 이 샘플의 검증 범위 밖이다.
전체 main.py, 다운로드, 모델/아이콘 생성, 운영 적재·MySQL 전체 데이터는 실행하지 않는다.
580 강화 IES는 미등록 진단 검증용이며 지원 대상으로 자동 등록하지 않는다.

새 원본은 별도 디렉터리에 캡처하고 기존 기준과 비교한다. 이 도구는 검토한 샘플을 덮어쓰지 않는다.

```bash
python -m harness.live_fixture --source-root /path/to/TavernofSoul --output-dir /tmp/tavern-real-candidate
HARNESS_LIVE_FIXTURE=/tmp/tavern-real-candidate make check-live
```

수치 변경이 게임의 의도된 변경이면 원본과 계산 근거를 검토한 후 샘플·manifest·기준을 함께 갱신한다.
