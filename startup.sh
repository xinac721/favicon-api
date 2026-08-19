#!/usr/bin/env sh

set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"

for runtime_dir in "$project_dir/data" "$project_dir/logs"; do
    mkdir -p "$runtime_dir"
    if [ ! -w "$runtime_dir" ]; then
        echo "Error: runtime directory is not writable: $runtime_dir" >&2
        exit 1
    fi
done

if command -v gunicorn >/dev/null 2>&1; then
    gunicorn_bin=$(command -v gunicorn)
elif [ -x "$project_dir/.venv/bin/gunicorn" ]; then
    gunicorn_bin="$project_dir/.venv/bin/gunicorn"
else
    echo "Error: gunicorn is not installed; install requirements.txt first" >&2
    exit 127
fi

exec "$gunicorn_bin" -c conf/gunicorn.conf.py "$@" main:app
