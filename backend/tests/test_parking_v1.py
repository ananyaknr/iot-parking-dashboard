import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from parking_v1 import ParkingV1,TELEMETRY,COMMAND,ARRIVAL,ACK,CONTROL,WIRE_ACK,FEEDBACK,FEEDBACK_ACK

class ParkingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'ledger.sqlite3'
        self.sent=[];self.now=datetime(2026,11,27,8,0,tzinfo=timezone.utc);self.mono=10.
        self.bridge=ParkingV1(self.path,lambda topic,payload:self.sent.append((topic,json.loads(payload))),clock=lambda:self.now,mono=lambda:self.mono)
        self.t={'schema_version':3,'mode':'entrance_exit_sim','boot_id':'a'*32,'gateway_boot_id':'b'*32,
          'uptime_ms':10000,'gateway_uptime_ms':50000,'started_at_ms':9900,'u1_distance_cm':10.,'u2_distance_cm':40.,
          'u1_state':'detected','u2_state':'clear','phase':2,'lane':1,'cycle':1,'vibration_raw':1,
          'vibration_transition_count':2,'reason':2,'minimum_open_ms':5000,'servo_enabled':False}
        self.bridge.receive(TELEMETRY,json.dumps(self.t).encode());self.bridge.tick()
        self.arrival=self.sent[-1][1]
        self.cmd={'schema_version':1,'event_id':'command_event','arrival_id':self.arrival['arrival_id'],'command_id':'command_1',
          'producer_id':'teammate','session_id':'test_session','decision_id':'test_decision','action':'OPEN','direction':'entrance',
          'occurred_at':self.now.isoformat(),'issued_at':self.now.isoformat(),'expires_at':(self.now+timedelta(seconds=5)).isoformat(),
          'license_plate':'ทดสอบ TEST','lcd_plate':'TEST|PLATE','vehicle_type':'sportcar','reservation_ref':'preserved_extension'}
    def tearDown(self):self.bridge.close();self.tmp.cleanup()
    def send(self,m):return self.bridge.receive(COMMAND,json.dumps(m,ensure_ascii=False).encode())
    def test_correlation_unicode_lcd_hex_dedup_and_ack(self):
        self.send(self.cmd)
        control=next(m for t,m in self.sent if t==CONTROL)
        self.assertEqual(bytes.fromhex(control['lcd_hex']).decode(),'TEST|PLATE')
        self.assertEqual(control['deadline_ms'],55000)
        self.assertEqual(self.bridge.snapshot()['recognition']['license_plate'],'ทดสอบ TEST')
        self.send(self.cmd);self.assertEqual(sum(t==CONTROL for t,_ in self.sent),1)
        self.bridge.receive(WIRE_ACK,json.dumps({'wire_token':control['wire_token'],'status':'ok'}).encode())
        acks=[m for t,m in self.sent if t==ACK]
        self.assertEqual(acks[-1]['state'],'accepted');self.assertEqual(len(acks),1)
        self.assertEqual(acks[-1]['arrival_id'],self.arrival['arrival_id'])
        self.assertTrue(self.bridge.snapshot()['feedback_enabled'])
        stored=self.path.read_bytes()
        self.assertNotIn(self.cmd['license_plate'].encode(),stored)
        self.assertNotIn(self.cmd['lcd_plate'].encode(),stored)
    def test_arrival_retries_preserve_payload_ids_and_direction(self):
        self.mono+=2;self.bridge.tick();self.assertEqual(self.sent[0],self.sent[1])
        self.assertEqual(self.arrival['trigger'],'ultrasonic');self.assertEqual(self.arrival['direction'],'entrance')
        self.assertNotEqual(self.arrival['event_id'],self.arrival['arrival_id'])
    def test_exit_arrival_without_any_open_command(self):
        self.t.update(uptime_ms=11000,lane=2,phase=3,cycle=2,started_at_ms=10900,u1_distance_cm=40.,u2_distance_cm=10.,u1_state='clear',u2_state='detected')
        self.bridge.receive(TELEMETRY,json.dumps(self.t).encode());self.bridge.tick()
        self.assertEqual(self.sent[-1][1]['direction'],'exit');self.assertFalse(any(t==CONTROL for t,_ in self.sent))
    def test_expiry_direction_identity_and_conflicts(self):
        for i,change in enumerate(({'direction':'exit'},{'arrival_id':'wrong'},{'expires_at':self.now.isoformat()},{'lcd_plate':'ก'}, {'vehicle_type':'unknown'})):
            with self.assertRaises(ValueError):self.send(dict(self.cmd,command_id='invalid_'+str(i),event_id='invalid_event_'+str(i),**change))
        self.send(self.cmd)
        with self.assertRaises(ValueError):self.send(dict(self.cmd,lcd_plate='CHANGED'))
        with self.assertRaises(ValueError):self.send(dict(self.cmd,command_id='new_command',event_id='new_event'))
    def test_retained_duplicate_keys_stale_and_restart_no_replay(self):
        with self.assertRaises(ValueError):self.bridge.receive(COMMAND,json.dumps(self.cmd).encode(),True)
        with self.assertRaises(ValueError):self.bridge.receive(COMMAND,b'{"event_id":"a","event_id":"b"}')
        self.mono+=3
        with self.assertRaises(ValueError):self.send(dict(self.cmd,command_id='stale',event_id='stale_event'))
        self.mono-=3;self.send(self.cmd);self.bridge.close()
        self.sent=[];self.bridge=ParkingV1(self.path,lambda t,p:self.sent.append((t,json.loads(p))),clock=lambda:self.now,mono=lambda:self.mono)
        self.send(self.cmd);self.assertFalse(any(t==CONTROL for t,_ in self.sent));self.assertEqual(self.sent[-1][1]['status'],'unknown')
    def test_no_echo_is_not_clear_and_expired_arrival_not_replayed(self):
        bad=dict(self.t,uptime_ms=11000,u2_distance_cm=None)
        with self.assertRaises(ValueError):self.bridge.receive(TELEMETRY,json.dumps(bad).encode())
        self.now+=timedelta(seconds=21);n=len(self.sent);self.mono+=21;self.bridge.tick();self.assertEqual(len(self.sent),n)
    def test_ack_timeout_is_not_passage(self):
        self.send(self.cmd);self.now+=timedelta(seconds=6);self.mono+=6;self.bridge.tick()
        self.assertEqual(self.sent[-1][1]['status'],'unknown')
        self.assertNotIn('passage_confirmed',self.sent[-1][1])
        previous=self.sent[-1][1];self.send(self.cmd)
        self.assertEqual(self.sent[-1][1],previous)
        self.assertEqual(sum(t==CONTROL for t,_ in self.sent),1)

    def test_feedback_completed_requires_closing_and_durable_recorded_ack(self):
        self.send(self.cmd)
        self.assertFalse(any(t==ACK for t,_ in self.sent))
        self.t.update(uptime_ms=11000,phase=3,reason=5)
        self.bridge.receive(TELEMETRY,json.dumps(self.t));self.bridge.tick()
        opening=[m for t,m in self.sent if t==FEEDBACK][-1]
        self.assertEqual(opening['state'],'opening');self.assertFalse(opening['passage_confirmed'])
        self.now+=timedelta(seconds=2);self.bridge.tick()
        self.assertEqual([m for t,m in self.sent if t==FEEDBACK][-1],opening)
        self.bridge.close();self.bridge=ParkingV1(self.path,lambda t,p:self.sent.append((t,json.loads(p))),clock=lambda:self.now,mono=lambda:self.mono)
        self.now+=timedelta(seconds=4);self.bridge.tick()
        self.assertEqual([m for t,m in self.sent if t==FEEDBACK][-1],opening)
        ack={'schema_version':1,'event_id':'receipt_event','producer_id':'mock','occurred_at':self.now.isoformat(),
             'arrival_id':opening['arrival_id'],'feedback_id':opening['event_id'],'state':'recorded'}
        self.bridge.receive(FEEDBACK_ACK,json.dumps(ack))
        self.assertEqual(self.bridge.snapshot()['pending_feedback'],0)
        self.t.update(uptime_ms=18000,phase=4,reason=6,u1_distance_cm=40.,u2_distance_cm=40.,u1_state='clear',u2_state='clear')
        self.bridge.receive(TELEMETRY,json.dumps(self.t))
        self.t.update(uptime_ms=19000,phase=1,lane=0,reason=13)
        self.bridge.receive(TELEMETRY,json.dumps(self.t));self.bridge.tick()
        complete=[m for t,m in self.sent if t==FEEDBACK][-1]
        self.assertEqual(complete['state'],'completed');self.assertTrue(complete['passage_confirmed'])
        self.assertEqual(complete['command_id'],self.cmd['command_id'])

    def test_feedback_backoff_and_exit_has_null_command(self):
        self.t.update(uptime_ms=11000,lane=2,phase=3,cycle=2,started_at_ms=10900,u1_distance_cm=40.,u2_distance_cm=10.,u1_state='clear',u2_state='detected')
        self.bridge.receive(TELEMETRY,json.dumps(self.t));self.bridge.tick()
        feedback=[m for t,m in self.sent if t==FEEDBACK][-1]
        self.assertIsNone(feedback['command_id']);self.assertEqual(feedback['direction'],'exit')
        for delay in (2,4,8,16,30,30):
            self.assertEqual(self.bridge.db.execute('SELECT next_send FROM feedback').fetchone()[0],self.now.timestamp()+delay)
            self.now+=timedelta(seconds=delay);self.bridge.tick()
            self.assertEqual([m for t,m in self.sent if t==FEEDBACK][-1],feedback)

    def test_normal_vip_types_and_full_category_no_command(self):
        for i,kind in enumerate(('car','sportcar','supercar'),1):
            self.t.update(uptime_ms=10000+i*1000,cycle=i,phase=2,lane=1,started_at_ms=9900+i*1000)
            self.bridge.receive(TELEMETRY,json.dumps(self.t));self.bridge.tick()
            aid=f"r_{self.t['boot_id']}_{i}"
            self.send(dict(self.cmd,arrival_id=aid,event_id='event_'+str(i),command_id='command_'+str(i),vehicle_type=kind))
            self.assertEqual([m for t,m in self.sent if t==CONTROL][-1]['vehicle_type'],kind)
        count=sum(t==CONTROL for t,_ in self.sent)
        # Full-category decision belongs to teammate: absence of OPEN cannot move this gate.
        self.t.update(uptime_ms=15000,cycle=4,started_at_ms=14900)
        self.bridge.receive(TELEMETRY,json.dumps(self.t));self.bridge.tick()
        self.assertEqual(sum(t==CONTROL for t,_ in self.sent),count)
        self.assertFalse(any(m['passage_confirmed'] for t,m in self.sent if t==FEEDBACK))

    def test_automatic_close_is_review_never_passage_and_physical_rejected(self):
        self.t.update(mode='entrance_exit_auto_sim',uptime_ms=11000,phase=3,reason=5)
        self.bridge.receive(TELEMETRY,json.dumps(self.t))
        self.t.update(uptime_ms=17000,phase=4,reason=6,u1_distance_cm=25.,u1_state='clear')
        self.bridge.receive(TELEMETRY,json.dumps(self.t))
        self.t.update(uptime_ms=18000,phase=1,lane=0,reason=16)
        self.bridge.receive(TELEMETRY,json.dumps(self.t));self.bridge.tick()
        feedback=[m for t,m in self.sent if t==FEEDBACK][-1]
        self.assertEqual(feedback['state'],'hold')
        self.assertFalse(feedback['passage_confirmed'])
        self.assertEqual(feedback['arrival_id'],self.arrival['arrival_id'])
        # Even an erroneous legacy completion reason cannot confirm automatic passage.
        self.t.update(uptime_ms=19000,reason=13)
        self.bridge.receive(TELEMETRY,json.dumps(self.t));self.bridge.tick()
        self.assertFalse(any(m['passage_confirmed'] for t,m in self.sent if t==FEEDBACK))
        with self.assertRaises(ValueError):
            self.bridge.receive(TELEMETRY,json.dumps(dict(self.t,mode='entrance_exit_auto_physical',servo_enabled=True)))

    def test_unverifiable_clock_and_wrong_feedback_correlation(self):
        self.bridge.clock_verified=lambda:False
        with self.assertRaises(ValueError):self.send(self.cmd)
        self.assertFalse(any(t==CONTROL for t,_ in self.sent))
        with self.assertRaises(ValueError):self.bridge.receive(FEEDBACK_ACK,json.dumps({'schema_version':1,
          'event_id':'test_ack','producer_id':'mock','occurred_at':self.now.isoformat(),
          'arrival_id':'wrong','feedback_id':'missing','state':'recorded'}))

if __name__=='__main__':unittest.main()
