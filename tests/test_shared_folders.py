import asyncio
import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from meetingroom import mcp_bridge, saved, tools
from meetingroom.server import Room, create_hub
from meetingroom.location import Location


class SharedFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.cfg = {'workspace': str(self.root), 'agents': [{'name': 'one', 'provider': 'mock', 'add_dirs': [str(self.root)]}]}
        self.files = [self.root / 'plot_one.svg', self.root / 'summary.md']
        self.files[0].write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.files[1].write_text('# Results\n42')

    def test_folder_publishes_once_and_survives_save(self):
        room = Room(self.cfg)
        room.broadcast = AsyncMock()
        asyncio.run(room.share(room.agents['one'], self.files, 'Results'))
        room.broadcast.assert_awaited_once()
        folder = room.shared[-1]
        self.assertEqual(folder['kind'], 'folder')
        self.assertEqual([c['name'] for c in folder['children']], ['plot_one.svg', 'summary.md'])
        for c in folder['children']:
            self.assertEqual(c['parent'], folder['id'])
            self.assertTrue(room.files[c['id']].is_file())
        checkpoint = saved.read(room.session_dir.parent, room.session)
        self.assertEqual(checkpoint['shared'], room.shared)

    def test_invalid_batch_does_not_publish_partial_files(self):
        room = Room(self.cfg)
        with self.assertRaises(ValueError):
            asyncio.run(room.share(room.agents['one'], self.files + [self.root / 'missing'], 'Bad'))
        self.assertEqual(room.shared, [])
        self.assertEqual(room.files, {})

    def test_api_tool_and_approval_check_every_file(self):
        cb = AsyncMock(return_value='shared folder')
        args = {'paths': [str(p) for p in self.files], 'title': 'Results'}
        self.assertEqual(asyncio.run(tools.execute('share_to_screen', args, self.root, 'python', cb)), 'shared folder')
        cb.assert_awaited_once_with(self.files, 'Results')
        self.assertFalse(tools.needs_approval('share_to_screen', args, self.root))
        self.assertTrue(tools.needs_approval('share_to_screen', {'paths': [str(self.files[0]), '/outside/file']}, self.root))
        cb.reset_mock()
        self.assertIn('error:', asyncio.run(tools.execute('share_to_screen', {'paths': []}, self.root, 'python', cb)))
        cb.assert_not_awaited()

    def test_bridge_remote_uploads_every_file(self):
        with patch.object(mcp_bridge, 'UPLOAD', True), patch.object(mcp_bridge, 'hub', return_value={'text': 'folder'}) as hub:
            self.assertEqual(mcp_bridge.call('share_to_screen', {'paths': [str(p) for p in self.files]}), 'folder')
        entries = hub.call_args.args[1]['files']
        self.assertEqual([base64.b64decode(e['content_b64']) for e in entries], [p.read_bytes() for p in self.files])

    def test_http_local_and_uploaded_folders_and_child_access(self):
        app = create_hub(self.cfg, 8765, 'token')
        with patch.object(Room, 'start'):
            room = asyncio.run(app.state.hub.open_room(['one'], Location()))
        with TestClient(app, base_url='http://127.0.0.1:8765') as client:
            url = room.base + '/internal/share'
            headers = {'x-mr-token': 'token'}
            res = client.post(url, headers=headers, json={'agent': 'one', 'files': [{'path': str(p)} for p in self.files], 'title': 'Local'})
            self.assertIn('2 files', res.json()['text'])
            self.assertEqual(room.shared[-1]['children'][0]['name'], 'plot_one.svg')
            entries = [{'path': '/remote/output_' + str(i) + '.md', 'content_b64': base64.b64encode(b'# Remote').decode()} for i in range(2)]
            res = client.post(url, headers=headers, json={'agent': 'one', 'files': entries, 'title': 'Remote'})
            self.assertIn('2 files', res.json()['text'])
            child = room.shared[-1]['children'][0]
            self.assertEqual(child['name'], 'output_0.md')
            fetched = client.get(room.base + '/files/' + child['id'] + '?t=token')
            self.assertEqual(fetched.text, '# Remote')
            before = len(room.shared)
            res = client.post(url, headers=headers, json={'agent': 'one', 'files': [{'path': str(self.files[0])}, {'path': '/missing'}]})
            self.assertIn('error:', res.json()['text'])
            self.assertEqual(len(room.shared), before)
            self.assertEqual(client.post(url, json={'agent': 'one', 'files': entries}).status_code, 403)
