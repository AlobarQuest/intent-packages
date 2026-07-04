"""Domain-profile registry and dispatch (WS-2.2 spec §2).

A profile extends the universal intent-package envelope (WS-2.1) via the reserved
`profile`/`profile_fields` keys — it never adds a new top-level `package.yaml` key.
`validate_profile()` is called from `validate.validate_package()` as one more check
(check P) after the universal checks pass.
"""
from __future__ import annotations

from collections.abc import Callable

from intent_packages.profiles import software_delivery

PROFILES: dict[str, Callable[[dict], list[str]]] = {
    "software-delivery": software_delivery.validate,
}


def validate_profile(package: dict) -> list[str]:
    """Check P: dispatch to the named profile's validator, if any.

    Returns [] when `profile` is absent/null (a universal-only package is
    unaffected, per AC-003). Returns a single actionable error naming the
    valid choices when `profile` is set to an unregistered name. Otherwise
    delegates to that profile's own `validate(package) -> list[str]`.
    """
    name = package.get("profile")
    if name is None:
        return []
    if not isinstance(name, str):
        return []  # _check_k_and_j already reports "profile: expected str"
    if name not in PROFILES:
        return [f"profile: unknown profile {name!r}; valid: {sorted(PROFILES)}"]
    return PROFILES[name](package)
