"""Geometry helpers: haversine distance and noise-filtered path length."""

import math
from datetime import datetime

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def filter_and_measure(
    points: list[dict],
    max_accuracy_m: float = 50,
    max_speed_kmph: float = 150,
    min_segment_m: float = 20,
) -> tuple[float, list[dict]]:
    """Return (distance_m, accepted_points).

    points: dicts with latitude, longitude, accuracy, ping_time (datetime), is_mocked.
    Filtering:
      * drop mocked points and points with poor accuracy
      * drop jitter: movements shorter than min_segment_m (or shorter than the
        combined accuracy radius) are not counted and don't move the anchor
      * drop teleports: segments implying a speed above max_speed_kmph
    """
    pts = sorted(
        (p for p in points if p.get("latitude") is not None and p.get("longitude") is not None),
        key=lambda p: p["ping_time"],
    )
    accepted: list[dict] = []
    total = 0.0
    for p in pts:
        if p.get("is_mocked"):
            continue
        acc = float(p.get("accuracy") or 0)
        if max_accuracy_m and acc > max_accuracy_m:
            continue
        if not accepted:
            accepted.append(p)
            continue
        last = accepted[-1]
        d = haversine_m(last["latitude"], last["longitude"], p["latitude"], p["longitude"])
        noise = max(min_segment_m or 0, (acc + float(last.get("accuracy") or 0)) / 2)
        if d < noise:
            continue
        dt = _seconds(last["ping_time"], p["ping_time"])
        if dt > 0 and max_speed_kmph and (d / dt) * 3.6 > max_speed_kmph:
            continue
        total += d
        accepted.append(p)
    return total, accepted


def _seconds(a, b) -> float:
    if isinstance(a, datetime) and isinstance(b, datetime):
        return (b - a).total_seconds()
    return 0.0


def downsample(points: list[dict], limit: int = 1500) -> list[dict]:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    out = [points[int(i * step)] for i in range(limit)]
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out
