from pathlib import Path

import pytest

from dash.config import TickerConfig, load_rules
from dash.verdict import ticker_verdict

RULES = load_rules(Path(__file__).resolve().parent.parent / "config" / "rules.yaml")

NORMAL = TickerConfig("VTI", "VTI", "us", "n")
LEV = TickerConfig("SOXL", "SOXL", "semi", "n", leveraged=True)
KIOXIA = TickerConfig("285A.T", "キオクシア", "semi", "n", cautious_when_area_ratio_ge=35)


@pytest.mark.parametrize("ratio,expected", [
    (0, "買い増し"), (20, "保有"), (35, "保有"),
    (50, "利確 1/4"), (70, "利確 1/3"), (90, "利確 1/2"),
])
def test_verdict_table_normal(ratio, expected):
    assert ticker_verdict(NORMAL, ratio, 10.0, RULES) == (expected, [])


def test_verdict_table_leveraged_column():
    assert ticker_verdict(LEV, 35, 10.0, RULES)[0] == "利確 1/3"
    assert ticker_verdict(LEV, 90, 10.0, RULES)[0] == "全利確"


def test_verdict_deep_drop_bullish_shift():
    v, notes = ticker_verdict(NORMAL, 20, 32.0, RULES)
    assert v == "買い増し" and len(notes) == 1


def test_verdict_deep_drop_stops_at_left_edge():
    assert ticker_verdict(NORMAL, 0, 40.0, RULES) == ("買い増し", [])


def test_verdict_deep_drop_no_shift_when_cautious():
    assert ticker_verdict(NORMAL, 50, 32.0, RULES) == ("利確 1/4", [])


def test_verdict_kioxia_cautious_shift():
    v, notes = ticker_verdict(KIOXIA, 35, 10.0, RULES)
    assert v == "利確 1/4" and len(notes) == 1


def test_verdict_normal_never_full_exit():
    assert ticker_verdict(KIOXIA, 90, 10.0, RULES) == ("利確 1/2", [])


def test_verdict_no_data():
    assert ticker_verdict(NORMAL, 20, None, RULES) == ("データなし", [])
