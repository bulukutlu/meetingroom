import unittest
from unittest.mock import Mock, patch
import numpy as np
from meetingroom.stt import Transcriber, SAMPLE_RATE


class LiveSpeechTests(unittest.TestCase):
    def transcriber(self):
        st = Transcriber({'engine': 'echo'}, 'Host', ['Helga'])
        st.load()
        return st

    def test_continuous_speech_is_not_mistaken_for_its_own_noise_floor(self):
        st = self.transcriber()
        st.vad = object()
        st._run = Mock(return_value='Continuous speech')
        audio = np.full(SAMPLE_RATE * 2, .1, dtype=np.float32)
        with patch('silero_vad.get_speech_timestamps', return_value=[{'start': 0, 'end': len(audio)}]):
            self.assertEqual(st.transcribe(audio), 'Continuous speech')
        self.assertEqual(len(st._run.call_args.args[0]), len(audio))

    def test_silence_does_not_invoke_decoder(self):
        st = self.transcriber()
        st._run = Mock()
        self.assertEqual(st.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32)), '')
        st._run.assert_not_called()

    def test_vad_rejects_non_speech_before_decoding(self):
        st = self.transcriber()
        st.vad = object()
        st._run = Mock()
        with patch('silero_vad.get_speech_timestamps', return_value=[]):
            self.assertEqual(st.transcribe(np.full(SAMPLE_RATE, .2, dtype=np.float32)), '')
        st._run.assert_not_called()

    def test_vad_keeps_pauses_between_speech_regions(self):
        st = self.transcriber()
        st.vad = object()
        st._run = Mock(return_value='Please compare both plots.')
        audio = np.arange(SAMPLE_RATE * 3, dtype=np.float32) / (SAMPLE_RATE * 3)
        regions = [{'start': 1000, 'end': 10000}, {'start': 22000, 'end': 40000}]
        with patch('silero_vad.get_speech_timestamps', return_value=regions):
            self.assertEqual(st.transcribe(audio), 'Please compare both plots.')
        np.testing.assert_array_equal(st._run.call_args.args[0], audio[1000:40000])

    def test_invalid_samples_are_rejected(self):
        st = self.transcriber()
        for invalid in [np.array([np.nan], dtype=np.float32), np.array([np.inf], dtype=np.float32), np.zeros((2, 100))]:
            with self.assertRaises(ValueError): st.transcribe(invalid)

    def test_live_capability_requires_ready_model_and_detector(self):
        st = self.transcriber()
        self.assertTrue(st.public()['live'])
        st.status = 'error'
        self.assertFalse(st.public()['live'])
        st.status, st.engine = 'ready', 'mlx'
        self.assertFalse(st.public()['live'])
        st.vad = object()
        self.assertTrue(st.public()['live'])
