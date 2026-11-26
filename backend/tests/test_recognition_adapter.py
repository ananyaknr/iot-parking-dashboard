from datetime import datetime,timezone,timedelta
import unittest
from recognition_adapter import RecognitionAdapter


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.gate={'fresh':True,'payload_valid':True,'arrival_id':'v2:'+'a'*32+':a:1'}
        self.adapter=RecognitionAdapter(lambda:self.gate,enabled=True)
        self.now=datetime.now(timezone.utc)
        self.result={'schema_version':2,'result_id':'isolated-test-1','arrival_id':self.gate['arrival_id'],
                     'occurred_at':self.now.isoformat(),'license_plate':'กข 1234','lcd_plate':'AB1234',
                     'vehicle_type':'car','status':'recognized','authorized':True,'origin':'synthetic',
                     'session_id':None,'photo_ref':None}

    def test_original_thai_and_ascii_delivery_are_separate(self):
        self.assertEqual(self.adapter.receive(self.result,now=self.now),'accepted')
        self.assertEqual(self.adapter.snapshot()['license_plate'],'กข 1234')
        self.assertEqual(self.adapter.snapshot()['lcd_plate'],'AB1234')
        self.assertEqual(self.adapter.snapshot()['gate_authorization'],'disabled')
        self.assertEqual(self.adapter.receive(self.result,now=self.now),'duplicate')
        self.gate['arrival_id']='v2:'+'a'*32+':a:2'
        self.assertIsNone(self.adapter.snapshot()['license_plate'])

    def test_stale_malformed_unknown_or_wrong_arrival_cannot_authorize(self):
        cases=[dict(self.result,arrival_id='old'),dict(self.result,vehicle_type='unknown'),
               dict(self.result,status='failed'),dict(self.result,origin='teammate'),
               dict(self.result,lcd_plate='กข1234'),dict(self.result,license_plate='bad\nplate'),
               dict(self.result,photo_ref='unagreed'),dict(self.result,authorized=1),
               dict(self.result,occurred_at=(self.now-timedelta(seconds=6)).isoformat())]
        for message in cases:
            with self.subTest(message=message),self.assertRaises(ValueError):self.adapter.receive(message,now=self.now)
        disabled=RecognitionAdapter(lambda:self.gate)
        with self.assertRaises(PermissionError):disabled.receive(self.result,now=self.now)

    def test_result_identity_conflicts_and_explicit_ascii_fallback(self):
        self.adapter.receive(self.result,now=self.now)
        with self.assertRaises(ValueError):self.adapter.receive(dict(self.result,vehicle_type='supercar'),now=self.now)
        self.adapter.receive(dict(self.result,result_id='isolated-test-2',lcd_plate=None),now=self.now)
        self.assertEqual(self.adapter.snapshot()['lcd_status'],'ascii_fallback_required')
        self.assertEqual(self.adapter.snapshot()['license_plate'],'กข 1234')
