"""Parity map between the JS tests and their Python ports (PORTING.md)."""

import re
from pathlib import Path

_TEST_CALL = re.compile(r"(?<![.\w])test\(\s*([\"'`])(.*?)(?<!\\)\1")


def js_tests(plugin_dir: Path) -> list[tuple[str, str]]:
    """(file basename, test name) for every test( ... ) in test/*.test.mjs; [] once test/ is gone."""
    test_dir = plugin_dir / "test"
    if not test_dir.is_dir():
        return []
    found = []
    for path in sorted(test_dir.glob("*.test.mjs")):
        for match in _TEST_CALL.finditer(path.read_text()):
            found.append((path.name, match.group(2)))
    return found


def _split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [c.strip().replace("\\|", "|") for c in cells[1:-1]]


def read_map(path: Path) -> list[tuple[str, str, str]]:
    """Rows of the `| JS file | JS test | Python test |` table."""
    rows = []
    for line in path.read_text().splitlines():
        if not line.startswith("|"):
            continue
        cells = _split_row(line)
        if len(cells) != 3 or cells[0] == "JS file" or set(cells[0]) <= {"-", ":", " "}:
            continue
        rows.append((cells[0], cells[1], cells[2]))
    return rows


def escape_cell(text: str) -> str:
    return text.replace("|", "\\|")
