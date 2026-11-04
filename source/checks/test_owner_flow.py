import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import owner_flow


class OwnerFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.flow = owner_flow.Flow(self.root)
        self.flow.create('A customer received records after access was revoked.')

    def test_report_creation_refuses_to_overwrite_existing_source(self):
        fresh = owner_flow.Flow(self.root/'fresh')
        existing = fresh.root/'service.go'
        existing.write_text('unrelated work')
        with self.assertRaises(owner_flow.InvalidState):
            fresh.create('Report')
        self.assertEqual(existing.read_text(), 'unrelated work')
        self.assertIsNone(fresh.view()['report'])
        self.assertFalse(fresh.receipts())

    def test_report_creation_does_not_commit_if_source_cannot_be_written(self):
        fresh = owner_flow.Flow(self.root/'unwritable')
        with mock.patch.object(Path, 'open', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                fresh.create('Report')
        self.assertIsNone(fresh.view()['report'])
        self.assertFalse(fresh.receipts())

    def test_request_time_choice_preserves_authorized_request_and_audit(self):
        baseline = self.flow.reproduce()
        self.flow.choose('request-time')
        state = self.flow.view()
        self.assertEqual(state['decision'], 'request-time')
        self.assertEqual(state['request_time_replay']['status'], 'exported')
        self.assertFalse(state['request_time_replay']['access_at_delivery'])
        self.assertEqual(state['request_time_replay']['audit_count'], 1)
        self.assertEqual(state['request_time_replay']['export_count'], 1)
        self.assertEqual(state['application']['state'], 'not_applied')
        self.assertIsNone(state['checks'])
        self.assertFalse(any(r['kind'] == 'generation_started' for r in self.flow.receipts()))
        self.assertIn('Request-time replay', self.flow.receipt())
        self.assertIn(state['request_time_replay']['job_id'], self.flow.receipt())
        self.assertIn('Report to observed replay:', self.flow.receipt())
        self.assertEqual(baseline['export_count'], 1)

    def test_request_time_recovery_preserves_request_authorization(self):
        self.flow.reproduce()
        self.flow.choose('request-time')
        job = self.flow.enqueue('authorized request')
        self.flow.deliver(job, fail_after_audit=True)
        self.flow.revoke(job)
        result = self.flow.recover(job)
        self.assertEqual(result['status'], 'exported')
        self.assertEqual(result['audit_count'], 1)
        self.assertEqual(result['export_count'], 1)

    def test_request_time_replay_resumes_same_job_after_interruption(self):
        self.flow.reproduce()
        with mock.patch.object(self.flow, 'revoke', side_effect=SystemExit('simulated exit')):
            with self.assertRaises(SystemExit): self.flow.choose('request-time')
        with self.flow.connect() as db:
            job = self.flow.get(db, 'request_time_replay_job')
        restarted = owner_flow.Flow(self.root)
        result = restarted.resume_request_time()
        self.assertEqual(result['job_id'], job)
        self.assertEqual(result['status'], 'exported')
        self.assertEqual(result['audit_count'], 1)
        self.assertEqual(result['export_count'], 1)
        with restarted.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE request_label='request-time replay'").fetchone()[0], 1)

    def test_request_time_refuses_missing_original_authorization(self):
        self.flow.reproduce()
        self.flow.choose('request-time')
        job = self.flow.enqueue('missing authorization evidence')
        with self.flow.connect() as db:
            db.execute('DELETE FROM request_authorizations WHERE job_id=?', (job,))
        self.flow.revoke(job)
        with self.assertRaises(owner_flow.InvalidState): self.flow.deliver(job)
        self.assertEqual(self.flow.job(job)['export_count'], 0)

    def test_request_time_choice_requires_observed_authorized_baseline(self):
        with self.assertRaises(owner_flow.InvalidState): self.flow.choose('request-time')
        self.assertIsNone(self.flow.view()['decision'])

    def test_original_journey_replayed_after_checked_fix(self):
        baseline = self.flow.reproduce()
        self.assertEqual(baseline['status'], 'exported')
        self.assertEqual(baseline['access_at_delivery'], False)
        self.flow.choose('delivery-time')
        result = self.flow.construct_and_check(ROOT/'evidence'/'muse-events.jsonl')
        self.assertEqual(result['baseline']['verdict'], 'violated')
        self.assertEqual(result['wrong_fix']['verdict'], 'violated')
        self.assertEqual(result['candidate']['verdict'], 'satisfied')
        self.flow.apply()
        replay = self.flow.replay()
        self.assertEqual(replay['status'], 'access_revoked')
        self.assertEqual(replay['export_count'], 0)
        again = owner_flow.Flow(self.root)
        self.assertEqual(again.view()['replay']['status'], 'access_revoked')
        self.assertEqual(again.view()['candidate_sha256'], result['candidate']['sha256'])

    def test_failure_and_recovery_are_durable_without_duplicate_audit_or_export(self):
        self.flow.choose('delivery-time')
        self.flow.construct_and_check(ROOT/'evidence'/'muse-events.jsonl')
        self.flow.apply()
        job = self.flow.enqueue('recovery-case')
        failure = self.flow.deliver(job, fail_after_audit=True)
        self.assertEqual(failure['status'], 'interrupted')
        reloaded = owner_flow.Flow(self.root)
        self.assertEqual(reloaded.job(job)['audit_count'], 1)
        self.assertEqual(reloaded.job(job)['export_count'], 0)
        result = reloaded.recover(job)
        self.assertEqual(result['status'], 'exported')
        self.assertEqual(result['audit_count'], 1)
        self.assertEqual(result['export_count'], 1)
        receipts = reloaded.receipts()
        self.assertTrue(any(r['kind'] == 'attempt_failed' for r in receipts))
        self.assertTrue(any(r['kind'] == 'recovery_completed' for r in receipts))
        self.assertEqual(reloaded.recover(job)['export_count'], 1)

    def test_recovery_rechecks_current_access(self):
        self.flow.choose('delivery-time')
        self.flow.construct_and_check(ROOT/'evidence'/'muse-events.jsonl')
        self.flow.apply()
        job = self.flow.enqueue('revoked-before-retry')
        self.flow.deliver(job, fail_after_audit=True)
        self.flow.revoke(job)
        result = self.flow.recover(job)
        self.assertEqual(result['status'], 'access_revoked')
        self.assertEqual(result['export_count'], 0)

    def test_changed_candidate_and_stale_application_are_refused(self):
        self.flow.choose('delivery-time')
        self.flow.construct_and_check(ROOT/'evidence'/'muse-events.jsonl')
        (self.root/'candidate.go').write_text('tampered')
        with self.assertRaises(owner_flow.EvidenceMismatch): self.flow.apply()
        self.assertEqual(self.flow.view()['application']['state'], 'not_applied')
        self.assertTrue(any(r['kind'] == 'application_refused' for r in self.flow.receipts()))

    def test_missing_model_evidence_is_recorded_and_not_applied(self):
        self.flow.choose('delivery-time')
        with self.assertRaises(FileNotFoundError):
            self.flow.construct_and_check(self.root/'missing-events.jsonl')
        self.assertTrue(any(r['kind'] == 'checks_failed' for r in self.flow.receipts()))
        self.assertEqual(self.flow.view()['application']['state'], 'not_applied')

    def test_model_events_hash_matches_the_bytes_used_to_generate_candidate(self):
        self.flow.choose('delivery-time')
        original = (ROOT/'evidence'/'muse-events.jsonl').read_bytes()
        events = self.root/'input-events.jsonl'
        events.write_bytes(original)
        parse = owner_flow.delivery.model_output
        def change_input_after_capture(path):
            events.write_text('changed after capture')
            return parse(path)
        with mock.patch.object(owner_flow.delivery, 'model_output', side_effect=change_input_after_capture):
            checks = self.flow.construct_and_check(events)
        self.assertEqual(checks['model_events_sha256'], owner_flow.delivery.digest(original))
        self.assertEqual((self.root/'muse-events.jsonl').read_bytes(), original)

    def test_missing_wrong_or_unrelated_meta_model_configuration_is_refused(self):
        original = [json.loads(line) for line in (ROOT/'evidence'/'muse-events.jsonl').read_text().splitlines()]
        for variant in ('missing', 'wrong_provider', 'wrong_model', 'unrelated'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temp:
                flow = owner_flow.Flow(Path(temp))
                flow.create('Report')
                flow.choose('delivery-time')
                rows = json.loads(json.dumps(original))
                configs = [r for r in rows if r.get('payload_type') == 'run.model.configured']
                if variant == 'missing':
                    rows = [r for r in rows if r.get('payload_type') != 'run.model.configured']
                elif variant == 'wrong_provider':
                    configs[0]['payload']['provider_id'] = 'another-provider'
                elif variant == 'wrong_model':
                    configs[0]['payload']['model_id'] = 'not-muse'
                else:
                    configs[0]['payload']['command_id'] = 'a-different-run'
                events = Path(temp)/'input.jsonl'
                events.write_text(''.join(json.dumps(row)+'\n' for row in rows))
                with self.assertRaisesRegex(ValueError, 'model configuration'):
                    flow.construct_and_check(events)
                self.assertIsNone(flow.view()['checks'])
                self.assertTrue(any(r['kind'] == 'checks_failed' for r in flow.receipts()))
                with self.assertRaises(owner_flow.InvalidState):
                    flow.apply()

    def test_failed_recheck_invalidates_prior_evidence_but_preserves_history(self):
        self.flow.choose('delivery-time')
        previous = self.flow.construct_and_check(ROOT/'evidence'/'muse-events.jsonl')
        with self.assertRaises(FileNotFoundError):
            self.flow.construct_and_check(self.root/'missing-events.jsonl')
        self.assertIsNone(self.flow.view()['checks'])
        self.assertTrue(any(r['kind'] == 'checks_completed' and r['detail']['candidate']['sha256'] == previous['candidate']['sha256'] for r in self.flow.receipts()))
        self.assertTrue(any(r['kind'] == 'checks_failed' for r in self.flow.receipts()))
        with self.assertRaises(owner_flow.InvalidState):
            self.flow.apply()
        self.assertEqual(self.flow.view()['application']['state'], 'not_applied')

    def test_changed_or_missing_provenance_refuses_application(self):
        for filename in ('muse-events.jsonl', 'checker.py'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp:
                flow = owner_flow.Flow(Path(temp))
                flow.create('Report')
                flow.choose('delivery-time')
                checks = flow.construct_and_check(ROOT/'evidence'/'muse-events.jsonl')
                if filename == 'checker.py':
                    (Path(temp)/'checkers'/(checks['checker_sha256']+'.py')).unlink()
                (Path(temp)/filename).write_text('tampered')
                with self.assertRaises(owner_flow.EvidenceMismatch):
                    flow.apply()
                self.assertEqual(flow.view()['application']['state'], 'not_applied')
                self.assertTrue(any(r['kind'] == 'application_refused' for r in flow.receipts()))

    def test_mutation_of_applied_source_preserves_failure_receipt(self):
        self.flow.choose('delivery-time')
        self.flow.construct_and_check(ROOT/'evidence'/'muse-events.jsonl')
        self.flow.apply()
        job = self.flow.enqueue('stale applied source')
        (self.root/'service.go').write_text('altered')
        self.assertEqual(self.flow.deliver(job)['status'], 'interrupted')
        self.assertEqual(self.flow.job(job)['export_count'], 0)
        self.assertTrue(any(r['kind'] == 'attempt_failed' for r in self.flow.receipts()))

if __name__ == '__main__':
    unittest.main()
