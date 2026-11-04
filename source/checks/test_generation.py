from pathlib import Path
import tempfile
import unittest

from test_owner_flow import ROOT
import owner_flow


class GenerationFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.flow = owner_flow.Flow(self.root)
        self.flow.create('Synthetic records were delivered after access was revoked.')
        self.flow.choose('delivery-time')

    def test_receipt_records_sanitized_process_exit(self):
        self.flow.reproduce()
        def runner(attempt):
            events = attempt / 'events.jsonl'
            events.write_bytes((ROOT / 'evidence' / 'muse-events.jsonl').read_bytes())
            return {'events_path': events, 'elapsed_seconds': 0.5, 'process_exit_code': 0}
        self.flow.synthesize_and_check(runner=runner)
        self.assertIn('process exit: 0', self.flow.receipt())

    def test_failed_process_exit_is_retained_without_diagnostics(self):
        import model_runner
        self.flow.reproduce()
        def runner(_):
            raise model_runner.GenerationError('confidential diagnostic', process_exit_code=7)
        with self.assertRaises(owner_flow.InvalidState):
            self.flow.synthesize_and_check(runner=runner)
        receipt = self.flow.receipt()
        self.assertIn('process exit: 7', receipt)
        self.assertNotIn('confidential diagnostic', receipt)

    def test_generation_requires_a_reproduced_baseline(self):
        with self.assertRaises(owner_flow.InvalidState):
            self.flow.synthesize_and_check(runner=lambda _: self.fail('must not run'))

    def test_generated_response_is_checked_and_retained_per_attempt(self):
        self.flow.reproduce()
        def runner(attempt):
            events = attempt / 'events.jsonl'
            events.write_bytes((ROOT / 'evidence' / 'muse-events.jsonl').read_bytes())
            return {'events_path': events, 'elapsed_seconds': 1.25}
        checks = self.flow.synthesize_and_check(runner=runner)
        self.assertEqual(checks['candidate']['verdict'], 'satisfied')
        self.assertEqual(checks['model'], 'meta-models/muse-spark-open-1026')
        history = self.flow.receipts()
        completed = [r for r in history if r['kind'] == 'generation_completed']
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]['detail']['elapsed_seconds'], 1.25)
        self.assertEqual(checks['model_events_sha256'], completed[0]['detail']['events_sha256'])
        self.assertIn('Model process elapsed: 1.25 seconds', self.flow.receipt())
        self.assertIn('Response origin: synthesis attempt', self.flow.receipt())
        self.assertNotIn('retained earlier response', self.flow.receipt())
        self.assertEqual(self.flow.apply()['sha256'], checks['candidate']['sha256'])

    def test_later_supplied_events_are_not_attributed_to_earlier_generation(self):
        self.flow.reproduce()
        def runner(attempt):
            events = attempt / 'events.jsonl'
            events.write_bytes((ROOT / 'evidence' / 'muse-events.jsonl').read_bytes())
            return {'events_path': events, 'elapsed_seconds': 0.5}
        self.flow.synthesize_and_check(runner=runner)
        self.flow.construct_and_check(ROOT / 'evidence' / 'muse-events.jsonl')
        self.assertIn('Response origin: supplied retained event file', self.flow.receipt())
        self.assertNotIn('Response origin: synthesis attempt', self.flow.receipt())
        self.assertNotIn('Model process elapsed: 0.5 seconds', self.flow.receipt())
        self.assertIn('Model process time: not recorded for this check', self.flow.receipt())

    def test_failed_generation_invalidates_old_checks_and_preserves_failure(self):
        self.flow.reproduce()
        self.flow.construct_and_check(ROOT / 'evidence' / 'muse-events.jsonl')
        def fail(attempt):
            raise RuntimeError('provider failed with confidential diagnostic')
        with self.assertRaises(owner_flow.InvalidState):
            self.flow.synthesize_and_check(runner=fail)
        self.assertIsNone(self.flow.view()['checks'])
        with self.assertRaises(owner_flow.InvalidState): self.flow.apply()
        failed = [r for r in self.flow.receipts() if r['kind'] == 'generation_failed']
        self.assertEqual(len(failed), 1)
        self.assertNotIn('confidential diagnostic', str(failed))
        self.assertIn('Synthesis attempt failed', self.flow.receipt())

    def test_cannot_generate_after_application(self):
        self.flow.construct_and_check(ROOT / 'evidence' / 'muse-events.jsonl')
        self.flow.apply()
        with self.assertRaises(owner_flow.InvalidState):
            self.flow.synthesize_and_check(runner=lambda _: self.fail('must not run'))


class MuseRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_runner_passes_credential_via_stdin_and_retains_redacted_events(self):
        from unittest.mock import patch
        import json, os, model_runner
        fixture = ROOT / 'evidence' / 'muse-events.jsonl'
        executable = self.root / 'fake-muse'
        executable.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
key = sys.stdin.readline().strip()
pathlib.Path(os.environ['TRACE_PATH']).write_text(json.dumps({'args':sys.argv[1:], 'environment_has_key':'BASETEN_API_KEY' in os.environ, 'stdin_ok':key=='example-secret'}))
sys.stdout.write(pathlib.Path(os.environ['FIXTURE_PATH']).read_text())
''')
        executable.chmod(0o700)
        attempt = self.root / 'attempt'; attempt.mkdir()
        with patch.dict(os.environ, {'BASETEN_API_KEY':'example-secret', 'TRACE_PATH':str(attempt/'trace.json'), 'FIXTURE_PATH':str(fixture)}):
            result = model_runner.generate(attempt, executable=str(executable))
        trace = json.loads((attempt/'trace.json').read_text())
        self.assertTrue(trace['stdin_ok'])
        self.assertFalse(trace['environment_has_key'])
        self.assertNotIn('example-secret', str(trace['args']))
        self.assertIn('--api-key-stdin', trace['args'])
        self.assertEqual(Path(result['events_path']).read_bytes(), fixture.read_bytes())
        self.assertGreaterEqual(result['elapsed_seconds'], 0)
        self.assertEqual(result['process_exit_code'], 0)

    def test_failed_provider_output_is_retained_without_credential(self):
        from unittest.mock import patch
        import os, model_runner
        executable = self.root / 'fake-muse'
        executable.write_text('#!/usr/bin/env python3\nimport sys\ns=sys.stdin.readline().strip()\nprint("partial:"+s)\nprint("error:"+s,file=sys.stderr)\nsys.exit(7)\n')
        executable.chmod(0o700)
        attempt = self.root / 'attempt'; attempt.mkdir()
        with patch.dict(os.environ, {'BASETEN_API_KEY':'example-secret'}):
            with self.assertRaises(model_runner.GenerationError) as raised:
                model_runner.generate(attempt, executable=str(executable))
        self.assertEqual(raised.exception.process_exit_code, 7)
        self.assertIn('[redacted]', (attempt/'events.jsonl').read_text())
        self.assertNotIn('example-secret', (attempt/'stderr.log').read_text())

class GenerationBridgeTests(unittest.TestCase):
    def test_native_action_invokes_generation_and_returns_checked_candidate(self):
        import json, threading
        from urllib.request import Request, urlopen
        import native_bridge
        with tempfile.TemporaryDirectory() as tmp:
            def runner(attempt):
                events = attempt / 'events.jsonl'
                events.write_bytes((ROOT/'evidence'/'muse-events.jsonl').read_bytes())
                return {'events_path':events, 'elapsed_seconds': 0.5}
            server = native_bridge.make_server(Path(tmp), port=0, generation_runner=runner)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}/action'
                def send(action, **fields):
                    data = json.dumps({'action':action, **fields}).encode()
                    with urlopen(Request(url,data=data,headers={'Content-Type':'application/json'})) as response:
                        return json.load(response)
                send('report', description='Synthetic revoked-access delivery')
                send('reproduce')
                send('decide', choice='delivery-time')
                state = send('synthesize')
                self.assertEqual(state['checks']['candidate']['verdict'], 'satisfied')
                self.assertTrue(any(r['kind'] == 'generation_completed' for r in state['receipts']))
            finally:
                server.shutdown(); server.server_close(); thread.join(3)

class GenerationGuideTests(unittest.TestCase):
    def test_guide_can_synthesize_and_replay_using_configured_process(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); bindir = root/'bin'; bindir.mkdir()
            fake = bindir/'muse'
            fake.write_text('#!/usr/bin/env python3\nimport os,pathlib,sys\nsys.stdin.readline()\nsys.stdout.write(pathlib.Path(os.environ["FIXTURE_PATH"]).read_text())\n')
            fake.chmod(0o700)
            env = os.environ.copy()
            env.update({'PATH':str(bindir)+os.pathsep+env['PATH'], 'BASETEN_API_KEY':'not-a-real-key', 'FIXTURE_PATH':str(ROOT/'evidence'/'muse-events.jsonl')})
            workspace = root/'run'
            p = subprocess.run([sys.executable,str(ROOT/'owner_flow.py'),'--workspace',str(workspace),'guide','--synthesize'],input='Synthetic delivery after revocation\n1\n',text=True,capture_output=True,env=env,timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            state = owner_flow.Flow(workspace).view()
            self.assertEqual(state['replay']['status'], 'access_revoked')
            self.assertEqual(state['replay']['export_count'], 0)
            self.assertTrue(any(r['kind']=='generation_completed' for r in state['receipts']))


if __name__ == '__main__': unittest.main()
