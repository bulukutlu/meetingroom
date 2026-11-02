# Meeting Room v1.0.2

Fixes new rooms containing only one agent of each model despite selecting additional seats.

The picker submitted handles such as `sonnet-2` and `codex-4`, but the server validated only the base handles and silently discarded the numbered ones. New-room creation now validates against the same complete seat catalog used by the picker.

Every selected seat is retained, including a selection containing only numbered instances. Repeated base handles remain supported for older clients. Invalid selections now produce an error rather than silently opening a smaller room; the limits remain four copies per type and twelve agents total.

Regression tests cover multiple instances, numbered-only selections, all twelve seats, the initial room snapshot and corridor roster, identity/color preservation, legacy repeated handles, malformed input and capacity limits.

Save and close the app, pull the update and restart before creating a new room:

```bash
git pull --ff-only
./run.sh
```

If upgrading from v1.0.0, also read the [v1.0.1 workspace migration notes](release-v1.0.1.md). This patch keeps those defaults and does not migrate older meeting data automatically.
