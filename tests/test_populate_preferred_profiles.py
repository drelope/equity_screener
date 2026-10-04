from scripts import populate_preferred_profiles


class _RowCount:
    @property
    def rowcount(self):
        return 1


class _Capturer:
    """Mock connection that records the last executed statement + params."""

    def __init__(self):
        self.statement = None
        self.params = None
        self.statements = []

    def execute(self, statement, params=None):
        self.statement = str(statement)
        self.params = params or {}
        self.statements.append((self.statement, self.params))
        return _RowCount()


def _facts_payload():
    return {
        "entityName": "ACRES COMMERCIAL REALTY CORP.",
        "facts": {
            "us-gaap": {
                "PreferredStockDividendRatePercentage": {
                    "units": {"pure": [{"val": 0.085, "end": "2024-12-31"}]}
                },
                "PreferredStockLiquidationPreferenceValue": {
                    "units": {"USD": [{"val": 25, "end": "2024-12-31"}]}
                },
            }
        },
    }


def test_upsert_preferred_profile_builds_preferred_row():
    capturer = _Capturer()
    candidate = {
        "security_id": "security-acr-pd",
        "ticker": "ACR-PD",
        "cik": "0001332551",
        "security_name": "ACRES Commercial Realty Corp.",
        "security_type": "preferred stock",
        "raw_payload": _facts_payload(),
    }

    count = populate_preferred_profiles.upsert_preferred_profile(capturer, candidate)

    assert count == 1
    params = capturer.params
    assert params["security_id"] == "security-acr-pd"
    assert params["ticker"] == "ACR-PD"
    assert params["provider"] == "SEC_XBRL"
    assert params["security_type"] == "preferred stock"
    assert params["coupon_rate"] is None
    assert params["liquidation_preference"] is None
    assert '"coupon_rate": 8.5' in params["raw_payload"]
    assert '"liquidation_preference": 25' in params["raw_payload"]
    assert '"sec_xbrl_scope": "issuer_level_unallocated"' in params["raw_payload"]
    assert "sector = COALESCE(EXCLUDED.sector, current_profile.sector)" in capturer.statement
    assert "industry = COALESCE(EXCLUDED.industry, current_profile.industry)" in capturer.statement
    assert "SEC_XBRL+OPENBB_YFINANCE" in capturer.statement
    assert (
        "coupon_rate = COALESCE(EXCLUDED.coupon_rate, current_profile.coupon_rate)"
        in capturer.statement
    )
    assert "current_profile.liquidation_preference" in capturer.statement
    assert "COALESCE(current_profile.raw_payload, '{}'::jsonb)" in capturer.statement
    assert len(capturer.statements) == 1
    assert "UPDATE reference.securities" not in capturer.statement


def test_upsert_preferred_profile_falls_back_when_no_facts():
    capturer = _Capturer()
    candidate = {
        "security_id": "security-lfmdp",
        "ticker": "LFMDP",
        "cik": "0000948320",
        "security_name": "LifeMD, Inc.",
        "security_type": "preferred stock",
        "raw_payload": None,
    }

    populate_preferred_profiles.upsert_preferred_profile(capturer, candidate)

    assert capturer.params["coupon_rate"] is None
    assert capturer.params["liquidation_preference"] is None
    assert capturer.params["security_type"] == "preferred stock"
    assert '"sec_xbrl"' not in capturer.params["raw_payload"]
