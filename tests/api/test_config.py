"""Settings: environment variables, documented defaults, the gunicorn file and the Render start command."""
import os
import pathlib
import re
import runpy
import subprocess
import sys

import pytest

from tracker import config
from tracker.countries import COUNTRIES

API_DIR = pathlib.Path(__file__).resolve().parents[2] / "api"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 60), ("7", 7), ("0", 0), ("-5", 0), ("abc", 60), ("", 60), ("1.5", 60)],
    ids=["unset", "number", "zero", "negative-means-off", "text", "empty", "decimal"],
)
def test_env_int(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("T_SETTING", raising=False)
    else:
        monkeypatch.setenv("T_SETTING", raw)
    assert config.env_int("T_SETTING", 60) == expected


def imported_value(expression: str, env: dict) -> str:
    """Import the API in a fresh interpreter with `env` set and evaluate `expression`."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("RATE_LIMIT_", "APPLE_", "MAX_PARALLEL", "ADMIN_"))}
    clean["PYTHONPATH"] = os.pathsep.join(filter(None, [str(API_DIR), os.environ.get("PYTHONPATH")]))
    out = subprocess.run([sys.executable, "-c", f"import app; from tracker import config, limits, search; print({expression})"],
                         env={**clean, **env}, capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.mark.parametrize(
    ("variable", "value", "expression", "expected"),
    [
        ("RATE_LIMIT_REQUESTS_PER_MIN", "7", "limits.request_limiter.limit", "7"),
        ("RATE_LIMIT_FETCHES_PER_10MIN", "3", "limits.fetch_limiter.limit", "3"),
        ("RATE_LIMIT_GLOBAL_FETCHES_PER_10MIN", "0", "limits.global_fetch_limiter.limit", "0"),
        ("APPLE_MAX_CONNECTIONS", "12", "config.APPLE_MAX_CONNECTIONS", "12"),
        ("APPLE_MAX_CONNECTIONS", "0", "config.APPLE_MAX_CONNECTIONS", "1"),
        ("APPLE_MAX_CONNECTIONS", "abc", "config.APPLE_MAX_CONNECTIONS", "50"),
        ("MAX_PARALLEL_FETCHES", "5", "(config.MAX_PARALLEL_FETCHES, search.fetch_slots._value)", "(5, 5)"),
        ("MAX_PARALLEL_FETCHES", "0", "config.MAX_PARALLEL_FETCHES", "1"),
        ("ADMIN_TOKEN", "s3cret", "config.ADMIN_TOKEN", "s3cret"),
    ],
)
def test_environment_variable_is_used(variable, value, expression, expected):
    assert imported_value(expression, {variable: value}) == expected


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("MAX_PRODUCT_LENGTH", 80),
        ("RATES_TTL", 30 * 60),
        ("RESULTS_TTL", 6 * 3600),
        ("RESULTS_TTL_SHORT", 5 * 60),
        ("RESULTS_CACHE_MAX", 200),
        ("SLUG_CACHE_MAX", 500),
        ("SLUG_TTL_NOT_FOUND", 3600),
        ("SLUG_TTL_UNSURE", 5 * 60),
        ("SLUG_TTL_FAILED", 60),
        ("APPLE_MAX_CONNECTIONS", 50),
        ("MAX_PARALLEL_FETCHES", 2),
        ("FETCH_SLOT_WAIT", 45),
        ("PRICE_FLOOR_SLACK", 0.8),
    ],
)
def test_documented_default(setting, value):
    assert getattr(config, setting) == value


def test_default_rate_limits():
    limiters = "(limits.request_limiter, limits.fetch_limiter, limits.global_fetch_limiter)"
    assert imported_value(f"[(lim.limit, lim.window) for lim in {limiters}]", {}) == "[(60, 60), (20, 600), (60, 600)]"


def test_one_connection_per_store_by_default():
    assert config.APPLE_MAX_CONNECTIONS == len(COUNTRIES) == 50


# ---------------------------------------------------------------------------
# api/gunicorn.conf.py and api/render.yaml
# ---------------------------------------------------------------------------

def gunicorn_settings(monkeypatch, web_threads=None) -> dict:
    if web_threads is None:
        monkeypatch.delenv("WEB_THREADS", raising=False)
    else:
        monkeypatch.setenv("WEB_THREADS", web_threads)
    return runpy.run_path(str(API_DIR / "gunicorn.conf.py"))


def test_gunicorn_settings(monkeypatch):
    conf = gunicorn_settings(monkeypatch)
    assert conf["workers"] == 1                      # caches and limits live in one process
    assert conf["worker_class"] == "gthread"         # visitors are served side by side
    assert conf["threads"] == 16
    assert conf["timeout"] == 120                    # a heartbeat with threads, not a per-request limit
    assert conf["graceful_timeout"] == 30
    assert "bind" not in conf                        # gunicorn then listens on Render's PORT


@pytest.mark.parametrize(("raw", "threads"), [("4", 4), ("32", 32), ("0", 1), ("-2", 1), ("abc", 16), ("", 16)])
def test_web_threads(monkeypatch, raw, threads):
    assert gunicorn_settings(monkeypatch, raw)["threads"] == threads


def test_render_starts_gunicorn_with_the_settings_file():
    start = re.search(r"startCommand:\s*(.+?)\s*(#|$)", (API_DIR / "render.yaml").read_text(), re.M).group(1)
    assert start == "gunicorn -c gunicorn.conf.py app:app"
