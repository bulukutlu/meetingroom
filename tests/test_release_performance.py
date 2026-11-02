import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from meetingroom import storage
from meetingroom.server import Room
from meetingroom.tts import MessageAudio


class ReleasePerformanceTests(unittest.TestCase):
    def test_already_deduplicated_archives_need_no_content_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a=root/'meetings/a/shared/a.pdf';a.parent.mkdir(parents=True);a.write_bytes(b'x'*1024)
            b=root/'meetings/b/shared/b.pdf';b.parent.mkdir(parents=True);os.link(a,b)
            with patch.object(storage,'digest',side_effect=AssertionError('unexpected file read')):
                self.assertEqual(storage.compact(root)['reclaimed_bytes'],0)

    def test_hash_cache_reuses_reads_and_invalidates_after_same_size_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'snapshot';p.write_bytes(b'first')
            storage._digest.cache_clear()
            with patch('builtins.open',wraps=open) as opened:
                first=storage.digest(p)
                self.assertEqual(first,storage.digest(p))
                self.assertEqual(opened.call_count,1)
                before=p.stat();p.write_bytes(b'other');os.utime(p,ns=(before.st_atime_ns,before.st_mtime_ns))
                self.assertNotEqual(first,storage.digest(p))
                self.assertEqual(opened.call_count,2)

    def test_failed_snapshot_copy_does_not_publish_a_partial_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.txt';source.write_text('complete original')
            dest=root/'meetings/a/shared/id_result.txt';dest.parent.mkdir(parents=True)
            def fail(src,partial):
                partial.write_text('incomplete');raise OSError('disk full')
            with patch.object(shutil,'copy2',side_effect=fail):
                with self.assertRaises(OSError):storage.copy_snapshot(source,dest,root)
            self.assertFalse(dest.exists())
            self.assertEqual(list(dest.parent.iterdir()),[])
            self.assertEqual(source.read_text(),'complete original')

    def test_audio_eviction_wakes_waiters_and_bounds_pending_synthesis(self):
        entered,release=threading.Event(),threading.Event()
        class Speaker:
            def synth_wav(self,text,agent):
                entered.set();release.wait(3);return b'audio'
        audio=MessageAudio(Speaker(),keep=2)
        audio.start('old','One. Two.','one')
        self.assertTrue(entered.wait(1));old=audio.items['old']
        try:
            for n in range(100):audio.start(str(n),'One. Two.','one')
            self.assertEqual(len(audio.items),2)
            self.assertLessEqual(len(audio._q),4)
            self.assertTrue(all(done.is_set() for done in old['done']))
            self.assertTrue(all(mid in audio.items for mid,i in audio._q))
            self.assertIsNone(audio.get('99',-1))
        finally:
            audio.close();release.set();audio._thread.join(1)
        self.assertFalse(audio._thread.is_alive())

    def test_sharing_a_large_file_does_not_block_the_event_loop(self):
        async def go():
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                room=Room({'workspace':tmp,'agents':[{'name':'one','provider':'mock'}]})
                source=root/'plot.txt';source.write_text('result')
                heartbeat=threading.Event();seen=[]
                def copy(src,dest,workspace):
                    seen.append(heartbeat.wait(1));shutil.copy2(src,dest)
                with patch.object(storage,'copy_snapshot',side_effect=copy):
                    task=asyncio.create_task(room.share(room.agents['one'],source,'Result'))
                    await asyncio.sleep(.01)
                    heartbeat.set()
                    await task
                self.assertEqual(seen,[True])
                self.assertEqual(next(iter(room.files.values())).read_text(),'result')
        asyncio.run(go())
