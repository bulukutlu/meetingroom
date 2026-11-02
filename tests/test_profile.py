import tempfile
import unittest

from meetingroom import profile
from meetingroom.picker import lobby_page


class ProfileTests(unittest.TestCase):
    def test_first_launch_then_saved(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {"workspace": d}
            self.assertIsNone(profile.load(cfg))
            self.assertEqual(profile.save(cfg, "  Ada   Lovelace "), "Ada Lovelace")
            self.assertEqual(profile.load(cfg), "Ada Lovelace")
            with self.assertRaises(ValueError):
                profile.save(cfg, "   ")

    def test_lobby_embeds_name_and_prompt_flag(self):
        page = lobby_page([{"name": "a", "provider": "mock", "color": "#fff"}], "tok", "Ada </x>", True)
        self.assertIn("if(true)", page)
        self.assertNotIn("Ada </x>", page)


if __name__ == "__main__":
    unittest.main()
