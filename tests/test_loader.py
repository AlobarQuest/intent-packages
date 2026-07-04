import pytest

from intent_packages.loader import LoadError, load_yaml_strict


def test_rejects_multiple_documents():
    with pytest.raises(LoadError):
        load_yaml_strict("a: 1\n---\nb: 2\n")


def test_timestamp_stays_string_when_quoted():
    d = load_yaml_strict('created_at: "2026-07-03T00:00:00Z"\n')
    assert d["created_at"] == "2026-07-03T00:00:00Z"
    assert isinstance(d["created_at"], str)


def test_unquoted_timestamp_is_not_a_datetime():
    # A bare timestamp must NOT become a datetime object (breaks JSON round-trip).
    d = load_yaml_strict("created_at: 2026-07-03T00:00:00Z\n")
    assert isinstance(d["created_at"], str)


def test_top_level_must_be_mapping():
    with pytest.raises(LoadError):
        load_yaml_strict("- just\n- a\n- list\n")


def test_duplicate_top_level_key_is_rejected():
    with pytest.raises(LoadError):
        load_yaml_strict("title: a\ntitle: b\n")


def test_unique_keys_still_load():
    d = load_yaml_strict("title: a\nother: b\n")
    assert d == {"title": "a", "other": "b"}
