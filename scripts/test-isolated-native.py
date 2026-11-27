"""Synthetic native acceptance on loopback ports 18884/18086/15001 only.

Creates fresh temporary Influx data, users and ACLs under ignored .runtime.
Never reads .env, changes deployed credentials, or uses production topics/buckets.
"""
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, build_opener, ProxyHandler
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'isolated-test-only-password'
TOKEN = 'isolated-test-only-token-012345678901234567890123456789'


def http(port, path, data=None, auth=None):
    headers = {'Content-Type': 'application/json'}
    if auth:
        headers['Authorization'] = auth
    request = Request(f'http://127.0.0.1:{port}{path}',
                      data=None if data is None else json.dumps(data).encode(), headers=headers)
    with build_opener(ProxyHandler({})).open(request, timeout=8) as response:
        return json.load(response)


def wait(check, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    raise AssertionError('isolated test condition timed out')


def main():
    for port in (18884, 18086, 15001):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Test port {port} is occupied; refusing to reuse it')
    folder = Path(tempfile.mkdtemp(prefix='issue1-', dir=ROOT/'.runtime'))
    native = ROOT/'.tools/native'
    broker_dir = native/'mosquitto'
    processes, logs = [], []

    def start(name, args, env=None):
        log = (folder/f'{name}.log').open('w')
        logs.append(log)
        process = subprocess.Popen([str(a) for a in args], cwd=ROOT, env=env,
                                   stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append(process)
        return process

    def publish(user, topic, message, retained=False, allowed=True):
        args = [str(broker_dir/'mosquitto_pub.exe'), '-h','127.0.0.1','-p','18884',
                '-V','mqttv5','-q','1','-u',user,'-P',PASSWORD,'-t',topic,'-m',json.dumps(message)]
        if retained:
            args.append('-r')
        result = subprocess.run(args, capture_output=True, timeout=8)
        denied = b'not authorized' in result.stderr.lower() or result.returncode != 0
        assert (not denied) == allowed, f'ACL mismatch for {user} on {topic}: {result.stderr.decode(errors="replace")}'

    try:
        passwd = folder/'passwd'
        users = ['parking-gateway','parking-backend','parking-teammate','parking-test-publisher','parking-test-backend']
        entries = []
        for index, user in enumerate(users):
            user_file = folder/f'passwd-{index}'
            args = [str(broker_dir/'mosquitto_passwd.exe'), '-b', '-c']
            subprocess.run(args+[str(user_file),user,PASSWORD], check=True, capture_output=True)
            # Windows mosquitto_passwd can install a domain-only ACL. Restore
            # inheritance on this newly generated synthetic credential file.
            if os.name == 'nt':
                subprocess.run(['icacls', str(user_file), '/reset'], check=True, capture_output=True)
            entries.append(user_file.read_text())
        passwd.write_text(''.join(entries))
        # Namespace the candidate ACL so even isolated tests avoid production topics.
        acl = folder/'acl'
        acl.write_text((ROOT/'infra/mosquitto/acl.proposed').read_text().replace('parking/', 'issue1/parking/'))
        conf = folder/'mosquitto.conf'
        conf.write_text(f'listener 18884 127.0.0.1\nallow_anonymous false\npassword_file {passwd.as_posix()}\nacl_file {acl.as_posix()}\n')
        broker = start('broker', [broker_dir/'mosquitto.exe','-c',conf])
        def broker_ready():
            with socket.create_connection(('127.0.0.1',18884), timeout=1):
                return True
        wait(broker_ready)
        for user, topic in [('parking-gateway','node/telemetry'),('parking-gateway','gateway/telemetry'),
                            ('parking-teammate','camera/result')]:
            publish(user,'issue1/parking/'+topic,{'synthetic':True})
        for user, topic in [('parking-gateway','camera/result'),('parking-teammate','node/telemetry'),
                            ('parking-backend','node/telemetry'),('parking-test-publisher','node/telemetry'),
                            ('parking-test-backend','test/node/telemetry')]:
            publish(user,'issue1/parking/'+topic,{},allowed=False)
        print('PASS isolated candidate ACL publish allow/deny matrix', flush=True)

        for user, topic, publisher, allowed in [
                ('parking-backend','node/telemetry','parking-gateway',True),
                ('parking-gateway','node/telemetry','parking-gateway',False),
                ('parking-test-backend','test/node/telemetry','parking-test-publisher',True),
                ('parking-test-backend','node/telemetry','parking-gateway',False)]:
            subscriber = subprocess.Popen([str(broker_dir/'mosquitto_sub.exe'),'-h','127.0.0.1',
                '-p','18884','-V','mqttv5','-u',user,'-P',PASSWORD,'-t','issue1/parking/'+topic,
                '-C','1','-W','2'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW)
            processes.append(subscriber)
            time.sleep(.3)
            publish(publisher,'issue1/parking/'+topic,{'synthetic':True})
            try:
                output, _ = subscriber.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                subscriber.terminate()
                output, _ = subscriber.communicate(timeout=5)
            assert bool(output) == allowed, 'ACL read permission mismatch'
        print('PASS isolated candidate ACL read allow/deny matrix',flush=True)

        influx_env = dict(os.environ, INFLUXD_HTTP_BIND_ADDRESS='127.0.0.1:18086',
                          INFLUXD_BOLT_PATH=str(folder/'influx.bolt'), INFLUXD_ENGINE_PATH=str(folder/'engine'),
                          INFLUXD_REPORTING_DISABLED='true')
        database = start('influx', [native/'influxdb/influxd.exe'], influx_env)
        wait(lambda: http(18086,'/health').get('status') == 'pass')
        wait(lambda: http(18086,'/api/v2/setup',dict(username='synthetic',password=PASSWORD,org='parking',
                                      bucket='sensor_test',token=TOKEN,retentionPeriodSeconds=604800)))
        # Historical synthetic fixtures span independent windows; startup's
        # invalid status deliberately makes its mixed coarse window a gap.
        with InfluxDBClient(url='http://127.0.0.1:18086',token=TOKEN,org='parking') as fixture_db:
            with fixture_db.write_api(write_options=SYNCHRONOUS) as fixture_writer:
                fixture_writer.write(bucket='sensor_test',record=[
                    Point('parking_node').tag('source','uno').tag('kind','status').tag('data_origin','synthetic')
                    .field('a1_distance_cm',30.).field('a1_distance_cm_valid',True)
                    .time(datetime.now(timezone.utc)-timedelta(seconds=seconds))
                    for seconds in (3600,259200)])
                gap_base = (int(time.time()-7200)//144)*144
                fixture_writer.write(bucket='sensor_test',record=[
                    Point('parking_node').tag('source','uno').tag('kind','status').tag('data_origin','synthetic')
                    .field('a1_distance_cm',30.).field('a1_distance_cm_valid',True)
                    .time(datetime.fromtimestamp(gap_base+offset,timezone.utc)) for offset in (5,20)])
        stop_file = folder/'stop'
        backend_env = dict(os.environ, MQTT_HOST='127.0.0.1',MQTT_PORT='18884',
                           MQTT_USERNAME='parking-test-backend',MQTT_PASSWORD=PASSWORD,
                           MQTT_TOPIC_PREFIX='issue1/parking/test',MQTT_CLIENT_ID='issue1-isolated',
                           INFLUX_URL='http://127.0.0.1:18086',INFLUX_TOKEN=TOKEN,INFLUX_ORG='parking',
                           INFLUX_BUCKET='sensor_test',DATA_ORIGIN='synthetic',DASHBOARD_PORT='15001',
                           DASHBOARD_USERNAME='synthetic',DASHBOARD_PASSWORD=PASSWORD,BACKEND_STOP_FILE=str(stop_file))
        backend = start('backend',[sys.executable,ROOT/'backend/main.py'],backend_env)
        auth = 'Basic '+base64.b64encode(f'synthetic:{PASSWORD}'.encode()).decode()
        def latest():return http(15001,'/api/latest',auth=auth)
        wait(lambda: latest()['mqtt_connected'] and latest()['storage_connected'])
        uno = dict(node='uno',a1_distance_cm=30.,a1_occupied=False,m1_distance_cm=None,m1_occupied=None,
                   vibration=None,vibration_count=None,vibration_status='not_installed')
        publish('parking-test-publisher','issue1/parking/test/node/telemetry',uno)
        wait(lambda: latest()['sources']['uno']['a1_allocation_eligible'])
        time.sleep(2)
        for minutes in (5,1440,10080):
            data=http(15001,f'/api/history?minutes={minutes}',auth=auth)
            assert len(data['points']) <= 601
            assert any(p['value'] == 30 for p in data['points']), f'real Flux query lost valid telemetry at {minutes} minutes'
            assert any(p['value'] is None for p in data['points']), 'outage gaps missing'
            if minutes == 1440:
                gap_time = datetime.fromtimestamp(gap_base+144,timezone.utc).isoformat()
                assert next(p['value'] for p in data['points'] if p['time'] == gap_time) is None, 'internal outage was averaged away'
        print('PASS real Influx Flux history: 5m/24h/7d, values and empty gaps',flush=True)
        publish('parking-test-publisher','issue1/parking/test/node/telemetry',dict(uno,a1_distance_cm=10))
        wait(lambda: latest()['rejected_messages'] >= 1 and not latest()['sources']['uno']['a1_allocation_eligible'])
        publish('parking-test-publisher','issue1/parking/test/node/telemetry',uno,retained=True)
        # Restart our test backend so the retained value arrives on subscription.
        stop_file.write_text('test restart');backend.wait(timeout=15);stop_file.unlink()
        backend=start('backend-restarted',[sys.executable,ROOT/'backend/main.py'],backend_env)
        wait(lambda: latest()['rejected_messages'] >= 1)
        assert not latest()['sources']['uno']['a1_allocation_eligible']
        publish('parking-test-publisher','issue1/parking/test/node/telemetry',uno)
        wait(lambda: latest()['sources']['uno']['a1_allocation_eligible'])
        wait(lambda: not latest()['sources']['uno']['fresh'],seconds=15)
        print('PASS inconsistent telemetry, retained on restart, recovery and 10s freshness',flush=True)
        database.terminate();database.wait(timeout=10)
        wait(lambda: not latest()['storage_connected'])
        publish('parking-test-publisher','issue1/parking/test/node/telemetry',uno)
        wait(lambda: latest()['sources']['uno']['a1_allocation_eligible'])
        wait(lambda: latest()['storage_write_failures'] > 0)
        assert latest()['storage_backlog'] > 0
        database = start('influx-restarted',[native/'influxdb/influxd.exe'],influx_env)
        wait(lambda: latest()['storage_connected'] and latest()['storage_backlog'] == 0,seconds=40)
        print('PASS real database outage/restart: ingestion remains live, backlog drains',flush=True)
        broker.terminate();broker.wait(timeout=10)
        wait(lambda: not latest()['mqtt_connected'])
        assert not latest()['sources']['uno']['a1_allocation_eligible']
        broker = start('broker-restarted',[broker_dir/'mosquitto.exe','-c',conf])
        wait(lambda: latest()['mqtt_connected'])
        assert not latest()['sources']['uno']['a1_allocation_eligible']
        publish('parking-test-publisher','issue1/parking/test/node/telemetry',uno)
        wait(lambda: latest()['sources']['uno']['a1_allocation_eligible'])
        print('PASS real broker outage/reconnect: fail closed until new telemetry',flush=True)
        if '--gate' in sys.argv:
            # Reuse the private native server/ACLs; no production credentials or topics.
            import uuid
            sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'backend/tests'))
            from test_gate_model import GATE
            from test_model import GATEWAY
            from gate_model import identity
            boot=uuid.uuid4().hex
            gate=dict(GATE,boot_id=boot,event_id=identity(boot,'e',1))
            stop_file.write_text('gate schema test transition');backend.wait(timeout=15);stop_file.unlink()
            gate_env=dict(backend_env,GATE_SCHEMA_ROUTING='isolated',
                          GATE_EVENT_LEDGER_PATH=str(folder/'gate-events.sqlite3'))
            backend=start('gate-backend',[sys.executable,ROOT/'backend/main.py'],gate_env)
            wait(lambda:latest()['mqtt_connected'] and latest()['storage_connected'])
            assert latest()['cloud']['enabled'] is False
            publish('parking-test-publisher','issue1/parking/test/gate/telemetry',gate)
            wait(lambda:latest()['sources']['gate']['u1_distance_cm_valid'])
            publish('parking-test-publisher','issue1/parking/test/gateway/telemetry',GATEWAY)
            wait(lambda:latest()['sources']['esp32']['temperature_c_valid'])
            # Legacy occupancy remains separate and cannot become gate availability.
            publish('parking-test-publisher','issue1/parking/test/node/telemetry',uno)
            assert latest()['sources']['gate']['event_id']==gate['event_id']
            gate.update(uptime_ms=2000,u1_distance_cm=10,u1_state='detected',gate_sim_state='open_wait',
                        arrival_count=1,arrival_id=identity(boot,'a',1),event_seq=2,event_id=identity(boot,'e',2),last_event='arrival')
            publish('parking-test-publisher','issue1/parking/test/gate/telemetry',gate)
            wait(lambda:latest()['sources']['gate']['gate_sim_state']=='open_wait')
            def events():return http(15001,'/api/gate/events',auth=auth)['events']
            arrival=next(event for event in events() if event['event_id']==gate['event_id'])
            publish('parking-test-publisher','issue1/parking/test/gate/telemetry',dict(gate,servo_enabled=True))
            wait(lambda:not latest()['sources']['gate']['payload_valid'])
            gate['uptime_ms']=2100
            publish('parking-test-publisher','issue1/parking/test/gate/telemetry',gate)
            wait(lambda:latest()['sources']['gate']['payload_valid'])
            publish('parking-test-publisher','issue1/parking/test/gate/telemetry',gate,retained=True)
            stop_file.write_text('gate restart');backend.wait(timeout=15);stop_file.unlink()
            backend=start('gate-restarted',[sys.executable,ROOT/'backend/main.py'],gate_env)
            wait(lambda:latest()['rejected_messages']>0)
            assert not latest()['sources']['gate']['payload_valid']
            gate['uptime_ms']=2200
            publish('parking-test-publisher','issue1/parking/test/gate/telemetry',gate)
            wait(lambda:latest()['sources']['gate']['payload_valid'])
            assert next(event for event in events() if event['event_id']==gate['event_id'])['received_at_utc']==arrival['received_at_utc']
            gate.update(uptime_ms=2500,u1_distance_cm=40,u1_state='clear',u2_distance_cm=10,u2_state='detected',
                        gate_sim_state='passing',event_seq=3,event_id=identity(boot,'e',3),last_event='passage_detected')
            publish('parking-test-publisher','issue1/parking/test/gate/telemetry',gate)
            wait(lambda:latest()['sources']['gate']['gate_sim_state']=='passing')
            gate.update(uptime_ms=3500,u2_distance_cm=40,u2_state='clear',gate_sim_state='closing',event_seq=4,
                        event_id=identity(boot,'e',4),last_event='clearance_confirmed')
            publish('parking-test-publisher','issue1/parking/test/gate/telemetry',gate)
            wait(lambda:latest()['sources']['gate']['gate_sim_state']=='closing')
            time.sleep(1)
            gate.update(uptime_ms=4500,gate_sim_state='closed',completed_count=1,passage_id=identity(boot,'p',1),
                        event_seq=5,event_id=identity(boot,'e',5),last_event='passage_completed')
            publish('parking-test-publisher','issue1/parking/test/gate/telemetry',gate)
            wait(lambda:latest()['sources']['gate']['completed_count']==1)
            time.sleep(2)
            for field in ('u1_distance_cm','u2_distance_cm','arrival_count','completed_count','vibration_transition_count'):
                history=http(15001,'/api/history?source=gate&field='+field+'&minutes=5',auth=auth)
                assert any(point['value'] is not None for point in history['points']), 'Gate Flux lost '+field
            assert len({event['event_id'] for event in events()})==len(events())
            database.terminate();database.wait(timeout=10)
            wait(lambda:not latest()['storage_connected'])
            gate['uptime_ms']=5000
            publish('parking-test-publisher','issue1/parking/test/gate/telemetry',gate)
            wait(lambda:latest()['sources']['gate']['payload_valid'])
            wait(lambda:latest()['storage_backlog']>0)
            database=start('gate-influx-restarted',[native/'influxdb/influxd.exe'],influx_env)
            wait(lambda:latest()['storage_connected'] and latest()['storage_backlog']==0,seconds=40)
            print('PASS gate v2 private MQTT/Flux: strict servo rejection, legacy separation, environment, retained/restart, original event identity, U1/U2/counter history and database recovery',flush=True)

    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        for log in logs:log.close()


if __name__ == '__main__':
    main()
