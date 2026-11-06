# Wiki 작업 이력

요약: 제공된 로컬 Git commit 날짜·제목으로 확인한 PR #86~#103을 시드로 보존하는 append-only 이력이다.

날짜는 commit date이며 PR 생성일이나 merge 시각을 뜻하지 않는다. 아래 18개만 최초 시드로 넣는다. 이번 미완료 wiki 작업이나 미정 PR은 추가하지 않는다. 이 페이지 작성 과정에서 Git을 새로 조회한 것이 아니라 제공된 확인 결과를 사용했다.

이후에는 확인된 이력만 끝에 추가하는 append-only 방식으로 운영한다. 각 항목은 한 줄에 날짜 | PR 번호 | 결과만 쓴다. 기존 항목의 순서나 문구를 덮어쓰지 않는다. 이력의 변경 요약을 테스트·CI·운영 성공의 보증으로 해석하지 않는다.

```text
2026-10-27 | #86 | 읽기 전용 개선 지표와 회귀 fixture 수정 추가
2026-10-28 | #87 | 관측된 시작 기준으로 legacy workflow 호출 집계 수정
2026-10-28 | #88 | 개선 성과 조회 Make 진입점과 지표 계약 추가
2026-10-28 | #89 | downloader의 미사용 patch 인자와 죽은 코드 제거
2026-10-28 | #90 | specialist provenance를 origin_role 지표에 연결
2026-10-28 | #91 | private advisory reference helper 추가
2026-10-28 | #92 | cloud specialist에 bounded reference advice 추가
2026-10-29 | #93 | private reference attachment 관측 보존 수정
2026-10-29 | #94 | 개선 회차 간 bounded private usage 관측 보존
2026-10-30 | #95 | root refusal과 reference item 실패 구분
2026-10-30 | #96 | private counter와 범위 제한 Codex discovery 읽기 지원
2026-10-30 | #97 | downloader 모델을 glm-5.3으로 전환
2026-10-30 | #98 | downloader의 전역 region 의존 제거
2026-11-02 | #99 | makeEQ 조회 키를 TypeEquipment로 통일
2026-11-02 | #100 | 중복 이름이 있을 때 item type 보존
2026-11-02 | #101 | 연구 scope 여유 확보와 agent timeout 확대
2026-11-02 | #102 | 선택 설정으로 교차 경계 reviewer coverage 지원
2026-11-02 | #103 | 제품 37개 scope와 교차 경계 검토 활성화
2026-11-03 | #104 | docs wiki 탐색·운영·교훈 문서층 추가
2026-11-03 | #105 | docs wiki 상설 탐색 안내와 모델 시작 문구 정리
2026-11-03 | #106 | docs wiki에 harness 절 탐색 안내 추가
2026-11-03 | #107 | fix(harness): restore discovery schema validation with cross-boundary config
2026-11-03 | 21in7/IPFUnpacker#4 | 추가 이름 목록을 엄격히 검증하고 기존 IPF 형식 유지
```

실패·복구의 상세 교훈은 사용자 제공 관측으로 구분해 [설정과 크기](lessons/config-and-size.md), [GitHub 복구](lessons/github-recovery.md), [run 수명](lessons/run-lifecycle.md)에 둔다. commit 제목만으로 그 원인과 운영 결과를 독립 검증했다고 쓰지 않는다. 공개 정보 한계와 증거 수준은 [공개 근거](lessons/public-evidence.md)를 따른다.

[index로 돌아가기](index.md)

```text
2026-11-03 | #108 | fix(ipf): update IPFUnpacker gitlink and document deployment
2026-11-03 | #109 | fix(parser): preserve revise_mon_hp scope during Lua loading
2026-11-03 | #110 | 검색 Item_Type 이름 중복 제거 및 이름 필터·기존 ID URL 호환 수정
2026-11-04 | #111 | Python 2.7 map_image 호환을 위해 DB 계약 import를 실제 Python 3 검증 메서드로 지연
2026-11-04 | #112 | 세 지역 cron 공통 실행부·잠금·단계 오류 처리·실행별 로그
2026-11-04 | #113 | 수동 collectstatic-itos 타깃·회귀 테스트·운영 문서
2026-11-04 | #114 | cron 무변경·잠금 경합은 로그만, map 경고 포함 최종 알림1회
2026-11-04 | #115 | cron 실행 로그 30일 초과 정리, 현재 로그 보존 및 정리 실패 격리
2026-11-04 | #116 | 활성 importAll·migrate_recipe_ids의 Item_Type 정확한 이름·장비 flag 쌍 재사용 및 중복 WARNING
2026-11-05 | #117 | trusted parent 게시·응답 파일 수락·작업 트리 park·storage 경로 명령 표준화
2026-11-05 | #118 | 미전송 pending merge의 worktree park 허용
2026-11-05 | #119 | 읽기 전용 archive-verify 명령
2026-11-06 | #120 | A2c 외부 squash merge 정리 명령
2026-11-06 | #121 | awaiting_ci 증거 기반 external-merge·이미 ff-only된 checkout 처리
2026-11-06 | #122 | 저장된 GET 증거 생성 및 exact 다음 요청 파일 검증 명령
```
