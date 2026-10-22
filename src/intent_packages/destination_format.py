"""The rotation destination string (ADR-0055), as `profile_fields.destinations` must write it.

The rotation executor (orchestrator `src/rotation_worker/destinations.py`) acts only when a
package's destination list, the unit envelope's and the credential's registry entry are equal, so
all three are written in one format. A string is a `kind`, then each of that kind's identity fields
as `name=<JSON value>`, in the fixed order `IDENTITY_FIELDS` gives, separated by single spaces:

    bws-secret uuid="00000000-0000-0000-0000-000000000000"
    provider name="openrouter"

`tests/fixtures/rotation_destination_format.json` is byte-identical with the orchestrator's copy
and pins this table. A string is valid exactly when re-rendering what it names gives it back.
"""

from __future__ import annotations

import json
import unicodedata

IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "provider": ("name",),
    "bws-secret": ("uuid",),
    "coolify-env": ("instance", "resource_type", "uuid", "key", "redeploy"),
    # `entry` is the key id inside the variable's JSON whose hash this credential's bearer is
    # (orchestrator ADR-0055 amendment 9).
    "coolify-env-hash": ("instance", "resource_type", "uuid", "key", "entry"),
    # A value the application holds in its settings to call another service (orchestrator
    # ADR-0055 amendment 13).
    "coolify-env-held": ("instance", "resource_type", "uuid", "key"),
    "gh-actions-secret": ("repo", "name"),
    "keychain": ("service", "account"),
    "runtime-fetch": ("repo", "ref"),
    "shell-export": ("file", "var"),
}
BOOLEAN_FIELDS = frozenset({"redeploy"})


def destination_error(destination: str) -> str | None:
    """Why `destination` isn't a canonical destination string, or None when it is."""
    kind, _, rest = destination.partition(" ")
    fields = IDENTITY_FIELDS.get(kind)
    if fields is None:
        return f"unknown consumer kind {kind!r}"
    values: list[object] = []
    decoder = json.JSONDecoder()
    position = 0
    for name in fields:
        prefix = f"{name}="
        if not rest.startswith(prefix, position):
            return f"{kind} needs field {name!r} next"
        try:
            value, position = decoder.raw_decode(rest, position + len(prefix))
        except json.JSONDecodeError:
            return f"{kind}: {name} is not a JSON value"
        if (error := _value_error(name, value)) is not None:
            return f"{kind}: {name} {error}"
        values.append(value)
        position += rest.startswith(" ", position)
    rendered = " ".join(
        [
            kind,
            *(
                f"{n}={json.dumps(v, ensure_ascii=False)}"
                for n, v in zip(fields, values, strict=True)
            ),
        ]
    )
    # Anything the loop let through -- trailing text, a missing or doubled space, an escaped
    # character -- makes the re-rendered string differ, so this one comparison refuses it.
    if rendered != destination:
        return "not in canonical form"
    return None


def _value_error(name: str, value: object) -> str | None:
    if name in BOOLEAN_FIELDS:
        return None if isinstance(value, bool) else "must be true or false"
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return "must be a non-blank, trimmed string"
    # Two spellings of one character would read the same on the page and compare unequal.
    if not unicodedata.is_normalized("NFC", value):
        return "must be NFC-normalised"
    return None
