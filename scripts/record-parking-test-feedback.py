"""Explicit mock receiver for isolated feedback recovery; no session writes."""
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time
import uuid
import paho.mqtt.client as mqtt

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from parking_clock import VerifiedClock
from parking_v1 import FEEDBACK,FEEDBACK_ACK

def main():
    env=dict(x.split('=',1) for x in (ROOT/'.env').read_text().splitlines() if x and not x.startswith('#') and '=' in x)
    db=sqlite3.connect(ROOT/'.runtime/parking-v1-test.sqlite3')
    expected={fid:json.loads(raw) for fid,raw in db.execute('SELECT id,payload FROM feedback WHERE recorded=0')}
    stop=threading.Event();clock=VerifiedClock(stop)
    for _ in range(30):
        if clock.verified():break
        time.sleep(.1)
    if not clock.verified():raise RuntimeError('UTC unavailable')
    c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='feedback-test-recorder-'+uuid.uuid4().hex[:10])
    c.username_pw_set(env['MQTT_USERNAME'],env['MQTT_PASSWORD'])
    seen={};errors=[];acks={}
    def connect(c,u,f,r,p):
        if r==0:c.subscribe(FEEDBACK,qos=1)
    def message(c,u,msg):
        if msg.retain:return
        m=json.loads(msg.payload)
        if m['event_id'] not in expected:return
        if m!=expected[m['event_id']]:errors.append('Payload changed across restart');return
        # Mock only records receipt; does not match identity, reserve or release bays.
        seen[m['event_id']]=m
        if m['event_id'] not in acks:
            acks[m['event_id']]={'schema_version':1,'event_id':uuid.uuid4().hex,'producer_id':'isolated-feedback-recorder',
                 'occurred_at':clock().isoformat(),'arrival_id':m['arrival_id'],'feedback_id':m['event_id'],'state':'recorded'}
        ack=acks[m['event_id']]
        c.publish(FEEDBACK_ACK,json.dumps(ack),qos=1,retain=False)
    c.on_connect=connect;c.on_message=message;c.connect(env['MQTT_BIND_IP'],int(env.get('MQTT_PORT','1883')),15);c.loop_start()
    try:
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            pending=db.execute('SELECT count(*) FROM feedback WHERE recorded=0').fetchone()[0]
            if set(seen)==set(expected) and pending==0:break
            time.sleep(.2)
        result={'verified_at_utc':clock().isoformat(),'isolated_mock_receiver':True,
                'pending_after_backend_restart':len(expected),'same_payloads_received':len(seen),
                'pending_after_recorded_ack':pending,'states':sorted({m['state'] for m in seen.values()}),
                'terminal_exit_command_id_null':any(m['state']=='completed' and m['direction']=='exit' and m['command_id'] is None for m in seen.values()),
                'physical_movement':False,'session_writes':0,'errors':errors}
        (ROOT/'.runtime/parking-feedback-recovery.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))
        assert not errors and len(seen)==len(expected) and pending==0
    finally:c.disconnect();c.loop_stop();db.close();stop.set()

if __name__=='__main__':main()
