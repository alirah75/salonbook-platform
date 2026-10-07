"""Pure half-open UTC interval arithmetic and deterministic local-time conversion."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, order=True)
class Interval:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None or self.end <= self.start:
            raise ValueError("Expected an increasing aware interval.")


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    result: list[Interval] = []
    for item in sorted(intervals):
        if result and item.start <= result[-1].end:
            result[-1] = Interval(result[-1].start, max(result[-1].end, item.end))
        else:
            result.append(item)
    return result


def intersect(left: Sequence[Interval], right: Sequence[Interval]) -> list[Interval]:
    a, b = merge(left), merge(right)
    result: list[Interval] = []
    i = j = 0
    while i < len(a) and j < len(b):
        start, end = max(a[i].start, b[j].start), min(a[i].end, b[j].end)
        if start < end:
            result.append(Interval(start, end))
        if a[i].end < b[j].end:
            i += 1
        else:
            j += 1
    return result


def subtract(openings: Sequence[Interval], blocked: Sequence[Interval]) -> list[Interval]:
    result: list[Interval] = []
    cuts = merge(blocked)
    for item in merge(openings):
        cursor = item.start
        for cut in cuts:
            if cut.end <= cursor:
                continue
            if cut.start >= item.end:
                break
            if cursor < cut.start:
                result.append(Interval(cursor, cut.start))
            cursor = max(cursor, cut.end)
            if cursor >= item.end:
                break
        if cursor < item.end:
            result.append(Interval(cursor, item.end))
    return result


def contains(openings: Sequence[Interval], wanted: Interval) -> bool:
    return any(item.start <= wanted.start and item.end >= wanted.end for item in openings)


def local_instant(day: date, minute: int, zone: ZoneInfo) -> datetime:
    """Reject gaps; for a repeated wall-clock minute choose the earlier UTC instant."""
    wall = datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute)
    candidates = []
    for fold in (0, 1):
        candidate = wall.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None) == wall:
            candidates.append(candidate)
    if not candidates:
        raise ValueError("Nonexistent local time.")
    return min(candidates)


def local_interval(day: date, start: int, end: int, zone: ZoneInfo) -> Interval:
    return Interval(local_instant(day, start, zone), local_instant(day, end, zone))


@dataclass(frozen=True)
class Package:
    duration: int
    before: int
    after: int

    @property
    def occupied_minutes(self) -> int:
        return self.before + self.duration + self.after


def package(parts: Sequence[tuple[int, int, int]]) -> Package:
    """Ordered (service duration, before, after); share adjacent preparation buffers."""
    if not parts:
        raise ValueError("Select at least one service.")
    internal = sum(max(left[2], right[1]) for left, right in zip(parts, parts[1:], strict=False))
    return Package(sum(p[0] for p in parts) + internal, parts[0][1], parts[-1][2])
