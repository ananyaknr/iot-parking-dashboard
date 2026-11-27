import base64
import os
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from webapp import create_app, history_points

class Queries:
    def query(self, text, org):
        return []

class WebTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"DASHBOARD_USERNAME":"demo","DASHBOARD_PASSWORD":"test-only-password","DASHBOARD_AUTH_REQUIRED":"yes"})
        self.env.start()
        self.client=create_app(lambda:{"mqtt_connected":True,"storage_connected":True},Queries(),"sensor_test","parking").test_client()
        self.headers={"Authorization":"Basic "+base64.b64encode(b"demo:test-only-password").decode()}
    def tearDown(self):self.env.stop()
    def test_auth_and_health(self):
        self.assertEqual(self.client.get("/api/latest").status_code,401)
        self.assertEqual(self.client.get("/api/latest",headers=self.headers).status_code,200)
        self.assertEqual(self.client.get("/health").status_code,200)
    def test_query_parameters_reject_injection(self):
        self.assertEqual(self.client.get('/api/history?source=bad&field=x',headers=self.headers).status_code,400)
        self.assertEqual(self.client.get('/api/history?minutes=10081',headers=self.headers).status_code,400)
        self.assertEqual(self.client.get('/api/history?minutes=oops',headers=self.headers).status_code,400)
    def test_local_dashboard_can_disable_login(self):
        with patch.dict(os.environ, {"DASHBOARD_AUTH_REQUIRED":"no"}):
            self.assertEqual(self.client.get('/').status_code,200)
            self.assertEqual(self.client.get('/api/latest').status_code,200)
            with self.client.get('/static/app.js') as response:
                self.assertEqual(response.status_code,200)
            self.assertEqual(self.client.get('/api/latest',environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code,401)
    def test_local_assets_and_no_cdn(self):
        html=self.client.get("/",headers=self.headers).get_data(as_text=True)
        self.assertIn('/static/vendor/chart.umd.min.js',html)
        self.assertNotIn('cdn.',html)
        points = self.client.get('/api/history',headers=self.headers).json["points"]
        self.assertTrue(points)
        self.assertTrue(all(p['value'] is None for p in points))

    def test_history_midnight_multiday_seven_days_and_gaps(self):
        for minutes in (30, 1440, 4320, 10080):
            stop = datetime(2026, 11, 26, 0, 15, tzinfo=timezone.utc)
            start = stop - timedelta(minutes=minutes)
            every = max(1, (minutes * 60 + 599) // 600)
            end = (int(start.timestamp()) // every + 1) * every
            def record(offset, valid):
                return SimpleNamespace(values={'_stop': datetime.fromtimestamp(end+offset*every, timezone.utc),
                                              'total': 60., 'count': 2, 'valid': valid})
            points = history_points([record(0, True), record(1, False), record(3, True)],start,stop,every)
            self.assertLessEqual(len(points), 601)
            self.assertEqual([p['value'] for p in points[:4]], [30., None, None, 30.])
            times = [datetime.fromisoformat(p['time']) for p in points]
            self.assertEqual(times, sorted(set(times)))
            self.assertNotEqual(times[0].date(), times[-1].date())

    def test_history_storage_outage(self):
        with patch.object(Queries, 'query', side_effect=RuntimeError('offline')):
            response=self.client.get('/api/history', headers=self.headers)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json['points'], [])

    def test_cloud_endpoint_is_optional_and_sensor_only(self):
        self.assertEqual(self.client.get('/api/cloud/history').status_code,401)
        self.assertEqual(self.client.get('/api/cloud/history',headers=self.headers).status_code,503)
        for query in ('source=camera&field=confidence','source=uno&field=license_plate','minutes=43201'):
            self.assertEqual(self.client.get('/api/cloud/history?'+query,headers=self.headers).status_code,400)

    def test_cloud_failure_does_not_block_local_endpoints(self):
        cloud=SimpleNamespace(client=SimpleNamespace(history=lambda *args: (_ for _ in ()).throw(OSError('offline'))))
        client=create_app(lambda:{'mqtt_connected':True,'storage_connected':True},Queries(),'sensor_test','parking',cloud).test_client()
        self.assertEqual(client.get('/api/cloud/history',headers=self.headers).status_code,503)
        self.assertEqual(client.get('/api/latest',headers=self.headers).status_code,200)
        self.assertEqual(client.get('/api/history',headers=self.headers).status_code,200)

if __name__=="__main__":unittest.main()
