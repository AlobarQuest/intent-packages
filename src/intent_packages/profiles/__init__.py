"""Delivery-profile registry and dispatch (WS-2.2 spec §2; unified WS-P2.10).

A profile extends the universal intent-package envelope via the reserved
`profile`/`profile_fields` keys — it never adds a new top-level `package.yaml`
key. `validate_profile()` is called from `validate.validate_package()` as
check P after the universal checks pass.
"""

from __future__ import annotations

from intent_packages.profiles import base, infrastructure_change, software_delivery
from intent_packages.profiles.base import AuthorityDefaults, DeliveryProfile

__all__ = [
    "PROFILES",
    "KNOWN_EVIDENCE_PREFIXES",
    "AuthorityDefaults",
    "DeliveryProfile",
    "validate_profile",
]

PROFILES: dict[str, DeliveryProfile] = {
    p.name: p
    for p in (
        software_delivery.DELIVERY_PROFILE,
        infrastructure_change.DELIVERY_PROFILE,
    )
}
KNOWN_EVIDENCE_PREFIXES = frozenset(
    {"ci:", "gate:", "scan:", "review:", "health:", "human:", "plan:", "backup:"}
)


def validate_profile(package: dict) -> list[str]:
    """Check P: dispatch to the named profile, if any.

    Returns [] when `profile` is absent/null (a universal-only package is
    unaffected). Returns a single actionable error naming the valid choices
    when `profile` is set to an unregistered name. Otherwise runs the
    profile's validator plus the shared forbidden-evidence-type check.
    """
    name = package.get("profile")
    if name is None:
        errors = []
        if "profile_fields" in package:
            errors.append("profile_fields: requires a declared profile")
        return errors
    if not isinstance(name, str):
        return []  # _check_k_and_j already reports "profile: expected str"
    if name not in PROFILES:
        return [f"profile: unknown profile {name!r}; valid: {sorted(PROFILES)}"]
    profile = PROFILES[name]
    errors = list(profile.validate(package)) if profile.validate else []
    errors.extend(base.check_forbidden_evidence_types(package, profile.forbidden_evidence_types))
    return errors
