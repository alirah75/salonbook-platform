from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.modules.scheduling.intervals import (
    Interval,
    contains,
    intersect,
    local_instant,
    merge,
    package,
    subtract,
)
from app.modules.scheduling.schemas import (
    AvailabilityQuery,
    BlockCreate,
    CalendarCreate,
    OverrideWrite,
    WeeklyWrite,
)


def interval(start: int, end: int) -> Interval:
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    return Interval(origin + timedelta(minutes=start), origin + timedelta(minutes=end))


def test_architecture_example_and_half_open_boundaries() -> None:
    free = subtract([interval(540, 1020)], [interval(720, 780), interval(600, 690)])
    assert free == [interval(540, 600), interval(690, 720), interval(780, 1020)]
    assert contains(free, interval(915, 1020))
    assert not contains(free, interval(930, 1035))
    assert contains(free, interval(570, 600))
    assert not contains(free, interval(599, 601))


def test_union_intersection_overlapping_breaks_and_multiple_openings() -> None:
    assert merge([interval(5, 10), interval(0, 5), interval(2, 7)]) == [interval(0, 10)]
    assert intersect([interval(0, 10), interval(20, 30)], [interval(5, 25)]) == [
        interval(5, 10),
        interval(20, 25),
    ]
    assert subtract([interval(0, 20)], [interval(3, 8), interval(5, 10), interval(20, 30)]) == [
        interval(0, 3),
        interval(10, 20),
    ]
    assert subtract([interval(0, 20)], [interval(-1, 21)]) == []
    assert intersect([interval(0, 10)], [interval(10, 20)]) == []


def test_interval_arithmetic_matches_discrete_set_oracle() -> None:
    # Independent exhaustive small-domain oracle catches adjacency and containment errors.
    for a in range(5):
        for b in range(a + 1, 7):
            for c in range(5):
                for d in range(c + 1, 7):
                    left, right = [interval(a, b)], [interval(c, d)]
                    for point in range(7):
                        wanted = interval(point, point + 1)
                        assert contains(subtract(left, right), wanted) == (
                            point in set(range(a, b)) - set(range(c, d))
                        )
                        assert contains(intersect(left, right), wanted) == (
                            point in set(range(a, b)) & set(range(c, d))
                        )


def test_ordered_package_shares_internal_buffers_once() -> None:
    bundle = package([(30, 5, 10), (45, 15, 20), (20, 5, 10)])
    assert (bundle.duration, bundle.before, bundle.after, bundle.occupied_minutes) == (
        130,
        5,
        10,
        145,
    )
    assert package([(30, 5, 10)]).occupied_minutes == 45
    with pytest.raises(ValueError):
        package([])


def test_timezone_gap_rejected_fold_earlier_and_tehran_current_offset() -> None:
    zone = ZoneInfo("America/New_York")
    with pytest.raises(ValueError):
        local_instant(date(2027, 3, 14), 150, zone)
    assert local_instant(date(2027, 11, 7), 90, zone) == datetime(2027, 11, 7, 5, 30, tzinfo=UTC)
    assert local_instant(date(2027, 1, 1), 540, ZoneInfo("Asia/Tehran")) == datetime(
        2027, 1, 1, 5, 30, tzinfo=UTC
    )
    assert local_instant(date(2027, 1, 1), 1440, ZoneInfo("Asia/Tehran")) == datetime(
        2027, 1, 1, 20, 30, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "data",
    [
        {"scope": "SALON", "line_id": "00000000-0000-0000-0000-000000000001"},
        {"scope": "EMPLOYEE"},
        {"scope": "EMPLOYEE_LINE", "employee_id": "00000000-0000-0000-0000-000000000001"},
    ],
)
def test_calendar_target_validation(data: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        CalendarCreate.model_validate(data)


def test_schedule_input_bounds_and_timezone_required() -> None:
    with pytest.raises(ValidationError):
        WeeklyWrite.model_validate(
            {
                "periods": [
                    {
                        "weekday": 0,
                        "start_minute": 1200,
                        "end_minute": 100,
                        "valid_from": "2027-01-01",
                    }
                ]
            }
        )
    with pytest.raises(ValidationError):
        OverrideWrite.model_validate(
            {"mode": "CLOSED", "periods": [{"start_minute": 0, "end_minute": 1440}]}
        )
    with pytest.raises(ValidationError):
        OverrideWrite.model_validate({"mode": "REPLACE"})
    with pytest.raises(ValidationError):
        BlockCreate.model_validate(
            {
                "kind": "LEAVE",
                "reason": "Trip",
                "starts_at": "2027-01-01T09:00:00",
                "ends_at": "2027-01-01T10:00:00",
            }
        )
    with pytest.raises(ValidationError):
        AvailabilityQuery.model_validate(
            {
                "line_id": "00000000-0000-0000-0000-000000000001",
                "service_ids": ["00000000-0000-0000-0000-000000000002"],
                "date_from": "2027-01-01",
                "date_until": "2027-01-10",
            }
        )
