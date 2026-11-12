from dash.config import TickerConfig
from dash.models import AreaResult, Contribution, Metric
from dash.reasons import area_reason, metric_phrase, ticker_reason


def metric(key, value, status="live", as_of="2026-11-12", **extra):
    return Metric(key, key, value, status, as_of, extra=extra)


def area(contribs, on_hold=False):
    return AreaResult("semi", 0, 20, 20, 20, on_hold, None,
                      [Contribution(k, p) for k, p in contribs], [])


METRICS = {
    "fg": metric("fg", 18),
    "sox_drop": metric("sox_drop", 31.7, days=99),
    "capex_gdp": metric("capex_gdp", 19.0),
    "cpi_yoy": metric("cpi_yoy", 3.2),
    "sox_per": metric("sox_per", 15.5, "manual", "2026-11-05", days_since_update=7, overdue=False),
    "gdp_spread": metric("gdp_spread", 1.15),
}
CONTRIBS = [("fg", -1), ("sox_combo", -3), ("capex_gdp", 0), ("cpi_yoy", 1), ("sox_per", -2)]


def test_metric_phrase_basic():
    assert metric_phrase(METRICS["sox_drop"]) == "SOX 高値比-31.7%（日柄99日）"
    assert metric_phrase(METRICS["gdp_spread"]) == "名目GDP−10年債 +1.15%"


def test_metric_phrase_stale_and_manual():
    assert metric_phrase(metric("fg", 18, "stale", "2026-11-08")).endswith("（前回値 11/08）")
    assert metric_phrase(METRICS["sox_per"]).endswith("（手入力 11/05）")
    od = metric("sox_per", 15.5, "manual", "2026-11-05", overdue=True)
    assert metric_phrase(od).endswith("（手入力 11/05・要更新）")


def test_area_reason_top3_by_abs_points():
    r = area_reason(area(CONTRIBS), METRICS)
    parts = r.split("／")
    assert len(parts) == 3
    assert parts[0].startswith("SOX 高値比")
    assert parts[1].startswith("SOX 予想PER")
    assert parts[2].startswith("Fear & Greed")  # tie with cpi: contributions order


def test_area_reason_no_signal_and_hold_prefix():
    assert area_reason(area([("fg", 0), ("wti", None)]), METRICS) == "目立ったシグナルなし"
    assert area_reason(area(CONTRIBS, on_hold=True), METRICS).startswith("判定保留（データ不足）：SOX")


def test_ticker_reason():
    t = TickerConfig("NVDA", "NVDA", "semi", "AI向けGPUの中心銘柄")
    r = ticker_reason(t, 22.0, area(CONTRIBS), METRICS, ["補正A"])
    assert r == ("高値から-22.0%。SOX 高値比-31.7%（日柄99日）／SOX 予想PER 15.5倍（手入力 11/05）。"
                 "AI向けGPUの中心銘柄。補正A。")
    assert ticker_reason(t, None, area([]), METRICS, []).startswith("高値からの下落率はデータなし。")
