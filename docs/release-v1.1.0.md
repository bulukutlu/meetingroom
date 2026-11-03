# Meeting Room v1.1.0

## Agents
- **Exact model choice.** The room picker lists every model variant, grouped by Anthropic and OpenAI, with + / − for extra seats. Each variant gets its own handle, name, face and shirt colour. The list is built at startup: Codex models come from the local Codex model cache, and Claude models come from the Anthropic API when a key is stored (`python -m meetingroom set-key anthropic`). Without a key, a built-in list is used.
- **More replies per prompt.** Agents answer up to twice per chain, and supervisors up to five times.
- **`wake_me` / `say_now`.** An agent can ask to be woken after a timer, when a file appears or when a process ends, so it can report on background jobs without being mentioned. It can also post a progress update mid-turn. In SSH rooms only the timer works.

## Memory
- Whisper (MLX) now frees its GPU buffer cache after every transcription and caps it at 256 MB. This saves about 2 GB with no change in speed or output.
- **Settings → Voice** lets you pick the dictation model (Whisper large-v3-turbo full or 4-bit) and the voice model (Kokoro full, fp16 or int8). The choice is saved and applies at once to open rooms; the previous model is released.

## Shared screen
- Audio (wav, mp3, ogg, flac, m4a, aac, opus) and video (mp4, webm, mov) players.
- Jupyter notebooks with outputs, Office previews (docx, xlsx, pptx; content only, rendered server-side under a strict CSP), and a 3D viewer for STL, OBJ and GLB with orbit controls.
- More code and text formats. Text kinds are always served as `text/plain`, so they never render or run on the app's origin.
- Every shared file opens in a classic window, with a back-to-folder button when it came from a shared folder.

Upgrade: save and close the app, pull and restart.

```bash
git pull --ff-only
./run.sh
```
