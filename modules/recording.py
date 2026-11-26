"""Collects a recording and saves it to CSV."""

import csv
from pathlib import Path
from tempfile import NamedTemporaryFile

from .analysis import break_segment, metrics, new_analysis, process
from .heart_rate import milliseconds

FIELDS = (
    "row_type", "utc", "monotonic_s", "elapsed_ms", "address", "characteristic_uuid",
    "event", "packet_id", "raw_hex", "arrival_delta_ms", "flags_hex", "bpm",
    "contact_detected", "energy_kj", "rr_count", "rr_index", "rr_ticks", "rr_ms",
    "cumulative_rr_ms", "elapsed_minus_rr_ms", "segment_coverage_delta_ms",
    "segment", "rmssd_ms", "sdnn_ms", "detail",
)


def new_recording(start):
    recording = {
        "start": start,
        "stop": None,
        "analysis": new_analysis(),
        "rows": [],
        "packet_id": 0,
    }
    _append(recording, "event", start, event="recording_started")
    return recording


def _append(recording, row_type, stamp, **fields):
    row = {
        "row_type": row_type,
        "utc": stamp[1],
        "monotonic_s": stamp[0],
        "elapsed_ms": (stamp[0] - recording["start"][0]) * 1000,
    }
    row.update(fields)
    recording["rows"].append(row)


def elapsed(recording, now):
    return ((recording["stop"] or now)[0] - recording["start"][0]) * 1000


def stop_recording(recording, stamp):
    recording["stop"] = stamp
    total = milliseconds(recording["analysis"]["total_ticks"])
    _append(
        recording, "event", stamp, event="recording_stopped",
        cumulative_rr_ms=total, elapsed_minus_rr_ms=elapsed(recording, stamp) - total,
    )


def add_link(recording, stamp, address, kind, detail):
    if stamp[0] < recording["start"][0] or recording["stop"] is not None:
        return
    if kind in {"connected", "disconnected"}:
        break_segment(recording["analysis"])
    _append(recording, "event", stamp, address=address, event=kind, detail=detail)


def add_packet(recording, stamp, address, characteristic, payload):
    if stamp[0] < recording["start"][0] or recording["stop"] is not None:
        return

    recording["packet_id"] += 1
    packet = process(recording["analysis"], payload, stamp[0])
    measurement = packet["measurement"]
    rmssd, sdnn = metrics(recording["analysis"])
    flags = f"0x{payload[0]:02X}" if payload else None
    common = dict(address=address, characteristic_uuid=characteristic,
                  packet_id=recording["packet_id"])
    _append(
        recording, "packet", stamp, **common, raw_hex=payload.hex(" "),
        arrival_delta_ms=packet["arrival_delta_ms"], flags_hex=flags,
        bpm=measurement["bpm"] if measurement else None,
        contact_detected=measurement["contact_detected"] if measurement else None,
        energy_kj=measurement["energy_kj"] if measurement else None,
        rr_count=len(packet["beats"]) if measurement else None,
        cumulative_rr_ms=packet["cumulative_ms"],
        elapsed_minus_rr_ms=elapsed(recording, stamp) - packet["cumulative_ms"],
        segment_coverage_delta_ms=packet["coverage_delta_ms"], rmssd_ms=rmssd, sdnn_ms=sdnn,
        detail="; ".join(packet["notes"]),
    )
    for index, beat in enumerate(packet["beats"], start=1):
        _append(
            recording, "rr", stamp, **common, rr_index=index, rr_ticks=beat["ticks"],
            rr_ms=milliseconds(beat["ticks"]), cumulative_rr_ms=beat["cumulative_ms"],
            segment=beat["segment"], detail=beat["quality"],
        )


def export_csv(recording, path):
    destination = Path(path)
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=destination.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(recording["rows"])
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
