"""Model, feature and data versioning utilities.

The version strings are the contract a stored row is read under. They must match
the constants in ``scripts.evaluate_walk_forward`` (the checkpoint contract) and
the defaults in ``src.crispdm.scoring.predictions`` (what is written to
``model.predictions``); ``tests/test_versioning.py`` pins all three together so
a bump in one place cannot silently diverge from the others.

``FEATURE_SET_V1`` is the same list object as ``src.crispdm.model.FEATURES``:
both import it from the dependency-free ``src.crispdm.feature_set`` module, so
there is no duplicated list to drift and no import cycle.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .feature_set import FEATURES


def compute_feature_set_hash(feature_names: list[str]) -> str:
    """Compute hash of feature set definition."""
    sorted_features = sorted(feature_names)
    content = json.dumps(sorted_features, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_model_config_hash(config: dict[str, Any]) -> str:
    """Compute hash of model configuration."""
    content = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


#: Must equal ``src.crispdm.model.FEATURES`` (same object; pinned by tests).
FEATURE_SET_V1 = FEATURES

FEATURE_VERSION = "features_v5"
DATA_VERSION = "sec_xbrl_v3"
MODEL_VERSION = "rule_scoring_v1"
