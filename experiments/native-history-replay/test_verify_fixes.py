import unittest

from verify_fixes import remaining_cases


class RemainingScopeTests(unittest.TestCase):
    def test_excludes_only_completed_native_passes_and_keeps_every_related_case(self):
        cases = [{'category': 'opening_imbued_session', 'job': str(i)} for i in range(4)]
        cases += [{'category': 'terminal_toasty_surface', 'job': 'toasty'},
                  {'category': 'terminal_entropy_accounting', 'job': 'entropy'},
                  {'category': 'wine_page_fault', 'job': 'unrelated'}]
        previous = [dict(sourceJobId='0', passed=True, comparisonCompleted=True, nativeStatus='Passed'),
                    dict(sourceJobId='1', passed=True, comparisonCompleted=False, nativeStatus='Failed'),
                    dict(sourceJobId='2', passed=False, comparisonCompleted=True, nativeStatus='NativeWinePageFault')]
        self.assertEqual([c['job'] for c in remaining_cases(cases, previous)],
                         ['1', '2', '3', 'toasty', 'entropy'])

    def test_rejects_duplicate_remaining_jobs(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            remaining_cases([{'category': 'opening_imbued_session', 'job': 'same'}] * 2, [])


if __name__ == '__main__':
    unittest.main()
