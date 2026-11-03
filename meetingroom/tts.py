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
from concurrent.futures import Future
from pathlib import Path

import numpy as np

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {"model": "kokoro-v1.0.onnx", "voices": "voices-v1.0.bin"}
# Model files offered in Settings (same release, same voices file): (file, label).
MODEL_CHOICES = [("kokoro-v1.0.onnx", "Full precision (325 MB)"),
                 ("kokoro-v1.0.fp16.onnx", "Half precision (170 MB)"),
                 ("kokoro-v1.0.int8.onnx", "8-bit (90 MB, fastest)")]


def model_file(name: str | None) -> str:
    return name if name in {f for f, _ in MODEL_CHOICES} else FILES["model"]
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
        self.speed = float(c.get("speed") or 1.3)
        self.lang = c.get("lang") or "en-us"
        self.file = model_file(c.get("model"))
        self.dir = workspace / "models" / "kokoro"
        self.voices = {}
        from .agents import assign_voices   # voice gender follows the agent's face
        self.voices = assign_voices(agent_specs)
        self.model = None
        self.status = "off" if self.wanted == "browser" else "loading"
        self.detail = ""
        self._lock = _SYNTH_LOCK   # the Kokoro model is shared by every room
        self.acks: dict[str, list[bytes]] = {}   # agent -> short "on it" clips, made once at startup
        self.perms: dict[str, list[bytes]] = {}  # agent -> "I need your permission" clips

    def public(self) -> dict:
        ready = self.status == "ready" and bool(self.perms or not self.voices)
        return {"status": self.status if self.status != "ready" or ready else "loading", "detail": self.detail, "model": self.file, "voices": self.voices,
                "acks": {k: len(v) for k, v in self.acks.items()},
                "perms": {k: len(v) for k, v in self.perms.items()}}

    def load(self):
        if self.wanted == "browser":
            return
        try:
            t = time.time()
            self.model = preload(self.dir, self.speed, self.lang, self.file).result()   # usually already loading since start-up
            self.status = "ready"   # synth_wav needs this; clips are published only once all are made
            acks, perms = {}, {}
            for agent in self.voices:          # acknowledgement clips for instant playback
                key = (id(self.model), self.voices[agent], self.speed, self.lang)
                with _CLIP_LOCK:
                    clips = _CLIPS.get(key)
                    if clips is None:
                        clips = ([self.synth_wav(p, agent) for p in ACK_PHRASES],
                                 [self.synth_wav(p, agent) for p in PERMISSION_PHRASES])
                        _CLIPS[key] = clips
                acks[agent], perms[agent] = clips
            self.acks, self.perms = acks, perms
            print(f"  narration: Kokoro ready ({time.time() - t:.1f}s wait + clips)", flush=True)
        except Exception as e:
            self.status, self.detail = "error", f"{type(e).__name__}: {e}"
            print(f"  narration: Kokoro unavailable, using browser voices ({self.detail})", flush=True)

    def switch(self, file: str):
        """Use another Kokoro model file from now on (Settings); clips are remade with it."""
        file = model_file(file)
        if self.wanted == "browser" or file == self.file:
            return
        with _SWITCH_LOCK:
            self.file, self.status, self.detail, self.model = file, "loading", "", None
            self.acks, self.perms = {}, {}
            with _PRELOAD_LOCK:
                for k in [k for k in _PRELOADS if k[1] != file]:
                    del _PRELOADS[k]       # drop the old model once no room uses it
            with _CLIP_LOCK:
                _CLIPS.clear()
            self.load()

    def add_agent(self, spec: dict, existing: list[dict]):
        """Give a newly seated agent a voice (same gender as its face, unused if possible) and its clips."""
        from .agents import assign_voices
        have = [{**s, "voice": self.voices.get(s["name"].lower()) or s.get("voice")} for s in existing]
        self.voices[spec["name"].lower()] = assign_voices(have + [dict(spec, voice=None)])[spec["name"].lower()]
        if self.status != "ready":
            return          # load() will make the clips once the model is up
        agent = spec["name"].lower()
        key = (id(self.model), self.voices[agent], self.speed, self.lang)
        with _CLIP_LOCK:
            clips = _CLIPS.get(key)
            if clips is None:
                clips = ([self.synth_wav(p, agent) for p in ACK_PHRASES], [self.synth_wav(p, agent) for p in PERMISSION_PHRASES])
                _CLIPS[key] = clips
        self.acks[agent], self.perms[agent] = clips

    def remove_agent(self, name: str):
        for d in (self.voices, self.acks, self.perms):
            d.pop(name.lower(), None)

    def synth_wav(self, text: str, agent: str) -> bytes:
        if self.status != "ready":
            raise RuntimeError(f"Kokoro not ready ({self.status})")
        voice = self.voices.get(agent.lower(), VOICE_POOL[0])
        with self._lock:
            if self.model is None:
                raise RuntimeError("Kokoro is switching models")
            samples, sr = self.model.create(text[:1000], voice=voice, speed=self.speed, lang=self.lang)
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm)
        return buf.getvalue()


_PRELOADS: dict[Path, Future] = {}
_SYNTH_LOCK = threading.Lock()
_SWITCH_LOCK = threading.Lock()
_PRELOAD_LOCK = threading.Lock()
_CLIP_LOCK = threading.Lock()
_CLIPS: dict = {}   # shared startup clips: model, voice, speed, language


def _download(d: Path, name: str) -> Path:
    dest = d / name
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    d.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  narration: downloading {name} (one time) ...", flush=True)
    with urllib.request.urlopen(RELEASE + name, timeout=60) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)
    return dest


def _load_model(d: Path, speed: float, lang: str, file: str = FILES["model"]):
    from kokoro_onnx import Kokoro
    model = Kokoro(str(_download(d, file)), str(_download(d, FILES["voices"])))
    model.create("Ready.", voice=VOICE_POOL[0], speed=speed, lang=lang)  # warm-up
    return model


def preload(model_dir: Path, speed: float = 1.3, lang: str = "en-us", file: str = FILES["model"]) -> Future:
    """Start loading Kokoro in a background thread (once per model dir) and return its Future.
    Called at program start so the model is warm by the time the room opens."""
    with _PRELOAD_LOCK:
        key = (model_dir, file)
        f = _PRELOADS.get(key)
        if f is None:
            f = _PRELOADS[key] = Future()
            def run():
                try:
                    f.set_result(_load_model(model_dir, speed, lang, file))
                except BaseException as e:
                    f.set_exception(e)
            threading.Thread(target=run, name="kokoro-preload", daemon=True).start()
        return f


def preload_from_cfg(cfg: dict):
    c = cfg.get("narration") or {}
    if (c.get("engine") or "kokoro").lower() == "browser":
        return
    d = Path(cfg["workspace"]).expanduser().resolve() / "models" / "kokoro"
    preload(d, float(c.get("speed") or 1.3), c.get("lang") or "en-us", model_file(c.get("model")))


PERMISSION_PHRASES = ["I need your permission for this.", "Can I get your approval, please?", "I need a permission here."]
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
        self._closed = False
        self._thread: threading.Thread | None = None

    def close(self):
        """Release queued audio and wake waiters when a room is closed."""
        with self._cv:
            self._closed = True
            self._q.clear()
            for item in self.items.values():
                for done in item["done"]:
                    done.set()
            self.items.clear()
            self._order.clear()
            self._cv.notify_all()

    def start(self, mid: str, text: str, agent: str) -> list[str]:
        with self._cv:
            if self._closed:
                return []
            if mid in self.items:
                return self.items[mid]["parts"]
            parts = split_sentences(clean_for_speech(text[:4000]))
            item = {"parts": parts, "agent": agent, "wav": [None] * len(parts), "done": [threading.Event() for _ in parts]}
            self.items[mid] = item
            self._order.append(mid)
            evicted = set()
            while len(self._order) > self.keep:
                old_mid = self._order.popleft()
                old = self.items.pop(old_mid, None)
                evicted.add(old_mid)
                if old:
                    for done in old["done"]:
                        done.set()  # Do not leave an in-flight HTTP audio fetch waiting for 60s.
            if evicted:
                self._q = deque(job for job in self._q if job[0] not in evicted)
            self._q.extend((mid, i) for i in range(len(parts)))
            if self._thread is None and self._q:
                self._thread = threading.Thread(target=self._worker, daemon=True)
                self._thread.start()
            self._cv.notify()
            return parts

    def get(self, mid: str, i: int, timeout: float = 60) -> bytes | None:
        item = self.items.get(mid)
        if not item or i < 0 or i >= len(item["parts"]):
            return None
        item["done"][i].wait(timeout)
        return item["wav"][i]

    def _worker(self):
        while True:
            with self._cv:
                while not self._q and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
                mid, i = self._q.popleft()
                item = self.items.get(mid)
            if not item:
                continue
            try:
                item["wav"][i] = self.speaker.synth_wav(item["parts"][i], item["agent"])
            except Exception:
                item["wav"][i] = None
            item["done"][i].set()
