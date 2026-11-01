import asyncio
from concurrent.futures import Future
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from meetingroom import tools, tts


class PerformanceTests(unittest.TestCase):
    def test_file_pages_preserve_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "input.txt").write_text("".join(f"line {i}\n" for i in range(401)))

            def read(**kwargs):
                return asyncio.run(tools.execute("read_file", {"path": "input.txt", **kwargs}, root, "python3", None))

            first = read()
            self.assertTrue(first.startswith("line 0\n"))
            self.assertIn("line 199\n", first)
            self.assertNotIn("line 200\n", first)
            self.assertIn("offset=200", first)
            self.assertEqual(read(offset=400), "line 400\n")
            self.assertEqual(read(offset=401), "")
            self.assertIn("error:", read(offset=-1))
            self.assertIn("error:", read(limit=0))

    def test_startup_clips_reused_by_voice_and_settings(self):
        model = object()
        future = Future()
        future.set_result(model)
        calls = []

        def synth(speaker, text, agent):
            calls.append((speaker.voices[agent], speaker.speed, text))
            return text.encode()

        specs = [{"name": "one", "voice": "am_michael"},
                 {"name": "two", "voice": "am_michael"}]
        with patch.object(tts, "_CLIPS", {}), patch.object(tts, "preload", return_value=future), \
                patch.object(tts.Speaker, "synth_wav", synth):
            first = tts.Speaker({}, Path("/tmp"), specs)
            first.load()
            second = tts.Speaker({}, Path("/tmp"), specs)
            second.load()
            self.assertEqual(len(calls), len(tts.ACK_PHRASES) + len(tts.PERMISSION_PHRASES))
            self.assertIs(first.acks["one"], second.acks["two"])
            different = tts.Speaker({"speed": 1.5}, Path("/tmp"), specs)
            different.load()
            self.assertEqual(len(calls), 2 * (len(tts.ACK_PHRASES) + len(tts.PERMISSION_PHRASES)))

    def test_audio_worker_is_lazy_and_stops_on_close(self):
        entered, release = threading.Event(), threading.Event()

        class FakeSpeaker:
            def synth_wav(self, text, agent):
                entered.set()
                release.wait(3)
                return b"audio"

        audio = tts.MessageAudio(FakeSpeaker())
        self.assertIsNone(audio._thread)
        audio.start("m", "First sentence. Second sentence.", "one")
        self.assertTrue(entered.wait(2))
        item = audio.items["m"]
        try:
            audio.close()
            self.assertTrue(all(done.is_set() for done in item["done"]))
            self.assertFalse(audio.items)
            self.assertFalse(audio._q)
            self.assertEqual(audio.start("later", "Ignored.", "one"), [])
        finally:
            release.set()
            audio._thread.join(2)
        self.assertFalse(audio._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
