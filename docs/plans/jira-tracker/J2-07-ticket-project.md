# Task 07: `scripts/gated_dev/launch/ticket_project.py`

Package **J2** · prev [Task 06](J2-06-test-launch-units.md) · next [Task 08](J2-08-test-launch-cli.md) · [index](README.md)

## Goal

`TicketProject.read_config` accepts, checks and normalises `tracker`, which makes Task 06's config tests pass.

## Changes

1. `CONFIG_KEYS`: add `"tracker"`.
2. New class attributes:
   - `TRACKER_KEY_PATTERN = r"^[A-Z][A-Z0-9]*-\d+$"`
   - `TRACKER_KEYS = frozenset(("type", "site", "statuses", "startFrom", "assign", "comments", "baseFromParent"))`
   - `TRACKER_TYPES = frozenset(("jira",))`
   - `DEFAULT_STATUSES = {"inProgress": "In Progress", "inReview": "In Review", "done": "Done"}`
   - `_SITE = re.compile(r"[A-Za-z0-9.-]+")`
3. New method `_read_tracker(raw, file) -> dict | None` (one class per file still holds: it is a method of `TicketProject`). It runs the checks of Task 06 test 3 in that order and returns the normalised dict of test 1. Each error is `LaunchError(f"{file}: tracker.<key> ...")`.
4. `read_config`: call `_read_tracker` before compiling `keyPattern`. The default pattern is `TRACKER_KEY_PATTERN` when the tracker is set and `keyPattern` is not. Add `"tracker"` to the returned dict.
5. `baseFromParent` check: it must contain `{parent}`, and once `{parent}` is replaced by `PROJ-1` and `*` by `x`, the result must match `LaunchNaming._SAFE_REF`.

The launcher does not check `orchestratorRules` for a `## intake` section, because it does not read the rules file. The skill does (Task 04).

## Steps

- [ ] **1.** Implement. Standard library only; keep the method under ~40 lines, with one `if` per rule.
- [ ] **2.** `uv run pytest plugins/gated-dev-simple-workflow/tests/test_launch_units.py -k read_config`: green.
- [ ] **3.** `uv run ruff check .`

## Done when

- Task 06 tests 1–4 pass. Test 5 still fails until Task 09.
