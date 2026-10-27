import unittest
from civic_backlog.benchmark import benchmark
from civic_backlog.model import InputError


class BenchmarkTests(unittest.TestCase):
    def test_bounded_workload_checks_duplicates_outcomes_and_denominators(self):
        result=benchmark(100,1)
        self.assertEqual(result['workload']['input_rows'],110)
        self.assertEqual(result['workload']['closed'],50)
        self.assertEqual(result['workload']['open'],25)
        self.assertEqual(result['workload']['unknown'],25)
        self.assertEqual(result['workload']['normalized_duplicates'],10)
        for key,value in result['median_ms'].items():
            self.assertGreater(value,0);self.assertEqual(value,result['measurements'][0][key])
        self.assertEqual(result['environment']['duckdb_threads'],2)
        self.assertEqual(len(result['workload']['payload_sha256']),64)

    def test_invalid_bounds_are_rejected_before_generating_workload(self):
        for rows in (0,99,101,10100,True):
            with self.assertRaises(InputError):benchmark(rows,1)
        for repeats in (0,6,True):
            with self.assertRaises(InputError):benchmark(100,repeats)
