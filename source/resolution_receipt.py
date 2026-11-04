"""Readable, evidence-bound summaries of private owner-flow runs."""
from datetime import datetime
from pathlib import Path

import delivery


def _quote(value):
    return '\n'.join('> ' + line for line in str(value).splitlines())


def _value(value):
    return str(value) if value is not None else 'Not recorded'


def _current_hash(path):
    try:
        return delivery.digest(Path(path).read_bytes())
    except FileNotFoundError:
        return None


def _case_status(case):
    observed = case.get('observed')
    valid = (case.get('exit') == 0 and isinstance(observed, dict)
             and isinstance(observed.get('status'), str)
             and isinstance(observed.get('events'), list)
             and all(isinstance(event, str) for event in observed['events']))
    if not valid or case.get('satisfied') is None:
        return 'inconclusive'
    return 'satisfied' if case['satisfied'] is True else 'violated'


def render(flow):
    state = flow.view()
    receipts = state['receipts']
    checks = state['checks'] or {}
    application = state['application'] or {}
    baseline = state['baseline']
    replay = state['replay']
    request_time_replay = state.get('request_time_replay')
    lines = [
        '# Private resolution receipt',
        '',
        'Synthetic records scenario · controlled demonstration · not a production deployment.',
        '',
        '## Report and decision',
        '',
        _quote(state['report'] or 'Not recorded'),
        '',
        '**Owner decision:** ' + _value(state['decision']),
        '**Protected obligation:** audit before release' if state['decision'] else '**Protected obligation:** Not recorded',
        '',
        '## Reproduction and independent checks',
        '',
    ]
    attempts = [r for r in receipts if r['kind'] in ('checks_started', 'checks_failed', 'checks_completed')]
    if attempts:
        latest = attempts[-1]
        if latest['kind'] == 'checks_failed':
            lines.append(f"Latest check attempt: failed · {_value(latest['detail'].get('error'))}. No active checks.")
        elif latest['kind'] == 'checks_started':
            lines.append('Latest check attempt: started but not completed. No active checks.')
        else:
            lines.append('Latest check attempt: completed.')
    if baseline:
        lines.append(f"**Baseline:** {baseline['status']} · {baseline['export_count']} export(s) · access at delivery: {baseline['access_at_delivery']} · job `{baseline['job_id']}`")
    else:
        lines.append('**Baseline:** Not yet observed')
    for key, title in [('baseline', 'Original behavior'), ('wrong_fix', 'Authored wrong fix'), ('candidate', 'Muse candidate')]:
        check = checks.get(key)
        verdict = check.get('verdict', 'Not recorded') if check else 'Not run'
        if check and any(_case_status(case) == 'inconclusive' for case in check.get('cases', [])) and verdict != 'inconclusive':
            verdict = f"inconclusive (recorded verdict: {verdict})"
        lines.append(f"- **{title}:** {verdict}")
        if check:
            lines.append(f"  - Source SHA-256: `{check.get('sha256', 'Not recorded')}`; build exit: {_value(check.get('build_exit'))}")
            for case in check.get('cases', []):
                status = _case_status(case)
                lines.append(f"  - {case.get('name', 'Unnamed')} example: {status}; process exit: {_value(case.get('exit'))}.")
    origin = checks.get('response_origin') or {}
    if origin.get('kind') == 'synthesis_attempt':
        origin_text = 'synthesis attempt ' + _value(origin.get('attempt_id'))
    elif origin.get('kind') == 'supplied_event_file':
        origin_text = 'supplied retained event file'
    else:
        origin_text = 'not recorded'
    lines.extend(['', '## Evidence identity', '', f"- Model: {_value(checks.get('model'))}", f'- Response origin: {origin_text}', f"- Model event SHA-256: `{_value(checks.get('model_events_sha256'))}`", f"- Independent checker SHA-256: `{_value(checks.get('checker_sha256'))}`"])
    for name, path, expected in [('Candidate file', flow.root/'candidate.go', checks.get('candidate', {}).get('sha256')), ('Model event file', flow.root/'muse-events.jsonl', checks.get('model_events_sha256')), ('Checker file', Path(delivery.__file__), checks.get('checker_sha256'))]:
        if expected:
            actual = _current_hash(path)
            match = 'matches recorded identity' if actual == expected else 'missing' if actual is None else 'differs from recorded identity'
            lines.append(f'- {name}: {match}.')
    checker_hash = checks.get('checker_sha256')
    if checker_hash:
        snapshots = [flow.root / 'checkers' / (checker_hash + '.py'), flow.root / 'checker.py', Path(delivery.__file__).parent / 'evidence' / 'checkers' / (checker_hash + '.py')]
        archived = next((path for path in snapshots if _current_hash(path) == checker_hash), None)
        if archived:
            lines.append(f'- Recorded checker snapshot: verified at `{archived}`.')
        else:
            lines.append('- Recorded checker snapshot: not available or does not match.')
    if checks.get('candidate'):
        lines.append('- Retained candidate and event files: `candidate.go` and `muse-events.jsonl` in the run workspace.')
    lines.extend(['', '## Application and observed replay', ''])
    if request_time_replay:
        lines.append(f"**Request-time replay:** {request_time_replay['status']} · {request_time_replay['audit_count']} audit(s) · {request_time_replay['export_count']} export(s) · access at delivery: {request_time_replay['access_at_delivery']} · job `{request_time_replay['job_id']}`.")
        expected_source = delivery.digest(delivery.source(delivery.BASELINE))
        current_source = _current_hash(flow.root/'service.go')
        lines.append(f"**Original source SHA-256:** `{expected_source}` · " + ('current source matches.' if current_source == expected_source else 'current source differs or is missing.'))
        if request_time_replay['status'] == 'exported' and request_time_replay['audit_count'] == 1 and request_time_replay['export_count'] == 1 and request_time_replay['access_at_delivery'] is False:
            lines.append('No source change was needed for this observed case.')
    if application.get('state') == 'applied':
        expected = application.get('sha256')
        actual = _current_hash(flow.root/'service.go')
        status = 'Current source matches the applied source' if actual == expected and expected else 'Current source is missing' if actual is None else 'Current source differs from the applied source'
        lines.extend([f"**Applied to private demo:** `{_value(expected)}`", f'**Current source:** {status}.'])
    else:
        lines.append('**Application:** Not applied')
    if replay:
        lines.append(f"**Replay observed:** {replay['status']} · {replay['export_count']} export(s) · job `{replay['job_id']}`. This is a new synthetic job repeating the original scenario.")
    else:
        lines.append('**Replay:** Not yet observed')
    recoveries = [r for r in receipts if r['kind'] in ('attempt_failed', 'recovery_completed', 'recovery_failed')]
    lines.extend(['', '## Failure and recovery history', ''])
    if not recoveries:
        lines.append('No failure or recovery recorded.')
    for r in recoveries:
        d = r['detail']
        if r['kind'] == 'attempt_failed':
            lines.append(f"- {r['created_at']} UTC · attempt failed · job `{_value(d.get('job_id'))}` · {_value(d.get('error'))}")
        else:
            lines.append(f"- {r['created_at']} UTC · {r['kind']} · job `{_value(d.get('job_id'))}` · {_value(d.get('status'))} · {_value(d.get('audit_count'))} audit(s) · {_value(d.get('export_count'))} export(s)")
    generations = [r for r in receipts if r['kind'] in ('generation_started', 'generation_completed', 'generation_failed')]
    if generations:
        lines.extend(['', '## Synthesis history', ''])
        for event in generations:
            detail = event['detail']
            if event['kind'] == 'generation_started':
                lines.append(f"- Synthesis attempt started · `{_value(detail.get('attempt_id'))}`.")
            elif event['kind'] == 'generation_completed':
                outcome = f" · process exit: {detail['process_exit_code']}" if 'process_exit_code' in detail else ''
                lines.append(f"- Synthesis attempt completed · `{_value(detail.get('attempt_id'))}` · events SHA-256 `{_value(detail.get('events_sha256'))}`{outcome}.")
            else:
                outcome = f" · process exit: {detail['process_exit_code']}" if 'process_exit_code' in detail else ''
                lines.append(f"- Synthesis attempt failed · `{_value(detail.get('attempt_id'))}` · {_value(detail.get('error'))}{outcome}.")
    report_time = next((r['created_at'] for r in receipts if r['kind'] == 'report_received'), None)
    replay_time = next((r['created_at'] for r in reversed(receipts) if r['kind'] in ('replay_observed', 'request_time_replay_observed')), None)
    lines.extend(['', '## Measurements', ''])
    if report_time and replay_time:
        elapsed = (datetime.fromisoformat(replay_time) - datetime.fromisoformat(report_time)).total_seconds()
        if elapsed >= 0:
            lines.append(f'- Report to observed replay: {elapsed:.0f} seconds, from stored UTC timestamps (one-second resolution).')
    completed = [r for r in generations if r['kind'] == 'generation_completed'
                 and origin.get('kind') == 'synthesis_attempt'
                 and r['detail'].get('attempt_id') == origin.get('attempt_id')
                 and r['detail'].get('events_sha256') == checks.get('model_events_sha256')]
    if completed:
        lines.append(f"- Model process elapsed: {completed[-1]['detail']['elapsed_seconds']} seconds, including CLI overhead.")
    else:
        lines.append('- Model process time: not recorded for this check.')
    lines.extend(['- Human actions, clarification rounds, specialist intervention and model cost: not recorded for this run.', '- These observations are not a comparative productivity benchmark.', ''])
    if checks.get('model') and checks.get('candidate'):
        lines.append('The retained model output supplied a bounded policy function. The host owns the queue, protected checks, audit and recovery.')
    lines.append('')
    return '\n'.join(lines)
