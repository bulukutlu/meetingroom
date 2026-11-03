import tempfile, unittest
from meetingroom import profile, tts, stt


class SpeechSettings(unittest.TestCase):
    def test_saved_beside_name(self):
        cfg = {"workspace": tempfile.mkdtemp()}
        self.assertEqual(profile.load_speech(cfg), {})
        profile.save(cfg, "Ada")
        profile.save_speech(cfg, stt_model="mlx-community/whisper-large-v3-turbo-q4", tts_model="")
        profile.save_speech(cfg, tts_model="kokoro-v1.0.int8.onnx")
        self.assertEqual(profile.load(cfg), "Ada")
        self.assertEqual(profile.load_speech(cfg), {"stt_model": "mlx-community/whisper-large-v3-turbo-q4",
                                                    "tts_model": "kokoro-v1.0.int8.onnx"})
        profile.save(cfg, "Bea")   # renaming keeps the models
        self.assertIn("stt_model", profile.load_speech(cfg))

    def test_kokoro_file_whitelist(self):
        self.assertEqual(tts.model_file("kokoro-v1.0.int8.onnx"), "kokoro-v1.0.int8.onnx")
        self.assertEqual(tts.model_file("../../etc/passwd"), tts.FILES["model"])
        self.assertEqual(tts.model_file(None), tts.FILES["model"])

    def test_choices_include_defaults(self):
        for eng, choices in stt.MODEL_CHOICES.items():
            self.assertIn(stt.DEFAULT_MODELS[eng], [m for m, _ in choices])
        self.assertIn(tts.FILES["model"], [m for m, _ in tts.MODEL_CHOICES])
