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


class ParkingProxyTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"DASHBOARD_USERNAME":"demo","DASHBOARD_PASSWORD":"test-only-password","PARKING_API_URL":"http://127.0.0.1:9"})
        self.env.start()
        self.client=create_app(lambda:{"mqtt_connected":True,"storage_connected":True},Queries(),"sensor_test","parking").test_client()
        self.headers={"Authorization":"Basic "+base64.b64encode(b"demo:test-only-password").decode()}
    def tearDown(self):self.env.stop()

    def test_state_changes_must_be_same_origin(self):
        body={"observation_id":"00000000-0000-0000-0000-000000000000","request_id":"r1"}
        for headers in ({"Origin":"https://evil.example"},{"Sec-Fetch-Site":"cross-site"}):
            response=self.client.post("/api/parking/commit",json=body,headers={**self.headers,**headers})
            self.assertEqual(response.status_code,403)
        with patch.dict(os.environ,{"DASHBOARD_AUTH_REQUIRED":"no"}):
            self.assertEqual(self.client.post("/api/parking/analyze",headers={"Origin":"https://evil.example"}).status_code,403)
        ok=self.client.post("/api/parking/commit",json=body,headers={**self.headers,"Origin":"http://localhost","Sec-Fetch-Site":"same-origin"})
        self.assertEqual(ok.status_code,503)

    def test_simulator_commit_switch(self):
        body={"observation_id":"00000000-0000-0000-0000-000000000000","request_id":"r1"}
        self.assertIn('data-simulator-commit="yes"',self.client.get("/",headers=self.headers).get_data(as_text=True))
        with patch.dict(os.environ,{"PARKING_SIMULATOR_COMMIT":"no"}):
            self.assertEqual(self.client.post("/api/parking/commit",json=body,headers=self.headers).status_code,403)
            self.assertIn('data-simulator-commit="no"',self.client.get("/",headers=self.headers).get_data(as_text=True))

    def test_requires_auth(self):
        for path in ("/api/parking/status","/api/parking/history","/api/parking/media/00000000-0000-0000-0000-000000000000"):
            self.assertEqual(self.client.get(path).status_code,401)

    def test_unreachable_service_is_503_not_fake_data(self):
        response=self.client.get("/api/parking/status",headers=self.headers)
        self.assertEqual(response.status_code,503)
        self.assertFalse(response.json["available"])
        self.assertEqual(self.client.get("/api/parking/history",headers=self.headers).status_code,503)

    def test_passthrough_and_validation(self):
        import parking_proxy
        payload={"capacity":{"vip":{"total":2,"occupied":1,"available":1}},"spaces":[]}
        with patch.object(parking_proxy,"status",return_value=payload):
            self.assertEqual(self.client.get("/api/parking/status",headers=self.headers).json,payload)
        with patch.object(parking_proxy,"history",return_value={"events":[],"sessions":[]}) as history:
            self.assertEqual(self.client.get("/api/parking/history?limit=20",headers=self.headers).status_code,200)
            history.assert_called_once_with(20)
        self.assertEqual(self.client.get("/api/parking/history?limit=101",headers=self.headers).status_code,400)
        self.assertEqual(self.client.get("/api/parking/history?limit=x",headers=self.headers).status_code,400)
        self.assertEqual(self.client.get("/api/parking/media/../../etc",headers=self.headers).status_code,404)
        with patch.object(parking_proxy,"media",return_value=b"\xff\xd8jpeg"):
            r=self.client.get("/api/parking/media/00000000-0000-0000-0000-000000000000",headers=self.headers)
            self.assertEqual((r.status_code,r.mimetype),(200,"image/jpeg"))

    def test_rejects_bad_base_url(self):
        import parking_proxy
        with patch.dict(os.environ,{"PARKING_API_URL":"file:///etc/passwd"}):
            with self.assertRaises(parking_proxy.ParkingUnavailable):
                parking_proxy.base_url()

    def test_gate_operation_routes_validate_before_forwarding(self):
        import io
        import parking_proxy
        h=self.headers
        self.assertEqual(self.client.get("/api/camera/frame?camera=side",headers=h).status_code,400)
        jpeg=(io.BytesIO(b"\xff\xd8test"),"c.jpg","image/jpeg")
        bad=[{"camera":"side","image":jpeg},{"camera":"entrance","plate_bbox":"1,2,3","image":jpeg},
             {"camera":"entrance","previous_observation_id":"nope","image":jpeg},{"camera":"entrance"}]
        for form in bad:
            form={k:((io.BytesIO(b"\xff\xd8test"),"c.jpg","image/jpeg") if k=="image" else v) for k,v in form.items()}
            self.assertEqual(self.client.post("/api/parking/analyze",data=form,headers=h,content_type="multipart/form-data").status_code,400)
        with patch.object(parking_proxy,"analyze",return_value={"observation_id":"x","eligible":True}) as analyze:
            r=self.client.post("/api/parking/analyze",headers=h,content_type="multipart/form-data",
                data={"camera":"exit","plate_bbox":"10,20,30,40","image":(io.BytesIO(b"\xff\xd8"+b"x"*20000),"c.jpg","image/jpeg")})
            self.assertEqual(r.status_code,200)
            self.assertEqual(analyze.call_args.args[2:],("exit","10,20,30,40",None))
        self.assertEqual(self.client.post("/api/parking/commit",json={"observation_id":"bad","request_id":"r"},headers=h).status_code,400)
        oid="00000000-0000-0000-0000-000000000001"
        with patch.object(parking_proxy,"commit",side_effect=parking_proxy.ParkingUnavailable("Request ID was already used",409)):
            r=self.client.post("/api/parking/commit",json={"observation_id":oid,"request_id":oid},headers=h)
            self.assertEqual((r.status_code,r.json["error"]),(409,"Request ID was already used"))
        # other routes keep the 4 KB body limit
        self.assertEqual(self.client.post("/api/parking/commit",data=b"x"*5000,headers=h,content_type="application/json").status_code,413)

    def test_unreachable_camera_is_503(self):
        r=self.client.get("/api/camera/frame?camera=entrance",headers=self.headers)
        self.assertEqual(r.status_code,503)

    def test_camera_stream_relays_and_allows_one_viewer_per_camera(self):
        import io
        import parking_proxy
        h=self.headers
        self.assertEqual(self.client.get("/api/camera/stream?camera=side",headers=h).status_code,400)
        self.assertEqual(self.client.get("/api/camera/stream?camera=entrance").status_code,401)
        body=b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8x\r\n--frame--\r\n"
        ctype="multipart/x-mixed-replace; boundary=frame"
        with patch.object(parking_proxy,"camera_stream",side_effect=lambda c:(ctype,io.BufferedReader(io.BytesIO(body)))):
            self.assertFalse(self.client.get("/api/camera/stream?camera=entrance&probe=1",headers=h).json["busy"])
            first=self.client.get("/api/camera/stream?camera=entrance",headers=h,buffered=False)
            self.assertTrue(self.client.get("/api/camera/stream?camera=entrance&probe=1",headers=h).json["busy"])
            self.assertEqual(first.headers["Content-Type"],ctype)
            second=self.client.get("/api/camera/stream?camera=entrance",headers=h)
            self.assertEqual(second.status_code,409)
            self.assertEqual(self.client.get("/api/camera/stream?camera=exit",headers=h,buffered=True).data,body)
            self.assertEqual(b"".join(first.response),body); first.close()
            again=self.client.get("/api/camera/stream?camera=entrance",headers=h,buffered=True)
            self.assertEqual(again.status_code,200)
        with patch.object(parking_proxy,"camera_stream",side_effect=parking_proxy.ParkingUnavailable("Camera unavailable",502)):
            r=self.client.get("/api/camera/stream?camera=exit",headers=h)
            self.assertEqual(r.status_code,502)
            self.assertEqual(self.client.get("/api/camera/stream?camera=exit",headers=h).status_code,502)  # slot released after failure
