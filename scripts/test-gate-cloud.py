"""Real provider gate-v2 acceptance, synthetic fixture in the isolated TEST bucket only."""
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
from cloud_storage import CloudClient,CloudError,load_config,telemetry_line
from gate_model import identity
from test_gate_model import GATE


def main():
    config=load_config(ROOT/'.secrets/cloud-test.json',testing=True)
    assert config['bucket']=='parking_sensor_test'
    client=CloudClient(config);boot=uuid.uuid4().hex
    message=dict(GATE,boot_id=boot,event_id=identity(boot,'e',1),u1_distance_cm=27.5,u2_distance_cm=35.0)
    stamp=datetime.now(timezone.utc);delta=stamp-datetime(1970,1,1,tzinfo=timezone.utc)
    ns=(delta.days*86400+delta.seconds)*1000000000+delta.microseconds*1000
    line=telemetry_line('gate',message,stamp,data_origin='synthetic')
    print('PHASE isolated duplicate write',flush=True)
    client.write([line]);client.write([line])
    statement=('SELECT count("sample_present") AS samples, mean("u1_distance_cm") AS value '
               'FROM "parking_gate_v2" WHERE time = '+str(ns)+'ns')
    print('PHASE exact timestamp query',flush=True)
    deadline=time.monotonic()+90
    while True:
        response=json.loads(client.request('/query',{'db':config['bucket'],'epoch':'ns','q':statement},'read_token'))
        if response.get('error') or any(item.get('error') for item in response.get('results',[])):
            raise ValueError('Gate cloud query error')
        records=[dict(zip(series['columns'],row)) for item in response.get('results',[])
                 for series in item.get('series',[]) for row in series.get('values',[])]
        if any(record.get('samples')==1 and record.get('value')==27.5 for record in records):break
        if time.monotonic()>=deadline:raise ValueError('Gate exact point not visible')
        time.sleep(3)
    # Use a completed second, so the original nanosecond point falls inside history bounds.
    stop=datetime.now(timezone.utc)+timedelta(seconds=2)
    print('PHASE distance history',flush=True)
    distance=client.history('gate','u1_distance_cm',5,stop=stop)
    print('PHASE counter history',flush=True)
    counter=client.history('gate','arrival_count',5,stop=stop)
    if not any(point['value']==27.5 for point in distance['points']):raise ValueError('Distance history missing')
    if not any(point['value']==0 for point in counter['points']):raise ValueError('Counter history missing')
    receipt={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'bucket':config['bucket'],
             'data_origin':'synthetic','measurement':'parking_gate_v2','sample_timestamp_ns':ns,
             'logical_point_count':1,'distance_cm':27.5,'arrival_counter':0,
             'history':'PASS','physical_actuation':False,'transfer':client.usage()}
    (ROOT/'.runtime/gate-cloud-verification.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print('PASS isolated real cloud gate-v2 write/read, identical retry and distance/counter history')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    try:main()
    except CloudError as exc:
        raise SystemExit('Gate cloud verification failed; safe error code: '+str(exc.code)) from None
    except (ValueError,OSError,KeyError,TypeError,AssertionError):
        raise SystemExit('Gate cloud verification did not pass; no credentials/response body printed.') from None
