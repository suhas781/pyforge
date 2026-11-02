"""Deterministic tests for environment-backed configuration."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pyforge import (
    InvalidEnvironmentError,
    MissingEnvironmentError,
    OutOfRangeEnvironmentError,
    get_env,
    get_env_bool,
    get_env_float,
    get_env_int,
)

_SECRETS = ("password=supersecret", "token=abc123", "api_key=private-key")


def test_get_env_returns_the_stored_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYFORGE_NAME", "  café 请求  ")
    assert get_env("PYFORGE_NAME") == "  café 请求  "


def test_get_env_missing_optional_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYFORGE_MISSING", raising=False)
    assert get_env("PYFORGE_MISSING") is None


def test_get_env_missing_required_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(MissingEnvironmentError, match="DATABASE_URL is required but not set"):
        get_env("DATABASE_URL", required=True)


def test_get_env_default_is_used_only_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYFORGE_MODE", raising=False)
    assert get_env("PYFORGE_MODE", default="local") == "local"
    monkeypatch.setenv("PYFORGE_MODE", "prod")
    assert get_env("PYFORGE_MODE", default="local") == "prod"


def test_get_env_empty_string_is_preserved_until_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYFORGE_EMPTY", "")
    assert get_env("PYFORGE_EMPTY") == ""
    with pytest.raises(MissingEnvironmentError, match="PYFORGE_EMPTY is required but empty"):
        get_env("PYFORGE_EMPTY", required=True)


def test_get_env_preserves_whitespace_only_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYFORGE_SPACE", " \t ")
    assert get_env("PYFORGE_SPACE") == " \t "
    assert get_env("PYFORGE_SPACE", required=True) == " \t "


def test_get_env_rejects_non_string_names_and_bad_options() -> None:
    with pytest.raises(TypeError, match="name must be a string"):
        get_env(12)  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="must not be empty"):
        get_env("")
    with pytest.raises(TypeError, match="required must be a boolean"):
        get_env("PYFORGE_MODE", required=1)  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="cannot be required and have a default"):
        get_env("PYFORGE_MODE", default="local", required=True)  # type: ignore[call-overload]
    with pytest.raises(InvalidEnvironmentError, match="default must be a string"):
        get_env("PYFORGE_MODE", default=1)  # type: ignore[call-overload]


def test_get_env_reads_again_when_the_environment_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYFORGE_MODE", "first")
    assert get_env("PYFORGE_MODE") == "first"
    monkeypatch.setenv("PYFORGE_MODE", "second")
    assert get_env("PYFORGE_MODE") == "second"


@pytest.mark.parametrize("text", ["true", "1", "yes", "on", "TRUE", " Yes "])
def test_get_env_bool_accepts_true_values(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setenv("DEBUG", text)
    assert get_env_bool("DEBUG") is True


@pytest.mark.parametrize("text", ["false", "0", "no", "off", "False", "\tOFF\n"])
def test_get_env_bool_accepts_false_values(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setenv("DEBUG", text)
    assert get_env_bool("DEBUG") is False


@pytest.mark.parametrize("text", ["maybe", "2", "y", "n", "", "   ", "truee"])
def test_get_env_bool_rejects_unknown_values(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setenv("DEBUG", text)
    with pytest.raises(InvalidEnvironmentError, match="DEBUG must be a boolean") as caught:
        get_env_bool("DEBUG")
    assert str(caught.value) == ("DEBUG must be a boolean: true, 1, yes, on, false, 0, no, or off")


def test_get_env_bool_missing_uses_a_boolean_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEBUG", raising=False)
    assert get_env_bool("DEBUG", default=False) is False
    assert get_env_bool("DEBUG") is None
    with pytest.raises(MissingEnvironmentError, match="DEBUG is required but not set"):
        get_env_bool("DEBUG", required=True)


def test_get_env_bool_rejects_invalid_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEBUG", raising=False)
    with pytest.raises(InvalidEnvironmentError, match="default must be a boolean"):
        get_env_bool("DEBUG", default=1)  # type: ignore[call-overload]
    with pytest.raises(InvalidEnvironmentError, match="default must be a boolean"):
        get_env_bool("DEBUG", default="true")  # type: ignore[call-overload]


@pytest.mark.parametrize(("text", "expected"), [("42", 42), ("-7", -7), ("0", 0), ("  +8  ", 8)])
def test_get_env_int_parses_decimal_integers(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    expected: int,
) -> None:
    monkeypatch.setenv("PORT", text)
    assert get_env_int("PORT") == expected


@pytest.mark.parametrize("text", ["1.5", "1e2", "1_000", "0x10", "abc", "", "   ", "++1"])
def test_get_env_int_rejects_non_integers(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setenv("PORT", text)
    with pytest.raises(InvalidEnvironmentError, match="PORT must be an integer"):
        get_env_int("PORT")


def test_get_env_int_bounds_are_inclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "1")
    assert get_env_int("PORT", minimum=1, maximum=65535) == 1
    monkeypatch.setenv("PORT", "65535")
    assert get_env_int("PORT", minimum=1, maximum=65535) == 65535
    monkeypatch.setenv("PORT", "0")
    with pytest.raises(OutOfRangeEnvironmentError, match="from 1 to 65535"):
        get_env_int("PORT", minimum=1, maximum=65535)
    monkeypatch.setenv("PORT", "65536")
    with pytest.raises(OutOfRangeEnvironmentError, match="from 1 to 65535"):
        get_env_int("PORT", minimum=1, maximum=65535)


def test_get_env_int_supports_one_bound_and_a_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    assert get_env_int("PORT", default=8000, minimum=1, maximum=65535) == 8000
    monkeypatch.setenv("PORT", "9")
    with pytest.raises(OutOfRangeEnvironmentError, match="greater than or equal to 10"):
        get_env_int("PORT", minimum=10)
    with pytest.raises(OutOfRangeEnvironmentError, match="less than or equal to 8"):
        get_env_int("PORT", maximum=8)
    monkeypatch.delenv("PORT", raising=False)
    with pytest.raises(MissingEnvironmentError, match="PORT is required but not set"):
        get_env_int("PORT", required=True)


def test_get_env_int_rejects_invalid_and_boolean_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    with pytest.raises(InvalidEnvironmentError, match="default must be an integer"):
        get_env_int("PORT", default=True)
    with pytest.raises(InvalidEnvironmentError, match="default must be an integer"):
        get_env_int("PORT", default=False)
    with pytest.raises(InvalidEnvironmentError, match="default must be an integer"):
        get_env_int("PORT", default=1.5)  # type: ignore[call-overload]
    with pytest.raises(OutOfRangeEnvironmentError, match="PORT default"):
        get_env_int("PORT", default=0, minimum=1)
    with pytest.raises(TypeError, match="minimum must be an integer"):
        get_env_int("PORT", minimum=True)
    with pytest.raises(ValueError, match="minimum cannot be greater than maximum"):
        get_env_int("PORT", minimum=5, maximum=1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1.5", 1.5), ("-2.25", -2.25), ("0", 0.0), ("  +0.5  ", 0.5), ("1e-3", 0.001), (".5", 0.5)],
)
def test_get_env_float_parses_finite_numbers(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    expected: float,
) -> None:
    monkeypatch.setenv("RATIO", text)
    assert get_env_float("RATIO") == expected


@pytest.mark.parametrize(
    "text",
    [
        "abc",
        "1.2.3",
        "nan",
        "NaN",
        "inf",
        "+inf",
        "-inf",
        "Infinity",
        "-Infinity",
        "1e309",
        "1_000",
    ],
)
def test_get_env_float_rejects_non_finite_text(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setenv("RATIO", text)
    with pytest.raises(InvalidEnvironmentError, match="finite floating-point") as caught:
        get_env_float("RATIO")
    assert text not in str(caught.value)
    assert text not in repr(caught.value)


def test_get_env_float_bounds_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATIO", "0.5")
    assert get_env_float("RATIO", minimum=0, maximum=1) == 0.5
    monkeypatch.setenv("RATIO", "0")
    assert get_env_float("RATIO", minimum=0, maximum=1) == 0.0
    monkeypatch.setenv("RATIO", "1")
    assert get_env_float("RATIO", minimum=0, maximum=1) == 1.0
    monkeypatch.setenv("RATIO", "-0.1")
    with pytest.raises(OutOfRangeEnvironmentError, match="from 0.0 to 1.0"):
        get_env_float("RATIO", minimum=0, maximum=1)
    monkeypatch.setenv("RATIO", "1.1")
    with pytest.raises(OutOfRangeEnvironmentError, match="from 0.0 to 1.0"):
        get_env_float("RATIO", minimum=0, maximum=1)
    monkeypatch.delenv("RATIO", raising=False)
    assert get_env_float("RATIO", default=1, minimum=0, maximum=2) == 1.0
    with pytest.raises(MissingEnvironmentError, match="RATIO is required but not set"):
        get_env_float("RATIO", required=True)
    with pytest.raises(InvalidEnvironmentError, match="default must be a finite number"):
        get_env_float("RATIO", default=float("nan"))
    with pytest.raises(InvalidEnvironmentError, match="default must be a finite number"):
        get_env_float("RATIO", default=float("inf"))
    with pytest.raises(InvalidEnvironmentError, match="default must be a finite number"):
        get_env_float("RATIO", default=True)
    with pytest.raises(InvalidEnvironmentError, match="default must be a finite number"):
        get_env_float("RATIO", default="1.5")  # type: ignore[call-overload]
    with pytest.raises(OutOfRangeEnvironmentError, match="RATIO default"):
        get_env_float("RATIO", default=-1, minimum=0)
    with pytest.raises(ValueError, match="minimum must be a finite number"):
        get_env_float("RATIO", minimum=float("nan"))
    with pytest.raises(TypeError, match="maximum must be a finite number"):
        get_env_float("RATIO", maximum="1")  # type: ignore[call-overload]


@pytest.mark.parametrize("secret", _SECRETS)
def test_exceptions_do_not_contain_secret_values(
    monkeypatch: pytest.MonkeyPatch,
    secret: str,
) -> None:
    monkeypatch.setenv("API_TOKEN", secret)
    with pytest.raises(InvalidEnvironmentError) as invalid:
        get_env_int("API_TOKEN")
    with pytest.raises(InvalidEnvironmentError) as invalid_bool:
        get_env_bool("API_TOKEN")
    with pytest.raises(InvalidEnvironmentError) as invalid_float:
        get_env_float("API_TOKEN")
    for caught in (invalid, invalid_bool, invalid_float):
        rendered = " ".join(
            (
                str(caught.value),
                repr(caught.value),
                str(caught.value.__cause__),
                str(caught.value.__context__),
                *(str(arg) for arg in caught.value.args),
            )
        )
        assert secret not in rendered
        assert "supersecret" not in rendered
        assert "abc123" not in rendered
        assert "private-key" not in rendered


def test_out_of_range_errors_omit_the_stored_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "99999")
    with pytest.raises(OutOfRangeEnvironmentError) as caught:
        get_env_int("PORT", minimum=1, maximum=10)
    rendered = f"{caught.value} {caught.value!r}"
    assert "99999" not in rendered
    assert caught.value.__cause__ is None


def test_readers_do_not_modify_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYFORGE_SAMPLE", "kept")
    monkeypatch.delenv("PYFORGE_ABSENT", raising=False)
    before = dict(os.environ)
    assert get_env("PYFORGE_SAMPLE") == "kept"
    assert get_env("PYFORGE_ABSENT") is None
    get_env_bool("PYFORGE_ABSENT", default=False)
    get_env_int("PYFORGE_ABSENT", default=1)
    get_env_float("PYFORGE_ABSENT", default=1.5)
    with pytest.raises(MissingEnvironmentError):
        get_env("PYFORGE_ABSENT", required=True)
    assert dict(os.environ) == before


def test_import_does_not_read_environment_dotenv_or_logging(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=password=supersecret\n", encoding="utf-8")
    script = tmp_path / "check_import.py"
    script.write_text(
        "\n".join(
            (
                "import logging",
                "import os",
                "import sys",
                "before = dict(os.environ)",
                "root = logging.getLogger()",
                "handlers = list(root.handlers)",
                "level = root.level",
                "disabled = root.disabled",
                "import pyforge.config",
                "assert dict(os.environ) == before",
                "assert pyforge.config.get_env('DATABASE_URL') is None",
                "assert 'dotenv' not in sys.modules",
                "assert list(root.handlers) == handlers",
                "assert root.level == level",
                "assert root.disabled is disabled",
            )
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_logged_configuration_errors_do_not_gain_secret_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_TOKEN", "token=abc123")
    with pytest.raises(InvalidEnvironmentError) as caught:
        get_env_int("API_TOKEN")
    from pyforge import JsonFormatter

    record = logging.LogRecord(
        "pyforge.test",
        logging.ERROR,
        __file__,
        1,
        str(caught.value),
        (),
        None,
    )
    rendered = JsonFormatter().format(record)
    assert "abc123" not in rendered
    assert "API_TOKEN must be an integer" in rendered
