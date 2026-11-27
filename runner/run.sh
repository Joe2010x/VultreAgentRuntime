#!/usr/bin/env bash
set -euo pipefail

mode=${1:-chart}
case "$mode" in
    chart|generated|timeout-test) ;;
    *) printf 'Unknown runner mode: %s\n' "$mode" >&2; exit 2 ;;
esac

if [[ "$mode" == generated && $# -ne 3 ]] ||
   [[ "$mode" == chart && $# -gt 2 ]] ||
   [[ "$mode" == timeout-test && $# -gt 1 ]]; then
    printf 'Usage: %s [chart [csv-path] | generated csv-path script-path | timeout-test]\n' "$0" >&2
    exit 2
fi

image=vultre-agent-runner:local
runner_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ "${VULTRE_PREBUILT:-0}" != 1 ]]; then
    docker build -t "$image" "$runner_dir"
fi
runtime=()
if [[ -n "${VULTRE_SANDBOX_RUNTIME:-}" ]]; then
    runtime=(--runtime "$VULTRE_SANDBOX_RUNTIME")
fi

container="vultre-task-$(cat /proc/sys/kernel/random/uuid)"
temporary_output=
temporary_log=
container_id=
cleanup() {
    if [[ -n "$temporary_output" ]]; then
        rm -f -- "$temporary_output"
    fi
    if [[ -n "$temporary_log" ]]; then
        rm -f -- "$temporary_log"
    fi
    if [[ -n "$container_id" ]] && ! docker rm -f "$container_id" >/dev/null; then
        printf 'Could not confirm removal of %s\n' "$container" >&2
        return 1
    fi
    container_id=
}
trap 'status=$?; cleanup || status=1; exit "$status"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

command=(python /app/chart.py)
mount=()
if [[ -n "${2:-}" ]]; then
    mount=(--mount "type=bind,source=$2,target=/input.csv,readonly")
    command+=(/input.csv)
fi
if [[ "$mode" == generated ]]; then
    mount+=(--mount "type=bind,source=$3,target=/generated.py,readonly")
    command=(python /generated.py)
fi
deadline=20s
if [[ "$mode" == timeout-test ]]; then
    command=(python /app/containment_check.py)
    deadline=3s
fi

container_id=$(docker create --name "$container" --label app=vultre-agent-runner \
    --pull never --network none --read-only --user 65532:65532 "${runtime[@]}" \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
    --memory 256m --memory-swap 256m --cpus 1 --pids-limit 32 \
    --cap-drop ALL --security-opt no-new-privileges --log-driver none \
    "${mount[@]}" "$image" "${command[@]}")

temporary_output=$(mktemp ./sales-chart.XXXXXXXX)
temporary_log=$(mktemp ./sales-log.XXXXXXXX)
status=0
(
    ulimit -f 4096
    exec timeout --kill-after=2s "$deadline" docker start -a "$container_id"
) >"$temporary_output" 2>"$temporary_log" || status=$?
tail -c 12000 -- "$temporary_log" >&2
case "$status" in
    124)
        if [[ "$mode" == timeout-test ]]; then
            if ! grep -Fxq "Vultr key and Docker socket are absent. Starting the timeout test." "$temporary_output"; then
                printf 'Containment check did not finish before the deadline.\n' >&2
                exit 1
            fi
            cat -- "$temporary_output"
            cleanup
            printf 'Timed out after %s. Container removed.\n' "$deadline"
            exit 0
        fi
        printf 'Chart run timed out after %s.\n' "$deadline" >&2
        exit "$status"
        ;;
    0) ;;
    *) exit "$status" ;;
esac

if [[ "$mode" == timeout-test ]]; then
    printf 'The test process exited before the timeout.\n' >&2
    exit 1
fi
if [[ ! -s "$temporary_output" ]]; then
    printf 'The chart process produced no output.\n' >&2
    exit 1
fi
chmod 0644 -- "$temporary_output"
mv -- "$temporary_output" sales-chart.png
printf 'Wrote sales-chart.png\n'
