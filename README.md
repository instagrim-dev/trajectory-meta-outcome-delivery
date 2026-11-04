# Trajectory: owner-driven delivery — Meta hackathon

This submission centers on the Trajectory companion: a bounded records-delivery workflow that connects an owner’s decision to Muse-generated policy, independently controlled checks, application and replay. The native iOS workbench provides the interface.

A records request is authorized and queued; staff access is revoked before delivery. The owner chooses whether authorization is determined at request time or delivery time. For delivery-time authorization, the retained run independently rejects the baseline and an authored wrong fix, accepts the Muse candidate, applies the checked source, and replays the scenario with zero exports after revocation. A separate request-time run produced one audit and one export; a separate authorized interrupted job recovered with one audit and one export.

## Contents

- `source/`: Meta-specific companion delivery flow, native bridge, model runner, checks and retained model events. Start with `source/README.md` for offline and fresh-run instructions.
- `native-workbench/`: the separately inherited iOS interface and earlier companion. Its README describes the earlier Nebius submission, not the Meta-specific delivery backend. For the Meta flow, start `source/native_bridge.py` as described below.
- `evidence/` and `verification/`: source identities, independent checks, run receipts, database snapshots and logs. See `VERIFICATION.md`.
- `media/trajectory-meta-reviewed-private.mp4`: 2:56.9 demo, with narration and captions alongside it. Delivery-time selection and the completed check/replay are separate recordings.

## Reproduce

Python 3 and Go are required. These offline checks use retained model events; they do not make a provider call.

```sh
cd source
python3 -W error::ResourceWarning -m unittest discover -s checks -v
cd ..
python3 verification/recheck.py
```

For the native interface, run `python3 native_bridge.py --workspace /path/to/new/private-workspace` from `source/`, open `native-workbench/Workbench.xcodeproj`, select the Workbench scheme and an iOS simulator, and choose **Resolve a records delivery issue**. A fresh synthesis requires the existing Muse configuration.

## Contribution and scope

The Meta-specific companion slice, checks, replay, recovery and receipts are the entry. The native workbench and BMO research are antecedents; the earlier public Trajectory repository is https://github.com/instagrim-dev/trajectory-nebius. The inherited workbench’s earlier provider-specific documentation describes its original submission and must not be confused with this Meta run. The checker covers the demonstrated examples; it does not establish general privacy compliance or production deployment.

The earlier workbench is provided separately from the event-specific companion to make the contribution boundary clear.

## License

The Meta companion source and documentation are available under the [MIT License](LICENSE). The inherited native workbench retains its own license.
