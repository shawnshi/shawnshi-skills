import unittest
from management_claim_tracker import evaluate_claims
from test_staged_phase1 import claim_payload


class ExtremeNumbers(unittest.TestCase):
    def test_oversize_numbers_are_structured_not_overflow(self):
        for field in ('target', 'actual'):
            for number in (10**400, -(10**400)):
                for absent in (False, True):
                    p = claim_payload()
                    if absent:
                        p['claims'][0]['actual'] = None
                    p['claims'][0][field] = number
                    with self.subTest(field=field, sign=number > 0, absent=absent):
                        r = evaluate_claims(p)
                        self.assertFalse(r['valid'])
                        self.assertTrue(r['errors'])

    def test_ordinary_and_nonfinite_contract(self):
        for value in (True, False, float('nan'), float('inf'), float('-inf')):
            p = claim_payload(); p['claims'][0]['target'] = value
            self.assertFalse(evaluate_claims(p)['valid'])
        p = claim_payload()
        self.assertTrue(evaluate_claims(p)['valid'])
        self.assertEqual(evaluate_claims(p)['management_claim_tracking']['claims'][0]['status'], 'not_due')


if __name__ == '__main__':
    unittest.main()
