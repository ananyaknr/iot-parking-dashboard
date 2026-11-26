"""Bounded ingestion/storage helpers. No network or hardware side effects."""
import queue
import threading
import time

from model import TOPICS, validate


class Ingestion:
    def __init__(self, states):
        self.states = states
        self.rejected = 0
        self.discarded = 0

    def receive(self, topic, payload, retained, duplicate, received, now):
        source = TOPICS[topic]
        state = self.states[source]
        # A delayed queue entry must never replace a newer value or revive it.
        if duplicate or now - received >= 10 or (
                state.last_received is not None and received <= state.last_received):
            self.discarded += 1
            return None
        try:
            if retained:
                raise ValueError("retained telemetry rejected")
            _, message = validate(topic, payload)
            if state.accept(message, received) is False:
                self.discarded += 1
                return None
            return source
        except (ValueError, TypeError, UnicodeError):
            state.reject(received)
            self.rejected += 1
            return None


class StorageWorker:
    """Retry the same bounded batch off the ingestion thread; drop newest on overflow.

    Influx points retain their timestamps across retries, so retrying a partial
    write overwrites the same point rather than creating a new receive time.
    """
    def __init__(self, write, capacity=2000, batch_size=100):
        self.write = write
        self.queue = queue.Queue(maxsize=capacity)
        self.batch_size = batch_size
        self.pending = []
        self.connected = False
        self.last_success = None
        self.failures = 0
        self.dropped = 0
        self.lock = threading.Lock()

    def submit(self, point):
        with self.lock:
            try:
                self.queue.put_nowait(point)
            except queue.Full:
                self.dropped += 1

    def flush(self):
        with self.lock:
            while len(self.pending) < self.batch_size:
                try:
                    self.pending.append(self.queue.get_nowait())
                except queue.Empty:
                    break
            batch = list(self.pending)
        if not batch:
            return True
        try:
            self.write(batch)
        except Exception:
            with self.lock:
                self.connected = False
                self.failures += 1
            return False
        with self.lock:
            self.pending.clear()
            self.connected = True
            self.last_success = time.monotonic()
        return True

    def snapshot(self):
        with self.lock:
            return {"storage_connected": self.connected and self.last_success is not None
                    and time.monotonic() - self.last_success < 10,
                    "storage_backlog": self.queue.qsize() + len(self.pending),
                    "storage_dropped_points": self.dropped, "storage_write_failures": self.failures}

    def run(self, stop):
        while not stop.is_set():
            stop.wait(0.05 if self.flush() else 1)
