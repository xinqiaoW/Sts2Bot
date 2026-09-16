import unittest

from tools.operational_window import native_cutoff, record_native_window


class OperationalWindowTests(unittest.TestCase):
    def test_slow_backup_does_not_skip_new_results(self):
        report = {'time': 1700}
        record_native_window(report, [100, 1000])
        # Results arriving during 700 seconds of backup validation must be read
        # next time, including those more than the overlap before completion.
        cutoff = native_cutoff(100, report)
        self.assertEqual(cutoff, 910)
        results_during_backup = [1001, 1100, 1500, 1699]
        self.assertTrue(all(t > cutoff for t in results_during_backup))

    def test_repeated_slow_checks_have_no_coverage_gap(self):
        previous = None
        last_end = 100
        for verified_end, finished in [(1000, 1700), (2000, 3300), (4000, 6000)]:
            cutoff = native_cutoff(100, previous)
            self.assertLessEqual(cutoff, last_end)
            previous = {'time': finished}
            record_native_window(previous, [cutoff, verified_end])
            last_end = verified_end

    def test_overlap_does_not_precede_first_launch(self):
        self.assertEqual(native_cutoff(100), 100)
        self.assertEqual(native_cutoff(100, {'time': 140, 'native_verified_through': 120}), 100)

    def test_legacy_fallback_is_explicit_and_compatible(self):
        self.assertEqual(native_cutoff(100, {'time': 1000}), 910)

    def test_future_or_nonfinite_watermark_is_rejected(self):
        for value in (2001, float('nan'), float('inf'), '1000'):
            with self.assertRaises(ValueError):
                native_cutoff(100, {'time': 2000, 'native_verified_through': value})

    def test_invalid_window_does_not_modify_report(self):
        for window in ([200, 100], [100, 1001], [100, float('nan')]):
            report = {'time': 1000}
            with self.assertRaises(ValueError):
                record_native_window(report, window)
            self.assertEqual(report, {'time': 1000})


if __name__ == '__main__':
    unittest.main()
