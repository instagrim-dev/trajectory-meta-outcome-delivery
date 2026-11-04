import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import delivery


class DeliveryTests(unittest.TestCase):
    def test_outcome_is_bound_to_candidate_and_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = delivery.run(pathlib.Path(tmp), ROOT / 'evidence' / 'muse-events.jsonl')
            self.assertEqual(report['baseline']['verdict'], 'violated')
            self.assertEqual(report['wrong_fix']['verdict'], 'violated')
            self.assertEqual(report['candidate']['verdict'], 'satisfied')
            self.assertEqual(report['candidate']['sha256'], report['application']['sha256'])
            self.assertEqual(report['replay']['status'], 'access_revoked')
            self.assertEqual(report['replay']['events'], [])

    def test_failed_candidate_process_is_inconclusive(self):
        fn = 'func deliver(allowed bool, events *[]string) string { os.Exit(7); return "" }'
        with tempfile.TemporaryDirectory() as tmp:
            result = delivery.evaluate(delivery.source(fn), pathlib.Path(tmp))
        self.assertEqual(result['verdict'], 'inconclusive')
        self.assertTrue(all(case['satisfied'] is None for case in result['cases']))
        self.assertTrue(all(case['exit'] == 7 for case in result['cases']))

    def test_malformed_candidate_output_is_inconclusive(self):
        fn = 'func deliver(allowed bool, events *[]string) string { os.Stdout.WriteString("invalid-json"); os.Exit(0); return "" }'
        with tempfile.TemporaryDirectory() as tmp:
            result = delivery.evaluate(delivery.source(fn), pathlib.Path(tmp))
        self.assertEqual(result['verdict'], 'inconclusive')
        self.assertTrue(all(case['satisfied'] is None for case in result['cases']))

    def test_model_output_rejects_extra_same_line_function(self):
        malicious = 'func deliver(allowed bool, events *[]string) string { return "exported" }; func init() { os.Exit(0) }'
        with tempfile.TemporaryDirectory() as tmp:
            events = pathlib.Path(tmp) / 'events.jsonl'
            events.write_text(json.dumps({'payload_type': 'run.terminal.completed', 'payload': {'terminal': 'completed', 'text': malicious}}) + '\n')
            with self.assertRaisesRegex(ValueError, 'scope'):
                delivery.model_output(events)

    def test_model_output_rejects_operating_system_calls(self):
        malicious = 'func deliver(allowed bool, events *[]string) string { os.Exit(0); return "exported" }'
        with tempfile.TemporaryDirectory() as tmp:
            events = pathlib.Path(tmp) / 'events.jsonl'
            events.write_text(json.dumps({'payload_type': 'run.terminal.completed', 'payload': {'terminal': 'completed', 'text': malicious}}) + '\n')
            with self.assertRaisesRegex(ValueError, 'scope'):
                delivery.model_output(events)

    def test_scope_accepts_a_distinct_valid_policy(self):
        candidate = 'func deliver(allowed bool, events *[]string) string { if allowed { *events = append(*events, "audit", "release"); return "exported" }; return "access_revoked" }'
        delivery.validate_scope(candidate)

    def test_scope_rejects_go_compiler_directives(self):
        candidate = 'func deliver(allowed bool, events *[]string) string { /*go:directive*/ return "exported" }'
        with self.assertRaisesRegex(ValueError, 'scope'):
            delivery.validate_scope(candidate)

    def test_stale_preimage_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / 'service.go'
            target.write_text('changed')
            with self.assertRaises(delivery.StalePreimage):
                delivery.apply_checked(target, 'expected-hash', b'candidate', delivery.digest(b'candidate'))
            self.assertEqual(target.read_text(), 'changed')

    def test_changed_candidate_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / 'service.go'
            target.write_bytes(b'baseline')
            with self.assertRaises(delivery.StaleCandidate):
                delivery.apply_checked(target, delivery.digest(b'baseline'), b'changed', delivery.digest(b'checked'))
            self.assertEqual(target.read_bytes(), b'baseline')

if __name__ == '__main__':
    unittest.main()
