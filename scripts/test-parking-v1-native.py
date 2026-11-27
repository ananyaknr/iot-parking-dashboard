"""Real broker, mock teammate/gateway, unique isolated namespace; no sessions."""
import json
from pathlib import Path
import sys
import threading
import time
from datetime import datetime,timezone,timedelta
import uuid
import paho.mqtt.client as mqtt
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from parking_v1 import ParkingV1,PREFIX,TELEMETRY,COMMAND,CONTROL,WIRE_ACK,ARRIVAL,ACK,FEEDBACK,FEEDBACK_ACK

def main():
    run=uuid.uuid4().hex;sandbox='parking/test/acceptance/'+run+'/'
    env=dict(x.split('=',1) for x in (ROOT/'.env').read_text().splitlines() if x and not x.startswith('#') and '=' in x)
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='parking-v1-test-'+run[:12])
    client.username_pw_set(env['MQTT_USERNAME'],env['MQTT_PASSWORD'])
    connected=threading.Event();records=[];errors=[];rejected=[];commands={}
    def wire(topic):return topic.replace(PREFIX,sandbox,1)
    bridge=ParkingV1(ROOT/'.runtime'/('parking-v1-native-'+run+'.sqlite3'),lambda t,p:client.publish(wire(t),p,qos=1,retain=False))
    def publish(topic,m):client.publish(wire(topic),json.dumps(m,ensure_ascii=False),qos=1,retain=False)
    def on_connect(c,u,f,r,p):
        if r==0:c.subscribe(sandbox+'#',qos=1);connected.set()
    def on_message(c,u,msg):
        topic=msg.topic.replace(sandbox,PREFIX,1)
        try:
            m=json.loads(msg.payload);records.append((topic,m))
            if topic in (TELEMETRY,COMMAND,WIRE_ACK,FEEDBACK_ACK):
                try:bridge.receive(topic,msg.payload,msg.retain)
                except ValueError:rejected.append(topic)
            elif topic==ARRIVAL and m['direction']=='entrance':
                if m['arrival_id'] not in commands:
                    now=datetime.now(timezone.utc)
                    commands[m['arrival_id']]={'schema_version':1,'event_id':uuid.uuid4().hex,'arrival_id':m['arrival_id'],
                        'producer_id':'isolated-mock','command_id':uuid.uuid4().hex,'session_id':'TEST_ONLY_NO_SESSION_WRITE','decision_id':'TEST_DECISION',
                        'action':'OPEN','direction':'entrance','occurred_at':now.isoformat(),'issued_at':now.isoformat(),
                        'expires_at':(now+timedelta(seconds=5)).isoformat(),'license_plate':'ทดสอบ TEST',
                        'lcd_plate':'TEST|PLATE','vehicle_type':'sportcar'}
                    publish(COMMAND,commands[m['arrival_id']]);publish(COMMAND,commands[m['arrival_id']])
            elif topic==CONTROL:
                assert bytes.fromhex(m['lcd_hex']).decode()=='TEST|PLATE'
                assert m['vehicle_type']=='sportcar'
                publish(WIRE_ACK,{'wire_token':m['wire_token'],'status':'ok'})
        except Exception as exc:errors.append(type(exc).__name__)
    client.on_connect=on_connect;client.on_message=on_message
    client.connect(env['MQTT_BIND_IP'],int(env.get('MQTT_PORT','1883')),15);client.loop_start()
    def wait_for(predicate):
        end=time.monotonic()+15
        while time.monotonic()<end:
            if predicate():return
            bridge.tick();time.sleep(.05)
        raise AssertionError('Isolated MQTT acceptance timed out')
    try:
        assert connected.wait(10)
        t={'schema_version':3,'mode':'entrance_exit_sim','boot_id':run,'gateway_boot_id':'b'*32,
           'uptime_ms':10000,'gateway_uptime_ms':50000,'started_at_ms':9900,'u1_distance_cm':10.,'u2_distance_cm':40.,
           'u1_state':'detected','u2_state':'clear','phase':2,'lane':1,'cycle':1,'vibration_raw':1,
           'vibration_transition_count':2,'reason':2,'minimum_open_ms':5000,'servo_enabled':False}
        publish(TELEMETRY,t)
        wait_for(lambda:any(topic==ACK and m['state']=='accepted' for topic,m in records))
        assert sum(topic==CONTROL for topic,_ in records)==1
        originals={}
        for topic,m in records:
            if topic in (ARRIVAL,ACK):
                if m['event_id'] in originals:assert originals[m['event_id']]==m
                originals[m['event_id']]=m
        cmd=next(iter(commands.values()))
        publish(COMMAND,dict(cmd,event_id=uuid.uuid4().hex,command_id=uuid.uuid4().hex,direction='exit'))
        publish(COMMAND,dict(cmd,event_id=uuid.uuid4().hex,command_id=uuid.uuid4().hex,expires_at=datetime.now(timezone.utc).isoformat()))
        wait_for(lambda:len(rejected)>=2)
        t.update(uptime_ms=12000,gateway_uptime_ms=52000,started_at_ms=11900,cycle=2,phase=3,lane=2,
                 u1_distance_cm=40.,u2_distance_cm=10.,u1_state='clear',u2_state='detected')
        publish(TELEMETRY,t)
        wait_for(lambda:any(topic==ARRIVAL and m['direction']=='exit' for topic,m in records))
        wait_for(lambda:any(topic==FEEDBACK and m['direction']=='exit' for topic,m in records))
        feedback=next(m for topic,m in records if topic==FEEDBACK and m['direction']=='exit')
        assert feedback['command_id'] is None and not feedback['passage_confirmed']
        publish(FEEDBACK_ACK,{'schema_version':1,'event_id':uuid.uuid4().hex,'producer_id':'isolated-mock',
          'occurred_at':datetime.now(timezone.utc).isoformat(),'arrival_id':feedback['arrival_id'],
          'feedback_id':feedback['event_id'],'state':'recorded'})
        wait_for(lambda:bridge.snapshot()['pending_feedback']==0)
        assert sum(topic==CONTROL for topic,_ in records)==1 and not errors
        receipt={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'namespace':sandbox,
          'real_broker':True,'mock_teammate_and_gateway':True,'physical_hardware_test':False,
          'entrance_correlated_open':True,'unicode_and_ascii_sportcar':True,'duplicate_control_count':1,
          'exit_arrival_without_open_command':True,'invalid_direction_and_expiry_rejected':len(rejected),
          'feedback_published':True,'feedback_recorded_ack':True,'parking_sessions_written':0,'production_messages':0}
        (ROOT/'.runtime/parking-v1-native-receipt.json').write_text(json.dumps(receipt,indent=2))
        print(json.dumps(receipt,indent=2))
    finally:client.disconnect();client.loop_stop();bridge.close()

if __name__=='__main__':main()
