# 디스코드 모니터링 설정 가이드

이 가이드는 Cloudflare + nginx R2 모니터링 결과를 매일 디스코드로 자동 전송하는 방법을 설명합니다.

## 🚀 빠른 시작

### 1. 디스코드 웹훅 생성
1. Discord 채널에서 **설정 > 통합 > 웹훅** 으로 이동
2. **웹훅 추가** 클릭
3. 이름 설정 (예: "Tavern of Soul 모니터링")
4. **웹훅 URL 복사** (나중에 필요합니다)

### 2. 모니터링 설정
```bash
cd /home/ubuntu/TavernofSoul
./setup_discord_monitoring.sh
```

### 3. 웹훅 연결 테스트
```bash
./test_discord_webhook.sh
```

## 📁 파일 설명

| 파일 | 설명 |
|------|------|
| `monitor_cloudflare_r2.sh` | 메인 모니터링 스크립트 (디스코드 전송 기능 추가됨) |
| `setup_discord_monitoring.sh` | 초기 설정 스크립트 |
| `test_discord_webhook.sh` | 웹훅 연결 테스트 스크립트 |
| `.env` | 환경변수 파일 (자동 생성됨) |

## ⚙️ 설정 상세

### 환경변수
```bash
# .env 파일 내용
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### Cron 작업
매일 오전 9시에 자동 실행되도록 설정됩니다:
```bash
0 9 * * * cd /home/ubuntu/TavernofSoul && source .env && /bin/bash monitor_cloudflare_r2.sh
```

## 🎯 디스코드 메시지 형식

매일 전송되는 메시지에는 다음 정보가 포함됩니다:

### 📊 트래픽 분석
- Cloudflare 리디렉션 (icons) 요청 수 및 전송량
- nginx R2 캐시 (기타 static) 요청 수, 전송량, 히트율
- 로컬 파일 (fallback) 요청 수 및 전송량

### 💰 비용 분석
- 실제 R2 전송량 (월간 예상)
- 프리티어 상태 및 예상 추가 비용

### 🎯 최적화 권장사항
- 캐시 성능 분석
- Cloudflare 리디렉션 상태
- 추가 최적화 팁

## 🔧 고급 설정

### Cron 시간 변경
```bash
crontab -e
```
원하는 시간으로 수정 (현재: `0 9 * * *` = 매일 오전 9시)

### 웹훅 URL 변경
```bash
./setup_discord_monitoring.sh
```

### 수동 테스트
```bash
# 환경변수 로드 후 실행
source .env
./monitor_cloudflare_r2.sh
```

## 🐛 문제 해결

### 로그 파일 없음 경고
```
⚠️  로그 파일이 없습니다. nginx 설정을 먼저 적용하세요.
```
**해결**: nginx 설정 파일 적용
```bash
sudo cp nginx_cloudflare_r2.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/nginx_cloudflare_r2.conf /etc/nginx/sites-enabled/
sudo systemctl reload nginx
```

### 웹훅 전송 실패
```
❌ 디스코드 웹훅 전송 실패 (HTTP 401)
```
**해결**: 웹훅 URL 재설정
```bash
./setup_discord_monitoring.sh
```

### Cron 로그 확인
```bash
grep CRON /var/log/syslog | tail -10
```

## 📋 체크리스트

- [ ] Discord 웹훅 생성 및 URL 복사
- [ ] `./setup_discord_monitoring.sh` 실행
- [ ] `./test_discord_webhook.sh` 로 테스트
- [ ] nginx 로그 파일 존재 확인 (`/var/log/nginx/`)
- [ ] Cron 작업 동작 확인

## 💡 팁

- 웹훅 URL은 `.env` 파일에 안전하게 저장됩니다
- 실제 모니터링은 매일 오전 9시에 자동 실행됩니다
- 수동으로도 언제든지 실행 가능합니다
- Discord에서 멘션을 받고 싶다면 웹훅 설정에서 역할 선택하세요
