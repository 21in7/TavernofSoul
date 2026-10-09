#!/usr/bin/env bash
# Create a disposable server; never use existing containers or host DB services.
set -euo pipefail
python="${1:-python3}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
report_dir="${HARNESS_REPORT_DIR:-$root/logs/harness}"
phase=environment
container_id=''
removed=false
cleanup() {
    local status=$?
    trap - EXIT
    if [[ -n "$container_id" ]]; then
        if "${docker_command[@]}" rm --force "$container_id" >/dev/null; then
            removed=true
        else
            status=1
        fi
    fi
    write_result "$status" || status=1
    exit "$status"
}
write_result() {
    "$python" - "$report_dir" "$phase" "$1" "$container_id" "$removed" <<'PY'
import json, sys
from pathlib import Path
from harness.runner import write_report
directory, phase, code, container, removed = sys.argv[1:]
status = 'running' if code == 'running' else ('passed' if code == '0' else 'failed')
report = {'status': status, 'phase': phase, 'container': container,
          'container_removed': removed == 'true'}
if code != 'running':
    report['exit_code'] = int(code)
if phase == 'tests' and code != 'running':
    check = Path(directory) / 'check-mysql.json'
    if check.is_file():
        report['checks'] = {'mysql': json.loads(check.read_text())}
write_report(Path(directory) / 'mysql-container.json', report)
PY
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
write_result running
"$python" -m harness doctor --report-dir "$report_dir"
read -r -a docker_command <<< "${HARNESS_DOCKER:-docker}"
container="tavern-harness-mysql-$("$python" -c 'import uuid; print(uuid.uuid4().hex)')"
image='mysql:8.4@sha256:6ea90827b1100f8f2ae306a539f86d2c264a26ed435a2a9f75551dd5c3aeb242'
phase=server-create
echo 'Starting disposable MySQL harness container ...'
container_id="$("${docker_command[@]}" create --name "$container" \
    --publish 127.0.0.1::3306 --tmpfs /var/lib/mysql:rw,nosuid,nodev,size=1g \
    --env MYSQL_ROOT_PASSWORD=harness-root-only --env MYSQL_DATABASE=tavern_harness \
    --env MYSQL_USER=tavern_harness --env MYSQL_PASSWORD=harness-only "$image")"
phase=server-start
"${docker_command[@]}" start "$container_id" >/dev/null
phase=server-ready
ready=false
for ((attempt=0; attempt<120; attempt++)); do
    if "${docker_command[@]}" exec "$container" sh -c \
        'MYSQL_PWD="$MYSQL_PASSWORD" mysql -h127.0.0.1 -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT 1"' \
        >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
if [[ "$ready" != true ]]; then
    "${docker_command[@]}" logs "$container"
    echo 'MySQL harness container did not become ready' >&2
    exit 1
fi
phase=account
"${docker_command[@]}" exec -i "$container" sh -c \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot' < harness/mysql-init.sql
mapped_port="$("${docker_command[@]}" port "$container" 3306/tcp)"
export HARNESS_MYSQL_HOST=127.0.0.1 HARNESS_MYSQL_PORT="${mapped_port##*:}"
export HARNESS_MYSQL_USER=tavern_harness HARNESS_MYSQL_PASSWORD=harness-only
phase=tests
rm -f -- "$report_dir/check-mysql.json"
"$python" -m harness check-mysql --report-dir "$report_dir"
