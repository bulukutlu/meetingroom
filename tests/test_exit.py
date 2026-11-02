import tempfile
import unittest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from meetingroom.server import create_hub


class CorridorExitTests(unittest.TestCase):
    def test_quit_requires_token_and_origin_and_preserves_save_choice(self):
        with tempfile.TemporaryDirectory() as root:
            app = create_hub({'workspace': root, 'agents': []}, 8765, 'token')
            hub = app.state.hub
            async def quit(save=True):
                hub._quitting = True
            hub.quit = AsyncMock(side_effect=quit)
            with TestClient(app, base_url='http://127.0.0.1:8765') as client:
                self.assertEqual(client.post('/api/quit', json={}).status_code, 403)
                self.assertEqual(client.post('/api/quit?t=token', json={}).status_code, 403)
                hub.quit.assert_not_awaited()
                headers = {'origin': 'http://127.0.0.1:8765'}
                response = client.post('/api/quit?t=token', headers=headers, json={})
                self.assertEqual(response.status_code, 200)
                hub.quit.assert_awaited_once_with(save=True)
                response = client.post('/api/quit?t=token', headers=headers, json={'save': False})
                self.assertEqual(response.status_code, 200)
                hub.quit.assert_awaited_with(save=False)

    def test_failed_shutdown_does_not_report_success(self):
        with tempfile.TemporaryDirectory() as root:
            app = create_hub({'workspace': root, 'agents': []}, 8765, 'token')
            app.state.hub.quit = AsyncMock()
            with TestClient(app, base_url='http://127.0.0.1:8765') as client:
                response = client.post('/api/quit?t=token', headers={'origin': 'http://127.0.0.1:8765'}, json={})
                self.assertEqual(response.status_code, 500)
