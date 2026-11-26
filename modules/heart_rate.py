"""Reads Bluetooth heart rate packets (0x2A37)."""

SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


def milliseconds(ticks: int) -> float:
    return ticks * 1000 / 1024


def parse_measurement(payload):
    if not payload:
        raise ValueError("Empty measurement")
    flags = payload[0]
    bpm_end = 3 if flags & 1 else 2
    fields_end = bpm_end + (2 if flags & 8 else 0)
    if len(payload) < fields_end:
        raise ValueError("Truncated BPM or energy field")
    bpm = int.from_bytes(payload[1:bpm_end], "little")
    energy = int.from_bytes(payload[bpm_end:fields_end], "little") if flags & 8 else None
    remainder = payload[fields_end:]
    if flags & 16:
        if not remainder or len(remainder) % 2:
            raise ValueError("Invalid R-R field length")
    elif remainder:
        raise ValueError("Unexpected bytes after measurement fields")
    rr_ticks = []
    for offset in range(0, len(remainder), 2):
        ticks = int.from_bytes(remainder[offset:offset + 2], "little")
        rr_ticks.append(ticks)

    contact = None
    if flags & 4:
        contact = bool(flags & 2)

    return {
        "flags": flags,
        "bpm": bpm,
        "energy_kj": energy,
        "contact_detected": contact,
        "rr_ticks": rr_ticks,
    }
