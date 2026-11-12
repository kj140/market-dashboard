from datetime import date

import pytest

from dash.metrics import RawData, carry_forward, compute_metrics, METRIC_FREQ
from dash.models import Metric
from fixtures.series import daily, monthly, quarterly

LIMITS = {"daily": 3, "monthly": 25, "quarterly": 70}


def full_raw() -> RawData:
    sox = [100.0 + i for i in range(150)] + [240.0 - i for i in range(50)]
    return RawData(
        closes={
            "^GSPC": daily([100.0 + i for i in range(300)]),
            "^NDX": daily([200.0 - 0.1 * i for i in range(300)]),
            "^SOX": daily(sox),
            "^N225": daily([300.0 + 0.2 * i for i in range(300)]),
            "JPY=X": daily([150.0 - 0.05 * i for i in range(300)]),
            "CL=F": daily([70.0 + 0.01 * i for i in range(300)]),
        },
        fred={
            "DGS10": daily([4.6] * 5 + [4.2] * 3 + [4.7] * 4),
            "GDP": quarterly([100.0 + 2 * i for i in range(12)]),
            "CPIAUCSL": monthly([300.0 + i for i in range(20)]),
            "EFFR": daily([4.3] * 10),
            "PNFI": quarterly([20.0 + 0.2 * i for i in range(12)]),
        },
        fg=daily([17.0] * 30),
        errors={},
    )


def test_compute_metrics_all_live():
    m = compute_metrics(full_raw(), None, {})
    assert all(x.status == "live" for x in m.values())
    assert m["sox_drop"].extra["days"] == 50
    assert m["sox_drop"].extra["peak_date"]
    assert m["us10y"].value == 4.7
    assert m["us10y_streak"].value == 4
    assert m["gdp_spread"].value == pytest.approx(m["gdp_yoy"].value - m["us10y"].value)
    assert m["fg"].value == 17.0
    assert m["fg"].as_of == "2026-11-10"
    for key in ("effr", "wti", "usdjpy_1m", "capex_gdp", "cpi_yoy", "n225_drop", "ndx_drop"):
        assert key in m


def test_compute_metrics_fred_missing():
    raw = full_raw()
    raw.fred = {}
    m = compute_metrics(raw, None, {})
    for key in ("us10y", "us10y_streak", "gdp_yoy", "gdp_spread", "cpi_yoy", "capex_gdp", "effr"):
        assert m[key].status == "missing"
        assert m[key].value is None
        assert m[key].as_of is None
    assert m["ndx_drop"].status == "live"


def test_gdp_spread_missing_when_one_side_missing():
    raw = full_raw()
    del raw.fred["DGS10"]
    m = compute_metrics(raw, None, {})
    assert m["gdp_yoy"].status == "live"
    assert m["gdp_spread"].status == "missing"


def test_fg_none_is_missing():
    raw = full_raw()
    raw.fg = None
    assert compute_metrics(raw, None, {})["fg"].status == "missing"


def test_compute_metrics_asof_truncates():
    raw = full_raw()
    full = compute_metrics(raw, None, {})["sox_drop"]
    cut = compute_metrics(raw, date(2026, 5, 11), {})["sox_drop"]
    assert cut.value != full.value
    assert cut.as_of <= "2026-05-11"


def test_compute_metrics_backfill_has_no_manual_keys():
    result = compute_metrics(full_raw(), date(2026, 8, 1), None)
    assert "topix_per" not in result
    assert "sox_per" not in result


def test_manual_entries_copied():
    manual = {
        "topix_per": Metric("topix_per", "TOPIX PER", 15.0, "manual", "2026-11-05", "倍"),
        "sox_per": Metric("sox_per", "SOX PER", 20.0, "manual", "2026-11-05", "倍"),
    }
    result = compute_metrics(full_raw(), None, manual)
    assert result["topix_per"] is manual["topix_per"]
    assert result["sox_per"].value == 20.0


def prev_metric(key="fg", status="live", value=17.0, evals=0):
    return Metric(key, "x", value, status, "2026-11-08", "", evals)


def missing_metric(key="fg"):
    return Metric(key, "x", None, "missing", None)


def test_carry_forward_daily_within_limit():
    out = carry_forward({"fg": missing_metric()}, {"fg": prev_metric()}, LIMITS, METRIC_FREQ)
    assert out["fg"].status == "stale"
    assert out["fg"].value == 17.0
    assert out["fg"].stale_evals == 1
    assert out["fg"].as_of == "2026-11-08"


def test_carry_forward_increments_stale():
    prev = prev_metric(status="stale", evals=2)
    out = carry_forward({"fg": missing_metric()}, {"fg": prev}, LIMITS, METRIC_FREQ)
    assert out["fg"].status == "stale" and out["fg"].stale_evals == 3


def test_carry_forward_daily_exceeds_limit():
    prev = prev_metric(status="stale", evals=3)
    out = carry_forward({"fg": missing_metric()}, {"fg": prev}, LIMITS, METRIC_FREQ)
    assert out["fg"].status == "missing"
    assert out["fg"].value is None


def test_carry_forward_no_previous():
    out = carry_forward({"fg": missing_metric()}, None, LIMITS, METRIC_FREQ)
    assert out["fg"].status == "missing"


def test_carry_forward_leaves_live_untouched_and_skips_manual():
    cur = {
        "fg": Metric("fg", "x", 30.0, "live", "2026-11-10"),
        "topix_per": missing_metric("topix_per"),
    }
    prev = {
        "fg": prev_metric(),
        "topix_per": Metric("topix_per", "x", 15.0, "manual", "2026-11-01"),
    }
    out = carry_forward(cur, prev, LIMITS, METRIC_FREQ)
    assert out["fg"].value == 30.0 and out["fg"].status == "live"
    assert out["topix_per"].status == "missing"


def test_carry_forward_monthly_uses_monthly_limit():
    prev = Metric("cpi_yoy", "x", 3.1, "stale", "2026-09-01", "%", 20)
    out = carry_forward({"cpi_yoy": missing_metric("cpi_yoy")}, {"cpi_yoy": prev}, LIMITS, METRIC_FREQ)
    assert out["cpi_yoy"].status == "stale" and out["cpi_yoy"].stale_evals == 21


def test_carry_forward_does_not_mutate_input():
    cur = {"fg": missing_metric()}
    carry_forward(cur, {"fg": prev_metric()}, LIMITS, METRIC_FREQ)
    assert cur["fg"].status == "missing"
