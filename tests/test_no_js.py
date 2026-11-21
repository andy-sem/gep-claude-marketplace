"""The repo contains no JavaScript and no node invocation (P14).

Rule content that recognises JS in user commands is not project JS: packs, the
gate's recognition modules, test corpora and plans are not scanned; README
sections that describe what the gate recognises sit between
`<!-- recognises-js -->` markers.
"""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

JS_FILE = re.compile(r"\.(m|c)?js$")
NODE_CALL = re.compile(r"(?<![\w./-])(node|npx)\s+\S|\bNode\.js\b|\.mjs\b|\bnode_modules\b")
MARKED = re.compile(r"<!-- recognises-js -->.*?<!-- /recognises-js -->", re.DOTALL)

SCANNED = [
    "plugins/*/hooks/*",
    "plugins/*/skills/**/*.md",
    "plugins/*/agents/*.md",
    "plugins/*/README.md",
    ".github/workflows/*.yml",
    "CLAUDE.md",
]


def scan_text(text: str) -> list[str]:
    """Offending lines of a scanned file, marked recognition sections excluded."""
    text = MARKED.sub("", text)
    return [line.strip() for line in text.splitlines() if NODE_CALL.search(line)]


def scanned_files() -> list[Path]:
    found = {p for pattern in SCANNED for p in REPO.glob(pattern) if p.is_file() and "__pycache__" not in p.parts}
    return sorted(found)


def test_no_js_file_is_tracked():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert [f for f in tracked if JS_FILE.search(f)] == []


def test_no_node_invocation_in_scanned_files():
    bad = {str(p.relative_to(REPO)): hits for p in scanned_files() if (hits := scan_text(p.read_text()))}
    assert bad == {}


def test_no_setup_node_in_ci():
    for wf in (REPO / ".github" / "workflows").glob("*.yml"):
        assert "setup-node" not in wf.read_text(), wf.name


def test_no_gate_infra_node_outside_plans():
    hits = []
    for path in REPO.rglob("*"):
        rel = path.relative_to(REPO)
        if not path.is_file() or rel.parts[0] in {".git", ".venv", "docs", ".superpowers"} or "__pycache__" in rel.parts:
            continue
        if rel == Path("tests/test_no_js.py"):
            continue
        try:
            if "GATE_INFRA_NODE" in path.read_text():
                hits.append(str(rel))
        except UnicodeDecodeError:
            pass
    assert hits == []


# The scan must fail on real regressions and ignore only marked recognition text.


def test_scan_flags_node_in_a_skill_line():
    assert scan_text("Run `node scripts/x.mjs` first.\n")
    assert scan_text("npx prettier --write\n")
    assert scan_text("needs Node.js 22\n")


def test_scan_ignores_marked_recognition_section():
    assert scan_text("a <!-- recognises-js -->`node x.mjs`<!-- /recognises-js --> b\n") == []
    assert scan_text("<!-- recognises-js -->\n`npx x`\n<!-- /recognises-js -->\nnode y.mjs\n") == ["node y.mjs"]


def test_scan_ignores_plain_prose():
    assert scan_text("the nodes of a graph; a node: here\n") == []
