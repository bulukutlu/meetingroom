# Live Whisper dictation

Hold Space or toggle the microphone. The main message box fills while you speak, with words stabilized across successive decodes. Release to run one final pass in the same box. Cancel restores the text that was there before recording. Only the final text can auto-send.

The implementation keeps the accumulated recording rather than cutting it into independent clips, and allows one preview request at a time. This adapts the LocalAgreement approach described by [WhisperStreaming](https://github.com/ufal/whisper_streaming). It uses the installed MLX or faster-whisper backend, rather than adding a separate transcription server.

[Silero VAD](https://github.com/snakers4/silero-vad) runs locally before Whisper. Non-speech is rejected; leading and trailing silence is trimmed with padding, while pauses inside the utterance remain intact. The library and its ONNX runtime were installed in this project's environment and added to requirements.

| Check | Result |
| --- | --- |
| Actual Silero detector on public sample speech | Detected speech regions |
| Actual Silero detector on synthetic silence, random noise and a 440 Hz tone | No speech regions |
| Python suite | 29 checks passed |
| Frontend tests | Stable prefixes, corrections, Unicode, single in-flight request, stale-result suppression, finalization, auto-send ordering and cancellation passed |
| Existing room-state tests and JavaScript syntax | Passed |
| Live microphone accuracy and latency | Not measured in this environment |

The sandbox cannot access the Mac's Metal GPU, so the installed MLX Whisper model could not be exercised here. The interactive preview illustrates the UI with simulated text; it does not claim to be a live recognition benchmark.

Restart the app and reload the room. Recordings automatically finalize at three minutes. Live drafts need at least 1.5 seconds of audio and then update as the model finishes; slower computers will update less frequently. If Silero cannot load, the existing after-release dictation remains available. Preview failures also leave the final pass available.
