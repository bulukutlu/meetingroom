# Meeting Room

**v0.1.0** · A local, video-call style room where you hold a working meeting with
several AI agents at once: Claude Code, Codex and API models side by side. You
address them with `@name`, by typing or by talking. They do real work on **your**
computer (Python, shell, files), put plots, tables and HTML pages on a shared
screen, and answer out loud.

![The meeting room: three agents working on a task](docs/screenshot.png)

```
 your browser  http://127.0.0.1:8765        (reachable only from this computer)
        │ websocket
 local hub (this app, Python) ── approvals, shared screen, voice, minutes
        │
        ├── claude -p ...      Claude Code agents   (your claude.ai login)
        ├── codex exec ...     Codex CLI agents     (your ChatGPT login)
        └── HTTPS              Anthropic / OpenAI API agents (key from OS keychain)
```

---

## 1. Quick start (2 minutes)

Requirements: **Python 3.11+**, macOS or Linux (on Windows use the manual
commands below), a recent Chrome / Edge / Safari.

```bash
git clone <this repo> meetingroom
cd meetingroom
./run.sh --demo
```

The first run creates a private `.venv` and installs everything (one time, a few
minutes; nothing goes into your system or conda Python). Your browser opens on a
room with three **demo agents** that need no login or key but really run code and
show plots. Type `@all make a plot` to see it work.

When that works, set up real agents (section 2) and start:

```bash
./run.sh
```

A picker page lets you choose who joins this meeting, then the room opens.

> Manual install:
> `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python -m meetingroom run`

---

## 2. Setting up agents

All participants are defined in **`agents.yaml`**. It never contains secrets;
the app refuses to start if it sees a key-like field. Each entry needs a `name`
(what you `@mention`) and a `provider`, plus optionally a model, colour and role.
Mix any of the providers below.

### a) Claude Code: `provider: claude-code` (recommended, no API key)

Uses the `claude` CLI and your claude.ai subscription.

1. Install Claude Code (https://docs.claude.com/claude-code), e.g. `npm i -g @anthropic-ai/claude-code`.
2. Run `claude` once in a terminal and log in.
3. Add the agent:

```yaml
  - name: claude
    provider: claude-code
    model: opus             # anything `claude --model` accepts: opus, sonnet, haiku, full IDs
    color: "#d97757"
    role: Lead analyst. Plans the work and reviews others' results.
    approval: ask           # ask = permission prompts become approval cards; auto = allow all
    # effort: high          # low | medium | high | xhigh | max (also switchable live)
    # add_dirs: [~/data]    # extra folders it may use without asking
    # permission_mode: default   # override your Claude Code default (e.g. if it is bypassPermissions)
    # claude_path: /opt/homebrew/bin/claude   # only if `claude` isn't found automatically
```

Each agent is your own Claude Code running headless in its own folder
(`~/MeetingRoom/agents/<name>/`), continuing one conversation across turns. It
keeps all its tools, skills, MCP servers, `CLAUDE.md` and settings. A small local
MCP bridge adds two things: permission prompts show up as **approval cards** in
the room, and a **`share_to_screen`** tool puts results on the shared screen.
Your login stays in Claude Code's own storage. If `ANTHROPIC_API_KEY` is set in
your shell it is hidden from these agents so they use your subscription.

### b) Codex CLI: `provider: codex` (no API key)

Uses the `codex` CLI and your ChatGPT login.

1. Install Codex, e.g. `npm i -g @openai/codex` or `brew install codex`.
2. Run `codex` once and sign in.
3. Add the agent:

```yaml
  - name: codex
    provider: codex
    model:                  # empty = Codex default
    color: "#10a37f"
    role: Second opinion. Independent cross-checks, HTML pages.
    network: true           # allow internet inside the sandbox (pip, curl, APIs)
    # add_dirs: [~/data]    # extra writable folders
    # sandbox: workspace-write
    # codex_path: /opt/homebrew/bin/codex
```

Codex runs in its own `workspace-write` sandbox instead of approval cards: it can
write only in its folder plus `add_dirs`.

### c) API agents: `provider: anthropic` / `provider: openai`

Billed per use via console.anthropic.com / platform.openai.com (separate from
Pro/Plus subscriptions). Store each key once in your OS keychain:

```bash
./run.sh set-key anthropic     # paste key, input is hidden
./run.sh set-key openai
./run.sh keys                  # shows masked keys and where they are stored
./run.sh remove-key openai
```

```yaml
  - name: gpt
    provider: openai           # or anthropic
    model: gpt-5.6-sol
    color: "#10a37f"
    role: Plotting and pages.
    approval: ask
```

API agents use built-in tools (`run_shell`, `run_python`, file read/write/list,
`share_to_screen`). Set the top-level `python:` to your analysis environment
(conda or venv) so they have numpy, ROOT, uproot, etc.

### d) Demo: `provider: mock`

Key-free scripted agents for trying the UI (`./run.sh --demo`).

### Choosing who joins

```bash
./run.sh                         # picker page in the browser
./run.sh --agents claude,codex   # skip the picker, start only these
./run.sh --all                   # everyone in agents.yaml
./run.sh --config other.yaml     # a different roster file
./run.sh --port 9000 --no-browser
```

---

## 3. Other settings in `agents.yaml`

```yaml
user_name: Berkin               # how agents address you
workspace: ~/MeetingRoom        # agent folders + meeting records
python:                         # interpreter for API agents' run_python (empty = this app's)
reply_to_last_speaker: true     # un-addressed messages go to whoever spoke last

voice:                          # speech input
  engine: whisper               # whisper = local, audio never leaves the machine; browser = Chrome speech
  language: en                  # empty = auto-detect
  vocabulary: [ALPIDE, MOSS, Corryvreckan]   # domain words that help recognition

narration:                      # reading replies aloud
  engine: kokoro                # kokoro = local neural voices; browser = system voices
  speed: 1.1
```

Per agent you can also set `voice:` (a Kokoro voice such as `am_michael`,
`bf_emma`, `bm_george`, `af_heart`) and `face:` (1-6, the 3D character).

The first start downloads the Whisper model once (~1.6 GB) and the Kokoro voices
(~340 MB). Use `engine: browser` for both to skip the downloads.

---

## 4. Using the room

- **Address agents:** `@claude fit the S-curves in ~/data/run512 and plot the
  threshold map`. `@all` addresses everyone. Agents can hand work to each other
  (`@codex cross-check this`); the number of hops is capped.
- **Voice:** hold `Space` to talk (push-to-talk) or press `Ctrl+Space` / the mic
  to toggle. Starting with a name ("Claude, can you…") becomes `@claude`.
  `S` stops the current read-aloud.
- **Approvals:** with `approval: ask`, every command or out-of-folder file access
  appears as a card showing the full command. Choose *Run it* or *Always for X*,
  or flip the tile toggle to auto-run. *Stop* / *Stop all* kill running work.
- **Effort:** change an agent's reasoning effort live from its tile.
- **Shared screen:** plots (PNG/SVG), markdown, CSV tables and sandboxed HTML pages.
- **Records:** each meeting gets `~/MeetingRoom/meetings/<session>/` with
  `transcript.jsonl`, `details.jsonl` (every tool call behind the scenes),
  `minutes.md` (kept up to date automatically) and `shared/` (every file shown).
  Rebuild minutes of an old session: `./run.sh minutes ~/MeetingRoom/meetings/<session>`.

---

## 5. Security

- **Nothing is hosted.** The server binds to `127.0.0.1` only; non-localhost
  `Host` headers are rejected (blocks DNS rebinding).
- **Fresh access token on every start**, carried in the printed link and removed
  from the address bar. Other origins and token-less connections are refused.
- **API keys live only in the OS keychain** (macOS Keychain, Windows Credential
  Manager, Linux Secret Service), never in files, logs, transcripts or the
  browser. Plaintext keyrings are refused.
- **Agent HTML runs sandboxed** and cannot reach the app or your session.
- **OpenAI calls use `store=False`.**
- Remember: whatever an agent reads (files, command output) is sent to its model provider.

---

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| `Claude Code not found` | Set `claude_path:` for that agent (see `which claude`). |
| `Codex CLI not found` | Set `codex_path:` (see `which codex`). |
| No approval cards for Claude Code | Your Claude Code default is probably `bypassPermissions`; set `permission_mode: default`. |
| `no openai API key` | `./run.sh set-key openai` |
| Mic does nothing | Allow microphone access in the browser; the first Whisper start is slow (model download). |
| Port in use | `./run.sh --port 8766` |
| Changed `agents.yaml` | Restart the room. |
| Custom character faces | `.venv/bin/pip install pillow && .venv/bin/python tools/make_faces.py <photo folder>` |

---

## 7. Project layout

```
agents.yaml              participants and settings (no secrets)
run.sh                   one-command launcher (creates .venv on first run)
requirements.txt
meetingroom/
  __main__.py            CLI: run, set-key, keys, remove-key, minutes
  server.py              local hub: routing, approvals, shared screen, guards
  agents.py              agent loop; claude-code / codex / anthropic / openai / mock backends
  mcp_bridge.py          MCP server giving CLI agents approvals + share_to_screen
  tools.py               built-in tools for API agents
  picker.py              start-up participant picker
  stt.py, tts.py         local Whisper transcription, Kokoro narration
  minutes.py             details.jsonl + minutes.md
  keys.py                OS keychain access
  static/                room UI (index.html, room3d.js, faces, three.js)
tools/make_faces.py      turn portrait photos into character faces
```

## Changelog

- **0.1.0** (2026-10-31): first release. Claude Code, Codex, Anthropic and OpenAI
  agents; 3D room; approval cards; shared screen; local Whisper voice input and
  Kokoro narration; live effort switching; participant picker; automatic minutes.
