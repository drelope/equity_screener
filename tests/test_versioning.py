"""Pin the version strings and hashes shared by the pipeline, scorer and checkpoint.

A version string is only useful if every writer agrees on it. ``versioning`` was
added with a 31-name feature list and ``FEATURE_VERSION = "v1"`` while the
pipeline was already on ``features_v5``; because nothing imported the module the
drift was invisible. These tests make the module the single contract and fail if
any of the three sources (versioning, the walk-forward checkpoint constants, and
the ``predictions`` defaults) moves apart.
"""

from __future__ import annotations

import inspect

from scripts import evaluate_walk_forward
from src.crispdm.model import FEATURES
from src.crispdm.scoring import predictions
from src.crispdm.versioning import (
    DATA_VERSION,
    FEATURE_SET_V1,
    FEATURE_VERSION,
    MODEL_VERSION,
    compute_feature_set_hash,
    compute_model_config_hash,
)


def test_feature_set_matches_the_model_features():
    assert FEATURE_SET_V1 == FEATURES


def test_versions_match_the_walk_forward_contract():
    # Feature and data versions describe the inputs and are shared with the
    # checkpoint. The model version is intentionally different: the walk-forward
    # logistic regression is a separate model from the production rule scorer,
    # so ``versioning.MODEL_VERSION`` is pinned against ``predictions`` instead.
    assert FEATURE_VERSION == evaluate_walk_forward.FEATURE_VERSION
    assert DATA_VERSION == evaluate_walk_forward.DATA_VERSION
    assert MODEL_VERSION != evaluate_walk_forward.MODEL_VERSION


def test_predictions_defaults_match_the_shared_versions():
    defaults = {
        name: p.default
        for name, p in inspect.signature(predictions).parameters.items()
        if p.default is not inspect.Parameter.empty
    }
    assert defaults["feature_version"] == FEATURE_VERSION
    assert defaults["data_version"] == DATA_VERSION
    assert defaults["model_version"] == MODEL_VERSION


def test_hashes_are_order_independent_and_stable():
    assert compute_feature_set_hash(["a", "b"]) == compute_feature_set_hash(["b", "a"])
    assert compute_feature_set_hash(["a", "b"]) != compute_feature_set_hash(["a", "c"])
    assert compute_model_config_hash({"a": 1, "b": 2}) == compute_model_config_hash(
        {"b": 2, "a": 1}
    )
    assert len(compute_feature_set_hash(["a"])) == 16
    assert len(compute_model_config_hash({"a": 1})) == 16
