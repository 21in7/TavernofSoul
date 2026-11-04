#!/bin/bash
# Shared operational entry point; examples and manual runs use the same lock.
# No import-completion cursor or automatic recovery is maintained here (B2).
set +x
set +e
set +u
set -o pipefail
umask 077

region=${1:-unknown}
repo_root=
run_log=unknown
status=running
stage=setup_region
stage_code=0
stage_active=0
stage_started=$SECONDS
run_started=$SECONDS
map_code=0
notification_problem=none
revision=unknown

log() {
    printf '%(%Y-%m-%dT%H:%M:%S%z)T %s\n' -1 "$*"
}

read_revision() {
    revision=unknown
    [[ -n $repo_root && -r $repo_root/downloader/revision.csv ]] || return 0
    local key value extra
    # Read only the current observation, including CRLF and a final line without LF.
    {
        while IFS=, read -r key value extra || [[ -n $key ]]; do
            if [[ $key == "$region" ]]; then
                value=${value%$'\r'}
                if [[ $value =~ ^[0-9]+$ && -z $extra ]]; then
                    revision=$value
                fi
                break
            fi
        done < "$repo_root/downloader/revision.csv"
    } 2>/dev/null
    return 0
}

json_escape() {
    # Bash encoding works even when activation/python setup has failed.
    local LC_ALL=C character number index
    json_value='"'
    for ((index=0; index<${#1}; index++)); do
        character=${1:index:1}
        case $character in
            '"') json_value+='\"' ;;
            '\') json_value+='\\' ;;
            *)
                printf -v number '%d' "'$character"
                if ((number < 32)); then
                    printf -v character '\\u%04x' "$number"
                fi
                json_value+=$character
                ;;
        esac
    done
    json_value+='"'
}

notify() {
    local event=$1 original_code=$2 pipeline_code=$3 message payload curl_code
    read_revision
    log "event=notification_summary region=$region revision=$revision status=$event stage=$stage code=$original_code pipeline_exit=$pipeline_code log=$run_log"
    # Bound fields, not log contents: never send stage stdout/stderr to Discord.
    printf -v message 'region=%s\nrevision=%s\nstatus=%s\nstage=%s\ncode=%s\npipeline_exit=%s\nmap_exit=%s\nnotification_problem=%s\nlog=%s' \
        "${region:0:16}" "${revision:0:80}" "$event" "$stage" \
        "$original_code" "$pipeline_code" "$map_code" "$notification_problem" "${run_log:0:900}"
    if [[ -z ${TAVERN_DISCORD_WEBHOOK_URL:-} ]]; then
        notification_problem=unconfigured
        log "event=notification status=unconfigured summary=$event (TAVERN_DISCORD_WEBHOOK_URL unset; no delivery)"
        return 0
    fi
    json_escape "$message"
    payload="{\"content\":$json_value}"
    # Ignore curlrc, never retry, and suppress response/diagnostics that could leak URL.
    curl --disable --silent --fail --connect-timeout 5 --max-time 15 --retry 0 \
        --output /dev/null -H 'Content-Type: application/json' \
        --data-binary "$payload" "$TAVERN_DISCORD_WEBHOOK_URL" >/dev/null 2>&1
    curl_code=$?
    if ((curl_code != 0)); then
        notification_problem=failed
        log "event=notification status=failed summary=$event code=$curl_code"
    else
        log "event=notification status=sent summary=$event"
    fi
    return 0
}

finish() {
    local pipeline_code=$? final_status
    trap - EXIT HUP INT TERM
    if ((stage_active)); then
        stage_code=$pipeline_code
        log "event=stage_end stage=$stage code=$stage_code elapsed_seconds=$((SECONDS-stage_started)) interrupted=1"
    fi
    if [[ $status == running ]]; then
        status=failed
        # A sourced setup script may exit early with zero: no completed pipeline.
        ((pipeline_code != 0)) || pipeline_code=70
    elif ((pipeline_code != 0)); then
        status=failed
    fi
    read_revision
    log "event=pipeline_end region=$region revision=$revision status=$status stage=$stage code=$stage_code pipeline_exit=$pipeline_code map_exit=$map_code log=$run_log"
    # Normal no-op outcomes keep their run logs without notification degradation.
    if [[ $status != no_changes && $status != skipped_lock ]]; then
        notify "$status" "$stage_code" "$pipeline_code"
    fi
    final_status=$status
    if [[ $notification_problem != none ]]; then
        final_status="${status}_notification_${notification_problem}"
    fi
    # Notification degradation is explicit; it never replaces a pipeline exit code.
    log "event=run_end region=$region revision=$revision status=$final_status stage=$stage code=$stage_code pipeline_exit=$pipeline_code map_exit=$map_code elapsed_seconds=$((SECONDS-run_started)) log=$run_log"
    exit "$pipeline_code"
}

trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

run_stage() {
    stage=$1
    shift
    stage_started=$SECONDS
    stage_active=1
    log "event=stage_start stage=$stage"
    "$@"
    stage_code=$?
    stage_active=0
    log "event=stage_end stage=$stage code=$stage_code elapsed_seconds=$((SECONDS-stage_started))"
    return "$stage_code"
}

required_stage() {
    run_stage "$@"
    local result=$?
    if ((result != 0)); then
        exit "$result"
    fi
    return 0
}

resolve_root() {
    repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
}

prepare_log() {
    local result stamp
    mkdir -p -- "$repo_root/logs"
    result=$?
    ((result == 0)) || return "$result"
    printf -v stamp '%(%Y%m%dT%H%M%S)T' -1
    run_log=$(mktemp "$repo_root/logs/cron-${region}.${stamp}.XXXXXX.log")
    result=$?
    ((result == 0)) || return "$result"
    printf 'region=%s log=%s\n' "$region" "$run_log"
    exec >> "$run_log" 2>&1
    result=$?
    ((result == 0)) || return "$result"
    log "event=run_start region=$region repo_root=$repo_root log=$run_log setup_root_code=0"
}

open_lock() {
    # Append/open only: never truncate, replace, unlink, or use a per-region inode.
    exec 9>> "$repo_root/logs/cron-tos.lock"
}

case $region in
    itos|jtos|ktos) ;;
    *) log 'event=setup_error stage=setup_region allowed=itos,jtos,ktos'; stage_code=64; exit 64 ;;
esac
if (($# != 1)); then
    stage_code=64
    exit 64
fi

required_stage setup_root resolve_root
required_stage setup_log prepare_log
required_stage setup_lock open_lock
# A private contention code distinguishes an occupied lock from flock errors.
run_stage lock flock -n -E 200 9
lock_code=$?
if ((lock_code == 200)); then
    status=skipped_lock
    log "event=skipped_lock region=$region reason=shared_lock_busy"
    exit 0
elif ((lock_code != 0)); then
    exit "$lock_code"
fi

# FD 9 remains open through every stage and EXIT notification/summary.
required_stage setup_cwd cd -- "$repo_root"
required_stage setup_venv source "$repo_root/TavernofSoul/itos/3.8/bin/activate"
required_stage downloader_cwd cd -- "$repo_root/downloader"
run_stage downloader python downloader.py "$region"
download_code=$?
case $download_code in
    0) ;;
    1) status=no_changes; exit 0 ;;
    *) exit "$download_code" ;;
esac

required_stage map_cwd cd -- "$repo_root/parser_tidy"
run_stage map python2.7 map_image.py "$region"
map_code=$?
if ((map_code != 0)); then
    log "event=map_warning code=$map_code action=continue_parser_and_import"
fi

required_stage parser_venv source "$repo_root/TavernofSoul/itos/3.8/bin/activate"
required_stage parser_logging python -c 'import logging; logging.basicConfig(level=logging.INFO)'
required_stage parser python main.py "$region"
required_stage import_cwd cd -- "$repo_root/TavernofSoul"
required_stage import python "manage_${region}.py" importAll
if ((map_code != 0)); then
    status=completed_with_warnings
else
    status=completed
fi
exit 0
