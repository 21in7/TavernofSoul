#!/usr/bin/env bash
# Browser engine only: never mount operating JSON, source trees, credentials or DBs.
set -euo pipefail
python="${1:-python3}"
mode="${2:-check-browser}"
case "$mode" in check-browser|check-site) ;; *) exit 2 ;; esac
suite="${mode#check-}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
report_dir="${HARNESS_REPORT_DIR:-$root/logs/harness}"
phase=environment
container_id=''
removed=false
read -r -a docker_command <<< "${HARNESS_DOCKER:-docker}"
write_result() {
    "$python" - "$report_dir" "$phase" "$1" "$container_id" "$removed" "$suite" <<'PY'
import json, sys
from pathlib import Path
from harness.runner import write_report
directory, phase, code, container, removed, suite = sys.argv[1:]
report = {'status': 'running' if code == 'running' else ('passed' if code == '0' else 'failed'),
          'phase': phase, 'container': container, 'container_removed': removed == 'true'}
if code != 'running':
    report['exit_code'] = int(code)
if phase == 'tests' and code != 'running':
    check = Path(directory) / ('check-' + suite + '.json')
    if check.is_file():
        report['checks'] = {'browser': json.loads(check.read_text())}
write_report(Path(directory) / (suite + '-container.json'), report)
PY
}
cleanup() {
    local status=$?
    trap - EXIT
    if [[ -n "$container_id" ]]; then
        "${docker_command[@]}" logs "$container_id" > "$report_dir/$suite-container.log" 2>&1 || true
        if "${docker_command[@]}" rm --force "$container_id" >/dev/null; then
            removed=true
        else
            status=1
        fi
    fi
    write_result "$status" || status=1
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
write_result running
"$python" -m harness doctor --report-dir "$report_dir"
if [[ ! -f harness/browser/node_modules/playwright/cli.js ]]; then
    echo 'Install browser SDK first: npm ci --prefix harness/browser' >&2
    exit 1
fi
image="$(cat harness/browser/container-image.txt)"
container="tavern-harness-browser-$("$python" -c 'import uuid; print(uuid.uuid4().hex)')"
phase=server-create
container_id="$("${docker_command[@]}" create --name "$container" --init \
    --publish 127.0.0.1::3000 --user "$(id -u):$(id -g)" \
    --read-only --tmpfs /tmp:rw,nosuid,nodev,size=1g --shm-size=1g \
    --cap-drop ALL --security-opt no-new-privileges --workdir /tmp \
    --mount "type=bind,source=$root/harness/browser/node_modules,target=/opt/browser-sdk/node_modules,readonly" \
    "$image" node /opt/browser-sdk/node_modules/playwright/cli.js run-server --host 0.0.0.0 --port 3000)"
phase=server-start
"${docker_command[@]}" start "$container_id" >/dev/null
phase=server-ready
ready=false
for ((attempt=0; attempt<60; attempt++)); do
    if [[ "$("${docker_command[@]}" logs "$container_id" 2>&1)" == *'Listening on'* ]]; then
        ready=true
        break
    fi
    if [[ "$("${docker_command[@]}" inspect --format '{{.State.Running}}' "$container_id")" != true ]]; then
        break
    fi
    sleep 1
done
if [[ "$ready" != true ]]; then
    "${docker_command[@]}" logs "$container_id"
    echo 'Playwright test server did not become ready' >&2
    exit 1
fi
mapped_port="$("${docker_command[@]}" port "$container_id" 3000/tcp)"
export HARNESS_BROWSER_WS_ENDPOINT="ws://127.0.0.1:${mapped_port##*:}/"
phase=tests
rm -f -- "$report_dir/$mode.json"
"$python" -m harness "$mode" --report-dir "$report_dir"
