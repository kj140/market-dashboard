from __future__ import annotations

from dash.models import AreaResult, Contribution, Metric


def _matches(value: float, band: dict) -> bool:
    if "lt" in band:
        return value < band["lt"]
    if "le" in band:
        return value <= band["le"]
    return True


def band_points(value: float, bands: list[dict]) -> int:
    for band in bands:
        if _matches(value, band):
            return band["points"]
    raise ValueError(f"no band matched value {value}")


def points_to_ratio(points: int, steps: list[dict]) -> int:
    for step in steps:
        if _matches(points, step):
            return step["ratio"]
    raise ValueError(f"no ratio step matched points {points}")


def sox_combo_points(sox_drop: Metric, fg: Metric | None, cfg: dict) -> int | None:
    if sox_drop.status == "missing" or sox_drop.value is None:
        return None
    drop = sox_drop.value
    days = sox_drop.extra.get("days")
    if drop >= cfg["deep_drop"]:
        if days is not None and cfg["days_min"] <= days <= cfg["days_max"]:
            return cfg["deep_in_window"]
        return cfg["deep_outside"]
    if (
        drop < cfg["high_drop_lt"]
        and fg is not None
        and fg.status != "missing"
        and fg.value is not None
        and fg.value >= cfg["high_fg_ge"]
    ):
        return cfg["high_points"]
    return 0


def score_area(
    area: str,
    metrics: dict[str, Metric],
    rules: dict,
    apply_hold: bool = True,
    exclude_manual: bool = False,
) -> tuple[int, list[Contribution], list[str], bool]:
    keys = list(dict.fromkeys(rules["areas"][area] + rules["areas"]["common"]))
    contributions: list[Contribution] = []
    missing: list[str] = []
    total = 0
    for key in keys:
        if key == "sox_combo":
            sox = metrics.get("sox_drop")
            if sox is None:
                continue
            pts = sox_combo_points(sox, metrics.get("fg"), rules["sox_combo"])
        else:
            metric = metrics.get(key)
            if metric is None:
                continue
            if exclude_manual and metric.status == "manual":
                continue
            if metric.status == "missing" or metric.value is None:
                pts = None
            else:
                pts = band_points(metric.value, rules["bands"][key])
        contributions.append(Contribution(key, pts))
        if pts is None:
            missing.append(key)
        else:
            total += pts
    on_hold = apply_hold and len(missing) > len(contributions) * rules["hold_missing_fraction"]
    return total, contributions, missing, on_hold


def apply_hysteresis(
    raw_ratio: int, prev_ratio: int | None, prev_pending: int | None
) -> tuple[int, int | None]:
    if prev_ratio is None or raw_ratio >= prev_ratio:
        return raw_ratio, None
    if prev_pending is not None:
        return max(raw_ratio, prev_pending), None
    return prev_ratio, raw_ratio


def evaluate_area(
    area: str,
    metrics: dict[str, Metric],
    rules: dict,
    prev: dict | None,
    apply_hold: bool = True,
) -> AreaResult:
    steps = rules["ratio_steps"]
    points, contributions, missing, on_hold = score_area(area, metrics, rules, apply_hold)
    excl_points = score_area(area, metrics, rules, apply_hold=False, exclude_manual=True)[0]
    raw_ratio = points_to_ratio(points, steps)
    prev_ratio = prev["ratio"] if prev else None
    prev_pending = prev.get("pending_down") if prev else None
    if on_hold:
        ratio = prev_ratio if prev_ratio is not None else points_to_ratio(0, steps)
        pending = prev_pending
    else:
        ratio, pending = apply_hysteresis(raw_ratio, prev_ratio, prev_pending)
    return AreaResult(
        area=area,
        points=points,
        ratio=ratio,
        raw_ratio=raw_ratio,
        ratio_excl_manual=points_to_ratio(excl_points, steps),
        on_hold=on_hold,
        pending_down=pending,
        contributions=contributions,
        missing=missing,
        prev_ratio=prev_ratio,
    )
