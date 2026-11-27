"""Run the explicitly isolated joint adapter beside both existing services."""
import argparse
import json
from pathlib import Path
import queue
import sys
import threading
import uuid
import paho.mqtt.client as mqtt
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from parking_clock import VerifiedClock
from parking_http import ParkingHTTP
from parking_v1 import ARRIVAL,ACK,FEEDBACK

def main():
    p=argparse.ArgumentParser();p.add_argument('--api-url',default='http://127.0.0.1:8001')
    p.add_argument('--test-storage-confirmed',action='store_true',required=True)
    p.add_argument('--lcd-map',type=Path);p.add_argument('--check',action='store_true')
    args=p.parse_args();stop=threading.Event();clock=VerifiedClock(stop)
    env=dict(x.split('=',1) for x in (ROOT/'.env').read_text().splitlines() if x and not x.startswith('#') and '=' in x)
    c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='parking-http-test-'+uuid.uuid4().hex[:10])
    c.username_pw_set(env['MQTT_USERNAME'],env['MQTT_PASSWORD']);messages=queue.Queue(maxsize=200)
    bridge=ParkingHTTP(args.api_url,':memory:' if args.check else ROOT/'.runtime/joint-http-test.sqlite3',lambda t,b:c.publish(t,b,qos=1,retain=False),clock,
                       json.loads(args.lcd_map.read_text(encoding='utf-8')) if args.lcd_map else None)
    try:
        print(json.dumps(bridge.preflight()),flush=True)
        if args.check:return
        def connect(c,u,f,r,p):
            if r==0:c.subscribe([(ARRIVAL,1),(ACK,1),(FEEDBACK,1)])
        def message(c,u,m):
            try:messages.put_nowait((m.topic,bytes(m.payload),m.retain))
            except queue.Full:print('Joint receive queue full; durable source retries required',flush=True)
        c.on_connect=connect;c.on_message=message;c.connect(env['MQTT_BIND_IP'],int(env.get('MQTT_PORT','1883')),15);c.loop_start()
        print('Joint test bridge active; exit commit waits for completed confirmed passage',flush=True)
        while True:
            try:
                try:item=messages.get(timeout=.2)
                except queue.Empty:item=None
                if item:bridge.receive(*item)
                bridge.tick()
            except Exception as exc:
                # Responses may contain real plates/secrets: print only exception type.
                print('Joint action needs review/retry: '+type(exc).__name__,flush=True)
    except KeyboardInterrupt:pass
    finally:c.disconnect();c.loop_stop();bridge.close();stop.set()

if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('Joint bridge blocked: '+type(exc).__name__) from None
