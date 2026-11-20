// Where relative paths in GATE_* variables point. A hook runs in the session's
// current directory, which moves with every `cd`, so a relative rules file,
// prompt file or log would break or scatter. They resolve against the project
// instead: CLAUDE_PROJECT_DIR (set for hooks), else the nearest ancestor of
// `cwd` with a `.git` entry (a plain shell, such as a manual check.mjs run),
// else `cwd`. Absolute paths are kept as they are.

import { existsSync } from "node:fs"
import { dirname, isAbsolute, join, resolve } from "node:path"

export function projectDir(env = process.env, cwd = process.cwd()) {
  const fromEnv = typeof env.CLAUDE_PROJECT_DIR === "string" ? env.CLAUDE_PROJECT_DIR.trim() : ""
  if (fromEnv) return resolve(fromEnv)
  let dir = resolve(cwd)
  for (;;) {
    if (existsSync(join(dir, ".git"))) return dir
    const parent = dirname(dir)
    if (parent === dir) return resolve(cwd)
    dir = parent
  }
}

export function projectPath(path, env = process.env, cwd = process.cwd()) {
  return isAbsolute(path) ? path : resolve(projectDir(env, cwd), path)
}
