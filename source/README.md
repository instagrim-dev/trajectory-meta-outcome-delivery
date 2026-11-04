# Trajectory: outcome-owned delivery slice

This self-contained synthetic records-export demonstration accompanies issue #2. It separates an owner decision, bounded Muse-generated policy, host-owned checks, private application, replay and a readable receipt. Request-time keeps an originally authorized request, while delivery-time requires current access. Both preserve the audit-before-release obligation; for the observed request-time case the existing source needs no change. The inherited Trajectory iOS application is not part of this source tree; the accompanying native-workbench directory contains it.

## Reproduce with retained evidence

Requires Python 3 and Go on PATH; no network, Muse executable or credential is needed for this path. The checker compiles and executes the candidate locally, so use an isolated private environment.

```sh
python3 -W error::ResourceWarning -m unittest discover -s checks -v
run_dir=$(mktemp -d "${TMPDIR:-/tmp}/trajectory-meta.XXXXXXXX")
printf '%s\n%s\n' 'Synthetic records were delivered after staff access was revoked.' '1' | python3 owner_flow.py --workspace "$run_dir" guide --events "$PWD/evidence/muse-events.jsonl"
python3 owner_flow.py --workspace "$run_dir" receipt > "$run_dir/resolution-receipt.md"
printf 'Workspace: %s\n' "$run_dir"
```

Expected: original behavior and the authored wrong fix violate the protected examples; the candidate satisfies them; the checked candidate is applied in the disposable workspace; the replay blocks the revoked request with zero exports. Inspect the generated receipt, source and retained checker. The event file is a fixture, not proof of a live inference or transport.

To reproduce the request-time choice separately, use a new workspace and select `2`:

```sh
request_dir=$(mktemp -d "${TMPDIR:-/tmp}/trajectory-request.XXXXXXXX")
printf '%s\n%s\n' 'Synthetic records were delivered after staff access was revoked.' '2' | python3 owner_flow.py --workspace "$request_dir" guide --events "$PWD/evidence/muse-events.jsonl"
python3 owner_flow.py --workspace "$request_dir" receipt > "$request_dir/resolution-receipt.md"
```

This path observes one audit and one export for the originally authorized request after revocation. It does not make a model call or apply a source change for this observed case.

## Fresh Muse attempt

The programmatic `Flow.resolve()` path and native bridge can invoke the configured Meta Muse model through Baseten with `BASETEN_API_KEY` available in the environment. A fresh attempt can incur provider cost. Start the loopback bridge with `python3 native_bridge.py --workspace /path/to/new/private-workspace`; the separately maintained native app uses it. The `guide --synthesize` command also invokes fresh generation. The runner passes the key via standard input and retains redacted output and the synthetic prompt in the private workspace.

The supplied checks cover two examples, not all possible behaviors. The demo does not establish production compliance. See `PROVENANCE.md` for the source boundary.
