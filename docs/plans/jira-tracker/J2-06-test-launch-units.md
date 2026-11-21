# Task 06: `tests/test_launch_units.py`

Package **J2** (tasks 06–10) · prev [Task 05](J1-05-agents.md) · next [Task 07](J2-07-ticket-project.md) · [index](README.md)

## Goal

Failing tests first (TDD) for the `tracker` key in `TicketProject.read_config` and for the launcher's no-`ticket.md` case.

## Tests to add

Follow the style of `test_read_config_defaults_overrides_and_invalid_content` (line ~162): `tmp_path`, write `.claude/gated-dev.json`, call `TicketProject(tmp_path).read_config()`.

1. `test_read_config_tracker_defaults`: `{"tracker": {"type": "jira"}}` returns `config["tracker"] == {"type": "jira", "site": None, "statuses": {"inProgress": "In Progress", "inReview": "In Review", "done": "Done"}, "startFrom": None, "assign": True, "comments": True, "baseFromParent": None}`, and `config["keyPattern"].pattern == r"^[A-Z][A-Z0-9]*-\d+$"`.
2. `test_read_config_tracker_overrides`: partial `statuses` merges with the defaults; `inReview: null` stays `None`; an explicit `keyPattern` wins over the tracker default.
3. `test_read_config_tracker_invalid`, parametrised, each raising `LaunchError` with a message that names the problem:
   - not an object; `type` missing; `type: "linear"` (unsupported);
   - unknown sub-key; unknown `statuses` key;
   - `inProgress` or `done` set to `null` or `""`;
   - `startFrom` not a list of non-empty strings;
   - `assign` or `comments` not a bool;
   - `site` with a scheme or a slash (`https://x`, `x/y`);
   - `baseFromParent` without `{parent}`, or with characters outside the safe ref set plus `*`.
4. `test_read_config_without_tracker_is_unchanged`: no `tracker` key gives `config["tracker"] is None` and the old default `keyPattern`.
5. Launcher (the existing unit tests for `TicketLauncher.launch_ticket` with a fake `run`): with `tracker` set and no `ticket.md`, the plan is `mode: "main-checkout"`, `summary: None`, `note: "no ticket.md yet; the session fetches it from Jira"`. With `ticket.md` present, behaviour is unchanged.

## Steps

- [ ] **1.** Update the existing defaults test: `read_config()` now also returns `"tracker": None`. This is the one expectation that changes, because the return value gets a new key.
- [ ] **2.** Add tests 1–5. Run `uv run pytest plugins/gated-dev-simple-workflow/tests/test_launch_units.py`: the new tests fail and the old ones pass.

## Done when

- The new tests fail only because of the missing feature (no import errors).
