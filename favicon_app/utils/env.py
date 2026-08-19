import math
import os


_TRUE_VALUES = frozenset(('1', 'true', 'yes', 'on'))
_FALSE_VALUES = frozenset(('0', 'false', 'no', 'off'))


def env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ValueError(f'{name} must be a boolean value')


def env_int(
        name: str,
        default: int,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
) -> int:
    raw_value = os.getenv(name)
    try:
        value = default if raw_value is None else int(raw_value.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f'{name} must be an integer') from exc
    if minimum is not None and value < minimum:
        raise ValueError(f'{name} must be at least {minimum}')
    if maximum is not None and value > maximum:
        raise ValueError(f'{name} must be at most {maximum}')
    return value


def env_float(
        name: str,
        default: float,
        *,
        minimum: float | None = None,
) -> float:
    raw_value = os.getenv(name)
    try:
        value = default if raw_value is None else float(raw_value.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f'{name} must be a number') from exc
    if not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    if minimum is not None and value < minimum:
        raise ValueError(f'{name} must be at least {minimum}')
    return value
