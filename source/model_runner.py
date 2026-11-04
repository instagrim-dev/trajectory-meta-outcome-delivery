"""Run the bounded delivery-time Muse construction in a private attempt directory."""
import json
import os
from pathlib import Path
import subprocess
import time

PROMPT = '''Implement the body of a Go function for a synthetic queued records export. An authorized request is queued, then access may be revoked before delivery. The owner chose delivery-time authorization: if current access is false, return "access_revoked" and do not record any events. Otherwise append an "audit" event before a "release" event and return "exported". The function signature must be exactly: func deliver(allowed bool, events *[]string) string. Return ONLY the complete Go function, with no markdown. Do not use tools.\n'''
MODEL = 'meta-models/muse-spark-open-1026'


class GenerationError(RuntimeError):
    def __init__(self, message, *, process_exit_code=None):
        super().__init__(message)
        self.process_exit_code = process_exit_code


def _key():
    key = os.environ.get('BASETEN_API_KEY')
    if key:
        return key
    paths = [Path.home()/'Documents/dev/bmo/.env', Path.home()/'Documents/dev/.env']
    for path in paths:
        try:
            result = subprocess.run(['bash', '-c', 'set -a; source "$1"; printf %s "$BASETEN_API_KEY"', 'bash', str(path)], capture_output=True, text=True, timeout=4)
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise GenerationError('Baseten credential unavailable in the configured environment')


def _write_private(path, text):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        output.write(text)


def generate(attempt, *, executable='muse'):
    attempt = Path(attempt)
    key = _key()
    scratch = attempt/'workspace'
    scratch.mkdir(mode=0o700)
    prompt = attempt/'prompt.txt'
    _write_private(prompt, PROMPT)
    cmd = [executable, 'exec', '--provider', 'meta', '--model', MODEL,
           '--workspace', str(scratch), '--worktree', 'off', '--approval-mode', 'never',
           '--trust-workspace', '--disable-sandbox', '--disable-reminders',
           '--disable-request-user-input', '--disable-web-tools', '--no-foreign-personal-context',
           '--no-session-log', '--no-parallel-tool-calls', '--reasoning-effort', 'low',
           '--max-model-steps', '4', '--api-key-stdin', '--json', '--prompt-file', str(prompt),
           '-c', 'endpoint_transport=' + json.dumps({'base_url':'https://inference.baseten.co/v1','auth':'bearer'})]
    env = os.environ.copy()
    env.pop('BASETEN_API_KEY', None)
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, input=key+'\n', text=True, capture_output=True, timeout=180, env=env)
    except subprocess.TimeoutExpired as exc:
        for name, data in [('events.jsonl', exc.stdout), ('stderr.log', exc.stderr)]:
            if isinstance(data, bytes): data = data.decode('utf-8', errors='replace')
            _write_private(attempt/name, (data or '').replace(key, '[redacted]'))
        raise GenerationError('Muse synthesis timed out') from exc
    except OSError as exc:
        raise GenerationError('Muse executable unavailable') from exc
    elapsed = round(time.monotonic()-started, 3)
    events = attempt/'events.jsonl'
    _write_private(events, result.stdout.replace(key, '[redacted]'))
    _write_private(attempt/'stderr.log', result.stderr.replace(key, '[redacted]'))
    if result.returncode:
        raise GenerationError(f'Muse synthesis failed (exit {result.returncode})', process_exit_code=result.returncode)
    return {'events_path': events, 'elapsed_seconds': elapsed, 'process_exit_code': result.returncode}
