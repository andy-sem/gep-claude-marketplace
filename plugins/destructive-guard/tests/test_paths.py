"""project_dir / project_path (port of paths.mjs; its cases also run through the config tests)."""

import os

from destructive_guard.paths import ProjectDir
from testkit.projects import TempProject


def make_project(tmp_path):
    root = TempProject.temp_project(tmp_path, {})
    sub = root / "apps" / "web"
    sub.mkdir(parents=True)
    return root, sub


def test_env_dir_wins_and_is_trimmed(tmp_path):
    _, sub = make_project(tmp_path)
    assert ProjectDir.project_dir({"CLAUDE_PROJECT_DIR": "  /proj  "}, sub) == "/proj"
    assert ProjectDir.project_dir({"CLAUDE_PROJECT_DIR": "/proj/../other"}, sub) == "/other"


def test_empty_env_dir_is_unset(tmp_path):
    root, sub = make_project(tmp_path)
    assert ProjectDir.project_dir({"CLAUDE_PROJECT_DIR": "   "}, sub) == str(root)
    assert ProjectDir.project_dir({}, sub) == str(root)


def test_git_root_via_git_directory(tmp_path):
    root, sub = make_project(tmp_path)
    assert ProjectDir.project_dir({}, sub) == str(root)
    assert ProjectDir.project_dir({}, root) == str(root)


def test_git_root_via_git_file_for_worktrees(tmp_path):
    wt = tmp_path / "wt"
    (wt / "src").mkdir(parents=True)
    (wt / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
    assert ProjectDir.project_dir({}, wt / "src") == str(wt)


def test_falls_back_to_cwd_without_git(tmp_path):
    bare = tmp_path / "gate-nogit"
    bare.mkdir()
    # tmp_path itself has no .git above it in the usual layout; guard the assumption
    probe = os.path.abspath(bare)
    while probe != os.path.dirname(probe):
        assert not os.path.exists(os.path.join(probe, ".git")), "test needs a tree without .git"
        probe = os.path.dirname(probe)
    assert ProjectDir.project_dir({}, bare) == str(bare)


def test_absolute_path_kept_as_given(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    assert ProjectDir.project_path(str(link / "r.json"), {}, tmp_path) == str(link / "r.json")
    assert ProjectDir.project_path("/a/../b.json", {}, tmp_path) == "/a/../b.json"


def test_relative_path_resolves_against_project(tmp_path):
    root, sub = make_project(tmp_path)
    assert ProjectDir.project_path(".claude/r.json", {}, sub) == str(root / ".claude" / "r.json")
    assert ProjectDir.project_path("logs/g.jsonl", {"CLAUDE_PROJECT_DIR": "/proj"}, "/elsewhere") == "/proj/logs/g.jsonl"
    assert ProjectDir.project_path("../x.json", {"CLAUDE_PROJECT_DIR": "/proj/a"}, "/elsewhere") == "/proj/x.json"
