import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import native_bridge

class NativeBridgeTests(unittest.TestCase):
    def test_resolve_action_runs_one_bounded_attempt_and_reports_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def runner(attempt):
                calls.append(1)
                events = attempt/'events.jsonl'
                events.write_bytes((ROOT/'evidence'/'muse-events.jsonl').read_bytes())
                return {'events_path': events, 'elapsed_seconds': 0.1}
            server = native_bridge.make_server(Path(tmp), port=0, generation_runner=runner)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 3)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            url = 'http://127.0.0.1:%d/action' % server.server_port
            def send(action, **fields):
                data = json.dumps({'action':action, **fields}).encode()
                with urlopen(Request(url, data=data, headers={'Content-Type':'application/json'})) as response:
                    return json.load(response)
            send('report', description='Exported after revocation')
            send('reproduce')
            send('decide', choice='delivery-time')
            state = send('resolve')
            self.assertEqual(state['resolution']['state'], 'completed')
            self.assertEqual(state['replay']['status'], 'access_revoked')
            self.assertEqual(state['replay']['export_count'], 0)
            self.assertEqual(state['application']['sha256'], state['checks']['candidate']['sha256'])
            self.assertEqual(len(calls), 1)
            self.assertEqual(send('resolve')['resolution']['state'], 'completed')
            self.assertEqual(len(calls), 1)

    def test_request_time_choice_returns_observed_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = native_bridge.make_server(Path(tmp), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 3)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            url = 'http://127.0.0.1:%d/action' % server.server_port
            def send(action, **fields):
                data = json.dumps({'action':action, **fields}).encode()
                with urlopen(Request(url, data=data, headers={'Content-Type':'application/json'})) as response:
                    return json.load(response)
            send('report', description='Records released after revocation')
            send('reproduce')
            state = send('decide', choice='request-time')
            self.assertEqual(state['decision'], 'request-time')
            self.assertEqual(state['request_time_replay']['status'], 'exported')
            self.assertEqual(state['request_time_replay']['audit_count'], 1)
            self.assertEqual(state['request_time_replay']['export_count'], 1)
            self.assertIn('Request-time replay', state['readable_receipt'])
            self.assertFalse(any(r['kind']=='generation_started' for r in state['receipts']))

    def test_native_operations_return_real_persisted_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = native_bridge.make_server(Path(tmp), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 3)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            url = 'http://127.0.0.1:%d/action' % server.server_port
            def send(action, **fields):
                data = json.dumps({'action':action, **fields}).encode()
                with urlopen(Request(url, data=data, headers={'Content-Type':'application/json'})) as response:
                    return json.load(response)
            s = send('report', description='Exported after revocation')
            self.assertEqual(s['report'], 'Exported after revocation')
            self.assertEqual(send('reproduce')['baseline']['status'], 'exported')
            send('decide', choice='delivery-time')
            self.assertEqual(send('check')['checks']['candidate']['verdict'], 'satisfied')
            self.assertEqual(send('apply')['application']['state'], 'applied')
            self.assertEqual(send('replay')['replay']['status'], 'access_revoked')
            self.assertEqual(send('interrupt')['recovery']['status'], 'interrupted')
            state = send('recover')
            self.assertEqual(state['recovery']['status'], 'exported')
            self.assertEqual(state['recovery']['audit_count'], 1)
            self.assertEqual(state['recovery']['export_count'], 1)
            self.assertTrue(state['source'].startswith('package main'))
            self.assertIn('Exported after revocation', state['readable_receipt'])
            self.assertIn('access_revoked', state['readable_receipt'])
            self.assertIn(state['application']['sha256'], state['readable_receipt'])
            self.assertIn('recovery_completed', state['readable_receipt'])

if __name__ == '__main__': unittest.main()
