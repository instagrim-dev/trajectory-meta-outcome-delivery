import json, os, pathlib, subprocess, sys, uuid

root = pathlib.Path(__file__).resolve().parent
key = os.environ.get('BASETEN_API_KEY')
if not key:
    sys.exit('Baseten credential unavailable in the configured environment')
prompt = '''Implement the body of a Go function for a synthetic queued records export. An authorized request is queued, then access may be revoked before delivery. The owner chose delivery-time authorization: if current access is false, return "access_revoked" and do not record any events. Otherwise append an "audit" event before a "release" event and return "exported". The function signature must be exactly: func deliver(allowed bool, events *[]string) string. Return ONLY the complete Go function, with no markdown. Do not use tools.\n'''
(root/'evidence'/'muse-prompt.txt').write_text(prompt)
cmd = ['muse','exec','--provider','meta','--model','meta-models/muse-spark-open-1026','--workspace',str(root),'--worktree','off','--approval-mode','never','--trust-workspace','--disable-sandbox','--disable-reminders','--disable-request-user-input','--disable-web-tools','--no-foreign-personal-context','--no-session-log','--no-parallel-tool-calls','--reasoning-effort','low','--max-model-steps','4','--api-key-stdin','--json','--prompt-file',str(root/'evidence'/'muse-prompt.txt'),'-c','endpoint_transport='+json.dumps({'base_url':'https://inference.baseten.co/v1','auth':'bearer'})]
try:
    result = subprocess.run(cmd, input=key+'\n', text=True, capture_output=True, timeout=180)
except subprocess.TimeoutExpired:
    sys.exit('Muse inference timed out')
(root/'evidence'/'muse-events.jsonl').write_text(result.stdout.replace(key,'[redacted]'))
(root/'evidence'/'muse-stderr.log').write_text(result.stderr.replace(key,'[redacted]'))
print('Muse exit:',result.returncode)
sys.exit(result.returncode)
