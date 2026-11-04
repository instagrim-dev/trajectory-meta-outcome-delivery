"""Private, synthetic delivery proof. Generated source is never trusted as a checker."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent
CHECKER_SOURCE = Path(__file__).read_bytes()
BASELINE = '''func deliver(allowed bool, events *[]string) string {
    *events = append(*events, "audit", "release")
    return "exported"
}'''
WRONG = '''func deliver(allowed bool, events *[]string) string {
    if !allowed { return "access_revoked" }
    *events = append(*events, "release")
    return "exported"
}'''
WRAPPER = '''package main
import ("encoding/json"; "os")
%s
func main() {
  var input struct { Allowed bool `json:"allowed"` }
  if json.NewDecoder(os.Stdin).Decode(&input) != nil { os.Exit(2) }
  events := []string{}
  status := deliver(input.Allowed, &events)
  json.NewEncoder(os.Stdout).Encode(map[string]interface{}{"status":status,"events":events})
}
'''

# Parse, but never execute, model output before putting it in the Go wrapper.
# This bounded language is deliberately narrower than arbitrary Go: the function
# may inspect the boolean, return an outcome, and append audit/release events.
SCOPE_VALIDATOR = r'''package main
import ("bytes"; "fmt"; "go/ast"; "go/format"; "go/parser"; "go/token"; "io"; "os"; "strconv")
func bad() { fmt.Fprintln(os.Stderr, "candidate outside permitted scope"); os.Exit(1) }
func isEvents(e ast.Expr) bool {
 x, ok := e.(*ast.StarExpr); if !ok { return false }; id, ok := x.X.(*ast.Ident); return ok && id.Name == "events"
}
func main() {
 data, err := io.ReadAll(io.LimitReader(os.Stdin, 16385)); if err != nil || len(data) > 16384 { bad() }
 fset := token.NewFileSet(); file, err := parser.ParseFile(fset, "candidate.go", "package main\n"+string(data), parser.ParseComments)
 if err != nil || len(file.Decls) != 1 || len(file.Comments) != 0 { bad() }
 fn, ok := file.Decls[0].(*ast.FuncDecl); if !ok || fn.Recv != nil || fn.Name.Name != "deliver" || fn.Body == nil { bad() }
 var signature bytes.Buffer; if format.Node(&signature, fset, fn.Type) != nil || signature.String() != "func(allowed bool, events *[]string) string" { bad() }
 ast.Inspect(fn, func(n ast.Node) bool {
  switch v := n.(type) {
  case nil, *ast.FuncDecl, *ast.FuncType, *ast.FieldList, *ast.Field, *ast.BlockStmt, *ast.StarExpr, *ast.ParenExpr:
  case *ast.ArrayType:
   id, ok := v.Elt.(*ast.Ident); if v.Len != nil || !ok || id.Name != "string" { bad() }
  case *ast.Ident:
   switch v.Name { case "deliver", "allowed", "events", "append", "bool", "string", "true", "false": default: bad() }
  case *ast.BasicLit:
   if v.Kind != token.STRING { bad() }; value, err := strconv.Unquote(v.Value); if err != nil { bad() }
   switch value { case "access_revoked", "exported", "audit", "release": default: bad() }
  case *ast.IfStmt:
   if v.Init != nil { bad() }
  case *ast.UnaryExpr:
   if v.Op != token.NOT { bad() }
  case *ast.BinaryExpr:
   switch v.Op { case token.EQL, token.NEQ, token.LAND, token.LOR: default: bad() }
  case *ast.ReturnStmt:
   if len(v.Results) != 1 { bad() }; lit, ok := v.Results[0].(*ast.BasicLit); if !ok || lit.Kind != token.STRING { bad() }
   value, err := strconv.Unquote(lit.Value); if err != nil || (value != "access_revoked" && value != "exported") { bad() }
  case *ast.AssignStmt:
   if v.Tok != token.ASSIGN || len(v.Lhs) != 1 || !isEvents(v.Lhs[0]) || len(v.Rhs) != 1 { bad() }
   call, ok := v.Rhs[0].(*ast.CallExpr); if !ok || call.Ellipsis.IsValid() || len(call.Args) < 2 || !isEvents(call.Args[0]) { bad() }
   name, ok := call.Fun.(*ast.Ident); if !ok || name.Name != "append" { bad() }
   for _, arg := range call.Args[1:] { lit, ok := arg.(*ast.BasicLit); if !ok || lit.Kind != token.STRING { bad() }; value, err := strconv.Unquote(lit.Value); if err != nil || (value != "audit" && value != "release") { bad() } }
  case *ast.CallExpr:
   name, ok := v.Fun.(*ast.Ident); if !ok || name.Name != "append" { bad() }
  default: bad()
  }
  return true
 })
}
'''


def validate_scope(output):
    if len(output.encode('utf-8')) > 16384:
        raise ValueError('Muse output outside allowed function scope')
    with tempfile.TemporaryDirectory(prefix='policy-scope-') as tmp:
        validator = Path(tmp) / 'validate.go'
        binary = Path(tmp) / 'validate'
        validator.write_text(SCOPE_VALIDATOR)
        env = dict(os.environ, GOPROXY='off', GOWORK='off', GO111MODULE='off', GOTOOLCHAIN='local')
        build = subprocess.run(['go', 'build', '-o', str(binary), str(validator)], capture_output=True, text=True, timeout=60, env=env)
        if build.returncode:
            raise OSError('Unable to build the scope validator')
        result = subprocess.run([str(binary)], input=output, capture_output=True, text=True, timeout=10)
    if result.returncode:
        if result.stderr.strip() == 'candidate outside permitted scope':
            raise ValueError('Muse output outside allowed function scope')
        raise OSError('Scope validator failed')

class StalePreimage(Exception): pass
class StaleCandidate(Exception): pass

def digest(data): return hashlib.sha256(data).hexdigest()

def apply_checked(target, expected_preimage, candidate, checked_hash):
    if digest(candidate) != checked_hash: raise StaleCandidate()
    if digest(target.read_bytes()) != expected_preimage: raise StalePreimage()
    tmp = target.with_suffix('.pending')
    tmp.write_bytes(candidate)
    os.replace(tmp, target)

def source(fn): return (WRAPPER % fn).encode()

def model_output(events):
    records = [json.loads(line) for line in events.read_text().splitlines()]
    terminal = [x['payload'] for x in records if x.get('payload_type') == 'run.terminal.completed']
    if len(terminal) != 1 or terminal[0].get('terminal') != 'completed':
        raise ValueError('missing completed Muse response')
    output = terminal[0]['text'].strip()
    if not output.startswith('func deliver(') or '```' in output or '\nfunc ' in output:
        raise ValueError('Muse output outside allowed function scope')
    validate_scope(output)
    return output

def evaluate(code, workdir):
    """Build an isolated candidate and run independent black-box examples."""
    path = workdir / 'candidate.go'
    path.write_bytes(code)
    binary = workdir / 'candidate-bin'
    build = subprocess.run(['go','build','-o',str(binary),str(path)], capture_output=True, text=True, timeout=60)
    evidence = {'sha256': digest(code), 'build_exit': build.returncode, 'build_stderr': build.stderr, 'cases': []}
    if build.returncode:
        evidence['verdict'] = 'inconclusive'
        return evidence
    cases = [('revoked', False, 'access_revoked', []), ('authorized', True, 'exported', ['audit','release'])]
    for name, allowed, status, events in cases:
        result = subprocess.run([str(binary)], input=json.dumps({'allowed':allowed}), capture_output=True, text=True, timeout=10)
        try: observed = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError): observed = None
        valid = (result.returncode == 0 and isinstance(observed, dict)
                 and isinstance(observed.get('status'), str)
                 and isinstance(observed.get('events'), list)
                 and all(isinstance(event, str) for event in observed['events']))
        ok = observed == {'status':status,'events':events} if valid else None
        evidence['cases'].append({'name':name, 'exit':result.returncode, 'observed':observed, 'expected':{'status':status,'events':events}, 'satisfied':ok, 'stderr':result.stderr})
    outcomes = [c['satisfied'] for c in evidence['cases']]
    evidence['verdict'] = 'inconclusive' if None in outcomes else 'satisfied' if all(outcomes) else 'violated'
    return evidence

def run(workdir, events):
    started = time.monotonic()
    workdir.mkdir(parents=True, exist_ok=True)
    baseline, wrong, candidate = source(BASELINE), source(WRONG), source(model_output(events))
    target = workdir / 'service.go'
    target.write_bytes(baseline)
    result = {'report':'Queued export was released after access was revoked.', 'decision':'Check access at delivery; audit before release.', 'model':'meta-models/muse-spark-open-1026', 'provider':'Baseten', 'baseline':evaluate(baseline, workdir), 'wrong_fix':evaluate(wrong, workdir), 'candidate':evaluate(candidate, workdir)}
    result['wrong_fix']['origin'] = 'authored control'
    if result['baseline']['verdict'] != 'violated' or result['wrong_fix']['verdict'] != 'violated' or result['candidate']['verdict'] != 'satisfied':
        result['application'] = {'state':'not_applied'}
        return result
    apply_checked(target, result['baseline']['sha256'], candidate, result['candidate']['sha256'])
    result['application'] = {'state':'applied_to_disposable_demo','sha256':digest(target.read_bytes())}
    replay = evaluate(target.read_bytes(), workdir)
    result['replay'] = replay['cases'][0]['observed'] if replay.get('cases') else None
    result['replay_check'] = replay
    result['elapsed_seconds'] = round(time.monotonic()-started,3)
    return result

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='meta-delivery-') as tmp:
        result = run(Path(tmp), ROOT/'evidence'/'muse-events.jsonl')
        (ROOT/'evidence'/'baseline.go').write_bytes(source(BASELINE))
        (ROOT/'evidence'/'authored-wrong-fix.go').write_bytes(source(WRONG))
        (ROOT/'evidence'/'muse-candidate.go').write_bytes(source(model_output(ROOT/'evidence'/'muse-events.jsonl')))
        result['evidence'] = {'model_events_sha256':digest((ROOT/'evidence'/'muse-events.jsonl').read_bytes()), 'baseline_source':'baseline.go', 'wrong_source':'authored-wrong-fix.go', 'candidate_source':'muse-candidate.go'}
        (ROOT/'evidence'/'resolution.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result, indent=2))
