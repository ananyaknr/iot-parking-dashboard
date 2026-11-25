import base64
import os
import unittest
from unittest.mock import patch
from webapp import create_app

class Queries:
    def query(self, text, org):
        return []

class WebTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"DASHBOARD_USERNAME":"demo","DASHBOARD_PASSWORD":"test-only-password"})
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
    def test_local_assets_and_no_cdn(self):
        html=self.client.get("/",headers=self.headers).get_data(as_text=True)
        self.assertIn('/static/vendor/chart.umd.min.js',html)
        self.assertNotIn('cdn.',html)
        self.assertEqual(self.client.get('/api/history',headers=self.headers).json["points"],[])

if __name__=="__main__":unittest.main()
