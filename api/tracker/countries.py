"""
The Apple stores searched, read from countries.json next to this file: the one
table of countries for the whole project. The page gets the same table as
docs/js/countries.js, which scripts/sync_countries.py writes from it (a test
checks the two match). To add or change a store, edit countries.json and run
that script.

Each country: name, ISO code (for its flag, and on the page to guess a
visitor's home country), region, the store's URL prefix on apple.com ("" is
the US store), currency and currency symbol.
"""
import json
import pathlib

TABLE_FILE = pathlib.Path(__file__).with_name("countries.json")
_table = json.loads(TABLE_FILE.read_text(encoding="utf-8"))


def flag(code: str) -> str:
    """The flag emoji for an ISO country code: "IE" → 🇮🇪 (two regional-indicator letters)."""
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in code.upper())


REGIONS: list[str] = _table["regions"]

# country → (URL prefix, currency, currency symbol)
COUNTRIES: dict[str, tuple[str, str, str]] = {
    c["name"]: (c["store"], c["currency"], c["symbol"]) for c in _table["countries"]
}

COUNTRY_FLAGS: dict[str, str] = {c["name"]: flag(c["code"]) for c in _table["countries"]}
