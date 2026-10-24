# 다운로더

- 진입점: `downloader.py <region> [full]`; 다운로드와 압축 해제를 함께 담당한다.
  선택적인 `full` 인자가 있으면 partial 대신 full 모드를 실행한다.
- 입력: 지역별 패치 서버 응답, `release.csv`, `revision.csv`. full 모드는
  `full/data.file.list.txt`의 암호화된 CRLF 리비전 목록과 `full/data/` 패치 응답을 읽으며
  버전 CSV는 읽지 않는다.
- 출력: 지역별 patch/unpack 데이터, 일부 지역의 `Translation/`, 다운로드 버전 CSV.
- 압축 해제 도구: `../IPFUnpacker/ipf_unpack`, `unpacker_pak.py`.
- 상대 경로와 현재 작업 디렉터리에 의존하는 코드가 있으므로 실행 위치를 확인한다.
- CLI 종료 코드: 변경 0, 변경 없음 1, 실패 2. 모든 지역 cron은 다운로드 실패 시 후속 단계를 중단한다.
  full 모드는 변경 여부를 판단하지 않으므로 성공 시 항상 변경 0이며, full 경로의 예외는 main이
  실패 2로 반환한다. 변경 없음 1은 partial 모드에만 있다.
- 기본 검증: 루트에서 `make check-downloader`. `make check`에도 포함된다.
- 테스트는 실제 Blowfish revision 해석·다운로드 저장·PAK 압축 해제를 고정 입력으로 실행한다.
  네이티브 IPF 도구는 임시 실행 파일로 대체한다. 내부 IPF/IES 변환 정확성은 검증 범위가 아니다.
  full 모드 회귀는 do_patch_full의 인자 전달과 patch_full의 암호화 CRLF 목록 처리·repatch·
  캐시 재사용·성공 폐기·실패 보존을 오프라인 합성 응답으로 검증한다.
- 다운로드가 완료된 파일만 캐시로 공개한다. 오류가 난 `.part`는 삭제한다.
- 복호화·압축 해제·복사 오류는 버전을 전진시키지 않는다. release는 번역 복사도 성공해야 완료다.
- 여러 패치 중 일부가 실패하면 마지막 완료된 패치의 버전을 유지하고 다음 실행에서 재시도한다.
- 패치 건너뜀 규칙 세 가지: `IPF_BLACKLIST`는 full 모드(`patch_full`)의 다운로드 조건에서만 검사되므로 full 경로 전용이다. `error_ipf`는 `patch_process`가 RuntimeError로 차단하므로 full·partial 양쪽 경로에서 실패한다. partial 모드(`patch_partial`)는 리비전 147674(`PARTIAL_REVISION_BLACKLIST`)를 다운로드·버전 갱신 없이 무음 건너뛰며, 그 사유는 소스에 기록이 없어 불명이다(추정하지 않는다).
- full 모드(`patch_full`)는 복호화한 목록을 서버 응답 순서 그대로 처리한다. partial과 달리
  수치 정렬이나 토큰 파싱이 없고 패치 파일명은 `<리비전>.ipf`다(partial은 `<리비전>_001001.ipf`).
  `_run`은 partial 분기보다 full을 먼저 선택하므로 full 실행에는 partial 처리와 Translation
  복사가 없고 revision.csv·release.csv를 읽거나 앞당기지 않는다.
- `do_patch_full`은 항상 repatch=True로 `patch_full`을 호출한다. repatch=0은 이미 존재하는
  패치 경로의 재처리를 건너뛰고, repatch=1은 존재해도 재처리한다. 재처리가 곧 재다운로드는
  아니다. `patch_process`는 비어 있지 않은 캐시를 그대로 재사용하고 캐시가 없거나 비어 있을 때만
  `full/data/`에서 내려받는다. full과 partial data 스트림은 unpack=False로 IPF 도구 해제
  경로를 쓰고, partial release만 PAK 해제를 쓴다.
- full 처리는 캐시된 아카이브를 검증과 복사가 모두 끝난 뒤에만 삭제하고, 임시 extract와 작업
  사본은 성공·실패 모두에서 정리한다. 처리에 실패하면 캐시는 보존되어 다음 실행에서
  재다운로드 없이 재사용된다.
- 파일·CSV는 개별 원자 교체를 사용한다. unpack·번역 디렉터리 전체의 원자 갱신은 보장하지 않는다.
- 연결된 cron/버전 처리 변경의 기존 회귀 검증은 `make check-parser`에 포함된다.
- 실행 상태 CSV는 `.example`과 구분한다. 기존 버전·unpack 데이터를 변경하지 않는다.

전체 연결 계약은 [../docs/architecture.md](../docs/architecture.md)를 참고한다.
