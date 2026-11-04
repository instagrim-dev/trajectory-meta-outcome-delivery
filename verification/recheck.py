#!/usr/bin/env python3
"""Independently build and exercise retained source against the two examples."""
import hashlib, importlib.util, json, pathlib, subprocess, tempfile
root = pathlib.Path(__file__).resolve().parents[1]
evidence = root / 'evidence'
spec = importlib.util.spec_from_file_location('retained_checker', evidence / 'checker.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
programs = {'baseline': checker.source(checker.BASELINE), 'wrong_fix': checker.source(checker.WRONG), 'candidate': (evidence/'candidate.go').read_bytes()}
cases = [('revoked', False, {'status': 'access_revoked', 'events': []}), ('authorized', True, {'status': 'exported', 'events': ['audit','release']})]
results = {}
with tempfile.TemporaryDirectory(prefix='trajectory-independent-') as temp:
    work = pathlib.Path(temp)
    for name, source in programs.items():
        src, binary = work / (name + '.go'), work / (name + '-bin')
        src.write_bytes(source)
        subprocess.run(['go', 'build', '-o', str(binary), str(src)], check=True, capture_output=True, timeout=60)
        checks = []
        for label, allowed, expected in cases:
            completed = subprocess.run([str(binary)], input=json.dumps({'allowed': allowed}), check=True, capture_output=True, text=True, timeout=10)
            actual = json.loads(completed.stdout)
            checks.append({'name': label, 'observed': actual, 'expected': expected, 'satisfied': actual == expected})
        results[name] = {'sha256': hashlib.sha256(source).hexdigest(), 'cases': checks, 'verdict': 'satisfied' if all(x['satisfied'] for x in checks) else 'violated'}
    assert {name: result['verdict'] for name,result in results.items()} == {'baseline':'violated','wrong_fix':'violated','candidate':'satisfied'}
    assert hashlib.sha256(programs['candidate']).digest() == hashlib.sha256((evidence/'service.go').read_bytes()).digest(), 'applied source differs from checked candidate'
    print(json.dumps(results, indent=2))
