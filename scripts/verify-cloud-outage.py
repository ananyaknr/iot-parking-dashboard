"""Staged acceptance with actual hardware. User keeps LAN up and toggles hotspot internet.

Run baseline, offline-before-restart, offline-after-restart, then recovered.
Only recovered deliberately retries one existing hardware point at its original timestamp.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from cloud_storage import CloudClient, load_config, CloudError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['baseline','offline-before-restart','offline-after-restart','recovered'])
    parser.add_argument('--controlled-https-failure', action='store_true',
                        help='Separate transport-fault evidence; does not establish physical internet loss')
    args = parser.parse_args()
    prefix = 'cloud-transport' if args.controlled_https_failure else 'cloud-outage'
    if args.controlled_https_failure and args.phase.startswith('offline'):
        assert os.environ.get('HTTPS_PROXY') == 'http://127.0.0.1:9', 'Controlled proxy environment required'
    env = dict(line.split('=',1) for line in (ROOT/'.env').read_text().splitlines()
               if line and not line.startswith('#') and '=' in line)
    auth = base64.b64encode((env.get('DASHBOARD_USERNAME',env.get('GRAFANA_USERNAME','parking-admin'))
                            +':'+env.get('DASHBOARD_PASSWORD',env.get('GRAFANA_PASSWORD',''))).encode()).decode()
    opener = build_opener(ProxyHandler({}))
    def api(path):
        with opener.open(Request('http://127.0.0.1:5000'+path,
                                 headers={'Authorization':'Basic '+auth}),timeout=10) as response:
            return json.load(response)
    client = CloudClient(load_config())
    probe_opener = build_opener() if args.controlled_https_failure else opener
    def internet(url):
        try:
            with probe_opener.open(url,timeout=6) as response:
                return True
        except HTTPError as error:
            error.close()
            return True  # An HTTP error still proves external HTTPS connectivity.
        except URLError as error:
            if isinstance(error.reason, ssl.SSLError):
                raise  # A TLS validation problem is not proof of internet loss.
            return False
        except ssl.SSLError:
            raise
        except OSError:
            return False
    connected = {'cloud_https':internet(client.config['url']+'/health'),
                 'independent_https':internet('https://api.github.com/')}
    latest = api('/api/latest')
    assert latest['data_origin'] == 'hardware' and latest['cloud']['enabled'], 'Hardware cloud export required'
    assert latest['mqtt_connected'] and latest['storage_connected'], 'Local broker/database must be connected'
    assert all(latest['sources'][source]['fresh'] and latest['sources'][source]['payload_valid']
               for source in ('uno','esp32')), 'Both actual hardware feeds must be fresh'
    history = api('/api/history?source=esp32&field=light_raw&minutes=5')
    assert any(point['value'] is not None for point in history['points']), 'Local history unavailable'
    outbox = ROOT/'.runtime/cloud-outbox.sqlite3'
    with sqlite3.connect(outbox.as_uri()+'?mode=ro',uri=True,timeout=5) as database:
        rows = database.execute('SELECT line FROM pending ORDER BY id').fetchall()
    lines = [row[0] for row in rows]
    hashes = [hashlib.sha256(line.encode()).hexdigest() for line in lines]
    files = [outbox,Path(str(outbox)+'-journal'),Path(str(outbox)+'-wal'),Path(str(outbox)+'-shm')]
    receipt = {'verified_at_utc':datetime.now(timezone.utc).isoformat(),'phase':args.phase,
               'outage_type':'controlled_https_proxy_failure' if args.controlled_https_failure else 'physical_internet_outage',
               'backend_process':json.loads((ROOT/'.runtime/processes.json').read_text(encoding='utf-8-sig'))['backend'],
               'connectivity':connected,'cloud':latest['cloud'],'pending_sqlite_rows':len(lines),
               'pending_hashes':hashes,'outbox_file_bytes':{file.name:file.stat().st_size for file in files if file.exists()},
               'drive_free_bytes':shutil.disk_usage(ROOT).free,'local_history':'PASS',
               'hardware_received_at':{source:latest['sources'][source]['last_received_utc'] for source in ('uno','esp32')}}
    receipt_path = ROOT/('.runtime/'+prefix+'-'+args.phase+'.json')
    if args.phase.startswith('offline'):
        assert not any(connected.values()), 'Both external HTTPS probes must fail during actual internet outage'
        assert latest['cloud']['error'] == 'network_error', 'Wait for actual cloud network failure'
        assert len(lines) >= 5, 'Wait for durable hardware buffering'
        if args.phase == 'offline-before-restart':
            # Private local evidence contains actual sensor lines only, never credentials.
            (ROOT/('.runtime/'+prefix+'-hardware-lines.json')).write_text(json.dumps(lines))
        else:
            before = json.loads((ROOT/('.runtime/'+prefix+'-offline-before-restart.json')).read_text())
            assert receipt['backend_process']['started'] != before['backend_process']['started'], 'Backend was not restarted'
            assert set(before['pending_hashes']).issubset(hashes), 'Committed rows did not survive restart'
            receipt['committed_rows_survived_restart'] = len(before['pending_hashes'])
    elif args.phase == 'baseline':
        assert all(connected.values()), 'Online HTTPS baseline failed: '+json.dumps(connected)
        assert not latest['cloud']['error'] and latest['cloud']['uploaded'] > 0, 'Cloud acknowledgement required'
    else:
        assert all(connected.values()) and not latest['cloud']['error']
        saved = json.loads((ROOT/('.runtime/'+prefix+'-hardware-lines.json')).read_text())
        assert not set(hashlib.sha256(line.encode()).hexdigest() for line in saved).intersection(hashes), 'Backlog not yet drained'
        assert latest['cloud']['uploaded'] >= len(saved), 'No recovery upload acknowledgement'
        assert latest['cloud']['dropped'] == 0, 'Recovery dropped records'
        checks = []
        assert saved and all(line.startswith(('parking_node,source=uno,data_origin=hardware ',
                                              'parking_gateway,source=esp32,data_origin=hardware ')) for line in saved)
        selected = []
        for measurement in ('parking_node','parking_gateway'):
            matching = [line for line in saved if line.startswith(measurement+',')]
            if matching:
                selected.extend(dict.fromkeys([matching[0],matching[-1]]))
        # Retry an existing hardware identity, never invent a production reading.
        client.write([saved[0]])
        for line in dict.fromkeys([saved[0]]+selected):
            identity, _, stamp = line.split(' ',2)
            assert ',data_origin=hardware' in identity
            measurement = identity.split(',',1)[0]
            statement = 'SELECT count("sample_present") AS samples FROM "'+measurement+'" WHERE time = '+stamp+'ns'
            response = json.loads(client.request('/query',{'db':client.config['bucket'],'epoch':'ns','q':statement},'read_token'))
            assert not response.get('error') and not any(item.get('error') for item in response.get('results',[]))
            counts = [dict(zip(series['columns'],row)).get('samples')
                      for item in response.get('results',[]) for series in item.get('series',[]) for row in series.get('values',[])]
            assert counts == [1], 'Expected exactly one logical original hardware point'
            checks.append({'timestamp_ns':stamp,'measurement':measurement,'logical_point_count':1})
        receipt['recovered_original_points'] = checks
        receipt['original_backlog_rows_acknowledged'] = len(saved)
        receipt['existing_hardware_duplicate_retry'] = 'PASS'
        receipt['verification_transfer'] = client.usage()
    receipt_path.write_text(json.dumps(receipt,indent=2))
    print('PASS actual hardware '+receipt['outage_type']+' stage: '+args.phase)
    print(json.dumps({key:value for key,value in receipt.items() if key != 'pending_hashes'},indent=2))


if __name__ == '__main__':
    try:
        main()
    except AssertionError as error:
        raise SystemExit('Outage stage has not passed: '+str(error)) from None
    except (OSError, ValueError, KeyError, TypeError, CloudError, sqlite3.Error):
        raise SystemExit('Outage stage has not passed; verify LAN/fresh hardware, internet state, backlog and prior stages. No secrets printed.') from None
