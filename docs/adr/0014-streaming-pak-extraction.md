# 0014. PAK 스트리밍 추출의 메모리 제한과 파일별 공개

- 상태: 제안(proposed), 최종 새 검토·전체 검증·전달 대기
- 기록일: 2026-10-14
- 기록 성격: 승인된 PAK 최적화 재시도의 구현 결정과 근거 범위
- 대체 관계: 없음. importer [0012](0012-importer-single-run-snapshot.md)와
  owned-temp [0013](0013-owned-validation-temporary-cleanup.md)을 대체하지 않는다.

## 문맥

전체 PAK 또는 압축·해제 member를 메모리에 모으면 Python 메모리 사용량이 입력이나
출력 크기에 따라 늘어난다. 이번 결정은 양쪽 IO 조각을 제한하면서 기존 PAK 형식,
blacklist·checksum·경로 정책과 파일별 실패 복구 계약을 유지한다.
이전 실제 GLM 구현 단계는 passed로 보고되었지만 이후 큰 테스트 요청은 900초 timeout했다.
이 상태는 전체 검증 성공을 뜻하지 않는다.
2026-10-14 최신 인계 정정: 마지막 실제 GLM 소스·fixture·테스트와 Codex 문서 작성 및
Claude 승인까지 완료했지만 Python3.8 실제 `check`에서 `raw_deflate`의
`zlib.compress(data, 9, -15)`가 `TypeError: compress() takes at most 2 arguments`로
downloader 수집을 실패시켰다. 해당 run은 failed이고 Root 반영은 없었다.
메인은 승인된 7개 파일만 새 격리 모델 사본에 재사용했으며 원본 Root와 원래 baseline은
새 전체 검토·검증 후 반영 전까지 유지한다.

## 결정

압축 member는 한 read 요청당 최대 64KiB(65536 bytes)로 읽는다. raw-deflate의 모든
`decompress` 호출은 양수 `max_length` 1MiB(1048576 bytes)를 전달하고 반환 조각을
바로 `.part`에 쓴다. `unconsumed_tail`도 같은 상한으로 처리한다. 전체 archive/member를
모으거나 무제한 `decompressor.flush()`를 호출하지 않는다.
14바이트 header와 최대 32767 bytes의 이름만 작은 exact-read loop로 모아 짧은 read에 대응한다.
입력·tail·출력 조각, 이름 복사, Python/file buffer와 zlib 내부 상태가 동시에 존재하므로
두 chunk 상한의 합은 총 Python peak나 RSS의 절대 상한이 아니다. 이 버퍼 한계는
archive/member 크기·레코드 수에 비례하지 않으며 디스크 사용량을 제한하지 않는다.

형식은 offset 0/2/6/10의 native signed `@h`/`@i`/`@i`/`@i`로 해석하는 기존 14바이트
header를 유지한다. endian·alignment 정책을 새로 정하지 않는다. 빈 archive, 짧은
header/name/member, 비양수 이름 길이, 음수 compressed/uncompressed 크기와 archive 끝을
넘는 record를 거부한다. checksum은 읽되 검증하지 않는다. raw 이름 bytes에 blacklist를
먼저 적용하여 해당 invalid UTF-8 이름도 디코딩하지 않고 건너뛴다. 비blacklist 이름의
UTF-8 오류는 전파한다. 경로 해석과 format 정책은 바꾸지 않는다.

추출 member는 실제 출력 크기가 선언값과 같고 deflate `eof`에 도달해야 공개한다.
완전한 stream이 만드는 빈 decoded 파일은 유효하지만 빈 compressed member는 eof에
도달할 수 없어 실패한다. 완전한 stream 뒤 compressed trailing bytes는 기존
`zlib.decompress`처럼 무시한다. 다음 record는 stream 끝이 아닌 선언된 compressed
크기의 경계로 seek하여 처리한다.

## 비교 대안과 선택 이유

| 대안 | 평가 |
| --- | --- |
| 전체 archive/member buffering 유지 | 제어 흐름은 단순하지만 입력·decoded member 크기에 따라 메모리가 늘어나는 문제를 유지한다. |
| 압축 read만 제한 | inflate 한 번의 반환 출력이 제한되지 않으면 큰 decoded member의 메모리 문제를 해결하지 못한다. |
| read와 inflate 모두 제한 | 반복 제어·tail·byte count·eof 검사가 필요하지만 기존 파일별 공개 의미를 유지하며 양쪽 버퍼를 제한한다. 이번 선택이다. |
| archive 전체 staging과 rollback | 별도 디스크·복구·공개 정책이 필요하고 기존 부분 완료 경계를 바꾼다. 이번 범위에 포함하지 않는다. |

비교는 이번 문서화 시점의 판단이다. 제공된 측정은 메모리 감소의 후보 근거이며
새 검토나 최종 검증을 대신하지 않는다. 다른 성능 변경은 포함하지 않는다.

## 결과·비용·실패 복구

각 destination의 같은 경로 `.part`에 쓰고 실제 크기/eof 확인 → 파일 flush/fsync →
close → `os.replace` 순서로 공개한다. 교체 전 decode·size·fsync·replace 실패는 기존
destination과 archive를 보존하고 실패한 part를 정리한다. 두 record 중 뒤 record가
실패해도 앞 파일은 이미 완료된 상태로 남는다. 뒤 파일의 기존 bytes와 archive는 유지된다.
전체 archive rollback은 없으며 새 디렉터리가 남을 수 있다. 모든 record 처리와 archive
close가 성공한 뒤에만 archive를 삭제한다. 정리·삭제 자체의 IO 오류는 전파하며 part 정리의
무조건 성공을 보장하지 않는다. directory fsync나 정전·강제 종료 전체의 원자성도 보장하지 않는다.

직접 `unpack()`은 실패 archive를 보존한다. 동일 archive 경로를 정상 bytes로 다시 제공하면
처음 record부터 다시 적용하고 전체 성공 후 archive를 삭제한다. 상위 다운로더의 기존 회귀는
손상 PAK을 폐기하고 다음 실행에 재다운로드하는 별도 복구 정책을 확인한다. release 버전은
해제와 번역 복사까지 성공해야 전진한다. 어느 경계도 unpack/번역 디렉터리 전체의 원자 갱신이 아니다.

작은 조각의 read/inflate/write 반복과 상태 검사가 추가된다. 이 결정의 속도 효과나 전체
파이프라인 성능에 대한 측정 근거는 없다. checksum·경로 보안·형식 정책, 전체 archive rollback,
다른 최적화를 추가하지 않는다.

## 검증 근거와 현재 상태

메인이 제공한 재사용 소스의 SHA256은
`ace103822ecb0496602066e25ff5d5172cff44fd471ede65e9226c002568108e`다.
그 소스·fixture의 기존 downloader 회귀 81개는 passed/skip 0으로 제공되었다.
격리 64MiB 합성 입력 3회와 별도 tracemalloc에서 output bytes/SHA256은 baseline과
같았고 Python traced peak는 **134851344 → 2337899 bytes**였다. 이는 이전 승인 후보의 제공된 측정이며
validation success가 아니다. RSS·전체 pipeline peak·운영 archive 호환성을 증명하지 않는다.
문서 worker는 hash나 측정을 실행하지 않았으며 최종 소스와 제공된 측정의 일치 확인은 메인 책임이다.

테스트 전용 `pak_io_guard`는 실제 파일·decompressobj를 감싸 양수·고정 상한 read,
양수·bounded max_length와 반환 출력, decompressor flush 금지를 assertion으로 정의한다.
짧은 read를 반환할 수 있고 monkeypatch는 pytest teardown으로 복원한다.
HTTP fixture·인증·의존성·production behavior는 바꾸지 않는다.
현재 여섯 작은 테스트 함수는 parameterization을 포함하여 새 18개 회귀를 정의하며
실제 실행 결과는 아직 없다.

1. RNG 하나(seed 20261014)의 200 bytes와 read 16/inflate 32 bytes로 다중 조각 처리,
   출력 equality·호출 상한·archive 삭제·no part를 확인한다.
2. 짧은 header/name/member read, 빈 decoded member, 여러 record, blacklist invalid UTF-8,
   trailing compressed bytes와 다음 record boundary의 정상 결과를 확인한다.
3. 빈/짧은 header·name·member 경계, native signed 음수와 비blacklist invalid UTF-8을
   parameterize하여 archive 보존·미공개·no part를 확인한다.
4. 뒤 record의 incomplete/corrupt deflate·declared size mismatch에서 앞 파일 완료,
   기존 뒤 파일·archive 보존과 part 정리를 확인한다.
5. 동일 archive 경로를 정상 bytes로 다시 제공한 retry의 정상 출력·archive 삭제를 확인한다.
6. fsync/replace 오류의 기존 destination·archive 보존과 part 정리를 확인한다.

기존 `test_pak_validation_preserves_existing_output_and_retries(deflate,size,truncated)`와
version/redownload/CSV guard를 유지한다. 64MiB benchmark는 기본 테스트에 넣지 않는다.
이전 RNG 재생성·truncated_name/empty_member 누락 finding은 현재 승인 테스트 소스에서
정정된 정의를 확인했으며, 이 열람은 실행 성공을 뜻하지 않는다.
이번 helper 수리는 Python3.8 지원 raw `zlib.compressobj(9, zlib.DEFLATED, -15)`를
생성하여 `compressor.compress(data) + compressor.flush()`로 fixture 입력을 완성한다.
현재 승인 테스트 소스에서 이 정의를 확인했다. 작은 입력의 compressor flush는
production decompressor flush 금지와 별개이며 생산 계약·fixture·나머지 테스트를 바꾸지 않는다.
이전 기본 gate의 parser 실패도 같은 downloader 수집 오류를 재실행하는 통합 테스트
한 건이며 django/regression/pipeline은 통과했다. 이전 관측은 새 전체 gate 성공이 아니다.

## 실행·검토·게시 책임

2026-10-14 배정 정정: 종전 세 task 대신 정확히 두 순차 task를 배정한다.
downloader GLM은 `unpacker_pak.py`·`conftest.py`·`test_downloader.py`에서
`raw_deflate` 한 곳만 수리하고 나머지를 유지한다. coordinator는 네 문서를 확인·유지하며
필요할 때만 갱신한다. 읽기 참조를 별도 task로 배정하지 않는다.
기존 GLM `glm-5.3-flash`·모든 역할 설정·NFS 저장 설정·mount·floor를 그대로 유지한다.
worker는 승인된 7개 파일만 읽고 배정 파일만 수정하며 기존 사용자 편집을 보존한다.
tests/checks·Git·운영 데이터·cron·전체다운로더·실DB·다운로드·importAll·다른 모델·
agent-run·harness.workflow를 실행하거나 위임하지 않는다.

매 새 review는 `documentation={status,files,reason}`으로 실제 changed docs의 의미적
완전성을 판단한다. Markdown 확장자 검사로 이를 대신하지 않는다. 이전 문서 수리는 승인
경로의 누락 ADR을 작성했다. 이번 인계는 그 결정과 계약을 보존하고 네 문서의 Python3.8
수집 실패·근거 상태·두 task와 7개 파일 범위를 정정한 `updated`이며 새 독립 review는 대기다.
필요 문서가 승인 밖이면 자동으로 읽거나 만들지 않고 정확한 누락 경로를 기존 승인 파일
finding에 기록하여 changes_requested로 보고한다. scope 확인과 새 run 준비는 메인
coordinator 책임이며 repair round는 승인을 확대하지 않는다.

실행기는 새 검토 뒤 필수 check 하나인 **전체 offline gate (`make check`)**를 실행한다.
selected skip/xfail·미수집은 성공으로 처리하지 않는다. 원본 Root/baseline 반영은 전체
검토·검증 후에만 허용된다. 메인은 최종 source hash와 제공된 측정의 일치를 확인한 뒤
기존 GitHub request/accept 흐름으로 원격 commit·PR을 수행한다. 실제
`Offline harness (SQLite)`·`MySQL harness`·`Chromium browser harness` CI success 3개를
확인한 뒤 승인 SHA를 squash merge하고 해당 run branch를 정리한다. 기존 journal·정확한
ref·lease·사용자 편집 보존 계약을 유지하며 merge와 cleanup 완료를 구분한다.
cleanup complete 전 전체 성공을 선언하지 않는다. 검토·offline gate·게시·CI·merge·cleanup은
모두 후속 책임이며 현재 완료 결과는 제공되지 않았다. proposed 상태는 작업 승인과 별개다.

## 관련 코드·검증·문서

- [PAK 구현](../../downloader/unpacker_pak.py)
- [테스트 전용 IO guard](../../downloader/tests/conftest.py)
- [기존 회귀와 여섯 작은 테스트](../../downloader/tests/test_downloader.py)
- [다운로더 책임](../../downloader/AGENTS.md)
- [메모리·공개·복구 계약](../architecture.md#pak-스트리밍-추출의-메모리공개복구-경계)
- [측정·정정 이력·검증과 게시 인계](../harness.md#이번-pak-스트리밍-재시도의-근거와-인계)
- [ADR 목록](README.md)

링크는 참조 경로이며 승인 밖 ADR이나 다른 문서를 읽었다는 뜻이 아니다.
