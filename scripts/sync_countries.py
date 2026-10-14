"""
Copy the country table to where it is needed besides the API.

api/tracker/countries.json is the one table of countries. The website is
served from docs/ and the API from api/, and neither can read the other's
folder, so this script writes:

  docs/js/countries.js   the same table, for the page
  README.md              the "Supported Countries" list

Run it after editing countries.json:

  python3 scripts/sync_countries.py           # write the copies
  python3 scripts/sync_countries.py --check   # only check them (the tests do this)
"""
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "api" / "tracker" / "countries.json"
PAGE_COPY = ROOT / "docs" / "js" / "countries.js"
README = ROOT / "README.md"
README_START = "<!-- countries:start (written by scripts/sync_countries.py from api/tracker/countries.json) -->"
README_END = "<!-- countries:end -->"


def _flag():
    """The API's flag() (api/tracker/countries.py), loaded without the rest of the API."""
    spec = importlib.util.spec_from_file_location("countries", ROOT / "api" / "tracker" / "countries.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.flag


def page_copy(source: str) -> str:
    return ("// The countries: written by scripts/sync_countries.py from api/tracker/countries.json.\n"
            "// Edit that file and run the script; do not edit this one.\n"
            "export default " + source.rstrip("\n") + ";\n")


def readme_list(table: dict) -> str:
    flag = _flag()
    lines = [f"{len(table['countries'])} Apple stores:", "", "| Region | Countries |", "|--------|-----------|"]
    for region in table["regions"]:
        names = [f"{flag(c['code'])} {c['name']}" for c in table["countries"] if c["region"] == region]
        lines.append(f"| {region} | {' · '.join(names)} |")
    return "\n".join(lines)


def expected() -> dict[pathlib.Path, str]:
    """Every file this script writes, with the text it should have."""
    source = SOURCE.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    before, rest = readme.split(README_START, 1)
    _, after = rest.split(README_END, 1)
    readme = f"{before}{README_START}\n{readme_list(json.loads(source))}\n{README_END}{after}"
    return {PAGE_COPY: page_copy(source), README: readme}


def main(check: bool) -> int:
    stale = [path for path, text in expected().items()
             if not path.exists() or path.read_text(encoding="utf-8") != text]
    if check:
        for path in stale:
            print(f"{path.relative_to(ROOT)} does not match api/tracker/countries.json: "
                  "run python3 scripts/sync_countries.py")
        return 1 if stale else 0
    for path, text in expected().items():
        path.write_text(text, encoding="utf-8")
    print("updated: " + (", ".join(str(p.relative_to(ROOT)) for p in stale) or "nothing, already in sync"))
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv[1:]))
