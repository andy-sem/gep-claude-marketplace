"""Temporary projects (an empty .git marks the root) for script-scan tests."""

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

    @classmethod
    def provision_project(cls, base: Path) -> Path:
        """An entry script that names terraform and imports a deploy module, which shells out to cloudctl."""
        return cls.temp_project(
            base,
            {
                "scripts/provision-cloud-app-dev.mjs": (
                    'import { join } from "node:path"\n'
                    'import { deploy } from "./deploy-cloud-app-dev.mjs"\n'
                    "// Applies the terraform plan, then deploys.\n"
                    "await deploy(join(process.cwd(), 'out'))\n"
                ),
                "scripts/deploy-cloud-app-dev.mjs": (
                    'import { spawn } from "node:child_process"\n'
                    "export async function deploy(dir) {\n"
                    '  spawn("cloudctl", ["run", "deploy", "app", "--source", dir])\n'
                    "}\n"
                ),
            },
        )
