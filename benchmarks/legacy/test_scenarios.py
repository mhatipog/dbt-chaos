import unittest
from scenarios import BASE, SCENARIOS, oracle, diff

class OracleTests(unittest.TestCase):
    def test_newer_version(self):
        self.assertEqual([(1,1100,15),(2,2000,20)], oracle([*BASE,(1,1100,15)]))
    def test_older_version_ignored(self):
        self.assertEqual(list(BASE), oracle([*BASE,(1,0,9)]))
    def test_same_timestamp_last_arrival_wins(self):
        self.assertEqual([(1,1234,10),(2,2000,20)], oracle([*BASE,(1,1234,10)]))
    def test_duplicate_difference(self):
        self.assertEqual({"missing":[],"unexpected":[BASE[0]]},diff(list(BASE),[*BASE,BASE[0]]))
    def test_cases_unique(self):
        self.assertEqual(len(SCENARIOS),len({s.name for s in SCENARIOS}))

if __name__ == "__main__":
    unittest.main()
