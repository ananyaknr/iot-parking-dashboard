import json
import threading
import unittest

from model import Source, validate
from runtime import Ingestion, StorageWorker
from test_model import NODE


class RuntimeTests(unittest.TestCase):
    def test_delays_duplicates_order_retained_and_recovery(self):
        state = Source('uno')
        ingestion = Ingestion({'uno': state})
        payload = json.dumps(NODE)
        def send(received, now, retained=False, duplicate=False):
            return ingestion.receive('parking/node/telemetry', payload, retained, duplicate, received, now)
        self.assertEqual(send(20, 20), 'uno')
        for received, now, duplicate in [(19, 21, False), (21, 21, True), (21, 31, False)]:
            self.assertIsNone(send(received, now, duplicate=duplicate))
        self.assertEqual(state.last_valid, 20)
        self.assertFalse(state.snapshot(31)['a1_allocation_eligible'])
        self.assertIsNone(send(32, 32, retained=True))
        self.assertFalse(state.snapshot(32)['payload_valid'])
        self.assertEqual(send(33, 33), 'uno')
        self.assertEqual(ingestion.discarded, 3)
        self.assertEqual(ingestion.rejected, 1)

    def test_hysteresis_and_rounding(self):
        for distance, occupied in [(14.9, False), (18.1, True)]:
            with self.assertRaises(ValueError):
                validate('parking/node/telemetry', json.dumps(dict(NODE,a1_distance_cm=distance,a1_occupied=occupied)))
        for distance in (15, 16.2, 18):
            for occupied in (True, False):
                validate('parking/node/telemetry',json.dumps(dict(NODE,a1_distance_cm=distance,a1_occupied=occupied)))

    def test_bounded_outage_and_identical_retry(self):
        batches=[]
        def write(batch):
            batches.append(batch)
            if len(batches) == 1:
                raise OSError('database offline')
        worker=StorageWorker(write,capacity=2,batch_size=2)
        worker.submit('original timestamp 1'); worker.submit('original timestamp 2')
        self.assertFalse(worker.flush())
        self.assertFalse(worker.snapshot()['storage_connected'])
        for point in (3,4,5):worker.submit(point)
        self.assertEqual(worker.snapshot()['storage_backlog'],4)
        self.assertEqual(worker.snapshot()['storage_dropped_points'],1)
        self.assertTrue(worker.flush())
        self.assertEqual(batches[0],batches[1])
        self.assertTrue(worker.snapshot()['storage_connected'])
        self.assertTrue(worker.flush())
        self.assertEqual(batches[-1],[3,4])

    def test_slow_storage_does_not_hold_ingestion(self):
        started=threading.Event(); release=threading.Event()
        def write(batch):
            started.set(); release.wait(5)
        worker=StorageWorker(write)
        worker.submit('synthetic')
        thread=threading.Thread(target=worker.flush)
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            state=Source('uno'); ingestion=Ingestion({'uno':state})
            self.assertEqual(ingestion.receive('parking/node/telemetry',json.dumps(NODE),False,False,1,1),'uno')
            worker.submit('next')
            self.assertEqual(worker.snapshot()['storage_backlog'],2)
        finally:
            release.set(); thread.join()
