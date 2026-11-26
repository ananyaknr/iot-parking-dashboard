import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2]/'scripts/measure-cloud-usage.py'
spec = importlib.util.spec_from_file_location('cloud_usage',path)
usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usage)


class UsageTests(unittest.TestCase):
    def test_separates_write_bytes_and_latest_storage_gauges(self):
        header = ',_measurement,_field,_value,_start,_stop,_time,bucket_id,endpoint,status\n'
        csv = header + (
            ',http_request,req_bytes,100,start,stop,t1,,/api/v2/write,204\n'
            ',http_request,req_bytes,50,start,stop,t1,,/api/v2/write,403\n'
            ',http_request,req_bytes,30,start,stop,t1,,/query,200\n'
            ',http_request,resp_bytes,20,start,stop,t1,,/query,200\n'
            ',query_count,req_bytes,3,start,stop,t1,,/query,200\n'
            ',storage_usage_bucket_bytes,gauge,10,start,stop,t1,b1,,\n')
        csv += header + (
            ',storage_usage_bucket_bytes,gauge,15,start,stop,t2,b1,,\n'
            ',storage_usage_bucket_bytes,gauge,7,start,stop,t2,b2,,\n')
        result = usage.summarize(csv.encode())
        self.assertEqual(result['successful_write_request_bytes'],100)
        self.assertEqual(result['query_count'],3)
        self.assertEqual(result['http_response_bytes_including_errors'],20)
        self.assertEqual(result['latest_reported_storage_bytes'],22)
        self.assertNotIn('b1',str(result))

    def test_rejects_empty_or_nonfinite_usage(self):
        for raw in (b'{"error":"unavailable"}',
                    b',_measurement,_field,_value\n,http_request,req_bytes,NaN\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                usage.summarize(raw)
