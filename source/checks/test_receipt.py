from pathlib import Path
import tempfile
import unittest

from test_owner_flow import ROOT
import owner_flow


class ResolutionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.flow = owner_flow.Flow(self.root)
        self.flow.create('Synthetic records were delivered after staff access was revoked.')

    def test_unfinished_work_has_no_claim_of_a_verified_resolution(self):
        receipt = self.flow.receipt()
        self.assertIn('Not yet observed', receipt)
        self.assertIn('Not applied', receipt)
        self.assertIn('Not run', receipt)
        self.assertNotIn('Replay verified', receipt)
        self.assertNotIn('The model supplied a bounded policy function', receipt)

    def test_failed_check_attempt_remains_distinct_from_not_run(self):
        self.flow.choose('delivery-time')
        with self.assertRaises(FileNotFoundError):
            self.flow.construct_and_check(self.root / 'missing-events.jsonl')
        receipt = self.flow.receipt()
        self.assertIn('Latest check attempt: failed', receipt)
        self.assertIn('No active checks', receipt)
        self.assertIn('Not applied', receipt)

    def test_historical_crash_is_not_presented_as_behavioral_violation(self):
        checks = {'baseline': {'verdict': 'violated', 'sha256': 'example', 'build_exit': 0,
                              'cases': [{'name': 'revoked', 'exit': 7, 'observed': None, 'satisfied': False}]}}
        with self.flow.connect() as db:
            self.flow.put(db, 'checks', checks)
        receipt = self.flow.receipt()
        self.assertIn('revoked example: inconclusive', receipt)
        self.assertIn('inconclusive (recorded verdict: violated)', receipt)

    def test_legacy_checks_do_not_claim_a_response_origin(self):
        with self.flow.connect() as db:
            self.flow.put(db, 'checks', {'model':'example-model'})
        self.assertIn('Response origin: not recorded', self.flow.receipt())
        self.assertNotIn('retained earlier response', self.flow.receipt())

    def test_completed_run_reports_bound_evidence_and_flags_later_source_changes(self):
        self.flow.reproduce()
        self.flow.choose('delivery-time')
        checks = self.flow.construct_and_check(ROOT / 'evidence' / 'muse-events.jsonl')
        self.flow.apply()
        replay = self.flow.replay()
        job = self.flow.enqueue('authorized recovery')
        self.flow.deliver(job, fail_after_audit=True)
        self.flow.recover(job)
        receipt = self.flow.receipt()
        self.assertIn(checks['candidate']['sha256'], receipt)
        self.assertIn(checks['checker_sha256'], receipt)
        self.assertEqual(owner_flow.delivery.digest((self.root / 'checkers' / (checks['checker_sha256'] + '.py')).read_bytes()), checks['checker_sha256'])
        self.assertIn(checks['model_events_sha256'], receipt)
        self.assertIn('Response origin: supplied retained event file', receipt)
        self.assertIn('Authored wrong fix', receipt)
        self.assertIn('access_revoked', receipt)
        self.assertIn(replay['job_id'], receipt)
        self.assertIn(job, receipt)
        self.assertIn('1 audit', receipt)
        self.assertIn('1 export', receipt)
        self.assertIn('Current source matches the applied source', receipt)
        self.assertIn('not recorded', receipt)
        (self.root / 'service.go').write_text('changed after replay')
        self.assertIn('Current source differs from the applied source', self.flow.receipt())


if __name__ == '__main__': unittest.main()
