"""Checks R-R values and calculates HRV."""

from collections import deque
from math import sqrt
from statistics import fmean, median, stdev

from .heart_rate import milliseconds, parse_measurement


def new_analysis():
    state = {"total_ticks": 0, "segment": 0, "hrv": deque(maxlen=120)}
    break_segment(state)
    return state


def _reset_coverage(state):
    state["anchor"] = None
    state["recent_deficits"] = deque(maxlen=5)


def break_segment(state):
    state["segment"] += 1
    state["previous_arrival"] = None
    _reset_coverage(state)
    state["baseline"] = deque(maxlen=9)


def metrics(state):
    values = []
    differences = []
    previous_value = None
    previous_segment = None
    for value, segment in state["hrv"]:
        if value is not None:
            values.append(value)
            if previous_value is not None and previous_segment == segment:
                differences.append((value - previous_value) ** 2)
        previous_value = value
        previous_segment = segment
    return (
        sqrt(fmean(differences)) if differences else None,
        stdev(values) if len(values) >= 2 else None,
    )


def process(state, payload, arrival):
    previous_arrival = state["previous_arrival"]
    delta = None if previous_arrival is None else (arrival - previous_arrival) * 1000
    state["previous_arrival"] = arrival
    try:
        measurement = parse_measurement(payload)
    except ValueError as error:
        state["segment"] += 1
        state["baseline"].clear()
        _reset_coverage(state)
        return {
            "measurement": None,
            "arrival_delta_ms": delta,
            "beats": [],
            "cumulative_ms": milliseconds(state["total_ticks"]),
            "coverage_delta_ms": None,
            "notes": [f"Malformed packet: {error}"],
        }

    notes = []
    beats = []
    if measurement["flags"] & 0xE0:
        notes.append("Reserved flag bits set")
    if measurement["contact_detected"] is False:
        notes.append("Poor sensor contact")
    if not measurement["rr_ticks"]:
        notes.append("No R-R values in packet")
    elif len(measurement["rr_ticks"]) > 1:
        notes.append("Batched R-R values")

    for ticks in measurement["rr_ticks"]:
        rr = milliseconds(ticks)
        expected = median(state["baseline"]) if len(state["baseline"]) >= 5 else None
        if measurement["contact_detected"] is False:
            quality = "poor contact"
        elif expected is not None and 1.75 <= rr / expected <= 2.25:
            quality = "long R-R / possible missed detection"
        elif not 250 <= rr <= 2500 or (
            expected is not None and not 0.65 <= rr / expected <= 1.50
        ):
            quality = "suspicious R-R"
        else:
            quality = ""
        if measurement["contact_detected"] is not False and 250 <= rr <= 2500:
            state["baseline"].append(rr)
        state["total_ticks"] += ticks
        beats.append({
            "ticks": ticks,
            "cumulative_ms": milliseconds(state["total_ticks"]),
            "segment": state["segment"],
            "quality": quality,
        })
        state["hrv"].append((None if quality else rr, state["segment"]))

    # Compare at packet boundaries. The first batch can predate the anchor.
    coverage = None
    if measurement["contact_detected"] is False:
        state["segment"] += 1
        state["baseline"].clear()
        _reset_coverage(state)
    elif beats and state["anchor"] is None:
        state["anchor"] = (arrival, state["total_ticks"])
    if state["anchor"] is not None:
        anchor_time, anchor_ticks = state["anchor"]
        coverage = (arrival - anchor_time) * 1000 - milliseconds(state["total_ticks"] - anchor_ticks)
        state["recent_deficits"].append(coverage)
        if len(state["recent_deficits"]) == 5 and min(state["recent_deficits"]) > 2000:
            notes.append("Sustained R-R coverage deficit / possible unreported time")
    return {
        "measurement": measurement,
        "arrival_delta_ms": delta,
        "beats": beats,
        "cumulative_ms": milliseconds(state["total_ticks"]),
        "coverage_delta_ms": coverage,
        "notes": notes,
    }
