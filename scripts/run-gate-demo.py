"""Foreground isolated hardware demo; production services/data remain independent."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]

def main():
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',5001))==0:
            raise ValueError('Port 5001 occupied; refusing to start another backend')
    values=dict(line.split('=',1) for line in (ROOT/'.env').read_text().splitlines()
                if line and not line.startswith('#') and '=' in line)
    def api(method,path,data=None):
        req=Request('http://127.0.0.1:8086'+path,method=method,
                    data=None if data is None else json.dumps(data).encode(),
                    headers={'Authorization':'Token '+values['INFLUX_TOKEN'],'Content-Type':'application/json'})
        with urlopen(req,timeout=10) as response:return json.load(response)
    org=api('GET','/api/v2/orgs?org=parking')['orgs'][0]['id']
    buckets=api('GET','/api/v2/buckets?orgID='+org)['buckets']
    bucket=next(b for b in buckets if b['name']=='sensor_test')
    secret=ROOT/'.secrets/gate-local.json'
    if secret.exists():
        config=json.loads(secret.read_text())
        if config['bucket_id']!=bucket['id']:raise ValueError('Local test bucket identity changed')
        token=config['token']
    else:
        authorization=api('POST','/api/v2/authorizations',{'orgID':org,
            'description':'Isolated gate demo: sensor_test read/write only',
            'permissions':[{'action':action,'resource':{'type':'buckets','id':bucket['id'],'orgID':org}}
                           for action in ('read','write')]})
        token=authorization['token']
        secret.parent.mkdir(exist_ok=True)
        secret.write_text(json.dumps({'bucket_id':bucket['id'],'token':token}),encoding='utf-8')
    env=dict(os.environ,**values)
    env.update(INFLUX_URL='http://127.0.0.1:8086',INFLUX_ORG='parking',INFLUX_BUCKET='sensor_test',
               INFLUX_TOKEN=token,MQTT_HOST=values['MQTT_BIND_IP'],MQTT_TOPIC_PREFIX='parking/test',
               MQTT_CLIENT_ID='parking-gate-isolated-demo',DATA_ORIGIN='hardware_gate_sim',
               GATE_SCHEMA_ROUTING='isolated',GATE_PRODUCTION_APPROVED='no',GATE_MOCK_ADAPTER='no',
               GATE_ENVIRONMENT_FROM_PRODUCTION='yes',GATE_TEST_CLOUD='yes',PARKING_V1_ENABLED='yes',DASHBOARD_PORT='5001',
               BACKEND_STOP_FILE=str(ROOT/'.runtime/gate-demo.stop'))
    stop=ROOT/'.runtime/gate-demo.stop'
    if stop.exists():raise ValueError('Remove gate-demo.stop deliberately before restarting the demo')
    print('Isolated hardware simulation: http://127.0.0.1:5001; sensor_test only. No servo output.',flush=True)
    return subprocess.call([sys.executable,str(ROOT/'backend/main.py')],env=env,cwd=ROOT)

if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        raise SystemExit('Gate demo setup failed; no credentials or response bodies printed.') from None
