#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from pathlib import Path


ENVIRONMENT_FILE = Path('/run/blacklist-update.env')
UPDATE_SCRIPT = Path('/app/scripts/update_blacklist.pyc')
UPDATE_COMMAND = (
    '/usr/bin/gosu',
    'app',
    '/usr/local/bin/python',
    str(UPDATE_SCRIPT),
)


def parse_process_environment(content: bytes) -> dict[str, str]:
    environment = {}
    for entry in content.split(b'\0'):
        if not entry or b'=' not in entry:
            continue
        key, value = entry.split(b'=', 1)
        try:
            decoded_key = key.decode('utf-8')
            decoded_value = value.decode('utf-8')
        except UnicodeError:
            continue
        if decoded_key and '\x00' not in decoded_key and '=' not in decoded_key:
            environment[decoded_key] = decoded_value
    return environment


def main() -> None:
    if not UPDATE_SCRIPT.is_file():
        return

    environment = os.environ.copy()
    try:
        environment.update(parse_process_environment(ENVIRONMENT_FILE.read_bytes()))
    except OSError:
        pass
    os.execvpe(UPDATE_COMMAND[0], UPDATE_COMMAND, environment)


if __name__ == '__main__':
    main()
