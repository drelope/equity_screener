"""Schema drift detection.

`scripts/migrate.py --check` verifies the ledger: all migrations recorded, none
pending. That is not the same as verifying the database, and during an audit the
two diverged in a way the ledger could not see. A view had been replaced by hand
with an older definition, and `--check` reported "schema is up to date; no pending
migrations". Re-running the migrator would not have repaired it either, since the
migration was already applied.

`scripts/check_schema_drift.py` closes that by building a scratch database from
the repository and diffing its catalog against the live one. These tests cover the
logic that does not need a live database; the end-to-end run is the script itself,
because it creates and drops a database and so should not happen as a side effect
of the test suite.
"""

from pathlib import Path

import pytest

from scripts.check_schema_drift import (
    ACCEPTED_DIFFERENCES,
    _raise_system_exit,
    init_db_inline_migrations,
    partition,
    scratch_url,
)
from src.crispdm.schema_fingerprint import diff, format_report, oneline

ROOT = Path(__file__).resolve().parent.parent


class TestDiff:
    def test_identical_fingerprints_produce_nothing(self):
        fp = {"index a.b": "X", "column a.b.c": "int"}
        assert diff(fp, dict(fp)) == []

    def test_reports_each_kind_of_difference(self):
        live = {"index a.gone": "X", "column a.t.c": "int null=YES", "viewdef a.v": "old"}
        ref = {"index a.new": "Y", "column a.t.c": "int null=NO", "viewdef a.v": "new"}
        found = {(status, key) for status, key, *_ in diff(live, ref)}
        assert found == {
            ("missing_from_reference", "index a.gone"),
            ("differs", "column a.t.c"),
            ("differs", "viewdef a.v"),
            ("missing_from_live", "index a.new"),
        }

    def test_a_constraint_and_a_table_of_the_same_name_do_not_collide(self):
        """Constraints are keyed by name, not by the table they sit on.

        Keying on the table collapses a table's primary key, foreign keys and
        checks onto one key, so the check reports nonsense or nothing at all.
        """
        live = {"constraint raw.t": "ON raw.t PRIMARY KEY (id)"}
        ref = {"constraint raw.t": "ON raw.t FOREIGN KEY (s) REFERENCES x(y)"}
        ((status, key, *_),) = diff(live, ref)
        assert status == "differs"
        assert key == "constraint raw.t"


class TestReport:
    def test_missing_value_reads_as_absent(self):
        assert oneline(None) == "<absent>"

    def test_long_definitions_are_truncated(self):
        assert oneline("x" * 500, width=50).endswith("...")
        assert len(oneline("x" * 500, width=50)) == 50

    def test_report_leads_with_the_most_structural_problem(self):
        problems = [
            ("missing_from_reference", "index a.b", "X", None),
            ("differs", "column a.b.c", "X", "Y"),
            ("missing_from_live", "index a.d", None, "Z"),
        ]
        first_line = format_report(problems).splitlines()[0]
        assert "1 missing_from_live" in first_line
        assert "3 difference(s)" in first_line

    def test_no_problems_reports_cleanly(self):
        assert format_report([]) == "no drift"


class TestAcceptedDifferences:
    def test_one_entry_covers_a_constraint_and_its_backing_index(self):
        """Both keys name the same object, so one reason should apply to both.

        Exercises the name-matching mechanism with a synthetic entry: the live
        ``ACCEPTED_DIFFERENCES`` is deliberately empty since V0077 closed the last
        one, and the mechanism has to keep working for the next accepted
        difference.
        """
        problems = [
            ("missing_from_reference", "constraint example.thing_unique", "X", None),
            ("missing_from_reference", "index example.thing_unique", "X", None),
        ]
        unexplained, accepted = partition(problems, accepted={"example.thing_unique": "reason"})
        assert unexplained == []
        assert len(accepted) == 2

    def test_an_unlisted_object_is_still_unexplained(self):
        problems = [("differs", "viewdef model.current_predictions", "X", "Y")]
        unexplained, accepted = partition(problems)
        assert len(unexplained) == 1
        assert accepted == []

    def test_every_entry_states_a_reason(self):
        """An exception without a stated cost is just a way of not looking."""
        for name, reason in ACCEPTED_DIFFERENCES.items():
            assert reason.strip(), f"accepted difference {name} has no reason"
            assert len(reason) > 80, f"accepted difference {name} is not explained"


class TestInlineMigrationExtraction:
    def test_reads_the_list_without_importing_init_db(self):
        """init_db applies its migrations at module scope, so importing it would
        create and initialise a database as a side effect of a drift check."""
        statements = init_db_inline_migrations()
        assert len(statements) > 10
        assert any("securities_pkey" in s for s in statements)

    def test_raises_when_the_list_is_gone(self, tmp_path):
        empty = tmp_path / "init_db.py"
        empty.write_text("x = 1\n")
        with pytest.raises(RuntimeError, match="migrations"):
            init_db_inline_migrations(empty)


class TestScratchUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("postgresql://u:p@h:5432/warehouse", "postgresql://u:p@h:5432/schema_ref_abc"),
            (
                "postgresql://u:p@h/db?sslmode=require",
                "postgresql://u:p@h/schema_ref_abc?sslmode=require",
            ),
        ],
    )
    def test_swaps_only_the_database_name(self, url, expected):
        assert scratch_url(url, "schema_ref_abc") == expected

    def test_rejects_a_url_with_no_database(self):
        with pytest.raises(RuntimeError):
            scratch_url("postgresql://u:p@h:5432", "schema_ref_abc")


class TestBootstrapIsRebuildable:
    """Regression guards for the two defects a reference build exposed.

    Both were found by building a database from the repository and diffing it
    against the live one. Neither is visible to the migration ledger.
    """

    def test_primary_key_swap_is_conditional(self):
        """A bare DROP CONSTRAINT securities_pkey cannot run on a fresh database.

        17 foreign keys reference reference.securities(security_id), so PostgreSQL
        refuses the drop and init_db fails outright on a database built from
        schema.sql -- which already has the primary key on security_id, making the
        swap unnecessary in the first place.
        """
        statements = init_db_inline_migrations()
        swap = [s for s in statements if "securities_pkey" in s]
        assert swap, "the primary key migration disappeared entirely"
        assert any("DO $$" in s and "END IF;" in s for s in swap), (
            "the primary key swap is unconditional again; initialization will fail on "
            "a fresh database because 17 foreign keys depend on securities_pkey"
        )
        assert any("conkey" in s for s in swap), (
            "the guard does not inspect the existing primary key columns, so it "
            "cannot tell whether a swap is needed"
        )

    def test_company_ticker_fk_is_not_reset_to_not_valid(self):
        """Re-running init_db must not undo V0046's VALIDATE CONSTRAINT.

        Dropping and re-adding the constraint always yields NOT VALID, so an
        init_db run after V0046 left the live FK unvalidated while the ledger still
        said the migration had been applied.
        """
        statements = init_db_inline_migrations()
        assert not any(
            "DROP CONSTRAINT IF EXISTS fk_securities_company_ticker" in s for s in statements
        ), "init_db drops fk_securities_company_ticker again; re-adding it resets validation"
        add = [s for s in statements if "ADD CONSTRAINT fk_securities_company_ticker" in s]
        assert add, "the company-ticker foreign key is no longer created by init_db"
        assert all("IF NOT EXISTS" in s for s in add), (
            "the foreign key is added unconditionally; it must only be added when absent"
        )

    def test_schema_declares_the_uniqueness_index_that_duplicate_protection_needs(self):
        """V0039 stopped duplicate active securities by adding a unique index.

        A rebuild from schema.sql alone would have lost it, since init_db creates
        it outside schema.sql.
        """
        schema = (ROOT / "sql" / "schema.sql").read_text()
        assert "ux_security_cik_ticker_type" in schema, (
            "schema.sql does not create the unique index that prevents duplicate "
            "securities; a rebuild would reintroduce the V0039 problem"
        )

    def test_schema_index_names_match_what_the_migrations_created(self):
        """ix_contract_documents_security_id was a name no database ever had."""
        schema = (ROOT / "sql" / "schema.sql").read_text()
        assert "ix_contract_documents_security_id" not in schema
        assert "ix_contract_documents_security\n" in schema


class TestSigtermCleanup:
    def test_sigterm_raises_system_exit_so_finally_runs(self):
        """Default SIGTERM kills the interpreter without unwinding finally, which
        leaked half-built schema_ref_* databases (two found dated 2026-10-13).
        The handler converts it so drop_reference still runs."""
        import signal

        with pytest.raises(SystemExit) as excinfo:
            _raise_system_exit(signal.SIGTERM, None)
        assert excinfo.value.code == 128 + signal.SIGTERM
