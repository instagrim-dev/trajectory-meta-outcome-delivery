from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_owner_flow import ROOT
import owner_flow


class ResolutionFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.flow = owner_flow.Flow(self.root)
        self.flow.create('Synthetic records were delivered after staff access was revoked.')
        self.flow.reproduce()
        self.flow.choose('delivery-time')
        self.calls = 0

    def runner(self, attempt):
        self.calls += 1
        events = attempt/'events.jsonl'
        events.write_bytes((ROOT/'evidence'/'muse-events.jsonl').read_bytes())
        return {'events_path':events, 'elapsed_seconds':0.5}

    def test_one_authorized_action_checks_applies_and_observes_replay(self):
        result = self.flow.resolve(runner=self.runner)
        state = self.flow.view()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['model_attempts'], 1)
        self.assertEqual(result['max_model_attempts'], 1)
        self.assertEqual(self.calls, 1)
        self.assertEqual(state['checks']['candidate']['verdict'], 'satisfied')
        self.assertEqual(state['application']['sha256'], state['checks']['candidate']['sha256'])
        self.assertEqual(state['replay']['status'], 'access_revoked')
        self.assertEqual(state['replay']['export_count'], 0)
        self.assertEqual(self.flow.resolve(runner=self.runner)['state'], 'completed')
        self.assertEqual(self.calls, 1)

    def test_failed_generation_retains_budget_and_cannot_silently_repeat(self):
        def fail(_):
            self.calls += 1
            raise RuntimeError('provider failure')
        result = self.flow.resolve(runner=fail)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['stage'], 'synthesis')
        self.assertEqual(result['model_attempts'], 1)
        self.assertEqual(self.flow.resume_resolution()['state'], 'failed')
        self.assertEqual(self.flow.resolve(runner=fail)['state'], 'failed')
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.flow.view()['application']['state'], 'not_applied')

    def test_wrong_candidate_stops_at_checks_without_application(self):
        import json
        def wrong(attempt):
            self.calls += 1
            rows = [json.loads(line) for line in (ROOT/'evidence'/'muse-events.jsonl').read_text().splitlines()]
            for row in rows:
                if row.get('payload_type') == 'run.terminal.completed':
                    row['payload']['text'] = owner_flow.delivery.BASELINE
            events = attempt/'events.jsonl'
            events.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            return {'events_path':events, 'elapsed_seconds':0.5}
        result = self.flow.resolve(runner=wrong)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['stage'], 'checking')
        self.assertEqual(self.flow.view()['checks']['candidate']['verdict'], 'violated')
        self.assertEqual(self.flow.view()['application']['state'], 'not_applied')
        self.assertIsNone(self.flow.view()['replay'])
        self.assertEqual(self.flow.resume_resolution()['stage'], 'checking')
        self.assertEqual(self.calls, 1)

    def test_resume_recovers_same_interrupted_replay_without_new_model_call(self):
        with patch.object(self.flow, '_evaluate_applied', side_effect=RuntimeError('simulated interruption')):
            result = self.flow.resolve(runner=self.runner)
        self.assertEqual(result['state'], 'interrupted')
        job_id = self.flow.view()['replay']['job_id']
        result = self.flow.resume_resolution()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(self.flow.view()['replay']['job_id'], job_id)
        self.assertEqual(self.flow.view()['replay']['export_count'], 0)
        self.assertEqual(self.calls, 1)
        self.assertEqual(result['model_attempts'], 1)

    def test_resume_after_checks_before_binding_retains_one_attempt(self):
        update = self.flow._resolution_update
        def crash_before_binding(state, stage, **detail):
            if stage == 'checking':
                raise SystemExit('simulated exit after checks')
            return update(state, stage, **detail)
        with patch.object(self.flow, '_resolution_update', side_effect=crash_before_binding):
            with self.assertRaises(SystemExit):
                self.flow.resolve(runner=self.runner)
        self.assertEqual(self.flow.view()['checks']['candidate']['verdict'], 'satisfied')
        result = owner_flow.Flow(self.root).resume_resolution()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['model_attempts'], 1)
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.flow.view()['replay']['export_count'], 0)

    def test_resume_will_not_rebind_checks_with_changed_attempt_identity(self):
        update = self.flow._resolution_update
        def crash_before_binding(state, stage, **detail):
            if stage == 'checking': raise SystemExit('simulated exit after checks')
            return update(state, stage, **detail)
        with patch.object(self.flow, '_resolution_update', side_effect=crash_before_binding):
            with self.assertRaises(SystemExit): self.flow.resolve(runner=self.runner)
        with self.flow.connect() as db:
            checks = self.flow.get(db, 'checks')
            checks['response_origin']['attempt_id'] = 'different-attempt'
            self.flow.put(db, 'checks', checks)
        result = owner_flow.Flow(self.root).resume_resolution()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(self.flow.view()['application']['state'], 'not_applied')
        self.assertIsNone(self.flow.view()['replay'])
        self.assertEqual(self.calls, 1)

    def test_resume_after_queue_interruption_reuses_same_replay_job(self):
        with patch.object(self.flow, 'revoke', side_effect=SystemExit('simulated process exit')):
            with self.assertRaises(SystemExit):
                self.flow.resolve(runner=self.runner)
        with self.flow.connect() as db:
            jobs = db.execute("SELECT id FROM jobs WHERE request_label='original journey replay'").fetchall()
        self.assertEqual(len(jobs), 1)
        original_job = jobs[0]['id']
        resumed = owner_flow.Flow(self.root).resume_resolution()
        self.assertEqual(resumed['state'], 'completed')
        self.assertEqual(resumed['replay_job_id'], original_job)
        self.assertEqual(self.flow.job(original_job)['export_count'], 0)
        with self.flow.connect() as db:
            jobs = db.execute("SELECT id FROM jobs WHERE request_label='original journey replay'").fetchall()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(self.calls, 1)

    def test_resume_after_terminal_replay_preserves_job_and_outcome(self):
        deliver = self.flow.deliver
        def crash_after_delivery(job_id, *args, **kwargs):
            deliver(job_id, *args, **kwargs)
            raise SystemExit('simulated exit before replay observation')
        with patch.object(self.flow, 'deliver', side_effect=crash_after_delivery):
            with self.assertRaises(SystemExit):
                self.flow.resolve(runner=self.runner)
        with self.flow.connect() as db:
            jobs = db.execute("SELECT id, status FROM jobs WHERE request_label='original journey replay'").fetchall()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['status'], 'access_revoked')
        job_id = jobs[0]['id']
        result = owner_flow.Flow(self.root).resume_resolution()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['replay_job_id'], job_id)
        self.assertEqual(self.flow.view()['replay']['export_count'], 0)
        with self.flow.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE request_label='original journey replay'").fetchone()[0], 1)
        self.assertEqual(self.calls, 1)

    def test_resume_after_source_application_before_receipt(self):
        apply_checked = owner_flow.delivery.apply_checked
        def crash_after_write(*args):
            apply_checked(*args)
            raise SystemExit('simulated exit before application receipt')
        with patch.object(owner_flow.delivery, 'apply_checked', side_effect=crash_after_write):
            with self.assertRaises(SystemExit):
                self.flow.resolve(runner=self.runner)
        self.assertEqual(self.flow.view()['application']['state'], 'not_applied')
        result = owner_flow.Flow(self.root).resume_resolution()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(self.flow.view()['application']['sha256'], self.flow.view()['checks']['candidate']['sha256'])
        self.assertEqual(self.flow.view()['replay']['export_count'], 0)
        self.assertEqual(self.calls, 1)

    def test_resume_refuses_changed_model_evidence(self):
        with patch.object(self.flow, '_evaluate_applied', side_effect=RuntimeError('simulated interruption')):
            result = self.flow.resolve(runner=self.runner)
        self.assertEqual(result['state'], 'interrupted')
        (self.root/'muse-events.jsonl').write_text('changed')
        result = self.flow.resume_resolution()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['stage'], 'provenance')
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.flow.view()['replay']['status'], 'interrupted')


if __name__ == '__main__': unittest.main()
