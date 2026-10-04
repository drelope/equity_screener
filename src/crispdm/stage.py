"""Shared exit-code rule for the ETL stage scripts.

Every population script returns 0 once its work function has finished, and the
per-item ``errors += 1`` counter only ever reached the log. That combination is
what let the 2026-09-30 02:00 nightly write zero fundamentals rows, fail 8,350
times on its way, and still be recorded as a successful run: the stage had work
to do, every unit of it failed, and nothing in the return path noticed.

``stage_exit_code`` is the single place that notices. It is deliberately not a
check on ``errors`` -- a stage that errors on 3 of 10,000 securities has done its
job, and failing the nightly for that would train everyone to ignore the exit
code. The fault worth failing on is the one where the run committed to writing
something and wrote nothing at all.

``skipped`` is excluded from the test, and that exclusion is the difference
between a useful check and one that cries wolf. Units passed over because they
are already current are a stage working correctly, so a nightly that finds every
row cached and writes nothing is a success. The same zero-write result from a
run that tried and failed is not.
"""

import sys


def stage_exit_code(stage, attempted, written, skipped=0, errors=0):
    """Return 1 when a stage attempted work and produced nothing.

    ``attempted`` is the number of units the run committed to writing,
    ``written`` how many it actually wrote, and ``skipped`` how many it
    deliberately passed over as already current. ``errors`` is reported but
    never triggers the failure on its own.
    """
    if attempted and not written and not skipped:
        print(
            f"✗ {stage} wrote nothing: {attempted} attempted, {errors} errors, "
            "0 skipped. Reporting failure rather than success.",
            file=sys.stderr,
        )
        return 1
    return 0
