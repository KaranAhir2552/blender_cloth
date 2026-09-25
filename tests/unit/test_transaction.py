from ai_garment.core.transaction import Transaction


def test_rollback_runs_in_reverse():
    log = []
    tx = Transaction("t")
    tx.record("a", lambda: log.append("a"))
    tx.record("b", lambda: log.append("b"))
    rep = tx.rollback()
    assert log == ["b", "a"]
    assert rep.ok and rep.undone == ["b", "a"]


def test_failing_undo_is_reported_and_others_still_run():
    log = []
    tx = Transaction("t")
    tx.record("a", lambda: log.append("a"))

    def boom():
        raise RuntimeError("cannot undo")

    tx.record("b", boom)
    rep = tx.rollback()
    assert log == ["a"]
    assert not rep.ok
    assert "cannot undo" in rep.errors[0]


def test_commit_clears_journal():
    log = []
    tx = Transaction("t")
    tx.record("a", lambda: log.append("a"))
    tx.commit()
    rep = tx.rollback()
    assert log == []
    assert rep.undone == []
    assert rep.warnings


def test_context_manager_rolls_back_on_exception():
    log = []
    try:
        with Transaction("t") as tx:
            tx.record("a", lambda: log.append("a"))
            raise ValueError("fail")
    except ValueError:
        pass
    assert log == ["a"]
