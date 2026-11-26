"""Read-only provider usage receipt; no credentials, organization IDs or raw CSV logged."""
import csv
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from cloud_storage import CloudClient, CloudError, load_config


def summarize(raw):
    headers = None
    records = []
    for row in csv.reader(io.StringIO(raw.decode('utf-8-sig'))):
        if '_value' in row:
            headers = row
        elif headers and row and not row[0].startswith('#') and len(row) == len(headers):
            record = dict(zip(headers,row))
            if record.get('_measurement') not in ('http_request','query_count','storage_usage_bucket_bytes'):
                continue
            number = Decimal(record['_value'])
            if not number.is_finite() or number < 0 or number != int(number):
                raise ValueError('Invalid usage count')
            record['_value'] = int(number)
            records.append(record)
    if not records:
        raise ValueError('No recognized usage metrics')
    periods = {(record['_start'],record['_stop']) for record in records}
    if len(periods) != 1:
        raise ValueError('Inconsistent usage bounds')
    start, stop = periods.pop()
    latest_storage = {}
    for record in records:
        if record['_measurement'] == 'storage_usage_bucket_bytes' and record['_field'] == 'gauge':
            bucket = record['bucket_id']
            if bucket not in latest_storage or record['_time'] > latest_storage[bucket]['_time']:
                latest_storage[bucket] = record
    return {'period_start_utc':start,'period_stop_utc':stop,
            'meter_timestamps_utc':sorted({record['_time'] for record in records}),
            'successful_write_request_bytes':sum(record['_value'] for record in records
                if record['_measurement'] == 'http_request' and record['_field'] == 'req_bytes'
                and record.get('endpoint') == '/api/v2/write' and record.get('status','').startswith('2')),
            'query_count':sum(record['_value'] for record in records if record['_measurement'] == 'query_count'),
            'http_response_bytes_including_errors':sum(record['_value'] for record in records
                if record['_measurement'] == 'http_request' and record['_field'] == 'resp_bytes'),
            'latest_reported_storage_bytes':sum(record['_value'] for record in latest_storage.values()),
            'scope':'organization-wide provider metrics; aggregated/possibly delayed; not an exact rolling five-minute limit test'}


def main():
    client = CloudClient(load_config())
    buckets = json.loads(client.request('/api/v2/buckets',{'limit':100},'read_token'))['buckets']
    if len(buckets) != 1 or buckets[0]['name'] != client.config['bucket']:
        raise ValueError('Expected intended single-bucket read scope')
    raw = client.request('/api/v2/orgs/'+buckets[0]['orgID']+'/usage',
                         {'start':'-24h','raw':'false'},'read_token')
    receipt = dict(summarize(raw), verified_at_utc=datetime.now(timezone.utc).isoformat())
    (ROOT/'.runtime').mkdir(exist_ok=True)
    (ROOT/'.runtime/cloud-provider-usage-verification.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt,indent=2))


if __name__ == '__main__':
    try:
        main()
    except (CloudError, OSError, ValueError, KeyError, TypeError, ArithmeticError):
        raise SystemExit('Provider usage unavailable or invalid; no usage acceptance or secret output.') from None
