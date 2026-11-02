import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from meetingroom.server import create_hub
from meetingroom.storage import compact, copy_snapshot


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.a = self.root / 'meetings/a/shared/one_report.pdf'
        self.b = self.root / 'meetings/b/shared/two_report.pdf'
        for p in [self.a,self.b]:
            p.parent.mkdir(parents=True)
            p.write_bytes(b'PDF snapshot\n' * 1000)
        self.cache = self.root / 'meetings/a/pages/page.png'
        self.cache.parent.mkdir()
        self.cache.write_bytes(b'cached image')
        self.log = self.root / 'meetings/a/transcript.jsonl'
        self.log.write_text('Important meeting text')

    def test_dry_run_and_lossless_compaction_and_idempotence(self):
        before = self.b.read_bytes()
        result = compact(self.root,dry_run=True)
        self.assertGreater(result['duplicate_bytes'],0)
        self.assertTrue(self.cache.exists())
        self.assertNotEqual(self.a.stat().st_ino,self.b.stat().st_ino)
        result = compact(self.root)
        self.assertGreater(result['reclaimed_bytes'],0)
        self.assertEqual(self.a.stat().st_ino,self.b.stat().st_ino)
        self.assertEqual(self.b.read_bytes(),before)
        self.assertFalse(self.cache.exists())
        self.assertEqual(self.log.read_text(),'Important meeting text')
        self.assertEqual(compact(self.root)['reclaimed_bytes'],0)

    def test_live_room_cache_is_preserved(self):
        compact(self.root,active={'a'})
        self.assertTrue(self.cache.exists())

    def test_new_snapshots_reuse_archives_but_never_the_original(self):
        source=self.root/'report.pdf';source.write_bytes(self.a.read_bytes())
        dest=self.b.with_name('three_report.pdf')
        copy_snapshot(source,dest,self.root)
        self.assertEqual(dest.stat().st_ino,self.a.stat().st_ino)
        self.assertNotEqual(dest.stat().st_ino,source.stat().st_ino)
        source.write_bytes(b'Changed project output')
        self.assertNotEqual(dest.read_bytes(),source.read_bytes())

    def test_link_failure_keeps_both_files(self):
        before=self.b.read_bytes()
        with patch('meetingroom.storage.os.link',side_effect=OSError('unsupported filesystem')):
            result=compact(self.root)
        self.assertGreater(result['skipped_files'],0)
        self.assertEqual(self.b.read_bytes(),before)
        self.assertEqual(self.a.read_bytes(),before)
        self.assertEqual(list(self.b.parent.glob('.compact-*')),[])

    def test_already_linked_duplicate_group_is_fully_compacted(self):
        third=self.b.with_name('third_report.pdf');os.link(self.b,third)
        compact(self.root)
        self.assertEqual({p.stat().st_ino for p in [self.a,self.b,third]},{self.a.stat().st_ino})

    def test_same_size_different_contents_are_preserved(self):
        self.b.write_bytes(b'X'*self.a.stat().st_size)
        compact(self.root)
        self.assertNotEqual(self.b.read_bytes(),self.a.read_bytes())

    def test_endpoints_require_auth_and_keep_active_pages(self):
        app=create_hub({'workspace':str(self.root),'agents':[]},8765,'token')
        from types import SimpleNamespace
        app.state.hub.rooms['active']=SimpleNamespace(session='a')
        # No lifespan: this test's fake live room must not be shut down by the app.
        client=TestClient(app,base_url='http://127.0.0.1:8765')
        self.assertEqual(client.get('/api/storage').status_code,403)
        self.assertEqual(client.post('/api/storage/compact?t=token',json={}).status_code,403)
        res=client.post('/api/storage/compact?t=token',headers={'origin':'http://127.0.0.1:8765'},json={})
        self.assertEqual(res.status_code,200)
        self.assertTrue(self.cache.exists())

    def test_closing_room_compacts_archives_and_leaves_live_room_untouched(self):
        import asyncio
        from meetingroom.server import Room
        from meetingroom.location import Location
        async def go():
            cfg={'workspace':str(self.root),'agents':[{'name':'one','provider':'mock'}]}
            hub=create_hub(cfg,8765,'token').state.hub
            with patch.object(Room,'start'):
                closed=await hub.open_room(['one'],Location())
                live=await hub.open_room(['one'],Location())
            closed_file=closed.shared_dir/'close_report.pdf'
            live_file=live.shared_dir/'live_report.pdf'
            for p in [closed_file,live_file]:p.write_bytes(self.a.read_bytes())
            live_inode=live_file.stat().st_ino
            live_cache=live.session_dir/'pages/test.png'
            live_cache.parent.mkdir();live_cache.write_bytes(b'active preview')
            closed_cache=closed.session_dir/'pages/test.png'
            closed_cache.parent.mkdir();closed_cache.write_bytes(b'closed preview')
            await hub.close_room(closed.rid)
            self.assertNotIn(closed.rid,hub.rooms)
            self.assertIn(live.rid,hub.rooms)
            self.assertEqual(closed_file.stat().st_ino,self.a.stat().st_ino)
            self.assertEqual(live_file.stat().st_ino,live_inode)
            self.assertTrue(live_cache.exists())
            self.assertFalse(closed_cache.exists())
            self.assertTrue((closed.session_dir/'room.json').exists())
            await hub.close_room(live.rid)
            self.assertEqual(live_file.stat().st_ino,self.a.stat().st_ino)
            self.assertFalse(live_cache.exists())
        asyncio.run(go())

    def test_cleanup_failure_does_not_prevent_successful_close(self):
        import asyncio
        from meetingroom.server import Room
        from meetingroom.location import Location
        async def go():
            hub=create_hub({'workspace':str(self.root),'agents':[{'name':'one','provider':'mock'}]},8765,'token').state.hub
            with patch.object(Room,'start'):
                room=await hub.open_room(['one'],Location())
            with patch('meetingroom.server.storage.compact',side_effect=OSError('no space')):
                await hub.close_room(room.rid)
            self.assertNotIn(room.rid,hub.rooms)
            self.assertTrue((room.session_dir/'room.json').exists())
        asyncio.run(go())
