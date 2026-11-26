"""Read-only acceptance of actual hardware cloud samples; never publishes data."""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from cloud_storage import CloudClient, CloudError, load_config, MEASUREMENTS, RANGES


def main():
    values = dict(line.split('=',1) for line in (ROOT/'.env').read_text().splitlines()
                  if line and not line.startswith('#') and '=' in line)
    username = values.get('DASHBOARD_USERNAME',values.get('GRAFANA_USERNAME',''))
    password = values.get('DASHBOARD_PASSWORD',values.get('GRAFANA_PASSWORD',''))
    authorization = 'Basic '+base64.b64encode((username+':'+password).encode()).decode()
    opener = build_opener(ProxyHandler({}))
    def api(path):
        request = Request('http://127.0.0.1:5000'+path,headers={'Authorization':authorization})
        with opener.open(request,timeout=10) as response:
            return json.load(response)
    latest = api('/api/latest')
    if latest.get('data_origin') != 'hardware' or not latest.get('cloud',{}).get('enabled'):
        raise SystemExit('Hardware cloud export is not enabled; no PASS claimed.')
    deadline = time.monotonic()+90
    while not latest['cloud'].get('uploaded'):
        if latest['cloud'].get('error'):
            raise SystemExit('Production uploader reports '+str(latest['cloud']['error'])+'; no PASS claimed.')
        if time.monotonic() >= deadline:
            raise SystemExit('No production upload acknowledgement observed; no PASS claimed.')
        time.sleep(1)
        latest = api('/api/latest')
    client = CloudClient(load_config())
    checks = []
    for source, measurement in MEASUREMENTS.items():
        view = latest['sources'][source]
        if not view.get('fresh') or not view.get('payload_valid') or not view.get('last_received_utc'):
            raise SystemExit(source+' has no fresh valid hardware sample; no PASS claimed.')
        stamp = datetime.fromisoformat(view['last_received_utc'])
        delta = stamp-datetime(1970,1,1,tzinfo=timezone.utc)
        ns = (delta.days*86400+delta.seconds)*1_000_000_000+delta.microseconds*1000
        fields = [field for field in RANGES[source] if view.get(field+'_valid')]
        expected = {field+'_valid':bool(view.get(field+'_valid')) for field in RANGES[source]}
        expected.update({field:view[field] for field in fields})
        statement = ('SELECT '+','.join('"'+field+'"' for field in expected)
                     +',"sample_present","source","data_origin" FROM "'+measurement+'" WHERE time = '+str(ns)+'ns')
        deadline = time.monotonic()+90
        matched = False
        while time.monotonic() < deadline:
            response = json.loads(client.request('/query',{'db':client.config['bucket'],'epoch':'ns','q':statement},'read_token'))
            if response.get('error') or any(item.get('error') for item in response.get('results',[])):
                raise SystemExit('Production query error; no response body or credentials printed.')
            for item in response.get('results',[]):
                for series in item.get('series',[]):
                    for row in series.get('values',[]):
                        record = dict(zip(series['columns'],row))
                        if (record.get('source') == source and record.get('data_origin') == 'hardware'
                                and record.get('sample_present') == 1
                                and all(record.get(field) == value for field,value in expected.items())):
                            matched = True
            if matched:break
            time.sleep(5)
        if not matched:
            raise SystemExit(source+' exact hardware timestamp/values not visible in cloud; no PASS claimed.')
        history_field = fields[0] if fields else next(iter(RANGES[source]))
        history = api('/api/cloud/history?source='+source+'&field='+history_field+'&minutes=5')
        if fields and not any(point['value'] is not None for point in history['points']):
            raise SystemExit(source+' cloud dashboard history contains only gaps; no PASS claimed.')
        checks.append({'source':source,'received_at_utc':view['last_received_utc'],
                       'matching_fields':list(expected),'cloud_origin':'hardware','history':'PASS',
                       'valid_numeric_measurements':bool(fields)})
    receipt = {'verified_at_utc':datetime.now(timezone.utc).isoformat(),
               'bucket':client.config['bucket'],'network_writes':0,'sources':checks,
               'backend_cloud':api('/api/latest')['cloud'],'verifier_transfer':client.usage()}
    (ROOT/'.runtime/cloud-production-verification.json').write_text(json.dumps(receipt,indent=2))
    print('PASS actual UNO/ESP32 cloud timestamp/value identity and dashboard history API.')
    print(json.dumps(receipt,indent=2))


if __name__ == '__main__':
    try:
        main()
    except CloudError as exc:
        raise SystemExit('Cloud production verification failed: '+str(exc.code)) from None
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit('Production verification configuration/response unavailable; no PASS claimed.') from None
