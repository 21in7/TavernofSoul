#!/bin/bash

# 각 unpack 폴더를 parser_version.csv의 버전 정보로 커밋하는 스크립트

echo "=== Unpack 폴더 버전 커밋 스크립트 ==="

# parser_version.csv 파일 경로
CSV_FILE="parser_tidy/parser_version.csv"

# CSV 파일 존재 확인
if [ ! -f "$CSV_FILE" ]; then
    echo "Error: $CSV_FILE 파일을 찾을 수 없습니다."
    exit 1
fi

# 버전 정보 읽기
echo "읽은 버전 정보:"
while IFS=',' read -r name version; do
    if [ -n "$name" ] && [ -n "$version" ]; then
        echo "  $name: $version"
        case $name in
            "itos") ITOS_VERSION="$version" ;;
            "ktos") KTOS_VERSION="$version" ;;
            "jtos") JTOS_VERSION="$version" ;;
        esac
    fi
done < "$CSV_FILE"

echo ""
echo "처리할 폴더들: itos, ktos, jtos"

# 사용자 확인
read -p "계속 진행하시겠습니까? (y/N): " confirm
if [[ ! $confirm =~ ^[Yy]$ ]]; then
    echo "작업이 취소되었습니다."
    exit 0
fi

# 각 폴더 처리 함수
commit_folder() {
    local folder_name=$1
    local version=$2
    local folder_path="${folder_name}_unpack"
    
    echo ""
    echo "=== ${folder_name^^} 처리 중 ==="
    echo "폴더: $folder_path"
    echo "버전: $version"
    
    if [ ! -d "$folder_path" ]; then
        echo "  Warning: $folder_path 폴더가 존재하지 않습니다."
        return 1
    fi
    
    # 해당 폴더로 이동
    cd "$folder_path" || return 1
    
    # Git 상태 확인
    if [ -z "$(git status --porcelain)" ]; then
        echo "  $folder_name: 변경사항이 없습니다."
        cd ..
        return 0
    fi
    
    # 모든 변경사항 추가
    if ! git add -A; then
        echo "  $folder_name: git add 실패"
        cd ..
        return 1
    fi
    
    # 커밋 실행
    if ! git commit -m "Update $folder_name to version $version"; then
        echo "  $folder_name: git commit 실패"
        cd ..
        return 1
    fi
    
    echo "  $folder_name: 성공적으로 커밋됨"
    
    # 원격 저장소에 푸시 (선택사항)
    read -p "  $folder_name을 원격 저장소에 푸시하시겠습니까? (y/N): " push_confirm
    if [[ $push_confirm =~ ^[Yy]$ ]]; then
        if git push; then
            echo "  $folder_name: 원격 저장소에 푸시됨"
        else
            echo "  $folder_name: git push 실패"
        fi
    fi
    
    # 상위 디렉토리로 돌아가기
    cd ..
    return 0
}

# 각 폴더 처리
success_count=0
total_count=0

if [ -n "$ITOS_VERSION" ] && [ "$ITOS_VERSION" != "0" ]; then
    total_count=$((total_count + 1))
    if commit_folder "itos" "$ITOS_VERSION"; then
        success_count=$((success_count + 1))
    fi
else
    echo ""
    echo "itos: 버전 정보가 없거나 0입니다. 건너뜁니다."
fi

if [ -n "$KTOS_VERSION" ] && [ "$KTOS_VERSION" != "0" ]; then
    total_count=$((total_count + 1))
    if commit_folder "ktos" "$KTOS_VERSION"; then
        success_count=$((success_count + 1))
    fi
else
    echo ""
    echo "ktos: 버전 정보가 없거나 0입니다. 건너뜁니다."
fi

if [ -n "$JTOS_VERSION" ] && [ "$JTOS_VERSION" != "0" ]; then
    total_count=$((total_count + 1))
    if commit_folder "jtos" "$JTOS_VERSION"; then
        success_count=$((success_count + 1))
    fi
else
    echo ""
    echo "jtos: 버전 정보가 없거나 0입니다. 건너뜁니다."
fi

echo ""
echo "=== 완료 ==="
echo "성공: $success_count/$total_count 폴더"
