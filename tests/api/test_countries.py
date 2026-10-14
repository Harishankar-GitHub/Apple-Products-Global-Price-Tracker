"""The one table of countries (api/tracker/countries.json) and the copies scripts/sync_countries.py makes of it."""
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

from tracker import countries

ROOT = pathlib.Path(__file__).resolve().parents[2]
TABLE = json.loads(countries.TABLE_FILE.read_text(encoding="utf-8"))


def sync(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / "scripts" / "sync_countries.py"), *args],
                          capture_output=True, text=True)


def test_the_page_copy_and_the_readme_match_the_table():
    result = sync(ROOT, "--check")
    assert result.returncode == 0, result.stdout


def test_the_table():
    rows = TABLE["countries"]
    assert len(rows) == 50
    for key in ("name", "code", "store"):
        values = [c[key] for c in rows]
        assert len(set(values)) == len(values), f"duplicate {key}"
    assert [c["name"] for c in rows if c["store"] == ""] == ["United States"]       # apple.com/ with no prefix
    for c in rows:
        assert set(c) == {"name", "code", "region", "store", "currency", "symbol"}, c
        assert re.fullmatch(r"[A-Z]{2}", c["code"]) and re.fullmatch(r"[A-Z]{3}", c["currency"]), c
        assert re.fullmatch(r"[a-z]{2}|", c["store"]) and c["symbol"].strip() and c["region"] in TABLE["regions"], c
    assert {c["region"] for c in rows} == set(TABLE["regions"])                    # no empty region


def test_the_api_reads_the_table():
    assert list(countries.COUNTRIES) == [c["name"] for c in TABLE["countries"]]
    assert countries.COUNTRIES["Ireland"] == ("ie", "EUR", "€")
    assert countries.REGIONS == TABLE["regions"]


@pytest.mark.parametrize(
    ("country", "flag"),
    [("Ireland", "🇮🇪"), ("United Kingdom", "🇬🇧"), ("United States", "🇺🇸"), ("South Korea", "🇰🇷"),
     ("United Arab Emirates", "🇦🇪")],
    ids=["ireland", "uk-store-but-gb-flag", "us-store-without-prefix", "two-words", "three-words"],
)
def test_flags_come_from_the_iso_code(country, flag):
    assert countries.COUNTRY_FLAGS[country] == flag


def test_an_edit_not_yet_copied_is_caught_and_the_script_copies_it(tmp_path):
    for part in ("scripts/sync_countries.py", "api/tracker/countries.json", "api/tracker/countries.py",
                 "docs/js/countries.js", "README.md"):
        (tmp_path / part).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / part, tmp_path / part)
    table = tmp_path / "api/tracker/countries.json"
    table.write_text(table.read_text(encoding="utf-8").replace('"name": "Oman"', '"name": "Sultanate of Oman"'),
                     encoding="utf-8")

    stale = sync(tmp_path, "--check")
    assert stale.returncode == 1
    assert "docs/js/countries.js does not match" in stale.stdout and "README.md does not match" in stale.stdout

    assert sync(tmp_path).returncode == 0
    assert sync(tmp_path, "--check").returncode == 0
    assert "Sultanate of Oman" in (tmp_path / "docs/js/countries.js").read_text(encoding="utf-8")
    assert "🇴🇲 Sultanate of Oman |" in (tmp_path / "README.md").read_text(encoding="utf-8")
