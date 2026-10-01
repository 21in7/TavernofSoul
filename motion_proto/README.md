# motion_proto — 직업 스킬 모션 → WebM 시제품

GPU·Blender 없이 서버(aarch64, numpy)에서 ToS 스킬 모션을 **무기·스킬 이펙트까지** 렌더링해 WebM 으로 만든다.
현재 대상: `cleric_m` 기본 외형(costume01 + messy 머리/헤어 + 메이스/버클러), ktos 패치 기준.

## 파이프라인

1. **원격 추출** (`ipf_remote.py`) — 패치 CDN 의 ipf 끝 파일 테이블만 Range 로 읽어 인덱스를 만들고,
   필요한 엔트리만 Range 로 받아 복호화(짝수 바이트 XOR) → raw deflate → CRC 검증. ipf 전체를 받지 않는다.
   - full 기준본에 PC 몸통 모델이 없어서(partial 로만 들어옴) full + partial 550개 테이블을 합친 인덱스를 쓴다.
2. **파싱** — `xac.py`(노드·메시·스킨·머티리얼), `xsm.py`(뼈별 pos/rot/scale 키), `psb.py`(Fork Particle 이펙트, 근사).
3. **포즈** (`pose.py`) — `world = parent @ (T·R·S)`, 선형 블렌드 스키닝, 머리 빌보드, 무기 강체 부착.
4. **이펙트** (`effects.py`) — 트리거 타임라인 + 근사 파티클 시뮬레이션.
5. **렌더** (`raster.py`) — numpy 소프트웨어 래스터라이저(z-buffer, 원근 보정 UV, 알파 테스트, 툰 셰이딩,
   가산 블렌딩 스프라이트/바닥 판).
6. **인코딩** (`render_motion.py`) — PNG 프레임 → ffmpeg VP9 WebM.

## 사용법

```bash
cd motion_proto
python3 render_motion.py --motion cleric_m_mns_skl_blessing --out out/blessing.webm
python3 render_motion.py --motion cleric_m_mns_skl_holysmash --out out/holysmash.webm
python3 render_motion.py --motion cleric_m_mns_skl_blessing --no-effects --background ffffff --out out/b.webm
python3 render_motion.py --motion cleric_m_mns_skl_blessing --preview out/p.png --time 1.0
```

| 옵션 | 의미 |
|---|---|
| `--no-effects` / `--no-weapons` | 이펙트·무기 끄기 |
| `--background` | 배경색. 기본은 이펙트가 있으면 `1d2026`(가산 이펙트가 흰 배경에서 안 보임), 없으면 `ffffff` |
| `--max-duration` | 모션이 끝난 뒤 이펙트 꼬리를 포함한 최대 길이(기본 3초, 마지막 포즈 유지) |
| `--alpha` | 투명 배경 VP9(용량 약 4배, Safari 투명 미지원) |
| `--yaw/--pitch/--distance/--target-y` | 카메라(기본 3/4 정면, 모션 범위 자동 프레이밍) |

웹 삽입 예: `<video src="blessing.webm" autoplay loop muted playsinline width="360" height="480"></video>`

## 무기

- `JOB_ASSETS[job]['weapons']` = (더미 뼈, 모델, 텍스처 폴더). 무기 모델은 남녀 공용(`cleric_f_mace_*`).
- 메이스 → `Dummy_R_HAND`, 방패 → `Dummy_L_HAND`. `Dummy_Shield` 는 오른손 자식이라 메이스와 겹쳤다.
- **스킬 모션이 무기 더미 스케일을 0 으로 키잉해 시전 중 무기를 숨기는 경우가 많다**(blessing, magnusexorcismus 등).
  스케일을 그대로 따르므로 이런 스킬은 인게임처럼 무기가 안 보인다. holysmash 등은 보인다.

## 스킬 이펙트

트리거 출처:
1. 애니메이션 이벤트 xml `animation.ipf/pc/<job>/<motion>.xml` 의 `<Particle frame attachNode particleName scale>` — 자동.
2. `skill_bytool.ipf/*.xml`(`C_EFFECT_POS`)·`xml.ipf/pad_skill_list.xml`(`C_PAD_EFFECT_POS`) — 스킬↔모션 매핑이 없어
   `effects.MOTION_EXTRA_EVENTS` 에 수동 등록(출처 주석 포함).

이펙트 메타(`time`, `scale`, 실제 psb 파일명)는 `effect.ipf/forkparticle/forkparticle.xml`.
부착 더미(`Dummy_effect_*`)는 코스튬 모델에 없고 기본 뼈대 `cleric_m_bodybase.xac` 에만 있어,
몸통과 공통인 조상 뼈 기준 bind 상대 변환으로 위치를 구한다(`NodeResolver`).

### PSB(Fork Particle) — 근사 재현

상용 미들웨어 바이너리이고 공개 문서가 없다. 샘플 561파일/3,745 레코드 통계로 확인·추정한 레이아웃:

| 구분 | 내용 |
|---|---|
| 확실 | 64B 헤더(`PSB\0`, ver 100, dataLen) + 가변 길이 이미터 레코드 체인(크기 @+0x100), 이름 @+0, 텍스처 @(size-284), 로컬 4x4 @+0x2b8 |
| 확인(샘플 대조) | 바닥 판 플래그 @0x178 bit 0x40(`badak*` 이미터), 파티클 범위 bbox @0x1fc/0x208 |
| 추정 | 색·알파 키 @0x120~0x15c(시각 @0x160/0x164), 크기 키 @0x17c~0x184(시각 @0x168), 수명 @0x1e4, 발생량 @0x1f4, 속도 @0x1dc |

모든 텍스처는 가산 합성(`_alpha` 텍스처도 RGB 가 밝은 마스크 그림). 파티클은 이미터 위치에서 bbox 안 임의 점으로
감속 이동한다. **원본 런타임과 모양·타이밍이 다를 수 있다** — 게임 화면과 1:1 로 맞춘 결과가 아니다.

### Unity 이펙트(.pb) — 원본 파라미터 기반 재현

신형 스킬(예: BowMaster_GodArrow)은 스크립트가 `C_UNITY_EFFECT_NODE` / `C_ADD_UNITY_EFFECT` 로 이펙트를 부른다.
`effect.ipf/unityeffect.xml` 이 이름 → `assets.ipf/<guid>.pb` 를 매핑하고, `.pb` 는 IMC 가 Unity 씬 그래프
(GameObject/Transform/ParticleSystem/Renderer/Material/Mesh)를 protobuf 로 직렬화한 것이다(`unity_fx.py`).

- 스키마는 없지만 필드 번호가 Unity 파티클 모듈 순서를 따라, 수명·속도·크기·시작색·발생량·버스트·발생 모양·
  수명별 색/크기·스프라이트 시트·렌더 모드를 값으로 확인해 매핑했다(필드표는 `unity_fx.py` 머리말).
- 머티리얼 → 텍스처(`assets.ipf/<guid>.png|tga`), 메시(`.pb` Mesh) 까지 GUID 로 따라가 71/71 텍스처가 연결됐다.
- 동작 규칙은 Unity 파티클 시스템의 공개 동작을 따른다 → PSB 보다 근거가 강하다.
- 미반영: 곡선 탄젠트(선형 보간), 서브 이미터, 노이즈·충돌, IMC 전용 셰이더 효과(디졸브, `UVdistortion` 굴절은 렌더 제외).
- Unity 기본 scalingMode(Local)에 따라 스킬 스크립트 크기 인자는 루트 오브젝트의 시스템에만 적용한다.
- 알파가 전부 불투명한 텍스처(MTOS 셰이더 `_OpacityType`)와 알파 없는 RGB 텍스처는 밝기를 알파로 쓴다.

스킬 스크립트 이벤트는 `effects.SKILL_EVENTS`(phase `start`/`shot`, Dist/Height 오프셋, 발사 시 detach)에 등록하고
`--skill BowMaster_GodArrow` 로 켠다. 차지 중 캐릭터 색(`BowMaster_ActorBlend`)은 `SEGMENT_TINTS`.

```bash
python3 render_motion.py --job archer_m \
  --motion "archer_m_thb_skl_godarrow_cast,archer_m_thb_skl_godarrow_loop*3,archer_m_thb_skl_godarrow_shot" \
  --skill BowMaster_GodArrow --yaw 250 --max-duration 3.5 --out out/archer_m_godarrow_fx.webm
```

### 무기 스키닝(활)

archer 기본 뼈대(`archer_m_bodybase.xac`)에 활 뼈(`Dummy_body`, `Bone_up*`, `Bone_down*`)가 `Dummy_R_HAND` 아래 있고
모션에 트랙이 있다. 무기 메시의 스킨 뼈를 이름으로 포즈한 기본 뼈대에 연결해(`NodeResolver.skin_by_name`) 시위 휨까지 재현.
코스튬 모델에 더미 뼈가 없어도 같은 모션으로 기본 뼈대를 함께 포즈해 부착 위치를 구한다.

## 포맷에서 알아낸 것 (구현 시 주의)

- 뼈 이름 대소문자가 xac/xsm/이벤트 xml 간에 다르다 → 대소문자 무시 매칭.
- 음수 스케일 뼈(오른쪽 치마·팔 보조뼈 `scale=-1`) — 스케일을 빼면 애니메이션 시 치맛자락이 판처럼 튄다.
- 머리/헤어는 2D 판(빌보드), `c01~c09` 각도별 변형, 얼굴은 표정 아틀라스(5×4, 알파 자기상관으로 감지).
- 캐릭터 정면은 모델 −Z. ipf 헤더 fileCount 는 u16 이라 넘친다.
- ffmpeg `color` 소스 기본 25fps → `r=fps` 를 안 주면 overlay 에서 프레임이 버려진다.

## 성능·용량 (360x480, supersample 2, 2코어)

| 모션 | 프레임 | 렌더+인코딩 | VP9 CRF40 |
|---|---|---|---|
| blessing (이펙트 없음, 0.67s) | 21 | ~25s | 43KB |
| MagnusExorcismus (이펙트 없음, 1.2s) | 37 | ~36s | 58KB |

이펙트 포함 수치는 `out/` 최종 렌더 로그 참고(모션 뒤 이펙트 꼬리까지 최대 3초).

## 전직업 일괄 렌더 (사이트 스킬 → WebM)

1. **계획 생성** (`skill_plan.py`, 이 서버에서) — 사이트 `JSON_ktos/skills.json` 스킬마다 모션·자세·무기·이펙트를 자동으로 정해
   `plans/ktos_m.json` 에 쓴다. 규칙은 파일 머리말 참고(skill.ies FileName/Cast*, 스크립트 `MONSKL_C_PLAY_ANIM*`·`<Anim>`,
   stance.ies 자세 코드, 스크립트/패드 이펙트 → 이벤트). 렌더에 필요한 엔트리만 남긴 `cache/index_ktos_render.json`(약 19MB)도 만든다.
   ```bash
   python3 skill_plan.py --out plans/ktos_m.json --render-index cache/index_ktos_render.json
   ```
   ktos 936개 중 876개 계획, 60개 제외(패시브·토글 등 재생 모션 정의 없음 56, 모션 파일 없음 4). 남캐 5직업만.
2. **렌더** (`batch_render.py`, 코어 많은 PC에서) — 계획 + 렌더 인덱스 + 코드만 있으면 되고 에셋은 CDN 에서 받는다.
   워커 수만큼 병렬, 스킬별 상태 파일로 이어 하기, 끝나면 `manifest.json`.
   ```bash
   python batch_render.py --plans plans/ktos_m.json --workers 30
   ```
3. **사이트 반영** — `out_batch/*.webm` 을 `TavernofSoul/static/skill_motion/` 에 넣고 collectstatic + uwsgi 재시작.
   스킬 상세(`Skills/views.py` → `templates/Skills/index.html`)는 `skill_motion/<ClassName>.webm` 이 있을 때만 영상을 보여준다.

기본 외형(xac.ies `*_costume01` 행): warrior_m costume01, mage_m costume02(Mage_m_costume01 행), archer_m/cleric_m costume01,
scout_m scout01. 무기는 자세별 기본 모델(`skill_plan.WEAPON_MODELS`, 없으면 솔미키 세트).

이펙트 자동 변환의 추정 부분: 투사체 비행 시간·목표 거리(타깃 위치는 서버가 정함 → 전방 60~80), `C_UNITY_EFFECT_ATTACH`
BOT/MID/TOP 위치, 스크립트 lua 함수(`SKL_RUN_SCRIPT`, `effect_spin_god_arrow` 등)가 부르는 이펙트는 빠진다.

## 한계 / TODO

- 이펙트는 근사 재현(위 PSB 절). 메시 이미터(`effect.ipf/high/emitter/*.xac`), XML 이펙트(`effectlist.xml`) 미지원.
- lua 스크립트 안의 이펙트, 조건부 SubSkl, 캐릭터 색 연출(`C_COLORBLEND_ACTOR`)은 자동 변환하지 않는다.
- 표정 고정, 머리 판 기울기 미반영, 사운드 없음.
- 인덱스 재생성 스크립트 없음, 여캐 외형 미등록.
