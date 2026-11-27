"""Read-only connection receipt: streams, fresh snapshots and concurrent sensor reads."""
import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


async def check(url):
    config = dotenv_values(ROOT / '.env')
    username = config.get('DASHBOARD_USERNAME', config.get('GRAFANA_USERNAME', 'parking-admin'))
    password = config.get('DASHBOARD_PASSWORD', config.get('GRAFANA_PASSWORD', ''))
    auth = (username, password) if config.get('DASHBOARD_AUTH_REQUIRED', 'yes') != 'no' else None
    receipt = {'occurred_at': datetime.now(timezone.utc).isoformat(),
               'parking_commits': 0, 'mqtt_commands': 0, 'images_saved': False}
    async with httpx.AsyncClient(base_url=url, auth=auth, trust_env=False, timeout=20) as client:
        async with AsyncExitStack() as stack:
            async def stream(lane):
                response = await stack.enter_async_context(client.stream('GET', '/api/camera/stream', params={'camera': lane, 't': 'check'}))
                response.raise_for_status()
                if not response.headers.get('content-type', '').startswith('multipart/x-mixed-replace'):
                    raise ValueError('MJPEG required')
                iterator = response.aiter_bytes()
                data = bytearray()
                while b'\xff\xd8' not in data and len(data) < 1024*1024:
                    data.extend(await anext(iterator))
                return iterator, b'\xff\xd8' in data
            frames = await asyncio.gather(stream('entrance'), stream('exit'))
            if not all(frame[1] for frame in frames):
                raise ValueError('Both streams must contain JPEG data')
            receipt['streams'] = {lane: {'http': 200, 'jpeg': frames[i][1]} for i, lane in enumerate(('entrance', 'exit'))}
            # Keep both streams connected while querying Flask and the parking API.
            started = time.monotonic()
            for path in ('/', '/api/latest', '/api/history?source=esp32&field=temperature_c&minutes=1',
                         '/api/parking/status', '/api/parking/history?limit=1', '/api/integration/readiness'):
                r = await client.get(path)
                r.raise_for_status()
                receipt.setdefault('reads_with_two_streams', {})[path] = r.status_code
                if path == '/':
                    receipt['merged_dashboard'] = 'data-view="gate"' in r.text and 'data-simulator-commit="no"' in r.text
                    if not receipt['merged_dashboard']:
                        raise ValueError('Merged dashboard or safe simulator setting missing')
                if path == '/api/integration/readiness':
                    receipt['readiness'] = r.json()
                if path == '/api/parking/status':
                    receipt['capacity'] = r.json().get('capacity')
            for lane in ('entrance', 'exit'):
                r = await client.get('/api/camera/frame', params={'camera': lane})
                r.raise_for_status()
                receipt.setdefault('snapshots', {})[lane] = {
                    'jpeg': r.content.startswith(b'\xff\xd8'), 'role': r.headers.get('x-camera-role'), 'http': r.status_code}
                if not r.content.startswith(b'\xff\xd8') or r.headers.get('x-camera-role') != lane:
                    raise ValueError('Fresh role-specific JPEG required')
            receipt['concurrent_reads_seconds'] = round(time.monotonic() - started, 2)
        for path in ('/parking/commit', '/api/parking/commit', '/parking/sensors', '/api/integration/recognition'):
            r = await client.post(path, json={})
            if r.status_code != 405:
                raise ValueError('Write route exposed')
        receipt['write_routes_blocked'] = True
        r = await client.post('/api/parking/analyze', data={'camera': 'exit'}, headers={'Origin': url.rstrip('/')})
        if r.status_code != 400:
            raise ValueError('Analysis validation path unavailable')
        receipt['analysis_route_validates_missing_image'] = True
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8081')
    parser.add_argument('--output', type=Path, default=ROOT / '.runtime/unified-readiness.json')
    args = parser.parse_args()
    try:
        receipt = asyncio.run(check(args.url))
    except httpx.HTTPStatusError as exc:
        raise SystemExit(f'Connection check blocked: HTTP {exc.response.status_code} at {exc.request.url.path}') from None
    except Exception as exc:
        raise SystemExit('Connection check blocked: '+type(exc).__name__) from None
    args.output.write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(receipt))
