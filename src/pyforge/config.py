"""Environment readers that validate values when called.

Importing this module does not read ``os.environ``, load ``.env`` files, or
change logging. Each function looks up its variable on that call and does not
cache the result or modify the process environment.

Exception messages include the variable name and the expected type. They do
not include the environment value or the default.
"""

from __future__ import annotations

import math
import os
import re
from typing import Literal, overload

_INT_TEXT = re.compile(r"[+-]?[0-9]+")
_FLOAT_TEXT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_TRUE_TEXT = frozenset({"true", "1", "yes", "on"})
_FALSE_TEXT = frozenset({"false", "0", "no", "off"})


class MissingEnvironmentError(Exception):
    """A required environment variable is unset or exactly empty."""


class InvalidEnvironmentError(ValueError):
    """A value or default cannot be parsed as the requested type.

    Out-of-range numbers use ``OutOfRangeEnvironmentError`` instead. That
    class is also a ``ValueError``, but it is not a subclass of this one.
    """


class OutOfRangeEnvironmentError(ValueError):
    """A numeric value or default is outside the requested inclusive bounds."""


@overload
def get_env(name: str, *, default: str, required: Literal[False] = False) -> str: ...


@overload
def get_env(name: str, *, default: None = None, required: Literal[True]) -> str: ...


@overload
def get_env(name: str, *, default: None = None, required: Literal[False] = False) -> str | None: ...


def get_env(
    name: str,
    *,
    default: str | None = None,
    required: bool = False,
) -> str | None:
    """Return the environment string exactly as stored.

    A missing variable returns ``default`` when one was passed, ``None`` when
    it was not, and raises ``MissingEnvironmentError`` when ``required`` is
    true. A required variable set to ``""`` raises the same error. Any other
    stored string, including whitespace, is returned unchanged.
    """
    checked, is_required = _prepare(name, required=required, default=default)
    if default is not None and type(default) is not str:
        raise InvalidEnvironmentError(f"{checked} default must be a string")
    value = os.environ.get(checked)
    if value is None:
        if is_required:
            raise MissingEnvironmentError(f"{checked} is required but not set")
        return default
    if is_required and value == "":
        raise MissingEnvironmentError(f"{checked} is required but empty")
    return value


@overload
def get_env_bool(name: str, *, default: bool, required: Literal[False] = False) -> bool: ...


@overload
def get_env_bool(name: str, *, default: None = None, required: Literal[True]) -> bool: ...


@overload
def get_env_bool(
    name: str,
    *,
    default: None = None,
    required: Literal[False] = False,
) -> bool | None: ...


def get_env_bool(
    name: str,
    *,
    default: bool | None = None,
    required: bool = False,
) -> bool | None:
    """Return a boolean parsed from the environment.

    After surrounding whitespace is removed, these case-insensitive values are
    accepted: ``true``, ``1``, ``yes``, and ``on``; ``false``, ``0``, ``no``,
    and ``off``. Any other text, including a blank value, raises
    ``InvalidEnvironmentError``.
    """
    checked, is_required = _prepare(name, required=required, default=default)
    if default is not None and type(default) is not bool:
        raise InvalidEnvironmentError(f"{checked} default must be a boolean")
    value = os.environ.get(checked)
    if value is None:
        if is_required:
            raise MissingEnvironmentError(f"{checked} is required but not set")
        return default
    token = value.strip().casefold()
    if token in _TRUE_TEXT:
        return True
    if token in _FALSE_TEXT:
        return False
    raise InvalidEnvironmentError(
        f"{checked} must be a boolean: true, 1, yes, on, false, 0, no, or off"
    )


@overload
def get_env_int(
    name: str,
    *,
    default: int,
    required: Literal[False] = False,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int: ...


@overload
def get_env_int(
    name: str,
    *,
    default: None = None,
    required: Literal[True],
    minimum: int | None = None,
    maximum: int | None = None,
) -> int: ...


@overload
def get_env_int(
    name: str,
    *,
    default: None = None,
    required: Literal[False] = False,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None: ...


def get_env_int(
    name: str,
    *,
    default: int | None = None,
    required: bool = False,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    """Return a base-10 integer from the environment.

    Surrounding whitespace is removed. A leading ``+`` or ``-`` is accepted.
    Decimal points, exponents, underscores, and other bases are rejected.
    Leading zeros are still decimal, so ``007`` is ``7``. Booleans are
    rejected as defaults and as bounds. Bounds are inclusive.
    """
    checked, is_required = _prepare(name, required=required, default=default)
    lower = _int_bound("minimum", minimum)
    upper = _int_bound("maximum", maximum)
    _ordered(lower, upper)
    parsed_default = None if default is None else _int_default(checked, default)
    _within_int(checked, parsed_default, lower, upper, default=True)
    value = os.environ.get(checked)
    if value is None:
        if is_required:
            raise MissingEnvironmentError(f"{checked} is required but not set")
        return parsed_default
    parsed = _parse_int(checked, value)
    _within_int(checked, parsed, lower, upper, default=False)
    return parsed


@overload
def get_env_float(
    name: str,
    *,
    default: float | int,
    required: Literal[False] = False,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
) -> float: ...


@overload
def get_env_float(
    name: str,
    *,
    default: None = None,
    required: Literal[True],
    minimum: float | int | None = None,
    maximum: float | int | None = None,
) -> float: ...


@overload
def get_env_float(
    name: str,
    *,
    default: None = None,
    required: Literal[False] = False,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
) -> float | None: ...


def get_env_float(
    name: str,
    *,
    default: float | int | None = None,
    required: bool = False,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
) -> float | None:
    """Return a finite float from the environment.

    Surrounding whitespace is removed. Decimal values and scientific notation
    are accepted. ``NaN``, infinities, underscores, and non-numeric text are
    rejected. Integer defaults are converted with ``float``. Bounds are
    inclusive and must themselves be finite.
    """
    checked, is_required = _prepare(name, required=required, default=default)
    lower = _float_bound("minimum", minimum)
    upper = _float_bound("maximum", maximum)
    _ordered(lower, upper)
    parsed_default = None if default is None else _float_default(checked, default)
    _within_float(checked, parsed_default, lower, upper, default=True)
    value = os.environ.get(checked)
    if value is None:
        if is_required:
            raise MissingEnvironmentError(f"{checked} is required but not set")
        return parsed_default
    parsed = _parse_float(checked, value)
    _within_float(checked, parsed, lower, upper, default=False)
    return parsed


def _prepare(name: object, *, required: object, default: object) -> tuple[str, bool]:
    if not isinstance(name, str):
        raise TypeError("environment variable name must be a string")
    if name == "":
        raise ValueError("environment variable name must not be empty")
    if type(required) is not bool:
        raise TypeError("required must be a boolean")
    if required and default is not None:
        raise ValueError(f"{name} cannot be required and have a default")
    return name, required


def _int_bound(label: str, bound: object) -> int | None:
    if bound is None:
        return None
    if type(bound) is not int:
        raise TypeError(f"{label} must be an integer")
    return bound


def _float_bound(label: str, bound: object) -> float | None:
    if bound is None:
        return None
    if type(bound) is bool or not isinstance(bound, int | float):
        raise TypeError(f"{label} must be a finite number")
    if isinstance(bound, float) and not math.isfinite(bound):
        raise ValueError(f"{label} must be a finite number")
    return float(bound)


def _ordered(minimum: int | float | None, maximum: int | float | None) -> None:
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("minimum cannot be greater than maximum")


def _int_default(name: str, default: object) -> int:
    if type(default) is not int:
        raise InvalidEnvironmentError(f"{name} default must be an integer")
    return default


def _float_default(name: str, default: object) -> float:
    if type(default) is bool or not isinstance(default, int | float):
        raise InvalidEnvironmentError(f"{name} default must be a finite number")
    if isinstance(default, float) and not math.isfinite(default):
        raise InvalidEnvironmentError(f"{name} default must be a finite number")
    return float(default)


def _parse_int(name: str, value: str) -> int:
    token = value.strip()
    if _INT_TEXT.fullmatch(token) is None:
        raise InvalidEnvironmentError(f"{name} must be an integer")
    return int(token)


def _parse_float(name: str, value: str) -> float:
    token = value.strip()
    if _FLOAT_TEXT.fullmatch(token) is None:
        raise InvalidEnvironmentError(f"{name} must be a finite floating-point number")
    parsed = float(token)
    if not math.isfinite(parsed):
        raise InvalidEnvironmentError(f"{name} must be a finite floating-point number")
    return parsed


def _within_int(
    name: str,
    value: int | None,
    minimum: int | None,
    maximum: int | None,
    *,
    default: bool,
) -> None:
    if value is None:
        return
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise OutOfRangeEnvironmentError(_range_message(name, "integer", minimum, maximum, default))


def _within_float(
    name: str,
    value: float | None,
    minimum: float | None,
    maximum: float | None,
    *,
    default: bool,
) -> None:
    if value is None:
        return
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise OutOfRangeEnvironmentError(
            _range_message(name, "floating-point number", minimum, maximum, default)
        )


def _range_message(
    name: str,
    kind: str,
    minimum: int | float | None,
    maximum: int | float | None,
    default: bool,
) -> str:
    subject = f"{name} default" if default else name
    if minimum is not None and maximum is not None:
        return f"{subject} must be a {kind} from {minimum} to {maximum}"
    if minimum is not None:
        return f"{subject} must be a {kind} greater than or equal to {minimum}"
    return f"{subject} must be a {kind} less than or equal to {maximum}"
