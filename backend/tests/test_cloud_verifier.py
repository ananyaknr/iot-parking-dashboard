import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2]/'scripts/test-cloud-pipeline.py'
spec = importlib.util.spec_from_file_location('cloud_verifier',path)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class VerifierTests(unittest.TestCase):
    def test_http_200_authorization_errors_are_denials(self):
        for response in ({'error':'not authorized'},
                         {'results':[{'error':'permission denied'}]}):
            self.assertTrue(verifier.authorization_denied(response))

    def test_other_errors_or_data_do_not_establish_denial(self):
        for response in ({'results':[{'error':'syntax error'}]}, {'results':[]},
                         {'error':'not authorized','results':[{'series':[{'values':[[1]]}]}]}):
            self.assertFalse(verifier.authorization_denied(response))
