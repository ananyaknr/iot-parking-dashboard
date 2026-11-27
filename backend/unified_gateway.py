"""Loopback inspection gateway; session writes are blocked and streams bypass Flask."""
import asyncio
import base64
from contextlib import asynccontextmanager
import hmac
import re
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

SENSOR_READS = {'/', '/health', '/api/latest', '/api/history',
                '/api/cloud/history', '/api/gate/events'}
CAMERA_READS = {'/camera/stream', '/camera/snapshot', '/parking/status', '/parking/history'}
ALIASES = {'/api/camera/stream': '/camera/stream', '/api/camera/frame': '/camera/snapshot',
           '/api/parking/status': '/parking/status', '/api/parking/history': '/parking/history'}
MEDIA = re.compile(r'/parking/media/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
HEADERS = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
           'X-Frame-Options': 'DENY',
           'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data: blob:; frame-ancestors 'none'"}


def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
            or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise ValueError('Upstream must be a fixed http://127.0.0.1:PORT address')
    return value.rstrip('/')


def create_gateway(sensor_url, parking_url, *, username='', password='', auth_required=True,
                   transport=None):
    sensor_url, parking_url = local_url(sensor_url), local_url(parking_url)
    if auth_required and not password:
        raise ValueError('Dashboard password required when authentication is enabled')
    upstream_auth = 'Basic ' + base64.b64encode((username + ':' + password).encode()).decode()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, transport=transport,
                                    timeout=httpx.Timeout(15, connect=3, pool=3),
                                    limits=httpx.Limits(max_connections=16)) as regular:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, transport=transport,
                                        timeout=httpx.Timeout(15, connect=3, pool=3),
                                        limits=httpx.Limits(max_connections=8)) as streams:
                app.state.regular, app.state.streams = regular, streams
                yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware('http')
    async def guard(request, next_handler):
        # Bind is also loopback; reject remote clients if launched incorrectly.
        if (not request.client or request.client.host not in ('127.0.0.1', '::1')
                or request.url.hostname not in ('127.0.0.1', 'localhost', '::1')):
            return JSONResponse({'error': 'Loopback access only'}, 403)
        if auth_required:
            try:
                scheme, token = request.headers.get('authorization', '').split(' ', 1)
                user, secret = base64.b64decode(token, validate=True).decode().split(':', 1)
                valid = (scheme.lower() == 'basic' and hmac.compare_digest(user.encode(), username.encode())
                         and hmac.compare_digest(secret.encode(), password.encode()))
            except (ValueError, UnicodeError):
                valid = False
            if not valid:
                return Response(status_code=401, headers={**HEADERS, 'WWW-Authenticate': 'Basic realm="Parking monitor"'})
        if request.method not in ('GET', 'HEAD'):
            if request.method != 'POST' or request.url.path != '/api/parking/analyze':
                return JSONResponse({'error': 'Parking session writes are disabled'}, 405, headers=HEADERS)
            if (request.headers.get('origin') != str(request.base_url).rstrip('/')
                    or request.headers.get('sec-fetch-site', 'same-origin') not in ('same-origin', 'none')):
                return JSONResponse({'error': 'Same-origin analysis required'}, 403, headers=HEADERS)
        response = await next_handler(request)
        for key, value in HEADERS.items():
            response.headers[key] = value
        return response

    async def read_json(base, path, sensor=False):
        try:
            r = await app.state.regular.get(base + path,
                headers={'Authorization': upstream_auth} if sensor else {}, timeout=4)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            return None

    @app.get('/api/integration/readiness')
    async def readiness():
        sensors, parking = await asyncio.gather(read_json(sensor_url, '/api/latest', True),
                                               read_json(parking_url, '/parking/status'))
        gate = (sensors or {}).get('parking3', {})
        telemetry = gate.get('telemetry') or {}
        healthy = bool(sensors and sensors.get('mqtt_connected') and sensors.get('storage_connected'))
        return {'mode': 'inspection_simulation', 'sensor_service_ready': healthy,
                'parking_service_ready': bool(parking and parking.get('database') == 'ready'),
                'parking_storage': (parking or {}).get('storage', 'unknown'),
                'gate_mode': (parking or {}).get('gate_mode', 'unknown'),
                'gate_telemetry_fresh': gate.get('fresh', False),
                'gate_cycle_ready': bool(gate.get('fresh') and gate.get('clock_verified')
                                         and telemetry.get('phase') == 1
                                         and telemetry.get('u1_state') == telemetry.get('u2_state') == 'clear'
                                         and telemetry.get('servo_enabled') is False),
                'gate_phase_code': telemetry.get('phase'), 'gate_reason_code': telemetry.get('reason'),
                'environment_fresh': (sensors or {}).get('sources', {}).get('esp32', {}).get('fresh', False),
                'pending_feedback': gate.get('pending_feedback'),
                'mqtt_prefix': 'parking/test/v1', 'session_writes_enabled': False,
                'session_workflow': 'pending_teammate_passage_aware_api',
                'camera_check': 'Open each stream or request a fresh snapshot; health does not capture images'}

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST'])
    async def proxy(request: Request, path: str):
        browser_route = '/' + path
        analysis = browser_route == '/api/parking/analyze' and request.method == 'POST'
        route = ALIASES.get(browser_route, browser_route)
        if browser_route.startswith('/api/parking/media/'):
            route = browser_route[4:]
        sensor = route in SENSOR_READS or (route.startswith('/static/') and '..' not in path and '\\' not in path)
        camera = route in CAMERA_READS or MEDIA.fullmatch(route)
        if not sensor and not camera and not analysis:
            return JSONResponse({'error': 'Route unavailable in read-only migration'}, 404)
        query = request.url.query
        if route.startswith('/camera/'):
            allowed = {'camera', 't', 'probe'} if browser_route == '/api/camera/stream' else {'camera'}
            if (set(request.query_params) - allowed or len(request.query_params.getlist('camera')) > 1
                    or request.query_params.get('camera', 'entrance') not in ('entrance', 'exit')):
                return JSONResponse({'error': 'Use camera=entrance or camera=exit'}, 400)
            if request.query_params.get('probe'):
                return JSONResponse({'busy': False, 'transport': 'async'})
            query = 'camera=' + request.query_params.get('camera', 'entrance')
        if analysis:
            # Keep the existing Flask multipart/schema validation and same-origin checks.
            sensor = True
        base = sensor_url if sensor else parking_url
        url = base + route
        if query:
            url += '?' + query
        headers = {'Authorization': upstream_auth} if sensor else {}
        content = None
        if analysis:
            content = bytearray()
            async for chunk in request.stream():
                content.extend(chunk)
                if len(content) > 15 * 1024 * 1024 + 64 * 1024:
                    return JSONResponse({'error': 'Photo upload too large'}, 413)
            content = bytes(content)
            headers.update({'Content-Type': request.headers.get('content-type', ''),
                            'Host': request.headers['host'], 'Origin': request.headers['origin'],
                            'Sec-Fetch-Site': 'same-origin'})
        stream = route == '/camera/stream'
        client = app.state.streams if stream else app.state.regular
        response = None
        try:
            response = await client.send(client.build_request(request.method, url, headers=headers,
                content=content, timeout=75 if analysis else 15), stream=True)
            if 300 <= response.status_code < 400:
                await response.aclose()
                return JSONResponse({'error': 'Unexpected upstream redirect'}, 502)
            output_headers = {key: response.headers[key] for key in
                              ('content-type', 'www-authenticate', 'x-camera-role', 'x-camera-ms')
                              if key in response.headers}
            if stream and response.status_code == 200:
                if not response.headers.get('content-type', '').startswith('multipart/x-mixed-replace'):
                    await response.aclose()
                    return JSONResponse({'error': 'Invalid camera stream'}, 502)

                async def chunks():
                    try:
                        async for chunk in response.aiter_bytes():
                            yield chunk
                    except httpx.HTTPError:
                        # Close on stale/offline frames; the browser must reconnect.
                        return
                    finally:
                        await response.aclose()

                return StreamingResponse(chunks(), status_code=200, headers=output_headers)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 16 * 1024 * 1024:
                    raise ValueError('Response too large')
            await response.aclose()
            return Response(bytes(body), response.status_code, headers=output_headers)
        except (httpx.HTTPError, ValueError):
            if response is not None:
                await response.aclose()
            return JSONResponse({'error': 'Sensor service unavailable' if sensor else 'Parking/camera service unavailable'}, 503)

    return app
