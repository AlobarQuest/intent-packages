"""Shared evidence-tag check (WS-2.2 spec §5), used by every profile.

Each profile owns a fixed `tag -> required evidence_type` mapping. Every
`acceptance[].evidence` string must start with one of that profile's tags
(case-sensitive prefix, colon required); the item's `evidence_type` must
match the tag's required value. This is deliberately an enum-of-producers
check, not an evidence-payload framework (see spec §5).
"""
from __future__ import annotations


def check_evidence_tags(package: dict, tag_to_type: dict[str, str]) -> list[str]:
    acceptance = package.get("acceptance")
    if not isinstance(acceptance, list):
        return []

    valid_prefixes = sorted(tag_to_type)
    errors: list[str] = []

    for i, item in enumerate(acceptance):
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence")
        if not isinstance(evidence, str):
            continue  # universal check A already flags a non-str/empty evidence

        matched_tag = next((tag for tag in tag_to_type if evidence.startswith(tag)), None)
        if matched_tag is None:
            errors.append(
                f"acceptance[{i}].evidence: {evidence!r} does not start with a "
                f"recognized producer tag (valid: {valid_prefixes})"
            )
            continue

        expected_type = tag_to_type[matched_tag]
        actual_type = item.get("evidence_type")
        if actual_type != expected_type:
            errors.append(
                f"acceptance[{i}].evidence_type: tag {matched_tag!r} requires "
                f"evidence_type {expected_type!r}, got {actual_type!r}"
            )

    return errors
