import asyncio
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from meetingroom.launcher import publish, remove_own_state, serve


class LauncherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'.app-runtime.json'

    def test_state_is_private_and_only_owner_cleans_it(self):
        publish(self.path,'http://127.0.0.1:8765/?t=secret')
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o600)
        self.assertEqual(json.loads(self.path.read_text())['pid'],os.getpid())
        self.path.write_text(json.dumps({'pid':os.getpid()+1,'url':'different'}))
        remove_own_state(self.path)
        self.assertTrue(self.path.exists())
        publish(self.path,'http://127.0.0.1:8765/?t=secret')
        remove_own_state(self.path)
        self.assertFalse(self.path.exists())

    async def test_publishes_only_when_ready_and_removes_after_shutdown(self):
        owner=self
        class Server:
            started=False
            async def serve(server):
                self.assertFalse(owner.path.exists())
                await asyncio.sleep(.01)
                server.started=True
                await asyncio.sleep(.1)
                self.assertTrue(owner.path.exists())
        await serve(Server(),self.path,'http://127.0.0.1:8765/?t=secret')
        self.assertFalse(self.path.exists())

    async def test_failed_start_does_not_publish_token(self):
        class Server:
            started=False
            async def serve(server):
                raise RuntimeError('port in use')
        with self.assertRaises(RuntimeError):
            await serve(Server(),self.path,'http://127.0.0.1:8765/?t=secret')
        self.assertFalse(self.path.exists())
