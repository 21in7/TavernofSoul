#!/bin/bash

# 각 unpack 폴더를 parser_version.csv의 버전 정보로 자동 커밋하는 스크립트 (Cron용)
# 사용자 입력 없이 자동으로 실행됩니다.

# 로그 파일 설정
LOG_FILE="/home/ubuntu/TavernofSoul/logs/auto_commit_unpack.log"
mkdir -p "$(dirname "$LOG_FILE")"

# 로그 함수
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=== Unpack 폴더 자동 버전 커밋 시작 ==="

# parser_version.csv 파일 경로
CSV_FILE="/home/ubuntu/TavernofSoul/parser_tidy/parser_version.csv"

# CSV 파일 존재 확인
if [ ! -f "$CSV_FILE" ]; then
    log "ERROR: $CSV_FILE 파일을 찾을 수 없습니다."
    exit 1
fi

# 버전 정보 읽기
while IFS=',' read -r name version; do
    if [ -n "$name" ] && [ -n "$version" ]; then
        case $name in
            "itos") ITOS_VERSION="$version" ;;
            "ktos") KTOS_VERSION="$version" ;;
            "jtos") JTOS_VERSION="$version" ;;
        esac
    fi
done < "$CSV_FILE"

log "읽은 버전 정보: itos=$ITOS_VERSION, ktos=$KTOS_VERSION, jtos=$JTOS_VERSION"

# 각 폴더 처리 함수
commit_folder() {
    local folder_name=$1
    local version=$2
    local folder_path="/home/ubuntu/TavernofSoul/${folder_name}_unpack"
    
    log "=== ${folder_name^^} 처리 시작 ==="
    log "폴더: $folder_path, 버전: $version"
    
    if [ ! -d "$folder_path" ]; then
        log "WARNING: $folder_path 폴더가 존재하지 않습니다."
        return 1
    fi
    
    # Refuse ancestor Git fallback, wrong remotes, and application files.
    if ! python3 /home/ubuntu/TavernofSoul/repository_guard.py "$folder_path" "${folder_name}_unpack" --unpack; then
        log "ERROR: $folder_name repository verification failed"
        return 1
    fi

    # 해당 폴더로 이동
    cd "$folder_path" || {
        log "ERROR: $folder_path로 이동할 수 없습니다."
        return 1
    }
    
    # Git 상태 확인
    if [ -z "$(git status --porcelain)" ]; then
        log "$folder_name: 변경사항이 없습니다."
        cd /home/ubuntu/TavernofSoul
        return 0
    fi
    
    # 모든 변경사항 추가
    if ! git add -A >/dev/null 2>&1; then
        log "ERROR: $folder_name git add 실패"
        cd /home/ubuntu/TavernofSoul
        return 1
    fi
    
    # 커밋 실행
    if ! git commit -m "Auto update $folder_name to version $version" >/dev/null 2>&1; then
        log "ERROR: $folder_name git commit 실패"
        cd /home/ubuntu/TavernofSoul
        return 1
    fi
    
    log "$folder_name: 성공적으로 커밋됨"
    
    # 원격 저장소에 푸시
    if git push >/dev/null 2>&1; then
        log "$folder_name: 원격 저장소에 푸시됨"
    else
        log "ERROR: $folder_name git push 실패"
        cd /home/ubuntu/TavernofSoul
        return 1
    fi
    
    # 상위 디렉토리로 돌아가기
    cd /home/ubuntu/TavernofSoul
    return 0
}

# 각 폴더 처리
success_count=0
total_count=0

# itos 처리
if [ -n "$ITOS_VERSION" ] && [ "$ITOS_VERSION" != "0" ]; then
    total_count=$((total_count + 1))
    if commit_folder "itos" "$ITOS_VERSION"; then
        success_count=$((success_count + 1))
    fi
else
    log "itos: 버전 정보가 없거나 0입니다. 건너뜁니다."
fi

# ktos 처리
if [ -n "$KTOS_VERSION" ] && [ "$KTOS_VERSION" != "0" ]; then
    total_count=$((total_count + 1))
    if commit_folder "ktos" "$KTOS_VERSION"; then
        success_count=$((success_count + 1))
    fi
else
    log "ktos: 버전 정보가 없거나 0입니다. 건너뜁니다."
fi

# jtos 처리
if [ -n "$JTOS_VERSION" ] && [ "$JTOS_VERSION" != "0" ]; then
    total_count=$((total_count + 1))
    if commit_folder "jtos" "$JTOS_VERSION"; then
        success_count=$((success_count + 1))
    fi
else
    log "jtos: 버전 정보가 없거나 0입니다. 건너뜁니다."
fi

log "=== 완료: 성공 $success_count/$total_count 폴더 ==="
