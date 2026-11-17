"""Synthetic event streams; amounts are integer cents, times integer ticks."""
from dataclasses import dataclass

Event = tuple[int, int, int]
BASE: tuple[Event, ...] = ((1, 1000, 10), (2, 2000, 20))

@dataclass(frozen=True)
class Scenario:
    name: str
    batches: tuple[tuple[Event, ...], ...]
    expected: str
    watermark: bool = True

SCENARIOS = (
    Scenario("in_order", (((3, 3000, 30),),), "clean"),
    Scenario("late_arrival", (((3, 3000, 15),),), "silent_corruption"),
    Scenario("timestamp_collision", (((3, 3000, 20),),), "silent_corruption"),
    Scenario("historical_correction", (((1, 1100, 15),),), "silent_corruption"),
    Scenario("newer_correction", (((1, 1100, 30),),), "clean"),
    Scenario("duplicate_replay", (((3, 3000, 30),), ((3, 3000, 30),)), "clean"),
    Scenario("out_of_order_batches", (((4, 4000, 40),), ((3, 3000, 30),)), "silent_corruption"),
    Scenario("negative_amount_control", (((3, -100, 30),),), "test_detected"),
    Scenario("late_arrival_repaired", (((3, 3000, 15),),), "clean", False),
    Scenario("historical_correction_repaired", (((1, 1100, 15),),), "clean", False),
)

def oracle(events: list[Event]) -> list[Event]:
    """Independent latest-version business rule; later arrival wins equal ticks."""
    latest: dict[int, Event] = {}
    for event in events:
        key, _, ts = event
        if key not in latest or ts >= latest[key][2]:
            latest[key] = event
    return [latest[key] for key in sorted(latest)]

def diff(expected: list[Event], observed: list[Event]) -> dict:
    """Multiset difference: duplicated rows must not disappear in comparison."""
    from collections import Counter
    a, b = Counter(expected), Counter(observed)
    return {"missing": sorted((a-b).elements()), "unexpected": sorted((b-a).elements())}
