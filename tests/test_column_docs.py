"""The column-definition helper behind the hover tooltips.

The catalog read is monkeypatched, so these run without a database and pin the resolution
rules: a relation-scoped lookup wins, a bare name resolves only when unambiguous, and a
curated note covers a label that has no column of its own.
"""

from app import column_docs

FAKE = {
    "by_relation": {
        "raw.dividend_data": {"frequency": "cadence label", "amount": "per-share amount"},
        "reference.securities": {"security_id": "the securities key"},
    },
    "by_name": {"frequency": "cadence label"},
}


def fake_comments():
    return FAKE


def test_relation_scoped_lookup(monkeypatch):
    monkeypatch.setattr(column_docs, "_comments", fake_comments)
    assert column_docs.comment("raw.dividend_data", "frequency") == "cadence label"


def test_ambiguous_name_resolves_only_with_its_relation(monkeypatch):
    monkeypatch.setattr(column_docs, "_comments", fake_comments)
    assert column_docs.comment_any("security_id") is None
    assert column_docs.comment("reference.securities", "security_id") == "the securities key"


def test_unknown_column_has_no_help(monkeypatch):
    monkeypatch.setattr(column_docs, "_comments", fake_comments)
    assert column_docs.comment("raw.dividend_data", "nope") is None
    assert column_docs.help_text(relation="raw.dividend_data", column="nope") is None


def test_a_note_stands_alone_or_is_appended_to_the_definition(monkeypatch):
    monkeypatch.setattr(column_docs, "_comments", fake_comments)
    assert column_docs.help_text(column="nope", note="a note") == "a note"
    assert (
        column_docs.help_text(relation="raw.dividend_data", column="amount", note="a note")
        == "per-share amount\n\na note"
    )


def test_config_for_keeps_only_columns_with_a_definition(monkeypatch):
    monkeypatch.setattr(column_docs, "_comments", fake_comments)
    config = column_docs.config_for(
        "raw.dividend_data", ["frequency", "nope"], notes={"nope": "a note"}
    )
    assert set(config) == {"frequency", "nope"}
    assert config["frequency"]["help"] == "cadence label"
    assert config["nope"]["help"] == "a note"


def test_config_map_filters_to_the_columns_present(monkeypatch):
    monkeypatch.setattr(column_docs, "_comments", fake_comments)
    specs = {
        "frequency": ("raw.dividend_data", "frequency", None),
        "absent": ("raw.dividend_data", "amount", "not in the frame"),
    }
    config = column_docs.config_map(specs, ["frequency"])
    assert set(config) == {"frequency"}
    assert config["frequency"]["help"] == "cadence label"
