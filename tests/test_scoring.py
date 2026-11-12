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
    assert sox_combo_points(sox(31.7, 99), None, cfg) == -1
    assert sox_combo_points(sox(31.7, 30), None, cfg) == -3
    assert sox_combo_points(sox(20, 10), None, cfg) == 0
    assert sox_combo_points(sox(3, 5), m("fg", 75), cfg) == 2
    assert sox_combo_points(sox(3, 5), missing("fg"), cfg) == 0
    assert sox_combo_points(sox(3, 5), None, cfg) == 0
    assert sox_combo_points(missing("sox_drop"), m("fg", 75), cfg) is None


@pytest.mark.parametrize("p,r", [(-7, 0), (-6, 0), (-5, 10), (-3, 10), (-2, 20), (1, 20),
                                 (2, 35), (4, 50), (7, 70), (8, 90)])
def test_points_to_ratio(p, r):
    assert points_to_ratio(p, RULES["ratio_steps"]) == r


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
    assert r.on_hold and r.ratio == 35 and r.pending_down == 10 and r.prev_ratio == 35
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
    ms["sox_per"] = m("sox_per", 14, status="manual")  # -2
    r = evaluate_area("semi", ms, RULES, None)
    pts_excl = r.points + 2
    assert r.points == score_area("semi", ms, RULES)[0]
    assert r.ratio_excl_manual == points_to_ratio(pts_excl, RULES["ratio_steps"])
    assert r.raw_ratio == points_to_ratio(r.points, RULES["ratio_steps"])
