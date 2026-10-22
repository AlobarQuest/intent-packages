"""The rotation destination format, held to the fixture the orchestrator shares.

`tests/fixtures/rotation_destination_format.json` is a byte-identical copy of the file of the same
name in AlobarQuest/orchestrator, and `DESTINATION_FORMAT_SHA256` is identical in both repos' tests,
so a one-sided change to the format fails here rather than at the rotation executor's first claim.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from intent_packages.destination_format import BOOLEAN_FIELDS, IDENTITY_FIELDS, destination_error

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rotation_destination_format.json"
DESTINATION_FORMAT_SHA256 = "3c81cc3d22882598efa0486af4bf980f620f482243198ae1912f0134c0453f41"
FORMAT = json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_fixture_is_unchanged():
    """A one-sided edit here means the orchestrator's copy has silently drifted."""
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == DESTINATION_FORMAT_SHA256


def test_the_tables_are_the_fixture_s():
    assert {kind: list(fields) for kind, fields in IDENTITY_FIELDS.items()} == FORMAT[
        "identity_fields"
    ]
    assert sorted(BOOLEAN_FIELDS) == FORMAT["boolean_fields"]


@pytest.mark.parametrize(
    "destination",
    [e["destination"] for e in FORMAT["examples"]] + FORMAT["credential_example"]["destinations"],
)
def test_each_example_is_accepted(destination):
    assert destination_error(destination) is None


@pytest.mark.parametrize("destination", FORMAT["refused"])
def test_each_refused_string_is_refused(destination):
    assert destination_error(destination) is not None
