from pathlib import Path

import pytest

from dash.config import load_rules
from dash.models import Metric
from dash.scoring import (
    apply_hysteresis,
    band_points,
    evaluate_area,
    points_to_ratio,
    score_area,
    sox_combo_points,
)

RULES = load_rules(Path(__file__).resolve().parent.parent / "config" / "rules.yaml")


def m(key, value, status="live", **extra):
    return Metric(key, key, value, status, "2026-11-12", extra=extra)


def missing(key):
    return Metric(key, key, None, "missing", None)


def sox(drop, days):
    return m("sox_drop", drop, days=days)


@pytest.mark.parametrize("v,p", [(9, -3), (10, -2), (17, -1), (20, -1), (21, 0),
                                 (69, 0), (70, 2), (80, 2), (81, 3)])
def test_fg_bands(v, p):
    assert band_points(v, RULES["bands"]["fg"]) == p


@pytest.mark.parametrize("v,p", [(2.9, 0), (3.0, -1), (3.4, -1), (3.5, 1)])
def test_cpi_bands(v, p):
    assert band_points(v, RULES["bands"]["cpi_yoy"]) == p


@pytest.mark.parametrize("v,p", [(0, 0), (1, 1), (30, 1), (31, 0), (89, 0), (90, -1)])
def test_us10y_streak_bands(v, p):
    assert band_points(v, RULES["bands"]["us10y_streak"]) == p


def test_sox_combo():
    cfg = RULES["sox_combo"]
    assert sox_combo_points(sox(31.7, 99), None, cfg) == -3
    assert sox_combo_points(sox(31.7, 30), None, cfg) == -4
    assert sox_combo_points(sox(27.9, 99), None, cfg) == 0
    assert sox_combo_points(sox(20, 10), None, cfg) == 0
    assert sox_combo_points(sox(3, 5), m("fg", 75), cfg) == 2
    assert sox_combo_points(sox(3, 5), missing("fg"), cfg) == 0
    assert sox_combo_points(sox(3, 5), None, cfg) == 0
    assert sox_combo_points(missing("sox_drop"), m("fg", 75), cfg) is None


@pytest.mark.parametrize("p,r", [(-7, 0), (-6, 0), (-5, 10), (-3, 10), (-2, 20), (2, 20),
                                 (3, 35), (4, 50), (7, 70), (8, 90)])
def test_points_to_ratio(p, r):
    assert points_to_ratio(p, RULES["ratio_steps"]) == r


@pytest.mark.parametrize("key,v,p", [
    ("sox_gap", -15, -2), ("sox_gap", -5, -1), ("sox_gap", 29.9, 0), ("sox_gap", 30, 2),
    ("sox_gap", 45, 4), ("sox_gap", 60, 5), ("sox_gap", 74.9, 5),
    ("ndx_gap", -5, -1), ("ndx_gap", 9.9, 0), ("ndx_gap", 10, 2), ("ndx_gap", 15, 3), ("ndx_gap", 18, 4),
    ("n225_gap", -5, -1), ("n225_gap", 19.9, 0), ("n225_gap", 20, 2), ("n225_gap", 28, 3), ("n225_gap", 33, 4),
])
def test_ma_gap_bands(key, v, p):
    assert band_points(v, RULES["bands"][key]) == p


def test_ma_gap_scored_in_each_area():
    assert "ndx_gap" in RULES["areas"]["us"]
    assert "n225_gap" in RULES["areas"]["jp"]
    assert "sox_gap" in RULES["areas"]["semi"]


def test_hysteresis_up_immediate():
    assert apply_hysteresis(50, 35, None) == (50, None)
    assert apply_hysteresis(50, None, None) == (50, None)


def test_hysteresis_down_needs_two():
    assert apply_hysteresis(20, 50, None) == (50, 20)
    assert apply_hysteresis(35, 50, 20) == (35, None)


def test_hysteresis_down_interrupted():
    assert apply_hysteresis(20, 50, None) == (50, 20)
    assert apply_hysteresis(50, 50, 20) == (50, None)


def semi_metrics(n_missing):
    keys = ["sox_drop", "sox_per", "fg", "capex_gdp", "gdp_spread", "cpi_yoy", "wti"]
    values = {"sox_drop": 5, "sox_per": 20, "fg": 50, "capex_gdp": 10,
              "gdp_spread": 1, "cpi_yoy": 2, "wti": 70}
    out = {}
    for i, k in enumerate(keys):
        if i < n_missing:
            out[k] = missing(k)
        else:
            out[k] = m(k, values[k], **({"days": 3} if k == "sox_drop" else {}))
    return out


def test_hold_semi_four_missing():
    assert score_area("semi", semi_metrics(4), RULES)[3] is True
    assert score_area("semi", semi_metrics(3), RULES)[3] is False
    assert score_area("semi", semi_metrics(4), RULES, apply_hold=False)[3] is False


def test_hold_keeps_previous_ratio():
    r = evaluate_area("semi", semi_metrics(4), RULES, {"ratio": 35, "pending_down": 10})
    assert r.on_hold and r.ratio == 35 and r.pending_down is None and r.prev_ratio == 35
    r = evaluate_area("semi", semi_metrics(4), RULES, None)
    assert r.on_hold and r.ratio == 20 and r.prev_ratio is None


def test_backfill_absent_manual_not_counted():
    ms = {"n225_drop": missing("n225_drop"), "usdjpy_1m": missing("usdjpy_1m"),
          "gdp_spread": m("gdp_spread", 1), "cpi_yoy": m("cpi_yoy", 2), "wti": m("wti", 70)}
    points, contribs, miss, hold = score_area("jp", ms, RULES)
    assert len(miss) == 2 and hold is False
    assert [c.key for c in contribs] == ["n225_drop", "usdjpy_1m", "gdp_spread", "cpi_yoy", "wti"]


def test_ratio_excl_manual():
    ms = semi_metrics(0)
    ms["capex_gdp"] = m("capex_gdp", 18)  # +1
    ms["gdp_spread"] = m("gdp_spread", 0.3)  # +1
    ms["wti"] = m("wti", 105)  # +1
    ms["sox_per"] = m("sox_per", 14, status="manual")  # -2
    r = evaluate_area("semi", ms, RULES, None)
    assert r.points == 1
    assert r.raw_ratio == 20
    assert r.ratio_excl_manual == 35
    assert r.raw_ratio != r.ratio_excl_manual


def test_hold_day_resets_pending_down():
    good = semi_metrics(0)
    good["fg"] = m("fg", 85)  # +3 each for fg band -> push ratio up
    r1 = evaluate_area("semi", good, RULES, None)
    assert r1.ratio > 20
    bad = semi_metrics(0)  # 0 points -> raw 20, lower than r1.ratio
    r2 = evaluate_area("semi", bad, RULES, {"ratio": r1.ratio, "pending_down": r1.pending_down})
    assert r2.ratio == r1.ratio and r2.pending_down == 20
    r3 = evaluate_area("semi", semi_metrics(4), RULES, {"ratio": r2.ratio, "pending_down": r2.pending_down})
    assert r3.on_hold and r3.ratio == r1.ratio and r3.pending_down is None
    r4 = evaluate_area("semi", bad, RULES, {"ratio": r3.ratio, "pending_down": r3.pending_down})
    assert r4.ratio == r1.ratio and r4.pending_down == 20


def test_hysteresis_second_down_day_below_pending_uses_pending():
    assert apply_hysteresis(10, 50, 20) == (20, None)
