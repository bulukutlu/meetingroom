# Meeting Room performance review

**Four improvements implemented. Targeted checks pass.** Changes are saved locally and uncommitted; restart the app to load the Python changes and reload the page for the rendering change.

| Area | Problem found | Change |
|---|---|---|
| CPU / GPU | The entire 3D scene, character animation, label positioning and hit testing ran at the display refresh rate. | Cap that work at 30 frames/second; skip rendering when the page is hidden or the room has no visible size. |
| Speech startup | Every new room regenerated nine acknowledgement/permission clips per agent, even when another room already used the same voice. | Reuse clips for the same loaded model, voice, speed and language. Different settings keep separate clips. |
| Memory / threads | Every room immediately created a speech worker; closing a room never stopped it, retaining the audio cache and speaker. | Create the worker on first speech request; closing a room clears queued audio and cached clips, wakes waiters and stops the worker after any current synthesis finishes. |
| Input tokens / file I/O | The built-in file tool read entire files before clipping them, with no way to request a specific section. | Read 200 lines by default, with explicit continuation offsets and configurable page sizes. Applies to direct API agents; Claude Code and Codex use their own file tools. |

## Verification

The actual frame scheduling code was exercised with simulated refresh rates:

| Display refresh | Rendered frames over 10 seconds | Hidden or collapsed |
|---|---:|---:|
| 60 Hz | 300 | 0 |
| 120 Hz | 300 | 0 |
| 144 Hz | 300 | 0 |

That is 50–79% fewer full scene updates than rendering on every refresh. **This is a scheduling result, not a measured reduction in total CPU usage.** Browser animation smoothness and real CPU/GPU savings still need a live check.

Three Python tests pass: file pagination boundaries and invalid inputs; reuse of speech clips with settings isolation; lazy speech workers and shutdown during active synthesis. Python compilation, JavaScript syntax and whitespace checks also pass. Tests use a fake speech model; they do not benchmark Whisper or Kokoro inference.

## Further opportunities found

| Priority | Observation | Next improvement |
|---|---|---|
| High: tokens | Direct API backends retain every prior tool result and resend the growing history on subsequent requests. CLI agents also retain their sessions. | Add deliberate history compaction that preserves decisions, active tasks and recent tool exchanges. Measure per-turn input, cached input, output and reasoning usage before choosing thresholds. No transcript/history deletion was introduced here. |
| Medium: responsiveness | Codex usage reporting recursively searches session files and reads a log synchronously inside an async method. | Cache the matching rollout path and move filesystem work off the event loop. This affects local usage reporting, not inference speed. |
| Medium: memory | Shell output is collected in full before the displayed output is clipped. A noisy command can therefore allocate much more than the visible 20,000-character limit. | Drain output incrementally into a bounded head/tail buffer, preserving process cancellation and timeout handling. |
| Medium: long meetings | Minutes are rebuilt from the complete transcript and detail log after each agent turn. | Coalesce concurrent rebuild requests and serialize writes; profile a long session before redesigning the renderer. |

Current agent defaults already use medium reasoning effort. Restricting expensive reasoning to difficult analysis is a useful operational choice, but no model or effort settings were changed. No measured token savings are claimed for this meeting's CLI agents.
