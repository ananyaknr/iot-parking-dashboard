"""Focused gateway boundaries; no cameras, MQTT, OCR or persistent data."""
import base64
from pathlib import Path
import sys
import unittest
import httpx
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from unified_gateway import create_gateway


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def upstream(request):
            self.calls.append(request)
            if request.url.path == '/camera/stream':
                return httpx.Response(200, content=b'--frame\r\n\xff\xd8TEST',
                                      headers={'Content-Type': 'multipart/x-mixed-replace; boundary=frame'})
            if request.url.path == '/api/latest':
                return httpx.Response(200, json={'mqtt_connected': True, 'storage_connected': True,
                    'parking3': {'fresh': True, 'pending_feedback': 0, 'clock_verified': True,
                                 'telemetry': {'phase': 5, 'reason': 7, 'servo_enabled': False,
                                               'u1_state': 'clear', 'u2_state': 'clear'}},
                    'sources': {'esp32': {'fresh': True}}})
            if request.url.path == '/parking/status':
                return httpx.Response(200, json={'storage': 'local', 'gate_mode': 'simulation', 'database': 'ready'})
            return httpx.Response(200, json={'ok': True})
        self.app = create_gateway('http://127.0.0.1:5001', 'http://127.0.0.1:8001',
            username='operator', password='test-only', transport=httpx.MockTransport(upstream))
        self.auth = {'Authorization': 'Basic '+base64.b64encode(b'operator:test-only').decode()}

    def test_shared_auth_and_read_only_routes(self):
        with TestClient(self.app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000)) as c:
            for path in ('/', '/camera/stream', '/parking/status', '/parking/media/12345678-1234-1234-1234-123456789abc', '/api/integration/readiness'):
                self.assertEqual(c.get(path).status_code, 401)
            self.assertFalse(self.calls)
            for path in ('/parking/commit', '/parking/sensors', '/parking/analyze', '/api/integration/recognition'):
                self.assertEqual(c.post(path, headers=self.auth).status_code, 405)
                self.assertEqual(c.get(path, headers=self.auth).status_code, 404)
            self.assertFalse(self.calls)
            self.assertEqual(c.get('/camera/snapshot?camera=http://outside', headers=self.auth).status_code, 400)

    def test_stream_and_sensor_routing(self):
        with TestClient(self.app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000)) as c:
            for lane in ('entrance', 'exit'):
                r = c.get('/camera/stream?camera='+lane, headers=self.auth)
                self.assertIn(b'\xff\xd8', r.content)
                self.assertEqual(self.calls[-1].url.port, 8001)
                self.assertNotIn('authorization', self.calls[-1].headers)
            r = c.get('/api/latest', headers=self.auth)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(self.calls[-1].url.port, 5001)
            self.assertEqual(self.calls[-1].headers['authorization'], self.auth['Authorization'])
            self.assertEqual(r.headers['cache-control'], 'private, no-store')
            ready = c.get('/api/integration/readiness', headers=self.auth).json()
            self.assertTrue(ready['gate_telemetry_fresh'])
            self.assertFalse(ready['gate_cycle_ready'])
            self.assertFalse(ready['session_writes_enabled'])

    def test_dashboard_aliases_and_same_origin_analysis(self):
        with TestClient(self.app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000)) as c:
            for path, upstream in (('/api/parking/status','/parking/status'),
                                   ('/api/parking/history?limit=30','/parking/history'),
                                   ('/api/camera/frame?camera=entrance','/camera/snapshot'),
                                   ('/api/camera/stream?camera=exit&t=123','/camera/stream')):
                self.assertEqual(c.get(path, headers=self.auth).status_code, 200)
                self.assertEqual(self.calls[-1].url.path, upstream)
                self.assertEqual(self.calls[-1].url.port, 8001)
            self.assertFalse(c.get('/api/camera/stream?camera=exit&probe=1',headers=self.auth).json()['busy'])
            before = len(self.calls)
            for origin in ('https://other.example', None):
                h = {**self.auth, **({'Origin':origin} if origin else {})}
                self.assertEqual(c.post('/api/parking/analyze',headers=h).status_code, 403)
            self.assertEqual(len(self.calls), before)
            h = {**self.auth, 'Origin':'http://127.0.0.1'}
            self.assertEqual(c.post('/api/parking/analyze',headers=h,files={'image':('test.jpg',b'TEST','image/jpeg')},data={'camera':'exit'}).status_code,200)
            self.assertEqual(self.calls[-1].url.port, 5001)
            self.assertEqual(self.calls[-1].headers['origin'], 'http://127.0.0.1')
            self.assertIn(b'filename="test.jpg"', self.calls[-1].content)
            self.assertEqual(c.post('/api/parking/commit',headers=h,json={}).status_code,405)

    def test_outage_is_explicit_and_upstream_is_fixed(self):
        def offline(request):
            raise httpx.ConnectError('offline')
        app = create_gateway('http://127.0.0.1:5001', 'http://127.0.0.1:8001',
                             auth_required=False, transport=httpx.MockTransport(offline))
        with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000)) as c:
            self.assertEqual(c.get('/parking/status').status_code, 503)
            r = c.get('/api/integration/readiness').json()
            self.assertFalse(r['parking_service_ready'])
            self.assertFalse(r['sensor_service_ready'])
        with self.assertRaises(ValueError):
            create_gateway('http://example.com:5001', 'http://127.0.0.1:8001', auth_required=False)


if __name__ == '__main__':
    unittest.main()
