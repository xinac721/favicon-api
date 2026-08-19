from contextlib import contextmanager
import os
import threading

try:
    import fcntl
except ImportError:  # pragma: no cover - Gunicorn production runs on Unix.
    fcntl = None


_thread_lock = threading.Lock()


@contextmanager
def _locked(path: str):
    with _thread_lock:
        with open(f'{path}.lock', 'a+b') as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def append_rotating_line(path: str, line: str, max_bytes: int) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    line_size = len(line.encode('utf-8'))
    if line_size > max_bytes:
        return

    with _locked(path):
        current_size = os.path.getsize(path) if os.path.exists(path) else 0
        if current_size and current_size + line_size > max_bytes:
            os.replace(path, f'{path}.1')
        with open(path, 'a', encoding='utf-8') as referer_file:
            referer_file.write(line)


def read_text(path: str, max_bytes: int) -> str | None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with _locked(path):
        if not os.path.exists(path):
            return None
        with open(path, 'rb') as referer_file:
            return referer_file.read(max_bytes).decode('utf-8', errors='replace')


def read_referers(path: str, max_bytes: int, unique: bool = False) -> str | None:
    content = read_text(path, max_bytes)
    if not content or not unique:
        return content
    lines = {line.strip() for line in content.splitlines() if line.strip()}
    return '\n'.join(sorted(lines))
