#!/usr/bin/env sh

set -eu

for runtime_dir in /app/data /app/logs; do
    mkdir -p "$runtime_dir"
done

if [ "$(id -u)" -eq 0 ]; then
    case "${TZ:-Asia/Shanghai}" in
        ''|/*|*..*)
            echo "Error: invalid TZ value: ${TZ:-}" >&2
            exit 1
            ;;
    esac
    timezone_file="/usr/share/zoneinfo/${TZ:-Asia/Shanghai}"
    if [ ! -f "$timezone_file" ]; then
        echo "Error: timezone data not found: ${TZ:-Asia/Shanghai}" >&2
        exit 1
    fi
    ln -snf "$timezone_file" /etc/localtime
    printf '%s\n' "${TZ:-Asia/Shanghai}" > /etc/timezone

    app_owner="$(id -u app):$(id -g app)"
    permissions_need_update=0
    for runtime_dir in /app/data /app/logs; do
        if [ "$(stat -c '%u:%g' "$runtime_dir")" != "$app_owner" ] \
                || ! gosu app test -w "$runtime_dir"; then
            permissions_need_update=1
            break
        fi
    done
    if [ "$permissions_need_update" -eq 1 ]; then
        chown -R app:app /app/data /app/logs
        gosu app chmod -R u+rwX /app/data /app/logs
    fi
    for runtime_dir in /app/data /app/logs; do
        if ! gosu app test -w "$runtime_dir"; then
            echo "Error: runtime directory is not writable by app: $runtime_dir" >&2
            exit 1
        fi
    done
    if [ "${1:-}" = "gunicorn" ]; then
        if ! (umask 077 && /usr/bin/env -0 > /run/blacklist-update.env); then
            echo "Warning: could not snapshot environment for blacklist cron; using defaults" >&2
        fi
        if ! /usr/sbin/cron; then
            echo "Warning: blacklist cron failed to start; continuing without automatic updates" >&2
        fi
    fi
    exec gosu app "$@"
fi

for runtime_dir in /app/data /app/logs; do
    if [ ! -w "$runtime_dir" ]; then
        echo "Error: runtime directory is not writable: $runtime_dir" >&2
        exit 1
    fi
done

exec "$@"
