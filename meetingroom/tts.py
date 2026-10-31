"""Local text-to-speech with Kokoro (82M-parameter open model, ONNX runtime).
Runs entirely on this computer. Model files (~340 MB) are downloaded once
from the kokoro-onnx GitHub release into <workspace>/models/."""
from __future__ import annotations

import io
import re
from collections import deque
import threading
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {"model": "kokoro-v1.0.onnx", "voices": "voices-v1.0.bin"}
# Distinct default voices, handed out to agents in order (override per agent with `voice:`).
VOICE_POOL = ["am_michael", "bf_emma", "am_adam", "af_heart", "bm_george", "af_nicole", "am_puck", "bf_isabella"]


def clean_for_speech(text: str) -> str:
    t = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"https?://\S+", "a link", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)          # markdown links
    t = re.sub(r"(?<!\w)@([\w-]+)", r"\1", t)                  # @claude -> claude
    t = re.sub(r"(/[\w.\-]+){2,}/([\w.\-]+)", r"\2", t)        # long paths -> file name
    t = re.sub(r"[*_#>|~]+", " ", t)
    t = re.sub(r"(\d)\s?e-(?!\w)", r"\1 electrons", t)        # 62 e- -> 62 electrons
    return re.sub(r"\s+", " ", t).strip()


class Speaker:
    def __init__(self, cfg: dict | None, workspace: Path, agent_specs: list[dict]):
        c = cfg or {}
        self.wanted = (c.get("engine") or "kokoro").lower()  # kokoro | browser
        self.speed = float(c.get("speed") or 1.1)
        self.lang = c.get("lang") or "en-us"
        self.dir = workspace / "models" / "kokoro"
        self.voices = {}
        for i, s in enumerate(agent_specs):
            self.voices[s["name"].lower()] = s.get("voice") or VOICE_POOL[i % len(VOICE_POOL)]
        self.model = None
        self.status = "off" if self.wanted == "browser" else "loading"
        self.detail = ""
        self._lock = threading.Lock()
        self.acks: dict[str, list[bytes]] = {}   # agent -> short "on it" clips, made once at startup

    def public(self) -> dict:
        return {"status": self.status, "detail": self.detail, "voices": self.voices,
                "acks": {k: len(v) for k, v in self.acks.items()}}

    def _download(self, name: str):
        dest = self.dir / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            return dest
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        print(f"  narration: downloading {name} (one time) ...", flush=True)
        with urllib.request.urlopen(RELEASE + name, timeout=60) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        tmp.rename(dest)
        return dest

    def load(self):
        if self.wanted == "browser":
            return
        try:
            from kokoro_onnx import Kokoro
            model = self._download(FILES["model"])
            voices = self._download(FILES["voices"])
            t = time.time()
            self.model = Kokoro(str(model), str(voices))
            self.model.create("Ready.", voice=VOICE_POOL[0], speed=self.speed, lang=self.lang)  # warm-up
            self.status = "ready"
            print(f"  narration: Kokoro ready ({time.time() - t:.1f}s warm-up)", flush=True)
            for agent in self.voices:          # acknowledgement clips for instant playback
                self.acks[agent] = [self.synth_wav(p, agent) for p in ACK_PHRASES]
        except Exception as e:
            self.status, self.detail = "error", f"{type(e).__name__}: {e}"
            print(f"  narration: Kokoro unavailable, using browser voices ({self.detail})", flush=True)

    def synth_wav(self, text: str, agent: str) -> bytes:
        if self.status != "ready":
            raise RuntimeError(f"Kokoro not ready ({self.status})")
        voice = self.voices.get(agent.lower(), VOICE_POOL[0])
        with self._lock:
            samples, sr = self.model.create(text[:1000], voice=voice, speed=self.speed, lang=self.lang)
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm)
        return buf.getvalue()


ACK_PHRASES = ["Mm-hm.", "On it.", "Got it.", "Okay.", "Sure.", "Right."]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;:])\s+(?=[A-Z0-9(\"'])", text)
    out, cur = [], ""
    for p in parts:  # merge very short fragments so prosody stays natural (never into the first one)
        cur = f"{cur} {p}".strip() if cur else p
        if len(cur) >= 40 or not out:
            out.append(cur); cur = ""
    if cur:
        out.append(cur)
    # Keep the FIRST chunk short so audio starts quickly: split it at a comma
    # (or after ~8 words) if it is long.
    if out and len(out[0].split()) > 10:
        first = out[0]
        m = re.search(r",\s", first[20:])
        cut = 20 + m.end() if m else len(" ".join(first.split()[:8])) + 1
        head, tail = first[:cut].strip(), first[cut:].strip()
        if tail:
            out[0:1] = [head, tail]
    return out


class MessageAudio:
    """Synthesizes a message's sentences in the background as soon as it is
    posted, so the browser only has to fetch finished audio."""

    def __init__(self, speaker: Speaker, keep: int = 30):
        self.speaker, self.keep = speaker, keep
        self.items: dict[str, dict] = {}
        self._order: deque[str] = deque()
        self._q: deque = deque()
        self._cv = threading.Condition()
        threading.Thread(target=self._worker, daemon=True).start()

    def start(self, mid: str, text: str, agent: str) -> list[str]:
        with self._cv:
            if mid in self.items:
                return self.items[mid]["parts"]
            parts = split_sentences(clean_for_speech(text[:4000]))
            item = {"parts": parts, "agent": agent, "wav": [None] * len(parts), "done": [threading.Event() for _ in parts]}
            self.items[mid] = item
            self._order.append(mid)
            while len(self._order) > self.keep:
                self.items.pop(self._order.popleft(), None)
            self._q.extend((mid, i) for i in range(len(parts)))
            self._cv.notify()
            return parts

    def get(self, mid: str, i: int, timeout: float = 60) -> bytes | None:
        item = self.items.get(mid)
        if not item or i >= len(item["parts"]):
            return None
        item["done"][i].wait(timeout)
        return item["wav"][i]

    def _worker(self):
        while True:
            with self._cv:
                while not self._q:
                    self._cv.wait()
                mid, i = self._q.popleft()
                item = self.items.get(mid)
            if not item:
                continue
            try:
                item["wav"][i] = self.speaker.synth_wav(item["parts"][i], item["agent"])
            except Exception:
                item["wav"][i] = None
            item["done"][i].set()
