from datetime import date
from pathlib import Path

import pytest
import yaml

from dash.config import load_manual, load_rules, load_tickers

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
OVERDUE = load_rules(CONFIG / "rules.yaml")["manual_overdue_days"]


def test_load_tickers_has_seven_with_areas():
    tickers = load_tickers(CONFIG / "tickers.yaml")
    assert len(tickers) == 7
    by = {t.symbol: t for t in tickers}
    assert by["SOXL"].leveraged is True
    assert by["285A.T"].cautious_when_area_ratio_ge == 35
    areas = [t.area for t in tickers]
    assert areas.count("us") == 1
    assert areas.count("jp") == 1
    assert areas.count("semi") == 5


def test_load_rules_missing_key_raises(tmp_path):
    rules = yaml.safe_load((CONFIG / "rules.yaml").read_text(encoding="utf-8"))
    del rules["bands"]
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.safe_dump(rules, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError):
        load_rules(p)


def test_load_rules_real_file_ok():
    rules = load_rules(CONFIG / "rules.yaml")
    assert set(rules["verdict_table"]) == {0, 10, 20, 35, 50, 70, 90}


def _write(tmp_path, text):
    p = tmp_path / "manual.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_manual_ok(tmp_path):
    p = _write(
        tmp_path,
        "topix_per: {value: 13.7, updated: 2026-11-05}\n"
        "sox_per: {value: 14.2, updated: 2026-11-05}\n",
    )
    m = load_manual(p, today=date(2026, 11, 20), overdue_days=OVERDUE)
    t = m["topix_per"]
    assert t.status == "manual"
    assert t.value == 13.7
    assert t.as_of == "2026-11-05"
    assert t.extra["days_since_update"] == 15
    assert t.extra["overdue"] is True


def test_load_manual_broken_entry_is_missing(tmp_path):
    p = _write(
        tmp_path,
        "topix_per: {value: 13.7, updated: 2026-11-12}\n"
        "sox_per: {value: null}\n",
    )
    m = load_manual(p, today=date(2026, 11, 12), overdue_days=OVERDUE)
    assert m["sox_per"].status == "missing"
    assert m["sox_per"].value is None
    assert m["topix_per"].status == "manual"
    assert m["topix_per"].extra["overdue"] is False


def test_load_manual_broken_yaml_is_all_missing(tmp_path):
    p = _write(tmp_path, ":::")
    m = load_manual(p, today=date(2026, 11, 12), overdue_days=OVERDUE)
    assert set(m) == {"topix_per", "sox_per"}
    assert all(x.status == "missing" for x in m.values())


def test_load_manual_absent_file_is_all_missing(tmp_path):
    m = load_manual(tmp_path / "nope.yaml", today=date(2026, 11, 12), overdue_days=OVERDUE)
    assert all(x.status == "missing" for x in m.values())
