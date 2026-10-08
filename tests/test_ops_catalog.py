"""The task catalog is the security boundary of the Operations page.

What matters here is what it refuses: unknown tasks, unknown parameters, wrong types, and
text that could become a second flag. Each refusal is tested because a regression here is
a command-injection path from the web UI.
"""

import sys

import pytest

from src.crispdm.ops import catalog


def test_every_catalog_entry_builds_a_command_from_its_defaults():
    for key, task in catalog.CATALOG.items():
        argv = catalog.build_argv(key, {})
        assert argv[:3] == [sys.executable, "-m", task.module]
        assert all(isinstance(part, str) for part in argv)


def test_the_catalog_has_no_destructive_commands():
    """release deletes rows and has its own confirmation and archive; it is not exposed."""
    for task in catalog.CATALOG.values():
        assert "release" not in task.fixed_args
        assert not any(a in task.fixed_args for a in ("--execute", "--confirm", "--force"))
        assert task.timeout_seconds > 0


def test_modules_are_fixed_and_inside_the_scripts_package():
    for task in catalog.CATALOG.values():
        assert task.module.startswith("scripts.") and " " not in task.module


def test_an_unknown_task_is_refused():
    for key in ("rm -rf /", "", "build_features; id", None, "BUILD_FEATURES"):
        with pytest.raises(ValueError, match="unknown task"):
            catalog.build_argv(key, {})


def test_an_unknown_parameter_is_refused_not_ignored():
    with pytest.raises(ValueError, match="unknown parameter"):
        catalog.validate_params("score_rank", {"anything": 1})
    with pytest.raises(ValueError, match="unknown parameter"):
        catalog.validate_params("build_features", {"days": 400, "also": "x"})


def test_parameters_become_flags_and_values_in_order():
    argv = catalog.build_argv("build_features", {"days": 120}, python="py")
    assert argv == ["py", "-m", "scripts.build_features", "--days", "120"]


def test_a_default_is_applied_when_a_parameter_is_omitted():
    assert catalog.validate_params("build_features", {}) == {"days": 400}


def test_empty_optional_values_are_dropped_not_passed_as_empty_flags():
    argv = catalog.build_argv("populate_market_data", {"tickers": "", "limit": None}, python="py")
    assert argv == ["py", "-m", "scripts.populate_market_data"]


def test_a_false_flag_is_omitted_and_a_true_flag_is_added():
    base = catalog.build_argv("run_full_etl", {"skip_derived": False}, python="py")
    flagged = catalog.build_argv("run_full_etl", {"skip_derived": True}, python="py")
    assert "--skip-derived" not in base and "--skip-derived" in flagged
    assert base == ["py", "-m", "scripts.run_full_etl", "--trigger", "manual"]


@pytest.mark.parametrize("value", ["400", 4.5, True, [1], {"a": 1}, -1, 0, 4001, 6])
def test_an_integer_parameter_rejects_everything_that_is_not_an_in_range_int(value):
    with pytest.raises(ValueError):
        catalog.validate_params("build_features", {"days": value})


def test_a_bool_is_not_accepted_as_an_integer():
    # True == 1 in Python; it must not slip through as days=1 (and 1 is below the minimum anyway).
    with pytest.raises(ValueError, match="whole number"):
        catalog.validate_params("populate_market_data", {"limit": True})


@pytest.mark.parametrize(
    "value",
    [
        "--all",  # a second flag
        "KO --all",
        "KO;id",
        "KO,$(id)",
        "KO\nBAC",
        "KO,,",
        "-KO",
        "KO,-BAC",
        "../etc/passwd",
        "A" * 33,
        ",".join(["KO"] * 51),
        "KO BAC",
        "`id`",
        "KO|cat",
        "ΚΟ",  # Greek capitals
    ],
)
def test_the_ticker_parameter_cannot_carry_a_flag_or_a_shell_fragment(value):
    with pytest.raises(ValueError):
        catalog.validate_params("populate_market_data", {"tickers": value})


def test_tickers_are_normalised_and_spaces_around_commas_are_tolerated():
    assert catalog.validate_params("populate_market_data", {"tickers": " ko , bac-pk,BRK.B "}) == {
        "tickers": "KO,BAC-PK,BRK.B"
    }


def test_a_value_that_looks_like_a_flag_stays_one_argv_element():
    argv = catalog.build_argv("populate_market_data", {"tickers": "KO,BAC"}, python="py")
    i = argv.index("--tickers")
    assert argv[i + 1] == "KO,BAC" and argv.count("--tickers") == 1


def test_parameters_must_be_an_object():
    with pytest.raises(ValueError, match="object"):
        catalog.validate_params("score_rank", ["--all"])


def test_verify_treats_exit_one_as_a_finding_not_a_failure():
    assert 1 in catalog.CATALOG["verify_nightly"].ok_exit_codes
    assert catalog.CATALOG["score_rank"].ok_exit_codes == (0,)


def test_only_writers_that_do_not_take_their_own_lock_are_exclusive():
    """run_full_etl takes the pipeline lock itself; a second holder would refuse it."""
    assert catalog.CATALOG["run_full_etl"].exclusive is False
    for key in ("build_features", "score_rank", "populate_audit", "populate_market_data"):
        assert catalog.CATALOG[key].exclusive is True
    for key in ("verify_nightly", "migrate_check", "schema_drift", "ticker_conflicts"):
        assert catalog.CATALOG[key].risk == "read"


def test_describe_command_is_display_only():
    assert catalog.describe_command("score_rank", {}) == "python -m scripts.score_rank"
