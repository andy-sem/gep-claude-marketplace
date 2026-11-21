"""Shell tokenizer and wrapper normalisation of destructive_guard.gate_engine.

The two fixtures were generated once from the JS (`splitCommand`, `stripWrappers`,
`nestedShellString`, `shellScriptIndex`) over every Bash command of the three case corpora plus the
edge cases of the parser: they pin the Python port token for token.
"""

import json

import pytest

from destructive_guard.engine.normalizer import CommandNormalizer
from destructive_guard.errors import UnparsableError
from destructive_guard.rules.rule_loader import RuleLoader
from destructive_guard.shell.tokenizer import ShellTokenizer
from testkit import DG

FIXTURES = DG / "tests" / "fixtures"
SPLITS = json.loads((FIXTURES / "split_command.json").read_text())
NORMALIZE = json.loads((FIXTURES / "normalize.json").read_text())
RULES = {
    "default": RuleLoader.load_packs([RuleLoader.pack_path(p) for p in RuleLoader.DEFAULT_PACKS]),
    "engine": RuleLoader.load_rules(FIXTURES / "engine_rules.json"),
}


def test_fixture_sizes():
    assert len(SPLITS) >= 500
    assert sum(1 for _, r in SPLITS if isinstance(r, dict)) >= 10  # error rows
    assert len(NORMALIZE) >= 900


@pytest.mark.parametrize(("command", "expected"), SPLITS, ids=[c[:60] for c, _ in SPLITS])
def test_split_command_cases(command, expected):
    if isinstance(expected, dict):
        with pytest.raises(UnparsableError):
            ShellTokenizer.split_command(command)
    else:
        assert ShellTokenizer.split_command(command) == expected


def test_split_command_basics():
    assert ShellTokenizer.split_command('a b && c "d e"; f') == [["a", "b"], ["c", "d e"], ["f"]]
    with pytest.raises(UnparsableError):
        ShellTokenizer.split_command('echo "x')
    with pytest.raises(UnparsableError):
        ShellTokenizer.split_command("(echo x")


def normalize_id(row):
    return f"{row[0]}:{' '.join(row[1])[:60]}"


@pytest.mark.parametrize(("rules_name", "tokens", "expected"), NORMALIZE, ids=[normalize_id(r) for r in NORMALIZE])
def test_normalize_cases(rules_name, tokens, expected):
    rules = RULES[rules_name]
    sw = expected["stripWrappers"]
    if "error" in sw:
        with pytest.raises(UnparsableError):
            CommandNormalizer(rules).strip_wrappers(tokens)
    else:
        assert CommandNormalizer(rules).strip_wrappers(tokens) == sw
    assert CommandNormalizer(rules).nested_shell_string(tokens) == expected["nestedShellString"]
    assert CommandNormalizer.shell_script_index(tokens) == expected["shellScriptIndex"]


# --- edge cases the review asked for -------------------------------------------


def test_command_substitution_leaves_one_placeholder_code_point():
    parts = ShellTokenizer.split_command("echo a$(ls)b")
    assert ["echo", f"a{ShellTokenizer.DYN}b"] in parts
    assert ["ls"] in parts
    assert len(ShellTokenizer.DYN) == 1


def test_nesting_beyond_max_depth_is_unparsable_not_a_crash():
    deep = "echo x"
    for _ in range(12):
        deep = f"echo $({deep})"
    with pytest.raises(UnparsableError, match="nesting too deep"):
        ShellTokenizer.split_command(deep)
    nested_shells = "eval " * 12 + "ls"
    with pytest.raises(UnparsableError):
        ShellTokenizer.split_command(nested_shells)


def test_loose_parameter_reads_nested_strings_with_expansions():
    cmd = 'bash -c "ls $HOME"'
    with pytest.raises(UnparsableError, match="dynamic shell command"):
        ShellTokenizer.split_command(cmd)
    assert ["ls", "$HOME"] in ShellTokenizer.split_command(cmd, loose=True)


def test_heredoc_bodies_and_scopes():
    [cmd] = ShellTokenizer.split_command("cat <<-EOF\n\tbody\n\tEOF")
    assert cmd == ["cat"]
    assert [h["body"] for h in cmd.stdin] == ["\tbody"]
    cd, ls, pwd = ShellTokenizer.split_command("(cd x; ls); pwd")
    assert cd.scope is ls.scope
    assert cd.scope.parent is pwd.scope
    assert pwd.scope.parent is None


def test_scope_host_is_the_command_that_ran_the_shell():
    parts = ShellTokenizer.split_command("bash -c 'ls'")
    assert parts[0] == ["bash", "-c", "ls"]
    assert parts[1] == ["ls"]
    top = parts[1].scope
    while top.parent is not None:
        top = top.parent
    assert top.host is parts[0]
