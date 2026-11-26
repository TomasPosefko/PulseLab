import csv
from math import isclose
from pathlib import Path
from statistics import stdev
from tempfile import TemporaryDirectory
import unittest

from modules.analysis import break_segment, metrics, new_analysis, process
from modules.heart_rate import MEASUREMENT_UUID, milliseconds, parse_measurement
from modules.recording import add_link, add_packet, export_csv, new_recording, stop_recording


def stamp(seconds):
    return seconds, f"2026-11-26T00:00:{seconds:09.6f}+00:00"


def measurement_bytes(*rr, flags=None):
    if flags is None:
        flags = 16 if rr else 0
    return bytes((flags, 60)) + b"".join(value.to_bytes(2, "little") for value in rr)


def test_optional_fields_and_multiple_intervals():
    result = parse_measurement(bytes.fromhex("1F 2C 01 34 12 00 04 00 02"))
    assert (result["flags"], result["bpm"], result["energy_kj"]) == (31, 300, 4660)
    assert result["contact_detected"] is True
    assert result["rr_ticks"] == [1024, 512]
    assert list(map(milliseconds, result["rr_ticks"])) == [1000, 500]
    assert parse_measurement(b"\x00\x3c")["contact_detected"] is None
    assert parse_measurement(b"\x04\x3c")["contact_detected"] is False


def test_malformed_fields_rejected():
    for payload in ("", "00", "01 3C", "08 3C FF", "10 3C", "10 3C 00", "00 3C FF"):
        try:
            parse_measurement(bytes.fromhex(payload))
        except ValueError:
            continue
        raise AssertionError(f"Parser accepted a malformed packet: {payload!r}")


def test_irregular_arrivals_with_catch_up_batch():
    analysis = new_analysis()
    process(analysis, measurement_bytes(1024), 0)
    for arrival in (3, 3.2, 3.4, 3.6):
        process(analysis, measurement_bytes(), arrival)
    result = process(analysis, measurement_bytes(1024, 1024, 1024, 1024), 4)
    assert result["notes"] == ["Batched R-R values"]
    assert isclose(result["arrival_delta_ms"], 400)
    assert result["coverage_delta_ms"] == 0
    assert metrics(analysis) == (0, 0)


def test_coverage_and_long_rr_are_separate_signals():
    analysis = new_analysis()
    for arrival in range(5):
        process(analysis, measurement_bytes(1024), arrival)
    long_rr = process(analysis, measurement_bytes(2048), 6)
    assert "possible missed detection" in long_rr["beats"][0]["quality"]
    assert long_rr["coverage_delta_ms"] == 0
    for arrival in range(11, 16):
        result = process(analysis, measurement_bytes(1024), arrival)
    assert any("Sustained" in note for note in result["notes"])
    break_segment(analysis)
    resumed = process(analysis, measurement_bytes(1024), 30)
    assert resumed["arrival_delta_ms"] is None
    assert resumed["coverage_delta_ms"] == 0


def test_metrics_keep_pairs_within_segments_and_exclude_flagged_beats():
    analysis = new_analysis()
    process(analysis, measurement_bytes(800, 900), 0)
    break_segment(analysis)
    process(analysis, measurement_bytes(700, 0, 1024), 10)
    rmssd, sdnn = metrics(analysis)
    assert isclose(rmssd, milliseconds(100))
    assert isclose(sdnn, stdev(map(milliseconds, (800, 900, 700, 1024))))


def test_export_preserves_packets_beats_events_and_wall_time():
    recording = new_recording(stamp(1))
    address = "AA:BB"
    add_packet(recording, stamp(0), address, MEASUREMENT_UUID, measurement_bytes(1024))
    add_packet(recording, stamp(2), address, MEASUREMENT_UUID, measurement_bytes(512, 1024))
    add_link(recording, stamp(3), address, "disconnected", "Strap")
    add_packet(recording, stamp(4), address, MEASUREMENT_UUID, b"\x10\x3c")
    stop_recording(recording, stamp(5))
    add_packet(recording, stamp(6), address, MEASUREMENT_UUID, measurement_bytes(1024))
    with TemporaryDirectory() as directory:
        path = Path(directory) / "session.csv"
        export_csv(recording, path)
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))

    assert [row["row_type"] for row in rows] == [
        "event", "packet", "rr", "rr", "event", "packet", "event"
    ]
    assert rows[1]["raw_hex"] == "10 3c 00 02 00 04"
    assert rows[1]["rr_count"] == "2"
    assert [row["rr_ms"] for row in rows[2:4]] == ["500.0", "1000.0"]
    assert rows[3]["packet_id"] == "1"
    assert rows[4]["event"] == "disconnected"
    assert "Malformed" in rows[5]["detail"]
    assert rows[-1]["elapsed_minus_rr_ms"] == "2500.0"


def load_tests(loader, tests, pattern):
    for name, function in globals().items():
        if name.startswith("test_"):
            tests.addTest(unittest.FunctionTestCase(function))
    return tests
