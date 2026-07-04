import pytest

from intent_packages.canonical import CanonicalError, jcs, package_hash


def test_jcs_sorts_keys_no_whitespace():
    assert jcs({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_jcs_rejects_float():
    with pytest.raises(CanonicalError):
        jcs({"x": 1.5})


def test_jcs_unicode_and_nesting():
    assert jcs({"z": [3, 2], "a": "é"}) == '{"a":"é","z":[3,2]}'


def test_status_excluded_from_hash():
    a = {"package_id": "p", "status": "draft", "revision": 1}
    b = {"package_id": "p", "status": "approved", "revision": 1}
    assert package_hash(a) == package_hash(b)


def test_hash_is_key_order_and_reformat_invariant():
    a = {"a": 1, "b": {"c": 2, "d": 3}}
    b = {"b": {"d": 3, "c": 2}, "a": 1}
    assert package_hash(a) == package_hash(b)


def test_hash_is_stable_sha256_hex():
    h = package_hash({"package_id": "p", "revision": 1})
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
