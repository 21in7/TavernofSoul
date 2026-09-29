# TavernofSoul 파싱 서버 설정 가이드

이 문서는 `parsing_server_setup.sh` 스크립트를 GitHub Actions에서 사용하는 방법을 설명합니다.

## 로컬 데이터와 버전 상태 준비

로그, PID, `Translation/`, 다운로드·파서 버전 CSV는 서버별 데이터이므로
Git에서 추적하지 않습니다. 기존 서버에서는 해당 파일을 유지하고, 서버 이전 시
패치·unpack·JSON 데이터와 버전 CSV를 함께 백업·복원하세요.

새 체크아웃에서는 저장소 루트에서 누락된 버전 파일만 초기화합니다.
운영 중인 CSV를 예제로 덮어쓰면 처리한 패치를 다시 실행하므로 덮어쓰지 마세요.

```bash
mkdir -p Translation logs
for state_file in downloader/release.csv downloader/revision.csv parser_tidy/parser_version.csv; do
    if [ ! -e "$state_file" ]; then
        cp "$state_file.example" "$state_file"
    fi
done
```

예제의 `0`은 아직 처리한 패치가 없다는 뜻입니다. 기존 패치·unpack 데이터를
복원했다면 그 데이터와 일치하는 실제 버전 CSV도 복원해야 합니다.
영어·일본어·대만어 번역은 각각 `downloader/downloader.py`의
`itos`·`jtos`·`twtos` 실행 중 release 패치의 `languageData`에서 복사됩니다.
새 환경에서는 해당 지역 다운로드를 먼저 완료한 뒤 파서를 실행하세요.
다운로드가 성공했어도 필요한 번역 폴더가 없다면 기존 서버의 `Translation/`을
복원하거나 해당 지역 언어 패치를 다시 준비해야 합니다.

`motion_proto/`는 소스와 문서를 보관하고, 캐시·영상·`plans/`의 생성된 렌더 계획은
제외합니다. 계획 재생성 방법은 `motion_proto/README.md`를 참고하세요.

## 🚀 GitHub Actions에서 사용하기

### 방법 1: 직접 실행 (Ubuntu Runner)

```yaml
# .github/workflows/parsing-server-setup.yml
name: Parsing Server Setup

on:
  workflow_dispatch:
    inputs:
      environment:
        description: '환경 선택'
        required: true
        default: 'development'
        type: choice
        options:
          - development
          - staging
          - production

jobs:
  setup-parsing-server:
    runs-on: ubuntu-latest
    steps:
    - name: Checkout repository
      uses: actions/checkout@v4

    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y mysql-server python3-pip git

    - name: Run parsing server setup
      run: bash parsing_server_setup.sh
```

### 방법 2: Docker 컨테이너에서 실행

```yaml
# .github/workflows/parsing-server-docker.yml
name: Parsing Server Setup (Docker)

on: [workflow_dispatch]

jobs:
  setup-with-docker:
    runs-on: ubuntu-latest
    steps:
    - name: Checkout repository
      uses: actions/checkout@v4

    - name: Build and run with Docker
      run: |
        docker-compose -f docker-compose.parsing.yml up --build
```

## 🔧 로컬 환경에서 테스트하기

### Docker Compose로 실행

```bash
# MySQL과 파싱 서버를 함께 실행
docker-compose -f docker-compose.parsing.yml up --build

# 백그라운드에서 실행
docker-compose -f docker-compose.parsing.yml up -d --build

# 로그 확인
docker-compose -f docker-compose.parsing.yml logs -f

# 정지 및 정리
docker-compose -f docker-compose.parsing.yml down -v
```

### 직접 실행 (Ubuntu/Debian)

```bash
# 스크립트 실행 권한 부여
chmod +x parsing_server_setup.sh

# 스크립트 실행
./parsing_server_setup.sh
```

## 📋 사전 요구사항

### 시스템 요구사항
- Ubuntu 20.04+ 또는 Debian 11+
- 최소 4GB RAM
- 최소 50GB 여유 디스크 공간
- sudo 권한

### 필수 패키지
- python3
- python3-pip
- mysql-server
- git

## ⚙️ 환경 변수 설정

### 데이터베이스 설정
```bash
export MYSQL_HOST=localhost
export MYSQL_USER=parsing_user
export MYSQL_PASSWORD=secure_password_2024
export MYSQL_DATABASE=tavernof_parsing
```

### 디렉토리 설정
```bash
export PARSING_BASE_DIR=/opt/tavernof-parsing
export LOG_DIR=/opt/tavernof-parsing/logs
export DATA_DIR=/opt/tavernof-parsing/data
```

## 📁 생성되는 디렉토리 구조

```
/opt/tavernof-parsing/
├── venv/                    # Python 가상환경
├── logs/                    # 로그 파일들
│   ├── itos/
│   ├── jtos/
│   ├── ktos/
│   ├── ktest/
│   └── twtos/
├── data/                    # 파싱된 데이터
│   ├── itos/
│   ├── jtos/
│   ├── ktos/
│   ├── ktest/
│   └── twtos/
├── scripts/                 # 실행 스크립트들
│   ├── run_parsing.sh       # 메인 파싱 실행 스크립트
│   ├── setup_cron.sh        # 크론 작업 설정
│   └── monitor_parsing.sh   # 모니터링 스크립트
└── [region]/               # 각 지역별 프로젝트 파일들
    ├── itos/
    ├── jtos/
    ├── ktos/
    ├── ktest/
    └── twtos/
```

## 🔄 워크플로우 단계

1. **시스템 요구사항 확인**
   - 메모리, 디스크 공간, 필수 패키지 확인

2. **디렉토리 구조 생성**
   - `/opt/tavernof-parsing` 기본 디렉토리 생성
   - 각 지역별 서브디렉토리 생성

3. **Python 환경 설정**
   - 가상환경 생성 및 활성화
   - 필수 패키지 설치

4. **데이터베이스 설정**
   - MySQL 데이터베이스 및 사용자 생성
   - 권한 설정

5. **스크립트 생성**
   - 파싱 실행 스크립트
   - 크론 작업 설정 스크립트
   - 모니터링 스크립트

6. **서비스 설정**
   - systemd 서비스 생성
   - 자동 시작 설정

## 📊 모니터링 및 관리

### 로그 확인
```bash
# 실시간 모니터링
/opt/tavernof-parsing/scripts/monitor_parsing.sh

# 특정 지역 로그 확인
tail -f /opt/tavernof-parsing/logs/itos/parsing_*.log
```

### 크론 작업 관리
```bash
# 크론 작업 설정
/opt/tavernof-parsing/scripts/setup_cron.sh

# 크론 작업 확인
crontab -l

# 크론 로그 확인
grep CRON /var/log/syslog
```

### 수동 파싱 실행
```bash
# 단일 지역 파싱
/opt/tavernof-parsing/scripts/run_parsing.sh itos

# 모든 지역 파싱
/opt/tavernof-parsing/scripts/run_parsing.sh all
```

## 🚨 문제 해결

### 일반적인 문제들

1. **권한 문제**
   ```bash
   sudo chown -R ubuntu:ubuntu /opt/tavernof-parsing
   ```

2. **MySQL 연결 실패**
   ```bash
   sudo systemctl restart mysql
   mysql -u parsing_user -p
   ```

3. **Python 패키지 설치 실패**
   ```bash
   source /opt/tavernof-parsing/venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **스크립트 실행 실패**
   ```bash
   chmod +x /opt/tavernof-parsing/scripts/*.sh
   bash -n /opt/tavernof-parsing/scripts/run_parsing.sh
   ```

## 🔒 보안 고려사항

- 데이터베이스 비밀번호는 환경 변수나 시크릿으로 관리
- sudo 권한 필요한 작업만 제한적으로 사용
- 로그 파일 권한 적절히 설정
- 불필요한 서비스는 비활성화

## 📝 다음 단계

설정이 완료되면:

1. 프로젝트 파일들을 `/opt/tavernof-parsing/[region]/`으로 복사
2. 데이터베이스 연결 설정 수정
3. 크론 작업 활성화: `./scripts/setup_cron.sh`
4. 모니터링 시작: `./scripts/monitor_parsing.sh`

## 🤝 기여하기

스크립트 개선을 위해서는:
- 이슈 생성
- 풀 리퀘스트 제출
- 테스트 환경에서 검증
