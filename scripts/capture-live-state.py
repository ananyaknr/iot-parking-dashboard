"""Read-only API evidence for user-confirmed physical test positions."""
import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--label', required=True)
    p.add_argument('--seconds', type=int, default=10, choices=range(5, 61))
    p.add_argument('--expected-occupied', choices=['true', 'false'])
    args = p.parse_args()
    values = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
                  if line and not line.startswith('#') and '=' in line)
    user = values.get('DASHBOARD_USERNAME', values.get('GRAFANA_USERNAME', 'parking-admin'))
    password = values.get('DASHBOARD_PASSWORD', values.get('GRAFANA_PASSWORD', ''))
    auth = base64.b64encode(f'{user}:{password}'.encode()).decode()
    samples = []
    for _ in range(args.seconds):
        req = Request('http://127.0.0.1:5000/api/latest', headers={'Authorization': 'Basic ' + auth})
        with urlopen(req, timeout=5) as response:
            samples.append(json.load(response))
        time.sleep(1)
    def ranges(source, fields):
        result = {}
        for field in fields:
            observed = [s['sources'][source][field] for s in samples
                        if s['sources'][source].get('fresh') and
                        s['sources'][source].get(field + '_valid') and
                        field in s['sources'][source]]
            result[field] = {'valid_count': len(observed), 'min': min(observed) if observed else None,
                             'max': max(observed) if observed else None}
        return result
    summary = {'label': args.label, 'data_origin': 'hardware', 'api_samples': len(samples),
               'uno': ranges('uno', ['a1_distance_cm']),
               'esp32': ranges('esp32', ['temperature_c', 'humidity_pct', 'light_raw', 'gas_raw']),
               'all_sources_fresh': all(s['sources'][source]['fresh'] for s in samples for source in ['uno', 'esp32']),
               'fresh_sample_counts': {source: sum(s['sources'][source]['fresh'] for s in samples)
                                       for source in ['uno', 'esp32']},
               'a1_state_counts': dict(Counter(s['sources']['uno']['a1_state'] for s in samples)),
               'a1_allocation_eligible_count': sum(s['sources']['uno']['a1_allocation_eligible'] for s in samples),
               'm1_excluded': all(not s['sources']['uno']['m1_allocation_eligible'] and
                                  not s['sources']['uno']['m1_installed'] for s in samples)}
    if args.expected_occupied is not None:
        expected = args.expected_occupied == 'true'
        summary['expected_a1_occupied'] = expected
        summary['occupied_check_pass'] = all(s['sources']['uno'].get('fresh') and
            s['sources']['uno'].get('a1_occupied_valid') and
            s['sources']['uno'].get('a1_occupied') is expected for s in samples)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = ROOT / 'docs/runtime-logs' / ('physical-' + stamp)
    folder.mkdir(parents=True)
    (folder / 'evidence.json').write_text(json.dumps({'summary': summary, 'samples': samples}, indent=2))
    summary['folder'] = str(folder.relative_to(ROOT))
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
