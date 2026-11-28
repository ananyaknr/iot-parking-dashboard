import json
import unittest
import test_parking_v1 as legacy_tests
from parking_v1 import ParkingV1,TELEMETRY,COMMAND,CONTROL,ACK,FEEDBACK,WIRE_ACK,FEEDBACK_ACK


class InferredTests(unittest.TestCase):
    def setUp(self):
        legacy_tests.ParkingTests.setUp(self)
        self.bridge.close();self.path=self.path.with_name('physical-test.sqlite3')
        self.sent=[];self.open_bridge()
        self.t.update(mode='entrance_exit_auto_physical',servo_enabled=True)
        self.cmd['simulation']=False

    def tearDown(self):legacy_tests.ParkingTests.tearDown(self)

    def open_bridge(self):
        self.bridge=ParkingV1(self.path,lambda t,p:self.sent.append((t,json.loads(p))),
            clock=lambda:self.now,mono=lambda:self.mono,physical_inferred=True,test_storage=True)

    def telemetry(self,**changes):
        self.t.update(changes);self.bridge.receive(TELEMETRY,json.dumps(self.t))

    def start(self,exit=False):
        if exit:self.t.update(lane=2,phase=3,reason=3,u1_distance_cm=40.,u2_distance_cm=10.,u1_state='clear',u2_state='detected')
        self.telemetry();self.bridge.tick()
        arrival=[m for t,m in self.sent if t.endswith('/v1/arrival')][-1]
        self.assertIs(arrival['simulation'],False)
        if not exit:
            self.bridge.receive(COMMAND,json.dumps(self.cmd))
            token=[m for t,m in self.sent if t==CONTROL][-1]['wire_token']
            self.bridge.receive(WIRE_ACK,json.dumps({'wire_token':token,'status':'ok'}))
            ack=[m for t,m in self.sent if t==ACK][-1]
            self.assertIs(ack['simulation'],False)
            self.assertNotIn('physical_movement',ack)
            self.telemetry(uptime_ms=11000,phase=3,reason=5)

    def finish(self,reason=17):
        self.telemetry(uptime_ms=17000,phase=4,reason=6,u1_distance_cm=25.,u2_distance_cm=25.,u1_state='clear',u2_state='clear')
        self.telemetry(uptime_ms=17400) # repeated closing must not restart its interval
        self.telemetry(uptime_ms=17500,phase=1,lane=0,reason=reason)
        self.bridge.tick()
        return [m for t,m in self.sent if t==FEEDBACK][-1]

    def assert_inferred(self,m):
        self.assertEqual(m['state'],'completed');self.assertIs(m['simulation'],False)
        self.assertIs(m['passage_confirmed'],False);self.assertEqual(m['passage_basis'],'inferred_clearance')

    def test_clean_entrance(self):
        self.start();result=self.finish();self.assert_inferred(result)
        self.assertEqual(result['command_id'],self.cmd['command_id'])
        self.telemetry(uptime_ms=17600) # repeat terminal report, no new outcome
        self.now=self.now.replace(second=2);self.bridge.tick()
        self.assertEqual([m for t,m in self.sent if t==FEEDBACK][-1],result)

    def test_clean_exit(self):
        self.start(exit=True);self.assertFalse(any(t==CONTROL for t,_ in self.sent))
        result=self.finish();self.assert_inferred(result);self.assertIsNone(result['command_id'])

    def test_fault_then_recovery_never_infers(self):
        for fault in ('invalid','hold','disconnect','stale'):
            with self.subTest(fault=fault):
                self.bridge.close();self.path=self.path.with_name(fault+'-test.sqlite3')
                self.open_bridge();self.sent=[]
                self.t.update(uptime_ms=10000,lane=1,phase=2,reason=2,u1_distance_cm=10.,u2_distance_cm=40.,u1_state='detected',u2_state='clear')
                self.start()
                if fault=='invalid':self.telemetry(uptime_ms=12000,u1_distance_cm=None,u1_state='unknown')
                elif fault=='hold':self.telemetry(uptime_ms=12000,phase=5,reason=12)
                elif fault=='disconnect':self.bridge.interrupt()
                else:self.mono+=3
                self.telemetry(uptime_ms=13000,phase=3,u1_distance_cm=25.,u1_state='clear')
                result=self.finish() # contradictory clean reason cannot restore the trace
                self.assertEqual(result['state'],'hold');self.assertNotIn('passage_basis',result)
                self.assertIs(result['passage_confirmed'],False)

    def test_duplicate_restart_and_feedback_receipt(self):
        self.start();self.bridge.receive(COMMAND,json.dumps(self.cmd))
        self.assertEqual(sum(t==CONTROL for t,_ in self.sent),1)
        self.bridge.close();self.open_bridge()
        self.bridge.receive(COMMAND,json.dumps(self.cmd))
        self.assertEqual(sum(t==CONTROL for t,_ in self.sent),1)
        result=self.finish();self.assertEqual(result['state'],'hold')
        self.bridge.close();self.open_bridge();self.now=self.now.replace(second=4);self.bridge.tick()
        self.assertEqual([m for t,m in self.sent if t==FEEDBACK][-1],result)
        self.bridge.receive(FEEDBACK_ACK,json.dumps({'schema_version':1,'event_id':'receipt','producer_id':'test',
            'occurred_at':self.now.isoformat(),'arrival_id':result['arrival_id'],'feedback_id':result['event_id'],'state':'recorded'}))
        self.assertEqual(self.bridge.snapshot()['pending_feedback'],1) # earlier opening still pending

    def test_mode_mismatch_and_storage_guard(self):
        with self.assertRaises(ValueError):self.telemetry(mode='entrance_exit_sim',servo_enabled=False)
        self.assertIsNone(self.bridge.current)
        self.telemetry(mode='entrance_exit_auto_physical',servo_enabled=True)
        with self.assertRaises(ValueError):self.bridge.receive(COMMAND,json.dumps(dict(self.cmd,simulation=True)))
        with self.assertRaises(ValueError):ParkingV1(self.path,lambda *_:None)
        with self.assertRaises(ValueError):ParkingV1(self.path,lambda *_:None,physical_inferred=True)
        # A recognizable expired physical command still returns a physical ACK.
        with self.assertRaises(ValueError):
            self.bridge.receive(COMMAND,json.dumps(dict(self.cmd,command_id='expired',event_id='expired_event',expires_at=self.now.isoformat())))
        self.assertIs([m for t,m in self.sent if t==ACK][-1]['simulation'],False)

    def test_supervised_simulation_unchanged(self):
        self.bridge.close();self.path=self.path.with_name('legacy-test.sqlite3');self.sent=[]
        self.bridge=ParkingV1(self.path,lambda t,p:self.sent.append((t,json.loads(p))),clock=lambda:self.now,mono=lambda:self.mono)
        self.t.update(mode='entrance_exit_sim',servo_enabled=False)
        self.cmd.pop('simulation');self.telemetry();self.bridge.receive(COMMAND,json.dumps(self.cmd))
        self.telemetry(uptime_ms=11000,phase=3,reason=5)
        result=self.finish(reason=13)
        self.assertEqual(result['state'],'completed');self.assertIs(result['passage_confirmed'],True)
        self.assertIs(result['simulation'],True);self.assertNotIn('passage_basis',result)


if __name__=='__main__':unittest.main()
