"""Find a strap and read notifications on a background thread."""

from datetime import UTC, datetime
from queue import Empty, Queue
from time import monotonic, sleep

import simplepyble

from .heart_rate import MEASUREMENT_UUID, SERVICE_UUID


def timestamp():
    return monotonic(), datetime.now(UTC).isoformat(timespec="microseconds")


def run_monitor(address, messages, should_stop):
    target = {"address": address.upper() if address else None}
    while not should_stop():
        try:
            scan(target, messages, should_stop)
        except RuntimeError as error:
            messages.put(("status", f"Bluetooth error: {error}"))
        # Give the adapter a moment before scanning again.
        for _ in range(4):
            if should_stop():
                return
            sleep(0.25)


def scan(target, messages, should_stop):
    adapters = simplepyble.Adapter.get_adapters()
    if not adapters:
        messages.put(("status", "No Bluetooth adapter found"))
        return

    adapter = adapters[0]
    scan_name = target["address"] or "BLE heart rate monitors"
    messages.put(("status", f"Scanning for {scan_name}…"))
    adapter.scan_for(4000)
    candidates = []
    for device in adapter.scan_get_results():
        if should_stop():
            return
        name = device.identifier() or device.address()
        garmin = "hrm-dual" in name.lower().replace(" ", "-")
        if target["address"]:
            if device.address().upper() != target["address"]:
                continue
        elif not garmin and not any(service.uuid() == SERVICE_UUID for service in device.services()):
            continue
        candidates.append((garmin, device.rssi(), device, name))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _, _, device, name in candidates:
        if should_stop():
            return
        try:
            listen(target, messages, should_stop, device, name)
            return
        except RuntimeError as error:
            link(messages, "error", device.address(), str(error))
            messages.put(("status", f"Bluetooth error: {error}"))
            if target["address"]:
                return
    messages.put(("status", "No usable heart rate monitor found. Retrying…"))


def link(messages, kind, address, detail):
    messages.put(("link", (timestamp(), address, kind, detail)))


def listen(target, messages, should_stop, device, name):
    address = device.address()
    messages.put(("status", f"Connecting to {name} ({address})…"))
    packets = Queue()

    def receive(data):
        packets.put((timestamp(), bytes(data)))

    device.connect()
    listening = False
    try:
        if should_stop():
            return
        connected_at = timestamp()
        device.notify(SERVICE_UUID, MEASUREMENT_UUID, receive)
        target["address"] = address.upper()
        listening = True
        messages.put(("link", (connected_at, address, "connected", name)))
        messages.put(("status", f"Monitoring {name} ({address})"))
        last_arrival = monotonic()
        silent = False

        while not should_stop():
            try:
                stamp, payload = packets.get(timeout=0.25)
            except Empty:
                if not device.is_connected():
                    break
                if not silent and monotonic() - last_arrival >= 5:
                    silent = True
                    link(messages, "silent", address, "No notifications for at least 5 seconds")
                continue

            last_arrival = stamp[0]
            if silent:
                silent = False
                messages.put(("link", (stamp, address, "resumed", "Notifications resumed")))
            messages.put(("packet", (stamp, address, MEASUREMENT_UUID, payload)))
    finally:
        if listening:
            link(messages, "disconnected", address, name)
            messages.put(("status", f"Disconnected from {name}"))
        if device.is_connected():
            device.disconnect()
