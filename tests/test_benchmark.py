import unittest
from altreview.benchmark import metrics, outcome


class BenchmarkContracts(unittest.TestCase):
    def test_no_silent_dropping_of_cases(self):
        with self.assertRaises(ValueError):
            metrics({'a': 'passed'}, {'a': 'passed', 'b': 'failed'})

    def test_unknowns_remain_in_denominator(self):
        result = metrics({'a': 'passed', 'b': 'unknown'}, {'a': 'passed', 'b': 'failed'})
        self.assertEqual(result['agreement'], 0.5)
        self.assertEqual(result['unknown'], 1)

    def test_presentation_is_distinct_from_hidden_applicability(self):
        row = {'image_ax': {'available': True, 'ignored': True, 'role': 'none', 'ignored_reasons': ['emptyAlt']}}
        self.assertEqual(outcome([row]), 'passed')
        row['image_ax']['ignored_reasons'] = ['notRendered']
        self.assertEqual(outcome([row]), 'inapplicable')

    def test_browser_failures_never_become_passes(self):
        self.assertEqual(outcome([{'image_ax': {'available': False}}]), 'unknown')
