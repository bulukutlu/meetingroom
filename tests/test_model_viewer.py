import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from meetingroom.location import Location
from meetingroom.server import Room, create_hub, kind_of


class ModelViewerTests(unittest.TestCase):
    def test_model_files_use_authenticated_shared_file_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            cfg = {'workspace': str(root), 'agents': [{'name': 'one', 'provider': 'mock', 'add_dirs': [str(root)]}]}
            app = create_hub(cfg, 8765, 'token')
            with patch.object(Room, 'start'):
                room = asyncio.run(app.state.hub.open_room(['one'], Location()))
            with TestClient(app, base_url='http://127.0.0.1:8765') as client:
                for extension in ('.stl', '.obj', '.glb', '.STL'):
                    with self.subTest(extension=extension):
                        model = root / ('model' + extension)
                        model.write_bytes(b'model bytes')
                        self.assertEqual(kind_of(model), 'model3d')
                        response = client.post(room.base + '/internal/share', headers={'x-mr-token': 'token'}, json={
                            'agent': 'one', 'path': str(model), 'title': 'Model',
                        })
                        self.assertEqual(response.status_code, 200)
                        shared = room.shared[-1]
                        self.assertEqual(shared['kind'], 'model3d')
                        url = room.base + '/files/' + shared['id']
                        self.assertEqual(client.get(url).status_code, 403)
                        response = client.get(url, params={'f': room.file_token(shared['id'])})
                        self.assertEqual(response.content, b'model bytes')
                self.assertEqual(client.get('/static/model-viewer.html').status_code, 200)
                for addon in ('controls/OrbitControls', 'loaders/STLLoader', 'loaders/OBJLoader', 'loaders/GLTFLoader'):
                    self.assertEqual(client.get('/static/vendor/addons/' + addon + '.js').status_code, 200)
