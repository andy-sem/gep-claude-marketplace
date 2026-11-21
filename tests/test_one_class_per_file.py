"""Class refactor guard: one class per file, no module-level functions but `main`.

Covers the shipped code of both plugins and `testkit/`. `errors.py` holds exception classes only and
is exempt; `type` aliases are allowed; a module-level `main` is the CLI entry wrapper.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

PACKAGES = [
    REPO / "plugins/destructive-guard/lib/destructive_guard",
    REPO / "plugins/gated-dev-simple-workflow/scripts/gated_dev",
    REPO / "testkit",
]


def _modules():
    for package in PACKAGES:
        for path in sorted(package.rglob("*.py")):
            if path.name != "errors.py":
                yield path


def _is_exception(node: ast.ClassDef) -> bool:
    names = [base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "") for base in node.bases]
    return any(name.endswith(("Error", "Exception")) for name in names)


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef) and not _is_exception(n)]
    functions = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name != "main"]
    problems = []
    if len(classes) > 1:
        problems.append(f"more than one class: {classes}")
    if functions:
        problems.append(f"module-level functions: {functions}")
    return problems


@pytest.mark.parametrize("path", list(_modules()), ids=lambda p: str(p.relative_to(REPO)))
def test_one_class_per_file(path: Path):
    assert _violations(path) == []


def test_guard_sees_the_packages():
    assert len(list(_modules())) > 20
