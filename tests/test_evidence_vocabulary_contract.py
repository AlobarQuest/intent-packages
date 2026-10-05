"""The package evidence vocabulary is one set, shared with the orchestrator (SDS 1.1, review 4a).

Neither repository can import the other, so each carries a byte-identical
`tests/fixtures/package_evidence_vocabulary.json` and pins it with the same `CONTRACT_SHA256`.
This side holds `EVIDENCE_TYPES`, which `factory validate` enforces, equal to the fixture. The
orchestrator holds every member supported at intake and classified for its verifier. Adding a
type here without the fixture reds this repository; changing the fixture on one side only reds the
side whose pin no longer matches.
"""

import hashlib
import json
from pathlib import Path

from intent_packages.validate import EVIDENCE_TYPES

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "package_evidence_vocabulary.json"
CONTRACT_SHA256 = "04b4c0c1e4ba8ccc64eec59dccbdc3f4280fade10315a6d5bd75201f2bb81afb"


def test_the_fixture_is_the_pinned_contract() -> None:
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == CONTRACT_SHA256


def test_the_validator_enforces_exactly_the_shared_vocabulary() -> None:
    shared = json.loads(FIXTURE.read_text(encoding="utf-8"))["evidence_types"]

    assert EVIDENCE_TYPES == frozenset(shared)
