"""Rule case corpus (tests/cases/*.json), run through `check --json` (port of destructive / gate-rules cases)."""

import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from testkit import DG
from testkit.check_cli import check_call, run_check
from testkit.hook import decision, mcp_input, run_hook
from testkit.impl import select_impl
from testkit.projects import temp_project

CASES = DG / "tests" / "cases"
FIXTURES = DG / "tests" / "fixtures"
CORPORA = ["destructive", "gate_rules"]


def load_corpus(name: str) -> tuple[dict, list[dict]]:
    """(env with @fixture: paths resolved, cases) of tests/cases/<name>.json."""
    data = json.loads((CASES / f"{name}.json").read_text())
    env = {
        k: str(FIXTURES / v.removeprefix("@fixture:")) if v.startswith("@fixture:") else v
        for k, v in data["env"].items()
    }
    return env, data["cases"]


def call_of(case: dict) -> dict:
    return {k: case[k] for k in ("bash", "mcp", "input") if k in case}


def label(case: dict) -> str:
    if "bash" in case:
        return case["bash"]
    return f"{case['mcp']} {json.dumps(case['input'], separators=(',', ':'))}"


def _params(name: str):
    _, cases = load_corpus(name)
    return [pytest.param(i, c, id=label(c)) for i, c in enumerate(cases)]


@pytest.fixture(scope="module")
def corpus_results(tmp_path_factory) -> dict[tuple[str, int], str | None]:
    """Every case of every corpus, run once and concurrently: rule id (source) when it asks, else None."""
    impl = select_impl("destructive-guard", os.environ)
    cwd = temp_project(tmp_path_factory.mktemp("corpus"), {})
    jobs = []
    for name in CORPORA:
        env, cases = load_corpus(name)
        jobs += [((name, i), call_of(c), env) for i, c in enumerate(cases)]

    def one(job):
        key, call, env = job
        if "mcp" in call and not call["mcp"].startswith("mcp__"):
            # check --mcp only takes mcp__ tools; other tool names go through the hook itself.
            out = run_hook(impl, mcp_input(call["mcp"], call["input"], cwd), env, cwd=cwd).stdout
            return key, decision(out)["permissionDecisionReason"].split(":")[0] if out else None
        r = check_call(impl, call, env=env, cwd=cwd)
        return key, r["source"] if r["decision"] == "ask" else None

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
        return dict(pool.map(one, jobs))


def test_corpus_sizes():
    _, destructive = load_corpus("destructive")
    _, gate_rules = load_corpus("gate_rules")
    assert len(destructive) == 150
    assert len([c for c in gate_rules if c.get("group") != "not-gated"]) == 194
    assert len([c for c in gate_rules if c.get("group") == "not-gated"]) == 4


@pytest.mark.parametrize(("index", "case"), _params("destructive"))
def test_destructive_case(corpus_results, index, case):
    assert corpus_results[("destructive", index)] == case["expect"]


@pytest.mark.parametrize(("index", "case"), _params("gate_rules"))
def test_gate_rules_case(corpus_results, index, case):
    assert corpus_results[("gate_rules", index)] == case["expect"]


def test_every_destructive_rule_has_an_asking_case():
    pack = json.loads((DG / "packs" / "destructive.json").read_text())
    _, cases = load_corpus("destructive")
    hit = {c["expect"] for c in cases}
    assert {r["id"] for r in pack["rules"]} <= hit


def test_destructive_rules_do_not_make_script_scan_ask(impl, tmp_path):
    root = temp_project(tmp_path, {"build.sh": "rm -rf dist\ngit push\n"})
    assert check_call(impl, {"bash": "bash build.sh"}, cwd=root)["decision"] == "none"
    # a script outside the project does not ask when nothing is scanned for
    assert check_call(impl, {"bash": "bash /usr/local/bin/x.sh"}, cwd=root)["decision"] == "none"


def test_shipped_rule_file_loads(impl, tmp_path):
    env, _ = load_corpus("gate_rules")
    proc = run_check(impl, "--json", "--config", env=env, cwd=tmp_path)
    config = json.loads(proc.stdout)
    assert "error" not in config
    assert len(config["ruleIds"]) > 0
