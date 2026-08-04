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

What it does:

1. resolve the intended model from `routing-policy.toml`'s `runner-implementation`
   surface, via this repo's own `intent_packages.routing` loader;
2. read `factory-runner`'s `RECOMMENDED_CALLER_PIN` -- the revision callers are
   supposed to run -- and fetch `.github/workflows/factory-runner.yml` at that
   revision;
3. extract the `model:` input of its `claude-code-base-action` step;
4. fail, naming both values, if they differ.

Usage:
    python3 scripts/check_routing_policy_compatibility.py

Exit 0: the policy and the pinned runner agree. Exit 1: they disagree, or the
comparison could not be resolved (unreachable pin, malformed workflow, an
`runner-implementation` surface that no longer names exactly one model, ...).
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


def workflow_model(workflow_text: str) -> str:
    """The `model:` input of the `claude-code-base-action` step.

    Parsed as YAML and matched on the step's `uses:` prefix, not grepped for a
    bare `model:` line -- a `model:` key could in principle appear elsewhere in
    the file, and only the one on this specific step is the value that governs
    a run.
    """
    document = yaml.safe_load(workflow_text)
    for job in (document.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            uses = step.get("uses", "")
            if isinstance(uses, str) and uses.startswith(ACTION_STEP_USES_PREFIX):
                model = (step.get("with") or {}).get("model")
                if not isinstance(model, str) or not model.strip():
                    raise Unresolvable(
                        f"the {ACTION_STEP_USES_PREFIX} step has no non-empty `model:` input"
                    )
                return model
    raise Unresolvable(f"no step using {ACTION_STEP_USES_PREFIX} found in the fetched workflow")


def main() -> int:
    try:
        policy_model = resolve_policy_model_id()
        ref = pinned_revision(fetch(FACTORY_RUNNER_REPO, PIN_FILE_PATH, PIN_FILE_REF))
        runner_model = workflow_model(fetch(FACTORY_RUNNER_REPO, CONSUMER_WORKFLOW_PATH, ref))
    except Unresolvable as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print(f"policy: routing-policy.toml [[surface]] {SURFACE_ID!r} -> {policy_model}")
    print(f"runner: {FACTORY_RUNNER_REPO}@{ref[:8]} {CONSUMER_WORKFLOW_PATH} -> {runner_model}")

    if policy_model == runner_model:
        print(f"\nPASS: the policy and the pinned runner agree on {policy_model!r}.")
        return 0

    print(
        f"\nFAIL: routing-policy.toml declares {SURFACE_ID!r} -> {policy_model!r}, but the "
        f"runner pinned at {FACTORY_RUNNER_REPO}@{ref[:8]} hardcodes {runner_model!r} on its "
        f"{ACTION_STEP_USES_PREFIX} step.\n\n"
        "These must agree, and which one is correct is a routing decision -- this check "
        "does not resolve it. Update the runner's literal to match the policy (or escalate "
        "if the policy itself moved by mistake), then re-run.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
