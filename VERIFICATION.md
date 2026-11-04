# Independent verification — 2026-11-03

- Backend: `python3 -W error::ResourceWarning -m unittest discover -s checks -v`: 55 tests passed; log in `verification/backend-tests.log`.
- Native: `xcodebuild -project Workbench.xcodeproj -scheme Workbench -sdk iphonesimulator -configuration Debug CODE_SIGNING_ALLOWED=NO build`: succeeded; log in `verification/native-build.log`.
- Independent executable witness and retained host checker: baseline violated; authored wrong fix violated; retained Muse candidate satisfied the revoked and authorized examples. The applied and checked SHA-256 identities agree. Rerun using `python3 verification/recheck.py`.
- Delivery receipts: baseline exported after revocation; a newly queued replay blocked with zero exports; separate interrupted authorized job recovered with one audit and one export.
- Request-time receipts: replay exported with one audit and one export after revocation.
- The delivery run's report-to-replay interval was 93 seconds; model process time was 5.499 seconds. Those measurements describe this one run.
- Demo: `media/trajectory-meta-reviewed-private.mp4`, 176.933 seconds. New selection footage and completed delivery run are distinct takes.
