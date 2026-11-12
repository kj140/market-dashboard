"""Per-ticker verdicts from the area cash ratio (spec 7.4)."""
from __future__ import annotations

from .config import TickerConfig

NO_DATA = "データなし"


def ticker_verdict(
    t: TickerConfig, area_ratio: int, drop_pct: float | None, rules: dict
) -> tuple[str, list[str]]:
    """Return (verdict, descriptions of the adjustments that actually changed it)."""
    if drop_pct is None:
        return NO_DATA, []

    levels: list[str] = list(rules["verdict_levels"])
    row = rules["verdict_table"][area_ratio]
    idx = levels.index(row["leveraged"] if t.leveraged else row["normal"])
    # Normal tickers stop one step short of the last level (full take-profit).
    max_idx = len(levels) - 1 if t.leveraged else len(levels) - 2

    notes: list[str] = []
    adj = rules["adjust"]
    if drop_pct >= adj["deep_drop_pct"] and area_ratio <= adj["deep_drop_max_area_ratio"]:
        if idx > 0:
            idx -= 1
            notes.append(
                f"高値から{adj['deep_drop_pct']}%以上下落しており1段階強気寄りに補正"
            )
    cautious = t.cautious_when_area_ratio_ge
    if cautious is not None and area_ratio >= cautious:
        if idx < max_idx:
            idx += 1
            notes.append(f"この銘柄は比率{cautious}%以上で1段階警戒寄りに補正")
    return levels[idx], notes
