"""Temporary projects (an empty .git marks the root) for the project-path tests."""

import tempfile
from pathlib import Path


class TempProject:
    @staticmethod
    def temp_project(base: Path, files: dict[str, str]) -> Path:
        root = Path(tempfile.mkdtemp(prefix="gate-project-", dir=base)).resolve()
        (root / ".git").mkdir()
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return root
