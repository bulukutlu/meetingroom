"""Regression checks for the local hub's browser and filesystem boundaries."""
import asyncio
import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from meetingroom.location import Location, _ssh, list_dirs, probe
from meetingroom.server import Room, create_hub


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        app = create_hub({'workspace': str(self.root), 'agents': [{'name': 'one', 'provider': 'mock'}]}, 8765, 'secret')
        with patch.object(Room, 'start'):
            self.room = asyncio.run(app.state.hub.open_room(['one'], Location()))
        self.agent = self.room.agents['one']
        self.client = TestClient(app, base_url='http://127.0.0.1:8765')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {'x-mr-token': 'secret'}
        self.url = self.room.base + '/internal/share'
        self.outside = self.root / 'private.txt'
        self.outside.write_text('private')
        self.room.request_approval = AsyncMock(return_value=False)

    def share(self, **body):
        return self.client.post(self.url, headers=self.headers, json={'agent': 'one', **body})

    def test_host_token_origin_and_websocket_guards(self):
        self.assertEqual(self.client.get('/api/rooms?t=secret', headers={'host': 'evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/rooms').status_code, 403)
        self.assertEqual(self.client.post(self.url, json={'agent': 'one'}).status_code, 403)
        response = self.client.post(self.url, headers={**self.headers, 'origin': 'null'}, json={'agent': 'one'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post('/api/quit?t=secret', headers={'origin': 'https://evil.example'}, json={}).status_code, 403)
        from starlette.websockets import WebSocketDisconnect
        with self.client.websocket_connect(self.room.base + '/ws?t=secret', headers={'origin': 'https://evil.example'}) as ws:
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()

    def test_outside_paths_and_symlinks_require_approval_for_single_and_folder(self):
        link = self.agent.workdir / 'escape.txt'
        link.symlink_to(self.outside)
        for body in ({'path': str(self.outside)}, {'path': str(link)}, {'files': [{'path': str(link)}]}):
            self.assertIn('denied', self.share(**body).json()['text'])
        self.assertEqual(self.room.request_approval.await_count, 3)
        self.assertEqual(self.room.shared, [])
        self.room.request_approval.return_value = True
        self.assertIn('shared screen', self.share(path=str(link)).json()['text'])

    def test_workspace_and_extra_directories_work_without_approval(self):
        p = self.agent.workdir / 'output.txt'
        p.write_text('output')
        self.assertIn('shared screen', self.share(path=str(p)).json()['text'])
        self.agent.spec['add_dirs'] = [str(self.root)]
        self.assertIn('shared screen', self.share(path=str(self.outside)).json()['text'])
        self.room.request_approval.assert_not_awaited()

    def test_ssh_cannot_read_local_paths_even_in_auto_mode(self):
        self.room.location.kind = 'ssh'
        self.agent.approval = 'auto'
        for body in ({'path': str(self.outside)}, {'files': [{'path': str(self.outside)}]}):
            self.assertIn('must upload', self.share(**body).json()['text'])
        for content in ('', base64.b64encode(b'hello').decode()):
            self.assertIn('shared screen', self.share(path='remote.txt', content_b64=content).json()['text'])
        self.assertIn('bad upload', self.share(path='remote.txt', content_b64='%%%').json()['text'])

    def test_shared_page_credentials_are_file_scoped_and_not_persisted(self):
        p = self.agent.workdir / 'page.html'
        p.write_text('<script>document.body.textContent=location.href</script>')
        self.share(path=str(p))
        item = self.room.snapshot()['shared'][-1]
        fid, credential = item['id'], item['file_token']
        url = self.room.base + '/files/' + fid
        response = self.client.get(url + '?t=secret')
        self.assertNotIn('secret', str(response.url))
        self.assertIn('sandbox allow-scripts', response.headers['content-security-policy'])
        self.assertNotIn('allow-same-origin', response.headers['content-security-policy'])
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
        self.assertEqual(self.client.get(url + '?f=' + credential).status_code, 200)
        self.assertEqual(self.client.get(url + '?f=wrong').status_code, 403)
        self.assertEqual(self.client.get('/api/rooms?t=' + credential).status_code, 403)
        self.assertEqual(self.client.post(self.url, headers={'x-mr-token': credential}, json={'agent':'one'}).status_code, 403)
        other = self.room.base + '/files/another?f=' + credential
        self.assertEqual(self.client.get(other).status_code, 403)
        self.assertNotIn('file_token', self.room.shared[-1])
        checkpoint = (self.room.session_dir / 'room.json').read_text()
        self.assertNotIn(credential, checkpoint)

    def test_unknown_active_files_download_instead_of_executing(self):
        p = self.agent.workdir / 'page.xhtml'
        p.write_text('<html xmlns="http://www.w3.org/1999/xhtml"><script>alert(1)</script></html>')
        self.share(path=str(p))
        fid = self.room.shared[-1]['id']
        response = self.client.get(self.room.base + '/files/' + fid + '?t=secret')
        self.assertEqual(response.headers['content-type'], 'application/octet-stream')
        self.assertTrue(response.headers['content-disposition'].startswith('attachment;'))


class SSHInjectionTests(unittest.TestCase):
    def test_option_injection_is_rejected_before_launch(self):
        with patch('meetingroom.location.subprocess.run') as run:
            for host in ('-oProxyCommand=touch /tmp/pwned', '-V', 'host\nother', '$(id)', 'host;id'):
                with self.assertRaises(ValueError):
                    _ssh(host, 'pwd')
                self.assertIn('error', list_dirs('~', host))
                self.assertFalse(probe(host, '~')['ok'])
                loc = Location(kind='ssh', host=host)
                with self.assertRaises(ValueError):
                    loc.connect(8765, 'secret')
                with self.assertRaises(ValueError):
                    loc.ssh_argv('one', 8765, 'codex', [], 'API_KEY')
            run.assert_not_called()

    def test_normal_hosts_and_shell_quoted_paths(self):
        import shlex
        for host in ('my-alias', 'alice@example.com', '127.0.0.1', '::1', 'alice@[::1]'):
            # Bare IPv6 is a valid ssh destination as well as user@[IPv6].
            loc = Location(kind='ssh', host=host, path="/tmp/project'; touch /tmp/pwned; '")
            cmd = loc.ssh_argv('one', 8765, '/usr/bin/codex', ['--model', 'a;id'], 'API_KEY')
            self.assertEqual(cmd[-2], host)
            self.assertIn('cd -- ' + shlex.quote(loc.path), shlex.split(cmd[-1])[-1])
