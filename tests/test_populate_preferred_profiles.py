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

    def execute(self, statement, params=None):
        self.statement = str(statement)
        self.params = params or {}
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
    assert params["coupon_rate"] == 8.5
    assert params["liquidation_preference"] == 25


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