import importlib.util
from pathlib import Path
import unittest
import json
import tempfile
from unittest.mock import patch

path = Path(__file__).resolve().parents[2]/"scripts/configure-cloud-resources.py"
spec = importlib.util.spec_from_file_location("cloud_resources",path)
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)
config_path = path.parent/'configure-cloud.py'
config_spec = importlib.util.spec_from_file_location('cloud_configuration',config_path)
configuration = importlib.util.module_from_spec(config_spec)
config_spec.loader.exec_module(configuration)


class SetupTests(unittest.TestCase):
    def test_read_scope_rejects_wrong_or_all_buckets(self):
        for names,valid in [(['parking_sensor_data'],True),(['parking_sensor_test'],False),
                            (['parking_sensor_data','parking_sensor_test'],False)]:
            with self.subTest(names=names), patch.object(configuration.CloudClient,'request',
                    return_value=json.dumps({'buckets':[{'name':n} for n in names]}).encode()):
                if valid:configuration.validate_read_scope({'bucket':'parking_sensor_data'})
                else:
                    with self.assertRaises(ValueError):configuration.validate_read_scope({'bucket':'parking_sensor_data'})

    def test_replace_write_preserves_read_and_rejects_identical_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); (root/'.secrets').mkdir()
            saved=root/'.secrets/cloud.json'
            original={'url':'https://us-east-1-1.aws.cloud2.influxdata.com','bucket':'parking_sensor_data',
                      'free_plan_confirmed':True,'read_token':'test-read-only','write_token':'test-old-write'}
            saved.write_text(json.dumps(original))
            with patch.object(configuration,'ROOT',root), patch('sys.stdin.isatty',return_value=True), \
                    patch('sys.argv',['configure-cloud.py','--free-plan-confirmed','--replace-write']), \
                    patch.object(configuration,'restrict_file'), patch.object(configuration,'validate_read_scope'), patch('builtins.print'):
                with patch.object(configuration.getpass,'getpass',return_value='test-new-write'):
                    configuration.main()
                result=json.loads(saved.read_text())
                self.assertEqual(result['read_token'],original['read_token'])
                self.assertEqual(result['write_token'],'test-new-write')
                with patch.object(configuration.getpass,'getpass',return_value=original['read_token']):
                    with self.assertRaises(SystemExit):configuration.main()
                self.assertEqual(json.loads(saved.read_text()),result)

    def test_approved_empty_bucket_rename_keeps_id_and_only_creates_test(self):
        buckets=[{'id':'original','orgID':'test-org','name':'iot_parking','retentionRules':[]}]
        mappings=[];mutations=[]
        def call(method,path,body=None):
            if method != 'GET':mutations.append((method,path,body))
            if method=='PATCH' and path=='/api/v2/buckets/original':
                buckets[0].update(body);return dict(buckets[0])
            if method=='POST' and path=='/api/v2/buckets':
                bucket=dict(body,id='test');buckets.append(bucket);return dict(bucket)
            if method=='POST' and path=='/api/v2/dbrps':
                mappings.append(dict(body));return dict(body)
            if path.startswith('/api/v2/buckets?'):return {'buckets':[dict(b) for b in buckets]}
            if path.startswith('/api/v2/buckets/'):
                return dict(next(b for b in buckets if path.endswith('/'+b['id'])))
            return {'content':[m for m in mappings if path.endswith('db='+m['database'])]}
        result=resources.provision(call,rename_empty_iot_parking=True)
        self.assertEqual(len(result),2)
        self.assertEqual(buckets[0]['id'],'original')
        self.assertEqual(buckets[0]['name'],'parking_sensor_data')
        self.assertEqual([body['name'] for method,path,body in mutations if method=='POST' and path=='/api/v2/buckets'],['parking_sensor_test'])
        self.assertFalse(any(method=='DELETE' for method,path,body in mutations))
        self.assertTrue(all(body.get('orgID')=='test-org' for method,path,body in mutations if method=='POST'))

    def test_free_capacity_checked_before_mutations(self):
        calls=[]
        def call(method,path,body=None):
            calls.append(method)
            return {"buckets":[{"name":"existing-user-data","id":"1"}]}
        with self.assertRaises(resources.ResourceError):
            resources.provision(call)
        self.assertEqual(calls,["GET"])

    def test_foreign_mapping_never_overwritten(self):
        calls=[]
        def call(method,path,body=None):
            calls.append(method)
            if path.startswith('/api/v2/buckets'):
                return {"buckets":[{"name":"parking_sensor_data","id":"1","orgID":"test-org"},
                                   {"name":"parking_sensor_test","id":"2","orgID":"test-org"}]}
            return {"content":[{"bucketID":"another-bucket","default":True}]}
        with self.assertRaises(resources.ResourceError):
            resources.provision(call)
        self.assertTrue(all(method=='GET' for method in calls))

    def test_existing_correct_resources_are_read_only(self):
        calls=[]
        buckets=[{"name":name,"id":str(i),"orgID":"test-org","retentionRules":[{"type":"expire","everySeconds":2592000,"shardGroupDurationSeconds":0}]}
                 for i,name in enumerate(("parking_sensor_data","parking_sensor_test"))]
        def call(method,path,body=None):
            calls.append(method)
            if path.startswith('/api/v2/buckets?'):return {"buckets":buckets}
            if path.startswith('/api/v2/buckets/'):return next(b for b in buckets if path.endswith('/'+b['id']))
            return {"content":[{"bucketID":"1" if 'parking_sensor_test' in path else "0","default":True}]}
        self.assertEqual(len(resources.provision(call)),2)
        self.assertTrue(all(method=='GET' for method in calls))
