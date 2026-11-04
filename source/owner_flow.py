"""Private owner-driven, synthetic queued-records delivery demonstration."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import uuid

import delivery


class EvidenceMismatch(Exception): pass
class InvalidState(Exception): pass


class Flow:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.root / 'workbench.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request_label TEXT NOT NULL,
                    access INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS request_authorizations (job_id TEXT PRIMARY KEY, granted INTEGER NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id));
                CREATE TABLE IF NOT EXISTS audit (job_id TEXT PRIMARY KEY, detail TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id));
                CREATE TABLE IF NOT EXISTS exports (job_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id));
                CREATE TABLE IF NOT EXISTS receipts (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def put(db, key, value):
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?, ?)', (key, json.dumps(value)))

    @staticmethod
    def get(db, key, default=None):
        row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else default

    @staticmethod
    def record(db, kind, detail):
        db.execute('INSERT INTO receipts (kind, detail) VALUES (?, ?)', (kind, json.dumps(detail)))

    def create(self, report):
        if not report.strip(): raise ValueError('Describe the problem')
        source_path = self.root/'service.go'
        created = False
        try:
            with self.connect() as db:
                if self.get(db, 'report') is not None: raise InvalidState('Report already exists')
                try:
                    target = source_path.open('xb')
                except FileExistsError as exc:
                    raise InvalidState('Source already exists; refusing to overwrite') from exc
                created = True
                with target:
                    target.write(delivery.source(delivery.BASELINE))
                self.put(db, 'report', report)
                self.put(db, 'application', {'state':'not_applied'})
                self.record(db, 'report_received', {'report':report})
        except BaseException:
            if created:
                try: source_path.unlink(missing_ok=True)
                except OSError: pass
            raise
        return self.view()

    def choose(self, decision):
        if decision not in ('delivery-time', 'request-time'): raise ValueError('Unknown decision')
        with self.connect() as db:
            if self.get(db, 'report') is None: raise InvalidState('Start with a report')
            if self.get(db, 'decision') is not None: raise InvalidState('Decision already recorded')
            if decision == 'request-time':
                baseline = self.get(db, 'baseline') or {}
                grant = db.execute('SELECT granted FROM request_authorizations WHERE job_id=?', (baseline.get('job_id'),)).fetchone()
                if (not grant or grant['granted'] != 1 or baseline.get('status') != 'exported'
                        or baseline.get('access_at_delivery') is not False or baseline.get('audit_count') != 1
                        or baseline.get('export_count') != 1):
                    raise InvalidState('Reproduce an authorized request before choosing request time')
            self.put(db, 'decision', decision)
            self.record(db, 'decision_recorded', {'decision':decision, 'protected':'audit before release'})
            if decision == 'request-time':
                job_id = uuid.uuid4().hex
                db.execute('INSERT INTO jobs VALUES (?, ?, 1, ?, ?)', (job_id,'request-time replay','queued','synthetic customer records'))
                db.execute('INSERT INTO request_authorizations VALUES (?, 1)', (job_id,))
                self.put(db, 'request_time_replay_job', job_id)
                self.record(db, 'request_queued', {'job_id':job_id, 'label':'request-time replay', 'access_at_request':True})
        if decision == 'request-time': self.resume_request_time()

    def resume_request_time(self):
        with self.connect() as db:
            if self.get(db, 'decision') != 'request-time': raise InvalidState('Request time was not selected')
            job_id = self.get(db, 'request_time_replay_job')
        if not job_id: raise InvalidState('Request-time replay is missing')
        job = self.job(job_id)
        if job['status'] not in ('exported', 'access_revoked'):
            if job['access_at_delivery']: self.revoke(job_id)
            job = self.job(job_id)
            job = self.recover(job_id) if job['status'] == 'interrupted' else self.deliver(job_id)
        with self.connect() as db:
            self.put(db, 'request_time_replay', job)
            self.record(db, 'request_time_replay_observed', job)
        return job

    def enqueue(self, label):
        job_id = uuid.uuid4().hex
        with self.connect() as db:
            if self.get(db, 'report') is None: raise InvalidState('Start with a report')
            db.execute('INSERT INTO jobs VALUES (?, ?, 1, ?, ?)', (job_id,label,'queued','synthetic customer records'))
            db.execute('INSERT INTO request_authorizations VALUES (?, 1)', (job_id,))
            self.record(db, 'request_queued', {'job_id':job_id, 'label':label, 'access_at_request':True})
        return job_id

    def revoke(self, job_id):
        with self.connect() as db:
            if db.execute('UPDATE jobs SET access=0 WHERE id=?', (job_id,)).rowcount != 1: raise KeyError(job_id)
            self.record(db, 'access_revoked', {'job_id':job_id})

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None: raise KeyError(job_id)
            return {'job_id':job_id, 'status':row['status'], 'access_at_delivery':bool(row['access']),
                    'audit_count':db.execute('SELECT COUNT(*) FROM audit WHERE job_id=?',(job_id,)).fetchone()[0],
                    'export_count':db.execute('SELECT COUNT(*) FROM exports WHERE job_id=?',(job_id,)).fetchone()[0]}

    def _evaluate_applied(self, allowed, baseline=False):
        with self.connect() as db:
            application = self.get(db, 'application', {})
            expected = delivery.digest(delivery.source(delivery.BASELINE)) if baseline else application.get('sha256')
        source = (self.root/'service.go').read_bytes()
        if not expected or delivery.digest(source) != expected: raise EvidenceMismatch('Applied source differs from checked source')
        with tempfile.TemporaryDirectory(prefix='policy-run-') as tmp:
            path, binary = Path(tmp)/'service.go', Path(tmp)/'service'
            path.write_bytes(source)
            build = subprocess.run(['go','build','-o',str(binary),str(path)], capture_output=True, text=True, timeout=60)
            if build.returncode: raise RuntimeError('Applied source failed to build')
            p = subprocess.run([str(binary)], input=json.dumps({'allowed':allowed}), capture_output=True, text=True, timeout=10)
            if p.returncode: raise RuntimeError('Policy process failed')
            data = json.loads(p.stdout)
            if data not in ({'status':'exported','events':['audit','release']}, {'status':'access_revoked','events':[]}):
                raise RuntimeError('Policy returned unsupported result')
            return data

    def deliver(self, job_id, fail_after_audit=False, baseline=False):
        state = self.job(job_id)
        if state['status'] in ('exported', 'access_revoked'): return state
        try:
            with self.connect() as db:
                request_time = not baseline and self.get(db, 'decision') == 'request-time'
                grant = db.execute('SELECT granted FROM request_authorizations WHERE job_id=?', (job_id,)).fetchone() if request_time else None
            if request_time and (not grant or grant['granted'] != 1):
                raise InvalidState('Request-time authorization is missing')
            policy = self._evaluate_applied(state['access_at_delivery'], baseline=baseline or request_time)
            if policy['status'] == 'access_revoked':
                with self.connect() as db:
                    db.execute("UPDATE jobs SET status='access_revoked' WHERE id=?",(job_id,))
                    self.record(db, 'delivery_blocked', {'job_id':job_id,'reason':'access_revoked'})
                return self.job(job_id)
            with self.connect() as db:
                db.execute('INSERT OR IGNORE INTO audit VALUES (?, ?)', (job_id, 'records release authorized'))
                db.execute("UPDATE jobs SET status='audited' WHERE id=?",(job_id,))
                self.record(db, 'audit_persisted', {'job_id':job_id})
            if fail_after_audit: raise RuntimeError('Injected interruption after durable audit')
            with self.connect() as db:
                # Recheck access on recovery and immediately before publication.
                row = db.execute('SELECT access,payload FROM jobs WHERE id=?',(job_id,)).fetchone()
                if not baseline and not request_time and not row['access']:
                    db.execute("UPDATE jobs SET status='access_revoked' WHERE id=?",(job_id,))
                    self.record(db, 'delivery_blocked', {'job_id':job_id,'reason':'access_revoked'})
                else:
                    db.execute('INSERT OR IGNORE INTO exports VALUES (?, ?)', (job_id,row['payload']))
                    db.execute("UPDATE jobs SET status='exported' WHERE id=?",(job_id,))
                    self.record(db, 'delivery_completed', {'job_id':job_id})
            return self.job(job_id)
        except (RuntimeError, EvidenceMismatch, subprocess.TimeoutExpired, ValueError, OSError) as exc:
            with self.connect() as db:
                db.execute("UPDATE jobs SET status='interrupted' WHERE id=?",(job_id,))
                self.record(db, 'attempt_failed', {'job_id':job_id,'error':str(exc)})
            return self.job(job_id)

    def recover(self, job_id):
        before = self.job(job_id)
        if before['status'] in ('exported', 'access_revoked'): return before
        if before['status'] != 'interrupted': raise InvalidState('Job has no interrupted attempt')
        with self.connect() as db: self.record(db, 'recovery_started', {'job_id':job_id})
        result = self.deliver(job_id)
        with self.connect() as db: self.record(db, 'recovery_completed' if result['status'] != 'interrupted' else 'recovery_failed', result)
        return result

    def reproduce(self):
        job = self.enqueue('baseline reproduction')
        self.revoke(job)
        result = self.deliver(job, baseline=True)
        with self.connect() as db:
            self.put(db, 'baseline', result)
            self.record(db, 'baseline_observed', result)
        return result

    def construct_and_check(self, events, *, synthesis_attempt_id=None):
        with self.connect() as db:
            if self.get(db,'decision') != 'delivery-time': raise InvalidState('Record the decision first')
            # Starting a new attempt invalidates old active checks even if this process
            # is interrupted. The earlier completed results remain in receipt history.
            db.execute("DELETE FROM metadata WHERE key='checks'")
            self.record(db, 'checks_started', {})
        try:
            event_bytes = Path(events).read_bytes()
            records = [json.loads(line) for line in event_bytes.splitlines()]
            terminals = [r.get('payload', {}) for r in records if isinstance(r, dict) and r.get('payload_type') == 'run.terminal.completed']
            command_id = terminals[0].get('command_id') if len(terminals) == 1 and isinstance(terminals[0], dict) else None
            configs = [r.get('payload', {}) for r in records if isinstance(r, dict) and r.get('payload_type') == 'run.model.configured' and isinstance(r.get('payload'), dict) and r['payload'].get('command_id') == command_id]
            if not command_id or len(configs) != 1 or configs[0].get('provider_id') != 'meta' or configs[0].get('model_id') != 'meta-models/muse-spark-open-1026':
                raise ValueError('Expected Meta Muse model configuration for completed run')
            config = configs[0]
            baseline = (self.root/'service.go').read_bytes()
            # Parse and hash the same captured bytes; the caller's input may change
            # while the candidate is being checked.
            with tempfile.TemporaryDirectory(prefix='policy-check-') as tmp:
                work = Path(tmp)
                snapshot = work/'model-events.jsonl'
                snapshot.write_bytes(event_bytes)
                candidate = delivery.source(delivery.model_output(snapshot))
                checks = {'baseline':delivery.evaluate(baseline, work), 'wrong_fix':delivery.evaluate(delivery.source(delivery.WRONG), work), 'candidate':delivery.evaluate(candidate, work)}
            checks['wrong_fix']['origin'] = 'authored control'
            checks['response_origin'] = {'kind':'synthesis_attempt', 'attempt_id':synthesis_attempt_id} if synthesis_attempt_id else {'kind':'supplied_event_file'}
            checks['model_events_sha256'] = delivery.digest(event_bytes)
            checks['model_events_file'] = 'muse-events.jsonl'
            checks['checker_sha256'] = delivery.digest(delivery.CHECKER_SOURCE)
            checks['model'] = config['model_id']
            checks['provider'] = config['provider_id']
            checks['transport'] = 'not attested by model event stream'
            (self.root/'checkers').mkdir(exist_ok=True)
            (self.root/'checkers'/f"{checks['checker_sha256']}.py").write_bytes(delivery.CHECKER_SOURCE)
            (self.root/'checker.py').write_bytes(delivery.CHECKER_SOURCE)
            (self.root/'muse-events.jsonl').write_bytes(event_bytes)
            (self.root/'candidate.go').write_bytes(candidate)
            with self.connect() as db:
                self.put(db, 'checks', checks)
                self.record(db, 'checks_completed', checks)
            return checks
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            with self.connect() as db: self.record(db, 'checks_failed', {'error':str(exc)})
            raise

    def synthesize_and_check(self, runner=None):
        with self.connect() as db:
            if self.get(db, 'decision') != 'delivery-time':
                raise InvalidState('Record the delivery-time decision first')
            if self.get(db, 'application', {}).get('state') == 'applied':
                raise InvalidState('This demonstration cannot revise an applied candidate')
            baseline = self.get(db, 'baseline')
            if not baseline or baseline.get('status') != 'exported' or baseline.get('access_at_delivery') is not False or baseline.get('export_count') != 1:
                raise InvalidState('Reproduce the revoked-access delivery first')
            db.execute("DELETE FROM metadata WHERE key='checks'")
            attempt_id = uuid.uuid4().hex
            self.record(db, 'generation_started', {'attempt_id': attempt_id})
        attempt = self.root/'generations'/attempt_id
        try:
            attempt.mkdir(parents=True, mode=0o700)
            if runner is None:
                import model_runner
                runner = model_runner.generate
            generated = runner(attempt)
            events = Path(generated['events_path']).resolve()
            events.relative_to(attempt.resolve())
            event_bytes = events.read_bytes()
            elapsed = generated['elapsed_seconds']
            if not isinstance(elapsed, (int, float)) or elapsed < 0:
                raise ValueError('Invalid generation duration')
            exit_code = generated.get('process_exit_code')
            if exit_code is not None and (type(exit_code) is not int or exit_code != 0):
                raise ValueError('Invalid successful process outcome')
            snapshot = attempt/'captured-events.jsonl'
            snapshot.write_bytes(event_bytes)
            with self.connect() as db:
                detail = {'attempt_id': attempt_id, 'events_sha256': delivery.digest(event_bytes), 'elapsed_seconds': elapsed}
                if exit_code is not None: detail['process_exit_code'] = exit_code
                self.record(db, 'generation_completed', detail)
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
            import model_runner
            detail = {'attempt_id': attempt_id, 'error': type(exc).__name__}
            exit_code = getattr(exc, 'process_exit_code', None) if isinstance(exc, model_runner.GenerationError) else None
            if type(exit_code) is int: detail['process_exit_code'] = exit_code
            with self.connect() as db: self.record(db, 'generation_failed', detail)
            message = str(exc) if isinstance(exc, model_runner.GenerationError) else 'Synthesis failed; the attempt is retained and no candidate was checked'
            raise InvalidState(message) from exc
        checks = self.construct_and_check(snapshot, synthesis_attempt_id=attempt_id)
        if checks['model_events_sha256'] != delivery.digest(event_bytes):
            with self.connect() as db:
                db.execute("DELETE FROM metadata WHERE key='checks'")
                self.record(db, 'checks_failed', {'error': 'Generated event snapshot changed'})
            raise EvidenceMismatch('Generated event snapshot changed during checking')
        return checks

    def apply(self):
        with self.connect() as db:
            checks = self.get(db,'checks')
            if not checks or checks['candidate']['verdict'] != 'satisfied' or checks['wrong_fix']['verdict'] != 'violated' or checks['baseline']['verdict'] != 'violated':
                raise InvalidState('Required checks are not satisfied')
        try:
            event_path = self.root/'muse-events.jsonl'
            if delivery.digest(event_path.read_bytes()) != checks.get('model_events_sha256'):
                raise EvidenceMismatch('Retained model events do not match checked evidence')
            checker_hash = checks.get('checker_sha256')
            snapshots = [self.root/'checkers'/f'{checker_hash}.py', self.root/'checker.py', Path(delivery.__file__).parent/'evidence'/'checkers'/f'{checker_hash}.py']
            def matches(path):
                try: return delivery.digest(path.read_bytes()) == checker_hash
                except FileNotFoundError: return False
            if not checker_hash or not any(matches(path) for path in snapshots):
                raise EvidenceMismatch('Retained checker does not match checked evidence')
            candidate = (self.root/'candidate.go').read_bytes()
            delivery.apply_checked(self.root/'service.go', checks['baseline']['sha256'], candidate, checks['candidate']['sha256'])
        except (delivery.StaleCandidate, delivery.StalePreimage, EvidenceMismatch, OSError) as exc:
            with self.connect() as db: self.record(db, 'application_refused', {'reason':type(exc).__name__})
            raise EvidenceMismatch('Source, candidate, or provenance no longer matches checked evidence') from exc
        with self.connect() as db:
            application = {'state':'applied', 'sha256':delivery.digest(candidate)}
            self.put(db,'application',application)
            self.record(db,'candidate_applied',application)
        return application

    def replay(self):
        with self.connect() as db:
            if self.get(db,'application',{}).get('state') != 'applied': raise InvalidState('Apply checked candidate first')
        job = self.enqueue('original journey replay')
        self.revoke(job)
        result = self.deliver(job)
        with self.connect() as db:
            self.put(db,'replay',result)
            self.record(db,'replay_observed',result)
        return result

    def _resolution_update(self, state, stage, **detail):
        with self.connect() as db:
            current = self.get(db, 'resolution')
            if not current: raise InvalidState('No authorized resolution')
            current.update(state=state, stage=stage, **detail)
            self.put(db, 'resolution', current)
            self.record(db, 'resolution_' + state, {'id':current['id'], 'stage':stage, **detail})
        return current

    def _resolution_evidence_matches(self, resolution):
        with self.connect() as db:
            checks = self.get(db, 'checks') or {}
            baseline = self.get(db, 'baseline') or {}
            decision = self.get(db, 'decision')
            application = self.get(db, 'application', {})
        if (decision != resolution.get('decision') or baseline.get('job_id') != resolution.get('baseline_job_id')
                or checks.get('model_events_sha256') != resolution.get('model_events_sha256')
                or checks.get('checker_sha256') != resolution.get('checker_sha256')
                or checks.get('candidate', {}).get('sha256') != resolution.get('candidate_sha256')
                or checks.get('candidate', {}).get('verdict') != 'satisfied'
                or checks.get('baseline', {}).get('verdict') != 'violated'
                or checks.get('wrong_fix', {}).get('verdict') != 'violated'):
            return False
        try:
            if delivery.digest((self.root/'muse-events.jsonl').read_bytes()) != resolution['model_events_sha256']:
                return False
            if delivery.digest((self.root/'candidate.go').read_bytes()) != resolution['candidate_sha256']:
                return False
            checker = self.root/'checkers'/f"{resolution['checker_sha256']}.py"
            if delivery.digest(checker.read_bytes()) != resolution['checker_sha256']:
                return False
            if application.get('state') == 'applied':
                if application.get('sha256') != resolution['candidate_sha256']:
                    return False
                if delivery.digest((self.root/'service.go').read_bytes()) != resolution['candidate_sha256']:
                    return False
        except (OSError, KeyError):
            return False
        return True

    def _resolution_replay(self, resume=False):
        # Persist the replay identity in the same transaction as its queue entry.
        # A restart can then continue that exact job, including after revocation
        # or delivery has already completed but the observation was not saved.
        with self.connect() as db:
            resolution = self.get(db, 'resolution')
            job_id = resolution.get('replay_job_id')
            if not job_id:
                prior = self.get(db, 'replay')
                if prior:
                    job_id = prior['job_id']
                else:
                    job_id = uuid.uuid4().hex
                    db.execute('INSERT INTO jobs VALUES (?, ?, 1, ?, ?)',
                               (job_id, 'original journey replay', 'queued', 'synthetic customer records'))
                    db.execute('INSERT INTO request_authorizations VALUES (?, 1)', (job_id,))
                    self.record(db, 'request_queued', {'job_id':job_id, 'label':'original journey replay', 'access_at_request':True})
                resolution['replay_job_id'] = job_id
                self.put(db, 'resolution', resolution)
        job = self.job(job_id)
        if job['status'] not in ('exported', 'access_revoked'):
            if job['access_at_delivery']:
                self.revoke(job_id)
            job = self.job(job_id)
            if job['status'] == 'interrupted' and resume:
                job = self.recover(job_id)
            elif job['status'] != 'interrupted':
                job = self.deliver(job_id)
        with self.connect() as db:
            self.put(db, 'replay', job)
            self.record(db, 'replay_observed', job)
        return job

    def _finish_resolution(self, resolution, *, resume=False):
        with self.connect() as db: checks = self.get(db, 'checks')
        if checks and (checks.get('candidate', {}).get('verdict') != 'satisfied' or checks.get('baseline', {}).get('verdict') != 'violated' or checks.get('wrong_fix', {}).get('verdict') != 'violated'):
            return self._resolution_update('failed', 'checking', reason='Required independent checks did not pass')
        if not self._resolution_evidence_matches(resolution):
            return self._resolution_update('failed', 'provenance', reason='Bound evidence is missing or changed')
        try:
            with self.connect() as db:
                application = self.get(db, 'application', {})
                replay = self.get(db, 'replay')
            if application.get('state') != 'applied':
                # If the process stopped after the checked atomic write but before
                # its receipt, reconcile the exact authorized bytes on restart.
                can_reconcile = (resume and resolution.get('stage') == 'application'
                    and delivery.digest((self.root/'service.go').read_bytes()) == resolution['candidate_sha256'])
                if can_reconcile:
                    application = {'state':'applied', 'sha256':resolution['candidate_sha256'], 'reconciled':True}
                    with self.connect() as db:
                        self.put(db, 'application', application)
                        self.record(db, 'candidate_applied', application)
                else:
                    self._resolution_update('running', 'application')
                    self.apply()
            self._resolution_update('running', 'replay')
            replay = self._resolution_replay(resume=resume)
            if replay.get('status') == 'interrupted':
                return self._resolution_update('interrupted', 'replay', replay_job_id=replay['job_id'])
            if replay.get('status') != 'access_revoked' or replay.get('export_count') != 0:
                return self._resolution_update('failed', 'replay', replay_job_id=replay.get('job_id'), reason='Expected blocked replay was not observed')
            return self._resolution_update('completed', 'replay', replay_job_id=replay['job_id'])
        except (InvalidState, EvidenceMismatch, ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return self._resolution_update('failed', 'application_or_replay', reason=type(exc).__name__)

    def resolve(self, runner=None):
        with self.connect() as db:
            existing = self.get(db, 'resolution')
            if existing: return existing
            baseline = self.get(db, 'baseline') or {}
            if self.get(db, 'decision') != 'delivery-time' or baseline.get('status') != 'exported' or baseline.get('access_at_delivery') is not False or baseline.get('export_count') != 1:
                raise InvalidState('Reproduce the revoked-access delivery and choose delivery time first')
            if self.get(db, 'application', {}).get('state') == 'applied':
                raise InvalidState('This workspace already has an applied candidate')
            resolution = {'id':uuid.uuid4().hex, 'state':'running', 'stage':'synthesis',
                          'decision':'delivery-time', 'baseline_job_id':baseline['job_id'],
                          'max_model_attempts':1, 'model_attempts':1}
            self.put(db, 'resolution', resolution)
            self.record(db, 'resolution_started', resolution)
        try:
            checks = self.synthesize_and_check(runner=runner)
            resolution = self._resolution_update('running', 'checking',
                model_events_sha256=checks['model_events_sha256'], checker_sha256=checks['checker_sha256'],
                candidate_sha256=checks['candidate']['sha256'])
        except (InvalidState, EvidenceMismatch, ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return self._resolution_update('failed', 'synthesis', reason=type(exc).__name__)
        return self._finish_resolution(resolution)

    def resume_resolution(self):
        with self.connect() as db: resolution = self.get(db, 'resolution')
        if not resolution: raise InvalidState('No authorized resolution to resume')
        if resolution['state'] == 'completed': return resolution
        if not all(resolution.get(k) for k in ('model_events_sha256','checker_sha256','candidate_sha256')):
            # Rebind only completed checks from the one attempt started after
            # this resolution; never infer provenance from matching bytes alone.
            with self.connect() as db:
                checks = self.get(db, 'checks') or {}
                rows = list(db.execute('SELECT id, kind, detail FROM receipts ORDER BY id'))
            receipts = [{'id':row['id'], 'kind':row['kind'], 'detail':json.loads(row['detail'])} for row in rows]
            starts = [r for r in receipts if r['kind'] == 'resolution_started' and r['detail'].get('id') == resolution['id']]
            after = [r for r in receipts if starts and r['id'] > starts[-1]['id']]
            generations = [r for r in after if r['kind'] == 'generation_started']
            origin = checks.get('response_origin') or {}
            attempt_id = origin.get('attempt_id')
            completed = [r for r in after if r['kind'] == 'generation_completed' and r['detail'].get('attempt_id') == attempt_id and r['detail'].get('events_sha256') == checks.get('model_events_sha256')]
            checked = [r for r in after if r['kind'] == 'checks_completed' and r['detail'] == checks]
            may_rebind = (resolution.get('state') == 'running' and resolution.get('stage') == 'synthesis'
                and resolution.get('model_attempts') == resolution.get('max_model_attempts') == 1
                and origin.get('kind') == 'synthesis_attempt' and attempt_id
                and len(generations) == len(completed) == len(checked) == 1
                and generations[0]['detail'].get('attempt_id') == attempt_id
                and generations[0]['id'] < completed[0]['id'] < checked[0]['id']
                and checks.get('checker_sha256') and checks.get('candidate', {}).get('sha256'))
            if not may_rebind:
                return self._resolution_update('failed', 'synthesis', reason='No bound checked candidate; no new model attempt was started')
            resolution = self._resolution_update('running', 'checking',
                model_events_sha256=checks['model_events_sha256'], checker_sha256=checks['checker_sha256'],
                candidate_sha256=checks['candidate']['sha256'])
        return self._finish_resolution(resolution, resume=True)

    def receipts(self):
        with self.connect() as db:
            return [{'id':r['id'],'kind':r['kind'],'created_at':r['created_at'],'detail':json.loads(r['detail'])} for r in db.execute('SELECT * FROM receipts ORDER BY id')]

    def receipt(self):
        import resolution_receipt
        return resolution_receipt.render(self)

    def view(self):
        with self.connect() as db:
            checks = self.get(db,'checks',{})
            return {'report':self.get(db,'report'), 'decision':self.get(db,'decision'), 'baseline':self.get(db,'baseline'), 'request_time_replay':self.get(db,'request_time_replay'), 'candidate_sha256':checks.get('candidate',{}).get('sha256'), 'checks':checks or None, 'application':self.get(db,'application',{'state':'not_applied'}), 'replay':self.get(db,'replay'), 'resolution':self.get(db,'resolution'), 'receipts':self.receipts()}

def main():
    parser = argparse.ArgumentParser(description='Private queued-records owner workbench')
    parser.add_argument('--workspace', required=True, type=Path)
    sub = parser.add_subparsers(dest='command',required=True)
    p = sub.add_parser('report', help='Describe the problem in your own words'); p.add_argument('description')
    sub.add_parser('reproduce', help='Reproduce the reported revoked-access delivery')
    p = sub.add_parser('decide', help='Choose when access controls delivery'); p.add_argument('choice', choices=['delivery-time','request-time'])
    p = sub.add_parser('check', help='Independently check a retained Muse response'); p.add_argument('--events',type=Path,required=True)
    sub.add_parser('synthesize', help='Synthesize and check a fresh candidate using the configured provider')
    sub.add_parser('apply', help='Apply exactly the checked candidate to this private demo')
    sub.add_parser('replay', help='Replay the original request and revocation')
    sub.add_parser('show', help='Show the resolution record')
    sub.add_parser('receipt', help='Render a readable private resolution receipt')
    p = sub.add_parser('enqueue'); p.add_argument('label')
    p = sub.add_parser('deliver'); p.add_argument('job_id'); p.add_argument('--simulate-interruption',action='store_true')
    p = sub.add_parser('recover'); p.add_argument('job_id')
    p = sub.add_parser('guide', help='Walk through a private records-export report')
    construction = p.add_mutually_exclusive_group(required=True)
    construction.add_argument('--events',type=Path,help='Use a retained event stream')
    construction.add_argument('--synthesize',action='store_true',help='Run a fresh configured model attempt')
    args = parser.parse_args(); flow = Flow(args.workspace)
    if args.command == 'receipt':
        print(flow.receipt())
        return
    if args.command == 'guide':
        try:
            description = input('What happened? ').strip()
            flow.create(description)
            print('Reproducing the request, then revoking access before delivery…')
            baseline = flow.reproduce()
            print('Observed:', baseline['status'], '| exports:', baseline['export_count'])
            print('When should permission be checked?')
            print('  1. Delivery time: block records if access has been revoked.')
            print('  2. Request time: retain the authorization from the original request.')
            choice = input('Choose 1 or 2: ').strip()
            if choice == '2':
                flow.choose('request-time')
                replay = flow.view()['request_time_replay']
                print('Request-time replay:', replay['status'], '| audits:', replay['audit_count'], '| exports:', replay['export_count'])
                print('No source change was needed for this observed case.')
                return
            if choice != '1':
                print('No choice recorded. Your report and reproduction are saved.')
                return
            flow.choose('delivery-time')
            print('Protected condition: record an audit before releasing records.')
            checks = flow.synthesize_and_check() if args.synthesize else flow.construct_and_check(args.events)
            print('Original behavior:', checks['baseline']['verdict'])
            print('Authored wrong fix:', checks['wrong_fix']['verdict'])
            print('Muse candidate:', checks['candidate']['verdict'])
            application = flow.apply()
            replay = flow.replay()
            print('Applied checked source:', application['sha256'])
            print('Original journey replay:', replay['status'], '| exports:', replay['export_count'])
            print('The report, checks, application and replay are saved in', flow.db)
        except (InvalidState, EvidenceMismatch, ValueError, OSError, EOFError) as exc:
            parser.exit(1, f'{type(exc).__name__}: {exc}\n')
        return
    actions = {'report':lambda:flow.create(args.description), 'reproduce':flow.reproduce, 'decide':lambda:flow.choose(args.choice), 'check':lambda:flow.construct_and_check(args.events), 'synthesize':flow.synthesize_and_check, 'apply':flow.apply, 'replay':flow.replay, 'show':flow.view, 'enqueue':lambda:{'job_id':flow.enqueue(args.label)}, 'deliver':lambda:flow.deliver(args.job_id,fail_after_audit=args.simulate_interruption), 'recover':lambda:flow.recover(args.job_id)}
    try: print(json.dumps(actions[args.command](),indent=2))
    except (InvalidState, EvidenceMismatch, ValueError, OSError) as exc:
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')

if __name__ == '__main__': main()
