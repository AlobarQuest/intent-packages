"""Cross-file semantic validate checks (spec §6): status mirror (S), hash
drift (H), authority envelope (T), lineage consistency (L).

These check `package.yaml` against `lineage.yaml` (and, for T, the registry
vocabulary) — the "does this package's cross-file/cross-system state cohere"
half of validate, as opposed to `validate.py`'s single-file structural
checks (K/J/ID/TR/A). Kept in a separate module so `validate.py` doesn't
grow unwieldy; `validate_package` just calls `cross_file_errors`.

Every function here returns *bare* messages (no file prefix) except
`cross_file_errors`, which prefixes each with the file it concerns
(`package.yaml:` or `lineage.yaml:`) before returning.
"""
from __future__ import annotations

from pathlib import Path

from intent_packages import canonical, lifecycle, lineage, registry
from intent_packages.loader import LoadError


def status_mirror_errors(pkg: dict, lin: dict) -> list[str]:
    """Check S: package.yaml.status must equal lineage.yaml.current_state."""
    status = pkg.get("status")
    current_state = lin.get("current_state")
    if status == current_state:
        return []
    return [
        f"status: {status!r} does not match lineage current_state {current_state!r}"
    ]


def hash_drift_errors(pkg: dict, lin: dict) -> list[str]:
    """Check H: in a drift-locked status, the live intent hash must equal the
    current revision's recorded hash (spec §4.2). Wording differs
    pre-execution (points to `revise`) vs. once execution has begun (points
    to a superseding package)."""
    status = pkg.get("status")
    if status not in lifecycle.DRIFT_LOCKED:
        return []

    live_hash = canonical.package_hash(pkg)
    recorded_hash = lineage.current_revision_hash(lin)
    if live_hash == recorded_hash:
        return []

    if status in lifecycle.REVISE_LEGAL_FROM:
        return ["hash: intent changed since the recorded revision — run 'revise'"]
    return [
        "hash: intent materially changed after execution began — "
        "create a superseding package"
    ]


def _authority_duplicate_errors(membership: dict[str, list[str]]) -> list[str]:
    """For each capability term, decide between the cross-list message (term
    present in >=2 *distinct* lists) and the same-list message (term repeated
    within a single list) — the two are mutually exclusive per term."""
    errors: list[str] = []
    for term, list_names in membership.items():
        distinct_lists = sorted(set(list_names))
        if len(distinct_lists) > 1:
            errors.append(
                f"authority: capability term {term!r} appears in more than one "
                f"list ({', '.join(distinct_lists)})"
            )
        elif len(list_names) > 1:
            errors.append(
                f"authority.{distinct_lists[0]}: capability term {term!r} "
                "is listed more than once"
            )
    return errors


def authority_errors(pkg: dict) -> list[str]:
    """Check T: no capability term in more than one of allowed/
    requires_approval/prohibited (registry-independent); every term in the
    registry vocabulary, when the registry is available."""
    authority = pkg.get("authority")
    if not isinstance(authority, dict):
        return []

    lists: dict[str, list] = {}
    for list_name in ("allowed", "requires_approval", "prohibited"):
        value = authority.get(list_name)
        lists[list_name] = value if isinstance(value, list) else []

    membership: dict[str, list[str]] = {}
    for list_name, terms in lists.items():
        for term in terms:
            membership.setdefault(term, []).append(list_name)

    errors = _authority_duplicate_errors(membership)

    vocabulary = registry.capability_vocabulary()
    if vocabulary is not None:
        all_terms = sorted(membership)
        for term in all_terms:
            if term not in vocabulary:
                errors.append(
                    f"authority: unknown capability term {term!r} — add it to the "
                    "registry (capabilities.yaml) via a registry PR"
                )

    return errors


def _check_revisions(lin: dict, errors: list[str]) -> dict[int, object]:
    """Monotonic/unique revisions (at least one). Returns revision-number ->
    recorded-hash, for the approvals check below."""
    revisions = lin.get("revisions")
    revision_hashes: dict[int, object] = {}
    if not isinstance(revisions, list) or not revisions:
        errors.append("revisions must be a non-empty list")
        return revision_hashes

    seen: set[int] = set()
    for i, rev in enumerate(revisions):
        if not isinstance(rev, dict):
            errors.append(f"revisions[{i}] must be a mapping")
            continue
        rev_num = rev.get("revision")
        if not isinstance(rev_num, int) or isinstance(rev_num, bool) or rev_num <= 0:
            errors.append(f"revisions[{i}].revision must be a positive integer")
            continue
        if rev_num in seen:
            errors.append(f"revisions[{i}].revision {rev_num} is a duplicate")
            continue
        seen.add(rev_num)
        revision_hashes[rev_num] = rev.get("hash")
    return revision_hashes


def _check_current_state(lin: dict, errors: list[str]) -> None:
    current_state = lin.get("current_state")
    if current_state not in lifecycle.STATES:
        errors.append(f"current_state {current_state!r} is not a legal lifecycle state")


def _check_transitions(lin: dict, errors: list[str]) -> None:
    """Every `kind: transition` entry must be a legal edge (§5.2);
    `kind: revision`/`kind: supersession` entries are exempt (§4.2)."""
    transitions = lin.get("transitions")
    if not isinstance(transitions, list):
        return
    for i, tr in enumerate(transitions):
        if not isinstance(tr, dict):
            errors.append(f"transitions[{i}] must be a mapping")
            continue
        if tr.get("kind") in ("revision", "supersession"):
            continue
        src, dst = tr.get("from"), tr.get("to")
        if not lifecycle.is_legal_transition(src, dst):
            errors.append(f"transitions[{i}]: {src!r} -> {dst!r} is not a legal transition")


def _check_approvals(lin: dict, revision_hashes: dict[int, object], errors: list[str]) -> None:
    """Every approval must reference an existing revision with a matching hash."""
    approvals = lin.get("approvals")
    if not isinstance(approvals, list):
        return
    for i, appr in enumerate(approvals):
        if not isinstance(appr, dict):
            errors.append(f"approvals[{i}] must be a mapping")
            continue
        rev_num = appr.get("revision")
        if rev_num not in revision_hashes:
            errors.append(
                f"approvals[{i}].revision {rev_num!r} does not reference an existing revision"
            )
            continue
        if appr.get("approved_hash") != revision_hashes[rev_num]:
            errors.append(
                f"approvals[{i}].approved_hash does not match "
                f"revisions[revision={rev_num}].hash"
            )


def _check_grants(lin: dict, errors: list[str]) -> None:
    grants = lin.get("grants")
    if grants is not None and not isinstance(grants, list):
        errors.append("grants must be a list")


def lineage_consistency_errors(lin: dict) -> list[str]:
    """Check L: monotonic/unique revisions (at least one); current_state is a
    legal lifecycle state (NOT required to be reachable via recorded
    transitions — see task-8 report for why); every `kind: transition` entry
    is a legal edge (`kind: revision`/`kind: supersession` entries are
    exempt, per spec §4.2); approvals reference existing revisions with a
    matching hash; `grants`, if present, is a list."""
    errors: list[str] = []
    revision_hashes = _check_revisions(lin, errors)
    _check_current_state(lin, errors)
    _check_transitions(lin, errors)
    _check_approvals(lin, revision_hashes, errors)
    _check_grants(lin, errors)
    return errors


def cross_file_errors(pkg: dict, pkg_dir: str | Path) -> list[str]:
    """Run checks S/H/T/L and return fully file-prefixed error strings.

    A missing/unreadable lineage.yaml is surfaced as a single lineage.yaml
    error rather than raising — check T (registry-only, no lineage needed)
    still runs.
    """
    errors = [f"package.yaml: {e}" for e in authority_errors(pkg)]

    try:
        lin = lineage.read(pkg_dir)
    except (LoadError, OSError) as exc:
        errors.append(f"lineage.yaml: {exc}")
        return errors

    errors.extend(f"package.yaml: {e}" for e in status_mirror_errors(pkg, lin))
    errors.extend(f"package.yaml: {e}" for e in hash_drift_errors(pkg, lin))
    errors.extend(f"lineage.yaml: {e}" for e in lineage_consistency_errors(lin))
    return errors
