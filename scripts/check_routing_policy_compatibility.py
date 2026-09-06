#!/usr/bin/env python3
"""Refuse a pull request that lets the routing policy and the runner's hardcoded
model literal disagree.

WS-P2.38, the last open clause of Wave-3 exit ("the routing policy file is the
only place model selection lives" -- program plan line 153). It is not, today:
`routing-policy.toml`'s `[[surface]] id = "runner-implementation"` declares the
model for every factory coding run, and
`factory-runner/.github/workflows/factory-runner.yml` hardcodes a second copy of
the same value on the `claude-code-base-action` step. The two values agree as of
2026-08-04. Nothing enforces that they keep agreeing -- change the policy and
every run keeps using the old model, silently. That is this estate's
most-repeated defect class (`_is_skipped_reason`'s duplicated codes, the four
vocabulary mismatches, `budgets.max_attempts`): only the copy that gets exercised
stays correct, and neither of these two copies is ever compared to the other by
anything that runs.

This is a derivation pin, not a fix: the workflow cannot read the policy at
runtime (it runs in the *caller's* checkout; `routing-policy.toml` lives in
*this* repo, not on disk there), so the literal has to keep existing. What this
check adds is the guard that was missing -- the pull request that would let the
two values diverge is the one that must not merge.

Modeled directly on `orchestrator/scripts/check_brief_consumer_compatibility.py`
(WS-P2.23), the same mechanism on the other side of the same kind of boundary:
read this side's source of truth, fetch the far side's file at its declared
pinned revision, fail loudly on any divergence or on anything that leaves the
comparison unresolvable.

IT NOW VETS TWO SURFACES OF THE SAME FILE, and the second is not about models.
Alongside the model literal it checks that `BUDGETS["max_llm_calls"]` still
covers the structural worst case the runner's OWN `max_turns` literal implies at
the pinned revision -- `max_attempts` x `max_turns` x `CALLS_PER_TURN`.

That second surface exists because the coupling was written down and then not
honoured. `abd72db` raised `max_turns` 40 -> 60 and `#73` advanced
RECOMMENDED_CALLER_PIN onto it; the comment the runner carries beside its own
literal says "intent-packages moves with it. Raising one alone reproduces the
failure that killed a unit permanently." intent-packages did not move with it,
and nothing noticed for three days, because a comment naming a coupling is not a
check. The failure it names is unrecoverable: `budgets.max_llm_calls` lives
inside a write-once envelope whose human approval cannot be taken back, so a
shortfall is discovered by a unit dying of `budget_exceeded` with no cure.

The relation is `>=`, not equality, and that asymmetry is deliberate. The
property being defended is that the RECOVERABLE gate (`attempts_exhausted`,
curable by `approve_retry`) binds before the UNRECOVERABLE one. Over-provisioning
costs nothing -- nothing checks spend mid-run -- so a budget above the floor is a
margin, while one below it is a unit nobody can rescue. Equality here would red
on a deliberate margin, which is the check refusing something safe.

THE JOB'S NAME IS NOW NARROWER THAN WHAT IT CHECKS. It is a required status
check on `main`, so renaming it is a PAIRED operation -- the protected context
must move in the same operation or every pull request is blocked by a context
nothing reports. Left as it is, deliberately; the orchestrator's own
`Runner consumer compatibility` job carries the identical trade for the identical
reason.

What it does:

1. resolve the intended model from `routing-policy.toml`'s `runner-implementation`
   surface, via this repo's own `intent_packages.routing` loader;
2. read `factory-runner`'s `RECOMMENDED_CALLER_PIN` -- the revision callers are
   supposed to run -- and fetch `.github/workflows/factory-runner.yml` at that
   revision;
3. extract the `model:` and `max_turns:` inputs of its `claude-code-base-action`
   step;
4. fail, naming both values, if the models differ;
5. fail, naming the floor and the shortfall, if `max_llm_calls` is below
   `max_attempts` x `max_turns` x `CALLS_PER_TURN`.

Both surfaces are evaluated on every run and both verdicts are printed. A failure
in one must not hide a divergence in the other -- that would make the second
defect discoverable only after the first was fixed.

Usage:
    python3 scripts/check_routing_policy_compatibility.py

Exit 0: both surfaces agree with the pinned runner. Exit 1: either diverges, or
either comparison could not be resolved (unreachable pin, malformed workflow, an
`runner-implementation` surface that no longer names exactly one model, a
`max_turns` input that is not a positive integer, ...).
"""

from __future__ import annotations

import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from intent_packages import routing
from intent_packages.profiles.dependency_update import BUDGETS, CALLS_PER_TURN

REPO_ROOT = Path(__file__).resolve().parent.parent

FACTORY_RUNNER_REPO = "AlobarQuest/factory-runner"
PIN_FILE_PATH = "RECOMMENDED_CALLER_PIN"
PIN_FILE_REF = "main"  # the pin file names the recommended revision; it is read at HEAD
CONSUMER_WORKFLOW_PATH = ".github/workflows/factory-runner.yml"
ACTION_STEP_USES_PREFIX = "anthropics/claude-code-base-action"

SURFACE_ID = "runner-implementation"

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class Unresolvable(RuntimeError):
    """The check could not establish what it needed to compare. Never a silent pass."""


def resolve_policy_model_id(policy: routing.RoutingPolicy | None = None) -> str:
    """The model id `routing-policy.toml` declares for the runner's coding action.

    Reuses `intent_packages.routing` -- the repo's own validated TOML loader,
    already pinned by `tests/test_routing.py` -- rather than re-parsing the file.
    That loader fails loudly on an absent surface or an unknown model slug; the
    one thing it does not itself enforce (a dual-model row is valid for a
    surface like `judgment-ac-verification`) is checked here, because this check
    compares against a single workflow literal and a surface naming zero or two
    models has nothing single to compare it to.
    """
    policy = policy or routing.load_policy()
    try:
        row = routing.resolve_surface(policy, SURFACE_ID)
    except routing.RoutingPolicyError as error:
        raise Unresolvable(str(error)) from error
    if len(row.model_ids) != 1:
        raise Unresolvable(
            f"surface {SURFACE_ID!r} names {len(row.model_ids)} model(s) "
            f"({list(row.model_ids)}); this check compares against a single "
            "workflow literal and needs exactly one"
        )
    return row.model_ids[0]


def fetch(repo: str, path: str, ref: str) -> str:
    """The file at a revision, read from GitHub. Read-only, one GET."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}",
        headers={
            "Accept": "application/vnd.github.raw",
            "User-Agent": "intent-packages-routing-policy-compatibility/1",
        },
    )
    # Present in Actions; absent locally, where the public repository is readable anyway.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode()
    except urllib.error.HTTPError as error:
        raise Unresolvable(
            f"cannot read {path} at {repo}@{ref[:8]}: HTTP {error.code}. "
            "The repository must stay public and the ref must name a reachable revision."
        ) from error
    except urllib.error.URLError as error:
        raise Unresolvable(
            f"cannot reach GitHub to read {path} at {ref[:8]}: {error.reason}"
        ) from error


def pinned_revision(pin_text: str) -> str:
    """The full commit SHA `RECOMMENDED_CALLER_PIN` names.

    Must be a full 40-character hex SHA: a branch or tag is mutable, so there
    would be no fixed revision to compare the policy against.
    """
    ref = pin_text.strip()
    if not FULL_SHA.match(ref):
        raise Unresolvable(
            f"{FACTORY_RUNNER_REPO}'s {PIN_FILE_PATH} does not contain a full "
            f"40-character commit SHA: {ref!r}"
        )
    return ref


def action_step_inputs(workflow_text: str) -> dict:
    """The `with:` inputs of the `claude-code-base-action` step.

    Parsed as YAML and matched on the step's `uses:` prefix, not grepped for a
    bare key -- `model:` or `max_turns:` could in principle appear elsewhere in
    the file, and only the ones on this specific step are the values that govern
    a run.
    """
    document = yaml.safe_load(workflow_text)
    for job in (document.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            uses = step.get("uses", "")
            if isinstance(uses, str) and uses.startswith(ACTION_STEP_USES_PREFIX):
                return step.get("with") or {}
    raise Unresolvable(f"no step using {ACTION_STEP_USES_PREFIX} found in the fetched workflow")


def workflow_model(workflow_text: str) -> str:
    """The `model:` input of the `claude-code-base-action` step."""
    model = action_step_inputs(workflow_text).get("model")
    if not isinstance(model, str) or not model.strip():
        raise Unresolvable(f"the {ACTION_STEP_USES_PREFIX} step has no non-empty `model:` input")
    return model


def workflow_max_turns(workflow_text: str) -> int:
    """The `max_turns:` input of the `claude-code-base-action` step, as an int.

    This literal is the only thing that actually bounds a single coding attempt
    -- the runner does not read `budgets.max_llm_calls` from the envelope -- so
    it is the number the budget floor has to be computed from.

    Accepts the quoted string the workflow writes today (`max_turns: "60"`) and a
    bare YAML integer, because which one appears is a formatting choice on the
    far side of a boundary this check does not control. A value that is not a
    positive integer is Unresolvable rather than coerced: a floor computed from a
    number nobody can read is a floor asserted about nothing.
    """
    raw = action_step_inputs(workflow_text).get("max_turns")
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise Unresolvable(
            f"the {ACTION_STEP_USES_PREFIX} step has no readable `max_turns:` input (got {raw!r})"
        )
    try:
        turns = int(str(raw).strip())
    except ValueError:
        raise Unresolvable(
            f"the {ACTION_STEP_USES_PREFIX} step's `max_turns:` input is not an integer: {raw!r}"
        ) from None
    if turns <= 0:
        raise Unresolvable(
            f"the {ACTION_STEP_USES_PREFIX} step's `max_turns:` input is not positive: {turns}"
        )
    return turns


def structural_budget_floor(max_turns: int) -> int:
    """The smallest `max_llm_calls` under which all `max_attempts` attempts fit.

    `max_attempts` x `max_turns` x `CALLS_PER_TURN`. Below it, the unrecoverable
    gate (`budget_exceeded`, curable by nothing) binds before the recoverable one
    (`attempts_exhausted`, curable by `approve_retry`) -- the inversion that
    permanently killed unit b1e02957.
    """
    return BUDGETS["max_attempts"] * max_turns * CALLS_PER_TURN


def check_model(policy_model: str, runner_model: str, ref: str) -> bool:
    """Surface 1: the routing policy and the runner name the same model."""
    print(f"policy: routing-policy.toml [[surface]] {SURFACE_ID!r} -> {policy_model}")
    print(f"runner: {FACTORY_RUNNER_REPO}@{ref[:8]} {CONSUMER_WORKFLOW_PATH} -> {runner_model}")

    if policy_model == runner_model:
        print(f"PASS: the policy and the pinned runner agree on {policy_model!r}.\n")
        return True

    print(
        f"FAIL: routing-policy.toml declares {SURFACE_ID!r} -> {policy_model!r}, but the "
        f"runner pinned at {FACTORY_RUNNER_REPO}@{ref[:8]} hardcodes {runner_model!r} on its "
        f"{ACTION_STEP_USES_PREFIX} step.\n\n"
        "These must agree, and which one is correct is a routing decision -- this check "
        "does not resolve it. Update the runner's literal to match the policy (or escalate "
        "if the policy itself moved by mistake), then re-run.\n",
        file=sys.stderr,
    )
    return False


def check_budget_floor(runner_max_turns: int, ref: str) -> bool:
    """Surface 2: the stamped budget still covers every attempt the runner allows."""
    budget = BUDGETS["max_llm_calls"]
    attempts = BUDGETS["max_attempts"]
    floor = structural_budget_floor(runner_max_turns)

    print(f"policy: BUDGETS max_llm_calls -> {budget} (max_attempts {attempts})")
    print(
        f"runner: {FACTORY_RUNNER_REPO}@{ref[:8]} {CONSUMER_WORKFLOW_PATH} -> "
        f"max_turns {runner_max_turns}; floor = "
        f"{attempts} x {runner_max_turns} x {CALLS_PER_TURN} = {floor}"
    )

    if budget >= floor:
        margin = budget - floor
        print(f"PASS: {budget} covers the floor of {floor} (margin {margin}).\n")
        return True

    print(
        f"FAIL: BUDGETS['max_llm_calls'] is {budget}, below the structural floor of "
        f"{floor} implied by the runner's own max_turns of {runner_max_turns} at "
        f"{FACTORY_RUNNER_REPO}@{ref[:8]}.\n\n"
        f"A unit stamped at {budget} cannot spend the {attempts} attempts "
        "`max_attempts` grants it: `budget_exceeded` binds first, and it is curable "
        "by nothing -- the envelope is write-once and its human approval cannot be "
        "taken back. Raise `max_llm_calls` in BOTH "
        "`src/intent_packages/profiles/dependency_update.py` and "
        "`approval-policy.toml` to at least the floor (a test keeps them equal), or "
        "escalate if the runner's max_turns moved by mistake.\n",
        file=sys.stderr,
    )
    return False


def main() -> int:
    """Evaluate BOTH surfaces, print both verdicts, then decide.

    Deliberately not short-circuited: a model divergence must not hide a budget
    shortfall, or the second defect becomes discoverable only after the first is
    fixed. An Unresolvable is still fatal on the spot -- if the pin or the
    workflow cannot be read, neither surface has anything to compare.
    """
    try:
        policy_model = resolve_policy_model_id()
        ref = pinned_revision(fetch(FACTORY_RUNNER_REPO, PIN_FILE_PATH, PIN_FILE_REF))
        workflow_text = fetch(FACTORY_RUNNER_REPO, CONSUMER_WORKFLOW_PATH, ref)
        runner_model = workflow_model(workflow_text)
        runner_max_turns = workflow_max_turns(workflow_text)
    except Unresolvable as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    verdicts = [
        check_model(policy_model, runner_model, ref),
        check_budget_floor(runner_max_turns, ref),
    ]
    return 0 if all(verdicts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
