"""Loopback bridge for the private Trajectory simulator demonstration."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys

import owner_flow

ROOT = Path(__file__).resolve().parent

def make_server(workspace, port=8139, generation_runner=None):
    flow = owner_flow.Flow(workspace)

    def state():
        current = flow.view()
        with flow.connect() as db:
            job_id = flow.get(db, 'recovery_job')
        current['recovery'] = flow.job(job_id) if job_id else None
        source = flow.root/'candidate.go'
        current['source'] = source.read_text() if source.exists() else None
        current['readable_receipt'] = flow.receipt() if current['report'] is not None else None
        return current

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != '/state': return self.reply(404, {'error':'Unknown route'})
            return self.reply(200,state())

        def do_POST(self):
            if self.path != '/action': return self.reply(404, {'error':'Unknown route'})
            if self.headers.get('Origin') or self.headers.get_content_type() != 'application/json':
                return self.reply(403, {'error':'Local app requests only'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if length <= 0 or length > 8192: return self.reply(400, {'error':'Invalid request size'})
                body = json.loads(self.rfile.read(length))
                action = body.get('action')
                if action == 'report': flow.create(body.get('description',''))
                elif action == 'reproduce': flow.reproduce()
                elif action == 'decide': flow.choose(body.get('choice',''))
                elif action == 'resume_request_time': flow.resume_request_time()
                elif action == 'check': flow.construct_and_check(ROOT/'evidence'/'muse-events.jsonl')
                elif action == 'synthesize': flow.synthesize_and_check(runner=generation_runner)
                elif action == 'resolve': flow.resolve(runner=generation_runner)
                elif action == 'resume_resolution': flow.resume_resolution()
                elif action == 'apply': flow.apply()
                elif action == 'replay': flow.replay()
                elif action == 'interrupt':
                    with flow.connect() as db:
                        if flow.get(db,'recovery_job'): raise owner_flow.InvalidState('Recovery scenario already exists')
                    job = flow.enqueue('interrupted authorized delivery')
                    with flow.connect() as db: flow.put(db,'recovery_job',job)
                    flow.deliver(job,fail_after_audit=True)
                elif action == 'recover':
                    with flow.connect() as db: job = flow.get(db,'recovery_job')
                    if not job: raise owner_flow.InvalidState('No interrupted attempt')
                    flow.recover(job)
                else: return self.reply(400, {'error':'Unknown action'})
                return self.reply(200,state())
            except (ValueError, OSError, owner_flow.InvalidState, owner_flow.EvidenceMismatch) as exc:
                return self.reply(400, {'error':str(exc)})

    return HTTPServer(('127.0.0.1',port), Handler)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--port',type=int,default=8139)
    args = parser.parse_args()
    server = make_server(args.workspace,args.port)
    print('Private owner bridge on 127.0.0.1:%s' % server.server_port, flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
