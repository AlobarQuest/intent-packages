def test_vocab_loaded(fake_registry, monkeypatch):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    from intent_packages import registry

    vocabulary = registry.capability_vocabulary()
    assert vocabulary is not None
    assert "merge_to_main" in vocabulary


def test_human_operator(fake_registry, monkeypatch):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    from intent_packages import registry

    assert registry.is_human_operator("devon")
    assert not registry.is_human_operator("claude-code-interactive")  # profile != human-operator-v1


def test_absent_registry_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path / "nope"))
    from intent_packages import registry

    assert registry.capability_vocabulary() is None
