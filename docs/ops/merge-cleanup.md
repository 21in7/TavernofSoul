# Merge와 cleanup·archive

요약: 사용자의 UI squash merge 뒤 parent가 실제 비교 근거를 확보하고 정리와 보관을 각각 완료한다.

정본은 `logs/harness/harness-runbook-core.json`이며 충돌 시 runbook core가 우선한다. 이 페이지는 공개 요약이며 새 merge·삭제 권한을 부여하지 않는다.

## 사용자의 UI 단계

게시 대상은 fork `21in7/TavernofSoul`이다. parent는 PR 대상과 필수 CI 결과를 확인하며, 사용자가 GitHub UI에서 Squash and merge한다. 사용자는 Delete branch를 누르지 않는다. 기존 문서의 역사적 자동 merge 지침과 다르면 이번 사용자 UI merge 지시를 적용한다. 기존 문서 본문은 고치지 않는다.

구현자·reviewer는 Git·검사·운영 명령을 실행하지 않는다. [workflow 운영](workflow.md)의 역할 경계를 유지한다.

## Parent의 비교와 삭제

parent는 삭제 전에 정확한 브랜치·tip·보호 여부·다른 작업/PR의 사용 여부·CI·merge 증거를 비교한다. 완료된 PR과 대상이 일치해야 하며 다른 진행 작업과 사용자 변경을 보존한다. 이름이나 merge 알림만으로 삭제하지 않는다.

비교가 불충분하거나 불일치하면 확인된 증거와 남은 상태를 보고한다. private 조회 환경이나 고정 조회용 호스트 경로·식별값은 공개하지 않는다.

parent는 비교 후 해당 브랜치를 삭제하고 cleanup, archive를 수행한다. 사용자 UI merge를 자동 merge로 대체하지 않는다.

## Cleanup과 archive의 순서

의도한 완료 순서는 merge 확인 → 비교 후 삭제·cleanup → archive다. 사용자 제공 관측에는 archive가 cleanup보다 먼저 호출되는 알려진 문제가 있다. 관측 위치는 `harness/git_publish.py:904`이며 줄 번호는 현재 관측 위치이지 영구 API가 아니다. 이번 문서 작업에서는 이를 기록만 하고 우회하거나 코드를 수정하지 않는다.

이번 작업은 해당 소스를 읽거나 실행해 동작을 재검증한 것이 아니다.

## 보고할 상태

- PR·필수 CI·UI merge: 각각 실제 조회 또는 종료 결과로 확인된 상태.
- 삭제·cleanup: 대상 비교와 정리가 완료됐는지, 아니면 pending인지.
- archive: 실제 보관 완료가 확인됐는지, 아니면 pending인지.

merge 성공과 cleanup/archive 완료를 구분한다. 하나라도 pending이면 전체 완료가 아니며 다른 단계의 결과로 완료를 추정하지 않는다. 준비 상태나 정상 종료 결과 없는 호출도 성공으로 세지 않는다.

실패 후 재시도 금지와 증거 수준은 [실패 보고](failure-reporting.md), 실행 경계는 [run 수명 교훈](../lessons/run-lifecycle.md)을 따른다. 기존 상세는 읽기 승인된 [workflow](../workflow.md)에서 확인한다.

[index로 돌아가기](../index.md)
