from intent_packages import lifecycle as lc


def test_legal_edges():
    assert lc.is_legal_transition("ready_for_review", "approved")
    assert lc.is_legal_transition("approved", "executable")
    assert lc.is_legal_transition("completed", "follow_up_due")
    assert lc.is_legal_transition("in_execution", "superseded")


def test_illegal_edges():
    assert not lc.is_legal_transition("in_execution", "draft")
    assert not lc.is_legal_transition("completed", "draft")
    assert not lc.is_legal_transition("draft", "approved")


def test_terminals_have_no_out_edges():
    for s in lc.TERMINAL:
        assert lc.LEGAL_TRANSITIONS.get(s, frozenset()) == frozenset()


def test_maps_reference_only_known_states():
    for src, dsts in lc.LEGAL_TRANSITIONS.items():
        assert src in lc.STATES
        assert dsts <= lc.STATES
