"""WS-P2.38: the offline half of the pull-request gate that refuses routing/runner drift.

`scripts/check_routing_policy_compatibility.py` compares `routing-policy.toml`'s
`runner-implementation` surface against the model literal hardcoded on
factory-runner's `claude-code-base-action` step, fetched at factory-runner's own
`RECOMMENDED_CALLER_PIN` revision. The reading is over the network, so it runs as
its own CI job -- but everything it decides WITH is pure, and pure is what gets
tested here:

- the policy resolver returns today's real value, so it is not vacuous;
- it fails loudly on a surface with the wrong shape for a single-literal
  comparison, rather than picking one of several models silently;
- the pin reader accepts only an immutable, fully-resolved revision;
- the workflow parser finds the `model:` input on the right step, not any
  `model:` key anywhere in the file;
- the comparison actually reports a mismatch -- the guard shown firing, not
  merely shown passing.
"""

from __future__ import annotations

import pytest

from scripts import check_routing_policy_compatibility as check


def test_policy_resolver_returns_the_real_value_today():
    """Not vacuous: pins the live policy's answer, independent of the network check."""
    assert check.resolve_policy_model_id() == "claude-sonnet-5"


def test_policy_resolver_rejects_a_two_model_surface(monkeypatch):
    """This check compares against one workflow literal; a surface declaring more
    than one model (a real shape -- see `judgment-ac-verification`) has nothing
    single to compare, so it must fail loudly rather than pick one."""
    from intent_packages import routing

    original_resolve_surface = routing.resolve_surface

    def fake_resolve_surface(policy, surface_id):
        row = original_resolve_surface(policy, surface_id)
        if surface_id == check.SURFACE_ID:
            return routing.RoutingRow(
                id=row.id,
                models=("sonnet-5", "opus-4-8"),
                model_ids=("claude-sonnet-5", "claude-opus-4-8"),
                rationale=row.rationale,
                decided=row.decided,
            )
        return row

    monkeypatch.setattr(check.routing, "resolve_surface", fake_resolve_surface)

    with pytest.raises(check.Unresolvable, match="names 2 model"):
        check.resolve_policy_model_id()


def test_policy_resolver_rejects_a_missing_surface():
    """An absent/renamed surface must not read as agreement -- it must be loud."""
    from intent_packages import routing

    empty_policy = routing.RoutingPolicy(
        version=1, models={}, surfaces={}, change_classes={}, no_llm=()
    )

    with pytest.raises(check.Unresolvable, match="unknown surface"):
        check.resolve_policy_model_id(empty_policy)


def test_pinned_revision_accepts_a_full_sha():
    assert check.pinned_revision("0e047df56f42c8d87f432b9547f0f2fdeb0e61ca\n") == (
        "0e047df56f42c8d87f432b9547f0f2fdeb0e61ca"
    )


@pytest.mark.parametrize(
    "pin_text",
    ["main", "v1", "0e047df", ""],
    ids=["branch", "tag", "short-sha", "empty"],
)
def test_pinned_revision_rejects_anything_but_a_full_sha(pin_text: str):
    """A mutable or malformed pin leaves nothing fixed to compare against."""
    with pytest.raises(check.Unresolvable, match="full 40-character commit SHA"):
        check.pinned_revision(pin_text)


def test_workflow_model_reads_the_action_steps_input():
    workflow = """
jobs:
  run:
    steps:
      - uses: actions/checkout@abc
      - uses: anthropics/claude-code-base-action@e8132bc5e637a42c27763fc757faa37e1ee43b34
        with:
          model: claude-sonnet-5
"""
    assert check.workflow_model(workflow) == "claude-sonnet-5"


def test_workflow_model_ignores_an_unrelated_model_key():
    """A `model:` key elsewhere in the file must not satisfy the check -- only the
    one on the claude-code-base-action step governs a run."""
    workflow = """
jobs:
  run:
    steps:
      - uses: some/other-action@abc
        with:
          model: decoy-value
      - uses: anthropics/claude-code-base-action@e8132bc5e637a42c27763fc757faa37e1ee43b34
        with:
          model: claude-sonnet-5
"""
    assert check.workflow_model(workflow) == "claude-sonnet-5"


def test_workflow_model_is_loud_when_the_action_step_is_missing():
    workflow = "jobs:\n  run:\n    steps:\n      - uses: actions/checkout@abc\n"

    with pytest.raises(check.Unresolvable, match="no step using"):
        check.workflow_model(workflow)


def test_workflow_model_is_loud_when_the_step_has_no_model_input():
    workflow = (
        "jobs:\n  run:\n    steps:\n"
        "      - uses: anthropics/claude-code-base-action@abc\n"
        "        with:\n"
        "          prompt_file: x\n"
    )

    with pytest.raises(check.Unresolvable, match="no non-empty `model:` input"):
        check.workflow_model(workflow)


def test_the_comparison_fires_on_a_divergence(monkeypatch):
    """The guard shown firing: policy and runner disagree, `main` must fail and
    name both values. This is the exact defect class WS-P2.38 was written to
    catch, reproduced as a pure function call rather than over the network."""

    def fake_fetch(repo, path, ref):
        if path == check.PIN_FILE_PATH:
            return "0" * 40
        if path == check.CONSUMER_WORKFLOW_PATH:
            return (
                "jobs:\n  run:\n    steps:\n"
                "      - uses: anthropics/claude-code-base-action@abc\n"
                "        with:\n"
                "          model: claude-opus-4-8\n"
            )
        raise AssertionError(f"unexpected fetch: {path}")

    monkeypatch.setattr(check, "fetch", fake_fetch)

    assert check.main() == 1


def test_the_comparison_passes_on_agreement(monkeypatch, capsys):
    def fake_fetch(repo, path, ref):
        if path == check.PIN_FILE_PATH:
            return "0" * 40
        if path == check.CONSUMER_WORKFLOW_PATH:
            return (
                "jobs:\n  run:\n    steps:\n"
                "      - uses: anthropics/claude-code-base-action@abc\n"
                "        with:\n"
                "          model: claude-sonnet-5\n"
            )
        raise AssertionError(f"unexpected fetch: {path}")

    monkeypatch.setattr(check, "fetch", fake_fetch)

    assert check.main() == 0
    assert "PASS" in capsys.readouterr().out


def test_the_gate_runs_the_script_this_module_tests():
    """A check nothing invokes is the defect it guards against, wearing a different hat."""
    from pathlib import Path

    invocations = [
        path
        for path in Path(".github/workflows").glob("*.yml")
        if "check_routing_policy_compatibility.py" in path.read_text()
    ]

    assert [path.name for path in invocations] == ["routing-policy-compatibility.yml"]
