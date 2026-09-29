#!/bin/bash

# Discord WEBHOOK URL
DISCORD_URL="https://discord.com/api/webhooks/1344400483472642078/r_zJVVTCCq1AS59SbSq58iuZKEsnsejUA-by3MJ2vKzNzEOJGNha0t3BRwScv_Em9g63"

# Upload dirctory and R2 buckets
SOURCE_DIR="/home/ubuntu/TavernofSoul/TavernofSoul/staticfiles_itos"
BUCKET_NAME="R2:gihyeon"

# File Upload
rclone copy $SOURCE_DIR $BUCKET_NAME --progress

# log
LOG_MESSAGE="$(date): Files uploaded to R2 bucket" 

# JSON payload
payload=$(cat <<EOF
{
	"content": "${LOG_MESSAGE}"
}
EOF
)

# Send Discord WEBHOOK
curl -H "Content-Type: application/json" -X POST -d "${payload}" "${DISCORD_URL}"
