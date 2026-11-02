"""Local speech-to-text with Whisper. Audio never leaves your computer.

Engines (picked automatically):
  - mlx-whisper   on Apple Silicon Macs (runs on the GPU, fastest)
  - faster-whisper everywhere else (CPU, int8)
The model is downloaded once from Hugging Face on first start and cached.
"""
from __future__ import annotations

import platform
import re
import threading
import time

import numpy as np

SAMPLE_RATE = 16000
_MODELS: dict = {}
_LOAD_LOCK = threading.Lock()    # rooms opened together load the model once
_RUN_LOCK = threading.Lock()     # one model shared by every room: one transcription at a time   # (engine, model) -> loaded model, kept for the next room in this process
DEFAULT_MODELS = {
    "mlx": "mlx-community/whisper-large-v3-turbo",
    "faster": "large-v3-turbo",
}


def _key(s: str) -> str:
    """'ALICE 4,' -> 'alice', 'ITS3' -> 'its': letters only, for loose term matching."""
    return re.sub(r"[^a-z]", "", s.lower())


class Transcriber:
    def __init__(self, voice_cfg: dict | None, user: str, agent_names: list[str]):
        v = voice_cfg or {}
        self.wanted = (v.get("engine") or "whisper").lower()  # whisper | browser | echo (testing)
        self.model_name = v.get("model") or None
        self.language = v.get("language") or None
        vocab = [str(w) for w in (v.get("vocabulary") or [])]
        names = ", ".join(n.capitalize() for n in agent_names)
        # Vocabulary goes in as prose, not a bare comma list: a list in the prompt
        # is what Whisper "continues" on noise ("ALICE 3, ITS3, ALICE 4, ...").
        self.prompt = f"{user} is in a meeting with {names}." + (
            f" The discussion may mention {', '.join(vocab[:-1])} and {vocab[-1]}." if len(vocab) > 1 else
            f" The discussion may mention {vocab[0]}." if vocab else "")
        # Letters-only keys of every prompt term, to spot transcripts made of prompt terms only.
        self._terms = {_key(w) for w in [*vocab, *agent_names, user]} - {""}
        self.engine = None      # 'mlx' | 'faster' | 'echo'
        self.model = None
        self.vad = None
        self.status = "off" if self.wanted == "browser" else "loading"
        self.detail = ""
        self._lock = threading.Lock()

    def public(self) -> dict:
        return {"status": self.status, "engine": self.engine, "model": self.model_name, "detail": self.detail,
                "live": self.status == "ready" and (self.vad is not None or self.engine == "echo")}

    # ---------------- loading (runs in a background thread at startup)
    def load(self):
        with _LOAD_LOCK:
            self._load()

    def _load(self):
        if self.wanted == "browser":
            return
        if self.wanted == "echo":
            self.engine, self.status = "echo", "ready"
            return
        try:
            try:
                from silero_vad import load_silero_vad
                if ("vad", "silero") not in _MODELS:
                    _MODELS["vad", "silero"] = load_silero_vad(onnx=True)
                self.vad = _MODELS["vad", "silero"]
            except Exception as e:
                self.detail = f"Live dictation disabled: speech detector unavailable ({e}). Batch dictation still works."
                print(f"  voice: {self.detail}", flush=True)
            if platform.system() == "Darwin" and platform.machine() == "arm64":
                try:
                    import mlx_whisper  # noqa: F401
                    self.engine = "mlx"
                except ImportError:
                    pass
            if self.engine is None:
                from faster_whisper import WhisperModel
                self.engine = "faster"
                self.model_name = self.model_name or DEFAULT_MODELS["faster"]
                if ("faster", self.model_name) in _MODELS:
                    self.model, self.status = _MODELS["faster", self.model_name], "ready"
                    return
                print(f"  voice: loading Whisper '{self.model_name}' (first time downloads it) ...", flush=True)
                self.model = WhisperModel(self.model_name, device="auto", compute_type="int8")
            else:
                self.model_name = self.model_name or DEFAULT_MODELS["mlx"]
                if ("mlx", self.model_name) in _MODELS:   # mlx_whisper keeps the weights itself
                    self.status = "ready"
                    return
                print(f"  voice: loading Whisper '{self.model_name}' (first time downloads ~1.6 GB) ...", flush=True)
            t = time.time()
            self._run(np.zeros(SAMPLE_RATE, dtype=np.float32))  # warm-up (and download)
            _MODELS[self.engine, self.model_name] = self.model
            self.status = "ready"
            print(f"  voice: Whisper ready ({self.engine}, {time.time() - t:.1f}s warm-up)", flush=True)
        except Exception as e:
            self.status, self.detail = "error", f"{type(e).__name__}: {e}"
            print(f"  voice: local Whisper unavailable, using browser speech instead ({self.detail})", flush=True)

    # ---------------- transcription
    def _run(self, audio: np.ndarray, prev: str = "") -> str:
        if self.engine == "echo":
            return f"[{len(audio) / SAMPLE_RATE:.1f}s]"
        if self.engine == "mlx":
            import mlx_whisper
            r = mlx_whisper.transcribe(audio, path_or_hf_repo=self.model_name, language=self.language,
                                       initial_prompt=(self.prompt + " " + prev).strip(), temperature=0.0,
                                       condition_on_previous_text=False, verbose=None)
            segs = [(s.get("text", ""), s.get("no_speech_prob", 0), s.get("avg_logprob", 0),
                     s.get("compression_ratio", 1)) for s in r.get("segments") or []]
        else:
            out, _ = self.model.transcribe(audio, language=self.language, initial_prompt=(self.prompt + " " + prev).strip(),
                                           beam_size=1, condition_on_previous_text=False, vad_filter=True)
            segs = [(s.text, s.no_speech_prob, s.avg_logprob, s.compression_ratio) for s in out]
        # Drop segments Whisper itself flags as non-speech or as degenerate/looping output.
        return " ".join(t for t, nsp, lp, cr in segs
                        if not (nsp > 0.6 and lp < -0.7) and lp > -1.5 and cr < 2.4)

    def strip_term_lists(self, text: str) -> str:
        """Remove runs of 3+ comma/period-separated chunks that consist only of
        prompt terms (optionally with a number), e.g. 'ALICE 3, ITS3, ALICE 4,
        ITS3' - Whisper's prompt echo on background noise. Real speech around the
        run is kept."""
        chunks = re.split(r"(?<=[,.;!?])\s+", text.strip())
        is_term = [_key(c) in self._terms for c in chunks]
        out, i = [], 0
        while i < len(chunks):
            j = i
            while j < len(chunks) and is_term[j]:
                j += 1
            if j - i >= 3 or (j - i >= 2 and len(chunks) == j - i):   # a run of terms (or the whole text)
                i = j
                continue
            out.append(chunks[i]); i += 1
        return " ".join(out).strip(" ,;")

    @staticmethod
    def trim_silence(audio: np.ndarray, pad: float = 0.3) -> np.ndarray:
        """Cut leading/trailing silence: less audio to decode (faster) and fewer
        chances for Whisper to invent words from background noise."""
        frame = 320  # 20 ms
        n = len(audio) // frame
        if n < 3:
            return audio
        rms = np.sqrt(np.mean(audio[: n * frame].reshape(n, frame) ** 2, axis=1))
        thr = max(0.01, float(np.percentile(rms, 20)) * 3)
        voiced = np.nonzero(rms > thr)[0]
        if len(voiced) < 12:          # < ~0.25 s of sound above the noise floor: nothing was said
            return audio[:0]
        p = int(pad * SAMPLE_RATE)
        return audio[max(0, voiced[0] * frame - p): min(len(audio), (voiced[-1] + 1) * frame + p)]

    @staticmethod
    def clean(text: str) -> str:
        """Remove typical Whisper hallucinations: character runs like 'ssssss'
        and the same sentence repeated over and over."""
        text = re.sub(r"\b(\w)\1{3,}\b[.,!?]?", "", text)          # 'sssss' as a whole word -> drop
        text = re.sub(r"(\w)\1{4,}", r"\1\1", text)                 # inside a word -> shorten
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        out = []
        for p in parts:
            if p and not (out and p.strip().lower() == out[-1].strip().lower()):
                out.append(p)
        text = " ".join(out)
        words = text.split()                       # collapse a repeated 3-8 word phrase
        low = [w.lower() for w in words]           # lower-cased once, kept in step with words
        for n in range(8, 2, -1):
            i = 0
            while i + 2 * n <= len(words):
                if low[i:i + n] == low[i + n:i + 2 * n]:
                    del words[i + n:i + 2 * n], low[i + n:i + 2 * n]
                else:
                    i += 1
        low = [w.strip(",.") for w in low]
        for n in (2, 1):                           # short phrase repeated 3+ times
            i = 0
            while i + 3 * n <= len(words):
                if low[i:i + n] == low[i + n:i + 2 * n] == low[i + 2 * n:i + 3 * n]:
                    del words[i + n:i + 2 * n], low[i + n:i + 2 * n]
                else:
                    i += 1
        return " ".join(words)

    def transcribe(self, audio: np.ndarray, prev: str = "") -> str:
        if self.status != "ready":
            raise RuntimeError(f"Whisper not ready ({self.status})")
        if audio.ndim != 1 or not np.isfinite(audio).all():
            raise ValueError("Audio must be finite mono PCM")
        if len(audio) < SAMPLE_RATE * 0.3:
            return ""
        with _RUN_LOCK:
            if self.vad is not None:
                from silero_vad import get_speech_timestamps
                import torch
                speech = get_speech_timestamps(torch.from_numpy(audio.copy()), self.vad,
                    sampling_rate=SAMPLE_RATE, threshold=0.6, min_speech_duration_ms=250,
                    min_silence_duration_ms=500, speech_pad_ms=300)
                if not speech:
                    return ""
                # Keep pauses and word boundaries; never concatenate isolated VAD chunks.
                audio = audio[speech[0]["start"]:speech[-1]["end"]]
            else:
                audio = self.trim_silence(audio)
            if len(audio) < SAMPLE_RATE * 0.3:
                return ""
            text = self.strip_term_lists(self.clean(self._run(audio, prev).strip()))
        if not re.search(r"\w", text):   # only punctuation left ('.', '...')
            return ""
        # Drop a prompt echo, which Whisper sometimes produces on unclear audio.
        if len(text) > 25 and text.rstrip(".") in f"{self.prompt} {prev}":
            return ""
        return text
