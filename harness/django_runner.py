"""Use Django's real test DB/migration lifecycle and reject incomplete checks."""
from django.test.runner import DiscoverRunner


class HarnessRunner(DiscoverRunner):
    def run_suite(self, suite, **kwargs):
        result = super().run_suite(suite, **kwargs)
        self.report = {
            'runner': 'django', 'selected': result.testsRun,
            'passed': result.testsRun - len(result.failures) - len(result.errors)
                      - len(result.skipped) - len(result.expectedFailures)
                      - len(result.unexpectedSuccesses),
            'failures': [{'test': str(test), 'reason': reason} for test, reason in result.failures],
            'errors': [{'test': str(test), 'reason': reason} for test, reason in result.errors],
            'skipped': [{'test': str(test), 'reason': reason} for test, reason in result.skipped],
            'expected_failures': [str(test) for test, _ in result.expectedFailures],
            'unexpected_successes': [str(test) for test in result.unexpectedSuccesses],
        }
        if not result.testsRun or result.skipped or result.expectedFailures:
            reason = 'Required tests were skipped, expected to fail, or absent.'
            self.report['errors'].append({'test': 'harness coverage', 'reason': reason})
            result.errors.append(('harness coverage', reason))
        return result
