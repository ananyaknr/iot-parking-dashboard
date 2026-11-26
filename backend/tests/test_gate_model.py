import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch

from gate_model import GateSource,validate_gate,identity
from gate_events import GateEvents,gate_routing
from model import validate
from runtime import Ingestion
from cloud_storage import telemetry_line,CloudClient,start_optional_cloud,start_gate_test_cloud

BOOT='0123456789abcdef0123456789abcdef'
GATE={'node':'uno','schema_version':2,'mode':'gate_sim','control_mode':'standalone',
      'boot_id':BOOT,'uptime_ms':1000,'u1_distance_cm':40.0,'u2_distance_cm':45.0,
      'u1_state':'clear','u2_state':'clear','gate_sim_state':'closed','servo_enabled':False,
      'arrival_count':0,'completed_count':0,'vibration_raw':1,'vibration_transition_count':0,
      'vibration_semantics':'sampled_transitions','event_seq':1,'last_event':'ready',
      'arrival_id':None,'passage_id':None,'event_id':identity(BOOT,'e',1)}


class GateTests(unittest.TestCase):
    def test_strict_schema_and_no_actuation(self):
        self.assertEqual(validate('parking/gate/telemetry',json.dumps(GATE)),('gate',GATE))
        invalid=[dict(GATE,schema_version=True),dict(GATE,schema_version=3),dict(GATE,servo_enabled=True),
                 dict(GATE,u1_distance_cm=None),dict(GATE,u1_distance_cm=float('nan')),
                 dict(GATE,u2_distance_cm=1),dict(GATE,arrival_count=True),
                 dict(GATE,completed_count=1),dict(GATE,event_id='reboot_counter'),
                 dict(GATE,license_plate='NOT_ALLOWED'),dict(GATE,gate_sim_state='closing'),
                 dict(GATE,gate_sim_state='authorization_wait'),dict(GATE,vibration_raw=2)]
        for message in invalid:
            with self.subTest(message=message),self.assertRaises(ValueError):validate_gate(message)
        with self.assertRaises(ValueError):validate('parking/node/telemetry',json.dumps(GATE))

    def test_unknown_and_debounce_are_distinct_from_clear(self):
        validate_gate(dict(GATE,u1_distance_cm=None,u1_state='unknown'))
        validate_gate(dict(GATE,u1_distance_cm=10,u1_state='unknown'))
        validate_gate(dict(GATE,u1_distance_cm=16,u1_state='clear'))
        with self.assertRaises(ValueError):validate_gate(dict(GATE,u1_distance_cm=10,u1_state='clear'))

    def test_freshness_replay_boots_and_counter_regression(self):
        zero_age=GateSource();zero_age.accept(GATE,1.0)
        self.assertIs(type(zero_age.snapshot(1.0)['age_seconds']),float)
        source=GateSource();self.assertTrue(source.accept(GATE,1))
        self.assertTrue(source.snapshot(2)['u1_distance_cm_valid'])
        self.assertFalse(source.snapshot(11)['u1_distance_cm_valid'])
        self.assertIsNone(source.snapshot(11)['servo_enabled'])
        self.assertFalse(source.accept(GATE,12))
        self.assertTrue(source.accept(dict(GATE,uptime_ms=1100),13))
        boot='a'*32
        self.assertTrue(source.accept(dict(GATE,boot_id=boot,event_id=identity(boot,'e',1)),14))
        self.assertFalse(source.accept(dict(GATE,uptime_ms=2000),15))
        source.reject(16);self.assertEqual(source.snapshot(16)['gate_sim_state'],'unknown')

    def test_duplicate_producer_snapshot_is_discarded_not_freshened(self):
        source=GateSource();ingestion=Ingestion({'gate':source})
        payload=json.dumps(GATE)
        self.assertEqual(ingestion.receive('parking/gate/telemetry',payload,False,False,1,1),'gate')
        self.assertIsNone(ingestion.receive('parking/gate/telemetry',payload,False,False,2,2))
        self.assertEqual(source.last_valid,1);self.assertEqual(ingestion.discarded,1)

    def test_routing_never_silently_promotes_simulation(self):
        self.assertFalse(gate_routing('hardware','parking','sensor_data'))
        self.assertTrue(gate_routing('synthetic','parking/test','sensor_test','isolated'))
        self.assertTrue(gate_routing('hardware_gate_sim','parking/test','sensor_test','isolated'))
        for origin,prefix,bucket,routing,approved in [
            ('synthetic','parking','sensor_data','production',True),
            ('hardware_gate_sim','parking','sensor_data','production',False),
            ('hardware_gate_sim','parking/test','sensor_data','isolated',False)]:
            with self.assertRaises(ValueError):gate_routing(origin,prefix,bucket,routing,approved)
        with patch('cloud_storage.load_config',side_effect=AssertionError('must not load production')):
            self.assertEqual(start_optional_cloud('hardware_gate_sim','parking','sensor_data'),(None,None))
            with self.assertRaises(ValueError):start_gate_test_cloud('synthetic','parking','sensor_data')

    def test_gate_cloud_schema_and_counter_history_are_separate(self):
        stamp=datetime.now(timezone.utc)
        self.assertIsNone(telemetry_line('gate',GATE,stamp))
        line=telemetry_line('gate',GATE,stamp,data_origin='synthetic')
        self.assertTrue(line.startswith('parking_gate_v2,'));self.assertIn('data_origin=synthetic',line)
        self.assertIn('servo_enabled=false',line);self.assertIn('arrival_count=0i',line)
        self.assertNotIn('schema_version=2i',line)
        self.assertNotIn('a1_',line);self.assertNotIn('license_plate',line)
        client=CloudClient({'bucket':'parking_sensor_test'})
        with patch.object(client,'request',return_value=b'{"results":[]}') as query:
            client.history('gate','arrival_count',1)
            self.assertIn('last("arrival_count")',query.call_args.args[1]['q'])
            client.history('gate','u1_distance_cm',1)
            self.assertIn('mean("u1_distance_cm")',query.call_args.args[1]['q'])

    def test_event_identity_survives_backend_restart_with_original_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'events.sqlite3';stamp=datetime.now(timezone.utc)
            ledger=GateEvents(path,capacity=1);first=ledger.remember(GATE,stamp);ledger.close()
            ledger=GateEvents(path,capacity=1)
            self.assertEqual(ledger.remember(GATE,stamp+timedelta(seconds=5)),first)
            self.assertEqual(len(ledger.recent()),1)
            changed=dict(GATE,event_id=identity(BOOT,'e',2),event_seq=2)
            with self.assertRaises(ValueError):ledger.remember(changed,stamp)
            with self.assertRaises(ValueError):ledger.remember(dict(GATE,last_event='boot'),stamp)
            self.assertNotIn('license_plate',str(ledger.recent()));ledger.close()
