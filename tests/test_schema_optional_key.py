"""OptionalKey (WS-P2.10): a MapSpec field whose KEY may be absent. Present
values are checked against the wrapped spec; schemas stay closed (unknown
keys are still errors); required keys are unaffected."""

from intent_packages.schema import ListSpec, MapSpec, OptionalKey, _s, _walk

SPEC = MapSpec(
    {
        "required_field": _s(str),
        "optional_scalar": OptionalKey(_s(str)),
        "optional_list": OptionalKey(ListSpec(_s(str))),
    }
)


def _errors(value: dict) -> list[str]:
    errors: list[str] = []
    _walk(value, SPEC, "root", errors)
    return errors


def test_absent_optional_key_is_not_an_error():
    assert _errors({"required_field": "x"}) == []


def test_present_optional_key_is_checked_against_wrapped_spec():
    errs = _errors({"required_field": "x", "optional_scalar": 7})
    assert errs == ["root.optional_scalar: expected str, got int"]


def test_present_valid_optional_key_passes():
    assert _errors({"required_field": "x", "optional_scalar": "y", "optional_list": ["a"]}) == []


def test_optional_list_items_are_checked():
    errs = _errors({"required_field": "x", "optional_list": ["a", 3]})
    assert errs == ["root.optional_list[1]: expected str, got int"]


def test_required_keys_still_required():
    assert _errors({"optional_scalar": "y"}) == ["root.required_field: missing required key"]


def test_unknown_keys_still_rejected():
    errs = _errors({"required_field": "x", "mystery": "y"})
    assert errs == ["root.mystery: unknown key"]


def test_null_optional_value_is_checked_not_skipped():
    # OptionalKey affects key PRESENCE only; a present null hits the wrapped
    # spec's nullability rules like any other value.
    errs = _errors({"required_field": "x", "optional_scalar": None})
    assert errs == ["root.optional_scalar: null is not allowed here"]
