#!/bin/bash

# 파싱 서버 설정 스크립트
# 이 스크립트는 파싱 작업을 별도 서버로 분리하기 위한 설정을 합니다.

# 색상 출력
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 로그 함수
log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# 시스템 요구사항 확인
check_requirements() {
    log_step "시스템 요구사항 확인 중..."

    # 메모리 확인
    local total_mem=$(free -m | awk 'NR==2{printf "%.0f", $2}')
    if [ $total_mem -lt 4096 ]; then
        log_warn "권장 메모리: 4GB 이상, 현재: ${total_mem}MB"
    else
        log_info "메모리 확인: ${total_mem}MB ✓"
    fi

    # 디스크 공간 확인
    local available_space=$(df / | awk 'NR==2{printf "%.0f", $4/1024}')
    if [ $available_space -lt 50 ]; then
        log_warn "권장 여유 공간: 50GB 이상, 현재: ${available_space}GB"
    else
        log_info "디스크 공간 확인: ${available_space}GB ✓"
    fi

    # 필수 패키지 확인
    local required_packages=("python3" "python3-pip" "mysql-server" "git")
    for package in "${required_packages[@]}"; do
        if ! dpkg -l | grep -q "^ii  $package"; then
            log_warn "필수 패키지 누락: $package"
        else
            log_info "패키지 확인: $package ✓"
        fi
    done
}

# 파싱 디렉토리 구조 생성
create_parsing_structure() {
    log_step "파싱 작업 디렉토리 구조 생성 중..."

    local parsing_base="/opt/tavernof-parsing"
    local regions=("itos" "jtos" "ktos" "ktest" "twtos")

    # 기본 디렉토리 생성
    sudo mkdir -p "$parsing_base"
    sudo mkdir -p "$parsing_base/logs"
    sudo mkdir -p "$parsing_base/data"
    sudo mkdir -p "$parsing_base/scripts"
    sudo mkdir -p "$parsing_base/venv"

    # 각 지역별 디렉토리 생성
    for region in "${regions[@]}"; do
        sudo mkdir -p "$parsing_base/$region"
        sudo mkdir -p "$parsing_base/logs/$region"
        sudo mkdir -p "$parsing_base/data/$region"
    done

    # 권한 설정
    sudo chown -R ubuntu:ubuntu "$parsing_base"

    log_info "파싱 디렉토리 구조 생성 완료"
}

# Python 가상환경 설정
setup_python_env() {
    log_step "Python 가상환경 설정 중..."

    local parsing_base="/opt/tavernof-parsing"
    local venv_path="$parsing_base/venv"

    # 가상환경 생성
    python3 -m venv "$venv_path"

    # 가상환경 활성화 및 패키지 설치
    source "$venv_path/bin/activate"

    # 필수 패키지 설치
    pip install --upgrade pip
    pip install requests beautifulsoup4 lxml pandas numpy tqdm pymysql mysql-connector-python

    # 추가 패키지 (TavernofSoul 프로젝트 의존성)
    pip install django djangorestframework pillow binary-reader

    deactivate

    log_info "Python 가상환경 설정 완료"
}

# 데이터베이스 설정
setup_database() {
    log_step "데이터베이스 설정 중..."

    # MySQL 서비스 확인
    if ! systemctl is-active --quiet mysql; then
        log_warn "MySQL 서비스가 실행되지 않고 있습니다."
        sudo systemctl start mysql
    fi

    # 데이터베이스 생성 스크립트
    cat > /tmp/setup_databases.sql << 'EOF'
CREATE DATABASE IF NOT EXISTS tavernof_parsing CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS itos CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS jtos CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS ktos CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS ktest CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS twtos CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 파싱 전용 사용자 생성
CREATE USER IF NOT EXISTS 'parsing_user'@'localhost' IDENTIFIED BY 'secure_password_2024';
GRANT ALL PRIVILEGES ON tavernof_parsing.* TO 'parsing_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON itos.* TO 'parsing_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON jtos.* TO 'parsing_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON ktos.* TO 'parsing_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON ktest.* TO 'parsing_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON twtos.* TO 'parsing_user'@'localhost';

FLUSH PRIVILEGES;
EOF

    # 데이터베이스 설정 실행
    sudo mysql -u root < /tmp/setup_databases.sql

    # 임시 파일 삭제
    rm /tmp/setup_databases.sql

    log_info "데이터베이스 설정 완료"
}

# 파싱 스크립트 생성
create_parsing_scripts() {
    log_step "파싱 스크립트 생성 중..."

    local parsing_base="/opt/tavernof-parsing"
    local regions=("itos" "jtos" "ktos" "ktest" "twtos")

    # 메인 파싱 스크립트
    cat > "$parsing_base/scripts/run_parsing.sh" << 'EOF'
#!/bin/bash

# 메인 파싱 실행 스크립트
# 사용법: ./run_parsing.sh [region] [force]
# 예: ./run_parsing.sh itos force

REGION=${1:-"all"}
FORCE=${2:-""}
BASE_DIR="/opt/tavernof-parsing"
LOG_DIR="$BASE_DIR/logs"
DATA_DIR="$BASE_DIR/data"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') [$REGION] - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') [$REGION] - $1"
}

# 단일 지역 파싱 실행
run_single_parsing() {
    local region=$1
    local log_file="$LOG_DIR/$region/parsing_$(date +%Y%m%d_%H%M%S).log"

    log_info "파싱 시작: $region"
    log_info "로그 파일: $log_file"

    # 가상환경 활성화
    source "$BASE_DIR/venv/bin/activate"

    # 작업 디렉토리 이동
    cd "$BASE_DIR/$region" 2>/dev/null || {
        log_error "지역 디렉토리가 존재하지 않습니다: $BASE_DIR/$region"
        return 1
    }

    # 파싱 실행 (실제 명령어는 프로젝트에 맞게 수정 필요)
    {
        echo "=== $region 파싱 시작: $(date) ==="

        # 다운로드 단계
        python downloader.py "$region" || echo "다운로드 실패"

        # 맵 파싱 단계
        python2.7 map_image.py "$region" || echo "맵 파싱 실패"

        # 데이터 파싱 단계
        python main.py "$region" || echo "데이터 파싱 실패"

        # DB 임포트 단계
        python manage_${region}.py importAll || echo "DB 임포트 실패"

        echo "=== $region 파싱 완료: $(date) ==="
    } >> "$log_file" 2>&1

    # 결과 확인
    if [ $? -eq 0 ]; then
        log_info "파싱 완료: $region"
    else
        log_error "파싱 실패: $region"
    fi

    deactivate
}

# 모든 지역 파싱 실행
run_all_parsing() {
    local regions=("itos" "jtos" "ktos" "ktest" "twtos")

    for region in "${regions[@]}"; do
        run_single_parsing "$region"
        # 지역 간 간격
        sleep 30
    done
}

# 메인 실행
main() {
    case $REGION in
        "all")
            log_info "모든 지역 파싱 시작"
            run_all_parsing
            ;;
        "itos"|"jtos"|"ktos"|"ktest"|"twtos")
            log_info "단일 지역 파싱 시작: $REGION"
            run_single_parsing "$REGION"
            ;;
        *)
            log_error "잘못된 지역: $REGION"
            echo "사용법: $0 [region] [force]"
            echo "지역: itos, jtos, ktos, ktest, twtos, all"
            exit 1
            ;;
    esac
}

main "$@"
EOF

    # 크론 작업 설정 스크립트
    cat > "$parsing_base/scripts/setup_cron.sh" << 'EOF'
#!/bin/bash

# 파싱 크론 작업 설정 스크립트

CRON_JOBS="
0 * * * * /opt/tavernof-parsing/scripts/run_parsing.sh itos
15 * * * * /opt/tavernof-parsing/scripts/run_parsing.sh jtos
30 * * * * /opt/tavernof-parsing/scripts/run_parsing.sh ktos
45 * * * * /opt/tavernof-parsing/scripts/run_parsing.sh ktest
0 */6 * * * /opt/tavernof-parsing/scripts/run_parsing.sh twtos
"

# 기존 크론 작업 백업
crontab -l > /tmp/cron_backup_$(date +%Y%m%d_%H%M%S) 2>/dev/null || echo "기존 크론 작업 없음"

# 새로운 크론 작업 설정
echo "기존 크론 작업을 새로운 파싱 작업으로 교체합니다..."
(crontab -l 2>/dev/null | grep -v "tavernof-parsing\|TavernofSoul.*parsing"; echo "$CRON_JOBS") | crontab -

echo "크론 작업 설정 완료"
crontab -l
EOF

    # 모니터링 스크립트
    cat > "$parsing_base/scripts/monitor_parsing.sh" << 'EOF'
#!/bin/bash

# 파싱 작업 모니터링 스크립트

BASE_DIR="/opt/tavernof-parsing"
LOG_DIR="$BASE_DIR/logs"
REGIONS=("itos" "jtos" "ktos" "ktest" "twtos")

echo "=== 파싱 작업 모니터링 ==="
echo "시간: $(date)"
echo

# 각 지역별 최근 로그 확인
for region in "${REGIONS[@]}"; do
    echo "--- $region ---"

    # 최근 로그 파일 찾기
    latest_log=$(find "$LOG_DIR/$region" -name "*.log" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)

    if [ -n "$latest_log" ]; then
        echo "최근 로그: $latest_log"
        echo "마지막 수정: $(stat -c '%y' "$latest_log" 2>/dev/null || echo 'N/A')"

        # 로그의 마지막 몇 줄 표시
        echo "최근 활동:"
        tail -5 "$latest_log" | sed 's/^/  /'
    else
        echo "로그 파일 없음"
    fi

    # 프로세스 확인
    if pgrep -f "run_parsing.sh $region" > /dev/null; then
        echo "상태: 실행 중"
    else
        echo "상태: 중지됨"
    fi

    echo
done

# 시스템 리소스 확인
echo "=== 시스템 리소스 ==="
echo "CPU 사용량:"
top -bn1 | head -10
echo
echo "메모리 사용량:"
free -h
echo
echo "디스크 사용량:"
df -h "$BASE_DIR"
EOF

    # 스크립트 권한 설정
    chmod +x "$parsing_base/scripts/run_parsing.sh"
    chmod +x "$parsing_base/scripts/setup_cron.sh"
    chmod +x "$parsing_base/scripts/monitor_parsing.sh"

    log_info "파싱 스크립트 생성 완료"
}

# 서비스 설정
create_systemd_service() {
    log_step "systemd 서비스 설정 중..."

    # 파싱 모니터링 서비스
    sudo tee /etc/systemd/system/tavernof-parsing-monitor.service > /dev/null << 'EOF'
[Unit]
Description=TavernofSoul Parsing Monitor
After=network.target mysql.service

[Service]
Type=simple
User=ubuntu
ExecStart=/opt/tavernof-parsing/scripts/monitor_parsing.sh
Restart=always
RestartSec=300

[Install]
WantedBy=multi-user.target
EOF

    # 파싱 워처 서비스
    sudo tee /etc/systemd/system/tavernof-parsing-watcher.service > /dev/null << 'EOF'
[Unit]
Description=TavernofSoul Parsing Directory Watcher
After=network.target

[Service]
Type=simple
User=ubuntu
ExecStart=/usr/bin/python3 -c "
import time
import os
from pathlib import Path

WATCH_DIR = '/opt/tavernof-parsing/data'
PROCESSED_DIR = '/opt/tavernof-parsing/processed'

os.makedirs(PROCESSED_DIR, exist_ok=True)

while True:
    for file_path in Path(WATCH_DIR).glob('*.json'):
        if file_path.is_file():
            print(f'새 파일 발견: {file_path.name}')
            # 파일 처리 로직 추가
            time.sleep(60)
    time.sleep(30)
"
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
EOF

    # 서비스 활성화
    sudo systemctl daemon-reload
    sudo systemctl enable tavernof-parsing-monitor

    log_info "systemd 서비스 설정 완료"
}

# 메인 설치 함수
main() {
    log_info "TavernofSoul 파싱 서버 설정 시작"

    check_requirements
    create_parsing_structure
    setup_python_env
    setup_database
    create_parsing_scripts
    create_systemd_service

    log_info "파싱 서버 설정 완료!"
    log_info "다음 단계:"
    log_info "1. 프로젝트 파일들을 /opt/tavernof-parsing/으로 복사"
    log_info "2. 데이터베이스 연결 설정 수정"
    log_info "3. 크론 작업 설정: ./scripts/setup_cron.sh"
    log_info "4. 모니터링 실행: ./scripts/monitor_parsing.sh"
}

# 스크립트 실행
if [[ $EUID -eq 0 ]]; then
    log_error "이 스크립트는 root 권한으로 실행하지 마세요."
    exit 1
fi

main "$@"
