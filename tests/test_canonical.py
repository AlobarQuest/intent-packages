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


def test_jcs_rejects_non_string_dict_key():
    with pytest.raises(CanonicalError):
        jcs({1: "a"})


def test_key_sort_uses_utf16_code_unit_order_not_codepoint_order():
    # U+1F600 encodes as a UTF-16 surrogate pair (D83D DE00), whose first code
    # unit (0xD83D) is less than U+FFFF's single code unit (0xFFFF) -- so RFC
    # 8785's UTF-16-code-unit key ordering puts it FIRST, even though its
    # codepoint value (0x1F600) is numerically larger than 0xFFFF.
    out = jcs({"\U0001f600": 1, "￿": 2})
    assert out.index("\U0001f600") < out.index("￿")


def test_ascii_key_order_unchanged_by_utf16_sort():
    # For pure-ASCII keys, UTF-16-BE byte order and codepoint order coincide,
    # so existing ASCII-keyed hashes (e.g. the dogfood package) are stable.
    assert jcs({"b": 1, "a": 2, "aa": 3}) == '{"a":2,"aa":3,"b":1}'
