import subprocess

from testkit.fakebin import FakeBin
from testkit.gitrepo import GitRepo


def run(fb, name, *args, stdin=None, cwd=None):
    return subprocess.run(
        [str(fb.path / name), *args], input=stdin, capture_output=True, text=True, cwd=cwd, check=False
    )


def test_fakebin_records_argv_and_stdin(tmp_path):
    fb = FakeBin(tmp_path)
    fb.add("tool", stdout="out\n", stderr="err\n", status=3, read_stdin=True)
    proc = run(fb, "tool", "a", "--b", stdin="hello", cwd=tmp_path)
    assert (proc.stdout, proc.stderr, proc.returncode) == ("out\n", "err\n", 3)
    [call] = fb.calls("tool")
    assert call["argv"] == ["a", "--b"]
    assert call["stdin"] == "hello"
    assert call["cwd"] == str(tmp_path.resolve())
    assert fb.calls("other") == []
    assert len(fb.calls()) == 1


def test_fakebin_script_sequence_repeats_last(tmp_path):
    fb = FakeBin(tmp_path)
    fb.add("tool", script=[{"stdout": "one"}, {"stdout": "two", "status": 1}])
    got = [(p.stdout, p.returncode) for p in (run(fb, "tool") for _ in range(4))]
    assert got == [("one", 0), ("two", 1), ("two", 1), ("two", 1)]


def test_fakebin_routes_override_by_argument_prefix(tmp_path):
    fb = FakeBin(tmp_path)
    fb.add("tool", stdout="default", routes=[{"match": ["sub", "x"], "stdout": "routed", "status": 2}])
    assert run(fb, "tool", "sub", "x", "y").stdout == "routed"
    assert run(fb, "tool", "sub", "x", "y").returncode == 2
    assert run(fb, "tool", "sub").stdout == "default"


def test_fakebin_write_side_effect(tmp_path):
    fb = FakeBin(tmp_path)
    target = tmp_path / "state.json"
    target.write_text("before")
    fb.add("tool", script=[{"write": {str(target): "after"}}], snapshot=[str(target), str(tmp_path / "missing")])
    run(fb, "tool")
    assert target.read_text() == "after"
    assert fb.calls("tool")[0]["files"] == {str(target): "before", str(tmp_path / "missing"): None}


def test_fakebin_path_has_no_real_tools(tmp_path):
    fb = FakeBin(tmp_path)
    env = {"PATH": str(fb.path)}
    assert subprocess.run(["/bin/sh", "-c", "gh"], env=env, capture_output=True, check=False).returncode == 127
    fb.link("cat")
    assert (fb.path / "cat").is_symlink()
    assert subprocess.run(["/bin/sh", "-c", "echo hi | cat"], env=env, capture_output=True, check=False).returncode == 0


def test_git_helpers_isolated(tmp_path):
    repo = GitRepo.init_repo(tmp_path / "repo", origin=tmp_path / "origin.git")
    wt = GitRepo.add_worktree(repo, tmp_path / "wts" / "a", "K-1/a")
    proc = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"], capture_output=True, text=True, check=False
    )
    assert f"worktree {wt}" in proc.stdout
    assert "refs/heads/K-1/a" in proc.stdout
    head = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert head.stdout.strip() == "origin/main"
