# v1.0.0 performance and lifecycle review

Five fixes are ready in the shared working tree. No commit or version bump was made.

| Issue | Fix | Regression evidence |
| --- | --- | --- |
| Every storage audit/close rehashed archive contents, including already-linked copies | Skip groups already sharing one inode; cache hashes in a bounded 2,048-entry cache keyed by file identity, size, modification time and change time | Already-deduplicated groups perform no content reads; same-size edits with restored modification time invalidate the cache |
| Sharing a large output copied/hashed it on the server event loop | Perform snapshot I/O in a worker thread | A deliberately blocked copy allows the event-loop heartbeat to run |
| A failed snapshot copy could leave an incomplete file in the archive | Write to an excluded temporary path and publish by atomic replacement | Simulated disk-full failure leaves the original intact and no published or temporary partial file |
| Narration cache eviction left synthesis jobs queued and audio fetches waiting | Remove evicted jobs and wake their waiting fetches; reject negative chunk indexes | With synthesis paused, 100 incoming messages and a two-message cache retain at most four queued chunks; evicted waiters wake |
| Removing agents detached scene objects without freeing their GPU allocations or all interaction state | Dispose unique geometry/material/texture/skeleton resources, release late-loading face textures, dispose chairs, and clear seat/lean/hover state | Actual Three.js resource disposal events and skeleton disposal are checked; shared resources are released exactly once |

## Validation

- 22 targeted Python checks passed: release-performance (5), existing performance (3), storage (9), grouped sharing (5).
- Character-resource cleanup, frame-budget and room-state JavaScript checks passed.
- Room and generated picker JavaScript syntax passed. The shared character-builder helper remains included in the picker.
- Read-only audit of the current local meeting archive: first pass **0.341 seconds / 96 content reads**; repeat pass **0.017 seconds / 0 content reads**. This is a local audit measurement, not a full application benchmark.

## Files

`meetingroom/storage.py`, `meetingroom/tts.py`, one snapshot-copy await in `meetingroom/server.py`, and character cleanup in `meetingroom/static/room3d.js`.

New regression checks: `tests/test_release_performance.py` and `tests/character_resources.mjs`.

The full release suite is being handled separately; it should be rerun after all agents' changes are collected. Interactive GUI testing and hardware GPU profiling were not available in this environment.
