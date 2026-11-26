"""Measure real SQLite disk limits with isolated synthetic data; no network I/O."""
import ctypes
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from cloud_storage import Outbox, MAX_RECORDS, MAX_DB_BYTES


def allocated(path):
    if os.name != "nt":
        stat = path.stat()
        return getattr(stat, "st_blocks", 0) * 512
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel.GetCompressedFileSizeW
    function.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    function.restype = wintypes.DWORD
    high = wintypes.DWORD()
    low = function(str(path), ctypes.byref(high))
    if low == 0xFFFFFFFF and ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    return (high.value << 32) | low


def footprint(folder):
    logical = physical = 0
    for path in folder.glob("outbox.sqlite3*"):
        try:
            logical += path.stat().st_size
            physical += allocated(path)
        except (FileNotFoundError, PermissionError):
            pass  # A rollback journal may disappear between observations.
    return logical, physical


def main():
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cloud-capacity-", dir=runtime) as temporary:
        folder = Path(temporary).resolve()
        if not folder.is_relative_to(runtime.resolve()):
            raise RuntimeError("Temporary measurement must remain inside the project runtime")
        outbox = Outbox(folder / "outbox.sqlite3")
        stop = threading.Event()
        peaks = [0, 0]
        def sample():
            while not stop.wait(.002):
                logical, physical = footprint(folder)
                peaks[0] = max(peaks[0], logical)
                peaks[1] = max(peaks[1], physical)
        monitor = threading.Thread(target=sample)
        monitor.start()
        error = None
        started = time.monotonic()
        try:
            for offset in range(0, MAX_RECORDS, 100):
                # Roughly real-sized rows with stable identities, explicitly synthetic.
                rows = [("parking_node,source=uno,data_origin=synthetic "
                         "sample_present=1i,a1_distance_cm=27.5,a1_distance_cm_valid=true,"
                         "a1_occupied=false,a1_occupied_valid=true,m1_distance_cm_valid=false,"
                         "m1_occupied_valid=false,vibration_valid=false,vibration_status=\"not_installed\" "
                         + str(1_795_651_200_000_000_000 + n * 1_000_000_000), float(n))
                        for n in range(offset, min(offset + 100, MAX_RECORDS))]
                try:
                    outbox.put(rows)
                except sqlite3.Error as exc:
                    error = getattr(exc, "sqlite_errorname", type(exc).__name__)
                    break
            depth = outbox.depth()
            size = (folder / "outbox.sqlite3").stat().st_size
            assert size <= MAX_DB_BYTES
            assert peaks[1] <= 32 * 1024 * 1024
        finally:
            stop.set(); monitor.join(); outbox.close()
        # A real reopen verifies the committed rows remain readable after capacity pressure.
        reopened = Outbox(folder / "outbox.sqlite3")
        try:
            assert reopened.depth() == depth
        finally:
            reopened.close()
        print(json.dumps({"data_origin":"synthetic", "network_requests":0,
                          "committed_rows":depth,"database_bytes":size,
                          "sampled_peak_database_plus_journal_bytes":peaks[0],
                          "sampled_peak_allocated_bytes":peaks[1],"capacity_error":error,
                          "elapsed_seconds":round(time.monotonic()-started,3),
                          "reopen":"PASS", "temporary_files_removed":True}))


if __name__ == "__main__":
    main()
