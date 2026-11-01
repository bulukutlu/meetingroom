import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from meetingroom import saved
from meetingroom.location import Location
from meetingroom.server import Room, create_hub


class SavedMeetingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = {"workspace": str(self.root), "user_name": "Host",
                    "agents": [{"name": "one", "provider": "mock", "role": "Reviewer"}]}

    def room(self):
        return Room(self.cfg, title="Reboot test")

    def test_roundtrip_context_screen_and_native_state(self):
        room = self.room()
        agent = room.agents["one"]
        agent.backend.thread_id = "native-thread"
        agent.backend.items = [{"role": "assistant", "content": "Earlier analysis"}]
        agent.approval, agent.effort = "auto", "high"
        asyncio.run(room.post("Host", "We decided on option B."))
        agent.seen = 1
        source = self.root / "plot.svg"
        source.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        asyncio.run(room.share(agent, source, "Decision plot"))
        saved.checkpoint(room, "saved")
        state = saved.read(room.session_dir.parent, room.session)
        restored = Room({**self.cfg, "agents": [a["spec"] for a in state["agents"]]},
                        session=room.session, title=state["title"], token="new-token")
        restored.agents["one"].backend.thread_id = None
        restored.agents["one"].backend.items = []
        saved.restore(restored, state)
        self.assertEqual(restored.messages, room.messages)
        self.assertEqual(restored.shared, room.shared)
        self.assertTrue(next(iter(restored.files.values())).is_file())
        a = restored.agents["one"]
        self.assertEqual(a.backend.thread_id, "native-thread")
        self.assertEqual(a.backend.items, agent.backend.items)
        self.assertEqual((a.approval, a.effort), ("auto", "high"))
        self.assertIn("We decided on option B.", a._gather_context())
        self.assertTrue(a.queue.empty())

    def test_discard_retains_minutes_but_removes_resume(self):
        room = self.room()
        asyncio.run(room.post("Host", "Keep the minutes."))
        asyncio.run(room.shutdown(save=False))
        self.assertTrue((room.session_dir / "minutes.md").exists())
        self.assertEqual(saved.list_saved(room.session_dir.parent, set()), [])
        with self.assertRaises(ValueError):
            saved.read(room.session_dir.parent, room.session)

    def test_crash_checkpoint_and_invalid_files(self):
        room = self.room()
        asyncio.run(room.post("Host", "Survive a crash."))
        root = room.session_dir.parent
        broken = root / "broken"
        broken.mkdir()
        (broken / "room.json").write_text("{unfinished")
        listing = saved.list_saved(root, set())
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["status"], "recovery")
        self.assertEqual(saved.list_saved(root, {room.session}), [])
        for bad in ("../outside", ".", "..", "/tmp"):
            with self.assertRaises(ValueError):
                saved.read(root, bad)

    def test_no_credentials_or_connection_tokens_written(self):
        room = self.room()
        room.token = "DO-NOT-SAVE"
        room.agents["one"].spec["api_key"] = "SECRET-KEY"
        saved.checkpoint(room)
        text = (room.session_dir / "room.json").read_text()
        self.assertNotIn("DO-NOT-SAVE", text)
        self.assertNotIn("SECRET-KEY", text)
        self.assertEqual((room.session_dir / "room.json").stat().st_mode & 0o777, 0o600)

    def test_new_hub_reopens_and_does_not_duplicate_room(self):
        room = self.room()
        asyncio.run(room.post("Host", "Remember this next time."))
        saved.checkpoint(room, "saved")
        app = create_hub(self.cfg, 8765, "fresh-token")
        headers = {"origin": "http://127.0.0.1:8765"}
        with patch.object(Room, "start"), TestClient(app, base_url="http://127.0.0.1:8765") as client:
            self.assertEqual(client.get("/api/saved").status_code, 403)
            self.assertEqual(len(client.get("/api/saved?t=fresh-token").json()["rooms"]), 1)
            self.assertEqual(client.post("/api/restore?t=fresh-token", json={"session": room.session}).status_code, 403)
            res = client.post("/api/restore?t=fresh-token", headers=headers, json={"session": room.session})
            self.assertEqual(res.status_code, 200, res.text)
            again = client.post("/api/restore?t=fresh-token", headers=headers, json={"session": room.session})
            self.assertEqual(again.json()["url"], res.json()["url"])
            reopened = next(iter(app.state.hub.rooms.values()))
            self.assertEqual(reopened.session, room.session)
            self.assertEqual(reopened.messages[0]["text"], "Remember this next time.")
            self.assertEqual(client.get("/api/saved?t=fresh-token").json()["rooms"], [])

    def test_missing_project_does_not_consume_save(self):
        room = self.room()
        room.location = Location(kind="local", path=str(self.root / "missing"))
        saved.checkpoint(room, "saved")
        app = create_hub(self.cfg, 8765, "token")
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            res = client.post("/api/restore?t=token", headers={"origin": "http://127.0.0.1:8765"},
                              json={"session": room.session})
            self.assertEqual(res.status_code, 400)
            self.assertIn("does not exist", res.json()["error"])
            self.assertEqual(saved.read(room.session_dir.parent, room.session)["status"], "saved")

    def test_atomic_write_failure_preserves_previous_checkpoint(self):
        room = self.room()
        saved.checkpoint(room, "saved")
        original = (room.session_dir / "room.json").read_bytes()
        with patch.object(saved.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                saved.checkpoint(room)
        self.assertEqual((room.session_dir / "room.json").read_bytes(), original)
        self.assertEqual(list(room.session_dir.glob(".room-*")), [])

    def test_save_failure_keeps_room_available_for_retry(self):
        app = create_hub(self.cfg, 8765, "token")
        hub = app.state.hub
        with patch.object(Room, "start"):
            room = asyncio.run(hub.open_room(["one"], Location()))
        with patch.object(saved, "checkpoint", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                asyncio.run(hub.close_room(room.rid))
        self.assertIn(room.rid, hub.rooms)
        asyncio.run(hub.close_room(room.rid))
        self.assertNotIn(room.rid, hub.rooms)
