# Discord Web Hook URL
WEBHOOK_URL="https://discord.com/api/webhooks/1283619152950460416/zRLviXMTMQL-BpbphYqIgIThLCsBrLM-EVbeRBaLKSn8wwk1pe4LH-DJ_Glk2j3sX2Am"

# Save run results to a file
output_file="/tmp/cron_ktos_output.txt"
previous_output_file="/tmp/cron_ktos_previous_output.txt"
timing_file="/tmp/cron_ktos_timing.txt"

# JSON escape
json_escape() {
    printf '%s' "$1" | python -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

# 타이밍 측정 함수
measure_time() {
    local start_time=$1
    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))
    local hours=$((elapsed / 3600))
    local minutes=$(( (elapsed % 3600) / 60 ))
    local seconds=$((elapsed % 60))
    printf "%02d시간 %02d분 %02d초" $hours $minutes $seconds
}

# 시작 시간 기록
total_start_time=$(date +%s)
echo "=== KTOS 업데이트 시작: $(date) ===" > "$timing_file"

{
cd /home/ubuntu/TavernofSoul/
source /home/ubuntu/TavernofSoul/TavernofSoul/itos/3.8/bin/activate

# ========== downloading patch ipf ========
echo "다운로드 시작: $(date)" >> "$timing_file"
download_start_time=$(date +%s)

cd downloader
python downloader.py ktos
download_result=$?
cd ..

download_elapsed=$(measure_time $download_start_time)
echo "다운로드 완료: $(date) (소요시간: $download_elapsed)" >> "$timing_file"

if [ $download_result -eq 1 ]; then
    message="KTOS 패치 파일 없음."
    escaped_message=$(json_escape "$message")

    curl -H "Content-Type: application/json" \
         -d "{\"content\": \"$message\"}" \
         $WEBHOOK_URL

    sleep 2
    exit 0
fi

# ========== parsing maps ========
echo "맵 이미지 파싱 시작: $(date)" >> "$timing_file"
map_start_time=$(date +%s)

cd parser_tidy
python2.7 map_image.py ktos

map_elapsed=$(measure_time $map_start_time)
echo "맵 이미지 파싱 완료: $(date) (소요시간: $map_elapsed)" >> "$timing_file"

# ========== parsing unpacked ipf ========
echo "데이터 파싱 시작: $(date)" >> "$timing_file"
parsing_start_time=$(date +%s)

source /home/ubuntu/TavernofSoul/TavernofSoul/itos/3.8/bin/activate
# 로깅 레벨을 INFO로 설정하여 시간 측정 정보가 출력되도록 함
python -c "import logging; logging.basicConfig(level=logging.INFO)" 
python main.py ktos

parsing_elapsed=$(measure_time $parsing_start_time)
echo "데이터 파싱 완료: $(date) (소요시간: $parsing_elapsed)" >> "$timing_file"

# ========== importing changes to DB ========
echo "DB 가져오기 시작: $(date)" >> "$timing_file"
import_start_time=$(date +%s)

cd ..
cd TavernofSoul
python manage_ktos.py importAll

import_elapsed=$(measure_time $import_start_time)
echo "DB 가져오기 완료: $(date) (소요시간: $import_elapsed)" >> "$timing_file"

# 전체 소요 시간 계산
total_elapsed=$(measure_time $total_start_time)
echo "=== KTOS 업데이트 완료: $(date) (총 소요시간: $total_elapsed) ===" >> "$timing_file"

# 타이밍 정보를 출력 파일에 추가
cat "$timing_file" >> "$output_file"

} > "$output_file" 2>&1

# read file
output=$(cat "$output_file")

# Message splitting and sending function
send_message() {
    local content="$1"
    local escaped_content=$(json_escape "$content")
    curl -s --fail -S -H "Content-Type: application/json" \
         -d "{\"content\": $escaped_content}" \
         $WEBHOOK_URL
}

# Compare previous output with current output
if [ -f "$previous_output_file" ]; then
    previous_output=$(cat "$previous_output_file")
else
    previous_output=""
fi

# 타이밍 정보 가져오기
timing_info=$(cat "$timing_file")

if [ "$output" != "$previous_output" ]; then
    # 먼저 타이밍 정보 전송
    send_message "KTOS 업데이트 타이밍 정보:"
    send_message "\`\`\`$timing_info\`\`\`"
    
    # 그 다음 나머지 출력 전송
    send_message "KTOS 업데이트 결과:"
    
    # Split output into 1900 character chunks and send
    while [ -n "$output" ]; do
        chunk="${output:0:1900}"
        output="${output:1900}"
        send_message "\`\`\`$chunk\`\`\`"
    done
else
    # 변경 사항 없어도 타이밍 정보는 전송
    send_message "KTOS 업데이트 실행 완료. 변경 사항 없음."
    send_message "\`\`\`$timing_info\`\`\`"
fi

# Save current output to previous output file
cp "$output_file" "$previous_output_file"

# Delete temporary files
rm "$output_file"
rm "$timing_file"
