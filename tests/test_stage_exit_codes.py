"""The rule that stops a stage reporting success after writing nothing."""

from unittest.mock import patch

import pandas as pd
import pytest

from src.crispdm.stage import stage_exit_code


def test_a_stage_that_wrote_nothing_fails():
    """The exact shape of the 2026-09-30 nightly.

    8,350 candidates, every one of them raising, zero rows, and an exit code of
    zero. The per-item error counter only ever reached the log, so nothing in the
    return path noticed.
    """
    assert stage_exit_code("populate_fundamentals", attempted=8350, written=0, errors=8350) == 1


def test_a_stage_that_wrote_something_succeeds():
    assert stage_exit_code("populate_fundamentals", attempted=8350, written=1246309, errors=8) == 0


def test_some_errors_do_not_fail_the_stage():
    """A stage that errors on 3 of 10,000 securities has done its job.

    Failing here would train everyone to ignore the exit code, which is how the
    original defect survived: the nightly could have been failing loudly for
    months without anyone reading it.
    """
    assert stage_exit_code("populate_market_data", attempted=10000, written=9997, errors=3) == 0


def test_a_stage_with_nothing_to_do_succeeds():
    """Zero attempts is not a failure, it is a no-op.

    This is the case the check has to get right, and the reason ``skipped`` is
    excluded: a nightly that finds every row already current and writes nothing
    has succeeded, and failing it would make the pipeline unrunnable on the
    morning after a good run.
    """
    assert stage_exit_code("populate_dividend_data", attempted=0, written=0) == 0
    assert stage_exit_code("populate_dividend_data", attempted=0, written=0, errors=0) == 0


def test_skipped_units_excuse_an_empty_run():
    """Everything already current: attempted, nothing written, still success.

    This is the false-positive the rule is most likely to produce, so it is
    pinned directly. ``skipped`` is what separates a rerun on an up-to-date
    warehouse from a run in which every unit failed.
    """
    assert stage_exit_code("populate_dividend_data", attempted=5000, written=0, skipped=5000) == 0
    # No skips, same written count: this is the failure.
    assert stage_exit_code("populate_dividend_data", attempted=5000, written=0, skipped=0) == 1


def test_the_error_count_alone_never_fails_a_stage():
    """Errors are reported in the message, not used as the trigger.

    Worth its own test because it is the tempting simplification: `return 1 if
    errors`. That is wrong in both directions -- a long tail of single-security
    failures is normal, and a stage can fail every unit while somehow reporting
    no errors at all.
    """
    assert stage_exit_code("stage", attempted=100, written=100, errors=99) == 0
    assert stage_exit_code("stage", attempted=0, written=0, errors=500) == 0


def test_the_failure_message_names_the_stage_and_the_counts():
    """A silent non-zero exit is only marginally better than a silent zero.

    The message has to say which stage, how much it tried, and how much it
    wrote, because the first thing anyone does with a failed nightly is read
    the log.
    """
    err = pytest.MonkeyPatch()
    captured = []
    import sys

    real_stderr = sys.stderr

    class _Capture:
        def write(self, text):
            captured.append(text)

        def flush(self):
            pass

    err.setattr(sys, "stderr", _Capture())
    try:
        assert stage_exit_code("populate_sec_documents", attempted=5, written=0, errors=5) == 1
    finally:
        err.undo()
        sys.stderr = real_stderr

    message = "".join(captured)
    assert "populate_sec_documents" in message
    assert "5 attempted" in message
    assert "5 errors" in message
    assert "wrote nothing" in message


def test_score_rank_fails_on_an_empty_feature_table():
    """The one stage that could not see the failure, because it *was* the failure.

    Every other stage got a total-failure guard in this pass. `score_rank` had
    the same defect and no way to notice it: an empty `model.features` meant no
    rows to score, and it exited 0 while every score already in `model.scores`
    went on looking current. The audit says the nightly passed.
    """
    import scripts.score_rank as score_rank

    with patch.object(score_rank, "read_df", return_value=pd.DataFrame()):
        assert score_rank.main() == 1
