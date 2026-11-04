# Private resolution receipt

Synthetic records scenario · controlled demonstration · not a production deployment.

## Report and decision

> A customer received records after access was revoked.

**Owner decision:** delivery-time
**Protected obligation:** audit before release

## Reproduction and independent checks

Latest check attempt: completed.
**Baseline:** exported · 1 export(s) · access at delivery: False · job `39ae1f048a1a4861912201f7b567094e`
- **Original behavior:** violated
  - Source SHA-256: `149916c222ad2d19b52bfa554b5cf17a3884ec262f7741c40feb1a69ca6be6d2`; build exit: 0
  - revoked example: violated; process exit: 0.
  - authorized example: satisfied; process exit: 0.
- **Authored wrong fix:** violated
  - Source SHA-256: `a12b92ba0f7812ca7a60aaf2ffb3bd7814c747c8612bd6fc9cd0f901a91084bb`; build exit: 0
  - revoked example: satisfied; process exit: 0.
  - authorized example: violated; process exit: 0.
- **Muse candidate:** satisfied
  - Source SHA-256: `4677caae3a8bc91f6c6e1ce1ac5ddf373c1d7b615591be16d4c36b05be9f69ed`; build exit: 0
  - revoked example: satisfied; process exit: 0.
  - authorized example: satisfied; process exit: 0.

## Evidence identity

- Model: meta-models/muse-spark-open-1026
- Response origin: synthesis attempt 411bdb4ddb9041bbb2c09345354b324b
- Model event SHA-256: `970f2cb124e56d0b4a661b4d0b769118cbc83a617898d42150d0f8e2530f1802`
- Independent checker SHA-256: `41c596cf30e540dc74974f3bcafe27dbdac14713ef1564f91f35813ea6d0ecff`
- Candidate file: matches recorded identity.
- Model event file: matches recorded identity.
- Checker file: matches recorded identity.
- Recorded checker snapshot: verified at `/Users/user1/Documents/dev/hackathons/2026-fall/evidence-local/issue2-delivery-demo-dQi0Ywsp/checkers/41c596cf30e540dc74974f3bcafe27dbdac14713ef1564f91f35813ea6d0ecff.py`.
- Retained candidate and event files: `candidate.go` and `muse-events.jsonl` in the run workspace.

## Application and observed replay

**Applied to private demo:** `4677caae3a8bc91f6c6e1ce1ac5ddf373c1d7b615591be16d4c36b05be9f69ed`
**Current source:** Current source matches the applied source.
**Replay observed:** access_revoked · 0 export(s) · job `2a3af929bd8b4f8ab16fa15dbce74312`. This is a new synthetic job repeating the original scenario.

## Failure and recovery history

- 2026-11-03 19:54:35 UTC · attempt failed · job `dd1fe0011c064ebaa0f362f492d608fc` · Injected interruption after durable audit
- 2026-11-03 19:55:09 UTC · recovery_completed · job `dd1fe0011c064ebaa0f362f492d608fc` · exported · 1 audit(s) · 1 export(s)

## Synthesis history

- Synthesis attempt started · `411bdb4ddb9041bbb2c09345354b324b`.
- Synthesis attempt completed · `411bdb4ddb9041bbb2c09345354b324b` · events SHA-256 `970f2cb124e56d0b4a661b4d0b769118cbc83a617898d42150d0f8e2530f1802` · process exit: 0.

## Measurements

- Report to observed replay: 93 seconds, from stored UTC timestamps (one-second resolution).
- Model process elapsed: 5.499 seconds, including CLI overhead.
- Human actions, clarification rounds, specialist intervention and model cost: not recorded for this run.
- These observations are not a comparative productivity benchmark.

The retained model output supplied a bounded policy function. The host owns the queue, protected checks, audit and recovery.

