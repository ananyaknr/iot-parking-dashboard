import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2]/"scripts/configure-cloud-resources.py"
spec = importlib.util.spec_from_file_location("cloud_resources",path)
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)


class SetupTests(unittest.TestCase):
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
                return {"buckets":[{"name":"parking_sensor_data","id":"1"},
                                   {"name":"parking_sensor_test","id":"2"}]}
            return {"content":[{"bucketID":"another-bucket","default":True}]}
        with self.assertRaises(resources.ResourceError):
            resources.provision(call)
        self.assertTrue(all(method=='GET' for method in calls))

    def test_existing_correct_resources_are_read_only(self):
        calls=[]
        buckets=[{"name":name,"id":str(i),"retentionRules":[{"type":"expire","everySeconds":2592000,"shardGroupDurationSeconds":0}]}
                 for i,name in enumerate(("parking_sensor_data","parking_sensor_test"))]
        def call(method,path,body=None):
            calls.append(method)
            if path.startswith('/api/v2/buckets?'):return {"buckets":buckets}
            if path.startswith('/api/v2/buckets/'):return next(b for b in buckets if path.endswith('/'+b['id']))
            return {"content":[{"bucketID":"1" if 'parking_sensor_test' in path else "0","default":True}]}
        self.assertEqual(len(resources.provision(call)),2)
        self.assertTrue(all(method=='GET' for method in calls))
