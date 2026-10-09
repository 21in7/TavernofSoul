# 다운로더 고정 입력

모든 내용은 직접 만든 작은 합성 입력이다. 게임 서버에서 받은 파일은 포함하지 않는다.

- `revisions.bin`: 두 revision(`1`, `2`)을 CRLF로 구분한 Blowfish 암호화 응답.
  8바이트 헤더에 원문 길이와 암호화 길이를 little endian으로 기록한다.
- `release.pak`: raw deflate로 압축한 번역 TSV와 제외 대상 실행 파일 이름의 두 레코드.
  각 헤더는 `<hiii`(이름 길이, checksum, 압축 길이, 원문 길이)이다.
  checksum은 현재 Python unpacker가 사용하지 않는 필드로 0을 넣었다.
- `ipf_patch.json`: 복사 대상 IES/Lua 내용. 실제 IPF 바이너리 형식은 아니다.
- `ipf_unpack_stub.py`: 임시 디렉터리에서 `IPFUnpacker/ipf_unpack` 역할로 실행한다.
  `decrypt`/`extract`를 기록하고 실패 마커가 있으면 7을 반환한다.
  기존 네이티브 도구의 내부 복호화·IES 변환 정확성은 이 fixture로 검증하지 않는다.

바이너리 입력 재생성:

```bash
python harness/fixtures/downloader/generate.py
```

실행 환경의 Python을 지정해서 실행한다. 검증 명령 `make check-downloader`는 입력을
재생성하거나 실제 서버에 접근하지 않고 임시 경로에서 사용한다.
